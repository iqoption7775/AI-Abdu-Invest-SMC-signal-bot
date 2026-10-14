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

MIN_RR = 3.0              # Risk/Reward kamida 1:3
MIN_REASONS = 3           # Kamida nechta sabab bir vaqtda mos kelsa signal chiqadi
SR_MIN_TOUCHES = 2        # Support/Resistance zonasi uchun kamida necha marta tegish
MAX_TARGETS = 3           # Nechta take-profit ko'rsatiladi
MIN_STOP_ATR_4H = 0.3     # Stop kirishdan kamida 0.3×ATR(4H) pastda (shovqindan himoya)
BLOCKING_TFS = ["1W", "1D"]  # Shu TF'dagi taklif zonasi (bearish FVG/OB, resistance) ...
BLOCK_WITHIN_R = 1.0      # ... kirishdan 1R ichida yoki narx uning ichida bo'lsa — signal yo'q
MAX_SIGNALS_PER_RUN = 3   # Bir tekshiruvda ko'pi bilan nechta signal (BTC/ETH birinchi, keyin eng kuchlilari)

ZONE_TOUCH_HOURS = 3      # Narx zonaga oxirgi necha soat ichida tekkan bo'lishi kerak
BREAK_LOOKBACK_HOURS = 3  # BOS/CHoCH oxirgi necha soat ichida bo'lgan bo'lishi kerak
SWING_LEN = 2             # Swing high/low aniqlash uchun har ikki tomondagi shamlar soni
STOP_BUFFER_ATR = 0.15    # Stop past swing low dan qancha pastroq (5m ATR ulushida)
MAX_ZONES_PER_TF = 6      # Har bir timeframe'dan eng yangi nechta zona olinadi

SYMBOL_COOLDOWN_HOURS = 4 # Bitta juftlikdan signaldan keyin kamida shuncha soat yangi signal yo'q
TIMEZONE = "Asia/Tashkent"
BRAND = "AI Abdu Invest"
