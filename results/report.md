# Aggressive bot replay

Coins: 11, window ~101 days (2026-07-28 to 2026-11-06). $100 per position, fees 0.043%/side + 0.01% slippage.

## All variants (net P&L in $ at $100/position)

| variant | net | vs baseline | trades | win% | PF | max DD | longs | shorts | 1st half | 2nd half |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | -142.18 | +0.00 | 1137 | 34 | 0.80 | 168.0 | -10.35 | -131.83 | -75.32 | -66.86 |
| no longs below 96-bar MA | -151.05 | -8.87 | 909 | 33 | 0.75 | 189.3 | -21.69 | -129.36 | -98.97 | -52.08 |
| no longs below 240-bar MA | -122.95 | +19.22 | 928 | 34 | 0.80 | 154.0 | +4.06 | -127.02 | -66.16 | -56.79 |
| no longs below 480-bar MA | -130.19 | +11.99 | 950 | 34 | 0.80 | 162.7 | -3.17 | -127.02 | -71.84 | -58.35 |
| trend-follow both ways, 96-bar MA | -128.74 | +13.44 | 699 | 31 | 0.72 | 127.0 | -24.86 | -103.89 | -70.01 | -58.74 |
| trend-follow both ways, 240-bar MA | -95.13 | +47.05 | 760 | 33 | 0.80 | 105.7 | +1.37 | -96.50 | -47.52 | -47.61 |
| trend-follow both ways, 480-bar MA | -83.23 | +58.95 | 766 | 33 | 0.83 | 94.9 | -2.16 | -81.08 | -36.96 | -46.27 |
| BTC trend gates longs (240) | -144.10 | -1.92 | 868 | 34 | 0.75 | 167.2 | -18.22 | -125.89 | -76.08 | -68.03 |
| max 3 same-direction | -129.74 | +12.44 | 1020 | 35 | 0.80 | 160.1 | -3.45 | -126.29 | -64.79 | -64.95 |
| max 2 same-direction | -95.06 | +47.12 | 803 | 35 | 0.82 | 119.9 | +0.83 | -95.89 | -53.54 | -41.53 |
| 2h no-flip lockout | -144.30 | -2.12 | 1090 | 34 | 0.79 | 179.6 | -18.49 | -125.81 | -76.29 | -68.01 |
| 4h no-flip lockout | -130.42 | +11.76 | 1039 | 34 | 0.80 | 155.2 | -10.83 | -119.59 | -76.90 | -53.52 |
| 8h no-flip lockout | -159.36 | -17.18 | 1009 | 33 | 0.75 | 170.0 | -25.12 | -134.24 | -78.12 | -81.24 |
| 4h lockout, any direction | -123.93 | +18.25 | 1032 | 34 | 0.81 | 149.6 | -4.03 | -119.90 | -75.74 | -48.20 |
| 12h lockout, any direction | -138.80 | +3.38 | 871 | 32 | 0.76 | 155.5 | -37.08 | -101.73 | -96.89 | -41.91 |
| longs at half size | -137.48 | +4.70 | 1138 | 34 | 0.75 | 168.9 | -5.64 | -131.83 | -83.10 | -54.37 |
| max 6 positions | -148.75 | -6.57 | 1336 | 34 | 0.83 | 179.0 | -3.89 | -144.86 | -71.88 | -76.87 |
| max 2 positions | -87.60 | +54.58 | 725 | 34 | 0.82 | 114.9 | +2.61 | -90.21 | -47.82 | -39.78 |
| profit protection off | -74.57 | +67.61 | 786 | 32 | 0.90 | 149.2 | +34.62 | -109.18 | +27.94 | -102.51 |
| combo: no longs <240MA + max 3 same-dir | -128.09 | +14.09 | 840 | 34 | 0.78 | 153.2 | -5.44 | -122.65 | -68.96 | -59.13 |
| combo: above + 4h no-flip | -109.71 | +32.46 | 787 | 35 | 0.79 | 136.0 | +3.84 | -113.56 | -51.91 | -57.81 |
| combo: both-way trend 240 + 4h no-flip | -104.63 | +37.55 | 738 | 33 | 0.78 | 114.2 | -2.28 | -102.36 | -47.60 | -57.03 |

## Baseline by coin

| coin | net | trades | win% |
|---|---:|---:|---:|
| LINK | -26.57 | 103 | 28 |
| NEAR | -25.22 | 106 | 33 |
| HYPE | -25.15 | 110 | 37 |
| XRP | -19.46 | 107 | 29 |
| AVAX | -19.15 | 106 | 32 |
| SUI | -14.75 | 103 | 34 |
| VVV | -13.27 | 107 | 40 |
| BTC | -12.30 | 99 | 27 |
| ETH | -2.96 | 101 | 36 |
| ZEC | +5.54 | 95 | 37 |
| SOL | +11.10 | 100 | 39 |

## Baseline by exit reason

| reason | net | trades | avg |
|---|---:|---:|---:|
| signal | -618.87 | 407 | -1.52 |
| break-even stop | -98.78 | 349 | -0.28 |
| trailing stop | +575.47 | 381 | +1.51 |

## Baseline by hold time

| held | net | trades | avg |
|---|---:|---:|---:|
| <1h | -94.97 | 93 | -1.02 |
| 1-3h | -184.27 | 453 | -0.41 |
| 3-8h | +79.71 | 526 | +0.15 |
| 8-24h | +57.35 | 65 | +0.88 |

## Walk-forward check: drop worst 3 coins of the 1st half (HYPE, VVV, NEAR)

2nd-half net: baseline -66.86 vs with those coins dropped -57.54.

*Caveat: one ~3-month window of mostly one market regime. A variant that wins in both halves and across its parameter settings is more believable than one that wins in a single setting.*