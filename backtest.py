"""Backtest va bugungi signallar tahlili.

GitHub Actions'da qo'lda ishga tushiriladi (.github/workflows/backtest.yml).
Natija: hisobot/backtest.md

1) Bugungi signallar: stop urilgan bo'lsa — stopdan oldin narx qancha foydaga borgan (MFE),
   stopdan keyin TP ga yetganmi (stop "ovlanganmi"), kirish paytida 4H trend qanday edi.
2) Strategiyani so'nggi BACKTEST_DAYS kun tarixida har soatda (bot kabi) ishga tushirib,
   har bir variant uchun g'alaba foizi va o'rtacha R hisoblanadi.

Ma'lumot manbai: Coinbase ochiq API (5m, 15m, 1H, 1D). 4H — 1H dan, 1W — 1D dan yig'iladi.
"""
from __future__ import annotations

import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import config as cfg
import strategy
from data import resample
from smc import ema

BACKTEST_DAYS = 60
EXIT_AFTER_HOURS = 24 * 7          # shu vaqtgacha TP ham, stop ham bo'lmasa — bozor narxida yopiladi
LIMIT_FILL_HOURS = 12              # limit kirish shu vaqt ichida to'lmasa — bekor
TAIL = {"5m": 720, "10m": 360, "15m": 720, "4H": 400, "1D": 400, "1W": 200}  # Kraken ~720 sham beradi

COINBASE = {
    "⭐ BTC/USD": "BTC-USD", "⭐ ETH/USD": "ETH-USD", "SOL/USD": "SOL-USD", "XRP/USD": "XRP-USD",
    "ADA/USD": "ADA-USD", "AVAX/USD": "AVAX-USD", "LINK/USD": "LINK-USD", "DOT/USD": "DOT-USD",
    "LTC/USD": "LTC-USD", "XLM/USD": "XLM-USD", "NEAR/USD": "NEAR-USD", "ATOM/USD": "ATOM-USD",
    "ALGO/USD": "ALGO-USD",
}

# Test haftasida (17–22 oktabr, 17-okt versiya) Telegram'ga kelgan signallar. Vaqt — UTC.
# (koin, vaqt, kirish, stop, TP'lar, limit)
TODAY = [
    ("DOT/USD", "2026-10-19 17:28", 1.1440, 1.1080, [1.1972, 1.2323, 1.2596], True),
    ("XLM/USD", "2026-10-21 11:29", 0.18480, 0.18028, [0.19249, 0.19760, 0.20260], False),
    ("LINK/USD", "2026-10-21 15:32", 12.630, 12.393, [12.919, 13.156, 13.365], False),
    ("DOT/USD", "2026-10-22 00:34", 1.1246, 1.0849, [1.1736, 1.2194, 1.2601], True),
]

_KEYS = ["BTC_FILTER", "REQUIRE_SWEEP", "REQUIRE_4H_UPTREND", "SR_LIQUIDITY_TOUCHES", "LIQ_NEAR_STOP_ATR_4H",
         "LTF_TIMEFRAMES", "BLOCKING_TFS", "BTC_RANGE_FILTER", "BTC_RANGE_DAYS", "REQUIRE_15M", "MAX_ZONE_ATR_4H"]
DEFAULTS = {k: getattr(cfg, k) for k in _KEYS}

# 22-oktabr tuzatishlari (config.py da hozircha o'chiq — hozirgi bot = B varianti)
NEW_22OCT = {"BLOCKING_TFS": ["1W", "1D", "4H"], "BTC_RANGE_FILTER": True, "REQUIRE_15M": True, "MAX_ZONE_ATR_4H": 3.0}
VARIANTS = {
    "B. 17-okt versiya (hozirgi bot)": {},
    "C. Yangi — 5 ta tuzatish": NEW_22OCT,
    "D. Yangi, BTC diapazon filtrisiz": {**NEW_22OCT, "BTC_RANGE_FILTER": False},
    "E. Yangi, 15m talabisiz": {**NEW_22OCT, "REQUIRE_15M": False},
    "F. Yangi, BTC diapazoni 30 kun": {**NEW_22OCT, "BTC_RANGE_DAYS": 30},
}


# ------------------------------------------------------------------ ma'lumot
def _cb(product: str, gran: int, start: datetime, end: datetime) -> pd.DataFrame:
    rows, step = [], timedelta(seconds=gran * 300)
    t = start
    while t < end:
        t2 = min(t + step, end)
        for attempt in range(5):
            r = requests.get(f"https://api.exchange.coinbase.com/products/{product}/candles",
                             params={"granularity": gran, "start": t.isoformat(), "end": t2.isoformat()},
                             headers={"User-Agent": "AbduInvestBacktest"}, timeout=30)
            if r.status_code == 200:
                rows += r.json()
                break
            time.sleep(1 + attempt * 2)
        time.sleep(0.15)
        t = t2
    df = pd.DataFrame(rows, columns=["time", "low", "high", "open", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.drop_duplicates("time").set_index("time").sort_index()
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def load(product: str, end: datetime) -> dict[str, pd.DataFrame]:
    start = end - timedelta(days=BACKTEST_DAYS)
    m5 = _cb(product, 300, start - timedelta(days=3), end)
    m15 = _cb(product, 900, start - timedelta(days=8), end)
    h1 = _cb(product, 3600, start - timedelta(days=70), end)
    d1 = _cb(product, 86400, start - timedelta(days=1500), end)
    return {"5m": m5, "15m": m15, "4H": resample(h1, "4h"), "1D": d1,
            "1W": resample(d1, "W-MON")}


DUR = {"5m": "5min", "10m": "10min", "15m": "15min", "4H": "4h", "1D": "1D", "1W": "7D"}


def snapshot(full: dict[str, pd.DataFrame], t: pd.Timestamp) -> tuple[dict, float]:
    """t paytidagi bot ko'radigan ma'lumot: faqat yopilgan shamlar, Kraken kabi oxirgi N ta."""
    out = {}
    for tf in ("5m", "15m", "4H", "1D", "1W"):
        df = full[tf]
        df = df[df.index + pd.Timedelta(DUR[tf]) <= t]
        out[tf] = df.iloc[-TAIL[tf]:]
    out["10m"] = resample(out["5m"], "10min").iloc[-TAIL["10m"]:]
    out["10m"] = out["10m"][out["10m"].index + pd.Timedelta("10min") <= t]
    price = float(out["5m"]["close"].iloc[-1])
    return out, price


# ------------------------------------------------------------------ savdo simulyatsiyasi
def simulate(m5: pd.DataFrame, t: pd.Timestamp, entry: float, stop: float, tps: list[float], limit: bool) -> dict:
    fut = m5[m5.index >= t]
    if limit:
        fill = fut[(fut.index < t + pd.Timedelta(hours=LIMIT_FILL_HOURS)) & (fut["low"] <= entry)]
        if fill.empty:
            return {"result": "to'lmadi", "r": 0.0}
        fut = fut[fut.index >= fill.index[0]]
    risk = entry - stop
    fut = fut[fut.index < t + pd.Timedelta(hours=EXIT_AFTER_HOURS)]
    mfe, tp1 = 0.0, False
    for ts, row in fut.iterrows():
        if row["low"] <= stop:  # bir shamda ikkalasi bo'lsa — konservativ: stop
            after = m5[(m5.index > ts) & (m5.index < ts + pd.Timedelta(hours=24))]
            hunted = bool((after["high"] >= tps[-1]).any()) if len(after) else False
            return {"result": "stop", "r": -1.0, "mfe": mfe, "tp1": tp1, "hunted": hunted, "time": ts}
        mfe = max(mfe, (row["high"] - entry) / risk)
        if row["high"] >= tps[0]:
            tp1 = True
        if row["high"] >= tps[-1]:
            return {"result": "TP", "r": (tps[-1] - entry) / risk, "mfe": mfe, "tp1": True, "time": ts}
    if fut.empty or m5.index[-1] < t + pd.Timedelta(hours=EXIT_AFTER_HOURS):
        return {"result": "ochiq", "r": 0.0, "mfe": mfe, "tp1": tp1}
    last = float(fut["close"].iloc[-1])
    return {"result": "vaqt tugadi", "r": (last - entry) / risk, "mfe": mfe, "tp1": tp1}


def trend_at(full: dict, t: pd.Timestamp) -> str:
    snap, price = snapshot(full, t)
    e = ema(snap["4H"]["close"], 50)
    above = price > float(e.iloc[-1])
    rising = float(e.iloc[-1]) > float(e.iloc[-7])
    d = snap["1D"]["close"]
    d_down = float(d.iloc[-1]) < float(d.iloc[-6])
    parts = ["4H EMA50 ustida" if above else "4H EMA50 OSTIDA",
             "EMA50 ko'tarilmoqda" if rising else "EMA50 PASAYMOQDA",
             "1D: 5 kunda pastga" if d_down else "1D: 5 kunda yuqoriga"]
    return ", ".join(parts)


# ------------------------------------------------------------------ backtest
def run_variant(args):
    name, overrides, data = args
    # jarayon qayta ishlatilishi mumkin — avval standart sozlamalarga qaytaramiz
    for k, v in {**DEFAULTS, **overrides}.items():
        setattr(cfg, k, v)
    end = max(df["5m"].index[-1] for df in data.values())
    hours = pd.date_range((end - pd.Timedelta(days=BACKTEST_DAYS)).floor("h"), end.floor("h") - pd.Timedelta(hours=1),
                          freq="1h") + pd.Timedelta(minutes=3)
    state: dict[str, pd.Timestamp] = {}
    last_any = pd.Timestamp(0, tz="UTC")
    trades = []
    for t in hours:
        cands = []
        btc_ok = True
        if cfg.BTC_FILTER and "⭐ BTC/USD" in data:
            try:
                bf, bp = snapshot(data["⭐ BTC/USD"], t)
                btc_ok = strategy.btc_gate(bf, bp) is not None
            except Exception:
                btc_ok = False
        for sym, full in data.items():
            if not btc_ok and "BTC" not in sym:
                continue
            try:
                frames, price = snapshot(full, t)
                if min(len(frames[tf]) for tf in frames) < 60:
                    continue
                sig = strategy.analyze(sym, frames, price)
            except Exception:
                continue
            if sig is None or sig.key in state:
                continue
            recent = [v for k, v in state.items() if k.startswith(sym + "|")]
            if recent and t - max(recent) < pd.Timedelta(hours=cfg.SYMBOL_COOLDOWN_HOURS):
                continue
            cands.append(sig)
        cands.sort(key=lambda s: (not s.symbol.startswith("⭐"), -s.score))
        if cands and t - last_any < pd.Timedelta(hours=cfg.GLOBAL_COOLDOWN_HOURS):
            cands = []
        for sig in cands[: cfg.MAX_SIGNALS_PER_RUN]:
            state[sig.key] = t
            last_any = t
            res = simulate(data[sig.symbol]["5m"], t, sig.entry, sig.stop, [x.price for x in sig.targets], sig.limit)
            res.update(symbol=sig.symbol, t=t, entry=sig.entry, stop=sig.stop, score=sig.score,
                       risk_pct=(sig.entry - sig.stop) / sig.entry * 100, final_rr=sig.targets[-1].rr)
            trades.append(res)
    return name, trades


def summarize(trades: list[dict]) -> dict:
    done = [x for x in trades if x["result"] in ("stop", "TP", "vaqt tugadi")]
    wins = [x for x in done if x["r"] > 0]
    return {
        "signal": len(trades), "yopilgan": len(done),
        "tp": sum(x["result"] == "TP" for x in done), "stop": sum(x["result"] == "stop" for x in done),
        "winrate": 100 * len(wins) / len(done) if done else 0.0,
        "tp1": 100 * sum(bool(x.get("tp1")) for x in done) / len(done) if done else 0.0,
        "avg_r": float(np.mean([x["r"] for x in done])) if done else 0.0,
        "sum_r": float(np.sum([x["r"] for x in done])) if done else 0.0,
        "hunted": sum(bool(x.get("hunted")) for x in done),
        "risk": float(np.mean([x["risk_pct"] for x in trades])) if trades else 0.0,
    }


def main():
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    out = Path("hisobot"); out.mkdir(exist_ok=True)
    lines = [f"# Backtest hisoboti — {end:%Y-%m-%d %H:%M} UTC", ""]

    print("Ma'lumot yuklanmoqda...")
    data = {}
    for sym, prod in COINBASE.items():
        try:
            data[sym] = load(prod, end)
            print(f"  {sym}: 5m={len(data[sym]['5m'])} 4H={len(data[sym]['4H'])}")
        except Exception as e:
            print(f"  {sym}: XATO {e}")

    # 1) Test haftasi signallari — yangi qoidalar bilan ham tekshiriladi
    for k, v in {**DEFAULTS, **NEW_22OCT}.items():
        setattr(cfg, k, v)
    lines += ["## 1. Test haftasi signallari (17-okt versiya)", "",
              "| Koin | Vaqt (UTC) | Stop % | Natija (Coinbase) | Eng ko'p foyda | Yangi qoidalar bilan signal chiqardimi | Trend kirishda |",
              "|---|---|---|---|---|---|---|"]
    for sym, ts, entry, stop, tps, limit in TODAY:
        if sym not in data:
            continue
        t = pd.Timestamp(ts, tz="UTC")
        r = simulate(data[sym]["5m"], t, entry, stop, tps, limit)
        try:
            bf, bp = snapshot(data["⭐ BTC/USD"], t)
            gate = strategy.btc_gate(bf, bp)
            fr, pr = snapshot(data[sym], t)
            sig = strategy.analyze(sym, fr, pr) if gate else None
            new = "HA" if sig else ("YO'Q — BTC sharti" if gate is None else "YO'Q — setup filtri")
        except Exception as e:
            new = f"xato: {e}"
        lines.append(f"| {sym} | {ts[5:]} | −{(entry - stop) / entry * 100:.2f}% | {r['result']} ({r['r']:+.1f}R) "
                     f"| {r.get('mfe', 0):.1f}R | {new} | {trend_at(data[sym], t)} |")
    lines.append("")

    # 2) Backtest
    print("Backtest...")
    with ProcessPoolExecutor() as ex:
        results = dict(ex.map(run_variant, [(n, o, data) for n, o in VARIANTS.items()]))
    lines += [f"## 2. Backtest — so'nggi {BACKTEST_DAYS} kun, {len(data)} koin", "",
              "| Variant | Signal | TP | Stop | G'alaba % | TP1 ga yetdi % | O'rtacha R | Jami R | Stop ovlangan | O'rt. stop % |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for name, trades in results.items():
        s = summarize(trades)
        lines.append(f"| {name} | {s['signal']} | {s['tp']} | {s['stop']} | {s['winrate']:.0f}% | {s['tp1']:.0f}% "
                     f"| {s['avg_r']:+.2f} | {s['sum_r']:+.1f} | {s['hunted']} | {s['risk']:.2f}% |")
    lines += ["", "*Jami R > 0 — strategiya foydali. 1R = bitta savdodagi xavf (masalan depozitning 1%).*", ""]

    for name, trades in results.items():
        lines += [f"### {name} — barcha savdolar", "", "| Vaqt (UTC) | Koin | Kirish | Stop % | Natija | R | Maks. foyda |", "|---|---|---|---|---|---|---|"]
        for x in trades:
            lines.append(f"| {x['t']:%m-%d %H:%M} | {x['symbol']} | {x['entry']:.6g} | −{x['risk_pct']:.2f}% "
                         f"| {x['result']} | {x['r']:+.2f} | {x.get('mfe', 0):.1f}R |")
        lines.append("")

    (out / "backtest.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:40]))


if __name__ == "__main__":
    main()
