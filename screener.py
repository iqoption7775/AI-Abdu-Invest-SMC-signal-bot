"""BTC ga ergashmaydigan halol koinlar skrineri (29-oktabr, treyder g'oyasi).

G'oya: top koinlarning hammasi BTC ortidan yuradi — BTC tushsa, hammasi birga tushadi (28–29 oktabr:
AVAX va ALGO bir vaqtda stop bo'ldi). Shuning uchun BTC va ETH dan tashqari faqat BTC ga kam ergashadigan
halol koinlar tahlil qilinadi. Qanday aniqlanadi:
  1. BTC tushganda o'z narxini saqlab turadi  → "BTC tushganda" nisbati kichik (0 dan past — hatto o'sgan).
  2. BTC to'xtaganda ko'tarila boshlaydi       → "BTC to'xtagach 3 kun" koinning o'z o'sishi musbat.
  3. Pasayishdagi beta past — BTC ning har 1% tushishiga koin kamroq tushadi.
  4. Oxirgi 30 kunda BTC dan kuchliroq (koin/BTC nisbati o'smoqda).

Ma'lumot: Coinbase (likvid, ochiq API). 4H — 1H dan. Kraken'da (jonli bot birjasi) borligi tekshiriladi.
Natija: hisobot/screener.md va screener.json (jonli bot shu ro'yxatni oladi).

Ikki oyna hisoblanadi:
  * "jonli"  — oxirgi 90 kun → jonli bot uchun ro'yxat;
  * "test"   — 180→90 kun oldin → backtest uchun ro'yxat (koin tanlash va sinov bir davrda bo'lmasin —
               aks holda natija o'zini aldaydi).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from backtest import _cb
from data import resample
from smc import swing_points

# Nomzodlar: (nomi, Coinbase, Kraken, turi). Halollik — taxminiy: foizli qarz/kredit, derivativ/leverage,
# qimor, mem-koin va stablecoinlar KIRITILMAGAN. Yakuniy qaror — treyder/ulamo.
CANDIDATES = [
    ("SOL/USD", "SOL-USD", "SOLUSD", "L1 blokcheyn"),
    ("XRP/USD", "XRP-USD", "XRPUSD", "to'lovlar"),
    ("ADA/USD", "ADA-USD", "ADAUSD", "L1 blokcheyn"),
    ("AVAX/USD", "AVAX-USD", "AVAXUSD", "L1 blokcheyn"),
    ("LINK/USD", "LINK-USD", "LINKUSD", "oracle"),
    ("DOT/USD", "DOT-USD", "DOTUSD", "L0 blokcheyn"),
    ("LTC/USD", "LTC-USD", "LTCUSD", "to'lovlar"),
    ("XLM/USD", "XLM-USD", "XLMUSD", "to'lovlar"),
    ("NEAR/USD", "NEAR-USD", "NEARUSD", "L1 blokcheyn"),
    ("ATOM/USD", "ATOM-USD", "ATOMUSD", "L0 blokcheyn"),
    ("ALGO/USD", "ALGO-USD", "ALGOUSD", "L1 blokcheyn"),
    ("HBAR/USD", "HBAR-USD", "HBARUSD", "L1 blokcheyn"),
    ("ICP/USD", "ICP-USD", "ICPUSD", "L1 blokcheyn"),
    ("FIL/USD", "FIL-USD", "FILUSD", "fayl saqlash"),
    ("GRT/USD", "GRT-USD", "GRTUSD", "ma'lumot indeksi"),
    ("RENDER/USD", "RENDER-USD", "RENDERUSD", "GPU hisoblash"),
    ("FET/USD", "FET-USD", "FETUSD", "AI"),
    ("TAO/USD", "TAO-USD", "TAOUSD", "AI"),
    ("HNT/USD", "HNT-USD", "HNTUSD", "simsiz tarmoq"),
    ("ARB/USD", "ARB-USD", "ARBUSD", "L2"),
    ("OP/USD", "OP-USD", "OPUSD", "L2"),
    ("POL/USD", "POL-USD", "POLUSD", "L2"),
    ("SUI/USD", "SUI-USD", "SUIUSD", "L1 blokcheyn"),
    ("APT/USD", "APT-USD", "APTUSD", "L1 blokcheyn"),
    ("SEI/USD", "SEI-USD", "SEIUSD", "L1 blokcheyn"),
    ("TIA/USD", "TIA-USD", "TIAUSD", "modulli blokcheyn"),
    ("QNT/USD", "QNT-USD", "QNTUSD", "interoperability"),
    ("XTZ/USD", "XTZ-USD", "XTZUSD", "L1 blokcheyn"),
    ("BCH/USD", "BCH-USD", "BCHUSD", "to'lovlar"),
    ("ETC/USD", "ETC-USD", "ETCUSD", "L1 blokcheyn"),
    ("EGLD/USD", "EGLD-USD", "EGLDUSD", "L1 blokcheyn"),
    ("FLOW/USD", "FLOW-USD", "FLOWUSD", "L1 blokcheyn"),
    ("IMX/USD", "IMX-USD", "IMXUSD", "o'yin L2"),
    ("STX/USD", "STX-USD", "STXUSD", "BTC L2"),
    ("AXL/USD", "AXL-USD", "AXLUSD", "interoperability"),
    ("VET/USD", "VET-USD", "VETUSD", "ta'minot zanjiri"),
]
PICK = 11                 # BTC va ETH dan tashqari ko'pi bilan nechta koin tanlanadi
MAX_HOLD = 1.0            # shart 1: BTC tushganda koin BTC dan KAM tushgan bo'lsin (1.0 = BTC bilan bir xil)
MIN_REBOUND = 0.0         # shart 2: BTC to'xtagach 3 kunda koin O'SGAN bo'lsin (median)
MIN_EPISODES = 3          # kamida 3 ta BTC pasayishi kuzatilgan bo'lsin (tasodif bo'lmasin)
MIN_KRAKEN_USD = 300_000  # jonli bot Kraken'dan oladi — u yerda ham kunlik hajm yetarli bo'lsin
MIN_DROP = 0.03           # BTC pasayishi epizodi: 4H swing high → swing low kamida 3%
REBOUND_BARS = 18         # BTC to'xtagach 3 kun (18 ta 4H sham)
MIN_VOLUME_USD = 2_000_000  # Coinbase'da kunlik hajm kamida $2M (o'lik narxlar natijani buzmasin)


def kraken_pairs() -> set[str]:
    """Kraken'da bor va kunlik hajmi MIN_KRAKEN_USD dan katta juftliklar (altname, masalan SOLUSD)."""
    try:
        pairs = requests.get("https://api.kraken.com/0/public/AssetPairs", timeout=30).json()["result"]
        alt = {k: v.get("altname", "") for k, v in pairs.items()}
        want = [a for a in alt.values() if a in {c[2] for c in CANDIDATES}]
        tick = requests.get("https://api.kraken.com/0/public/Ticker", params={"pair": ",".join(want)},
                            timeout=30).json().get("result", {})
        ok = {alt.get(k, k) for k, t in tick.items() if float(t["v"][1]) * float(t["p"][1]) >= MIN_KRAKEN_USD}
        return ok or set(want)
    except Exception:
        return set()


def metrics(c4: pd.Series, b4: pd.Series, bh: pd.Series, bl: pd.Series, d1: pd.DataFrame) -> dict | None:
    """c4/b4 — koin va BTC 4H yopilishlari (bir xil indeks); bh/bl — BTC 4H high/low."""
    df = pd.concat([c4, b4], axis=1, keys=["c", "b"]).dropna()
    if len(df) < 200:
        return None
    rc, rb = np.log(df["c"]).diff().dropna(), np.log(df["b"]).diff().dropna()
    corr = float(rc.corr(rb))
    down = rb < 0
    beta_dn = float(np.cov(rc[down], rb[down])[0, 1] / rb[down].var()) if down.sum() > 20 else np.nan

    # BTC pasayish epizodlari: swing high → keyingi swing low, kamida MIN_DROP
    bdf = pd.DataFrame({"high": bh, "low": bl}).reindex(df.index)
    sh, sl = swing_points(bdf, 3)
    highs, lows = np.flatnonzero(sh), np.flatnonzero(sl)
    B, C = df["b"].to_numpy(), df["c"].to_numpy()
    hold, rebound = [], []
    for h in highs:
        nxt = lows[lows > h]
        if not len(nxt):
            continue
        lo = int(nxt[0])
        bchg = B[lo] / B[h] - 1
        if bchg > -MIN_DROP or lo - h > 30:
            continue
        hold.append((C[lo] / C[h] - 1) / bchg)          # 1 = BTC bilan bir xil, 0 = joyida, <0 = o'sgan
        if lo + REBOUND_BARS < len(B):
            rebound.append(C[lo + REBOUND_BARS] / C[lo] - 1)  # BTC tubidan keyingi 3 kunda koinning o'z o'sishi
    ratio = df["c"] / df["b"]
    rs30 = float(ratio.iloc[-1] / ratio.iloc[-min(180, len(ratio) - 1)] - 1)
    vol = float((d1["close"] * d1["volume"]).tail(30).median()) if len(d1) else 0.0
    return {"corr": corr, "beta_dn": beta_dn, "hold": float(np.median(hold)) if hold else np.nan,
            "rebound": float(np.median(rebound)) if rebound else np.nan, "episodes": len(hold),
            "rs30": rs30, "vol": vol}


def rank(rows: list[dict]) -> list[dict]:
    """Ball: har bir ko'rsatkich bo'yicha o'rin (kichik — yaxshi), o'rtachasi. Hajm yetarli bo'lganlar."""
    ok = [r for r in rows if r["vol"] >= MIN_VOLUME_USD and r["episodes"] >= MIN_EPISODES
          and not np.isnan(r["hold"]) and not np.isnan(r["rebound"])]
    if not ok:
        return []
    d = pd.DataFrame(ok)
    # Treyderning 2 ta asosiy sharti (BTC tushganda ushlab turish, BTC to'xtagach o'sish) — ikki barobar vazn
    d["score"] = (2 * d["hold"].rank() + 2 * d["rebound"].rank(ascending=False) + d["beta_dn"].rank()
                  + d["rs30"].rank(ascending=False) + d["corr"].rank()) / 7
    d["passes"] = (d["hold"] < MAX_HOLD) & (d["rebound"] > MIN_REBOUND)
    return d.sort_values("score").to_dict("records")


def pick(rows: list[dict], kraken: set[str]) -> list[dict]:
    """Ikkala shartdan o'tgan, Kraken'da savdosi bor eng yaxshi PICK ta koin."""
    return [r for r in rows if r["passes"] and (not kraken or r["kraken"] in kraken)][:PICK]


def entry(r: dict) -> dict:
    return {"name": r["name"], "kraken": r["kraken"], "coinbase": r["coinbase"],
            "hold": round(r["hold"], 3), "rebound": round(r["rebound"], 4)}


def window(data: dict, start: pd.Timestamp, end: pd.Timestamp) -> list[dict]:
    btc = data["BTC"]
    b4 = btc["4H"][(btc["4H"].index >= start) & (btc["4H"].index < end)]
    rows = []
    for name, cb, kr, kind in CANDIDATES:
        if name not in data:
            continue
        f = data[name]
        c4 = f["4H"]["close"][(f["4H"].index >= start) & (f["4H"].index < end)]
        d1 = f["1D"][(f["1D"].index >= end - pd.Timedelta(days=30)) & (f["1D"].index < end)]
        m = metrics(c4, b4["close"], b4["high"], b4["low"], d1)
        if m:
            rows.append({"name": name, "coinbase": cb, "kraken": kr, "kind": kind, **m})
    return rank(rows)


def table(rows: list[dict], kraken: set[str], top: list[str]) -> list[str]:
    out = ["| # | Koin | Turi | BTC tushganda | BTC to'xtagach 3 kun | Shartlar | Pasayish betasi | Korrelyatsiya "
           "| 30 kun BTC ga nisbatan | Pasayishlar | Hajm/kun | Kraken |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        mark = "⭐ " if r["name"] in top else ""
        out.append(f"| {i} | {mark}{r['name']} | {r['kind']} | {r['hold'] * 100:.0f}% | {r['rebound'] * 100:+.1f}% "
                   f"| {'✅' if r['passes'] else '—'} | {r['beta_dn']:.2f} | {r['corr']:.2f} | {r['rs30'] * 100:+.0f}% "
                   f"| {r['episodes']} | ${r['vol'] / 1e6:.0f}M | {'✅' if not kraken or r['kraken'] in kraken else '❌'} |")
    return out


def main():
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=185)
    data = {}
    try:  # Coinbase'da yo'q juftliklarni oldindan chiqarib tashlash (aks holda har biri uzoq qayta urinadi)
        listed = {p["id"] for p in requests.get("https://api.exchange.coinbase.com/products", timeout=30,
                                                headers={"User-Agent": "AbduInvestScreener"}).json()}
    except Exception:
        listed = set()
    for name, cb in [("BTC", "BTC-USD")] + [(n, c) for n, c, _, _ in CANDIDATES]:
        if listed and cb not in listed:
            print(f"{name}: Coinbase'da yo'q — o'tkazib yuborildi")
            continue
        try:
            h1 = _cb(cb, 3600, start, end)
            d1 = _cb(cb, 86400, start, end)
            if len(h1) > 500:
                data[name] = {"4H": resample(h1, "4h"), "1D": d1}
                print(f"{name}: 1H={len(h1)}")
        except Exception as e:
            print(f"{name}: XATO {e}")
    if "BTC" not in data:
        raise SystemExit("BTC ma'lumoti yo'q — screener.json o'zgartirilmadi")
    kraken = kraken_pairs()
    T = pd.Timestamp(end)
    live = window(data, T - pd.Timedelta(days=90), T)
    test = window(data, T - pd.Timedelta(days=180), T - pd.Timedelta(days=90))
    if not live:
        raise SystemExit("Ma'lumot yetarli emas — screener.json o'zgartirilmadi")
    live_pick, test_pick = pick(live, kraken), pick(test, kraken)
    Path("screener.json").write_text(json.dumps({
        "updated": f"{end:%Y-%m-%d %H:%M} UTC",
        "live": [entry(r) for r in live_pick],
        "test": [entry(r) for r in test_pick],
    }, indent=2, ensure_ascii=False) + "\n")

    L = [f"# BTC ga ergashmaydigan halol koinlar — {end:%Y-%m-%d %H:%M} UTC", "",
         "**Ustunlar:**",
         "- **BTC tushganda** — BTC har safar ≥3% tushganda koin qancha tushgan (BTC ga nisbatan). 100% — BTC bilan bir xil, "
         "0% — joyida turgan, manfiy — hatto o'sgan. **Kichik — yaxshi.**",
         "- **BTC to'xtagach 3 kun** — BTC tubidan keyingi 3 kunda koinning o'zi qancha o'sgan. **Katta — yaxshi.**",
         "- **Pasayish betasi** — BTC ning har 1% tushishiga koin necha % tushadi. **Kichik — yaxshi.**",
         "- **30 kun BTC ga nisbatan** — koin/BTC nisbati. **Musbat — BTC dan kuchli.**",
         f"- **Shartlar ✅** — ikkala shart bajarilgan: BTC tushganda < {MAX_HOLD * 100:.0f}% va BTC to'xtagach > {MIN_REBOUND * 100:+.0f}%. "
         f"Faqat shular botga olinadi (ko'pi bilan {PICK} ta, ball bo'yicha).",
         f"- Hajm/kun < ${MIN_VOLUME_USD / 1e6:.0f}M yoki {MIN_EPISODES} tadan kam BTC pasayishi bo'lgan koinlar jadvalga kirmaydi.", "",
         "Halollik taxminiy: foizli kredit, derivativ/leverage, qimor, mem-koin va stablecoinlar nomzodlarga kiritilmagan.", "",
         f"## Jonli bot uchun — oxirgi 90 kun (⭐ — tanlangan: {len(live_pick)} ta)", ""]
    L += table(live, kraken, [r["name"] for r in live_pick])
    L += ["", f"## Backtest uchun — 180→90 kun oldin (⭐ — tanlangan: {len(test_pick)} ta; tanlov va sinov bir davrda bo'lmasligi uchun)", ""]
    L += table(test, kraken, [r["name"] for r in test_pick])
    out = Path("hisobot")
    out.mkdir(exist_ok=True)
    (out / "screener.md").write_text("\n".join(L) + "\n")
    print("\n".join(L[:40]))


if __name__ == "__main__":
    main()
