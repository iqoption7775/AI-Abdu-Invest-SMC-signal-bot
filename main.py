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
from strategy import analyze
from telegram import format_signal, send

STATE_FILE = Path(__file__).with_name("state.json")


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    week_ago = time.time() - 7 * 24 * 3600
    state = {k: v for k, v in state.items() if v > week_ago}  # eski yozuvlarni tozalash
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def run() -> int:
    state = load_state()
    tfs = cfg.HTF_TIMEFRAMES + cfg.LTF_TIMEFRAMES
    candidates = []
    for sym in cfg.SYMBOLS:
        try:
            frames, price = fetch(sym, tfs)
            sig = analyze(sym["name"], frames, price)
        except Exception:
            print(f"❌ {sym['name']}: xato\n{traceback.format_exc()}")
            continue
        if sig is None:
            print(f"· {sym['name']}: signal yo'q (narx {price})")
            continue
        if sig.key in state:
            print(f"· {sym['name']}: bu signal avval yuborilgan, takrorlanmaydi")
            continue
        recent = [v for k, v in state.items() if k.startswith(sig.symbol + "|")]
        if recent and time.time() - max(recent) < cfg.SYMBOL_COOLDOWN_HOURS * 3600:
            print(f"· {sym['name']}: yaqinda signal berilgan, kutish vaqti tugamagan")
            continue
        candidates.append(sig)

    # Asosiy (⭐ BTC/ETH) birinchi, keyin sabablari ko'p bo'lganlari
    candidates.sort(key=lambda s: (not s.symbol.startswith("⭐"), -s.score))
    sent = 0
    for sig in candidates[: cfg.MAX_SIGNALS_PER_RUN]:
        if send(format_signal(sig)):
            state[sig.key] = time.time()
            sent += 1
            print(f"✅ {sig.symbol}: signal yuborildi ({sig.score} ta sabab)")
    for sig in candidates[cfg.MAX_SIGNALS_PER_RUN:]:
        print(f"· {sig.symbol}: limit tufayli yuborilmadi ({sig.score} ta sabab)")
    save_state(state)
    print(f"Tayyor. Yuborilgan signallar: {sent}")
    return sent

if __name__ == "__main__":
    run()
