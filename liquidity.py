"""Likvidlik: katta stoplar turgan joylar (sell-side liquidity) va ularning olinishi.

Katta o'yinchilar (banklar, fondlar) ulkan buy buyurtmasini to'ldirish uchun sotuvchilar kerak.
Shuning uchun narx low'lar ostiga tushiriladi: u yerdagi stop-losslar ishga tushadi, sotuvlar
yutib olinadi va narx qaytib yuqoriga ketadi. Bot shu holatni qidiradi:

  hovuz (PDL, PWL, swing low, teng low'lar) -> soya ostiga chiqdi -> narx qaytib ustida yopildi
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from data import TF_MINUTES
from smc import Zone, atr, swing_points

TF_ORDER = ["1W", "1D", "4H"]


@dataclass
class Pool:
    name: str
    level: float
    tf: str
    end: pd.Timestamp   # hovuz paydo bo'lgan sham yopilgan vaqt


def find_pools(frames: dict[str, pd.DataFrame], n: int = 2, recent: int = 6) -> list[Pool]:
    """Sell-side likvidlik hovuzlari: PDL, PWL, 1D/4H swing low'lar va teng low'lar (EQL)."""
    pools: list[Pool] = []
    d1, w1 = frames["1D"], frames["1W"]
    day, week = pd.Timedelta(minutes=TF_MINUTES["1D"]), pd.Timedelta(minutes=TF_MINUTES["1W"])
    pools.append(Pool("PDL (oldingi kun low'i)", float(d1["low"].iloc[-1]), "1D", d1.index[-1] + day))
    pools.append(Pool("PWL (oldingi hafta low'i)", float(w1["low"].iloc[-1]), "1W", w1.index[-1] + week))
    for tf in ("1D", "4H"):
        df = frames[tf]
        dur = pd.Timedelta(minutes=TF_MINUTES[tf])
        L = df["low"].to_numpy()
        _, sl = swing_points(df, n)
        idx = np.flatnonzero(sl)[-recent:]
        for i in idx:
            pools.append(Pool(f"{tf} swing low", float(L[i]), tf, df.index[i] + dur))
        # teng low'lar: bir xil darajada ikki va undan ko'p swing low — stoplar to'plami
        tol = 0.1 * float(atr(df).iloc[-1])
        for a_i, i in enumerate(idx):
            for j in idx[a_i + 1:]:
                if abs(L[i] - L[j]) <= tol:
                    pools.append(Pool(f"{tf} teng low'lar (EQL)", float(min(L[i], L[j])), tf, df.index[j] + dur))
    return pools


def _intact(pool: Pool, frames: dict, window_start: pd.Timestamp) -> bool:
    """Hovuz kuzatuv oynasigacha hali olinmagan bo'lishi kerak."""
    df = frames[pool.tf]
    dur = pd.Timedelta(minutes=TF_MINUTES[pool.tf])
    htf = df[(df.index >= pool.end) & (df.index + dur <= window_start)]
    d5 = frames["5m"]
    ltf = d5[(d5.index >= pool.end) & (d5.index < window_start)]
    return not ((htf["low"] < pool.level).any() or (ltf["low"] < pool.level).any())


def swept_zones(frames: dict, window_start: pd.Timestamp, price: float, merge_tol: float, n: int = 2) -> list[Zone]:
    """Oynada olingan katta likvidlik hovuzlari — "bank buy zonasi" sifatida.

    Zona: [stop urilgan eng past nuqta, hovuz darajasi]. Bir-biriga yaqin hovuzlar birlashtiriladi.
    """
    d5 = frames["5m"]
    w = d5[d5.index >= window_start]
    if w.empty:
        return []
    found: list[tuple[Pool, float, pd.Timestamp]] = []
    for p in find_pools(frames, n):
        if p.end > window_start or not _intact(p, frames, window_start):
            continue
        hit = w[w["low"] < p.level]
        if hit.empty or price <= p.level or float(w["close"].iloc[-1]) <= p.level:
            continue  # stop urilmagan yoki narx hali qaytib chiqmagan
        found.append((p, float(hit["low"].min()), hit["low"].idxmin()))

    found.sort(key=lambda x: x[0].level)
    groups: list[list[tuple[Pool, float, pd.Timestamp]]] = []
    for item in found:
        if groups and item[0].level - groups[-1][0][0].level <= merge_tol:
            groups[-1].append(item)
        else:
            groups.append([item])
    zones: list[Zone] = []
    for g in groups:
        names = list(dict.fromkeys(p.name for p, _, _ in g))
        tf = min((p.tf for p, _, _ in g), key=TF_ORDER.index)
        top = max(p.level for p, _, _ in g)
        bottom = min(low for _, low, _ in g)
        t = min(ts for _, _, ts in g)
        zones.append(Zone("LIQ", "bull", tf, bottom, top, t, touches=len(g), note=" + ".join(names)))
    return zones
