"""Signal mantiqi.

Majburiy (bularsiz signal bo'lmaydi):
  1. Narx istalgan talab hududiga tekkan: FVG, Order Block, Support, Fibonacci OTE yoki
     katta likvidlik olingan joy — "bank buy zonasi" (1W / 1D / 4H — qaysi biri bo'lsa ham).
  2. Kichik timeframe'da (5m/10m/15m) BOS yoki CHoCH tasdig'i.
  3. Likvidlik olingan (sweep) va CHoCH/BOS undan keyin bo'lgan (REQUIRE_SWEEP).
  4. Oxirgi TP kamida 1:3 RR. Kirish — zona tepasi, stop — zona ostida (treyder modeli):
     TP1 yaqin qarshilik (qisman foyda), TP2 likvidlikdan oldin, TP3 ≥ 1:3.

Qolgani — sabablar. Kamida MIN_REASONS ta sabab bir vaqtda mos kelsa, signal chiqadi.
Majburiy shartlarning o'zi ham sabab hisoblanadi (zona + tasdiq = 2 ta sabab).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

import config as cfg
from data import resample
from liquidity import find_pools, swept_zones
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
    stop_reason: str = ""        # stop nima ostiga qo'yilgani (xabarda ko'rsatiladi)

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
        if z.note == "swept":
            text += ", ostidagi stoplar olindi (sweep)"
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


def _trend_4h(frames: dict, price: float) -> str | None:
    """4H trend yuqoriga bo'lsa — sabab matni, pasayishda bo'lsa — None (buy yo'q).

    Yuqoriga: narx 4H EMA50 ustida va EMA50 ko'tarilmoqda, YOKI so'nggi kunlarda 4H da bullish
    sinish (CHoCH/BOS) bo'lgan — ya'ni pasayish trendi buzilgan.
    """
    e50 = ema(frames["4H"]["close"], 50)
    if price > float(e50.iloc[-1]) and float(e50.iloc[-1]) > float(e50.iloc[-7]):
        return "4H trend yuqoriga (narx EMA50 ustida, EMA50 ko'tarilmoqda)"
    f4 = frames["4H"]
    since = f4.index[-min(cfg.TREND_CHOCH_4H_BARS, len(f4))]
    b = bullish_break(f4, "4H", cfg.SWING_LEN, since)
    if b is not None:
        return f"4H {b.kind} — trend yuqoriga burildi ({fmt(b.level)} sindirildi)"
    return None


def _liquidity_ok(z: Zone, touch_low: float, price: float) -> bool:
    """3+ marta tegilgan support faqat sweep'dan keyin (narx ostiga tushib, qaytib chiqqan) hisoblanadi."""
    if z.kind != "SR" or z.touches < cfg.SR_LIQUIDITY_TOUCHES:
        return True
    if touch_low < z.bottom < price:
        z.note = "swept"
        return True
    return False


def _sweep(active: list[Zone], touch_low: float, price: float) -> Zone | None:
    """Likvidlik olinganmi: katta hovuz (PDL/PWL, swing low, teng low'lar) yoki support (2+ tegish)
    ostiga tushilib, narx qaytib chiqqan bo'lsa — o'sha zona, aks holda None."""
    for z in active:
        if z.kind == "LIQ":
            return z
    for z in active:
        if z.kind == "SR" and z.touches >= 2 and touch_low < z.bottom < price:
            z.note = "swept"
            return z
    return None


def _sell_side_levels(frames: dict, zones: list[Zone]) -> list[tuple[float, str]]:
    """Stoplar to'planadigan darajalar: PDL/PWL, 1D/4H/1H swing low'lar, teng low'lar, ko'p tegilgan support."""
    out = [(p.level, p.name) for p in find_pools(frames, cfg.SWING_LEN)]
    out += [(z.bottom, f"{z.tf} support ({z.touches} marta tegilgan)")
            for z in zones if z.kind == "SR" and z.side == "bull" and z.touches >= 2]
    # 1H swing low'lar (15m dan yasaladi) — kichik, lekin hammaga ko'rinadigan stop joylari
    h1 = resample(frames["15m"], "1h")
    if len(h1) > 2 * cfg.SWING_LEN + 2:
        _, sl = swing_points(h1, cfg.SWING_LEN)
        recent = h1.index >= h1.index[-1] - pd.Timedelta(hours=cfg.STOP_POOLS_1H_HOURS)
        out += [(float(v), "1H swing low") for v in h1["low"].to_numpy()[sl & recent]]
    return out


def _demand_below(frames: dict, zones: list[Zone], ceiling: float, atr4h: float) -> list[Zone]:
    """Narx ostidagi to'ldirilmagan bullish FVG/OB (4H/1D/1W) — narx ularni to'ldirib qaytishi mumkin.

    Zonaning to'ldirilgan qismi olib tashlanadi: tepa = yaratilgandan keyingi eng past narx.
    """
    out: list[Zone] = []
    for z in zones:
        if z.side != "bull" or z.kind not in ("FVG", "OB") or z.tf not in cfg.STOP_ZONE_TFS:
            continue
        df = frames[z.tf]
        later = df.loc[df.index > z.time, "low"].iloc[1:]  # zonani yasagan shamlardan keyin
        top = min(z.top, float(later.min())) if len(later) else z.top
        if z.bottom < top < ceiling and top - z.bottom <= cfg.ANCHOR_MAX_ATR_4H * atr4h:
            out.append(Zone(z.kind, z.side, z.tf, z.bottom, top, z.time, z.touches, z.flipped, z.note))
    return out


def _protect_stop(stop: float, reason: str, levels: list[tuple[float, str]], demand: list[Zone],
                  ceiling: float, atr4h: float) -> tuple[float | None, str, Zone | None]:
    """Stop likvidlik yoki to'ldirilmagan FVG/OB ichida/yonida qolmasin — aks holda uni "ovlashadi".

    - Stopdan LIQ_NEAR_STOP_ATR_4H masofadagi low (PDL/PWL, 1D/4H/1H swing low, EQL) ostiga tushadi.
    - Stop to'ldirilmagan 4H/1D/1W FVG/OB ichida yoki uning tepasiga yaqin bo'lsa — zona ostiga tushadi:
      narx FVG ni to'ldirib qaytishi mumkin.
    - Bu ZANJIR bo'lib takrorlanadi, lekin boshlang'ich stopdan STOP_MAX_PUSH_ATR_4H dan uzoqqa emas —
      undan uzoq kerak bo'lsa stop None (bu kirishdan xavfsiz savdo yo'q).
    - Qaytaradi: (stop yoki None, sabab, stop surilgan eng yuqori FVG/OB).
    16-oktabr LINK: stop 12.415 aynan 1H low 12.414 da, ostida 4H FVG 12.15–12.35 to'ldirilmagan edi.
    """
    near_d = cfg.LIQ_NEAR_STOP_ATR_4H * atr4h
    below = cfg.STOP_BELOW_LOW_ATR_4H * atr4h
    floor = stop - cfg.STOP_MAX_PUSH_ATR_4H * atr4h  # stop bundan pastga surilmaydi
    first_zone: Zone | None = None
    for _ in range(12):
        cands = [(lvl - below, f"likvidlik ostida: {name} — {fmt(lvl)} (stop ovlanmasligi uchun)", None)
                 for lvl, name in levels if stop - near_d < lvl < ceiling and lvl - below < stop]
        cands += [(z.bottom - cfg.STOP_BELOW_ZONE_ATR_4H * atr4h,
                   f"{z.label()} ({fmt(z.bottom)} – {fmt(z.top)}) ostida — narx FVG/OB ni to'ldirib qaytishi mumkin", z)
                  for z in demand if z.bottom - cfg.STOP_BELOW_ZONE_ATR_4H * atr4h < stop < z.top + near_d]
        if not cands:
            break
        new_stop, new_reason, z = min(cands, key=lambda c: c[0])
        if z is not None and (first_zone is None or z.top > first_zone.top):
            first_zone = z
        if new_stop < floor:
            return None, new_reason, first_zone  # xavfsiz stop juda uzoq — bu kirishdan savdo yo'q
        stop, reason = new_stop, new_reason
    return stop, reason, first_zone


def _plan(entry: float, stop: float | None, frames: dict, zones: list[Zone], atr4h: float) -> list | None:
    """Kirish/stop uchun TP'lar; 1W/1D taklif zonasi 1R ichida bo'lsa yoki 1:3 maqsad yo'q bo'lsa — None."""
    if stop is None or stop >= entry:
        return None
    risk = entry - stop
    for z in zones:
        if z.side == "bear" and z.tf in cfg.BLOCKING_TFS and (
            z.bottom <= entry < z.top or entry < z.bottom < entry + cfg.BLOCK_WITHIN_R * risk
        ):
            return None
    targets = _targets(entry, stop, frames, zones, merge_tol=0.25 * atr4h, frontrun=cfg.FRONTRUN_ATR_4H * atr4h)
    return targets or None


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

    # Ko'p (3+) marta tegilgan support — kuchli zona emas, ostida stoplar to'plangan likvidlik.
    # Bunday zona faqat narx uning ostiga tushib (stoplarni olib) qaytib chiqqandan keyin hisoblanadi.
    active = [z for z in active if _liquidity_ok(z, touch_low, price)]
    if not active:
        return None

    # Klassik SMC modeli: avval likvidlik olinadi (sweep), keyin CHoCH, keyin kirish.
    swept = _sweep(active, touch_low, price)
    if cfg.REQUIRE_SWEEP and swept is None:
        return None
    sweep_time = frames["5m"].loc[frames["5m"].index >= first_touch, "low"].idxmin()

    # 3) MAJBURIY: 5m/10m/15m da BOS yoki CHoCH (zonaga tekkandan keyin)
    since = max(first_touch, frames["5m"].index[-1] - pd.Timedelta(hours=cfg.BREAK_LOOKBACK_HOURS))
    breaks = [b for tf in cfg.LTF_TIMEFRAMES if (b := bullish_break(frames[tf], tf, cfg.SWING_LEN, since))]
    if cfg.REQUIRE_SWEEP:
        breaks = [b for b in breaks if b.time > sweep_time]  # CHoCH/BOS sweep'dan KEYIN bo'lishi shart
    if not breaks:
        return None

    # 4H trend filtri: pasayish trendida buy yo'q (faqat 4H CHoCH dan keyin)
    trend_reason = _trend_4h(frames, price)
    if cfg.REQUIRE_4H_UPTREND and trend_reason is None:
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
    stop_reason = "zona reaksiyasining eng past nuqtasi ostida"
    if anchor is not None:
        stop = min(stop, anchor.bottom - cfg.STOP_BELOW_ZONE_ATR_4H * atr4h)
        stop_reason = f"{anchor.label()} ({fmt(anchor.bottom)} – {fmt(anchor.top)}) ostida"

    levels = _sell_side_levels(frames, zones)
    demand = _demand_below(frames, zones, touch_low, atr4h)
    stop, stop_reason, deeper = _protect_stop(stop, stop_reason, levels, demand, touch_low, atr4h)
    entry_note = None
    targets = _plan(entry, stop, frames, zones, atr4h)
    if targets is None and deeper is not None and price - deeper.top <= cfg.MAX_LIMIT_DIST_ATR_4H * atr4h:
        # Stop ostdagi to'ldirilmagan FVG/OB ostiga tushgach RR yetmadi — narx o'sha zonani to'ldirishi
        # kutiladi: kirish zona tepasida (limit), stop zona ostida.
        entry, limit, anchor = deeper.top, True, deeper
        stop = min(deeper.bottom - cfg.STOP_BELOW_ZONE_ATR_4H * atr4h, entry - cfg.MIN_STOP_ATR_4H * atr4h)
        stop, stop_reason, _ = _protect_stop(
            stop, f"{deeper.label()} ({fmt(deeper.bottom)} – {fmt(deeper.top)}) ostida", levels,
            [z for z in demand if z.top < deeper.bottom], entry, atr4h)
        entry_note = (f"Kirish ostdagi to'ldirilmagan {deeper.label()} da ({fmt(deeper.bottom)} – {fmt(deeper.top)}) — "
                      f"narx uni to'ldirib qaytishi kutiladi")
        targets = _plan(entry, stop, frames, zones, atr4h)
    if targets is None:
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
    if entry_note:
        reasons.append(entry_note)
    if trend_reason:
        reasons.append(trend_reason)
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
    return Signal(symbol, entry, stop, targets, active, breaks, reasons, obstacles, anchor, limit, stop_reason)


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
