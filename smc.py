"""Smart Money Concepts: swing nuqtalar, FVG, Order Block, BOS / CHoCH.

Hamma funksiyalar faqat YOPILGAN shamlar bilan ishlaydi.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Zone:
    kind: str          # "FVG", "OB", "SR" (support/resistance) yoki "OTE" (Fibonacci)
    side: str          # "bull" (talab / support) yoki "bear" (taklif / resistance)
    tf: str
    bottom: float
    top: float
    time: pd.Timestamp
    touches: int = 0   # SR: zonaga necha marta tegilgan
    flipped: bool = False  # SR: rol almashgan (eski resistance -> support yoki aksincha)
    note: str = ""     # LIQ: qaysi likvidlik hovuzi olingani (PDL, EQL ...)

    @property
    def key(self) -> str:
        return f"{self.tf}-{self.kind}-{self.side}-{int(self.time.timestamp())}"

    def label(self) -> str:
        if self.kind == "SR":
            return f"{self.tf} {'support' if self.side == 'bull' else 'resistance'} zonasi"
        if self.kind == "OTE":
            return f"{self.tf} Fibonacci OTE 0.618–0.786"
        if self.kind == "LIQ":
            return f"Likvidlik olindi: {self.note}"
        side = "bullish" if self.side == "bull" else "bearish"
        kind = "FVG" if self.kind == "FVG" else "Order Block"
        return f"{self.tf} {side} {kind}"


@dataclass
class Break:
    kind: str          # "CHoCH" yoki "BOS"
    tf: str
    level: float       # sindirilgan swing high
    time: pd.Timestamp
    pullback_low: float  # sindirishdan oldingi eng past nuqta (stop shu ostiga)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=1).mean()


def swing_points(df: pd.DataFrame, n: int = 2) -> tuple[np.ndarray, np.ndarray]:
    """Fractal swing high/low: ikki tomonida n tadan sham undan past/baland."""
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    size = len(df)
    sh = np.zeros(size, bool)
    sl = np.zeros(size, bool)
    for i in range(n, size - n):
        win_h = h[i - n: i + n + 1]
        win_l = l[i - n: i + n + 1]
        if h[i] == win_h.max() and h[i] > h[i - n: i].max():
            sh[i] = True
        if l[i] == win_l.min() and l[i] < l[i - n: i].min():
            sl[i] = True
    return sh, sl


# ------------------------------------------------------------------ zonalar
def find_fvgs(df: pd.DataFrame, tf: str, min_atr: float = 0.15) -> list[Zone]:
    """To'ldirilmagan Fair Value Gap'lar.

    Bullish FVG: 1-sham high < 3-sham low. Keyin biror sham zona ostida YOPILSA — bekor.
    Bearish FVG: 1-sham low > 3-sham high. Keyin biror sham zona ustida YOPILSA — bekor.
    """
    H, L, C = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    a = atr(df).to_numpy()
    zones: list[Zone] = []
    for i in range(2, len(df)):
        later_close = C[i + 1:]
        if L[i] > H[i - 2] and (L[i] - H[i - 2]) >= min_atr * a[i]:
            bottom, top = H[i - 2], L[i]
            if not (later_close < bottom).any():
                zones.append(Zone("FVG", "bull", tf, bottom, top, df.index[i - 1]))
        if H[i] < L[i - 2] and (L[i - 2] - H[i]) >= min_atr * a[i]:
            bottom, top = H[i], L[i - 2]
            if not (later_close > top).any():
                zones.append(Zone("FVG", "bear", tf, bottom, top, df.index[i - 1]))
    return zones


def find_order_blocks(df: pd.DataFrame, tf: str, impulse_atr: float = 1.5, look: int = 3) -> list[Zone]:
    """Order Block: kuchli impuls oldidagi oxirgi qarama-qarshi sham.

    Bullish OB: tushuvchi sham, keyingi `look` sham ichida narx impuls bilan ko'tarilib
    oldingi 10 shamning eng balandidan yuqorida yopiladi (struktura sinishi).
    """
    O, H, L, C = (df[c].to_numpy() for c in ["open", "high", "low", "close"])
    a = atr(df).to_numpy()
    zones: list[Zone] = []
    for i in range(10, len(df) - 1):
        nxt = slice(i + 1, min(i + 1 + look, len(df)))
        if len(C[nxt]) == 0:
            continue
        later_close = C[i + 1:]
        # bullish OB
        if C[i] < O[i]:
            move = H[nxt].max() - L[i]
            if move >= impulse_atr * a[i] and C[nxt].max() > H[i - 10: i].max():
                if not (later_close < L[i]).any():
                    zones.append(Zone("OB", "bull", tf, L[i], H[i], df.index[i]))
        # bearish OB
        if C[i] > O[i]:
            move = H[i] - L[nxt].min()
            if move >= impulse_atr * a[i] and C[nxt].min() < L[i - 10: i].min():
                if not (later_close > H[i]).any():
                    zones.append(Zone("OB", "bear", tf, L[i], H[i], df.index[i]))
    return zones


def htf_zones(df: pd.DataFrame, tf: str, keep: int = 6) -> list[Zone]:
    """Har tur (FVG/OB) va yo'nalishdan eng yangi `keep` tasini qaytaradi."""
    out: list[Zone] = []
    for zones in (find_fvgs(df, tf), find_order_blocks(df, tf)):
        for side in ("bull", "bear"):
            picked = [z for z in zones if z.side == side]
            out.extend(sorted(picked, key=lambda z: z.time)[-keep:])
    return out


# ------------------------------------------------------------ struktura
def bullish_break(df: pd.DataFrame, tf: str, n: int, since: pd.Timestamp) -> Break | None:
    """`since` dan keyin yuz bergan eng so'nggi bullish BOS yoki CHoCH.

    Trend holati shamma-sham kuzatiladi:
    - Yopilish oxirgi sinmagan swing low ostida -> trend pastga (bearish).
    - Yopilish oxirgi sinmagan swing high ustida -> bullish sinish:
      trend pastga bo'lgan bo'lsa — CHoCH (xarakter o'zgarishi), aks holda — BOS.
    - Stop uchun pullback low: `since` (zonaga tegish) dan sinishgacha bo'lgan eng past nuqta.
    - Sinishdan keyin narx shu low ostida yopilsa — sinish bekor.
    """
    H, L, C = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    sh, sl = swing_points(df, n)
    trend: str | None = None
    ref_high = ref_low = None  # sinmagan oxirgi swing darajalari
    found: Break | None = None
    start = int(np.searchsorted(df.index, since))
    for j in range(len(df)):
        k = j - n - 1  # j-shamda o'ng tomoni to'liq bo'lgan swing endi tasdiqlanadi
        if k >= 0 and sh[k]:
            ref_high = H[k]
        if k >= 0 and sl[k]:
            ref_low = L[k]
        if ref_low is not None and C[j] < ref_low:
            trend, ref_low = "bear", None
        if ref_high is not None and C[j] > ref_high:
            kind = "CHoCH" if trend == "bear" else "BOS"
            if j >= start:
                pullback_low = L[min(start, j): j + 1].min()
                found = Break(kind, tf, float(ref_high), df.index[j], float(pullback_low))
            trend, ref_high = "bull", None
    if found is None:
        return None
    after = df.loc[df.index > found.time, "close"]
    if (after < found.pullback_low).any():
        return None
    return found


def sr_zones(df: pd.DataFrame, tf: str, price: float, n: int = 2, min_touches: int = 2,
             lookback: int = 150, tol_atr: float = 0.5) -> list[Zone]:
    """Support / Resistance zonalari: bir xil darajada bir necha marta to'xtagan swing nuqtalar.

    - Swing high va low'lar narx bo'yicha guruhlanadi (bir-biridan 0.5 ATR dan yaqin bo'lsa).
    - Kamida `min_touches` ta tegish bo'lgan guruh — zona (chiziq emas, oraliq).
    - Narxdan pastda yoki narx ichida bo'lsa — support, tepada bo'lsa — resistance.
    - Zona asosan swing high'lardan iborat bo'lib, endi narx ostida qolgan bo'lsa — S/R flip.
    """
    d = df.iloc[-lookback:]
    H, L = d["high"].to_numpy(), d["low"].to_numpy()
    a = float(atr(d).iloc[-1])
    sh, sl = swing_points(d, n)
    pts = [(H[i], "high", i) for i in np.flatnonzero(sh)] + [(L[i], "low", i) for i in np.flatnonzero(sl)]
    pts.sort()
    clusters: list[list[tuple]] = []
    for p in pts:
        if clusters and p[0] - clusters[-1][0][0] <= tol_atr * a:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    zones: list[Zone] = []
    for c in clusters:
        if len(c) < min_touches:
            continue
        levels = [p[0] for p in c]
        bottom, top = min(levels), max(levels)
        if top - bottom < 0.2 * a:  # juda ingichka bo'lsa, zona qilib kengaytiramiz
            mid = (top + bottom) / 2
            bottom, top = mid - 0.1 * a, mid + 0.1 * a
        side = "bull" if bottom <= price else "bear"
        highs = sum(1 for p in c if p[1] == "high")
        flipped = (side == "bull" and highs > len(c) / 2) or (side == "bear" and highs < len(c) / 2)
        last = d.index[max(p[2] for p in c)]
        zones.append(Zone("SR", side, tf, float(bottom), float(top), last, len(c), flipped))
    return zones


@dataclass
class FibLeg:
    tf: str
    low: float     # 1.0 darajasi (impuls boshlanishi)
    high: float    # 0.0 darajasi (impuls cho'qqisi)
    time: pd.Timestamp | None = None  # cho'qqi vaqti

    def to_zone(self) -> Zone:
        lo, hi = self.ote
        return Zone("OTE", "bull", self.tf, lo, hi, self.time)

    def level(self, r: float) -> float:
        """Retracement darajasi: 0 = high, 1 = low (TradingView'da low -> high chizilganidek)."""
        return self.high - r * (self.high - self.low)

    @property
    def ote(self) -> tuple[float, float]:
        """OTE zonasi (0.786 ... 0.618) — pastki va yuqori chegara."""
        return self.level(0.786), self.level(0.618)


def last_bullish_leg(df: pd.DataFrame, tf: str, n: int = 2, lookback: int = 40) -> FibLeg | None:
    """Oxirgi bullish impuls (0 = cho'qqi, 1 = impuls boshlanishi).

    - Cho'qqi: oxirgi `lookback` shamdagi eng baland swing high
      (pullback paytidagi kichik lower high'lar e'tiborga olinmaydi).
    - Boshlanish: cho'qqidan oldingi `lookback` sham ichidagi eng past nuqta
      (impuls aynan shu yerdan boshlangan).
    - Shart: impuls o'zidan oldingi high'larni sindirgan (struktura yangilangan) va
      keyin narx 1.0 ostida yopilmagan bo'lishi kerak.
    """
    H, L, C = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    sh, _ = swing_points(df, n)
    highs = np.flatnonzero(sh)
    recent = highs[highs >= len(df) - lookback]
    if len(recent) == 0:
        return None
    hi = int(recent[np.argmax(H[recent])])  # oxirgi davrdagi eng baland swing high
    if H[hi] < H[hi:].max():
        return None
    start = max(0, hi - lookback)
    if hi - start < 3:
        return None
    lo = start + int(np.argmin(L[start:hi]))
    before = H[max(0, lo - lookback): lo]
    if len(before) and H[hi] <= before.max():
        return None  # oldingi high sinmagan — bu impuls emas
    if (C[hi + 1:] < L[lo]).any():
        return None  # 1.0 ostida yopilgan — oyoq bekor
    return FibLeg(tf, float(L[lo]), float(H[hi]), df.index[hi])


def ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False).mean()
