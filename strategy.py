"""Signal mantiqi.

Majburiy (bularsiz signal bo'lmaydi):
  1. Narx istalgan talab hududiga tekkan: FVG, Order Block, Support, Fibonacci OTE yoki
     katta likvidlik olingan joy — "bank buy zonasi" (1W / 1D / 4H — qaysi biri bo'lsa ham).
  2. Kichik timeframe'da (5m/10m/15m) BOS yoki CHoCH tasdig'i.
  3. Oxirgi TP kamida 1:3 RR. Kirish — zona tepasi, stop — zona ostida (treyder modeli):
     TP1 yaqin qarshilik (qisman foyda), TP2 likvidlikdan oldin, TP3 ≥ 1:3.

Qolgani — sabablar. Kamida MIN_REASONS ta sabab bir vaqtda mos kelsa, signal chiqadi.
Majburiy shartlarning o'zi ham sabab hisoblanadi (zona + tasdiq = 2 ta sabab).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

import config as cfg
from liquidity import swept_zones
from smc import (Break, Zone, atr, bullish_break, ema, htf_zones, last_bullish_leg,
                 sr_zones, swing_points)


@dataclass
class Target:
    price: float
    rr: float
    reason: str


@dataclass
class Signal:
    symbol: str
    entry: float
    stop: float
    targets: list[Target]
    zones: list[Zone]
    breaks: list[Break]
    reasons: list[str] = field(default_factory=list)
    obstacles: list[Zone] = field(default_factory=list)  # TP1 gacha yo'ldagi qarshilik zonalari
    anchor: Zone | None = None   # stop qaysi zona ostiga qo'yilgan
    limit: bool = False          # kirish — zona tepasida limit buyurtma

    @property
    def score(self) -> int:
        return len(self.reasons)

    @property
    def strength(self) -> str:
        n = self.score
        return "Juda kuchli" if n >= 6 else "Kuchli" if n >= 4 else "O'rta"

    @property
    def key(self) -> str:
        # Bitta tasdiq (sinish) = bitta signal; keyingi tekshiruvlarda takrorlanmaydi
        first = min(b.time for b in self.breaks)
        return f"{self.symbol}|{first.isoformat()}"


# ------------------------------------------------------------------ yordamchilar
def _active(zones: list[Zone], ltf: pd.DataFrame, price: float, tol: float) -> list[tuple[Zone, pd.Timestamp]]:
    """Narx so'nggi soatlarda tekkan va hali ham yaqinida turgan talab (bull) hududlari."""
    recent = ltf[ltf.index >= ltf.index[-1] - pd.Timedelta(hours=cfg.ZONE_TOUCH_HOURS)]
    out = []
    for z in zones:
        if z.side != "bull":
            continue
        touched = recent[(recent["low"] <= z.top) & (recent["high"] >= z.bottom)]
        if touched.empty or price < z.bottom or price > z.top + tol:
            continue
        out.append((z, touched.index[0]))
    return out


def _targets(entry: float, stop: float, frames: dict, zones: list[Zone], merge_tol: float,
             frontrun: float) -> list[Target]:
    """TP1 — eng yaqin qarshilik (≥ MIN_TP1_RR), TP3 — birinchi ≥ MIN_RR maqsad, TP2 — ular orasida.

    High va likvidlik darajalariga TP biroz oldinroq qo'yiladi (narx ko'pincha unga yetmay qaytadi).
    Oxirgi TP 1:3 ga yetmasa — bo'sh ro'yxat (signal yo'q).
    """
    risk = entry - stop
    cands: list[tuple[float, str]] = []
    for z in zones:
        if z.side == "bear" and z.bottom > entry:
            why = f"{z.label()} ({z.touches} marta tegilgan)" if z.kind == "SR" else f"{z.label()} (to'ldirilmagan)"
            cands.append((z.bottom, why))
    for tf, name in (("1D", "PDH (oldingi kun high'i)"), ("1W", "PWH (oldingi hafta high'i)")):
        high = float(frames[tf]["high"].iloc[-1]) - frontrun
        if high > entry:
            cands.append((high, f"{name} oldidan — buy-side likvidlik"))
    for tf in cfg.HTF_TIMEFRAMES:
        df = frames[tf]
        sh, _ = swing_points(df, cfg.SWING_LEN)
        for p in df["high"].to_numpy()[sh][-15:]:
            if p - frontrun > entry:
                cands.append((float(p) - frontrun, f"{tf} swing high oldidan (likvidlik)"))
    cands.sort()
    merged: list[tuple[float, str]] = []
    for p, why in cands:  # bir-biriga juda yaqin darajalarni birlashtiramiz
        if merged and p - merged[-1][0] < merge_tol:
            continue
        merged.append((p, why))
    levels = [Target(p, (p - entry) / risk, why) for p, why in merged]
    levels = [t for t in levels if t.rr >= cfg.MIN_TP1_RR]
    final = next((t for t in levels if t.rr >= cfg.MIN_RR), None)
    if final is None:
        return []
    before = [t for t in levels if t.price < final.price]
    if not before:
        return [final]
    tp1 = before[0]
    if cfg.MAX_TARGETS < 2:
        return [final]
    # TP2 faqat haqiqiy oraliq daraja bo'lsa (TP1 va oxirgi TP dan kamida MIN_TP_GAP_R uzoqda)
    gap = cfg.MIN_TP_GAP_R
    middle = [t for t in before[1:] if t.rr - tp1.rr >= gap and final.rr - t.rr >= gap]
    if not middle or cfg.MAX_TARGETS < 3:
        return [tp1, final]
    mid_rr = (tp1.rr + final.rr) / 2
    tp2 = min(middle, key=lambda t: abs(t.rr - mid_rr))
    return [tp1, tp2, final]


def _anchor_zone(active: list[Zone], atr4h: float) -> Zone | None:
    """Stop qo'yiladigan zona: tor (≤ ANCHOR_MAX_ATR_4H) FVG/OB/support; kichik TF va tor zona afzal."""
    cands = [z for z in active if z.kind in ("FVG", "OB", "SR")
             and z.top - z.bottom <= cfg.ANCHOR_MAX_ATR_4H * atr4h]
    if not cands:
        return None
    order = {"4H": 0, "1D": 1, "1W": 2}
    return min(cands, key=lambda z: (order.get(z.tf, 3), z.top - z.bottom))


def _zone_reason(z: Zone, active: list[Zone]) -> str:
    text = f"{z.label()} ({fmt(z.bottom)} – {fmt(z.top)})"
    if z.kind == "LIQ":
        return (f"{z.label()} ({fmt(z.top)}) — stoplar {fmt(z.bottom)} gacha urilib, "
                f"narx qaytib chiqdi (bank buy zonasi)")
    if z.kind == "SR":
        text += f" — {z.touches} marta tegilgan"
        if z.flipped:
            text += ", S/R flip (eski resistance endi support)"
    if z.kind == "OTE" and any(o.kind in ("FVG", "OB") and o.bottom <= z.top and o.top >= z.bottom for o in active):
        text += " — FVG/OB bilan ustma-ust (golden zone)"
    return text


def _rejection(frames: dict, since: pd.Timestamp, zone_top: float) -> str | None:
    """Zonada uzun pastki soyali rad etish shami (pin bar)."""
    for tf in ("15m", "5m"):
        d = frames[tf][frames[tf].index >= since]
        body = (d["close"] - d["open"]).abs()
        lower = d[["open", "close"]].min(axis=1) - d["low"]
        rng = d["high"] - d["low"]
        hit = d[(lower >= 2 * body) & (lower >= 0.5 * rng) & (d["low"] <= zone_top) & (rng > 0)]
        if not hit.empty:
            return f"{tf} da kuchli rad etish shami (uzun pastki soya)"
    return None


def _liquidity_sweep(frames: dict, since: pd.Timestamp, touch_low: float, price: float, active: list[Zone]) -> str | None:
    """Narx oldingi low yoki support ostidagi stoplarni urib, qaytib yuqoriga chiqdi."""
    d15 = frames["15m"]
    before = d15[d15.index < since]
    if len(before) > 2 * cfg.SWING_LEN + 2:
        _, sl = swing_points(before, cfg.SWING_LEN)
        lows = before["low"].to_numpy()[sl]
        if len(lows) and touch_low < lows[-1] < price:
            return f"Likvidlik olindi: 15m oldingi low ({fmt(lows[-1])}) urilib, narx qaytdi"
    for z in active:
        if z.kind == "SR" and touch_low < z.bottom < price:
            return f"Likvidlik olindi: support ostidagi stoplar ({fmt(z.bottom)}) urildi (fakeout)"
    return None


def _round_number(touch_low: float, tol: float) -> str | None:
    """Narx psixologik yumaloq darajadan qaytdimi (BTC: 1 000 lik, oltin: 100 lik va h.k.)."""
    step = 10 ** (math.floor(math.log10(touch_low)) - 1)
    level = round(touch_low / step) * step
    if abs(touch_low - level) <= tol:
        return f"Psixologik yumaloq daraja ({fmt(level)}) dan qaytish"
    return None


def _deep_enough(z: Zone, touch_low: float, atr4h: float) -> bool:
    """Keng zona (> WIDE_ZONE_ATR_4H × ATR4H) uchun narx kamida uning yarmigacha (CE) tushgan bo'lishi kerak."""
    if z.kind in ("LIQ", "OTE") or z.top - z.bottom <= cfg.WIDE_ZONE_ATR_4H * atr4h:
        return True
    return touch_low <= (z.top + z.bottom) / 2


# ------------------------------------------------------------------ asosiy tahlil
def analyze(symbol: str, frames: dict[str, pd.DataFrame], price: float) -> Signal | None:
    atr4h = float(atr(frames["4H"]).iloc[-1])
    atr15 = float(atr(frames["15m"]).iloc[-1])

    # 1) Barcha hududlar: FVG/OB (1W/1D/4H), Support/Resistance (1D/4H), Fibonacci OTE (1D/4H)
    zones: list[Zone] = []
    for tf in cfg.HTF_TIMEFRAMES:
        zones += htf_zones(frames[tf], tf, cfg.MAX_ZONES_PER_TF)
    for tf in cfg.SR_TIMEFRAMES:
        zones += sr_zones(frames[tf], tf, price, cfg.SWING_LEN, cfg.SR_MIN_TOUCHES)
    for tf in cfg.FIB_TIMEFRAMES:
        leg = last_bullish_leg(frames[tf], tf, cfg.SWING_LEN)
        if leg is not None:
            zones.append(leg.to_zone())
    window_start = frames["5m"].index[-1] - pd.Timedelta(hours=cfg.ZONE_TOUCH_HOURS)
    zones += swept_zones(frames, window_start, price, merge_tol=0.1 * atr4h, n=cfg.SWING_LEN)

    # 2) MAJBURIY: narx biror talab hududiga tekkan
    active_pairs = _active(zones, frames["5m"], price, tol=0.5 * atr4h)
    if not active_pairs:
        return None
    # bir xil tur va timeframe'dagi ustma-ust hududlar bitta sabab hisoblanadi
    seen: set[tuple[str, str]] = set()
    active = []
    for z, _ in active_pairs:
        if (z.kind, z.tf) not in seen:
            seen.add((z.kind, z.tf))
            active.append(z)
    first_touch = min(t for _, t in active_pairs)
    touch_low = float(frames["5m"].loc[frames["5m"].index >= first_touch, "low"].min())

    # Keng zonaning faqat tepa chetiga tegish yetarli emas — narx zona yarmigacha (CE) tushgan bo'lishi kerak
    active = [z for z in active if _deep_enough(z, touch_low, atr4h)]
    if not active:
        return None

    # 3) MAJBURIY: 5m/10m/15m da BOS yoki CHoCH (zonaga tekkandan keyin)
    since = max(first_touch, frames["5m"].index[-1] - pd.Timedelta(hours=cfg.BREAK_LOOKBACK_HOURS))
    breaks = [b for tf in cfg.LTF_TIMEFRAMES if (b := bullish_break(frames[tf], tf, cfg.SWING_LEN, since))]
    if not breaks:
        return None

    # 4) Kirish va stop — treyder modeli: kirish zona tepasida, stop zona OSTIDA.
    #    Zona 4H/1D/1W dan olingan, shuning uchun stop 5m shovqiniga emas, zonaga va 4H ATR ga bog'lanadi.
    anchor = _anchor_zone(active, atr4h)
    entry, limit = price, False
    if anchor is not None and price > anchor.top:
        entry, limit = anchor.top, True  # narx zonadan biroz chiqib ketgan — zona tepasida limit kirish
    structural_low = min(touch_low, min(b.pullback_low for b in breaks))
    stop = min(structural_low - cfg.STOP_BELOW_LOW_ATR_4H * atr4h,
               entry - cfg.MIN_STOP_ATR_4H * atr4h)
    if anchor is not None:
        stop = min(stop, anchor.bottom - cfg.STOP_BELOW_ZONE_ATR_4H * atr4h)
    if stop >= entry:
        return None
    risk = entry - stop

    # Katta TF taklif zonasi (1W/1D) yaqin tepada yoki narx uning ichida bo'lsa — buy qilinmaydi
    for z in zones:
        if z.side == "bear" and z.tf in cfg.BLOCKING_TFS and (
            z.bottom <= entry < z.top or entry < z.bottom < entry + cfg.BLOCK_WITHIN_R * risk
        ):
            return None

    # 5) MAJBURIY: TP1 yaqin qarshilik, TP2 likvidlikdan oldin, oxirgi TP RR >= 1:3
    targets = _targets(entry, stop, frames, zones, merge_tol=0.25 * atr4h, frontrun=cfg.FRONTRUN_ATR_4H * atr4h)
    if not targets:
        return None

    # 6) Sabablar — har biri 1 ta
    reasons = [_zone_reason(z, active) for z in sorted(active, key=lambda z: cfg.HTF_TIMEFRAMES.index(z.tf))]
    kinds = sorted({b.kind for b in breaks}, reverse=True)  # CHoCH birinchi
    tfs = ", ".join(b.tf for b in breaks)
    reasons.append(f"{' / '.join(kinds)} tasdig'i ({tfs})")
    if len(breaks) >= 2 and any(b.tf == "15m" for b in breaks):  # 10m 5m dan yasaladi, 15m mustaqil
        reasons.append("Bir nechta timeframe'da tasdiq")
    major_liq = any(z.kind == "LIQ" for z in active)
    if major_liq and any(b.kind == "CHoCH" for b in breaks):
        reasons.append("Klassik SMC modeli: likvidlik olindi → CHoCH (katta o'yinchilar xarid qildi)")
    zone_top = max(z.top for z in active)
    for extra in (
        None if major_liq else _liquidity_sweep(frames, first_touch, touch_low, price, active),
        _rejection(frames, first_touch, zone_top),
        _round_number(touch_low, 0.3 * atr15),
    ):
        if extra:
            reasons.append(extra)
    if price > float(ema(frames["4H"]["close"], 50).iloc[-1]):
        reasons.append("Narx 4H EMA50 dan yuqorida (trend yuqoriga)")
    d = frames["1D"].iloc[-30:]
    lo, hi = d["low"].min(), d["high"].max()
    if hi > lo and price < lo + 0.5 * (hi - lo):
        reasons.append("Narx 1D diapazonning arzon (discount) qismida")

    if len(reasons) < cfg.MIN_REASONS:
        return None
    obstacles = sorted(
        (z for z in zones if z.side == "bear" and entry < z.bottom < targets[0].price),
        key=lambda z: z.bottom,
    )
    return Signal(symbol, entry, stop, targets, active, breaks, reasons, obstacles, anchor, limit)


def fmt(x: float) -> str:
    """Narxni koinga mos aniqlikda formatlash (BTC 65 432.1, LINK 12.873, XRP 1.3742)."""
    if x >= 1000:
        s = f"{x:,.1f}"
    elif x >= 100:
        s = f"{x:,.2f}"
    elif x >= 10:
        s = f"{x:,.3f}"
    elif x >= 1:
        s = f"{x:,.4f}"
    else:
        s = f"{x:.5f}"
    return s.replace(",", " ")
