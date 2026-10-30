"""Signal grafigi: 1H shamlar + kirish / stop / TP darajalari, 4H OB, 1H FVG, likvidlik va CHoCH belgilari.

Telegram'ga rasm (PNG) bo'lib yuboriladi — treyder stop va TP qayerdaligini bir qarashda ko'radi.
"""
from __future__ import annotations

import io
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config as cfg  # noqa: E402
from strategy import fmt  # noqa: E402

BG, PANEL, GRID, TEXT, MUTED = "#0f1218", "#131722", "#1f2433", "#e6e9ef", "#8b93a7"
UP, DOWN = "#26a69a", "#ef5350"
ENTRY, STOP, TP = "#4c8dff", "#ef5350", "#26a69a"
FVG_C, OB_C, LIQ_C = "#a970ff", "#ff9f1a", "#f5c542"
BARS, MAX_BARS, FUTURE = 110, 170, 30


def _x(index: pd.DatetimeIndex, t) -> float:
    """Vaqt → sham raqami (oyna boshidan)."""
    return float(np.searchsorted(index.values, pd.Timestamp(t).to_datetime64(), side="left"))


def _spread(ys: list[float], gap: float) -> list[float]:
    """Yon-yon yorliqlar ustma-ust tushmasin: kamida `gap` oraliq."""
    order = np.argsort(ys)
    out = list(ys)
    prev = -np.inf
    for i in order:
        out[i] = max(out[i], prev + gap)
        prev = out[i]
    return out


def render(sig, frames: dict | None = None) -> bytes:
    frames = frames or getattr(sig, "frames", None) or {}
    h1 = frames["1H"]
    s = getattr(sig, "setup", None)

    start = len(h1) - BARS
    if s is not None:
        start = min(start, int(_x(h1.index, s.pool_time if s.pool_time > h1.index[0] else s.sweep_time)) - 8)
    start = max(0, start, len(h1) - MAX_BARS)
    df = h1.iloc[start:]
    idx, n = df.index, len(df)
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))

    tps = [t.price for t in sig.targets]
    lo = min(float(l.min()), sig.stop)
    hi = max(float(h.max()), tps[-1] if tps else sig.entry)
    pad = (hi - lo) * 0.06
    lo, hi = lo - pad, hi + pad
    right = n + FUTURE

    fig = plt.figure(figsize=(12.8, 7.2), dpi=100, facecolor=BG)
    ax = fig.add_axes([0.035, 0.07, 0.80, 0.83], facecolor=PANEL)
    for side in ax.spines.values():
        side.set_color(GRID)
    ax.grid(color=GRID, linewidth=0.6)
    ax.set_xlim(-1, right)
    ax.set_ylim(lo, hi)
    ax.yaxis.tick_right()
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(v)))

    # Vaqt o'qi — Toshkent vaqti
    tz = ZoneInfo(cfg.TIMEZONE)
    ticks = list(range(0, n, max(1, n // 7)))
    ax.set_xticks(ticks)
    ax.set_xticklabels([idx[i].tz_convert(tz).strftime("%d.%m %H:%M") if idx[i].tzinfo else idx[i].strftime("%d.%m %H:%M")
                        for i in ticks])

    # Zonalar (sham ostida qoladi)
    future_x = n + 1
    if s is not None and s.ob is not None:
        x0 = max(0.0, _x(idx, s.ob.time))
        ax.add_patch(Rectangle((x0, s.ob.bottom), right - x0, s.ob.top - s.ob.bottom, color=OB_C, alpha=0.13, lw=0))
        ax.text(future_x + 0.8, (s.ob.top + s.ob.bottom) / 2, "4H OB", color=OB_C, fontsize=9, va="center",
                fontweight="bold", zorder=6)
    if s is not None and s.fvg is not None:
        x0 = max(0.0, _x(idx, s.fvg.time) - 1)
        ax.add_patch(Rectangle((x0, s.fvg.bottom), right - x0, s.fvg.top - s.fvg.bottom, color=FVG_C, alpha=0.20, lw=0))
        ax.text(future_x + 0.8, (s.fvg.top + s.fvg.bottom) / 2, "1H FVG", color=FVG_C, fontsize=9, va="center",
                fontweight="bold", zorder=6)

    # Pozitsiya qutisi (TradingView "long position" kabi)
    if tps:
        ax.add_patch(Rectangle((future_x, sig.entry), FUTURE - 2, tps[-1] - sig.entry, color=TP, alpha=0.16, lw=0))
    ax.add_patch(Rectangle((future_x, sig.stop), FUTURE - 2, sig.entry - sig.stop, color=STOP, alpha=0.20, lw=0))

    # Shamlar
    up = c >= o
    xs = np.arange(n)
    ax.vlines(xs, l, h, color=np.where(up, UP, DOWN), linewidth=1.0, zorder=3)
    body_lo, body_h = np.minimum(o, c), np.maximum(np.abs(c - o), (hi - lo) * 0.0012)
    for i in range(n):
        ax.add_patch(Rectangle((i - 0.33, body_lo[i]), 0.66, body_h[i], color=UP if up[i] else DOWN, lw=0, zorder=4))

    # Likvidlik va CHoCH
    if s is not None:
        xs_ = _x(idx, s.sweep_time)
        if 0 <= xs_ < n:
            xp = max(0.0, _x(idx, s.pool_time))
            ax.hlines(s.pool, xp, xs_ + 2, color=LIQ_C, linestyles=(0, (2, 2)), linewidth=1.1, zorder=5)
            ax.annotate("Likvidlik olindi", xy=(xs_, s.sweep_low), xytext=(xs_ - 2, s.sweep_low - (hi - lo) * 0.045),
                        color=LIQ_C, fontsize=9, ha="right", va="top", fontweight="bold",
                        arrowprops=dict(arrowstyle="-|>", color=LIQ_C, lw=1.1), zorder=6)
        xc = _x(idx, s.choch_time)
        if 0 <= xc < n:
            before = df.iloc[: int(xc)]
            lh_bars = np.flatnonzero(np.isclose(before["high"].to_numpy(float), s.lh, rtol=1e-6))
            xl = float(lh_bars[-1]) if len(lh_bars) else max(0.0, xc - 8)
            ax.hlines(s.lh, xl, xc, color=TEXT, linestyles=(0, (4, 3)), linewidth=1.0, zorder=5)
            ax.text((xl + xc) / 2, s.lh, "CHoCH", color=TEXT, fontsize=9, ha="center", va="bottom", fontweight="bold")

    # Darajalar: chiziq + o'ng tomonda yorliq
    risk_pct = (sig.entry - sig.stop) / sig.entry * 100
    levels = [(sig.entry, f"Kirish  {fmt(sig.entry)}", ENTRY),
              (sig.stop, f"Stop  {fmt(sig.stop)}  −{risk_pct:.1f}%", STOP)]
    for i, t in enumerate(sig.targets, 1):
        pct = (t.price - sig.entry) / sig.entry * 100
        levels.append((t.price, f"TP{i}  {fmt(t.price)}  +{pct:.1f}%", TP))
    for y, _, col in levels:
        ax.hlines(y, 0, right, color=col, linewidth=1.3 if col != TP else 1.1,
                  linestyles="solid" if col == ENTRY else (0, (5, 3)), alpha=0.95, zorder=5)
    ys = _spread([y for y, _, _ in levels], (hi - lo) * 0.045)
    for (y, label, col), yl in zip(levels, ys):
        ax.text(right - 0.6, yl, label, color="white", fontsize=10.5, ha="right", va="center", fontweight="bold",
                zorder=7, bbox=dict(boxstyle="round,pad=0.35", facecolor=col, edgecolor="none", alpha=0.95))

    # Joriy narx
    ax.hlines(c[-1], n - 1, n + 0.5, color=MUTED, linewidth=1.0, zorder=6)

    # Sarlavha va brend
    name = sig.symbol.replace("⭐ ", "")
    fig.text(0.035, 0.945, f"{name}  ·  1H  ·  BUY", color=TEXT, fontsize=17, fontweight="bold", va="center")
    fig.text(0.835, 0.945, cfg.BRAND, color=ENTRY, fontsize=13, fontweight="bold", va="center", ha="right")
    ax.text(0.5, 0.5, cfg.BRAND, transform=ax.transAxes, color="white", alpha=0.035, fontsize=60,
            fontweight="bold", ha="center", va="center", zorder=1)

    # O'ng panel: qisqa izoh (rang ma'nosi)
    legend = [("Kirish (limit)", ENTRY), ("Stop", STOP), ("Take profit", TP),
              ("1H FVG", FVG_C), ("4H Order Block", OB_C), ("Likvidlik", LIQ_C)]
    for k, (txt, col) in enumerate(legend):
        y = 0.84 - k * 0.05
        fig.patches.append(Rectangle((0.905, y - 0.012), 0.012, 0.024, transform=fig.transFigure,
                                     facecolor=col, edgecolor="none"))
        fig.text(0.922, y, txt, color=MUTED, fontsize=9.5, va="center")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
