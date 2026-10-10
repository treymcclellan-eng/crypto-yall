"""
hyperliquid_executor.py — Live trading executor for Hyperliquid DEX.

Translates signals from signal_utils into actual trades on Hyperliquid.
Runs daily via GitHub Actions, enforces risk guardrails, and sends
execution notifications through notifier.py.

Required environment variables:
    HL_PRIVATE_KEY      – API wallet private key (trading-only, no withdraw)
    HL_ACCOUNT_ADDRESS  – Main wallet address (0x…) that owns the funds
    HL_TESTNET          – "true" to use testnet, else mainnet
    SEGREGATED_CAPITAL  – USDC allocated to bot (e.g. "10000")
    DAILY_DD_PCT        – Max daily drawdown % before auto-pause (e.g. "5")
    MAX_POSITIONS       – Max concurrent open positions (4 aggressive)
    KILL_SWITCH         – "OFF" to halt all trading, else trades enabled
    GIST_TOKEN / GIST_ID – State persistence (same as notifier)
    GMAIL_USER / GMAIL_APP_PASSWORD / NOTIFY_EMAILS – email alerts
    TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID – telegram alerts
"""

import json
import os
import sys
import datetime as dt
from decimal import Decimal, ROUND_DOWN

import requests
from eth_account import Account

import profit_protection
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

from data_loader import fetch_data
from indicators import compute_all
from hmm_engine import causal_hmm_regimes
from strategy import generate_signals
from backtester import get_asset_profile
from signal_utils import classify_signal


# ── Config ───────────────────────────────────────────────────────────────────

# Map yfinance tickers → Hyperliquid symbols
HL_TICKER_MAP = {
    "BTC-USD": "BTC",
    "ETH-USD": "ETH",
    "SOL-USD": "SOL",
    "AVAX-USD": "AVAX",
    "LINK-USD": "LINK",
    "SUI20947-USD": "SUI",
    "XRP-USD": "XRP",
    "ZEC-USD": "ZEC",
    "NEAR-USD": "NEAR",
    "HYPE32196-USD": "HYPE",
    "VVV-USD": "VVV",
}

ASSETS = {
    "BTC-USD": "Bitcoin (BTC)",
    "ETH-USD": "Ethereum (ETH)",
    "SOL-USD": "Solana (SOL)",
    "AVAX-USD": "Avalanche (AVAX)",
    "LINK-USD": "Chainlink (LINK)",
    "SUI20947-USD": "Sui (SUI)",
    "XRP-USD": "XRP",
    "ZEC-USD": "Zcash (ZEC)",
    "NEAR-USD": "NEAR Protocol (NEAR)",
    "HYPE32196-USD": "Hyperliquid (HYPE)",
    "VVV-USD": "Venice Token (VVV)",
}

STATE_FILENAME = "trading_state.json"
POSITION_SIZE_PCT = 0.01  # 1% of segregated capital per trade


# ── State Persistence (GitHub Gist) ─────────────────────────────────────────

def load_trading_state() -> dict:
    gist_token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("GIST_ID")
    if not gist_token or not gist_id:
        return {}
    resp = requests.get(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {gist_token}"},
        timeout=15,
    )
    if resp.status_code != 200:
        return {}
    files = resp.json().get("files", {})
    if STATE_FILENAME not in files:
        return {}
    try:
        return json.loads(files[STATE_FILENAME]["content"])
    except Exception:
        return {}


def save_trading_state(state: dict):
    gist_token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("GIST_ID")
    if not gist_token or not gist_id:
        return
    requests.patch(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {gist_token}"},
        json={"files": {STATE_FILENAME: {"content": json.dumps(state, indent=2)}}},
        timeout=15,
    )


# ── Hyperliquid Client ──────────────────────────────────────────────────────

def get_client():
    """Return (info, exchange, account_address)."""
    priv_key = os.environ.get("HL_PRIVATE_KEY")
    account_address = os.environ.get("HL_ACCOUNT_ADDRESS")
    is_testnet = os.environ.get("HL_TESTNET", "true").lower() == "true"

    if not priv_key or not account_address:
        raise RuntimeError("HL_PRIVATE_KEY and HL_ACCOUNT_ADDRESS required")

    base_url = constants.TESTNET_API_URL if is_testnet else constants.MAINNET_API_URL
    wallet = Account.from_key(priv_key)
    info = Info(base_url, skip_ws=True)
    account_address = _resolve_account_address(info, wallet.address, account_address.strip())
    exchange = Exchange(wallet, base_url, account_address=account_address)

    return info, exchange, account_address


def _resolve_account_address(info, signer_address: str, configured: str) -> str:
    """Return the address whose positions and balance the bots should read.

    Orders are signed by HL_PRIVATE_KEY and land on whatever account that key
    trades for, no matter what HL_ACCOUNT_ADDRESS says. If the secret holds the
    wrong address (for example the API wallet's own address), every read
    (positions, fills, equity) comes back empty while trades still fill, which
    makes the bots re-buy coins they already hold. So ask Hyperliquid which
    account this key trades for and use that instead.
    """
    try:
        role = info.post("/info", {"type": "userRole", "user": signer_address})
    except Exception as e:
        print(f"WARNING: could not look up the signing key's account ({e}); "
              f"using HL_ACCOUNT_ADDRESS as configured")
        return configured
    kind = role.get("role") if isinstance(role, dict) else None
    master = None
    if kind == "agent":
        master = (role.get("data") or {}).get("user")
    elif kind == "user":
        master = signer_address
    if master and master.lower() != configured.lower():
        print(f"WARNING: HL_ACCOUNT_ADDRESS ({configured}) is not the account this "
              f"key trades for ({master}). Reading positions and equity from "
              f"{master}. Please correct the HL_ACCOUNT_ADDRESS secret.")
        return master
    return configured


def get_account_equity(info, address: str) -> float:
    """Total account value in USDC.

    Under Hyperliquid's Unified Account / Portfolio Margin modes the collateral
    sits in the SPOT balance and the perp clearinghouse reports an account
    value of 0 (especially when flat), so read spot USDC plus unrealized perp
    PnL there instead. Standard accounts keep using the perp account value.
    """
    state = info.user_state(address)
    perp_value = float(state["marginSummary"]["accountValue"])
    unrealized = sum(float(p["position"].get("unrealizedPnl", 0) or 0)
                     for p in state.get("assetPositions", []))

    mode = ""
    try:
        resp = info.post("/info", {"type": "userAbstraction", "user": address})
        mode = str(resp).lower()
    except Exception as e:
        print(f"WARNING: could not read account mode: {e}")

    spot_usdc = 0.0
    try:
        spot = info.spot_user_state(address)
        spot_usdc = sum(float(b.get("total", 0) or 0)
                        for b in spot.get("balances", [])
                        if b.get("coin") == "USDC")
    except Exception as e:
        print(f"WARNING: could not read spot balances: {e}")

    unified = "unified" in mode or "portfolio" in mode
    if unified:
        equity = spot_usdc + unrealized
        print(f"Unified account: equity = spot USDC {spot_usdc:,.2f} + unrealized PnL "
              f"{unrealized:,.2f} = {equity:,.2f}")
        return equity
    if perp_value <= 0 and spot_usdc > 0:
        equity = spot_usdc + unrealized
        print(f"Perp account value is 0 but spot USDC is {spot_usdc:,.2f}; "
              f"using spot-based equity {equity:,.2f}")
        return equity
    return perp_value


def _positions_from_fills(info, address: str) -> dict:
    """Independent view of open positions, derived from recent fills.

    Each fill carries `startPosition` (position before the fill) and a side
    ("B" buy / "A" sell), so the latest fill per coin tells us the position
    after it. This does not depend on the clearinghouse-state endpoint, so it
    still works if that endpoint returns nothing for the account.
    """
    out = {}
    try:
        fills = info.user_fills(address)
    except Exception as e:
        print(f"WARNING: could not read fills for position cross-check: {e}")
        return out

    latest = {}
    for f in fills:
        coin = f.get("coin")
        if not coin or coin.startswith("@") or "/" in coin:
            continue  # spot fills
        key = (int(f.get("time", 0)), int(f.get("tid", 0)))
        if coin not in latest or key > latest[coin][0]:
            latest[coin] = (key, f)

    for coin, (_, f) in latest.items():
        start = float(f.get("startPosition", 0))
        sz = float(f["sz"])
        after = round(start + sz if f.get("side") == "B" else start - sz, 8)
        if abs(after) > 1e-9:
            out[coin] = {
                "size": after,  # signed: + long, - short
                "entry_px": float(f.get("px", 0)),
                "unrealized_pnl": 0.0,
                "source": "fills",
            }
    return out


def get_open_positions(info, address: str) -> dict:
    """Return {coin: {size, entry_px, unrealized_pnl}} for open positions.

    Reads the clearinghouse state, then cross-checks against recent fills.
    Any coin that fills say we hold but the clearinghouse state omits is
    added (with a loud warning) so the bots never think the account is flat
    while it is not.
    """
    state = info.user_state(address)
    positions = {}
    for p in state.get("assetPositions", []):
        pos = p["position"]
        size = float(pos["szi"])
        if size == 0:
            continue
        positions[pos["coin"]] = {
            "size": size,  # signed: + long, - short
            "entry_px": float(pos["entryPx"]),
            "unrealized_pnl": float(pos["unrealizedPnl"]),
        }

    from_fills = _positions_from_fills(info, address)
    missing = {c: p for c, p in from_fills.items() if c not in positions}
    if missing:
        print(f"WARNING: clearinghouse state omitted {sorted(missing)} but recent "
              f"fills show open positions — using fills-derived positions: "
              f"{ {c: p['size'] for c, p in missing.items()} }")
        positions.update(missing)
    print(f"Open positions on account: { {c: p['size'] for c, p in positions.items()} }")
    return positions


def close_position(info, exchange, coin: str, size: float, slippage: float = 0.05) -> dict:
    """Close `size` (signed: + long, - short) with a reduce-only IOC order.

    Unlike exchange.market_close(), this does not re-query the clearinghouse
    state to find the position, so it works even when that read is empty.
    """
    is_buy = size < 0  # closing a short means buying
    mid = get_mid_price(info, coin)
    sz_decimals = get_size_decimals(info, coin)
    px = mid * (1 + slippage) if is_buy else mid * (1 - slippage)
    px = round(float(f"{px:.5g}"), max(0, 6 - sz_decimals))
    close_sz = round(abs(size), sz_decimals)
    return exchange.order(
        coin, is_buy, close_sz, px,
        {"limit": {"tif": "Ioc"}}, reduce_only=True,
    )


def apply_exposure_cap(trades: list, positions: dict, equity: float, info,
                       max_leverage: float | None = None) -> list:
    """Drop all new opens/adds when account-wide gross leverage is too high.

    Closes are always allowed. This is a backstop against runaway position
    stacking, whatever the cause.
    """
    if max_leverage is None:
        max_leverage = float(os.environ.get("MAX_ACCOUNT_LEVERAGE", "2.0"))
    if equity <= 0:
        if not positions:
            # Reads show an empty, unfunded account while we are trading: the
            # reads cannot be trusted, so do not open anything. Closes only.
            kept = [t for t in trades if t["action"] == "close"]
            print(f"ERROR: account equity reads $0 and no positions are visible — "
                  f"HL_ACCOUNT_ADDRESS is probably wrong. Blocking "
                  f"{len(trades) - len(kept)} open/add trade(s).")
            return kept
        print("WARNING: equity read as 0 — exposure cap not enforced")
        return trades
    mids = info.all_mids()
    gross = sum(abs(p["size"]) * float(mids.get(c, p["entry_px"]))
                for c, p in positions.items())
    lev = gross / equity
    if lev <= max_leverage:
        return trades
    kept = [t for t in trades if t["action"] == "close"]
    dropped = len(trades) - len(kept)
    print(f"EXPOSURE CAP: account leverage {lev:.2f}x exceeds {max_leverage:.2f}x — "
          f"blocking {dropped} open/add trade(s); closes still allowed")
    return kept


def get_mid_price(info, coin: str) -> float:
    return float(info.all_mids()[coin])


def coin_is_listed(info, coin: str) -> bool:
    """Check if a coin is available for trading on the current environment."""
    return coin in info.all_mids()


# ── Signal Computation (reuse notifier logic) ───────────────────────────────

def compute_all_signals() -> dict:
    """Return {ticker: {action_key, regime, price, bull_conf, signal}} — aggressive mode."""
    all_data = fetch_data(tickers=list(ASSETS.keys()))
    current = {}

    for ticker in ASSETS:
        try:
            raw = all_data.get(ticker)
            if raw is None or raw.empty:
                continue

            df = compute_all(raw)
            regimes, bull_probs, bear_probs = causal_hmm_regimes(df)
            profile = get_asset_profile(ticker)
            regime = regimes.iloc[-1] if len(regimes) > 0 else "Unknown"
            price = float(df["Close"].iloc[-1])
            bull_conf = float(bull_probs.iloc[-1]) if len(bull_probs) > 0 else 0.0
            bear_conf = float(bear_probs.iloc[-1]) if len(bear_probs) > 0 else 0.0

            # Aggressive mode only (per call decision)
            sig = generate_signals(
                df, regimes, bull_probs=bull_probs, bear_probs=bear_probs,
                aggressive=True, bull_leverage=profile["max_bull_leverage"],
                allow_short=profile["allow_short"], atr_mult=profile["atr_mult"],
            )
            last = int(sig["Signal"].iloc[-1])
            prev = int(sig["Signal"].iloc[-2]) if len(sig) >= 2 else last
            action_key = classify_signal(last, prev, regime)

            current[ticker] = {
                "signal": last,
                "action": action_key,
                "regime": regime,
                "price": price,
                "bull_conf": bull_conf,
                "bear_conf": bear_conf,
                "leverage": float(sig["Leverage"].iloc[-1]) if "Leverage" in sig.columns else 1.0,
                "atr": float(df["ATR"].iloc[-1]) if "ATR" in df.columns else 0.0,
            }
        except Exception as e:
            print(f"Error computing signal for {ticker}: {e}")
            continue

    return current


# ── Trade Decisions ─────────────────────────────────────────────────────────

def decide_trades(signals: dict, open_positions: dict, max_positions: int,
                   all_open_positions: dict | None = None,
                   extra_exits: dict | None = None,
                   blocked: dict | None = None,
                   cooldown: dict | None = None) -> list[dict]:
    """
    Reconcile signals vs current positions and return list of trade intents.

    `open_positions` is this bot's OWN tracked/owned positions (used for
    closes). `all_open_positions` is every position currently open on the
    exchange account, regardless of which bot owns it — used to avoid
    opening a new position in a coin another bot already holds. Defaults
    to `open_positions` for backward compatibility.

    `extra_exits` is {coin: reason} for protective exits (break-even,
    trailing, hard stop — see profit_protection.py). `blocked` is
    {coin: side} of coins we were protectively stopped out of and must not
    re-enter in that direction until the strategy resets.

    Each intent: {ticker, hl_coin, action, side, reason}
    action: "open_long" | "open_short" | "close"
    """
    extra_exits = extra_exits or {}
    cooldown = cooldown or {}
    blocked = blocked or {}
    trades = []
    if all_open_positions is None:
        all_open_positions = open_positions

    # Step 1: Determine which current positions need to be closed
    for ticker, info in signals.items():
        hl_coin = HL_TICKER_MAP[ticker]
        current_pos = open_positions.get(hl_coin)
        action_key = info["action"]

        if current_pos is None:
            continue

        is_long = current_pos["size"] > 0
        is_short = current_pos["size"] < 0

        # Close conditions are LEVEL-based: if we hold a position that the
        # strategy no longer wants, close it. (The old edge-based check only
        # fired on the single bar where the signal changed, so one skipped
        # run left the position open forever.)
        sig_val = info.get("signal", 0)
        should_close = False
        reason = ""
        if is_long and sig_val != 1:
            should_close = True
            reason = f"Strategy no longer long ({action_key})"
        elif is_short and sig_val != -1:
            should_close = True
            reason = f"Strategy no longer short ({action_key})"

        protect = False
        if not should_close and hl_coin in extra_exits:
            should_close = True
            protect = True
            reason = extra_exits[hl_coin]

        if should_close:
            trades.append({
                "ticker": ticker,
                "hl_coin": hl_coin,
                "action": "close",
                "side": "long" if is_long else "short",
                "size": current_pos["size"],
                "reason": reason,
                "protect": protect,
            })

    # Step 2: Determine which new positions to open
    # Count positions we'll have AFTER closes
    closes_by_coin = {t["hl_coin"] for t in trades if t["action"] == "close"}
    remaining_positions = {
        c: p for c, p in open_positions.items() if c not in closes_by_coin
    }
    slots_available = max_positions - len(remaining_positions)

    # Coins with an open position ANYWHERE on the account (any bot), minus
    # coins we're closing ourselves this cycle (which frees that coin up).
    all_open_coins = set(all_open_positions.keys()) - closes_by_coin

    # Candidate opens, sorted by confidence (highest first)
    open_candidates = []
    for ticker, info in signals.items():
        hl_coin = HL_TICKER_MAP[ticker]
        action_key = info["action"]

        # Skip if we already have a position in the right direction, OR if
        # ANY bot on this account already has an open position in this coin.
        existing = remaining_positions.get(hl_coin)
        if existing or hl_coin in all_open_coins:
            continue
        if hl_coin in extra_exits:
            continue  # just closed by a protective exit this run
        if hl_coin in cooldown:
            continue  # cooling down after a recent stop-out

        # Open on fresh entry (buy/enter_short) OR sync when strategy
        # says we should be holding long/short but we have no position.
        if action_key in ("buy",) and blocked.get(hl_coin) != 1:
            reason = "BUY signal" if action_key == "buy" else "Sync to hold_long (strategy already in position)"
            open_candidates.append({
                "ticker": ticker,
                "hl_coin": hl_coin,
                "action": "open_long",
                "side": "long",
                "reason": reason,
                "confidence": info["bull_conf"],
            })
        elif action_key in ("enter_short",) and blocked.get(hl_coin) != -1:
            reason = "ENTER SHORT signal" if action_key == "enter_short" else "Sync to hold_short (strategy already in position)"
            open_candidates.append({
                "ticker": ticker,
                "hl_coin": hl_coin,
                "action": "open_short",
                "side": "short",
                "reason": reason,
                "confidence": info["bear_conf"],
            })

    open_candidates.sort(key=lambda x: x["confidence"], reverse=True)
    trades.extend(open_candidates[:slots_available])

    return trades


# ── Order Execution ─────────────────────────────────────────────────────────

def round_size(size: float, sz_decimals: int) -> float:
    """Round position size down to the coin's size decimals."""
    if sz_decimals <= 0:
        return float(int(size))
    q = Decimal("1").scaleb(-sz_decimals)
    return float(Decimal(str(size)).quantize(q, rounding=ROUND_DOWN))


def get_size_decimals(info, coin: str) -> int:
    meta = info.meta()
    for universe in meta.get("universe", []):
        if universe["name"] == coin:
            return int(universe["szDecimals"])
    return 3  # safe default


def execute_trade(info, exchange, trade: dict, capital: float, leverage: float) -> dict:
    """Execute a single trade via Hyperliquid market order. Returns result dict."""
    coin = trade["hl_coin"]

    if trade["action"] == "close":
        resp = close_position(info, exchange, coin, trade["size"])
        return _parse_response(trade, resp, info, coin)

    # Open new position: size = (capital * 0.01 * leverage) / price
    mid = get_mid_price(info, coin)
    notional = capital * POSITION_SIZE_PCT * leverage
    raw_size = notional / mid
    sz_decimals = get_size_decimals(info, coin)
    size = round_size(raw_size, sz_decimals)

    if size <= 0:
        return {**trade, "status": "skipped", "reason": "Size rounded to zero"}

    # Set leverage before opening (cross margin)
    try:
        exchange.update_leverage(int(leverage), coin, True)
    except Exception as e:
        print(f"Warning: could not set leverage for {coin}: {e}")

    is_buy = trade["action"] == "open_long"
    resp = exchange.market_open(coin, is_buy, size)
    return _parse_response(trade, resp, info, coin)


def _parse_response(trade: dict, resp: dict, info, coin: str) -> dict:
    """Extract fill info from Hyperliquid response."""
    result = {**trade}
    try:
        if resp.get("status") == "ok":
            statuses = resp["response"]["data"]["statuses"]
            for s in statuses:
                if "filled" in s:
                    f = s["filled"]
                    result["status"] = "filled"
                    result["fill_size"] = float(f["totalSz"])
                    result["fill_price"] = float(f["avgPx"])
                    result["oid"] = f.get("oid")
                    return result
                elif "error" in s:
                    result["status"] = "error"
                    result["error"] = s["error"]
                    return result
            result["status"] = "unknown"
            result["raw"] = resp
        else:
            result["status"] = "error"
            result["error"] = resp.get("response", str(resp))
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"Parse error: {e} | raw={resp}"
    return result


# ── Guardrails ──────────────────────────────────────────────────────────────

def check_kill_switch() -> bool:
    """Return True if trading should halt."""
    return os.environ.get("KILL_SWITCH", "ON").upper() == "OFF"


def check_daily_drawdown(state: dict, current_equity: float, threshold_pct: float) -> tuple[bool, dict]:
    """
    Check if today's drawdown exceeds threshold.
    Returns (should_halt, updated_state_fragment).
    """
    today = dt.date.today().isoformat()
    day_key = f"day_start_{today}"
    day_start = state.get(day_key)

    update = {}
    if day_start is None:
        update[day_key] = current_equity
        return False, update

    drawdown_pct = (current_equity - day_start) / day_start * 100 if day_start > 0 else 0

    if drawdown_pct <= -threshold_pct:
        update["halted_today"] = today
        update["halt_reason"] = f"Daily DD {drawdown_pct:.2f}% exceeded {-threshold_pct}%"
        return True, update

    return False, update


# ── Notifications ───────────────────────────────────────────────────────────

def send_execution_notifications(results: list[dict], status_summary: str):
    """Send email + telegram notifications for trade executions."""
    if not results and not status_summary:
        return

    # Email
    try:
        _send_email(results, status_summary)
    except Exception as e:
        print(f"Email send failed: {e}")

    # Telegram
    try:
        _send_telegram(results, status_summary)
    except Exception as e:
        print(f"Telegram send failed: {e}")


def _send_email(results: list[dict], status_summary: str):
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    recipients = os.environ.get("NOTIFY_EMAILS", "")
    if not user or not password or not recipients:
        return

    recipient_list = [e.strip() for e in recipients.split(",")]

    rows = ""
    for r in results:
        status_color = "#1f883d" if r.get("status") == "filled" else "#cf222e"
        fill_px = f"${r.get('fill_price', 0):,.2f}" if r.get("status") == "filled" else "—"
        fill_sz = f"{r.get('fill_size', 0):.6g}" if r.get("status") == "filled" else "—"
        rows += f"""
        <tr>
            <td style="padding:10px;border-bottom:1px solid #e1e4e8;color:#1a1a1a;">{r['ticker']}</td>
            <td style="padding:10px;border-bottom:1px solid #e1e4e8;color:#1a1a1a;">{r['action']}</td>
            <td style="padding:10px;border-bottom:1px solid #e1e4e8;color:{status_color};font-weight:bold;">{r.get('status', '?').upper()}</td>
            <td style="padding:10px;border-bottom:1px solid #e1e4e8;color:#1a1a1a;">{fill_sz}</td>
            <td style="padding:10px;border-bottom:1px solid #e1e4e8;color:#1a1a1a;">{fill_px}</td>
            <td style="padding:10px;border-bottom:1px solid #e1e4e8;color:#1a1a1a;">{r.get('reason', '')}</td>
        </tr>"""

    html = f"""
    <div style="font-family:Arial,Helvetica,sans-serif;background:#ffffff;color:#1a1a1a;padding:24px;border:1px solid #e1e4e8;border-radius:8px;max-width:760px;">
        <h2 style="color:#0969da;margin:0 0 8px 0;">Crypto Y'all Trade Execution</h2>
        <p style="color:#57606a;margin:0 0 8px 0;">{dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p>
        <p style="color:#1a1a1a;margin:0 0 16px 0;"><strong>Status:</strong> {status_summary}</p>
        {f'<table style="width:100%;border-collapse:collapse;margin-top:16px;background:#ffffff;"><tr style="background:#f6f8fa;color:#57606a;text-transform:uppercase;font-size:0.75em;letter-spacing:0.5px;"><th style="padding:10px;text-align:left;">Asset</th><th style="padding:10px;text-align:left;">Action</th><th style="padding:10px;text-align:left;">Status</th><th style="padding:10px;text-align:left;">Size</th><th style="padding:10px;text-align:left;">Fill Price</th><th style="padding:10px;text-align:left;">Reason</th></tr>{rows}</table>' if results else '<p style="color:#1a1a1a;">No trades executed this cycle.</p>'}
    </div>
    """

    msg = MIMEMultipart("alternative")
    summary = f"{len(results)} trade(s)" if results else "No trades"
    msg["Subject"] = f"[Crypto Y'all] Execution: {summary}"
    msg["From"] = user
    msg["To"] = ", ".join(recipient_list)
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(user, password)
        server.send_message(msg)
    print(f"Email sent to {recipient_list}")


def _send_telegram(results: list[dict], status_summary: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_ids_raw = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_ids_raw:
        return

    chat_ids = [c.strip() for c in chat_ids_raw.split(",") if c.strip()]

    lines = ["*Crypto Y'all Trade Execution*", "", f"Status: {status_summary}", ""]
    for r in results:
        status = r.get("status", "?").upper()
        lines.append(f"*{r['ticker']}* — {r['action']} [{status}]")
        if r.get("status") == "filled":
            lines.append(f"  Size: {r.get('fill_size', 0):.6g} @ ${r.get('fill_price', 0):,.2f}")
        elif r.get("error"):
            lines.append(f"  Error: {r['error']}")
        lines.append(f"  Reason: {r.get('reason', '')}")
        lines.append("")

    lines.append(f"_{dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}_")
    text = "\n".join(lines)

    for chat_id in chat_ids:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=15,
        )


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    print(f"Trade executor started at {dt.datetime.utcnow().isoformat()}Z")

    # Kill switch check
    if check_kill_switch():
        print("KILL_SWITCH is OFF — halting all trading")
        send_execution_notifications([], "KILL SWITCH ACTIVE — no trades executed")
        sys.exit(0)

    try:
        info, exchange, address = get_client()
    except Exception as e:
        print(f"Failed to init Hyperliquid client: {e}")
        send_execution_notifications([], f"CLIENT INIT FAILED: {e}")
        sys.exit(1)

    # Load state and check drawdown
    state = load_trading_state()
    equity = get_account_equity(info, address)
    dd_threshold = float(os.environ.get("DAILY_DD_PCT", "5"))
    halted, state_update = check_daily_drawdown(state, equity, dd_threshold)
    state.update(state_update)

    if halted:
        msg = f"Daily drawdown triggered — halting today. {state_update.get('halt_reason')}"
        print(msg)
        send_execution_notifications([], msg)
        save_trading_state(state)
        sys.exit(0)

    # Check if already halted today
    today = dt.date.today().isoformat()
    if state.get("halted_today") == today:
        print(f"Already halted today: {state.get('halt_reason')}")
        sys.exit(0)

    # Compute signals and decide trades
    signals = compute_all_signals()
    open_positions = get_open_positions(info, address)
    capital = float(os.environ.get("SEGREGATED_CAPITAL", "10000"))
    max_positions = int(os.environ.get("MAX_POSITIONS", "4"))

    # Filter out assets not listed on this Hyperliquid environment
    mids = info.all_mids()
    available = set(mids.keys())
    signals = {t: s for t, s in signals.items() if HL_TICKER_MAP[t] in available}
    skipped = [t for t in ASSETS if t not in signals]
    if skipped:
        print(f"Skipping unavailable assets on this env: {skipped}")

    # Ownership tracking: only manage positions this bot opened.
    # owned_coins is the set of coin symbols this bot currently holds.
    owned_coins = set(state.get("owned_coins", []))

    # Reconcile: drop owned coins that no longer have a position on the exchange
    # (e.g., another strategy or manual action closed them). This keeps state
    # consistent with the actual Hyperliquid account.
    stale_owned = owned_coins - set(open_positions.keys())
    if stale_owned:
        print(f"Dropping stale owned coins (no position on exchange): {stale_owned}")
        owned_coins -= stale_owned

    managed_positions = {c: p for c, p in open_positions.items() if c in owned_coins}

    # Profit protection: break-even / trailing / hard stop (profit_protection.py)
    peaks = profit_protection.update_peaks(
        state.get("peaks", {}), managed_positions, signals, mids, HL_TICKER_MAP)
    blocked = profit_protection.update_blocks(
        state.get("protect_block", {}), signals, HL_TICKER_MAP)
    cooldowns = profit_protection.active_cooldowns(state.get("cooldowns", {}))
    if cooldowns:
        print(f"Re-entry cooldown active: {sorted(cooldowns)}")
    extra_exits = profit_protection.find_exits(
        managed_positions, signals, peaks, mids, HL_TICKER_MAP)
    for coin, why in extra_exits.items():
        print(f"Profit protection: closing {coin} — {why}")

    trades = decide_trades(signals, managed_positions, max_positions,
                            all_open_positions=open_positions,
                            extra_exits=extra_exits, blocked=blocked,
                            cooldown=cooldowns)
    trades = apply_exposure_cap(trades, open_positions, equity, info)
    print(f"Decided on {len(trades)} trade(s) (own {len(owned_coins)} position(s))")

    results = []
    for trade in trades:
        sig_info = signals.get(trade["ticker"], {})
        leverage = max(1.0, min(sig_info.get("leverage", 1.0), 3.0))
        result = execute_trade(info, exchange, trade, capital, leverage)
        results.append(result)
        print(f"  {result['ticker']} {result['action']}: {result.get('status')} "
              f"{result.get('fill_size', '')} @ {result.get('fill_price', '')}")

        # Update ownership on successful fills
        if result.get("status") == "filled":
            coin = result["hl_coin"]
            if result["action"] == "close":
                owned_coins.discard(coin)
                peaks.pop(coin, None)
                profit_protection.register_stopout(
                    cooldowns, coin, managed_positions.get(coin), mids,
                    bool(trade.get("protect")))
                if trade.get("protect"):
                    blocked[coin] = 1 if trade.get("side") == "long" else -1
            else:
                owned_coins.add(coin)

    # Append to trade history
    history = state.get("history", [])
    for r in results:
        history.append({
            "timestamp": dt.datetime.utcnow().isoformat() + "Z",
            **{k: v for k, v in r.items() if k not in ("raw",)},
        })
    state["history"] = history[-500:]  # keep last 500 trades
    state["last_equity"] = equity
    state["last_run"] = dt.datetime.utcnow().isoformat() + "Z"
    state["owned_coins"] = sorted(owned_coins)
    state["peaks"] = {c: v for c, v in peaks.items() if c in owned_coins}
    state["protect_block"] = blocked
    state["cooldowns"] = profit_protection.active_cooldowns(cooldowns)
    # Show only our positions on the dashboard
    latest_positions = get_open_positions(info, address)
    state["open_positions"] = {c: p for c, p in latest_positions.items() if c in owned_coins}

    save_trading_state(state)

    summary = f"{len(results)} trade(s) executed | Equity: ${equity:,.2f}"
    send_execution_notifications(results, summary)
    print("Done")


if __name__ == "__main__":
    main()
