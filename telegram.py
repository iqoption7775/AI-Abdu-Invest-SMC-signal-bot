"""Signalni chiroyli formatlab, Telegram'ga yuborish (shaxsiy chat + bot qo'shilgan guruh/kanallar)."""
from __future__ import annotations

import json
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


GROUPS = "_guruhlar"       # state.json ichida: signal yuboriladigan guruh/kanallar {chat_id: turi}
_groups: list[str] = []    # shu ishga tushirishda yuboriladigan guruhlar (sync_groups to'ldiradi)


def _creds() -> tuple[str | None, str | None]:
    return os.getenv("TELEGRAM_BOT_TOKEN"), (os.getenv("TELEGRAM_CHAT_ID") or "").strip() or None


def sync_groups(state: dict) -> list[tuple[str, str, str]]:
    """Bot qo'shilgan guruh/kanallarni Telegram'dan o'zi topadi.
    Faqat egasi (TELEGRAM_CHAT_ID dagi foydalanuvchi) qo'shgan guruhlar olinadi — begona guruhlarga signal ketmaydi.
    Bot guruhdan chiqarilsa — ro'yxatdan o'chadi. Qaytaradi: yangi ulangan [(chat_id, nomi, turi)]."""
    global _groups
    token, owner = _creds()
    groups = dict(state.get(GROUPS, {}))
    new: list[tuple[str, str, str]] = []
    if token and owner:
        api = f"https://api.telegram.org/bot{token}"
        try:
            js = requests.get(f"{api}/getUpdates", timeout=20, params={
                "timeout": 0, "allowed_updates": json.dumps(["my_chat_member", "message", "channel_post"])}).json()
        except Exception as e:
            js = {"ok": False, "description": str(e)}
        if not js.get("ok"):
            print(f"Guruhlarni tekshirib bo'lmadi: {js.get('description', js)}")
        last = None
        for u in js.get("result", []) if js.get("ok") else []:
            last = u["update_id"]
            m = u.get("my_chat_member")
            if m and m["chat"]["type"] != "private":
                cid, status = str(m["chat"]["id"]), m["new_chat_member"]["status"]
                if status in ("administrator", "member") and str(m["from"]["id"]) == owner:
                    if cid not in groups:
                        groups[cid] = m["chat"]["type"]
                        new.append((cid, m["chat"].get("title", ""), m["chat"]["type"]))
                elif status in ("left", "kicked") and cid in groups:
                    del groups[cid]
                    print(f"Bot guruhdan chiqarildi: {cid}")
            msg = u.get("message") or {}
            old = str(msg.get("chat", {}).get("id", ""))
            if msg.get("migrate_to_chat_id") and old in groups:     # guruh supergroup'ga aylandi — ID o'zgaradi
                groups[str(msg["migrate_to_chat_id"])] = "supergroup"
                del groups[old]
        if last is not None:  # o'qilgan yangilanishlarni tasdiqlash
            try:
                requests.get(f"{api}/getUpdates", params={"offset": last + 1, "timeout": 0}, timeout=20)
            except Exception:
                pass
    if groups:
        state[GROUPS] = groups
    else:
        state.pop(GROUPS, None)
    _groups = [g for g in groups if g != owner]
    return new


def _send_one(api: str, chat_id: str, text: str, photo: bytes | None) -> bool:
    if photo and len(text) <= 1024:
        r = requests.post(f"{api}/sendPhoto", data={"chat_id": chat_id, "caption": text, "parse_mode": "HTML"},
                          files={"photo": ("signal.png", photo, "image/png")}, timeout=40)
        if r.ok:
            return True
        print(f"Telegram rasm xatosi ({chat_id}) {r.status_code}: {r.text[:300]} — matn yuboriladi")
    r = requests.post(f"{api}/sendMessage", timeout=20, json={
        "chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
    if not r.ok:
        print(f"Telegram xatosi ({chat_id}) {r.status_code}: {r.text[:300]}")
    return r.ok


def send(text: str, photo: bytes | None = None, only: list[str] | None = None) -> bool:
    """Matn yoki grafik rasm + izoh: egasiga (TELEGRAM_CHAT_ID) va bot qo'shilgan guruh/kanallarga.
    Rasm yuborilmasa — oddiy matn bilan qayta urinadi. Kamida bittasiga yetsa — True."""
    token, owner = _creds()
    targets = only if only is not None else ([owner] if owner and cfg.SEND_TO_OWNER else []) + _groups
    if not token or not targets:
        print("[DRY RUN] Telegram sozlanmagan, xabar faqat chop etildi" + (" (grafik bilan)" if photo else "") + ":\n" + text)
        return False
    api = f"https://api.telegram.org/bot{token}"
    ok = False
    for chat_id in targets:
        try:
            ok = _send_one(api, chat_id, text, photo) or ok
        except Exception as e:
            print(f"Telegram ({chat_id}) yuborilmadi: {e}")
    return ok
