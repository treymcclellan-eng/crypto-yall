"""Offline checks for slow mode (no network, no Hyperliquid SDK needed).  python test_slow_mode.py"""
import os, sys, types
import numpy as np
import pandas as pd

# Stub the exchange-facing modules so aggressive_executor can be imported anywhere.
he = types.ModuleType("hyperliquid_executor")
he.ASSETS = {"BTC-USD": "BTC", "SOL-USD": "SOL", "AVAX-USD": "AVAX"}
for n in ["get_client", "get_account_equity", "get_open_positions", "get_mid_price", "get_size_decimals",
          "round_size", "_parse_response", "_send_email", "_send_telegram", "close_position",
          "apply_exposure_cap"]:
    setattr(he, n, lambda *a, **k: None)
sys.modules["hyperliquid_executor"] = he
bt = types.ModuleType("backtester")
bt.ASSET_PROFILES = {"large_cap": {"allow_short": True}, "mid_cap": {"allow_short": True}}
bt.get_asset_profile = lambda t: bt.ASSET_PROFILES["large_cap"]
sys.modules["backtester"] = bt

import slow_mode
import aggressive_executor as ae


def candles(n=3000, seed=3, start="2026-08-01"):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="30min")
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    return pd.DataFrame({"Open": c, "High": c * 1.002, "Low": c * 0.998, "Close": c, "Volume": 1.0}, index=idx)


def test_resample_drops_open_bar():
    df = candles(100)
    now = df.index[-1] + pd.Timedelta(minutes=30)          # last 30m candle just closed
    out = slow_mode.resample_closed(df, 2, now)
    assert out.index[-1] + pd.Timedelta(hours=2) <= now
    out2 = slow_mode.resample_closed(df, 2, df.index[-1])   # last candle still forming
    assert out2.index[-1] + pd.Timedelta(hours=2) <= df.index[-1]


def test_freshness():
    info = {"action": "buy", "pyramid_added": True}
    assert slow_mode.apply_bar_freshness(dict(info), "T1", {"X": "T1"}, "X")["action"] == "hold_long"
    assert slow_mode.apply_bar_freshness(dict(info), "T1", {"X": "T1"}, "X")["pyramid_added"] is False
    assert slow_mode.apply_bar_freshness(dict(info), "T2", {"X": "T1"}, "X")["action"] == "buy"
    assert slow_mode.apply_bar_freshness({"action": "enter_short", "pyramid_added": False}, "T1", {"X": "T1"}, "X")["action"] == "hold_short"


def test_compute_slow_and_classic():
    df = candles()
    ae.fetch_all_intraday = lambda tickers, interval, lookback_hours: {t: df for t in tickers}
    os.environ["AGGRESSIVE_MODE"] = "slow"
    s = ae.compute_aggressive_signals({})
    assert s and all("trend_up" in v and "bar_ts" in v for v in s.values())
    bar_ts = next(iter(s.values()))["bar_ts"]
    s2 = ae.compute_aggressive_signals({"slow_bars": {t: v["bar_ts"] for t, v in s.items()}})
    assert all(v["action"] not in ("buy", "enter_short") for v in s2.values())
    os.environ["AGGRESSIVE_MODE"] = "classic"
    c = ae.compute_aggressive_signals({})
    assert c and all("trend_up" not in v for v in c.values())


def sig(action, signal, osc=0.5, trend=None):
    return {"action": action, "signal": signal, "price": 100.0, "osc": osc, "atr": 1.0, "high": 101, "low": 99,
            "pyramid_added": False, "trend_up": trend}


def test_decide():
    pos = {"BTC": {"size": 1.0, "entry_px": 100}}
    sigs = {"BTC-USD": sig("flat", 0)}                       # strategy no longer long
    classic = ae.decide_trades(sigs, pos, 4, {})
    assert [t["action"] for t in classic] == ["close"]       # classic: flip exit
    slow = slow_mode.settings()
    assert ae.decide_trades(sigs, pos, 4, {}, slow=slow) == []   # slow: flip ignored
    ts = ae.decide_trades(sigs, pos, 4, {}, slow=slow, time_exits={"BTC": "time stop"})
    assert [t["action"] for t in ts] == ["close"] and not ts[0].get("protect")
    # trend gate
    g = {"BTC-USD": sig("buy", 1, trend=False), "SOL-USD": sig("enter_short", -1, trend=False),
         "AVAX-USD": sig("enter_short", -1, trend=True)}
    out = ae.decide_trades(g, {}, 4, {}, slow=slow)
    assert sorted(t["ticker"] for t in out) == ["SOL-USD"]
    # same-direction cap
    g = {t: sig("enter_short", -1, osc=o, trend=False) for t, o in [("BTC-USD", 3), ("SOL-USD", 2), ("AVAX-USD", 1)]}
    out = ae.decide_trades(g, {}, 4, {}, slow={**slow, "max_same_dir": 2})
    assert [t["ticker"] for t in out] == ["BTC-USD", "SOL-USD"]
    # classic ignores trend_up entirely
    g = {"BTC-USD": sig("buy", 1, trend=False)}
    assert len(ae.decide_trades(g, {}, 4, {})) == 1


def test_time_exits():
    now = pd.Timestamp("2026-11-06 12:00")
    out = slow_mode.time_exits({"BTC": {}, "SOL": {}}, {"BTC": "2026-11-03 00:00", "SOL": "2026-11-06 00:00"}, now, 72)
    assert list(out) == ["BTC"]


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
