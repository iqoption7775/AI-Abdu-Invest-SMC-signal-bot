"""Signalni chiroyli formatlab, Telegram'ga yuborish."""
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

import config as cfg
from strategy import Signal, fmt


def format_signal(s: Signal) -> str:
    risk_pct = (s.entry - s.stop) / s.entry * 100
    now = datetime.now(ZoneInfo(cfg.TIMEZONE)).strftime("%d.%m.%Y %H:%M")
    lines = [
        f"🟢 <b>BUY SIGNAL — {s.symbol}</b>",
        f"<i>{cfg.BRAND}</i>",
        "",
        f"📍 <b>Kirish:</b> {fmt(s.entry)}" + ("  (limit — zona tepasi)" if s.limit else ""),
        f"🛑 <b>Stop:</b> {fmt(s.stop)}  (−{risk_pct:.2f}%)",
    ]
    if s.stop_reason:
        lines.append(f"      └ {s.stop_reason}")
    for i, t in enumerate(s.targets, 1):
        pct = (t.price - s.entry) / s.entry * 100
        note = "  — qisman foyda" if i == 1 and len(s.targets) > 1 else ""
        lines.append(f"🎯 <b>TP{i}:</b> {fmt(t.price)}  (+{pct:.2f}% · RR 1:{t.rr:.1f}){note}")
        lines.append(f"      └ {t.reason}")
    lines += ["", f"💪 <b>Kuch:</b> {s.strength} — {s.score} ta sabab mos keldi", "", "🧠 <b>Sabablar:</b>"]
    lines += [f"• {r}" for r in s.reasons]
    if s.obstacles:
        lines += ["", "🚧 <b>TP1 gacha qarshilik</b> (qisman foyda olish mumkin):"]
        lines += [f"• {z.label()} — {fmt(z.bottom)}" for z in s.obstacles[:3]]
    lines += [
        "",
        f"🕐 {now} (Toshkent)",
        "🔎 <i>Savdoga kirishdan oldin o'zingiz ham qo'shimcha tahlil qilishingizni tavsiya qilamiz.</i>",
        "⚠️ <i>Moliyaviy maslahat emas. Riskni o'zingiz boshqaring.</i>",
    ]
    return "\n".join(lines)


def send(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[DRY RUN] Telegram sozlanmagan, xabar faqat chop etildi:\n" + text)
        return False
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=20,
    )
    if not r.ok:
        print(f"Telegram xatosi {r.status_code}: {r.text[:300]}")
    return r.ok
