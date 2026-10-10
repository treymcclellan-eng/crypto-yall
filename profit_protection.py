"""
profit_protection.py — Shared exit rules that protect open profits.

Used by all three bots (daily, intraday, aggressive). These rules run IN
ADDITION to each strategy's own exits and stops (which are unchanged):

  1. Break-even stop  — once a position's best price has moved +BE_ATR x ATR
     in our favour, close it if price falls back to entry (plus a small fee
     buffer).
  2. Trailing stop    — once the best price has moved +TRAIL_ATR x ATR in our
     favour, close it if price gives back TRAIL_DIST x ATR from that best price.
  3. Hard stop        — close any position that is down HARD_STOP_ATR x ATR from
     its REAL entry price. (The strategies' own stops are measured from the
     strategy's historical entry, which can be far from where we actually got
     filled.)

After a protective exit the coin is "blocked" from re-entry in the same
direction until the strategy signal resets (goes flat/flips, or gives a fresh
entry signal). Without this the bot would immediately re-buy a position the
strategy still considers long.

Settings (GitHub repo Variables, all optional):
    PROFIT_PROTECTION   "OFF" disables everything here (default ON)
    PP_BE_ATR           break-even activation, in ATRs of profit    (default 1.0)
    PP_TRAIL_ATR        trailing activation, in ATRs of profit      (default 2.0)
    PP_TRAIL_DIST_ATR   trailing distance from best price, in ATRs  (default 1.0)
    PP_HARD_STOP_ATR    hard stop distance from entry, in ATRs; 0 = off (default 3.0)
    PP_BE_FEE_PCT       fee buffer for break-even exit, % of entry  (default 0.1)
"""

import math
import os
import time


# ── Settings ────────────────────────────────────────────────────────────────

def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(str(raw).strip())
    except ValueError:
        print(f"WARNING: {name}={raw!r} is not a number; using default {default}")
        return default


def enabled() -> bool:
    return os.environ.get("PROFIT_PROTECTION", "ON").strip().upper() != "OFF"


def settings() -> dict:
    return {
        "be_atr": _env_float("PP_BE_ATR", 1.0),
        "trail_atr": _env_float("PP_TRAIL_ATR", 2.0),
        "trail_dist": _env_float("PP_TRAIL_DIST_ATR", 1.0),
        "hard_stop_atr": _env_float("PP_HARD_STOP_ATR", 3.0),
        "be_fee_pct": _env_float("PP_BE_FEE_PCT", 0.1),
    }


# ── Helpers ─────────────────────────────────────────────────────────────────

def _side(size: float) -> int:
    return 1 if size > 0 else -1


def _price_for(coin: str, sig: dict, mids: dict | None):
    """Best available current price: exchange mid first, else candle close."""
    try:
        if mids and coin in mids:
            p = float(mids[coin])
            if p > 0 and math.isfinite(p):
                return p
    except (TypeError, ValueError):
        pass
    p = sig.get("price") if sig else None
    try:
        p = float(p)
        if p > 0 and math.isfinite(p):
            return p
    except (TypeError, ValueError):
        pass
    return None


# ── Peak tracking ───────────────────────────────────────────────────────────

def update_peaks(peaks: dict, positions: dict, signals: dict, mids: dict | None,
                 coin_map: dict) -> dict:
    """Return a new {coin: {"peak": price, "side": 1|-1}} for held positions.

    "peak" is the best price seen in our favour since we first saw the
    position (highest for longs, lowest for shorts). It uses the exchange mid
    price plus, when available, the high/low of the latest candle so moves
    between bot runs are not missed. Coins no longer held are dropped.
    """
    peaks = peaks or {}
    by_coin = {}
    for ticker, sig in (signals or {}).items():
        coin = coin_map.get(ticker)
        if coin:
            by_coin[coin] = sig

    new = {}
    for coin, pos in positions.items():
        size = float(pos.get("size", 0))
        if size == 0:
            continue
        side = _side(size)
        entry = float(pos.get("entry_px") or 0)
        sig = by_coin.get(coin, {})
        price = _price_for(coin, sig, mids)

        prev = peaks.get(coin)
        if isinstance(prev, dict) and prev.get("side") == side and prev.get("peak"):
            peak = float(prev["peak"])
            candidates = [price]
            # Candle extremes only once we have a baseline, so a high from
            # before we entered can't be counted.
            candidates.append(sig.get("high") if side == 1 else sig.get("low"))
        else:
            # First time we see this position: start from entry / now.
            peak = entry if entry > 0 else (price or 0.0)
            candidates = [price]

        for c in candidates:
            try:
                c = float(c)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(c) or c <= 0:
                continue
            peak = max(peak, c) if side == 1 else (min(peak, c) if peak > 0 else c)

        if peak > 0:
            new[coin] = {"peak": peak, "side": side}
    return new


# ── Exit check ──────────────────────────────────────────────────────────────

def check_exit(coin: str, pos: dict, sig: dict, peak_rec: dict | None,
               mids: dict | None, cfg: dict | None = None) -> str | None:
    """Return a human-readable reason if the position should be closed, else None."""
    cfg = cfg or settings()
    try:
        atr = float(sig.get("atr"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(atr) or atr <= 0:
        return None

    size = float(pos.get("size", 0))
    entry = float(pos.get("entry_px") or 0)
    if size == 0 or entry <= 0:
        return None
    side = _side(size)

    price = _price_for(coin, sig, mids)
    if price is None:
        return None

    peak = float(peak_rec["peak"]) if peak_rec and peak_rec.get("peak") else entry
    fav = side * (peak - entry)          # best profit reached, in price units
    now = side * (price - entry)         # profit right now, in price units

    # 3. Hard stop from real entry
    if cfg["hard_stop_atr"] > 0 and -now >= cfg["hard_stop_atr"] * atr:
        return (f"hard stop: down {-now / atr:.1f} ATR ({-now / entry * 100:.1f}%) "
                f"from entry {entry:g}")

    floor = None
    label = ""

    # 2. Trailing stop
    if cfg["trail_atr"] > 0 and fav >= cfg["trail_atr"] * atr:
        floor = fav - cfg["trail_dist"] * atr
        label = (f"trailing stop: best +{fav / atr:.1f} ATR, gave back to "
                 f"+{now / atr:.1f} ATR")

    # 1. Break-even stop (never lower than an active trailing floor)
    if cfg["be_atr"] > 0 and fav >= cfg["be_atr"] * atr:
        be_floor = min(cfg["be_fee_pct"] / 100.0 * entry, 0.5 * fav)
        if floor is None or be_floor > floor:
            floor = be_floor
            label = (f"break-even stop: best +{fav / atr:.1f} ATR, fell back to "
                     f"+{now / atr:.1f} ATR")

    if floor is not None and now <= floor:
        return label
    return None


def find_exits(positions: dict, signals: dict, peaks: dict, mids: dict | None,
               coin_map: dict) -> dict:
    """Return {coin: reason} for managed positions that trip a protective exit."""
    if not enabled():
        return {}
    cfg = settings()
    by_coin = {}
    for ticker, sig in (signals or {}).items():
        coin = coin_map.get(ticker)
        if coin:
            by_coin[coin] = sig

    exits = {}
    for coin, pos in positions.items():
        sig = by_coin.get(coin)
        if sig is None:
            print(f"Profit protection: no signal/ATR for held {coin}; skipped this run")
            continue
        reason = check_exit(coin, pos, sig, (peaks or {}).get(coin), mids, cfg)
        if reason:
            exits[coin] = reason
    return exits


# ── Re-entry blocking ───────────────────────────────────────────────────────

def update_blocks(blocked: dict, signals: dict, coin_map: dict) -> dict:
    """Drop re-entry blocks once the strategy has reset for that coin.

    blocked: {coin: side} where side is the direction (1 long / -1 short) we
    were protectively stopped out of. The block lifts when the strategy signal
    is no longer that direction, or the strategy gives a fresh entry signal.
    """
    blocked = dict(blocked or {})
    by_coin = {}
    for ticker, sig in (signals or {}).items():
        coin = coin_map.get(ticker)
        if coin:
            by_coin[coin] = sig

    for coin in list(blocked):
        sig = by_coin.get(coin)
        if sig is None:
            continue
        side = blocked[coin]
        fresh_entry = sig.get("action") in ("buy", "enter_short")
        if sig.get("signal", 0) != side or fresh_entry:
            del blocked[coin]
    return blocked


# ── Re-entry cooldown after stop-outs ───────────────────────────────────────

def cooldown_seconds() -> float:
    """REENTRY_COOLDOWN_HOURS (default 24; 0 disables)."""
    return max(0.0, _env_float("REENTRY_COOLDOWN_HOURS", 24.0)) * 3600.0


def active_cooldowns(cooldowns: dict | None) -> dict:
    """Return {coin: start_epoch} for cooldowns that have not yet expired."""
    secs = cooldown_seconds()
    if secs <= 0:
        return {}
    now = time.time()
    out = {}
    for coin, started in (cooldowns or {}).items():
        try:
            if now - float(started) < secs:
                out[coin] = float(started)
        except (TypeError, ValueError):
            continue
    return out


def register_stopout(cooldowns: dict, coin: str, pos: dict | None,
                     mids: dict | None, protect: bool) -> None:
    """Start a cooldown on `coin` if the close was a protective exit or a loss."""
    if cooldown_seconds() <= 0:
        return
    losing = False
    try:
        entry = float((pos or {}).get("entry_px") or 0)
        size = float((pos or {}).get("size") or 0)
        price = float((mids or {}).get(coin) or 0)
        if entry > 0 and price > 0 and size != 0:
            losing = _side(size) * (price - entry) < 0
    except (TypeError, ValueError):
        pass
    if protect or losing:
        cooldowns[coin] = time.time()

