"""
data_loader.py — Institutional-grade crypto data loader.
Fetches 4 years of daily OHLCV data for BTC-USD and ETH-USD via yfinance.
"""

import datetime as dt
import time

import pandas as pd
import yfinance as yf

TICKERS = ["BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "LINK-USD", "SUI20947-USD", "XRP-USD",
           "ZEC-USD", "NEAR-USD", "HYPE32196-USD", "VVV-USD"]
ANCHOR_START = dt.date(2022, 3, 1)  # Fixed start date — never shifts


def fetch_data(
    tickers: list[str] = TICKERS,
) -> dict[str, pd.DataFrame]:
    """
    Download daily OHLCV data for each ticker.

    Uses a fixed start date so adding new days never drops early data,
    keeping walk-forward fold boundaries and HMM training windows stable.

    Returns
    -------
    dict mapping ticker -> DataFrame with columns
    [Open, High, Low, Close, Volume] and a DatetimeIndex.
    """
    end = dt.date.today()
    start = ANCHOR_START

    data: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        # Retry with backoff if Yahoo rate-limits us
        for attempt in range(3):
            df = yf.download(
                ticker,
                start=start.isoformat(),
                end=end.isoformat(),
                auto_adjust=True,
                progress=False,
            )
            # yfinance may return MultiIndex columns; flatten if needed
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            if not df.empty:
                break
            time.sleep(2 ** attempt)  # 1s, 2s, 4s

        if df.empty:
            # Yahoo has no data (unknown symbol / rate-limited): fall back to
            # Hyperliquid's own daily candles so one bad ticker can't break
            # the whole run.
            try:
                from intraday_data_loader import fetch_candles
                df = fetch_candles(ticker, interval="1d", lookback_hours=24 * 4000)
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
                if not df.empty:
                    print(f"{ticker}: Yahoo returned nothing; using Hyperliquid daily candles ({len(df)} rows)")
            except Exception as e:
                print(f"{ticker}: Hyperliquid candle fallback failed: {e}")

        if df.empty:
            print(f"WARNING: no data for {ticker}; skipping it this run")
            continue

        df.index.name = "Date"
        data[ticker] = df

    if not data:
        raise RuntimeError("No data returned for any ticker (likely rate-limited)")
    return data


if __name__ == "__main__":
    for sym, df in fetch_data().items():
        print(f"{sym}: {len(df)} rows  [{df.index[0].date()} → {df.index[-1].date()}]")
