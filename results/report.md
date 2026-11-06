# Round 2 replay (162 variants)

Baseline (current bot): net -142.18, PF 0.80, thirds -19.75 / -99.06 / -23.36.

$100/position, fees 0.043%/side + 0.01% slippage. Thirds = three equal time slices of the window.

## Top 15 by net P&L

| market | exit | overlay | net | trades | win% | PF | max DD | long | short | 1/3 | 2/3 | 3/3 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 4h thr0.5 | flip exit (current) | trend both ways (5d) | +139.70 | 63 | 51 | 2.26 | 35 | +140.89 | -1.20 | +30.31 | +111.46 | -2.07 |
| 4h thr0.5 | min hold 3h | trend both ways (5d) | +139.70 | 63 | 51 | 2.26 | 35 | +140.89 | -1.20 | +30.31 | +111.46 | -2.07 |
| 4h thr0.5 | trail/stop only, 72h time stop | no overlay | +126.73 | 93 | 51 | 1.74 | 50 | +125.98 | +0.75 | +41.96 | +124.80 | -40.04 |
| 4h thr0.5 | trail/stop only, 72h time stop | max2 pos + max2 same-dir | +117.15 | 58 | 50 | 2.05 | 31 | +112.43 | +4.72 | +47.83 | +100.42 | -31.10 |
| 4h thr0.5 | trail/stop only, 72h time stop | trend both ways (5d) | +115.28 | 62 | 52 | 1.95 | 36 | +131.68 | -16.40 | +17.41 | +113.74 | -15.87 |
| 4h thr0.5 | flip exit (current) | no overlay | +99.61 | 103 | 47 | 1.47 | 58 | +113.68 | -14.07 | +7.11 | +104.18 | -11.67 |
| 4h thr0.5 | min hold 3h | no overlay | +99.61 | 103 | 47 | 1.47 | 58 | +113.68 | -14.07 | +7.11 | +104.18 | -11.67 |
| 4h thr0.5 | flip exit (current) | max2 pos + max2 same-dir | +92.06 | 68 | 46 | 1.61 | 44 | +113.36 | -21.30 | +19.28 | +88.67 | -15.89 |
| 4h thr0.5 | min hold 3h | max2 pos + max2 same-dir | +92.06 | 68 | 46 | 1.61 | 44 | +113.36 | -21.30 | +19.28 | +88.67 | -15.89 |
| 4h thr0.5 | trail/stop only, 24h time stop | trend both ways (5d) | +85.42 | 68 | 56 | 2.12 | 24 | +68.51 | +16.91 | +41.14 | +46.47 | -2.18 |
| 4h thr0.5 | trail/stop only, 24h, looser trail | trend both ways (5d) | +81.46 | 68 | 57 | 2.01 | 24 | +67.53 | +13.93 | +39.48 | +46.98 | -5.00 |
| 2h thr0.25 | trail/stop only, 72h time stop | trend both ways (5d) | +74.40 | 158 | 47 | 1.39 | 29 | +76.87 | -2.46 | +11.74 | +51.38 | +11.28 |
| 1h thr0.25 | trail/stop only, 24h, tighter trail | max2 pos + max2 same-dir | +72.61 | 327 | 46 | 1.30 | 39 | +98.09 | -25.48 | -3.06 | +52.32 | +23.35 |
| 1h thr0.25 | trail/stop only, 24h, tighter trail | no overlay | +57.24 | 495 | 45 | 1.14 | 62 | +99.74 | -42.50 | -3.04 | +45.56 | +14.72 |
| 1h thr0.25 | trail/stop only, 24h time stop | no overlay | +56.37 | 430 | 46 | 1.14 | 62 | +86.92 | -30.55 | -10.86 | +72.63 | -5.40 |

## Top 15 by WORST third (most consistent)

| market | exit | overlay | net | trades | win% | PF | max DD | long | short | 1/3 | 2/3 | 3/3 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2h thr0.25 | trail/stop only, 72h time stop | trend both ways (5d) | +74.40 | 158 | 47 | 1.39 | 29 | +76.87 | -2.46 | +11.74 | +51.38 | +11.28 |
| 2h thr0.25 | trail/stop only, 72h time stop | max2 pos + max2 same-dir | +40.77 | 125 | 47 | 1.25 | 40 | +37.60 | +3.18 | +20.14 | +13.48 | +7.15 |
| 4h thr0.5 | trail/stop only, 24h, tighter trail | trend both ways (5d) | +55.57 | 71 | 52 | 1.71 | 23 | +41.90 | +13.68 | +27.33 | +26.91 | +1.34 |
| 4h thr0.5 | trail/stop only, 24h, tighter trail | max2 pos + max2 same-dir | +31.80 | 84 | 48 | 1.27 | 25 | +24.30 | +7.50 | +26.88 | +3.70 | +1.22 |
| 4h thr0.5 | flip exit (current) | trend both ways (5d) | +139.70 | 63 | 51 | 2.26 | 35 | +140.89 | -1.20 | +30.31 | +111.46 | -2.07 |
| 4h thr0.5 | min hold 3h | trend both ways (5d) | +139.70 | 63 | 51 | 2.26 | 35 | +140.89 | -1.20 | +30.31 | +111.46 | -2.07 |
| 2h thr0.25 | trail/stop only, 72h time stop | no overlay | +24.71 | 207 | 48 | 1.09 | 44 | +56.59 | -31.88 | +2.44 | -2.11 | +24.38 |
| 4h thr0.5 | trail/stop only, 24h time stop | trend both ways (5d) | +85.42 | 68 | 56 | 2.12 | 24 | +68.51 | +16.91 | +41.14 | +46.47 | -2.18 |
| 4h thr0.5 | trail/stop only, 24h, tighter trail | no overlay | +36.30 | 117 | 47 | 1.24 | 33 | +25.00 | +11.30 | +22.14 | +16.47 | -2.32 |
| 1h thr0.25 | trail/stop only, 24h, tighter trail | no overlay | +57.24 | 495 | 45 | 1.14 | 62 | +99.74 | -42.50 | -3.04 | +45.56 | +14.72 |
| 1h thr0.25 | trail/stop only, 24h, tighter trail | max2 pos + max2 same-dir | +72.61 | 327 | 46 | 1.30 | 39 | +98.09 | -25.48 | -3.06 | +52.32 | +23.35 |
| 2h thr0.25 | trail/stop only, 24h time stop | trend both ways (5d) | +16.78 | 176 | 42 | 1.08 | 63 | +26.63 | -9.85 | -0.41 | +20.48 | -3.29 |
| 1h thr1.0 | trail/stop only, 24h time stop | trend both ways (5d) | +20.35 | 151 | 45 | 1.16 | 31 | +42.20 | -21.84 | +12.91 | +11.29 | -3.86 |
| 1h thr1.0 | trail/stop only, 24h, looser trail | trend both ways (5d) | +37.59 | 145 | 45 | 1.25 | 40 | +70.74 | -33.14 | +32.38 | +9.62 | -4.41 |
| 4h thr0.5 | trail/stop only, 24h, looser trail | trend both ways (5d) | +81.46 | 68 | 57 | 2.01 | 24 | +67.53 | +13.93 | +39.48 | +46.98 | -5.00 |

## Profitable in ALL three slices: 4 of 162 variants

| market | exit | overlay | net | trades | win% | PF | max DD | long | short | 1/3 | 2/3 | 3/3 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2h thr0.25 | trail/stop only, 72h time stop | trend both ways (5d) | +74.40 | 158 | 47 | 1.39 | 29 | +76.87 | -2.46 | +11.74 | +51.38 | +11.28 |
| 4h thr0.5 | trail/stop only, 24h, tighter trail | trend both ways (5d) | +55.57 | 71 | 52 | 1.71 | 23 | +41.90 | +13.68 | +27.33 | +26.91 | +1.34 |
| 2h thr0.25 | trail/stop only, 72h time stop | max2 pos + max2 same-dir | +40.77 | 125 | 47 | 1.25 | 40 | +37.60 | +3.18 | +20.14 | +13.48 | +7.15 |
| 4h thr0.5 | trail/stop only, 24h, tighter trail | max2 pos + max2 same-dir | +31.80 | 84 | 48 | 1.27 | 25 | +24.30 | +7.50 | +26.88 | +3.70 | +1.22 |

## Average net by factor (shows which choices matter, not just the best row)


**By market**

| market | avg net | best | avg trades | avg PF |
|---|---:|---:|---:|---:|
| 4h thr0.5 | +80.94 | +139.70 | 82 | 1.65 |
| 1h thr0.25 | +19.98 | +72.61 | 357 | 1.07 |
| 2h thr0.25 | -2.19 | +74.40 | 189 | 1.02 |
| 1h thr1.0 | -2.62 | +37.59 | 246 | 1.00 |
| 2h thr0.5 | -27.99 | +5.19 | 176 | 0.90 |
| 1h thr0.5 | -32.19 | -0.31 | 336 | 0.89 |
| 30m thr0.5 | -71.83 | +4.67 | 714 | 0.86 |
| 30m thr1.0 | -92.95 | -28.83 | 541 | 0.78 |
| 30m thr0.25 (current) | -102.92 | -32.62 | 762 | 0.82 |

**By exit**

| exit | avg net | best | avg trades | avg PF |
|---|---:|---:|---:|---:|
| trail/stop only, 72h time stop | -12.69 | +126.73 | 351 | 1.06 |
| trail/stop only, 24h, tighter trail | -24.15 | +72.61 | 400 | 0.98 |
| trail/stop only, 24h, looser trail | -26.92 | +81.46 | 318 | 1.00 |
| flip exit (current) | -29.81 | +139.70 | 421 | 0.99 |
| min hold 3h | -30.14 | +139.70 | 416 | 0.99 |
| trail/stop only, 24h time stop | -30.81 | +85.42 | 363 | 0.98 |

**By overlay**

| overlay | avg net | best | avg trades | avg PF |
|---|---:|---:|---:|---:|
| trend both ways (5d) | -16.54 | +139.70 | 314 | 1.04 |
| max2 pos + max2 same-dir | -17.40 | +117.15 | 314 | 1.00 |
| no overlay | -43.32 | +126.73 | 507 | 0.96 |

*Caveats: ~100 days, mostly one market regime; ~160 variants tried, so the single best row is likely partly luck. Trust patterns (a whole column of settings that works), not one cell.*