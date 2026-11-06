"""
backtest_round2.py — second replay round: is the SIGNAL/EXIT design the problem?

Round 1 showed the aggressive bot loses mostly on oscillator zero-cross exits
and on short (<3h) trades. This round tests, across several bar sizes and entry
thresholds:
  * exit style: oscillator flip (current) / trailing+hard stop only (with a
    time stop) / flip exit only after a minimum hold
  * tighter vs looser profit-protection settings
  * the round-1 "trade less" overlays (max 2 positions + max 2 same direction,
    both-way trend filter)

Results are judged on three equal time slices, so a variant that only wins in
one slice is flagged. Many variants are tried, so treat the best single row with
suspicion; look for a CLUSTER of neighbouring settings that all work.

    python backtest_round2.py [--synthetic] [--out results2]
"""

import argparse
import itertools
import os
import sys

import pandas as pd

import backtest_replay as br
from backtest_replay import Rules, build_market, simulate, stats, fmt


MARKETS = [
    # name, bar factor (x30min), signal kwargs
    ("30m thr0.25 (current)", 1, {}),
    ("30m thr0.5", 1, dict(osc_upper=0.5, osc_lower=-0.5)),
    ("30m thr1.0", 1, dict(osc_upper=1.0, osc_lower=-1.0)),
    ("1h thr0.25", 2, {}),
    ("1h thr0.5", 2, dict(osc_upper=0.5, osc_lower=-0.5)),
    ("1h thr1.0", 2, dict(osc_upper=1.0, osc_lower=-1.0)),
    ("2h thr0.25", 4, {}),
    ("2h thr0.5", 4, dict(osc_upper=0.5, osc_lower=-0.5)),
    ("4h thr0.5", 8, dict(osc_upper=0.5, osc_lower=-0.5)),
]

EXITS = [
    ("flip exit (current)", dict()),
    ("min hold 3h", dict(min_hold_h=3)),
    ("trail/stop only, 24h time stop", dict(trail_only=True, max_hold_h=24)),
    ("trail/stop only, 72h time stop", dict(trail_only=True, max_hold_h=72)),
    ("trail/stop only, 24h, looser trail", dict(trail_only=True, max_hold_h=24,
        pp=dict(be_atr=1.5, trail_atr=2.5, trail_dist=1.5))),
    ("trail/stop only, 24h, tighter trail", dict(trail_only=True, max_hold_h=24,
        pp=dict(be_atr=0.75, trail_atr=1.5, trail_dist=0.75))),
]

OVERLAYS = [
    ("no overlay", dict()),
    ("max2 pos + max2 same-dir", dict(max_positions=2, max_same_dir=2)),
    ("trend both ways (5d)", dict(trend_hours=120, gate_longs=True, gate_shorts=True)),
]


def make_rules(name, factor, exit_kw, over_kw):
    kw = dict(exit_kw)
    kw.update(over_kw)
    th = kw.pop("trend_hours", 0)
    if th:
        kw["trend_bars"] = int(th * 2 / factor)
    return Rules(name, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--out", default="results2")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    raw = br.synthetic() if a.synthetic else br.fetch_real()
    raw = {t: d for t, d in raw.items() if d is not None and len(d) > br.WARMUP + 50}
    if not raw:
        sys.exit("no data")

    rows = []
    for mname, factor, sk in MARKETS:
        print(f"== building {mname}", flush=True)
        mk = build_market(raw, factor=factor, **sk)
        idx = mk["index"]
        lo = idx[min(br.WARMUP, len(idx) - 1)]
        span = (idx[-1] - lo) / 3
        cut1, cut2 = lo + span, lo + 2 * span
        for (ename, ekw), (oname, okw) in itertools.product(EXITS, OVERLAYS):
            tr = simulate(mk, make_rules(f"{mname}|{ename}|{oname}", factor, ekw, okw))
            s = stats(tr)
            t1 = stats(tr[tr.close < cut1])["net"]
            t2 = stats(tr[(tr.close >= cut1) & (tr.close < cut2)])["net"]
            t3 = stats(tr[tr.close >= cut2])["net"]
            rows.append({"market": mname, "exit": ename, "overlay": oname, **s,
                         "t1": t1, "t2": t2, "t3": t3, "worst_third": min(t1, t2, t3),
                         "open_pnl": tr.attrs.get("open_pnl", 0)})
        print(f"   done {mname}: {len(rows)} rows", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(f"{a.out}/matrix.csv", index=False)
    base = df[(df.market == MARKETS[0][0]) & (df.exit == EXITS[0][0]) & (df.overlay == OVERLAYS[0][0])].iloc[0]

    def table(d, n):
        out = ["| market | exit | overlay | net | trades | win% | PF | max DD | long | short | 1/3 | 2/3 | 3/3 |",
               "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for _, x in d.head(n).iterrows():
            out.append(f"| {x.market} | {x.exit} | {x.overlay} | {fmt(x.net)} | {int(x.n)} | {x.win:.0f} | "
                       f"{x.pf:.2f} | {x.dd:.0f} | {fmt(x.long)} | {fmt(x.short)} | {fmt(x.t1)} | {fmt(x.t2)} | {fmt(x.t3)} |")
        return "\n".join(out)

    L = [f"# Round 2 replay ({len(df)} variants)\n",
         f"Baseline (current bot): net {fmt(base.net)}, PF {base.pf:.2f}, thirds {fmt(base.t1)} / {fmt(base.t2)} / {fmt(base.t3)}.\n",
         "$100/position, fees 0.043%/side + 0.01% slippage. Thirds = three equal time slices of the window.\n",
         "## Top 15 by net P&L\n", table(df.sort_values("net", ascending=False), 15),
         "\n## Top 15 by WORST third (most consistent)\n", table(df.sort_values("worst_third", ascending=False), 15)]
    prof = df[(df.t1 > 0) & (df.t2 > 0) & (df.t3 > 0)].sort_values("net", ascending=False)
    L.append(f"\n## Profitable in ALL three slices: {len(prof)} of {len(df)} variants\n")
    L.append(table(prof, 20) if len(prof) else "None.")

    L.append("\n## Average net by factor (shows which choices matter, not just the best row)\n")
    for col in ("market", "exit", "overlay"):
        g = df.groupby(col).agg(avg_net=("net", "mean"), best=("net", "max"), avg_trades=("n", "mean"),
                                avg_pf=("pf", "mean")).sort_values("avg_net", ascending=False)
        L.append(f"\n**By {col}**\n\n| {col} | avg net | best | avg trades | avg PF |\n|---|---:|---:|---:|---:|")
        for k, x in g.iterrows():
            L.append(f"| {k} | {fmt(x.avg_net)} | {fmt(x.best)} | {x.avg_trades:.0f} | {x.avg_pf:.2f} |")

    L.append("\n*Caveats: ~100 days, mostly one market regime; ~160 variants tried, so the single best row is likely "
             "partly luck. Trust patterns (a whole column of settings that works), not one cell.*")
    rep = "\n".join(L)
    with open(f"{a.out}/report.md", "w") as f:
        f.write(rep)
    print(rep)


if __name__ == "__main__":
    main()
