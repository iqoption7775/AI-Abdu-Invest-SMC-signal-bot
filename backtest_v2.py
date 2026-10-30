"""Abdu modeli backtesti — so'nggi 90 kun, har soatda (bot kabi).

GitHub Actions: .github/workflows/backtest_v2.yml (abdu_model.py / backtest_v2.py o'zgarganda o'zi ishga tushadi).
Natija: hisobot/abdu_backtest.md

Ma'lumot: Coinbase ochiq API — 15m (kirish/chiqish simulyatsiyasi), 1H, 1D. 4H/12H — 1H dan, 1W — 1D dan.
Ikki xil boshqaruv hisoblanadi:
  A) Faqat oxirgi TP yoki stop.
  B) TP1 da 50% yopiladi, qolgani uchun stop kirishga ko'chadi (zararsiz), qolgani oxirgi TP gacha.
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import abdu_model as am
import config as cfg
import strategy
from backtest import COINBASE, _cb
from data import resample

DAYS = 90
EXPIRY_H = 48            # limit shu vaqtda to'lmasa — bekor
MAX_HOLD_D = 10          # shu vaqtda TP ham stop ham bo'lmasa — bozor narxida yopiladi
TAIL = {"1H": 720, "4H": 720, "12H": 400, "1D": 400, "1W": 200}
DUR = {"1H": "1h", "4H": "4h", "12H": "12h", "1D": "1D", "1W": "7D", "15m": "15min"}

VARIANTS = {
    "1. 1H FVG tepasi": dict(entry="fvg_top"),
    "2. 1H FVG o'rtasi (50%)": dict(entry="fvg_ce"),
    "3. 4H OB tepasi": dict(entry="ob_top"),
    "4. FVG tepasi + BTC 4H trend filtri": dict(entry="fvg_top", btc=True),
    "5. FVG tepasi, discount shartisiz": dict(entry="fvg_top", AM_USE_DISCOUNT=False),
    "6. FVG tepasi + 1R ichida taklif zonasi bo'lmasin": dict(entry="fvg_top", AM_BLOCK_SUPPLY_R=1.0),
    "7. JONLI BOT: FVG tepasi + BTC filtri + stop ≤ 5%": dict(entry="fvg_top", btc=True, AM_MAX_STOP_PCT=cfg.AM_MAX_STOP_PCT),
}
# UNIVERSE=screener: skrener tanlagan (BTC ga kam ergashadigan) koinlar va hozirgi 13 koin solishtiriladi.
# Tanlov 180→90 kun oldingi ma'lumotdan ("test"), sinov — oxirgi 90 kun: natija o'zini aldamaydi.
UNIVERSE = os.environ.get("UNIVERSE", "default")
REPORT = "abdu_backtest.md"
if UNIVERSE == "screener":
    _pick = json.loads(Path("screener.json").read_text())["test"]
    OLD = set(COINBASE)
    NEW = {"⭐ BTC/USD", "⭐ ETH/USD"} | {p["name"] for p in _pick}
    COINBASE = {**COINBASE, **{p["name"]: p["coinbase"] for p in _pick}}
    _live = dict(entry="fvg_top", AM_MAX_STOP_PCT=cfg.AM_MAX_STOP_PCT)
    VARIANTS = {
        "A. ESKI BOT: 13 koin + BTC filtri": {**_live, "btc": True, "syms": OLD},
        "B. YANGI BOT: BTC + ETH + BTC ga kam ergashadigan koinlar, BTC filtrisiz": {**_live, "syms": NEW},
        "C. Yangi koinlar + BTC filtri": {**_live, "btc": True, "syms": NEW},
        "D. Eski 13 koin, BTC filtrisiz": {**_live, "syms": OLD},
        "E. Faqat BTC va ETH": {**_live, "syms": {"⭐ BTC/USD", "⭐ ETH/USD"}},
    }
    REPORT = "abdu_backtest_screener.md"

_CFG = ["AM_USE_DISCOUNT", "AM_BLOCK_SUPPLY_R", "AM_MAX_STOP_PCT"]
BASE = {k: getattr(cfg, k) for k in _CFG}
BASE["AM_MAX_STOP_PCT"] = 100.0  # 1–6 variantlarda stop chegarasi yo'q (avvalgi backtest bilan solishtirish uchun)


def load(product: str, end: datetime) -> dict[str, pd.DataFrame]:
    start = end - timedelta(days=DAYS)
    m15 = _cb(product, 900, start - timedelta(days=1), end)
    h1 = _cb(product, 3600, start - timedelta(days=125), end)
    d1 = _cb(product, 86400, start - timedelta(days=420), end)
    return {"15m": m15, "1H": h1, "4H": resample(h1, "4h"), "12H": resample(h1, "12h"),
            "1D": d1, "1W": resample(d1, "W-MON")}


def snapshot(full: dict, t: pd.Timestamp) -> tuple[dict, float]:
    out = {}
    for tf in TAIL:
        df = full[tf]
        n = int(np.searchsorted(df.index.values, (t - pd.Timedelta(DUR[tf])).to_datetime64(), side="right"))
        out[tf] = df.iloc[max(0, n - TAIL[tf]): n]
    m = full["15m"]
    n = int(np.searchsorted(m.index.values, (t - pd.Timedelta("15min")).to_datetime64(), side="right"))
    return out, float(m["close"].iloc[n - 1])


def simulate(m15: pd.DataFrame, t: pd.Timestamp, entry: float, stop: float, tps: list[float]) -> dict:
    fut = m15[m15.index >= t]
    hi, lo, cl, idx = fut["high"].to_numpy(), fut["low"].to_numpy(), fut["close"].to_numpy(), fut.index
    exp = np.searchsorted(idx.values, (t + pd.Timedelta(hours=EXPIRY_H)).to_datetime64())
    f = None
    for i in range(min(exp, len(fut))):
        if lo[i] <= entry:
            f = i
            break
        if hi[i] >= tps[0]:
            return {"res": "o'tib ketdi", "a": 0.0, "b": 0.0, "until": idx[i]}  # narx zonaga qaytmay TP1 ga ketdi
    if f is None:
        last = idx[min(exp, len(fut)) - 1] if len(fut) else t
        return {"res": "to'lmadi" if exp < len(fut) else "kutilmoqda", "a": 0.0, "b": 0.0, "until": last}
    risk = entry - stop
    rr = [(p - entry) / risk for p in tps]
    end = np.searchsorted(idx.values, (idx[f] + pd.Timedelta(days=MAX_HOLD_D)).to_datetime64())
    tp1_hit, mfe, free = False, 0.0, None   # free — TP1 olingan vaqt: stop kirishga ko'chdi, xavf qolmadi
    for i in range(f, min(end, len(fut))):
        if lo[i] <= (entry if tp1_hit else stop) and not (i == f and tp1_hit):
            if tp1_hit:   # B: qolgan yarmi zararsiz yopildi
                return {"res": "TP1 + zararsiz", "a": _a_after_tp1(lo, hi, i, stop, tps[-1], rr[-1]),
                        "b": 0.5 * rr[0], "mfe": mfe, "fill": idx[f], "until": free}
            return {"res": "stop", "a": -1.0, "b": -1.0, "mfe": mfe, "fill": idx[f], "until": idx[i]}
        mfe = max(mfe, (hi[i] - entry) / risk)
        if hi[i] >= tps[-1]:
            return {"res": "TP", "a": rr[-1], "b": 0.5 * rr[0] + 0.5 * rr[-1], "mfe": mfe, "fill": idx[f],
                    "until": free or idx[i]}
        if not tp1_hit and hi[i] >= tps[0] and len(tps) > 1:
            tp1_hit, free = True, idx[i]
    k = min(end, len(fut)) - 1
    if k + 1 >= len(fut):
        return {"res": "ochiq", "a": 0.0, "b": 0.0, "mfe": mfe, "fill": idx[f], "until": free or idx[k]}
    last = (cl[k] - entry) / risk
    return {"res": "vaqt tugadi", "a": last, "b": (0.5 * rr[0] + 0.5 * max(last, 0)) if tp1_hit else last,
            "mfe": mfe, "fill": idx[f], "until": free or idx[k]}


def _a_after_tp1(lo, hi, i, stop, final, final_rr):
    """A boshqaruv (stop joyida qoladi): TP1 dan keyin narx kirishga qaytgan — davom etib natijani topamiz."""
    for k in range(i, len(lo)):
        if lo[k] <= stop:
            return -1.0
        if hi[k] >= final:
            return final_rr
    return 0.0


def run_symbol(args):
    sym, full, btc = args
    end = full["15m"].index[-1]
    hours = pd.date_range((end - pd.Timedelta(days=DAYS)).floor("h"), end.floor("h"), freq="1h") + pd.Timedelta(minutes=3)
    sent = {name: set() for name in VARIANTS}
    trades = []
    for t in hours:
        try:
            frames, price = snapshot(full, t)
            s = am.detect(frames)
        except Exception:
            continue
        if s is None:
            continue
        btc_ok = None
        key = f"{sym}|{s.key_time}"
        for name, v in VARIANTS.items():
            if key in sent[name] or ("syms" in v and sym not in v["syms"]):
                continue  # bu setup bo'yicha signal berilgan yoki koin bu variantga kirmaydi
            for k in _CFG:
                setattr(cfg, k, v.get(k, BASE[k]))
            if v.get("btc") and "BTC" not in sym:
                if btc_ok is None:
                    try:
                        bf, bp = snapshot(btc, t)
                        btc_ok = strategy._trend_4h(bf, bp) is not None
                    except Exception:
                        btc_ok = False
                if not btc_ok:
                    continue
            try:
                sig = am.build(sym, s, frames, price, v["entry"])
            except Exception:
                continue
            if sig is None or sig.setup_key in sent[name]:
                continue
            sent[name].add(sig.setup_key)
            r = simulate(full["15m"], t, sig.entry, sig.stop, [x.price for x in sig.targets])
            r.update(variant=name, symbol=sym, t=t, entry=sig.entry, risk=(sig.entry - sig.stop) / sig.entry * 100,
                     final_rr=sig.targets[-1].rr, tp1_rr=sig.targets[0].rr)
            trades.append(r)
    return trades


def summarize(tr: list[dict]) -> dict:
    done = [x for x in tr if x["res"] in ("TP", "stop", "TP1 + zararsiz", "vaqt tugadi")]
    return {
        "signal": len(tr), "kirildi": len(done) + sum(x["res"] == "ochiq" for x in tr),
        "tp": sum(x["res"] == "TP" for x in done), "stop": sum(x["res"] == "stop" for x in done),
        "win_a": 100 * sum(x["a"] > 0 for x in done) / len(done) if done else 0,
        "sum_a": float(np.sum([x["a"] for x in done])) if done else 0.0,
        "win_b": 100 * sum(x["b"] > 0 for x in done) / len(done) if done else 0,
        "sum_b": float(np.sum([x["b"] for x in done])) if done else 0.0,
        "avg_a": float(np.mean([x["a"] for x in done])) if done else 0.0,
        "risk": float(np.mean([x["risk"] for x in tr])) if tr else 0.0,
        "rr": float(np.mean([x["final_rr"] for x in tr])) if tr else 0.0,
    }


def cap_open(trades: list[dict], n: int, label: str) -> list[dict]:
    """Bir vaqtda ko'pi bilan n ta "xavfli" signal: kutilayotgan limit yoki stopi hali kirishga ko'chmagan savdo.
    Yangi signal kelganda shunday signallar n ta bo'lsa — u yuborilmaydi (AVAX+ALGO kabi birga stop bo'lmasin)."""
    kept = []
    for x in sorted(trades, key=lambda x: (x["t"], x["risk"])):
        if sum(1 for k in kept if k["until"] > x["t"]) >= n:
            continue
        kept.append({**x, "variant": label})
    return kept


def main():
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    data = {}
    for sym, prod in COINBASE.items():
        try:
            data[sym] = load(prod, end)
            print(f"{sym}: 15m={len(data[sym]['15m'])} 1H={len(data[sym]['1H'])} 1D={len(data[sym]['1D'])}")
        except Exception as e:
            print(f"{sym}: XATO {e}")
    btc = data.get("⭐ BTC/USD")
    with ProcessPoolExecutor() as ex:
        allt = [x for part in ex.map(run_symbol, [(s, f, btc) for s, f in data.items()]) for x in part]
    # Jonli bot varianti + "bir vaqtda ko'pi bilan N ta ochiq xavf" cheklovi (birga stop bo'lishga qarshi)
    live = [n for n in VARIANTS if "JONLI" in n or "ESKI BOT" in n][0]
    for n in (3, 2):
        label = f"{live.split('.')[0]}+{n}. {live.split('. ', 1)[1].split(':')[0]} + bir vaqtda ≤ {n} ta ochiq xavf"
        allt += cap_open([x for x in allt if x["variant"] == live], n, label)
        VARIANTS[label] = VARIANTS[live]

    L = [f"# Abdu modeli — backtest ({DAYS} kun, {len(data)} koin) — {end:%Y-%m-%d %H:%M} UTC", "",
         "Setup: discount → sell-side sweep → 1H CHoCH → 4H OB + 1H FVG → retestda limit BUY. Oxirgi TP ≥ 1:3.", "",
         "**A** — faqat oxirgi TP yoki stop. **B** — TP1 da 50% yopiladi, qolgani uchun stop kirishga ko'chadi.", "",
         "| Variant | Signal | Kirildi | TP | Stop | A: g'alaba | A: jami R | B: g'alaba | B: jami R | O'rt. stop | O'rt. oxirgi RR |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name in VARIANTS:
        s = summarize([x for x in allt if x["variant"] == name])
        L.append(f"| {name} | {s['signal']} | {s['kirildi']} | {s['tp']} | {s['stop']} | {s['win_a']:.0f}% | {s['sum_a']:+.1f}R "
                 f"| {s['win_b']:.0f}% | {s['sum_b']:+.1f}R | {s['risk']:.2f}% | 1:{s['rr']:.1f} |")
    L += ["", "*Jami R > 0 — foydali. 1R = bitta savdodagi xavf (masalan depozitning 1%).*", ""]

    first = list(VARIANTS)[1 if UNIVERSE == "screener" else 0]
    L += [f"## Koinlar bo'yicha — {first}", "", "| Koin | Signal | TP | Stop | A: jami R | B: jami R |", "|---|---|---|---|---|---|"]
    for sym in data:
        if "syms" in VARIANTS[first] and sym not in VARIANTS[first]["syms"]:
            continue
        s = summarize([x for x in allt if x["variant"] == first and x["symbol"] == sym])
        L.append(f"| {sym} | {s['signal']} | {s['tp']} | {s['stop']} | {s['sum_a']:+.1f}R | {s['sum_b']:+.1f}R |")
    L.append("")
    for name in VARIANTS:
        L += [f"### {name} — barcha signallar", "",
              "| Vaqt (UTC) | Koin | Kirish | Stop % | Oxirgi RR | Natija | A | B | Maks. foyda |", "|---|---|---|---|---|---|---|---|---|"]
        for x in sorted((x for x in allt if x["variant"] == name), key=lambda x: x["t"]):
            L.append(f"| {x['t']:%m-%d %H:%M} | {x['symbol']} | {x['entry']:.6g} | −{x['risk']:.2f}% | 1:{x['final_rr']:.1f} "
                     f"| {x['res']} | {x['a']:+.2f} | {x['b']:+.2f} | {x.get('mfe', 0):.1f}R |")
        L.append("")
    out = Path("hisobot")
    out.mkdir(exist_ok=True)
    if UNIVERSE == "screener":
        L.insert(2, "**Yangi koinlar:** " + ", ".join(sorted(NEW)) + "  \n*(180→90 kun oldingi ma'lumot bo'yicha tanlangan, sinov — oxirgi 90 kun)*\n")
    (out / REPORT).write_text("\n".join(L) + "\n")
    print("\n".join(L[:30]))


if __name__ == "__main__":
    main()
