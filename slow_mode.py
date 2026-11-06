"""
slow_mode.py — optional "slow" mode for the aggressive bot (OFF by default).

Backtests (backtest_replay.py / backtest_round2.py) showed the 30-minute
oscillator churns: most losses came from short trades and oscillator-flip
exits. Slow mode keeps the same strategy but:

  * computes signals on completed 2-hour bars (resampled from 30-min candles)
  * a new entry can only fire once per newly closed bar
  * longs only when price is above its ~5-day average, shorts only when below
  * ignores oscillator-flip exits; positions leave via the profit-protection
    rules (break-even / trailing / hard stop) or a time stop (default 72h)

Enable with the GitHub repo Variable  AGGRESSIVE_MODE = slow
Revert with AGGRESSIVE_MODE = classic (or delete the variable).

Optional Variables (defaults shown):
    SLOW_BAR_HOURS 2        SLOW_OSC_THR 0.25      SLOW_MAX_HOLD_H 72
    SLOW_TREND_HOURS 120    SLOW_MAX_SAME_DIR 0 (0 = no cap)
"""

import datetime as dt
import math
import os

import pandas as pd


def _f(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(str(raw).strip())
    except ValueError:
        print(f"WARNING: {name}={raw!r} is not a number; using default {default}")
        return default


def enabled() -> bool:
    return os.environ.get("AGGRESSIVE_MODE", "classic").strip().lower() == "slow"


def settings() -> dict:
    return {
        "bar_hours": _f("SLOW_BAR_HOURS", 2.0),
        "osc_thr": _f("SLOW_OSC_THR", 0.25),
        "max_hold_h": _f("SLOW_MAX_HOLD_H", 72.0),
        "trend_hours": _f("SLOW_TREND_HOURS", 120.0),
        "max_same_dir": int(_f("SLOW_MAX_SAME_DIR", 0)),
    }


def utc_now() -> pd.Timestamp:
    return pd.Timestamp(dt.datetime.now(dt.UTC).replace(tzinfo=None))


def resample_closed(df30: pd.DataFrame, bar_hours: float, now: pd.Timestamp | None = None) -> pd.DataFrame:
    """Resample 30-min candles to bar_hours bars, dropping any bar not yet closed."""
    now = now if now is not None else utc_now()
    minutes = int(round(bar_hours * 60))
    out = df30.resample(f"{minutes}min").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    out = out.dropna(subset=["Close"])
    if out.empty:
        return out
    closed = out.index + pd.Timedelta(minutes=minutes) <= now
    return out[closed]


def trend_up(closed: pd.DataFrame, trend_hours: float, bar_hours: float):
    """True if the last close is above its trend_hours average, False if below,
    None if there is not enough history to say."""
    bars = max(2, int(round(trend_hours / bar_hours)))
    if len(closed) < max(2, bars // 2):
        return None
    ma = closed["Close"].rolling(bars, min_periods=bars // 2).mean().iloc[-1]
    last = closed["Close"].iloc[-1]
    if not (math.isfinite(ma) and math.isfinite(last)):
        return None
    return bool(last > ma)


def apply_bar_freshness(info: dict, bar_ts: str, last_seen: dict, ticker: str) -> dict:
    """Entries and pyramid adds are only allowed on the first run after a new
    bar closes; later runs inside the same bar see them downgraded to holds."""
    info["bar_ts"] = bar_ts
    if last_seen.get(ticker) == bar_ts:
        if info["action"] == "buy":
            info["action"] = "hold_long"
        elif info["action"] == "enter_short":
            info["action"] = "hold_short"
        info["pyramid_added"] = False
    return info


def time_exits(managed: dict, opened_at: dict, now: pd.Timestamp, max_hold_h: float) -> dict:
    """{coin: reason} for managed positions held at least max_hold_h hours."""
    if max_hold_h <= 0:
        return {}
    out = {}
    for coin in managed:
        ts = opened_at.get(coin)
        if not ts:
            continue
        try:
            held = (now - pd.Timestamp(ts)).total_seconds() / 3600
        except Exception:
            continue
        if held >= max_hold_h:
            out[coin] = f"time stop: held {held:.0f}h (limit {max_hold_h:g}h)"
    return out
