"""AI Abdu Invest — signal bot sozlamalari.

Bu faylni o'zgartirib, juftliklar va strategiya parametrlarini sozlaysiz.
"""

# Kuzatiladigan juftliklar.
#   source="kraken" -> kripto (Kraken birjasining ochiq ma'lumoti, kalit shart emas)
#   source="yahoo"  -> oltin, forex, indekslar (Yahoo Finance)
SYMBOLS = [
    {"name": "BTC/USD", "source": "kraken", "ticker": "XBTUSD"},
    {"name": "ETH/USD", "source": "kraken", "ticker": "ETHUSD"},
    {"name": "SOL/USD", "source": "kraken", "ticker": "SOLUSD"},
    {"name": "XAU/USD (Oltin)", "source": "yahoo", "ticker": "GC=F"},
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

ZONE_TOUCH_HOURS = 3      # Narx zonaga oxirgi necha soat ichida tekkan bo'lishi kerak
BREAK_LOOKBACK_HOURS = 3  # BOS/CHoCH oxirgi necha soat ichida bo'lgan bo'lishi kerak
SWING_LEN = 2             # Swing high/low aniqlash uchun har ikki tomondagi shamlar soni
STOP_BUFFER_ATR = 0.15    # Stop past swing low dan qancha pastroq (5m ATR ulushida)
MAX_ZONES_PER_TF = 6      # Har bir timeframe'dan eng yangi nechta zona olinadi

SYMBOL_COOLDOWN_HOURS = 4 # Bitta juftlikdan signaldan keyin kamida shuncha soat yangi signal yo'q
TIMEZONE = "Asia/Tashkent"
BRAND = "AI Abdu Invest"
