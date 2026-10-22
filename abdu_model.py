"""Abdu modeli — treyderning o'z strategiyasi (0 dan qurilgan, 22-oktabr).

BUY setup (hammasi ketma-ket bo'lishi shart):
  1. 4H: narx tushib kelib DISCOUNT zonaga yetgan (1D diapazonning pastki qismi).
  2. Sell-side likvidlik olingan: narx oldingi 4H swing low ostiga tushib, stoplarni olib, qaytgan (sweep).
  3. Struktura o'zgargan: sweep'dan keyin 1H da oxirgi lower-high ustida yopilish (CHoCH).
  4. Shu harakat 4H bullish OB (sweep'dagi oxirgi qizil sham) va 1H bullish FVG qoldirgan.
  5. Buy zona — narx retestga qaytadigan 1H FVG yoki 4H OB (limit buyurtma).
  6. Stop — sweep low / OB ostida. TP — tepadagi likvidlik, oxirgi TP kamida 1:3.

12H / 1D / 1W — kontekst: discount darajasi va tepadagi maqsadlar (TP).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

import config as cfg
from smc import Zone, atr, find_fvgs, find_order_blocks, swing_points
from strategy import Signal, Target, fmt

H4 = pd.Timedelta(hours=4)


@dataclass
class Setup:
    """Topilgan setup (kirish usuliga bog'liq bo'lmagan qismi)."""
    sweep_time: pd.Timestamp     # sweep low bo'lgan 1H sham
    sweep_low: float
    pool: float                  # olingan likvidlik darajasi (4H swing low)
    pool_time: pd.Timestamp
    lh: float                    # 1H da sindirilgan lower-high (CHoCH darajasi)
    choch_time: pd.Timestamp
    imp_high: float              # sweep'dan keyingi impuls cho'qqisi
    ob: Zone | None              # 4H bullish OB
    fvg: Zone | None             # 1H bullish FVG (hali retest qilinmagan)
    fvg_touched: bool            # FVG ga narx allaqachon qaytganmi
    ob_touched: bool
    disc: float                  # sweep low 1D diapazonning qayerida (0 — tub, 1 — tepa)
    atr4h: float

    @property
    def key_time(self) -> str:
        return self.sweep_time.isoformat()


def detect(frames: dict[str, pd.DataFrame]) -> Setup | None:
    """Oxirgi (eng yangi) setup — topilmasa None. Faqat yopilgan shamlar beriladi."""
    f4, h1 = frames["4H"], frames["1H"]
    n = cfg.AM_SWING_N
    if len(f4) < 60 or len(h1) < 60:
        return None
    a4 = float(atr(f4).iloc[-1])
    L, C = f4["low"].to_numpy(), f4["close"].to_numpy()
    _, sl4 = swing_points(f4, n)
    N = len(f4)

    # 1) Sweep: oxirgi AM_SWEEP_LOOKBACK_4H sham ichida oldingi (olinmagan) 4H swing low ostiga tushish.
    #    Sweep low o'shandan beri eng past nuqta bo'lib qolishi va narx hovuz ustida yopilgan bo'lishi kerak.
    found = None
    for j in range(N - 1, max(n + 2, N - cfg.AM_SWEEP_LOOKBACK_4H) - 1, -1):
        if L[j] > L[j:].min():
            continue
        for k in range(j - n - 1, max(0, j - cfg.AM_POOL_LOOKBACK_4H) - 1, -1):
            if not sl4[k] or L[k] <= L[j]:
                continue
            broke = np.flatnonzero(L[k + 1:j + 1] < L[k])
            if len(broke) and k + 1 + int(broke[0]) < j - cfg.AM_SWEEP_SPAN_4H:
                continue  # bu hovuz ancha oldin olingan — bu sweep emas, pasayish davomi
            if (C[j:] > L[k]).any():
                found = (j, k)
            break
        if found:
            break
    if found is None:
        return None
    j, k = found
    pool, sweep_low = float(L[k]), float(L[j])

    # 2) 1H: sweep sham va undan oldingi oxirgi lower-high
    hi_, lo_, cl_ = h1["high"].to_numpy(), h1["low"].to_numpy(), h1["close"].to_numpy()
    t4 = f4.index[j]
    win = np.flatnonzero((h1.index >= t4) & (h1.index < t4 + H4))
    if len(win) == 0:
        return None
    p = int(win[np.argmin(lo_[win])])
    if (cl_[p:] < sweep_low).any():
        return None  # sweep low ostida yopilish — setup buzilgan
    sh1, _ = swing_points(h1.iloc[: p + 1], n)
    highs = np.flatnonzero(sh1[: max(0, p - n)])
    if len(highs) == 0:
        return None
    lh = float(hi_[highs[-1]])

    # 3) CHoCH: sweep'dan keyin 1H yopilish lower-high ustida
    after = np.flatnonzero(cl_[p + 1:] > lh)
    if len(after) == 0:
        return None
    c = p + 1 + int(after[0])
    imp = p + int(np.argmax(hi_[p:]))
    imp_high = float(hi_[imp])
    if imp > len(h1) - 1 - n:
        return None  # impuls hali davom etyapti — cho'qqi tasdiqlanib, narx retestga qayta boshlagach signal

    # 4) 4H bullish OB — sweep shamidan orqaga, oxirgi qizil sham
    O4 = f4["open"].to_numpy()
    ob = None
    for b in range(j, max(-1, j - 4), -1):
        if C[b] < O4[b]:
            ob = Zone("OB", "bull", "4H", float(L[b]), float(f4["high"].iloc[b]), f4.index[b])
            break
    ob_touched = bool(ob is not None and len(h1.index) > c + 1 and lo_[c + 1:].min() <= ob.top)

    # 5) 1H bullish FVG — sweep'dan impuls cho'qqisigacha bo'lgan harakatda, CHoCH shamiga eng yaqini
    a1 = float(atr(h1).iloc[-1])
    fvgs = []
    for i in range(p + 2, min(imp + 2, len(h1))):
        if lo_[i] > hi_[i - 2] and lo_[i] - hi_[i - 2] >= cfg.AM_FVG_MIN_ATR * a1:
            fvgs.append(i)
    fvg, fvg_touched = None, False
    if fvgs:
        i = min(fvgs, key=lambda x: abs((x - 1) - c))
        fvg = Zone("FVG", "bull", "1H", float(hi_[i - 2]), float(lo_[i]), h1.index[i - 1])
        fvg_touched = bool(i + 1 < len(h1) and lo_[i + 1:].min() <= fvg.top)

    # 6) Discount: sweep low 1D diapazonning qayerida
    d = frames["1D"].iloc[-cfg.AM_DISCOUNT_DAYS:]
    top = max(float(d["high"].max()), imp_high)
    bot = min(float(d["low"].min()), sweep_low)
    disc = (sweep_low - bot) / (top - bot) if top > bot else 0.0

    return Setup(h1.index[p], sweep_low, pool, f4.index[k], lh, h1.index[c], imp_high,
                 ob, fvg, fvg_touched, ob_touched, disc, a4)


def _targets(entry: float, stop: float, frames: dict, imp_high: float, a4: float) -> tuple[list[Target], list[Zone]]:
    """TP nomzodlari: impuls cho'qqisi, 4H/12H/1D/1W swing high'lar, PDH/PWH, to'ldirilmagan bearish FVG/OB."""
    risk = entry - stop
    front = cfg.FRONTRUN_ATR_4H * a4
    cands: list[tuple[float, str]] = [(imp_high - front, "1H impuls cho'qqisi oldidan (likvidlik)")]
    supply: list[Zone] = []
    for tf in ("4H", "12H", "1D", "1W"):
        df = frames[tf]
        sh, _ = swing_points(df, cfg.AM_SWING_N)
        for v in df["high"].to_numpy()[sh][-15:]:
            cands.append((float(v) - front, f"{tf} swing high oldidan (likvidlik)"))
        if tf != "12H":
            for z in find_fvgs(df.iloc[-300:], tf) + find_order_blocks(df.iloc[-300:], tf):
                if z.side == "bear" and z.bottom > entry:
                    supply.append(z)
                    cands.append((z.bottom, f"{z.label()} (to'ldirilmagan)"))
    cands.append((float(frames["1D"]["high"].iloc[-1]) - front, "PDH (oldingi kun high'i) oldidan"))
    cands.append((float(frames["1W"]["high"].iloc[-1]) - front, "PWH (oldingi hafta high'i) oldidan"))
    cands = sorted((p, w) for p, w in cands if p > entry)
    merged: list[tuple[float, str]] = []
    for p, w in cands:
        if merged and p - merged[-1][0] < 0.25 * a4:
            continue
        merged.append((p, w))
    levels = [Target(p, (p - entry) / risk, w) for p, w in merged if (p - entry) / risk >= cfg.MIN_TP1_RR]
    final = next((t for t in levels if t.rr >= cfg.AM_MIN_RR), None)
    if final is None:
        return [], supply
    before = [t for t in levels if t.price < final.price]
    if not before:
        return [final], supply
    tp1 = before[0]
    mid = [t for t in before[1:] if t.rr - tp1.rr >= cfg.MIN_TP_GAP_R and final.rr - t.rr >= cfg.MIN_TP_GAP_R]
    if not mid:
        return [tp1, final], supply
    tp2 = min(mid, key=lambda t: abs(t.rr - (tp1.rr + final.rr) / 2))
    return [tp1, tp2, final], supply


def build(symbol: str, s: Setup, frames: dict, price: float, entry_mode: str | None = None) -> Signal | None:
    """Setup'dan limit BUY signal. entry_mode: fvg_top | fvg_ce | ob_top (standart — config)."""
    mode = entry_mode or cfg.AM_ENTRY
    if cfg.AM_USE_DISCOUNT and s.disc > cfg.AM_DISCOUNT_MAX:
        return None
    if mode.startswith("fvg"):
        if s.fvg is None or s.fvg_touched:
            return None
        zone = s.fvg
        entry = zone.top if mode == "fvg_top" else (zone.top + zone.bottom) / 2
        where = "1H FVG tepasi" if mode == "fvg_top" else "1H FVG o'rtasi (50%)"
    else:
        if s.ob is None or s.ob_touched:
            return None
        zone, entry, where = s.ob, s.ob.top, "4H OB tepasi"
    if price <= entry:
        return None  # narx allaqachon zonada — kech
    low = min(s.sweep_low, s.ob.bottom if s.ob else s.sweep_low)
    stop = low - cfg.AM_STOP_BUF_ATR * s.atr4h
    if stop >= entry:
        return None
    risk = entry - stop
    targets, supply = _targets(entry, stop, frames, s.imp_high, s.atr4h)
    if not targets:
        return None
    if cfg.AM_BLOCK_SUPPLY_R > 0 and any(entry < z.bottom < entry + cfg.AM_BLOCK_SUPPLY_R * risk for z in supply):
        return None
    reasons = [
        f"4H: narx discount zonada — 1D {cfg.AM_DISCOUNT_DAYS} kunlik diapazonning {s.disc * 100:.0f}% qismi",
        f"Sell-side likvidlik olindi: 4H swing low {fmt(s.pool)} → {fmt(s.sweep_low)} gacha (stoplar urildi)",
        f"1H CHoCH: {fmt(s.lh)} sindirildi — struktura yuqoriga o'zgardi",
    ]
    if s.ob:
        reasons.append(f"4H bullish Order Block: {fmt(s.ob.bottom)} – {fmt(s.ob.top)}")
    if s.fvg:
        reasons.append(f"1H bullish FVG: {fmt(s.fvg.bottom)} – {fmt(s.fvg.top)}")
    reasons.append(f"Kirish: {where} — retestda (limit)")
    sig = Signal(symbol, entry, stop, targets, [z for z in (s.ob, s.fvg) if z], [], reasons, [],
                 zone, True, f"sweep low ({fmt(s.sweep_low)}) va 4H OB ostida")
    sig.setup_key = f"{symbol}|{s.key_time}"
    return sig


def analyze(symbol: str, frames: dict, price: float) -> Signal | None:
    s = detect(frames)
    return build(symbol, s, frames, price) if s else None
