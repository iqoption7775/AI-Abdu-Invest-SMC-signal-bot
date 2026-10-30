"""Bir martalik tekshiruv: har bir juftlikni tahlil qiladi va yangi signallarni yuboradi.

GitHub Actions buni har soatda ishga tushiradi (.github/workflows/signals.yml).
Qo'lda ishga tushirish:  python main.py
"""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path

import config as cfg
from data import fetch
import abdu_model
from strategy import analyze, btc_gate
from telegram import format_signal, send

STATE_FILE = Path(__file__).with_name("state.json")
SCREENER_FILE = Path(__file__).with_name("screener.json")  # screener.py yozadi (har dushanba)


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    week_ago = time.time() - 7 * 24 * 3600
    state = {k: v for k, v in state.items() if v > week_ago}  # eski yozuvlarni tozalash
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def universe(abdu: bool) -> list[dict]:
    """Tahlil qilinadigan koinlar (config.AM_UNIVERSE):
      "fixed"          — config.SYMBOLS (13 koin);
      "fixed+screener" — 13 koin + screener.json dagi "live" ro'yxat (BTC ga kam ergashadigan halol koinlar);
      "screener"       — ⭐ BTC + ⭐ ETH + screener.json ro'yxati."""
    mode = cfg.AM_UNIVERSE if abdu else "fixed"
    if mode not in ("screener", "fixed+screener"):
        return cfg.SYMBOLS
    base = cfg.SYMBOLS if mode == "fixed+screener" else \
        [s for s in cfg.SYMBOLS if "BTC" in s["name"] or "ETH" in s["name"]]
    try:
        picks = json.loads(SCREENER_FILE.read_text())["live"]
    except Exception as e:
        print(f"screener.json o'qilmadi ({e}) — skrener koinlarisiz davom etiladi")
        return base
    names = {s["name"].lstrip("⭐ ") for s in base}
    return base + [{"name": p["name"], "source": "kraken", "ticker": p["kraken"],
                    "hold": p.get("hold"), "rebound": p.get("rebound")}
                   for p in picks if p["name"] not in names]


def decorrelation_note(hold: float, rebound: float) -> str:
    """Skrener ko'rsatkichlari — signal sabablari ostida (oxirgi 90 kun, medianalar)."""
    fall = "hatto o'sgan" if hold <= 0 else f"o'rtacha {hold * 10:.1f}% tushgan"
    return (f"BTC ga kam ergashadi (90 kun): BTC 10% tushganda bu koin {fall}, "
            f"BTC to'xtagach 3 kunda {rebound * 100:+.1f}% o'sgan")


def abdu_analyze(symbol: str, frames: dict, price: float):
    """Abdu modeli: signal + setup (grafikda OB, FVG, likvidlik va CHoCH chizish uchun)."""
    s = abdu_model.detect(frames)
    sig = abdu_model.build(symbol, s, frames, price) if s else None
    if sig is not None:
        sig.setup = s
    return sig


def deliver(sig) -> bool:
    """Signal: grafik rasm (stop/TP darajalari bilan) + qisqa izoh. Grafik chizilmasa — faqat matn."""
    text = format_signal(sig)
    photo = None
    if cfg.SIGNAL_CHART and "1H" in (getattr(sig, "frames", None) or {}):
        try:
            import chart
            photo = chart.render(sig)
        except Exception:
            print(f"Grafik chizilmadi ({sig.symbol}):\n{traceback.format_exc()}")
    return send(text, photo) if photo else send(text)


def run() -> int:
    state = load_state()
    abdu = cfg.STRATEGY == "abdu"
    tfs = cfg.AM_TIMEFRAMES if abdu else cfg.HTF_TIMEFRAMES + cfg.LTF_TIMEFRAMES
    analyze_fn = abdu_analyze if abdu else analyze
    candidates = []
    btc_trend = None  # BTC sharti matni; None — BTC pasayishda, diapazon tepasida yoki ma'lumot yo'q
    symbols = universe(abdu)
    alt_filter = cfg.AM_ALT_BTC_FILTER if abdu else cfg.BTC_FILTER
    for sym in symbols:
        is_btc = "BTC" in sym["name"]
        if alt_filter and not is_btc and btc_trend is None:
            print(f"· {sym['name']}: BTC sharti bajarilmadi (4H trend yoki diapazon tepasi) — altkoin signali yo'q")
            continue
        try:
            frames, price = fetch(sym, tfs)
            if is_btc:
                try:
                    btc_trend = btc_gate(frames, price)
                except Exception:
                    btc_trend = None
            sig = analyze_fn(sym["name"], frames, price)
        except Exception:
            print(f"❌ {sym['name']}: xato\n{traceback.format_exc()}")
            continue
        if sig is not None and sym.get("hold") is not None:
            sig.reasons.append(decorrelation_note(sym["hold"], sym.get("rebound") or 0.0))
        if sig is not None and not is_btc and btc_trend:
            sig.reasons.append(f"BTC ham qo'llab-quvvatlaydi: {btc_trend}")
        if sig is None:
            print(f"· {sym['name']}: signal yo'q (narx {price})")
            continue
        sig.frames = frames
        key = getattr(sig, "setup_key", None) or sig.key
        sig.state_key = key
        if key in state:
            print(f"· {sym['name']}: bu setup bo'yicha signal avval yuborilgan, takrorlanmaydi")
            continue
        recent = [v for k, v in state.items() if k.startswith(sig.symbol + "|")]
        if not abdu and recent and time.time() - max(recent) < cfg.SYMBOL_COOLDOWN_HOURS * 3600:
            print(f"· {sym['name']}: yaqinda signal berilgan, kutish vaqti tugamagan")
            continue
        candidates.append(sig)

    # Asosiy (⭐ BTC/ETH) birinchi; Abdu modelida — 🏆 A+ (kichik stop) birinchi
    candidates.sort(key=lambda s: (not s.symbol.startswith("⭐"),
                                   (s.entry - s.stop) / s.entry if abdu else -s.score))
    limit = cfg.AM_MAX_SIGNALS_PER_RUN if abdu else cfg.MAX_SIGNALS_PER_RUN

    # Eski botda: koinlar birga harakatlanadi — yaqinda signal bo'lsa, yangi to'lqin kutiladi.
    # Abdu modelida har bir setup mustaqil (backtest ham shunday) — umumiy kutish yo'q.
    last_any = max(state.values(), default=0)
    if not abdu and candidates and time.time() - last_any < cfg.GLOBAL_COOLDOWN_HOURS * 3600:
        for sig in candidates:
            print(f"· {sig.symbol}: umumiy kutish vaqti ({cfg.GLOBAL_COOLDOWN_HOURS} soat) tugamagan")
        candidates = []
    sent = 0
    for sig in candidates[:limit]:
        if deliver(sig):
            state[sig.state_key] = time.time()
            sent += 1
            print(f"✅ {sig.symbol}: signal yuborildi ({sig.score} ta sabab)")
    for sig in candidates[limit:]:
        print(f"· {sig.symbol}: limit tufayli yuborilmadi ({sig.score} ta sabab)")
    save_state(state)
    print(f"Tayyor. Yuborilgan signallar: {sent}")
    return sent

if __name__ == "__main__":
    run()
