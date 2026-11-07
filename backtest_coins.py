"""
backtest_coins.py — would candidate new coins have helped?

Replays the slow-mode config (and the 2h alternative) on the current 11 coins
and on candidate coins, each coin ALONE (stand-alone edge, split in thirds) and
the whole basket with vs without the candidates.

    python backtest_coins.py [--out results4]
"""
import argparse
import os

import pandas as pd

import backtest_replay as br
from backtest_replay import Rules, build_market, simulate, stats, fmt

NEW = ["XLM", "TAO", "ONDO", "HBAR"]          # Hyperliquid symbols
CONFIGS = [
    ("4h thr0.75 / 96h / trend 240h (slow-mode default)", 8, 0.75, Rules("a", trail_only=True, max_hold_h=96,
        trend_bars=60, gate_longs=True, gate_shorts=True)),
    ("2h thr0.25 / 72h / trend 120h", 4, 0.25, Rules("b", trail_only=True, max_hold_h=72,
        trend_bars=60, gate_longs=True, gate_shorts=True)),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results4")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    from intraday_data_loader import fetch_candles
    raw, status = {}, []
    for t in br.TICKERS:
        raw[t] = fetch_candles(t, interval="30m", lookback_hours=2500).iloc[:-1]
    for c in NEW:
        br.SHORT[c] = c
        try:
            df = fetch_candles(c, interval="30m", lookback_hours=2500).iloc[:-1]
            if len(df) < br.WARMUP + 50:
                status.append((c, f"only {len(df)} candles"))
                continue
            raw[c] = df
            status.append((c, f"OK, {len(df)} candles from {df.index[0].date()}"))
        except Exception as e:
            status.append((c, f"NOT AVAILABLE: {e}"))
    names = {t: br.SHORT.get(t, t) for t in raw}

    L = ["# Candidate coin check\n", "Listing / data status:\n"] + [f"- {c}: {s}" for c, s in status]
    for cname, factor, thr, rules in CONFIGS:
        L.append(f"\n## {cname}\n")
        L.append("Each coin traded ALONE ($100 per position), thirds = three equal time slices.\n")
        L.append("| coin | new? | net | trades | win% | PF | long | short | 1/3 | 2/3 | 3/3 |\n|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for t in raw:
            mk = build_market({t: raw[t]}, factor=factor, osc_upper=thr, osc_lower=-thr)
            idx = mk["index"]
            lo = idx[min(br.WARMUP, len(idx) - 1)]
            sp = (idx[-1] - lo) / 3
            tr = simulate(mk, rules)
            s = stats(tr)
            th = [stats(tr[tr.close < lo + sp])["net"],
                  stats(tr[(tr.close >= lo + sp) & (tr.close < lo + 2 * sp)])["net"],
                  stats(tr[tr.close >= lo + 2 * sp])["net"]]
            L.append(f"| {names[t]} | {'NEW' if t in NEW else ''} | {fmt(s['net'])} | {s['n']} | {s['win']:.0f} | "
                     f"{s['pf']:.2f} | {fmt(s['long'])} | {fmt(s['short'])} | {fmt(th[0])} | {fmt(th[1])} | {fmt(th[2])} |")
        L.append("\n**Basket (4 positions max, as live):**\n")
        L.append("| coins | net | trades | win% | PF | max DD |\n|---|---:|---:|---:|---:|---:|")
        base = {t: raw[t] for t in raw if t not in NEW}
        for label, d in [("current 11", base), (f"11 + {len([c for c in NEW if c in raw])} new", raw)]:
            tr = simulate(build_market(d, factor=factor, osc_upper=thr, osc_lower=-thr), rules)
            s = stats(tr)
            L.append(f"| {label} | {fmt(s['net'])} | {s['n']} | {s['win']:.0f} | {s['pf']:.2f} | {s['dd']:.0f} |")
    L.append("\n*Single coins over ~100 days have few trades; look for coins that are positive in most thirds, "
             "and treat one lucky coin with suspicion.*")
    rep = "\n".join(L)
    open(f"{a.out}/report.md", "w").write(rep)
    print(rep)


if __name__ == "__main__":
    main()
