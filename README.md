# AI Abdu Invest — Signal Bot

Har soatda bozorni avtomatik tahlil qilib, @Abduinvestbot orqali Telegram'ga BUY signallarini yuboradi.
Server shart emas — GitHub Actions'da bepul ishlaydi, Claude limitini sarflamaydi.

## Strategiya

Bot hamma sabablarni kutmaydi: **istalgan 3 ta sabab bir vaqtda mos kelsa** signal beradi
(`config.py` dagi `MIN_REASONS`).

**Majburiy shartlar** (bularsiz signal yo'q):
1. Narx biror talab hududiga tekkan — FVG, Order Block, Support, Fibonacci OTE yoki **katta likvidlik olingan joy (bank buy zonasi)** — 1W / 1D / 4H, qaysi biri bo'lsa ham.
2. Zonaga tekkandan keyin 5m / 10m / 15m da **CHoCH yoki BOS** tasdig'i.
3. **Oxirgi TP kamida 1:3 RR.**

**Kirish / stop / TP (treyder modeli):**
- **Kirish** — zona tepasida (narx zonadan chiqib ketgan bo'lsa — limit), zona ichida bo'lsa — joriy narx.
- **Stop** — zona **ostida** (kengligi ≤ 3×ATR(4H) bo'lgan 4H/1D FVG, OB yoki support), kamida 0.75×ATR(4H).
- TP soni vaziyatga qarab **1–3 ta**: **TP1** — eng yaqin qarshilik (≥ 1R, qisman foyda), **TP2** — oraliq likvidlik (faqat alohida daraja bo'lsa), oxirgi TP — birinchi ≥ 1:3 maqsad.
  High va likvidlik darajalariga TP biroz oldinroq qo'yiladi.

**Sabablar** (har biri 1 ta; majburiy zona va tasdiq ham sabab hisoblanadi):
- Bullish FVG / Order Block (1W, 1D, 4H)
- Support zonasi (1D, 4H) — kamida 2 marta tegilgan; S/R flip bo'lsa belgilanadi
- Fibonacci OTE 0.618–0.786 (1D, 4H); FVG/OB bilan ustma-ust bo'lsa — golden zone
- CHoCH / BOS tasdig'i, bir nechta timeframe'da tasdiq
- **Katta likvidlik olinishi (bank buy zonasi):** PDL (oldingi kun low'i), PWL (oldingi hafta low'i),
  1D/4H swing low'lar va teng low'lar (EQL). Shart: hovuz shu paytgacha olinmagan, narx soya bilan
  ostiga tushib stoplarni urgan va qaytib ustida yopilgan. Yaqin hovuzlar birlashtiriladi.
- **Klassik SMC modeli:** likvidlik olindi → CHoCH — alohida sabab sifatida qo'shiladi
- Kichik likvidlik (15m oldingi low yoki support ostidagi stoplar) — katta hovuz olinmagan bo'lsa
- Zonada kuchli rad etish shami (uzun pastki soya)
- Psixologik yumaloq darajadan qaytish
- Narx 4H EMA50 ustida, narx 1D diapazonning discount qismida

**Kuch:** 3 sabab — O'rta, 4–5 — Kuchli, 6+ — Juda kuchli.
Bitta tasdiq bo'yicha signal bir marta yuboriladi; bitta juftlikdan 4 soat, umuman esa 2 soat ichida yangi signal chiqmaydi;
bir martada ko'pi bilan 2 ta signal (⭐ BTC/ETH birinchi). 1W/1D taklif zonasi kirishdan 1R ichida bo'lsa — signal yo'q.

Juftliklar va qoidalar `config.py` da o'zgartiriladi (⭐ BTC, ⭐ ETH + 11 ta altkoin).

## O'rnatish (telefondan ~10 daqiqa)

1. **GitHub'da yangi repozitoriy** oching (Private) va bu fayllarni yuklang.
2. **Telegram ma'lumotlari** — repozitoriyda: *Settings → Secrets and variables → Actions → New repository secret*:
   - `TELEGRAM_BOT_TOKEN` — @BotFather → /mybots → @Abduinvestbot → API Token
   - `TELEGRAM_CHAT_ID` — signallar boradigan joy:
     - kanal uchun: botni kanalga **admin** qiling va `@kanal_nomi` yozing
     - shaxsiy chat uchun: botga /start yuboring, ID'ingizni @userinfobot dan oling
3. **Sinash:** *Actions → AI Abdu Invest signallari → Run workflow*. Loglarda har juftlik natijasi ko'rinadi.

Shundan keyin bot har soatda o'zi ishlaydi.

## Bilish muhim

- Private repozitoriyda GitHub oyiga 2000 daqiqa bepul beradi; bot oyiga ~720 daqiqa ishlatadi.
- GitHub rejali ishlarni ba'zan 5–15 daqiqa kechiktiradi.
- Repozitoriyda 60 kun hech qanday o'zgarish bo'lmasa, GitHub jadvalni to'xtatadi — Actions sahifasida qayta yoqiladi.
- Lokal sinov: `pip install -r requirements.txt && python -m pytest -q` (yoki `python tests/test_bot.py`).

⚠️ Signallar moliyaviy maslahat emas. Har bir savdoda riskni o'zingiz boshqaring.
