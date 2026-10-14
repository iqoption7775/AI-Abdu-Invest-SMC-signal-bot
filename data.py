"""Bozor ma'lumotlarini olish: Kraken (kripto) va Yahoo Finance (oltin/forex).

Har bir funksiya ustunlari open/high/low/close/volume bo'lgan, UTC vaqt indeksli
pandas DataFrame qaytaradi. Oxirgi (hali yopilmagan) sham olib tashlanadi,
joriy narx esa alohida qaytariladi.
"""
from __future__ import annotations

import time

import pandas as pd
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (AbduInvestBot)"}

# Timeframe -> daqiqa
TF_MINUTES = {"5m": 5, "10m": 10, "15m": 15, "1H": 60, "4H": 240, "1D": 1440, "1W": 10080}
RESAMPLE_RULE = {"10m": "10min", "4H": "4h"}


def _get(url: str, params: dict, retries: int = 3) -> dict:
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=20)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # tarmoq xatosi — biroz kutib qayta urinamiz
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Ma'lumot olinmadi: {url} ({last_err})")


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Kichik shamlarni katta timeframe'ga yig'ish (masalan 5m -> 10m, 1H -> 4H)."""
    out = df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return out.dropna(subset=["open"])


# ---------------------------------------------------------------- Kraken
def _kraken(ticker: str, minutes: int) -> pd.DataFrame:
    js = _get("https://api.kraken.com/0/public/OHLC", {"pair": ticker, "interval": minutes})
    if js.get("error"):
        raise RuntimeError(f"Kraken xatosi: {js['error']}")
    key = next(k for k in js["result"] if k != "last")
    rows = js["result"][key]
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"])
    df["time"] = pd.to_datetime(df["time"].astype(int), unit="s", utc=True)
    df = df.set_index("time")[["open", "high", "low", "close", "volume"]].astype(float)
    return df


def fetch_kraken(ticker: str, tfs: list[str]) -> tuple[dict[str, pd.DataFrame], float]:
    frames: dict[str, pd.DataFrame] = {}
    raw5 = _kraken(ticker, 5)
    price = float(raw5["close"].iloc[-1])
    for tf in tfs:
        if tf == "10m":
            df = resample(raw5, "10min")
        elif tf == "5m":
            df = raw5
        else:
            df = _kraken(ticker, TF_MINUTES[tf])
        frames[tf] = df.iloc[:-1]  # oxirgi sham hali yopilmagan
    return frames, price


# ---------------------------------------------------------------- Yahoo
def _yahoo(ticker: str, interval: str, rng: str) -> pd.DataFrame:
    js = _get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
        {"interval": interval, "range": rng},
    )
    res = js["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame(
        {k: q[k] for k in ["open", "high", "low", "close", "volume"]},
        index=pd.to_datetime(res["timestamp"], unit="s", utc=True),
    )
    return df.dropna(subset=["open", "high", "low", "close"]).astype(float)


def fetch_yahoo(ticker: str, tfs: list[str]) -> tuple[dict[str, pd.DataFrame], float]:
    frames: dict[str, pd.DataFrame] = {}
    raw5 = _yahoo(ticker, "5m", "5d")
    price = float(raw5["close"].iloc[-1])
    plan = {
        "5m": lambda: raw5,
        "10m": lambda: resample(raw5, "10min"),
        "15m": lambda: _yahoo(ticker, "15m", "10d"),
        "4H": lambda: resample(_yahoo(ticker, "60m", "180d"), "4h"),
        "1D": lambda: _yahoo(ticker, "1d", "3y"),
        "1W": lambda: _yahoo(ticker, "1wk", "10y"),
    }
    for tf in tfs:
        frames[tf] = plan[tf]().iloc[:-1]
    return frames, price


def fetch(symbol: dict, tfs: list[str]) -> tuple[dict[str, pd.DataFrame], float]:
    if symbol["source"] == "kraken":
        return fetch_kraken(symbol["ticker"], tfs)
    if symbol["source"] == "yahoo":
        return fetch_yahoo(symbol["ticker"], tfs)
    raise ValueError(f"Noma'lum manba: {symbol['source']}")
