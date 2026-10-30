"""Signalni chiroyli formatlab, Telegram'ga yuborish."""
from __future__ import annotations

import os

import requests

import config as cfg
from strategy import Signal, fmt


def reason_count(s: Signal) -> int:
    """Mos kelgan sabablar soni (kirish usuli sabab hisoblanmaydi)."""
    return sum(1 for r in s.reasons if not r.startswith("Kirish:"))


def grade(s: Signal) -> str:
    """Signal kuchi. Abdu modeli: stop hajmi bo'yicha (backtestda kichik stopli setuplar ko'proq foyda bergan)."""
    if getattr(s, "badge", None) is None:
        return {"Juda kuchli": "🔥 Juda kuchli", "Kuchli": "💪 Kuchli"}.get(s.strength, "⚖️ O'rta")
    risk_pct = (s.entry - s.stop) / s.entry * 100
    return "🏆 A+ — kuchli" if risk_pct <= cfg.AM_TOP_STOP_PCT else "🥈 A — o'rta, riskni kamaytiring"


def format_signal(s: Signal) -> str:
    """Qisqa signal matni (grafik rasmining izohi). Sabablar yozilmaydi — faqat soni va signal kuchi."""
    risk_pct = (s.entry - s.stop) / s.entry * 100
    lines = [
        f"🟢 <b>BUY — {s.symbol}</b>  ·  <i>{cfg.BRAND}</i>",
        "",
        f"📍 Kirish: <b>{fmt(s.entry)}</b>" + ("  (limit)" if s.limit else ""),
        f"🛑 Stop: <b>{fmt(s.stop)}</b>  (−{risk_pct:.2f}%)",
    ]
    for i, t in enumerate(s.targets, 1):
        pct = (t.price - s.entry) / s.entry * 100
        rr = f"  · RR 1:{t.rr:.1f}" if i == len(s.targets) else ""
        lines.append(f"🎯 TP{i}: <b>{fmt(t.price)}</b>  (+{pct:.2f}%){rr}")
    lines += [
        "",
        f"💪 Kuch: <b>{grade(s)}</b>  ·  {reason_count(s)} ta sabab mos keldi",
    ]
    if len(s.targets) > 1:
        lines.append("📌 TP1 da 50% yoping, stopni kirishga ko'chiring" + (" · limit 48 soat" if s.limit else ""))
    lines.append("🔎 <i>O'zingiz ham tahlil qiling. Moliyaviy maslahat emas.</i>")
    return "\n".join(lines)


def send(text: str, photo: bytes | None = None) -> bool:
    """Matn yoki grafik rasm + izoh. Rasm yuborilmasa — oddiy matn bilan qayta urinadi."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[DRY RUN] Telegram sozlanmagan, xabar faqat chop etildi" + (" (grafik bilan)" if photo else "") + ":\n" + text)
        return False
    api = f"https://api.telegram.org/bot{token}"
    if photo and len(text) <= 1024:
        r = requests.post(f"{api}/sendPhoto", data={"chat_id": chat_id, "caption": text, "parse_mode": "HTML"},
                          files={"photo": ("signal.png", photo, "image/png")}, timeout=40)
        if r.ok:
            return True
        print(f"Telegram rasm xatosi {r.status_code}: {r.text[:300]} — matn yuboriladi")
    r = requests.post(
        f"{api}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=20,
    )
    if not r.ok:
        print(f"Telegram xatosi {r.status_code}: {r.text[:300]}")
    return r.ok
