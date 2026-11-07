"""
backtest_maxpos.py — how many simultaneous positions should slow mode allow?

Replays slow mode (and the 2h alternative) with different position caps, with
and without a same-direction cap, and reports peak exposure so the extra
risk is visible.

    python backtest_maxpos.py [--synthetic] [--out results5]
"""
import argparse
import os
import sys

import pandas as pd

import backtest_replay as br
from backtest_replay import Rules, build_market, simulate, stats, fmt

CONFIGS = [
    ("4h thr0.75 / 96h / trend 240h (slow-mode default)", 8, 0.75, dict(max_hold_h=96, trend_bars=60)),
    ("2h thr0.25 / 72h / trend 120h", 4, 0.25, dict(max_hold_h=72, trend_bars=60)),
]
CAPS = [2, 3, 4, 5, 6, 8, 11]
SAME = [99, 3]


def peak_exposure(tr: pd.DataFrame) -> int:
    if tr.empty:
        return 0
    ev = [(o, 1) for o in tr.open] + [(c, -1) for c in tr.close]
    ev.sort(key=lambda x: (x[0], x[1]))
    cur = peak = 0
    for _, d in ev:
        cur += d
        peak = max(peak, cur)
    return peak


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--out", default="results5")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    raw = br.synthetic() if a.synthetic else br.fetch_real()
    raw = {t: d for t, d in raw.items() if d is not None and len(d) > br.WARMUP + 50}
    if not raw:
        sys.exit("no data")

    L = ["# Position-cap check (slow mode)\n", "$100/position; fees 0.043%/side + 0.01% slippage; "
         "peak = most positions open at once ($100 each).\n"]
    for cname, factor, thr, kw in CONFIGS:
        mk = build_market(raw, factor=factor, osc_upper=thr, osc_lower=-thr)
        idx = mk["index"]
        lo = idx[min(br.WARMUP, len(idx) - 1)]
        sp = (idx[-1] - lo) / 3
        L.append(f"\n## {cname}\n")
        L.append("| max positions | max same-dir | net | trades | win% | PF | max DD | peak open | 1/3 | 2/3 | 3/3 |\n"
                 "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for cap in CAPS:
            for sd in SAME:
                tr = simulate(mk, Rules("x", trail_only=True, gate_longs=True, gate_shorts=True,
                                        max_positions=cap, max_same_dir=sd, **kw))
                s = stats(tr)
                t = [stats(tr[tr.close < lo + sp])["net"],
                     stats(tr[(tr.close >= lo + sp) & (tr.close < lo + 2 * sp)])["net"],
                     stats(tr[tr.close >= lo + 2 * sp])["net"]]
                L.append(f"| {cap} | {'-' if sd == 99 else sd} | {fmt(s['net'])} | {s['n']} | {s['win']:.0f} | "
                         f"{s['pf']:.2f} | {s['dd']:.0f} | {peak_exposure(tr)} | {fmt(t[0])} | {fmt(t[1])} | {fmt(t[2])} |")
    L.append("\n*Look for where extra slots stop adding profit; more slots always add exposure and drawdown.*")
    rep = "\n".join(L)
    open(f"{a.out}/report.md", "w").write(rep)
    print(rep)


if __name__ == "__main__":
    main()
