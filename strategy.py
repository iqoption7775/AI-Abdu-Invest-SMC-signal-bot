"""Signal mantiqi.

Majburiy (bularsiz signal bo'lmaydi):
  1. Narx istalgan talab hududiga tekkan: FVG, Order Block, Support, Fibonacci OTE yoki
     katta likvidlik olingan joy — "bank buy zonasi" (1W / 1D / 4H — qaysi biri bo'lsa ham).
  2. Kichik timeframe'da (5m/10m/15m) BOS yoki CHoCH tasdig'i.
  3. Risk/Reward kamida 1:3.

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


def _targets(entry: float, stop: float, frames: dict, zones: list[Zone], merge_tol: float) -> list[Target]:
    risk = entry - stop
    cands: list[tuple[float, str]] = []
    for z in zones:
        if z.side == "bear" and z.bottom > entry:
            why = f"{z.label()} ({z.touches} marta tegilgan)" if z.kind == "SR" else f"{z.label()} (to'ldirilmagan)"
            cands.append((z.bottom, why))
    for tf, name in (("1D", "PDH (oldingi kun high'i)"), ("1W", "PWH (oldingi hafta high'i)")):
        high = float(frames[tf]["high"].iloc[-1])
        if high > entry:
            cands.append((high, f"{name} — buy-side likvidlik"))
    for tf in cfg.HTF_TIMEFRAMES:
        df = frames[tf]
        sh, _ = swing_points(df, cfg.SWING_LEN)
        for p in df["high"].to_numpy()[sh][-15:]:
            if p > entry:
                cands.append((float(p), f"{tf} swing high (likvidlik)"))
    cands.sort()
    merged: list[tuple[float, str]] = []
    for p, why in cands:  # bir-biriga juda yaqin darajalarni birlashtiramiz
        if merged and p - merged[-1][0] < merge_tol:
            continue
        merged.append((p, why))
    out = [Target(p, (p - entry) / risk, why) for p, why in merged]
    return [t for t in out if t.rr >= cfg.MIN_RR][: cfg.MAX_TARGETS]


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


# ------------------------------------------------------------------ asosiy tahlil
def analyze(symbol: str, frames: dict[str, pd.DataFrame], price: float) -> Signal | None:
    atr4h = float(atr(frames["4H"]).iloc[-1])
    atr5 = float(atr(frames["5m"]).iloc[-1])
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

    # 3) MAJBURIY: 5m/10m/15m da BOS yoki CHoCH (zonaga tekkandan keyin)
    since = max(first_touch, frames["5m"].index[-1] - pd.Timedelta(hours=cfg.BREAK_LOOKBACK_HOURS))
    breaks = [b for tf in cfg.LTF_TIMEFRAMES if (b := bullish_break(frames[tf], tf, cfg.SWING_LEN, since))]
    if not breaks:
        return None

    # 4) Stop — tasdiqdan oldingi eng past low ostida
    stop = min(b.pullback_low for b in breaks) - cfg.STOP_BUFFER_ATR * atr5
    if stop >= price:
        return None

    # 5) MAJBURIY: TP — yuqoridagi zonalar, resistance va high'lar, RR >= 1:3
    targets = _targets(price, stop, frames, zones, merge_tol=0.25 * atr4h)
    if not targets:
        return None

    # 6) Sabablar — har biri 1 ta
    reasons = [_zone_reason(z, active) for z in sorted(active, key=lambda z: cfg.HTF_TIMEFRAMES.index(z.tf))]
    kinds = sorted({b.kind for b in breaks}, reverse=True)  # CHoCH birinchi
    tfs = ", ".join(b.tf for b in breaks)
    reasons.append(f"{' / '.join(kinds)} tasdig'i ({tfs})")
    if len(breaks) >= 2:
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
        (z for z in zones if z.side == "bear" and price < z.bottom < targets[0].price),
        key=lambda z: z.bottom,
    )
    return Signal(symbol, price, stop, targets, active, breaks, reasons, obstacles)


def fmt(x: float) -> str:
    """Narxni o'qishga qulay formatlash."""
    if x >= 1000:
        s = f"{x:,.1f}"
    elif x >= 1:
        s = f"{x:,.2f}"
    else:
        s = f"{x:.5f}"
    return s.replace(",", " ")
