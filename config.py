"""AI Abdu Invest — signal bot sozlamalari.

Bu faylni o'zgartirib, juftliklar va strategiya parametrlarini sozlaysiz.
"""

# Kuzatiladigan juftliklar.
#   source="kraken" -> kripto (Kraken birjasining ochiq ma'lumoti, kalit shart emas)
SYMBOLS = [
    # Asosiy
    {"name": "⭐ BTC/USD", "source": "kraken", "ticker": "XBTUSD"},
    {"name": "⭐ ETH/USD", "source": "kraken", "ticker": "ETHUSD"},
    # Qo'shimcha
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
BLOCKING_TFS = ["1W", "1D"]  # Shu TF'dagi taklif zonasi (bearish FVG/OB, resistance) ...
BLOCK_WITHIN_R = 1.0      # ... kirishdan 1R ichida yoki narx uning ichida bo'lsa — signal yo'q
MAX_SIGNALS_PER_RUN = 2   # Bir tekshiruvda ko'pi bilan nechta signal (BTC/ETH birinchi, keyin eng kuchlilari)
GLOBAL_COOLDOWN_HOURS = 2 # Har qanday signaldan keyin shuncha soat yangi signal yo'q (koinlar birga harakatlanadi)

ZONE_TOUCH_HOURS = 3      # Narx zonaga oxirgi necha soat ichida tekkan bo'lishi kerak
BREAK_LOOKBACK_HOURS = 3  # BOS/CHoCH oxirgi necha soat ichida bo'lgan bo'lishi kerak
SWING_LEN = 2             # Swing high/low aniqlash uchun har ikki tomondagi shamlar soni
MAX_ZONES_PER_TF = 6      # Har bir timeframe'dan eng yangi nechta zona olinadi

SYMBOL_COOLDOWN_HOURS = 4 # Bitta juftlikdan signaldan keyin kamida shuncha soat yangi signal yo'q
TIMEZONE = "Asia/Tashkent"
BRAND = "AI Abdu Invest"
