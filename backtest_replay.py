"""
backtest_replay.py — replay the AGGRESSIVE bot over recent Hyperliquid 30-min
candles and compare rule changes on the same data.

It reuses the bot's real code for signals (aggressive_strategy) and profit
protection (profit_protection), and mirrors the executor's decision logic
(level-based exits, fresh-entry-only opens, max positions, block after a
protective exit, pyramid adds). Nothing here touches the exchange or any
bot state.

Usage:
    python backtest_replay.py                 # fetch live candles, write ./results
    python backtest_replay.py --synthetic     # offline self-test on fake data

Assumptions (so results are comparable, not a promise of live P&L):
  * decisions at each 30-min bar close, fills at that close +- slippage
  * every new position is $100 notional (pyramid adds $33), no compounding
  * taker fee 0.043% per side (what the account actually pays) + 0.01% slippage
  * the same 11 coins the bot trades; BTC/ETH sized like the others
"""

import argparse
import math
import os
import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import profit_protection as pp
from aggressive_strategy import generate_aggressive_signals, classify_aggressive_signal

TICKERS = [
    "BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "LINK-USD", "SUI20947-USD",
    "XRP-USD", "ZEC-USD", "NEAR-USD", "HYPE32196-USD", "VVV-USD",
]
SHORT = {"BTC-USD": "BTC", "ETH-USD": "ETH", "SOL-USD": "SOL", "AVAX-USD": "AVAX",
         "LINK-USD": "LINK", "SUI20947-USD": "SUI", "XRP-USD": "XRP", "ZEC-USD": "ZEC",
         "NEAR-USD": "NEAR", "HYPE32196-USD": "HYPE", "VVV-USD": "VVV"}

NOTIONAL = 100.0
PYRAMID_NOTIONAL = NOTIONAL * (0.005 / 0.015)
FEE = 0.00043
SLIP = 0.0001
WARMUP = 150


@dataclass
class Rules:
    name: str
    max_positions: int = 4
    max_same_dir: int = 99          # cap on simultaneous longs / shorts
    trend_bars: int = 0             # 0 = no trend filter
    gate_longs: bool = False        # longs only when price > MA
    gate_shorts: bool = False       # shorts only when price < MA
    use_btc_trend: bool = False     # judge trend by BTC instead of the coin
    lockout_h: float = 0.0          # hours after a close before re-entering
    lockout_flip_only: bool = True  # lockout applies only to the opposite direction
    exclude: tuple = ()
    long_mult: float = 1.0          # scale long size
    protect: bool = True
    trail_only: bool = False        # ignore oscillator flip exits; exit via protection/time stop only
    min_hold_h: float = 0.0         # ignore oscillator flip exits until held this long
    max_hold_h: float = 0.0         # time stop (0 = off)
    pp: dict = field(default_factory=dict)   # overrides for profit-protection settings


@dataclass
class Pos:
    side: int
    size: float          # coins, >0
    entry: float
    t_open: pd.Timestamp
    peak: float
    pyramids: int = 0
    fresh: bool = True


def resample(df: pd.DataFrame, factor: int) -> pd.DataFrame:
    if factor == 1:
        return df
    o = df.resample(f"{30 * factor}min").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    return o.dropna(subset=["Close"])


def build_market(raw: dict, factor: int = 1, **sig_kwargs) -> dict:
    """raw: ticker -> OHLCV df. Returns aligned frames + signals."""
    raw = {t: resample(df, factor) for t, df in raw.items() if df is not None and len(df)}
    idx = pd.DatetimeIndex(sorted(set().union(*[set(df.index) for df in raw.values() if len(df)])))
    mk = {"index": idx, "coins": {}}
    for t, df in raw.items():
        if df is None or len(df) < WARMUP + 50:
            continue
        sig = generate_aggressive_signals(df, allow_short=True, **sig_kwargs)
        s = sig["Signal"].astype(int)
        act = [classify_aggressive_signal(int(s.iloc[i]), int(s.iloc[i - 1]) if i else 0)
               for i in range(len(s))]
        d = pd.DataFrame({
            "close": df["Close"], "high": df["High"], "low": df["Low"],
            "atr": sig["ATR"], "osc": sig["TwoPole_Osc"], "signal": s,
            "pyr": sig["Pyramid"].astype(int), "action": act,
        })
        d["pyr_added"] = d["pyr"].diff().fillna(0) > 0
        mk["coins"][t] = d.iloc[WARMUP:].reindex(idx)
    return mk


def simulate(mk: dict, rules: Rules) -> pd.DataFrame:
    idx = mk["index"]
    coins = mk["coins"]
    cfg = {**pp.settings(), **rules.pp}

    trend_up = {}
    if rules.trend_bars:
        for t, d in coins.items():
            ma = d["close"].rolling(rules.trend_bars, min_periods=rules.trend_bars // 2).mean()
            trend_up[t] = (d["close"] > ma).astype(float).where(ma.notna())
        if rules.use_btc_trend and "BTC-USD" in trend_up:
            btc = trend_up["BTC-USD"]
            trend_up = {t: btc for t in trend_up}

    pos: dict[str, Pos] = {}
    blocked: dict[str, int] = {}
    last_close: dict[str, tuple] = {}   # coin -> (time, side closed)
    trades = []

    def fill_px(px, is_buy):
        return px * (1 + SLIP) if is_buy else px * (1 - SLIP)

    def close(t, ts, px, reason):
        p = pos.pop(t)
        exit_px = fill_px(px, p.side == -1)   # closing a long = sell
        gross = p.side * (exit_px - p.entry) * p.size
        fees = FEE * (p.entry * p.size) + FEE * (exit_px * p.size)
        trades.append({"coin": SHORT[t], "side": "long" if p.side == 1 else "short",
                       "open": p.t_open, "close": ts, "entry": p.entry, "exit": exit_px,
                       "pnl": gross - fees, "reason": reason,
                       "hours": (ts - p.t_open).total_seconds() / 3600})
        last_close[t] = (ts, p.side)

    for ti, ts in enumerate(idx):
        rows = {t: d.iloc[ti] for t, d in coins.items() if not math.isnan(d["close"].iloc[ti])}
        if not rows:
            continue

        sigs = {}
        for t, r in rows.items():
            sigs[t] = {"signal": int(r.signal), "action": r.action, "price": float(r.close),
                       "osc": float(r.osc), "atr": float(r.atr) if not math.isnan(r.atr) else 0.0,
                       "high": float(r.high), "low": float(r.low), "pyramid_added": bool(r.pyr_added)}

        blocked = pp.update_blocks(blocked, sigs, {t: t for t in sigs})

        protect_closed = set()
        for t in list(pos):
            if t not in sigs:
                continue
            p, s = pos[t], sigs[t]
            cands = [s["price"]] if p.fresh else [s["price"], s["high"] if p.side == 1 else s["low"]]
            p.peak = max([p.peak] + cands) if p.side == 1 else min([p.peak] + cands)
            p.fresh = False

            held_h = (ts - p.t_open).total_seconds() / 3600
            if s["signal"] != p.side and not rules.trail_only and held_h >= rules.min_hold_h:
                close(t, ts, s["price"], "signal")
                continue
            if rules.protect:
                reason = pp.check_exit(t, {"size": p.side * p.size, "entry_px": p.entry}, s,
                                       {"peak": p.peak, "side": p.side}, None, cfg)
                if reason:
                    side = p.side
                    close(t, ts, s["price"], reason.split(":")[0])
                    blocked[t] = side
                    protect_closed.add(t)
                    continue
            if rules.max_hold_h and held_h >= rules.max_hold_h:
                close(t, ts, s["price"], "time stop")

        for t, p in pos.items():
            s = sigs.get(t)
            if s and s["pyramid_added"] and p.pyramids < 2 and s["signal"] == p.side:
                px = fill_px(s["price"], p.side == 1)
                add = PYRAMID_NOTIONAL / px
                p.entry = (p.entry * p.size + px * add) / (p.size + add)
                p.size += add
                p.pyramids += 1

        slots = rules.max_positions - len(pos)
        if slots > 0:
            n_long = sum(1 for p in pos.values() if p.side == 1)
            n_short = len(pos) - n_long
            cands = []
            for t, s in sigs.items():
                if t in pos or t in protect_closed or SHORT[t] in rules.exclude:
                    continue
                if s["action"] not in ("buy", "enter_short"):
                    continue
                side = 1 if s["action"] == "buy" else -1
                if blocked.get(t) == side:
                    continue
                if rules.trend_bars and t in trend_up:
                    up = trend_up[t].iloc[ti]
                    if not pd.isna(up):
                        if side == 1 and rules.gate_longs and up < 0.5:
                            continue
                        if side == -1 and rules.gate_shorts and up > 0.5:
                            continue
                if rules.lockout_h and t in last_close:
                    lt, lside = last_close[t]
                    within = (ts - lt).total_seconds() / 3600 < rules.lockout_h
                    if within and (not rules.lockout_flip_only or lside != side):
                        continue
                cands.append((abs(s["osc"]), t, side, s["price"]))
            cands.sort(reverse=True)
            for _, t, side, price in cands:
                if slots <= 0:
                    break
                if (n_long if side == 1 else n_short) >= rules.max_same_dir:
                    continue
                px = fill_px(price, side == 1)
                mult = rules.long_mult if side == 1 else 1.0
                pos[t] = Pos(side=side, size=NOTIONAL * mult / px, entry=px, t_open=ts, peak=px)
                slots -= 1
                if side == 1:
                    n_long += 1
                else:
                    n_short += 1

    open_pnl = 0.0
    for t, p in pos.items():
        last = coins[t]["close"].dropna().iloc[-1]
        open_pnl += p.side * (last - p.entry) * p.size
    df = pd.DataFrame(trades, columns=["coin", "side", "open", "close", "entry", "exit",
                                       "pnl", "reason", "hours"])
    df.attrs["open_pnl"] = open_pnl
    return df


def stats(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return dict(net=0.0, n=0, win=0.0, pf=0.0, avg=0.0, dd=0.0, long=0.0, short=0.0)
    w, l = tr[tr.pnl > 0].pnl.sum(), -tr[tr.pnl <= 0].pnl.sum()
    cum = tr.sort_values("close").pnl.cumsum()
    return dict(net=tr.pnl.sum(), n=len(tr), win=(tr.pnl > 0).mean() * 100,
                pf=(w / l if l > 0 else float("inf")), avg=tr.pnl.mean(),
                dd=float((cum.cummax() - cum).max()),
                long=tr[tr.side == "long"].pnl.sum(), short=tr[tr.side == "short"].pnl.sum())


def variants() -> list[Rules]:
    v = [Rules("baseline")]
    for n in (96, 240, 480):
        v.append(Rules(f"no longs below {n}-bar MA", trend_bars=n, gate_longs=True))
    for n in (96, 240, 480):
        v.append(Rules(f"trend-follow both ways, {n}-bar MA", trend_bars=n, gate_longs=True, gate_shorts=True))
    v.append(Rules("BTC trend gates longs (240)", trend_bars=240, gate_longs=True, use_btc_trend=True))
    for c in (3, 2):
        v.append(Rules(f"max {c} same-direction", max_same_dir=c))
    for h in (2, 4, 8):
        v.append(Rules(f"{h}h no-flip lockout", lockout_h=h))
    for h in (4, 12):
        v.append(Rules(f"{h}h lockout, any direction", lockout_h=h, lockout_flip_only=False))
    v.append(Rules("longs at half size", long_mult=0.5))
    v.append(Rules("max 6 positions", max_positions=6))
    v.append(Rules("max 2 positions", max_positions=2))
    v.append(Rules("profit protection off", protect=False))
    v.append(Rules("combo: no longs <240MA + max 3 same-dir", trend_bars=240, gate_longs=True, max_same_dir=3))
    v.append(Rules("combo: above + 4h no-flip", trend_bars=240, gate_longs=True, max_same_dir=3, lockout_h=4))
    v.append(Rules("combo: both-way trend 240 + 4h no-flip", trend_bars=240, gate_longs=True,
                   gate_shorts=True, lockout_h=4))
    return v


def synthetic(n=4000, seed=1) -> dict:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-07-01", periods=n, freq="30min")
    raw = {}
    for i, t in enumerate(TICKERS):
        r = rng.normal(0, 0.004, n) + 0.0003 * np.sin(np.arange(n) / (200 + 30 * i))
        c = 100 * np.exp(np.cumsum(r))
        h = c * (1 + np.abs(rng.normal(0, 0.002, n)))
        l = c * (1 - np.abs(rng.normal(0, 0.002, n)))
        o = np.r_[c[0], c[:-1]]
        raw[t] = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": 1.0}, index=idx)
    return raw


def fetch_real() -> dict:
    from intraday_data_loader import fetch_candles
    raw = {}
    for t in TICKERS:
        try:
            df = fetch_candles(t, interval="30m", lookback_hours=2500)
            df = df.iloc[:-1]  # drop the still-forming candle
            raw[t] = df
            print(f"{t}: {len(df)} candles {df.index[0]} -> {df.index[-1]}")
        except Exception as e:
            print(f"{t}: FAILED {e}")
    return raw


def fmt(x):
    return f"{x:+.2f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--out", default="results")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    raw = synthetic() if a.synthetic else fetch_real()
    raw = {t: d for t, d in raw.items() if d is not None and len(d) > WARMUP + 50}
    if not raw:
        sys.exit("no data")
    mk = build_market(raw)
    idx = mk["index"]
    mid = idx[len(idx) // 2]
    days = (idx[-1] - idx[WARMUP]).days
    print(f"Replaying {len(mk['coins'])} coins over ~{days} days; half split at {mid}")

    rows, results = [], {}
    for r in variants():
        tr = simulate(mk, r)
        results[r.name] = tr
        s = stats(tr)
        rows.append({"variant": r.name, **s,
                     "first_half": stats(tr[tr.close < mid])["net"],
                     "second_half": stats(tr[tr.close >= mid])["net"],
                     "open_pnl": tr.attrs.get("open_pnl", 0)})
    summ = pd.DataFrame(rows)
    summ["vs_base"] = summ.net - summ.net.iloc[0]
    summ.to_csv(f"{a.out}/summary.csv", index=False)
    results["baseline"].to_csv(f"{a.out}/trades_baseline.csv", index=False)

    L = [f"# Aggressive bot replay\n\nCoins: {len(mk['coins'])}, window ~{days} days "
         f"({idx[WARMUP].date()} to {idx[-1].date()}). $100 per position, fees 0.043%/side + 0.01% slippage.\n",
         "## All variants (net P&L in $ at $100/position)\n",
         "| variant | net | vs baseline | trades | win% | PF | max DD | longs | shorts | 1st half | 2nd half |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for _, x in summ.iterrows():
        L.append(f"| {x.variant} | {fmt(x.net)} | {fmt(x.vs_base)} | {int(x.n)} | {x.win:.0f} | {x.pf:.2f} | "
                 f"{x.dd:.1f} | {fmt(x.long)} | {fmt(x.short)} | {fmt(x.first_half)} | {fmt(x.second_half)} |")

    bt = results["baseline"]
    if len(bt):
        L.append("\n## Baseline by coin\n")
        L.append("| coin | net | trades | win% |\n|---|---:|---:|---:|")
        g = bt.groupby("coin").pnl.agg(net="sum", n="count", win=lambda s: (s > 0).mean() * 100).sort_values("net")
        for c, rr in g.iterrows():
            L.append(f"| {c} | {fmt(rr.net)} | {int(rr.n)} | {rr.win:.0f} |")
        L.append("\n## Baseline by exit reason\n")
        L.append("| reason | net | trades | avg |\n|---|---:|---:|---:|")
        g = bt.groupby("reason").pnl.agg(net="sum", n="count", avg="mean").sort_values("net")
        for c, rr in g.iterrows():
            L.append(f"| {c} | {fmt(rr.net)} | {int(rr.n)} | {fmt(rr.avg)} |")
        L.append("\n## Baseline by hold time\n")
        L.append("| held | net | trades | avg |\n|---|---:|---:|---:|")
        bins = pd.cut(bt.hours, [0, 1, 3, 8, 24, 72, 1e9], labels=["<1h", "1-3h", "3-8h", "8-24h", "1-3d", ">3d"])
        g = bt.groupby(bins, observed=True).pnl.agg(net="sum", n="count", avg="mean")
        for c, rr in g.iterrows():
            L.append(f"| {c} | {fmt(rr.net)} | {int(rr.n)} | {fmt(rr.avg)} |")

    h1 = bt[bt.close < mid]
    if len(h1):
        worst = list(h1.groupby("coin").pnl.sum().sort_values().index[:3])
        wf = simulate(mk, Rules("wf", exclude=tuple(worst)))
        b2, w2 = stats(bt[bt.close >= mid])["net"], stats(wf[wf.close >= mid])["net"]
        L.append(f"\n## Walk-forward check: drop worst 3 coins of the 1st half ({', '.join(worst)})\n")
        L.append(f"2nd-half net: baseline {fmt(b2)} vs with those coins dropped {fmt(w2)}.")

    L.append("\n*Caveat: one ~3-month window of mostly one market regime. A variant that wins in both halves "
             "and across its parameter settings is more believable than one that wins in a single setting.*")
    rep = "\n".join(L)
    with open(f"{a.out}/report.md", "w") as f:
        f.write(rep)
    print(rep)


if __name__ == "__main__":
    main()
