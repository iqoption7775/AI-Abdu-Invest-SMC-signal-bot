"""AI Abdu Invest — signal bot sozlamalari.

Bu faylni o'zgartirib, juftliklar va strategiya parametrlarini sozlaysiz.
"""

# Kuzatiladigan juftliklar.
#   source="kraken" -> kripto (Kraken birjasining ochiq ma'lumoti, kalit shart emas)
SYMBOLS = [
    # Asosiy
    {"name": "⭐ BTC/USD", "source": "kraken", "ticker": "XBTUSD"},
    {"name": "⭐ ETH/USD", "source": "kraken", "ticker": "ETHUSD"},
]
# Qo'shimcha 11 ta koin — hammasi tahlil qilinadi (faqat BTC/ETH kerak bo'lsa — pastdagi `SYMBOLS += EXTRA_SYMBOLS` qatorini o'chiring)
EXTRA_SYMBOLS = [
    {"name": "SOL/USD", "source": "kraken", "ticker": "SOLUSD"},
    {"name": "XRP/USD", "source": "kraken", "ticker": "XRPUSD"},
    {"name": "ADA/USD", "source": "kraken", "ticker": "ADAUSD"},
    {"name": "AVAX/USD", "source": "kraken", "ticker": "AVAXUSD"},
    {"name": "LINK/USD", "source": "kraken", "ticker": "LINKUSD"},
    {"name": "DOT/USD", "source": "kraken", "ticker": "DOTUSD"},
    {"name": "LTC/USD", "source": "kraken", "ticker": "LTCUSD"},
    {"name": "XLM/USD", "source": "kraken", "ticker": "XLMUSD"},
    {"name": "NEAR/USD", "source": "kraken", "ticker": "NEARUSD"},
    {"name": "ATOM/USD", "source": "kraken", "ticker": "ATOMUSD"},
    {"name": "ALGO/USD", "source": "kraken", "ticker": "ALGOUSD"},
]
SYMBOLS += EXTRA_SYMBOLS

# --- Strategiya qoidalari ---
HTF_TIMEFRAMES = ["1W", "1D", "4H"]     # FVG va Order Block zonalari shu yerdan
LTF_TIMEFRAMES = ["5m", "10m", "15m"]   # BOS / CHoCH tasdig'i shu yerdan
SR_TIMEFRAMES = ["1D", "4H"]         # Support / Resistance zonalari shu yerdan
FIB_TIMEFRAMES = ["1D", "4H"]        # Fibonacci OTE (0.618–0.786) shu impulslardan

MIN_RR = 3.0              # Oxirgi TP kamida 1:3 RR (TP1/TP2 — oraliq, qisman foyda)
MIN_TP1_RR = 1.0          # TP1 kamida 1R masofada
MIN_TP_GAP_R = 0.5        # TP'lar orasida kamida 0.5R — yo'q bo'lsa TP soni kamayadi (1–3 ta, vaziyatga qarab)
ANCHOR_MAX_ATR_4H = 3.0   # Stop shu zona ostiga qo'yiladi: kengligi ≤ 3×ATR(4H) bo'lgan FVG/OB/support
STOP_BELOW_ZONE_ATR_4H = 0.1  # Stop zona pastidan 0.1×ATR(4H) pastda
FRONTRUN_ATR_4H = 0.1     # TP high/likvidlikdan 0.1×ATR(4H) oldinroq (to'lishi uchun)
MIN_REASONS = 3           # Kamida nechta sabab bir vaqtda mos kelsa signal chiqadi
SR_MIN_TOUCHES = 2        # Support/Resistance zonasi uchun kamida necha marta tegish
MAX_TARGETS = 3           # Nechta take-profit ko'rsatiladi
MIN_STOP_ATR_4H = 0.75    # Stop kirishdan kamida 0.75×ATR(4H) pastda (shovqindan himoya)
STOP_BELOW_LOW_ATR_4H = 0.15  # Stop zona reaksiyasining eng past nuqtasidan 0.15×ATR(4H) pastda
WIDE_ZONE_ATR_4H = 1.5    # Zona bundan keng bo'lsa, narx uning yarmigacha (CE) tushgan bo'lishi shart
BLOCKING_TFS = ["1W", "1D", "4H"]  # Shu TF'dagi taklif zonasi (bearish FVG/OB, resistance) ...
BLOCK_WITHIN_R = 1.0      # ... kirishdan 1R ichida yoki narx uning ichida bo'lsa — signal yo'q
MAX_SIGNALS_PER_RUN = 2   # Bir tekshiruvda ko'pi bilan nechta signal (BTC/ETH birinchi, keyin eng kuchlilari)
GLOBAL_COOLDOWN_HOURS = 2 # Har qanday signaldan keyin shuncha soat yangi signal yo'q (koinlar birga harakatlanadi)

REQUIRE_4H_UPTREND = True  # Pasayish trendida buy yo'q: narx 4H EMA50 ustida va EMA50 ko'tarilmoqda,
                           # yoki so'nggi TREND_CHOCH_4H_BARS ta 4H shamda bullish CHoCH/BOS bo'lgan
TREND_CHOCH_4H_BARS = 6    # 6 ta 4H sham = 1 sutka
BTC_FILTER = True          # Altkoinlarga signal faqat BTC 4H trend yuqoriga bo'lganda (altlar BTC ortidan yuradi)
# --- 22-oktabr tuzatishlari (backtest, 60 kun: hozirgi bot −16.4R → D varianti +4.9R) ---
BTC_RANGE_FILTER = False   # True: altlarga faqat BTC diapazonining pastki qismida (backtest: juda qattiq, 60 kunda 7 signal)
BTC_RANGE_DAYS = 14        # BTC diapazoni: oxirgi 14 kunlik high/low
BTC_RANGE_MAX = 0.5        # BTC diapazonning pastki 50% ida bo'lishi kerak
REQUIRE_15M = True         # CHoCH/BOS 15m da ham bo'lishi shart (faqat 5m — signal yo'q)
MAX_ZONE_ATR_4H = 3.0      # Kengligi 3×ATR(4H) dan katta FVG/OB/OTE zona hisoblanmaydi
REQUIRE_SWEEP = True       # Klassik SMC: likvidlik olinishi (sweep) majburiy, CHoCH/BOS undan keyin bo'lishi shart
SR_LIQUIDITY_TOUCHES = 3   # Shuncha va ko'p tegilgan support — likvidlik: faqat sweep'dan keyin kirish
LIQ_NEAR_STOP_ATR_4H = 0.3 # Stopdan shu masofadagi urilmagan likvidlik bo'lsa — stop uning ostiga tushadi (zanjir bo'lib)
STOP_POOLS_1H_HOURS = 24  # Stop tekshiruvida oxirgi 24 soatdagi 1H swing low'lar hisobga olinadi
STOP_ZONE_TFS = ["4H"]     # Stop to'ldirilmagan 4H bullish FVG/OB ichida yoki tepasida qolmaydi — ostiga tushadi
STOP_MAX_PUSH_ATR_4H = 1.0 # Likvidlik/FVG uchun stop ko'pi bilan 1×ATR(4H) pastga suriladi; ko'proq kerak bo'lsa — signal yo'q
MAX_LIMIT_DIST_ATR_4H = 2.0  # Ostdagi FVG/OB narxdan ≤ 2×ATR(4H) da bo'lsa — kirish o'sha zona tepasida (limit)

ZONE_TOUCH_HOURS = 3      # Narx zonaga oxirgi necha soat ichida tekkan bo'lishi kerak
BREAK_LOOKBACK_HOURS = 3  # BOS/CHoCH oxirgi necha soat ichida bo'lgan bo'lishi kerak
SWING_LEN = 2             # Swing high/low aniqlash uchun har ikki tomondagi shamlar soni
MAX_ZONES_PER_TF = 6      # Har bir timeframe'dan eng yangi nechta zona olinadi

SYMBOL_COOLDOWN_HOURS = 4 # Bitta juftlikdan signaldan keyin kamida shuncha soat yangi signal yo'q
SIGNAL_CHART = True       # signal grafik rasm bilan yuboriladi (kirish/stop/TP, OB, FVG, likvidlik, CHoCH)
TIMEZONE = "Asia/Tashkent"
BRAND = "AI Abdu Invest"

# --- ABDU MODELI (abdu_model.py) — treyderning o'z strategiyasi, 0 dan ---
STRATEGY = "abdu"           # "abdu" — Abdu modeli (23-oktabrdan jonli); "v1" — eski SMC bot
AM_TIMEFRAMES = ["1H", "4H", "12H", "1D", "1W"]
AM_TOP_STOP_PCT = 3.5       # stop ≤ 3.5% — 🏆 A+ setup (backtest: 75% g'alaba), 3.5–5% — 🥈 A setup
AM_MAX_STOP_PCT = 5.0       # stop 5% dan katta bo'lsa — signal yo'q (oxirgi TP har doim ≥ 3R: stop 5% → TP ≥ 15%)
AM_MAX_OPEN_RISK = 3       # bir vaqtda ko'pi bilan 3 ta ochiq xavf (backtest 90 kun: stop 8 → 4, +14.0R → +16.4R); 0 — cheklovsiz
AM_MAX_SIGNALS_PER_RUN = 4  # bir tekshiruvda ko'pi bilan nechta signal (backtestda cheklov yo'q edi)
# Koinlar ro'yxati (29-oktabr backtesti bo'yicha tanlandi: 13 koin + BTC filtri — 75%, +15.4R / 90 kun):
#   "fixed+screener" — yuqoridagi 13 koin + skrener topgan BTC ga kam ergashadigan halol koinlar (screener.json,
#                      har dushanba yangilanadi; shartdan o'tgan koin bo'lmasa — faqat 13 koin)
#   "fixed"          — faqat 13 koin;  "screener" — ⭐ BTC + ⭐ ETH + skrener koinlari
AM_UNIVERSE = "fixed+screener"
AM_ALT_BTC_FILTER = True    # altkoinlarga signal faqat BTC 4H sharti bajarilganda (backtest: stoplar 19 → 6)
# Discount → sell-side sweep → 1H CHoCH → 4H OB + 1H FVG → retestda limit BUY
AM_SWING_N = 2              # swing high/low: har ikki tomonda 2 tadan sham
AM_SWEEP_LOOKBACK_4H = 18   # sweep oxirgi 18 ta 4H sham (3 sutka) ichida bo'lgan bo'lishi kerak
AM_POOL_LOOKBACK_4H = 90    # olinadigan 4H swing low oxirgi 90 sham (15 sutka) ichidan
AM_SWEEP_SPAN_4H = 3       # hovuz sweep low dan ko'pi bilan 3 ta 4H sham oldin sinilgan bo'lishi kerak
AM_USE_DISCOUNT = True      # sweep discount zonada bo'lishi shart
AM_DISCOUNT_DAYS = 30       # discount: 1D oxirgi 30 kunlik diapazon
AM_DISCOUNT_MAX = 0.5       # sweep low diapazonning pastki 50% ida
AM_FVG_MIN_ATR = 0.1        # 1H FVG kamida 0.1×ATR(1H) kenglikda
AM_ENTRY = "fvg_top"        # kirish: fvg_top | fvg_ce (FVG o'rtasi) | ob_top (4H OB tepasi)
AM_STOP_BUF_ATR = 0.15      # stop sweep low / OB ostidan 0.15×ATR(4H) pastda
AM_MIN_RR = 3.0             # oxirgi TP kamida 1:3
AM_BLOCK_SUPPLY_R = 0.0     # >0: kirishdan shuncha R ichida taklif zonasi bo'lsa — signal yo'q
