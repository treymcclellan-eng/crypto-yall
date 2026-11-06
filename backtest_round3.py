"""
backtest_round3.py — neighbourhood check around the "slow mode" winner.

Round 2's most consistent setup: 2h bars, entry threshold 0.25, trailing/stop
exits with a 72h time stop, both-way trend filter (5 days). This round varies
each of those around that point to see whether it sits in a stable zone or is
a lone spike, and stress-tests it with higher trading costs.

    python backtest_round3.py [--synthetic] [--out results3]
"""

import argparse
import itertools
import os
import sys

import pandas as pd

import backtest_replay as br
from backtest_replay import Rules, build_market, simulate, stats, fmt

MARKETS = [
    ("2h thr0.15", 4, 0.15), ("2h thr0.25", 4, 0.25), ("2h thr0.35", 4, 0.35), ("2h thr0.5", 4, 0.5),
    ("3h thr0.25", 6, 0.25), ("3h thr0.5", 6, 0.5),
    ("4h thr0.35", 8, 0.35), ("4h thr0.5", 8, 0.5), ("4h thr0.75", 8, 0.75),
]
HOLDS = [48, 72, 96, 144]
TRENDS = [0, 72, 120, 240]          # hours; 0 = no trend filter
EXTRA = [("tight trail, 72h, trend 120h", dict(max_hold_h=72, trend_hours=120,
                                              pp=dict(be_atr=0.75, trail_atr=1.5, trail_dist=0.75))),
         ("trend 120h + max 2 same-dir, 72h", dict(max_hold_h=72, trend_hours=120, max_same_dir=2))]
DEFAULT = ("2h thr0.25", 72, 120)


def rules_for(factor, hold, trend_h, **extra):
    kw = dict(trail_only=True, max_hold_h=hold)
    if trend_h:
        kw.update(trend_bars=int(trend_h * 2 / factor), gate_longs=True, gate_shorts=True)
    kw.update(extra)
    return Rules(f"{hold}h/{trend_h}h", **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--out", default="results3")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    raw = br.synthetic() if a.synthetic else br.fetch_real()
    raw = {t: d for t, d in raw.items() if d is not None and len(d) > br.WARMUP + 50}
    if not raw:
        sys.exit("no data")

    rows, markets = [], {}
    for mname, factor, thr in MARKETS:
        print(f"== {mname}", flush=True)
        mk = build_market(raw, factor=factor, osc_upper=thr, osc_lower=-thr)
        markets[mname] = (mk, factor)
        idx = mk["index"]
        lo = idx[min(br.WARMUP, len(idx) - 1)]
        span = (idx[-1] - lo) / 3
        c1, c2 = lo + span, lo + 2 * span
        combos = [(f"{h}h hold", h, t, {}) for h, t in itertools.product(HOLDS, TRENDS)]
        combos += [(n, kw["max_hold_h"], kw["trend_hours"], {k: v for k, v in kw.items()
                                                              if k not in ("max_hold_h", "trend_hours")})
                   for n, kw in EXTRA]
        for label, hold, th, extra in combos:
            tr = simulate(mk, rules_for(factor, hold, th, **extra))
            s = stats(tr)
            t = [stats(tr[tr.close < c1])["net"], stats(tr[(tr.close >= c1) & (tr.close < c2)])["net"],
                 stats(tr[tr.close >= c2])["net"]]
            rows.append({"market": mname, "variant": label, "hold": hold, "trend_h": th, **s,
                         "t1": t[0], "t2": t[1], "t3": t[2], "worst": min(t)})
    df = pd.DataFrame(rows)
    df.to_csv(f"{a.out}/matrix.csv", index=False)

    def table(d, n):
        o = ["| market | variant | hold | trend | net | trades | win% | PF | DD | long | short | 1/3 | 2/3 | 3/3 |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for _, x in d.head(n).iterrows():
            o.append(f"| {x.market} | {x.variant} | {x.hold} | {x.trend_h} | {fmt(x.net)} | {int(x.n)} | {x.win:.0f} | "
                     f"{x.pf:.2f} | {x.dd:.0f} | {fmt(x.long)} | {fmt(x.short)} | {fmt(x.t1)} | {fmt(x.t2)} | {fmt(x.t3)} |")
        return "\n".join(o)

    plain = df[df.variant.str.endswith("h hold")]
    L = [f"# Round 3 replay ({len(df)} variants)\n",
         "$100/position, fees 0.043%/side + 0.01% slippage. All variants: trailing/stop exits + time stop "
         "(oscillator-flip exits ignored). Thirds = three equal time slices.\n",
         "## Top 15 by worst third\n", table(df.sort_values("worst", ascending=False), 15)]
    pos3 = df[(df.t1 > 0) & (df.t2 > 0) & (df.t3 > 0)]
    L.append(f"\n## Profitable in all three slices: {len(pos3)} of {len(df)}\n")
    L.append(table(pos3.sort_values("net", ascending=False), 20) if len(pos3) else "None.")

    L.append("\n## Stability map: net P&L (worst third in brackets), trend filter 120h\n")
    g = plain[plain.trend_h == 120]
    L.append("| market | " + " | ".join(f"{h}h hold" for h in HOLDS) + " |\n|---|" + "---:|" * len(HOLDS))
    for m, _, _ in MARKETS:
        cells = []
        for h in HOLDS:
            x = g[(g.market == m) & (g.hold == h)].iloc[0]
            cells.append(f"{fmt(x.net)} ({fmt(x.worst)})")
        L.append(f"| {m} | " + " | ".join(cells) + " |")
    L.append("\n## Effect of the trend filter length (avg net over all markets/holds)\n")
    L.append("| trend filter | avg net | avg worst third | share of variants profitable |\n|---|---:|---:|---:|")
    for th in TRENDS:
        x = plain[plain.trend_h == th]
        L.append(f"| {'none' if th == 0 else f'{th}h'} | {fmt(x.net.mean())} | {fmt(x.worst.mean())} | "
                 f"{(x.net > 0).mean() * 100:.0f}% |")
    L.append("\n## Effect of time stop (avg net, trend 120h)\n")
    L.append("| hold limit | avg net | share profitable |\n|---|---:|---:|")
    for h in HOLDS:
        x = g[g.hold == h]
        L.append(f"| {h}h | {fmt(x.net.mean())} | {(x.net > 0).mean() * 100:.0f}% |")

    # cost stress on the shipping default
    mname, hold, th = DEFAULT
    mk, factor = markets[mname]
    L.append(f"\n## Cost stress on the default ({mname}, {hold}h hold, trend {th}h)\n")
    L.append("| costs | net | trades | PF |\n|---|---:|---:|---:|")
    f0, s0 = br.FEE, br.SLIP
    for label, fee, slip in [("as modelled (0.043% + 0.01%)", f0, s0), ("2x fees", f0 * 2, s0),
                              ("fees + 0.05% slippage", f0, 0.0005), ("2x fees + 0.05% slippage", f0 * 2, 0.0005)]:
        br.FEE, br.SLIP = fee, slip
        s = stats(simulate(mk, rules_for(factor, hold, th)))
        L.append(f"| {label} | {fmt(s['net'])} | {s['n']} | {s['pf']:.2f} |")
    br.FEE, br.SLIP = f0, s0

    L.append("\n*Caveats: ~100 days, mostly one market regime; 200+ variants tried. A broad plateau of positive "
             "cells is evidence; one bright cell is not.*")
    rep = "\n".join(L)
    open(f"{a.out}/report.md", "w").write(rep)
    print(rep)


if __name__ == "__main__":
    main()
