"""
╔═══════════════════════════════════════════════════════════════════╗
║                       HYPE_BOT v3.0                              ║
║       كاشف الهايب — Wintermute-Style Multi-Source Scanner       ║
║                                                                   ║
║  5 مصادر بأوزان احترافية ديناميكية (chain-aware):               ║
║    💧 DexScreener    35%  on-chain DEX volume                   ║
║    🦙 DefiLlama      20%  TVL change (institutional)            ║
║    🔍 Etherscan V2   20%  on-chain whale activity (إذا EVM)     ║
║    🐋 Binance Fut.   15%  OI + futures action                   ║
║    📊 CoinPaprika    10%  retail trending confirmation          ║
║                                                                   ║
║  100% on-chain heavy: 75% من الوزن on-chain                     ║
║  للأغراض التعليمية فقط — ليس نصيحة مالية                        ║
╚═══════════════════════════════════════════════════════════════════╝
"""

import os
import time
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Tuple

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes
)


# ══════════════════════════════════════════════════════════════════
# 1. CONFIG & CONSTANTS
# ══════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("HYPE_BOT")

BOT_TOKEN      = os.environ.get("BOT_TOKEN", "").strip()
ETHERSCAN_KEY  = os.environ.get("ETHERSCAN_KEY", "").strip()
# v4.0 additions:
POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY", "").strip()  # Massive.com
GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "").strip()
CLAUDE_API_KEY  = os.environ.get("CLAUDE_API_KEY", "").strip()   # v5.0
OPENAI_API_KEY  = os.environ.get("OPENAI_API_KEY", "").strip()   # v5.0
DCA_DATA_DIR    = os.environ.get("DCA_DATA_DIR", "/data").strip()

DS_BASE         = "https://api.dexscreener.com"
LLAMA_BASE      = "https://api.llama.fi"
BIN_FAPI        = "https://fapi.binance.com/fapi/v1"
CP_BASE         = "https://api.coinpaprika.com/v1"
ETHERSCAN_BASE  = "https://api.etherscan.io/v2/api"
# v4.0 — Massive.com (Polygon.io rebrand) cross-exchange data
MASSIVE_BASE    = "https://api.polygon.io"
# v4.0 — Gemini AI
GEMINI_BASE     = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_MODEL    = "gemini-2.5-flash"
# v5.0 — Specialized AI Council
CLAUDE_BASE     = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL    = "claude-opus-4-5"
CLAUDE_FALLBACK = "claude-sonnet-4-5"
OPENAI_BASE     = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL    = "gpt-4o"
OPENAI_FALLBACK = "gpt-4o-mini"

CHAIN_ID_MAP = {
    "ethereum":  1,    "eth":       1,    "mainnet":   1,
    "bsc":       56,   "binance":   56,   "bnb":       56,
    "polygon":   137,  "matic":     137,
    "arbitrum":  42161, "arb":      42161, "arbitrum-one": 42161,
    "optimism":  10,   "op":        10,
    "base":      8453,
    "avalanche": 43114, "avax":     43114,
    "fantom":    250,  "ftm":       250,
    "linea":     59144,
    "blast":     81457,
}

def is_evm_chain(chain: str) -> bool:
    if not chain:
        return False
    return chain.lower().strip() in CHAIN_ID_MAP

def get_chain_id(chain: str) -> int:
    return CHAIN_ID_MAP.get((chain or "").lower().strip(), 0)


# v3.0 — 5 sources (legacy weights)
W_5SRC = {
    "dexscreener": 0.35,
    "defillama":   0.20,
    "etherscan":   0.20,
    "binance":     0.15,
    "coinpaprika": 0.10,
}

W_4SRC = {
    "dexscreener": 0.45,
    "defillama":   0.25,
    "etherscan":   0.00,
    "binance":     0.18,
    "coinpaprika": 0.12,
}

# v4.0 — 6 sources with Massive (cross-exchange aggregated)
# Reduced other weights proportionally to add Massive
W_6SRC_EVM = {
    "dexscreener": 0.30,  # was 35
    "defillama":   0.18,  # was 20
    "etherscan":   0.18,  # was 20
    "binance":     0.12,  # was 15
    "coinpaprika": 0.07,  # was 10
    "massive":     0.15,  # NEW! cross-exchange
}

W_6SRC_NONEVM = {
    "dexscreener": 0.40,  # was 45
    "defillama":   0.22,  # was 25
    "etherscan":   0.00,
    "binance":     0.15,  # was 18
    "coinpaprika": 0.08,  # was 12
    "massive":     0.15,  # NEW!
}


def get_weights_for_chain(chain: str) -> Dict[str, float]:
    """
    Determines weight distribution based on:
    - EVM vs non-EVM chain
    - Whether Etherscan key exists
    - Whether Massive (Polygon) key exists
    """
    has_es = bool(ETHERSCAN_KEY)
    has_massive = bool(POLYGON_API_KEY)

    if has_massive:
        if has_es and is_evm_chain(chain):
            return W_6SRC_EVM
        return W_6SRC_NONEVM

    # Fallback to v3.0 weights (no Massive)
    if not ETHERSCAN_KEY:
        return W_4SRC
    if is_evm_chain(chain):
        return W_5SRC
    return W_4SRC


MODES = {
    "عادي":    {"min": 65, "min_sources": 2, "label": "🟢 عادي",   "min_per_source": 0},
    "متوازن":  {"min": 75, "min_sources": 3, "label": "⚖️ متوازن", "min_per_source": 50},
    "جودة":    {"min": 85, "min_sources": 3, "label": "💎 جودة",   "min_per_source": 60},
    "ذهبي":    {"min": 92, "min_sources": 4, "label": "👑 ذهبي",   "min_per_source": 70},
}

SCAN_INTERVAL_SEC = 300
COOLDOWN_HOURS    = 1
MAX_RESULTS_KEPT  = 50
MIN_LIQUIDITY_USD = 100_000
MIN_BINANCE_VOL   = 500_000

ES_TX_OFFSET     = 1000
ES_WHALE_USD     = 10_000
ES_REQUEST_DELAY = 0.25
ES_MAX_TOKENS    = 15

BLACKLIST = {
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDD", "USDP",
    "WBTC", "WETH", "STETH", "WSTETH", "WBNB", "WMATIC", "USDE",
    "GUSD", "PYUSD", "FRAX", "SUSDS", "SUSDE", "USDS", "RLUSD",
    "USD0", "USDX", "EURS", "EURT",
}

TZ_RIYADH = timezone(timedelta(hours=3))


# ══════════════════════════════════════════════════════════════════
# 2. STATE
# ══════════════════════════════════════════════════════════════════

chat_config: Dict[int, Dict[str, Any]] = {}
seen_coins: Dict[str, str] = {}
last_results: List[Dict[str, Any]] = []

source_status: Dict[str, Dict[str, Any]] = {
    "dexscreener": {"ok": False, "last_check": None, "error": None, "count": 0},
    "defillama":   {"ok": False, "last_check": None, "error": None, "count": 0},
    "etherscan":   {"ok": False, "last_check": None, "error": None, "count": 0},
    "binance":     {"ok": False, "last_check": None, "error": None, "count": 0},
    "coinpaprika": {"ok": False, "last_check": None, "error": None, "count": 0},
    "massive":     {"ok": False, "last_check": None, "error": None, "count": 0},
}

alert_history: List[Dict[str, Any]] = []


# ══════════════════════════════════════════════════════════════════
# 3. HTTP HELPER
# ══════════════════════════════════════════════════════════════════

_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; HypeBot/3.0)",
    "Accept": "application/json",
})


def safe_get(url: str, params: Optional[dict] = None,
             headers: Optional[dict] = None,
             timeout: tuple = (5, 20),
             retries: int = 2) -> Optional[Any]:
    last_err = None
    for attempt in range(retries + 1):
        try:
            h = dict(_session.headers)
            if headers:
                h.update(headers)
            r = _session.get(url, params=params, headers=h, timeout=timeout)
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    return r.text
            elif r.status_code == 429:
                last_err = "429 rate limit"
                time.sleep(2 ** attempt)
                continue
            elif r.status_code in (401, 402, 403):
                return {"_auth_error": r.status_code,
                        "_text": r.text[:200] if r.text else "no body"}
            else:
                last_err = f"HTTP {r.status_code}"
        except requests.exceptions.Timeout:
            last_err = "timeout"
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:100]}"
        if attempt < retries:
            time.sleep(1)
    log.warning(f"[HTTP] {url[:60]} → {last_err}")
    return None


def now_iso() -> str:
    return datetime.now(TZ_RIYADH).isoformat()


def normalize_sym(s: str) -> str:
    s = (s or "").upper().strip()
    for suffix in ("USDT", "BUSD", "USDC", "USD"):
        if s.endswith(suffix) and len(s) > len(suffix):
            return s[:-len(suffix)]
    return s


# ══════════════════════════════════════════════════════════════════
# 4. SOURCE FETCHERS (5 sources)
# ══════════════════════════════════════════════════════════════════

# ── ① DexScreener (must run FIRST — provides token addresses for Etherscan) ──
def fetch_dexscreener_data() -> Dict[str, Dict]:
    """
    Returns: {symbol_upper: {volume metrics, liquidity, base_token_address, chain, ...}}
    """
    boosts = safe_get(f"{DS_BASE}/token-boosts/top/v1")
    if not boosts or "_auth_error" in (boosts or {}):
        source_status["dexscreener"] = {
            "ok": False, "last_check": now_iso(),
            "error": "boosts unreachable", "count": 0,
        }
        return {}

    addresses = []
    if isinstance(boosts, list):
        for b in boosts[:30]:
            addr = b.get("tokenAddress")
            chain = b.get("chainId")
            if addr and chain:
                addresses.append((chain, addr, b.get("totalAmount", 0)))

    out = {}
    for chain, addr, boost_amount in addresses[:25]:
        pair_data = safe_get(f"{DS_BASE}/latest/dex/tokens/{addr}", retries=1)
        if not pair_data or "pairs" not in pair_data:
            continue
        pairs = pair_data.get("pairs") or []
        if not pairs:
            continue

        best = max(pairs, key=lambda p: float(
            (p.get("liquidity") or {}).get("usd") or 0
        ))

        base_token = best.get("baseToken", {}) or {}
        sym = (base_token.get("symbol") or "").upper()
        base_addr = (base_token.get("address") or "").lower()
        if not sym or sym in BLACKLIST or not base_addr:
            continue

        liquidity = float((best.get("liquidity") or {}).get("usd") or 0)
        if liquidity < MIN_LIQUIDITY_USD:
            continue

        vol = best.get("volume", {}) or {}
        v_h1  = float(vol.get("h1") or 0)
        v_h6  = float(vol.get("h6") or 0)
        v_h24 = float(vol.get("h24") or 0)

        avg_h1_from_h6 = (v_h6 / 6.0) if v_h6 > 0 else 0
        vol_change_pct = ((v_h1 - avg_h1_from_h6) / avg_h1_from_h6 * 100) \
            if avg_h1_from_h6 > 0 else 0

        pc = best.get("priceChange", {}) or {}
        price_change_h1  = float(pc.get("h1") or 0)
        price_change_h24 = float(pc.get("h24") or 0)

        created_at_ms = best.get("pairCreatedAt") or 0
        age_days = 0
        if created_at_ms:
            age_days = (time.time() * 1000 - created_at_ms) / (1000 * 86400)

        out[sym] = {
            "volume_h1":         v_h1,
            "volume_h6":         v_h6,
            "volume_h24":        v_h24,
            "vol_change_pct":    vol_change_pct,
            "liquidity_usd":     liquidity,
            "price_usd":         float(best.get("priceUsd") or 0),
            "price_change_h1":   price_change_h1,
            "price_change_h24":  price_change_h24,
            "boost_amount":      boost_amount,
            "chain":             (chain or "").lower(),
            "pair_url":          best.get("url", ""),
            "age_days":          age_days,
            "pair_address":      best.get("pairAddress", ""),
            "base_token_address": base_addr,    # ⭐ NEW for Etherscan
            "is_evm":            is_evm_chain(chain),
        }

    source_status["dexscreener"] = {
        "ok": True, "last_check": now_iso(), "error": None, "count": len(out),
    }
    log.info(f"[DS] {len(out)} tokens fetched")
    return out


# ── ② DefiLlama: TVL changes ──
def fetch_defillama_data() -> Dict[str, Dict]:
    data = safe_get(f"{LLAMA_BASE}/protocols")
    if not data or "_auth_error" in (data or {}):
        source_status["defillama"] = {
            "ok": False, "last_check": now_iso(),
            "error": "unreachable", "count": 0,
        }
        return {}

    if not isinstance(data, list):
        source_status["defillama"] = {
            "ok": False, "last_check": now_iso(),
            "error": "unexpected response", "count": 0,
        }
        return {}

    by_sym: Dict[str, Dict] = {}
    for p in data:
        sym = (p.get("symbol") or "").upper()
        if not sym or sym == "-" or sym in BLACKLIST:
            continue
        tvl = float(p.get("tvl") or 0)
        if tvl < 100_000:
            continue

        existing = by_sym.get(sym)
        if existing and existing["tvl"] >= tvl:
            continue

        by_sym[sym] = {
            "name":        p.get("name", ""),
            "tvl":         tvl,
            "change_1h":   float(p.get("change_1h") or 0),
            "change_1d":   float(p.get("change_1d") or 0),
            "change_7d":   float(p.get("change_7d") or 0),
            "category":    p.get("category", ""),
            "chains":      p.get("chains") or [],
            "url":         p.get("url", ""),
            "twitter":     p.get("twitter", ""),
            "mcap":        float(p.get("mcap") or 0),
        }

    source_status["defillama"] = {
        "ok": True, "last_check": now_iso(), "error": None, "count": len(by_sym),
    }
    log.info(f"[LLAMA] {len(by_sym)} protocols fetched")
    return by_sym


# ── ③ Etherscan V2: on-chain whale activity ──
def _es_compute_metrics(transfers: List[dict], price_usd: float) -> Dict[str, Any]:
    """Compute hype metrics from token transfer list."""
    if not transfers:
        return {
            "tx_count_1h": 0, "tx_count_24h": 0,
            "velocity_ratio": 0, "unique_addrs_24h": 0,
            "whale_tx_count_1h": 0, "whale_volume_usd_24h": 0,
        }

    now_ts = time.time()
    txs_1h_count = 0
    txs_24h_count = 0
    unique_addrs = set()
    whale_tx_1h = 0
    whale_volume_24h = 0.0

    for tx in transfers:
        try:
            ts = int(tx.get("timeStamp", 0))
            age_sec = now_ts - ts
            if age_sec > 86400:
                continue

            value_raw = float(tx.get("value", 0))
            decimals = int(tx.get("tokenDecimal", 18))
            if decimals < 0 or decimals > 36:
                continue
            value_tokens = value_raw / (10 ** decimals)
            value_usd = value_tokens * price_usd if price_usd > 0 else 0

            from_addr = (tx.get("from") or "").lower()
            to_addr = (tx.get("to") or "").lower()
            if from_addr:
                unique_addrs.add(from_addr)
            if to_addr:
                unique_addrs.add(to_addr)

            txs_24h_count += 1
            if value_usd >= ES_WHALE_USD:
                whale_volume_24h += value_usd
            if age_sec < 3600:
                txs_1h_count += 1
                if value_usd >= ES_WHALE_USD:
                    whale_tx_1h += 1
        except (TypeError, ValueError):
            continue

    avg_per_hour = txs_24h_count / 24.0 if txs_24h_count else 0
    velocity_ratio = (txs_1h_count / avg_per_hour) if avg_per_hour > 0 else 0

    return {
        "tx_count_1h":         txs_1h_count,
        "tx_count_24h":        txs_24h_count,
        "velocity_ratio":      round(velocity_ratio, 2),
        "unique_addrs_24h":    len(unique_addrs),
        "whale_tx_count_1h":   whale_tx_1h,
        "whale_volume_usd_24h": round(whale_volume_24h, 2),
    }


def fetch_etherscan_data(ds_data: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    Use Etherscan V2 to fetch on-chain metrics for EVM tokens from DS data.
    Sequential dependency: DS must run first.
    """
    if not ETHERSCAN_KEY:
        source_status["etherscan"] = {
            "ok": False, "last_check": now_iso(),
            "error": "no API key", "count": 0,
        }
        return {}

    # Filter for EVM tokens only
    evm_tokens = []
    for sym, info in ds_data.items():
        if info.get("is_evm") and info.get("base_token_address"):
            evm_tokens.append((
                sym,
                info["chain"],
                info["base_token_address"],
                info.get("price_usd", 0),
            ))

    if not evm_tokens:
        source_status["etherscan"] = {
            "ok": True, "last_check": now_iso(),
            "error": "no EVM tokens in DS results", "count": 0,
        }
        return {}

    # Limit to ES_MAX_TOKENS to avoid hitting rate limits
    evm_tokens = evm_tokens[:ES_MAX_TOKENS]

    out = {}
    auth_error_seen = False
    for sym, chain, contract, price in evm_tokens:
        chainid = get_chain_id(chain)
        if not chainid:
            continue

        params = {
            "chainid": chainid,
            "module": "account",
            "action": "tokentx",
            "contractaddress": contract,
            "page": 1,
            "offset": ES_TX_OFFSET,
            "sort": "desc",
            "apikey": ETHERSCAN_KEY,
        }

        data = safe_get(ETHERSCAN_BASE, params=params, timeout=(5, 25), retries=1)

        if not data:
            log.warning(f"[ES] {sym} ({chain}) → no response")
            time.sleep(ES_REQUEST_DELAY)
            continue

        if isinstance(data, dict) and "_auth_error" in data:
            auth_error_seen = True
            log.warning(f"[ES] auth error: {data.get('_auth_error')}")
            break

        if not isinstance(data, dict):
            time.sleep(ES_REQUEST_DELAY)
            continue

        if data.get("status") == "0":
            # "No transactions found" or other non-error empty result
            msg = (data.get("message") or "").lower()
            if "no transactions" in msg or "no records" in msg:
                pass  # not an error, just empty
            time.sleep(ES_REQUEST_DELAY)
            continue

        transfers = data.get("result") or []
        if not isinstance(transfers, list):
            time.sleep(ES_REQUEST_DELAY)
            continue

        metrics = _es_compute_metrics(transfers, price)
        if metrics["tx_count_24h"] > 0:
            out[sym] = {
                "chain":   chain,
                "chainid": chainid,
                "contract": contract,
                **metrics,
            }

        time.sleep(ES_REQUEST_DELAY)  # rate-limit-friendly

    if auth_error_seen and not out:
        source_status["etherscan"] = {
            "ok": False, "last_check": now_iso(),
            "error": "auth error (check ETHERSCAN_KEY)", "count": 0,
        }
    else:
        source_status["etherscan"] = {
            "ok": True, "last_check": now_iso(),
            "error": None, "count": len(out),
        }

    log.info(f"[ES] {len(out)}/{len(evm_tokens)} EVM tokens analyzed")
    return out


# ── ④ Binance Futures ──
def fetch_binance_data() -> Dict[str, Dict]:
    data = safe_get(f"{BIN_FAPI}/ticker/24hr", timeout=(5, 25))
    if not data or "_auth_error" in (data or {}):
        source_status["binance"] = {
            "ok": False, "last_check": now_iso(),
            "error": "unreachable (region?)", "count": 0,
        }
        return {}

    if not isinstance(data, list):
        source_status["binance"] = {
            "ok": False, "last_check": now_iso(),
            "error": "unexpected response", "count": 0,
        }
        return {}

    usdt_pairs = []
    for t in data:
        sym_full = t.get("symbol", "")
        if not sym_full.endswith("USDT"):
            continue
        try:
            qv = float(t.get("quoteVolume") or 0)
            pc = float(t.get("priceChangePercent") or 0)
            lp = float(t.get("lastPrice") or 0)
        except (TypeError, ValueError):
            continue
        if qv < MIN_BINANCE_VOL:
            continue
        usdt_pairs.append({
            "symbol_full": sym_full,
            "symbol":      normalize_sym(sym_full),
            "quote_vol":   qv,
            "price_chg":   pc,
            "last_price":  lp,
            "high":        float(t.get("highPrice") or 0),
            "low":         float(t.get("lowPrice") or 0),
            "trades":      int(t.get("count") or 0),
        })

    usdt_pairs.sort(key=lambda x: x["quote_vol"], reverse=True)
    total = len(usdt_pairs)

    out = {}
    for rank, p in enumerate(usdt_pairs, 1):
        sym = p["symbol"]
        if not sym or sym in BLACKLIST:
            continue
        out[sym] = {
            "symbol_full":      p["symbol_full"],
            "price_change_pct": p["price_chg"],
            "quote_volume":     p["quote_vol"],
            "last_price":       p["last_price"],
            "high":             p["high"],
            "low":              p["low"],
            "trades":           p["trades"],
            "volume_rank":      rank,
            "total_pairs":      total,
        }

    source_status["binance"] = {
        "ok": True, "last_check": now_iso(), "error": None, "count": len(out),
    }
    log.info(f"[BIN] {len(out)} USDT-perp pairs fetched")
    return out


# ── ⑤ CoinPaprika ──
def fetch_coinpaprika_data() -> Dict[str, Dict]:
    data = safe_get(f"{CP_BASE}/tickers", params={"limit": 2000},
                    timeout=(5, 25))
    if not data or "_auth_error" in (data or {}):
        source_status["coinpaprika"] = {
            "ok": False, "last_check": now_iso(),
            "error": "unreachable", "count": 0,
        }
        return {}

    if not isinstance(data, list):
        source_status["coinpaprika"] = {
            "ok": False, "last_check": now_iso(),
            "error": "unexpected response", "count": 0,
        }
        return {}

    coins = []
    for c in data:
        sym = (c.get("symbol") or "").upper()
        if not sym or sym in BLACKLIST:
            continue
        usd = (c.get("quotes") or {}).get("USD") or {}
        try:
            pct_24h = float(usd.get("percent_change_24h") or 0)
            price   = float(usd.get("price") or 0)
            mc      = float(usd.get("market_cap") or 0)
            vol_24h = float(usd.get("volume_24h") or 0)
        except (TypeError, ValueError):
            continue
        if mc < 1_000_000:
            continue
        coins.append({
            "id":       c.get("id", ""),
            "name":     c.get("name", ""),
            "symbol":   sym,
            "rank":     int(c.get("rank") or 9999),
            "price":    price,
            "pct_24h":  pct_24h,
            "mcap":     mc,
            "volume":   vol_24h,
        })

    sorted_by_gain = sorted(coins, key=lambda x: x["pct_24h"], reverse=True)
    gainer_rank_map = {c["symbol"]: idx + 1 for idx, c in enumerate(sorted_by_gain)}

    out = {}
    for c in coins:
        out[c["symbol"]] = {
            "id":          c["id"],
            "name":        c["name"],
            "price":       c["price"],
            "percent_24h": c["pct_24h"],
            "mcap":        c["mcap"],
            "volume_24h":  c["volume"],
            "mc_rank":     c["rank"],
            "gainer_rank": gainer_rank_map.get(c["symbol"], 9999),
        }

    source_status["coinpaprika"] = {
        "ok": True, "last_check": now_iso(), "error": None, "count": len(out),
    }
    log.info(f"[CP] {len(out)} coins fetched")
    return out


# ══════════════════════════════════════════════════════════════════
# 4.6 MASSIVE.COM (POLYGON.IO) — Cross-Exchange Aggregated Data (v4.0)
# ══════════════════════════════════════════════════════════════════
# Massive.com rebranded from Polygon.io in Oct 2025.
# API endpoints still live at api.polygon.io.
# Plan: Currencies Starter ($49/mo) — All Crypto + Trades + Unlimited.

# Massive uses USD as quote currency, format: X:{from}{to}
_MASSIVE_SYMBOLS = {
    "BTC":   "X:BTCUSD",   "ETH":  "X:ETHUSD",   "SOL":  "X:SOLUSD",
    "BNB":   "X:BNBUSD",   "XRP":  "X:XRPUSD",   "ADA":  "X:ADAUSD",
    "DOGE":  "X:DOGEUSD",  "AVAX": "X:AVAXUSD",  "DOT":  "X:DOTUSD",
    "MATIC": "X:MATICUSD", "LINK": "X:LINKUSD",  "UNI":  "X:UNIUSD",
    "AAVE":  "X:AAVEUSD",  "ATOM": "X:ATOMUSD",  "NEAR": "X:NEARUSD",
    "HBAR":  "X:HBARUSD",  "ARB":  "X:ARBUSD",   "OP":   "X:OPUSD",
    "PEPE":  "X:PEPEUSD",  "SHIB": "X:SHIBUSD",  "WIF":  "X:WIFUSD",
    "BONK":  "X:BONKUSD",  "ONDO": "X:ONDOUSD",  "PYTH": "X:PYTHUSD",
    "RENDER":"X:RENDERUSD","TAO":  "X:TAOUSD",   "FET":  "X:FETUSD",
    "HYPE":  "X:HYPEUSD",  "SUI":  "X:SUIUSD",   "APT":  "X:APTUSD",
    "INJ":   "X:INJUSD",   "SEI":  "X:SEIUSD",   "TIA":  "X:TIAUSD",
    "JUP":   "X:JUPUSD",   "ENS":  "X:ENSUSD",   "MKR":  "X:MKRUSD",
    "LDO":   "X:LDOUSD",   "GRT":  "X:GRTUSD",   "FIL":  "X:FILUSD",
    "LTC":   "X:LTCUSD",   "BCH":  "X:BCHUSD",   "TRX":  "X:TRXUSD",
}


def _massive_request(path: str, params: Optional[Dict] = None,
                     timeout=(5, 12)) -> Optional[Dict]:
    """Generic Massive API request with auth. Returns parsed JSON or None."""
    if not POLYGON_API_KEY:
        return None
    p = dict(params or {})
    p["apiKey"] = POLYGON_API_KEY
    try:
        r = requests.get(MASSIVE_BASE + path, params=p, timeout=timeout)
        if r.status_code != 200:
            log.debug(f"[MASSIVE] {path} HTTP {r.status_code}")
            return None
        return r.json()
    except Exception as e:
        log.debug(f"[MASSIVE] {path} failed: {e}")
        return None


def fetch_massive_data() -> Dict[str, Dict]:
    """
    Fetch top movers + snapshots from Massive (cross-exchange aggregated).
    Returns: {symbol: {price, change_24h, volume_24h, momentum_score}}
    """
    if not POLYGON_API_KEY:
        source_status["massive"]["ok"] = False
        source_status["massive"]["error"] = "no key"
        return {}

    out = {}

    # Strategy 1: Get snapshot of all crypto tickers (single API call)
    snapshot = _massive_request(
        "/v2/snapshot/locale/global/markets/crypto/tickers"
    )

    if not snapshot or "tickers" not in snapshot:
        log.info("[MASSIVE] snapshot failed, trying individual symbols")
        out = _fetch_massive_individual()
    else:
        tickers = snapshot.get("tickers", [])
        log.info(f"[MASSIVE] snapshot: {len(tickers)} crypto tickers")

        rev_map = {v: k for k, v in _MASSIVE_SYMBOLS.items()}

        for t in tickers:
            ticker = t.get("ticker", "")
            if ticker not in rev_map:
                continue

            our_sym = rev_map[ticker]
            day = t.get("day", {}) or {}
            prev_day = t.get("prevDay", {}) or {}
            last_trade = t.get("lastTrade", {}) or {}

            price = float(last_trade.get("p") or day.get("c") or 0)
            prev_close = float(prev_day.get("c") or 0)

            if price <= 0:
                continue

            if prev_close > 0:
                change_24h = ((price - prev_close) / prev_close) * 100
            else:
                change_24h = float(t.get("todaysChangePerc", 0))

            volume_24h = float(day.get("v", 0)) * price
            high_24h = float(day.get("h", 0))
            low_24h = float(day.get("l", 0))

            # Massive momentum score (0-100)
            momentum = 50.0
            if change_24h >= 10:
                momentum += 25
            elif change_24h >= 5:
                momentum += 15
            elif change_24h >= 2:
                momentum += 8
            elif change_24h <= -10:
                momentum -= 25
            elif change_24h <= -5:
                momentum -= 15

            prev_volume = float(prev_day.get("v", 0)) * prev_close
            if prev_volume > 0:
                vol_ratio = volume_24h / prev_volume
                if vol_ratio >= 3:
                    momentum += 15
                elif vol_ratio >= 2:
                    momentum += 10
                elif vol_ratio >= 1.5:
                    momentum += 5

            momentum = max(0, min(100, momentum))

            out[our_sym] = {
                "price":         price,
                "change_24h":    change_24h,
                "volume_24h":    volume_24h,
                "high_24h":      high_24h,
                "low_24h":       low_24h,
                "momentum_score": momentum,
                "source":        "massive",
            }

    # Update source status
    source_status["massive"]["ok"] = len(out) > 0
    source_status["massive"]["last_check"] = now_iso()
    source_status["massive"]["count"] = len(out)
    source_status["massive"]["error"] = None if out else "no data returned"

    log.info(f"[MASSIVE] mapped {len(out)} symbols")
    return out


def _fetch_massive_individual() -> Dict[str, Dict]:
    """Fallback: fetch each symbol individually (slower)."""
    out = {}
    # Limit to top tracked symbols to avoid rate limit
    priority_symbols = ["BTC", "ETH", "SOL", "HYPE", "ONDO", "RENDER", "AAVE",
                        "LINK", "PYTH", "SUI", "TAO", "AVAX", "NEAR", "DOT"]
    for sym in priority_symbols:
        massive_sym = _MASSIVE_SYMBOLS.get(sym)
        if not massive_sym:
            continue
        data = _massive_request(
            f"/v2/snapshot/locale/global/markets/crypto/tickers/{massive_sym}"
        )
        if not data or "ticker" not in data:
            continue
        t = data["ticker"]
        day = t.get("day", {}) or {}
        prev_day = t.get("prevDay", {}) or {}
        last_trade = t.get("lastTrade", {}) or {}

        price = float(last_trade.get("p") or day.get("c") or 0)
        if price <= 0:
            continue

        change_24h = float(t.get("todaysChangePerc", 0))
        out[sym] = {
            "price":         price,
            "change_24h":    change_24h,
            "volume_24h":    float(day.get("v", 0)) * price,
            "high_24h":      float(day.get("h", 0)),
            "low_24h":       float(day.get("l", 0)),
            "momentum_score": 50 + min(25, change_24h * 2),
            "source":        "massive",
        }
        time.sleep(0.1)
    return out


def massive_get_top_movers(limit: int = 10) -> List[Dict]:
    """Get top gainers from Massive (24h % change)."""
    if not POLYGON_API_KEY:
        return []
    data = _massive_request(
        "/v2/snapshot/locale/global/markets/crypto/gainers",
        {"include_otc": "false"}
    )
    if not data or "tickers" not in data:
        return []

    rev_map = {v: k for k, v in _MASSIVE_SYMBOLS.items()}
    movers = []
    for t in data["tickers"][:limit]:
        ticker = t.get("ticker", "")
        sym = rev_map.get(ticker, ticker.replace("X:", "").replace("USD", ""))
        movers.append({
            "symbol":     sym,
            "ticker":     ticker,
            "change_pct": float(t.get("todaysChangePerc", 0)),
            "price":      float(t.get("lastTrade", {}).get("p", 0)),
        })
    return movers


# ══════════════════════════════════════════════════════════════════
# 5. SOURCE SCORERS (each → 0..100)
# ══════════════════════════════════════════════════════════════════

def score_dexscreener(sym: str, ds_data: Dict[str, Dict]) -> float:
    info = ds_data.get(sym)
    if not info:
        return 0.0

    vol_change = info.get("vol_change_pct", 0)
    liquidity  = info.get("liquidity_usd", 0)
    price_h1   = info.get("price_change_h1", 0)
    price_h24  = info.get("price_change_h24", 0)
    boost      = info.get("boost_amount", 0)
    age_days   = info.get("age_days", 0)

    if vol_change <= 0:
        base = 20.0
    elif vol_change < 50:
        base = 30.0
    elif vol_change < 100:
        base = 50.0
    elif vol_change < 300:
        base = 65.0
    elif vol_change < 500:
        base = 75.0
    elif vol_change < 1000:
        base = 85.0
    else:
        base = 95.0

    if liquidity >= 5_000_000:
        base += 3.0
    elif liquidity >= 1_000_000:
        base += 2.0
    elif liquidity < 250_000:
        base -= 5.0

    if vol_change > 100 and price_h1 > 5:
        base += 5.0
    elif vol_change > 100 and price_h1 < -5:
        base -= 3.0

    if price_h24 > 20:
        base += 2.0

    if boost >= 500:
        base += 3.0
    elif boost >= 100:
        base += 1.5

    if age_days < 7:
        base -= 8.0
    elif age_days < 30:
        base -= 3.0

    return max(0.0, min(100.0, base))


def score_defillama(sym: str, llama_data: Dict[str, Dict]) -> float:
    info = llama_data.get(sym)
    if not info:
        return 0.0

    tvl    = info.get("tvl", 0)
    chg_1d = info.get("change_1d", 0)
    chg_7d = info.get("change_7d", 0)

    if chg_1d > 50:
        base = 95.0
    elif chg_1d > 25:
        base = 85.0
    elif chg_1d > 15:
        base = 75.0
    elif chg_1d > 8:
        base = 65.0
    elif chg_1d > 3:
        base = 50.0
    elif chg_1d > 0:
        base = 35.0
    elif chg_1d > -5:
        base = 25.0
    else:
        base = 10.0

    if chg_7d > 30:
        base += 5.0
    elif chg_7d > 15:
        base += 3.0
    elif chg_7d < -20:
        base -= 5.0

    if tvl >= 1_000_000_000:
        base += 5.0
    elif tvl >= 100_000_000:
        base += 3.0
    elif tvl >= 10_000_000:
        base += 1.0
    elif tvl < 1_000_000:
        base -= 5.0

    return max(0.0, min(100.0, base))


def score_etherscan(sym: str, es_data: Dict[str, Dict]) -> float:
    """
    Score based on on-chain whale activity:
    - velocity_ratio (1h vs 24h average) → main signal
    - whale_tx_count (transfers ≥$10K)
    - unique_addrs_24h (diversity)
    """
    info = es_data.get(sym)
    if not info:
        return 0.0

    velocity     = info.get("velocity_ratio", 0)
    unique_addrs = info.get("unique_addrs_24h", 0)
    whale_count  = info.get("whale_tx_count_1h", 0)
    whale_vol    = info.get("whale_volume_usd_24h", 0)
    tx_24h       = info.get("tx_count_24h", 0)

    # Base: velocity ratio (1h tx count / 24h hourly average)
    if velocity >= 5.0:
        base = 95.0           # 5x normal = explosion
    elif velocity >= 3.0:
        base = 85.0
    elif velocity >= 2.0:
        base = 75.0
    elif velocity >= 1.5:
        base = 65.0
    elif velocity >= 1.0:
        base = 50.0
    elif velocity >= 0.5:
        base = 35.0
    else:
        base = 20.0

    # Whale tx bonus (last 1h)
    if whale_count >= 5:
        base += 8.0
    elif whale_count >= 2:
        base += 5.0
    elif whale_count >= 1:
        base += 2.0

    # Unique address diversity (organic interest indicator)
    if unique_addrs >= 200:
        base += 5.0
    elif unique_addrs >= 100:
        base += 3.0
    elif unique_addrs < 20:
        base -= 5.0  # too few = manipulated

    # Whale volume bonus
    if whale_vol >= 1_000_000:
        base += 3.0

    # Activity floor: very low tx_24h = dead token
    if tx_24h < 10:
        base = min(base, 30.0)

    return max(0.0, min(100.0, base))


def score_binance(sym: str, bin_data: Dict[str, Dict]) -> float:
    info = bin_data.get(sym)
    if not info:
        return 0.0

    price_chg = info.get("price_change_pct", 0)
    qvol      = info.get("quote_volume", 0)
    vol_rank  = info.get("volume_rank", 9999)
    total     = info.get("total_pairs", 1)

    abs_chg = abs(price_chg)
    if abs_chg > 40:
        base = 95.0
    elif abs_chg > 25:
        base = 85.0
    elif abs_chg > 15:
        base = 70.0
    elif abs_chg > 8:
        base = 55.0
    elif abs_chg > 4:
        base = 40.0
    else:
        base = 20.0

    rank_pct = (vol_rank / total * 100) if total > 0 else 100
    if rank_pct <= 5:
        base += 8.0
    elif rank_pct <= 10:
        base += 5.0
    elif rank_pct <= 25:
        base += 2.0
    elif rank_pct > 75:
        base -= 5.0

    if price_chg > 0:
        base += 2.0

    if qvol >= 500_000_000:
        base += 5.0
    elif qvol >= 100_000_000:
        base += 3.0

    return max(0.0, min(100.0, base))


def score_coinpaprika(sym: str, cp_data: Dict[str, Dict]) -> float:
    info = cp_data.get(sym)
    if not info:
        return 0.0

    pct_24h     = info.get("percent_24h", 0)
    gainer_rank = info.get("gainer_rank", 9999)
    mc_rank     = info.get("mc_rank", 9999)

    if gainer_rank <= 5:
        base = 95.0
    elif gainer_rank <= 10:
        base = 85.0
    elif gainer_rank <= 25:
        base = 70.0
    elif gainer_rank <= 50:
        base = 55.0
    elif gainer_rank <= 100:
        base = 35.0
    elif gainer_rank <= 250:
        base = 20.0
    else:
        base = 10.0

    if pct_24h < 2:
        base *= 0.5
    elif pct_24h > 30:
        base += 5.0

    if mc_rank <= 50:
        base += 3.0
    elif mc_rank > 1000:
        base -= 3.0

    return max(0.0, min(100.0, base))


def score_massive(sym: str, massive_data: Dict[str, Dict]) -> float:
    """
    Score from Massive (cross-exchange aggregated data).
    Already pre-computed in fetch_massive_data.
    """
    info = massive_data.get(sym)
    if not info:
        return 0.0
    return float(info.get("momentum_score", 0))


# ══════════════════════════════════════════════════════════════════
# 6. AGGREGATOR (chain-aware dynamic weights)
# ══════════════════════════════════════════════════════════════════

def aggregate_hype_signals(
    ds_data: Dict[str, Dict],
    llama_data: Dict[str, Dict],
    es_data: Dict[str, Dict],
    bin_data: Dict[str, Dict],
    cp_data: Dict[str, Dict],
    massive_data: Optional[Dict[str, Dict]] = None,
) -> List[Dict[str, Any]]:
    """Combine 5-6 sources with chain-aware weights → ranked list."""

    if massive_data is None:
        massive_data = {}

    all_syms = set()
    all_syms.update(ds_data.keys())
    all_syms.update(llama_data.keys())
    all_syms.update(es_data.keys())
    all_syms.update(bin_data.keys())
    all_syms.update(cp_data.keys())
    all_syms.update(massive_data.keys())

    results = []
    for sym in all_syms:
        s_ds      = score_dexscreener(sym, ds_data)
        s_llama   = score_defillama(sym, llama_data)
        s_es      = score_etherscan(sym, es_data)
        s_bin     = score_binance(sym, bin_data)
        s_cp      = score_coinpaprika(sym, cp_data)
        s_massive = score_massive(sym, massive_data)

        # Determine chain context for weight selection
        ds_info = ds_data.get(sym, {})
        chain = ds_info.get("chain", "")
        is_evm = ds_info.get("is_evm", False)

        weights = get_weights_for_chain(chain)

        all_scores = [s_ds, s_llama, s_es, s_bin, s_cp, s_massive]
        sources_count = sum(1 for s in all_scores if s >= 30)

        # Compute unified score (weights["massive"] is 0 if no key)
        unified = (
            s_ds      * weights["dexscreener"] +
            s_llama   * weights["defillama"] +
            s_es      * weights["etherscan"] +
            s_bin     * weights["binance"] +
            s_cp      * weights["coinpaprika"] +
            s_massive * weights.get("massive", 0)
        )

        if unified < 30:
            continue

        results.append({
            "symbol":         sym,
            "score":          round(unified, 1),
            "sources_count":  sources_count,
            "is_evm":         is_evm,
            "chain":          chain,
            "weights_used":   weights,
            "breakdown": {
                "dexscreener": round(s_ds, 1),
                "defillama":   round(s_llama, 1),
                "etherscan":   round(s_es, 1),
                "binance":     round(s_bin, 1),
                "coinpaprika": round(s_cp, 1),
                "massive":     round(s_massive, 1),
            },
            "ds_info":      ds_data.get(sym, {}),
            "llama_info":   llama_data.get(sym, {}),
            "es_info":      es_data.get(sym, {}),
            "bin_info":     bin_data.get(sym, {}),
            "cp_info":      cp_data.get(sym, {}),
            "massive_info": massive_data.get(sym, {}),
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ══════════════════════════════════════════════════════════════════
# 6.5 AI LAYER — Gemini Hype Quality Analysis (v4.0)
# ══════════════════════════════════════════════════════════════════
# Gemini analyzes each high-grade hype signal to determine:
# - Is the hype ORGANIC or PUMPED?
# - Risk level
# - Hold/Sell/Avoid recommendation
import json
import re

def gemini_analyze_hype(item: Dict[str, Any]) -> Optional[Dict]:
    """
    Analyze hype signal with Gemini AI.
    Returns: {quality, risk, recommendation_ar, reasoning_ar} or None
    """
    if not GEMINI_API_KEY:
        return None

    sym = item.get("symbol", "")
    score = item.get("score", 0)
    breakdown = item.get("breakdown", {})
    ds_info = item.get("ds_info", {})
    llama_info = item.get("llama_info", {})
    es_info = item.get("es_info", {})
    massive_info = item.get("massive_info", {})

    # Build context for AI
    context = []
    context.append(f"Symbol: {sym}")
    context.append(f"Total hype score: {score}/100")
    context.append(f"Chain: {ds_info.get('chain', 'unknown')}")

    # Source scores
    context.append("\nSource breakdown:")
    for src, val in breakdown.items():
        if val > 0:
            context.append(f"  - {src}: {val}/100")

    # Critical metrics
    if ds_info:
        context.append(f"\nDEX volume 24h: ${ds_info.get('volume_24h', 0):,.0f}")
        context.append(f"DEX price change 24h: {ds_info.get('price_change_24h', 0):.1f}%")
        context.append(f"Liquidity: ${ds_info.get('liquidity', 0):,.0f}")

    if es_info:
        context.append(f"\nWhale tx (1h, ≥$10K): {es_info.get('whale_tx_count', 0)}")
        context.append(f"Velocity ratio: {es_info.get('velocity_ratio', 0):.2f}")
        context.append(f"Unique addresses 24h: {es_info.get('unique_addresses', 0)}")

    if llama_info:
        context.append(f"\nTVL: ${llama_info.get('tvl', 0):,.0f}")
        context.append(f"TVL change 1d: {llama_info.get('tvl_change_1d', 0):.1f}%")

    if massive_info:
        context.append(f"\nMassive cross-exchange:")
        context.append(f"  Price: ${massive_info.get('price', 0):,.4f}")
        context.append(f"  24h change: {massive_info.get('change_24h', 0):.2f}%")
        context.append(f"  24h volume: ${massive_info.get('volume_24h', 0):,.0f}")

    context_str = "\n".join(context)

    prompt = f"""You are a crypto hype quality analyst (Wintermute/Jump-style).
Analyze this hype signal and determine if it's ORGANIC growth or PUMPED.

{context_str}

Reply with ONLY this JSON (no markdown, no code fences):

{{
  "quality": "ORGANIC OR PUMPED OR MIXED",
  "risk": "low OR medium OR high OR extreme",
  "recommendation_ar": "توصية قصيرة بالعربي (HOLD/SELL/AVOID + سبب)",
  "reasoning_ar": "2-3 جمل بالعربي تشرح الجودة والمخاطر",
  "confidence": "high OR medium OR low"
}}

Decision rules:
- ORGANIC: balanced sources, real volume from many addresses, sustainable TVL growth
- PUMPED: extreme spike with low whale count, vol/liquidity ratio > 5x normal
- High risk if: low liquidity, single-source spike, suspicious patterns
- AVOID: high risk + pumped signals
- HOLD: organic + medium risk
- BUY (carefully): organic + low risk + multiple sources confirm"""

    url = f"{GEMINI_BASE}/models/{GEMINI_MODEL}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
    }
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 500}
    }

    try:
        r = requests.post(url, headers=headers, json=body, timeout=(10, 25))
    except Exception as e:
        log.warning(f"[GEMINI] {sym}: {type(e).__name__}: {e}")
        return None

    if r.status_code != 200:
        log.warning(f"[GEMINI] {sym}: HTTP {r.status_code}")
        return None

    try:
        data = r.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, ValueError):
        return None

    # Strip code fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)

    parsed = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None

    if not parsed:
        return None

    return {
        "quality":          str(parsed.get("quality", "MIXED")).upper(),
        "risk":             str(parsed.get("risk", "medium")).lower(),
        "recommendation_ar": parsed.get("recommendation_ar", ""),
        "reasoning_ar":     parsed.get("reasoning_ar", ""),
        "confidence":       str(parsed.get("confidence", "medium")).lower(),
    }


# ══════════════════════════════════════════════════════════════════
# 6.6 PORTFOLIO INTEGRATION (v4.0)
# ══════════════════════════════════════════════════════════════════

# ── v5.0: Claude — Wintermute-Style Strategist ──
# Triggers on score ≥85. Provides scenario + risks + historical context.

def claude_analyze_strategy(item: Dict[str, Any]) -> Optional[Dict]:
    """
    🟣 Claude — Wintermute-Style Strategist.
    Deep reasoning: 24-48h scenario, risks, historical pattern matching.
    Returns: {scenario_ar, risks_ar, historical_ar, target_pct, confidence}
    """
    if not CLAUDE_API_KEY:
        return None

    sym = item.get("symbol", "")
    score = item.get("score", 0)
    breakdown = item.get("breakdown", {})
    ds_info = item.get("ds_info", {})
    es_info = item.get("es_info", {})
    llama_info = item.get("llama_info", {})
    massive_info = item.get("massive_info", {})
    gemini = item.get("ai", {})  # Gemini's quality verdict

    # Build context
    context_parts = [
        f"Token: {sym}",
        f"Hype Score: {score}/100",
        f"Chain: {ds_info.get('chain', 'unknown')}",
    ]

    if ds_info:
        context_parts.append(
            f"DEX: vol_24h=${ds_info.get('volume_24h', 0):,.0f}, "
            f"price_change_24h={ds_info.get('price_change_24h', 0):.1f}%, "
            f"liquidity=${ds_info.get('liquidity', 0):,.0f}"
        )
    if es_info:
        context_parts.append(
            f"On-chain: whale_tx={es_info.get('whale_tx_count', 0)}, "
            f"velocity={es_info.get('velocity_ratio', 0):.2f}x, "
            f"unique_addrs={es_info.get('unique_addresses', 0)}"
        )
    if llama_info:
        context_parts.append(
            f"TVL: ${llama_info.get('tvl', 0):,.0f}, "
            f"1d={llama_info.get('tvl_change_1d', 0):.1f}%, "
            f"7d={llama_info.get('tvl_change_7d', 0):.1f}%"
        )
    if massive_info:
        context_parts.append(
            f"Cross-exchange: price=${massive_info.get('price', 0):,.4f}, "
            f"24h={massive_info.get('change_24h', 0):.2f}%, "
            f"vol=${massive_info.get('volume_24h', 0):,.0f}, "
            f"24h_high=${massive_info.get('high_24h', 0):,.4f}, "
            f"24h_low=${massive_info.get('low_24h', 0):,.4f}"
        )
    if gemini:
        context_parts.append(
            f"Gemini verdict: quality={gemini.get('quality', '?')}, "
            f"risk={gemini.get('risk', '?')}"
        )

    context_str = "\n".join(context_parts)

    prompt = f"""You are a senior crypto strategist at a quantitative fund (Wintermute/Jump style).
Analyze this hype signal with DEEP reasoning. Focus on whale behavior, market structure, and historical patterns.

{context_str}

YOUR TASK: Provide strategic analysis. Reply with ONLY this JSON (no markdown, no code fences):

{{
  "scenario_ar": "السيناريو الأرجح خلال 24-48 ساعة (3-4 أسطر بالعربي مع نسب %)",
  "risks_ar": "أهم 2-3 مخاطر يجب الحذر منها (بالعربي)",
  "historical_ar": "سياق تاريخي: متى حدث pattern مشابه وما كانت النتيجة (سطر-سطرين بالعربي)",
  "target_pct_24h": number (expected % move in 24h, e.g. 8.5 or -5.0),
  "target_pct_48h": number (expected % move in 48h),
  "key_resistance": number OR null (price level if data available),
  "key_support": number OR null,
  "confidence": "high OR medium OR low",
  "agree_with_gemini": true OR false
}}

CRITICAL:
- USE the cross-exchange prices above for resistance/support
- Do NOT invent price levels — use 24h_high/low as anchors
- Be specific. Reference whale behavior, velocity ratios, TVL flows."""

    headers = {
        "Content-Type": "application/json",
        "x-api-key": CLAUDE_API_KEY,
        "anthropic-version": "2023-06-01",
    }
    body = {
        "model": CLAUDE_MODEL,
        "max_tokens": 800,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        r = requests.post(CLAUDE_BASE, headers=headers, json=body, timeout=(10, 35))
    except Exception as e:
        log.warning(f"[CLAUDE] {sym}: {type(e).__name__}: {e}")
        return None

    # Fallback to Sonnet if Opus fails
    if r.status_code in (404, 400):
        log.info(f"[CLAUDE] {CLAUDE_MODEL} unavailable, trying {CLAUDE_FALLBACK}")
        body["model"] = CLAUDE_FALLBACK
        try:
            r = requests.post(CLAUDE_BASE, headers=headers, json=body, timeout=(10, 35))
        except Exception as e:
            log.warning(f"[CLAUDE] fallback failed: {e}")
            return None

    if r.status_code != 200:
        log.warning(f"[CLAUDE] {sym}: HTTP {r.status_code}")
        return None

    try:
        data = r.json()
        content = data.get("content", [])
        if not content:
            return None
        text = content[0].get("text", "").strip()
    except (KeyError, IndexError, ValueError):
        return None

    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    text = text.strip()

    parsed = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None

    if not parsed:
        return None

    return {
        "scenario_ar":      parsed.get("scenario_ar", ""),
        "risks_ar":         parsed.get("risks_ar", ""),
        "historical_ar":    parsed.get("historical_ar", ""),
        "target_pct_24h":   parsed.get("target_pct_24h"),
        "target_pct_48h":   parsed.get("target_pct_48h"),
        "key_resistance":   parsed.get("key_resistance"),
        "key_support":      parsed.get("key_support"),
        "confidence":       str(parsed.get("confidence", "medium")).lower(),
        "agree_with_gemini": bool(parsed.get("agree_with_gemini", True)),
    }


# ── v5.0: OpenAI — Trade Execution Advisor ──
# Triggers on score ≥92 (golden tier only). Provides specific entry/exit levels.

def openai_analyze_execution(item: Dict[str, Any]) -> Optional[Dict]:
    """
    🔵 OpenAI GPT-4o — Trade Execution Advisor.
    Specific actionable trade plan: entry, targets, stop loss, timing.
    Returns: {entry, target1, target2, stop_loss, time_window_ar, conviction}
    """
    if not OPENAI_API_KEY:
        return None

    sym = item.get("symbol", "")
    score = item.get("score", 0)
    massive_info = item.get("massive_info", {})
    ds_info = item.get("ds_info", {})
    gemini = item.get("ai", {})
    claude = item.get("claude", {})
    portfolio = item.get("portfolio", {})

    # Use cross-exchange price (most accurate)
    current_price = (massive_info.get("price")
                     or ds_info.get("price_usd") or 0)
    high_24h = massive_info.get("high_24h", 0)
    low_24h = massive_info.get("low_24h", 0)

    if current_price <= 0:
        return None

    # Build context
    context_parts = [
        f"Token: {sym}",
        f"Hype Score: {score}/100 (golden tier)",
        f"Current Price: ${current_price:,.6f}".rstrip("0").rstrip("."),
        f"24h High: ${high_24h:,.6f}".rstrip("0").rstrip("."),
        f"24h Low: ${low_24h:,.6f}".rstrip("0").rstrip("."),
    ]

    if gemini:
        context_parts.append(
            f"Gemini quality: {gemini.get('quality', '?')} / "
            f"risk={gemini.get('risk', '?')}"
        )
    if claude:
        ctx_24h = claude.get("target_pct_24h")
        ctx_res = claude.get("key_resistance")
        ctx_sup = claude.get("key_support")
        if ctx_24h is not None:
            context_parts.append(f"Claude 24h target: {ctx_24h:.1f}%")
        if ctx_res:
            context_parts.append(f"Claude resistance: ${ctx_res}")
        if ctx_sup:
            context_parts.append(f"Claude support: ${ctx_sup}")

    if portfolio:
        avg_buy = portfolio.get("avg_buy_price", 0)
        if avg_buy > 0:
            context_parts.append(f"User holding at avg ${avg_buy:.6f}")

    context_str = "\n".join(context_parts)

    prompt = f"""You are a crypto trading desk executor (Jump Trading style).
Give a SPECIFIC actionable trade plan for this golden hype signal.

{context_str}

YOUR TASK: Build a precise trade plan. Reply with ONLY this JSON:

{{
  "entry": number (recommended entry price),
  "target_1": number (first take-profit, ~3-7% from entry),
  "target_2": number (second take-profit, ~10-20% from entry),
  "stop_loss": number (max loss point, below 24h low),
  "position_size_ar": "حجم الصفقة الموصى به (مثل: '2-5% من المحفظة')",
  "time_window_ar": "متى تنفذ ومتى تخرج (مثل: 'دخول الآن، خروج خلال 24-48h')",
  "conviction": "high OR medium OR low",
  "action_ar": "1-2 سطر توصية تنفيذية واضحة بالعربي"
}}

CRITICAL PRICE RULES:
- ALL prices must be plain numbers (e.g. 76490.50 NOT "$76,490.50")
- entry should be at or near current price (slight pullback ideal)
- target_1 must be > entry, target_2 > target_1
- stop_loss must be < entry (typically below 24h_low)
- Use the actual 24h_high/low above as anchors
- DO NOT invent levels outside the data provided
- Be DECISIVE but never financial advice."""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
    }
    body = {
        "model": OPENAI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 600,
        "response_format": {"type": "json_object"},
    }

    try:
        r = requests.post(OPENAI_BASE, headers=headers, json=body, timeout=(10, 35))
    except Exception as e:
        log.warning(f"[OPENAI] {sym}: {type(e).__name__}: {e}")
        return None

    # Fallback to mini if main fails
    if r.status_code in (404, 400):
        log.info(f"[OPENAI] {OPENAI_MODEL} issue, trying {OPENAI_FALLBACK}")
        body["model"] = OPENAI_FALLBACK
        try:
            r = requests.post(OPENAI_BASE, headers=headers, json=body, timeout=(10, 35))
        except Exception as e:
            log.warning(f"[OPENAI] fallback failed: {e}")
            return None

    if r.status_code != 200:
        log.warning(f"[OPENAI] {sym}: HTTP {r.status_code}")
        return None

    try:
        data = r.json()
        text = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, ValueError):
        return None

    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)

    parsed = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None

    if not parsed:
        return None

    def _safe_float(v):
        try:
            return float(v) if v is not None and v != "null" else None
        except (ValueError, TypeError):
            return None

    return {
        "entry":           _safe_float(parsed.get("entry")),
        "target_1":        _safe_float(parsed.get("target_1")),
        "target_2":        _safe_float(parsed.get("target_2")),
        "stop_loss":       _safe_float(parsed.get("stop_loss")),
        "position_size_ar": parsed.get("position_size_ar", ""),
        "time_window_ar":  parsed.get("time_window_ar", ""),
        "conviction":      str(parsed.get("conviction", "medium")).lower(),
        "action_ar":       parsed.get("action_ar", ""),
    }


# ── v5.0: AI Council Router ──
# Tier-based escalation: more AIs as score increases.

def determine_ai_tier(score: float) -> str:
    """
    Determines which AI tier to invoke based on score.
    - tier_none:     score < 75   → no AI (basic alert)
    - tier_quality:  75-84        → Gemini only (quality check)
    - tier_strategy: 85-91        → Gemini + Claude (+ scenario)
    - tier_council:  92+          → All 3 AIs (full council)
    """
    if score >= 92:
        return "tier_council"
    if score >= 85:
        return "tier_strategy"
    if score >= 75:
        return "tier_quality"
    return "tier_none"


def run_ai_council(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run AI council based on score tier.
    Modifies item in-place to add ai/claude/openai keys.
    """
    score = item.get("score", 0)
    tier = determine_ai_tier(score)
    sym = item.get("symbol", "?")

    if tier == "tier_none":
        return item

    # Tier 1: Gemini (always for score ≥75)
    if tier in ("tier_quality", "tier_strategy", "tier_council"):
        try:
            gemini_result = gemini_analyze_hype(item)
            if gemini_result:
                item["ai"] = gemini_result
                log.info(f"[AI] {sym} Gemini: {gemini_result.get('quality')}/"
                         f"{gemini_result.get('risk')}")
        except Exception as e:
            log.warning(f"[AI] {sym} Gemini failed: {e}")

    # Tier 2: Claude (score ≥85)
    if tier in ("tier_strategy", "tier_council"):
        try:
            claude_result = claude_analyze_strategy(item)
            if claude_result:
                item["claude"] = claude_result
                log.info(f"[AI] {sym} Claude: target_24h="
                         f"{claude_result.get('target_pct_24h')}%, "
                         f"conf={claude_result.get('confidence')}")
        except Exception as e:
            log.warning(f"[AI] {sym} Claude failed: {e}")

    # Tier 3: OpenAI (score ≥92 only — golden)
    if tier == "tier_council":
        try:
            openai_result = openai_analyze_execution(item)
            if openai_result:
                item["openai"] = openai_result
                log.info(f"[AI] {sym} OpenAI: entry={openai_result.get('entry')}, "
                         f"conv={openai_result.get('conviction')}")
        except Exception as e:
            log.warning(f"[AI] {sym} OpenAI failed: {e}")

    item["ai_tier"] = tier
    return item


def load_dca_portfolio() -> Optional[Dict]:
    """Load latest portfolio from DCA_BOT shared volume."""
    portfolio_file = os.path.join(DCA_DATA_DIR, "portfolio_latest.json")
    if not os.path.exists(portfolio_file):
        return None
    try:
        with open(portfolio_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.debug(f"[PORTFOLIO] load failed: {e}")
        return None


def get_portfolio_position(symbol: str) -> Optional[Dict]:
    """Check if symbol is in user's DCA portfolio."""
    portfolio = load_dca_portfolio()
    if not portfolio:
        return None
    holdings = portfolio.get("holdings", [])
    for h in holdings:
        if h.get("symbol", "").upper() == symbol.upper():
            return {
                "amount":      h.get("amount", 0),
                "avg_buy_price": h.get("avg_buy_price", 0),
                "current_pnl_pct": h.get("pnl_pct", 0),
                "exchange":    h.get("exchange", ""),
            }
    return None


# ══════════════════════════════════════════════════════════════════
# 7. FILTERS
# ══════════════════════════════════════════════════════════════════

def passes_mode_filter(item: Dict[str, Any], mode: str) -> Tuple[bool, str]:
    cfg = MODES.get(mode, MODES["عادي"])

    if item["score"] < cfg["min"]:
        return False, f"score {item['score']} < {cfg['min']}"

    # For non-EVM tokens, max sources is 4 (Etherscan unavailable)
    max_possible_sources = 5 if item.get("is_evm") and ETHERSCAN_KEY else 4
    required_sources = min(cfg["min_sources"], max_possible_sources)

    if item["sources_count"] < required_sources:
        return False, f"sources {item['sources_count']}/{required_sources}"

    if cfg["min_per_source"] > 0:
        active_scores = [v for v in item["breakdown"].values() if v >= 30]
        if active_scores:
            min_active = min(active_scores)
            if min_active < cfg["min_per_source"]:
                return False, f"weakest {min_active} < {cfg['min_per_source']}"

    return True, "ok"


def is_in_cooldown(symbol: str) -> bool:
    last_seen = seen_coins.get(symbol)
    if not last_seen:
        return False
    try:
        last_dt = datetime.fromisoformat(last_seen)
        return (datetime.now(TZ_RIYADH) - last_dt) < timedelta(hours=COOLDOWN_HOURS)
    except Exception:
        return False


def mark_seen(symbol: str):
    seen_coins[symbol] = now_iso()


# ══════════════════════════════════════════════════════════════════
# 8. ALERT FORMATTER
# ══════════════════════════════════════════════════════════════════

def _grade_label(score: float) -> str:
    if score >= 92:  return "👑 *ذهبي* (نادر)"
    if score >= 85:  return "💎 *جودة*"
    if score >= 75:  return "⚖️ *متوازن*"
    if score >= 65:  return "🟢 *عادي*"
    return "⚪ ضعيف"


def _src_emoji(score: float) -> str:
    if score >= 75: return "🟢"
    if score >= 50: return "🟡"
    if score >= 30: return "🔵"
    return "⚪"


def _explorer_url(chain: str, address: str) -> str:
    """Get block explorer URL for chain."""
    explorers = {
        "ethereum":  "https://etherscan.io/token/",
        "bsc":       "https://bscscan.com/token/",
        "polygon":   "https://polygonscan.com/token/",
        "arbitrum":  "https://arbiscan.io/token/",
        "optimism":  "https://optimistic.etherscan.io/token/",
        "base":      "https://basescan.org/token/",
        "avalanche": "https://snowtrace.io/token/",
        "fantom":    "https://ftmscan.com/token/",
        "linea":     "https://lineascan.build/token/",
        "blast":     "https://blastscan.io/token/",
    }
    base = explorers.get((chain or "").lower(), "https://etherscan.io/token/")
    return f"{base}{address}"


def format_alert(item: Dict[str, Any], mode: str) -> str:
    sym       = item["symbol"]
    score     = item["score"]
    sources   = item["sources_count"]
    is_evm    = item["is_evm"]
    chain     = item["chain"]
    bk        = item["breakdown"]
    weights   = item["weights_used"]
    ds        = item["ds_info"]
    llama     = item["llama_info"]
    es        = item["es_info"]
    bin_i     = item["bin_info"]
    cp        = item["cp_info"]

    grade = _grade_label(score)

    lines = []
    lines.append(f"🔥 *إشارة HYPE* — `{sym}`")
    if chain:
        lines.append(f"⛓ Chain: `{chain}` {'(EVM ✅)' if is_evm else '(non-EVM)'}")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🎯 السكور الموحّد: *{score}/100* {grade}")

    total_sources = 5 if (is_evm and ETHERSCAN_KEY) else 4
    lines.append(f"📊 المصادر المتفقة: *{sources}/{total_sources}*")
    lines.append("")

    lines.append("*التفصيل (whale-weighted):*")

    # ① DexScreener
    if bk["dexscreener"] > 0:
        w_pct = int(weights["dexscreener"] * 100)
        lines.append(
            f"{_src_emoji(bk['dexscreener'])} DexScreener: `{bk['dexscreener']}/100` (وزن {w_pct}%)"
        )
        if ds:
            vc = ds.get("vol_change_pct", 0)
            liq = ds.get("liquidity_usd", 0)
            ph1 = ds.get("price_change_h1", 0)
            lines.append(
                f"   💧 Vol +{vc:.0f}% | Liq ${liq/1000:.0f}K | "
                f"H1: {ph1:+.1f}%"
            )

    # ② DefiLlama
    if bk["defillama"] > 0:
        w_pct = int(weights["defillama"] * 100)
        lines.append(
            f"{_src_emoji(bk['defillama'])} DefiLlama: `{bk['defillama']}/100` (وزن {w_pct}%)"
        )
        if llama:
            tvl = llama.get("tvl", 0)
            c1d = llama.get("change_1d", 0)
            c7d = llama.get("change_7d", 0)
            cat = llama.get("category", "?")
            tvl_s = f"${tvl/1e9:.1f}B" if tvl >= 1e9 else f"${tvl/1e6:.1f}M"
            lines.append(
                f"   🦙 TVL: {tvl_s} | 1d: {c1d:+.1f}% | 7d: {c7d:+.1f}% | {cat}"
            )

    # ③ Etherscan (only for EVM tokens with key)
    if is_evm and ETHERSCAN_KEY and bk["etherscan"] > 0:
        w_pct = int(weights["etherscan"] * 100)
        lines.append(
            f"{_src_emoji(bk['etherscan'])} Etherscan: `{bk['etherscan']}/100` (وزن {w_pct}%)"
        )
        if es:
            vel = es.get("velocity_ratio", 0)
            uniq = es.get("unique_addrs_24h", 0)
            whale = es.get("whale_tx_count_1h", 0)
            tx1h = es.get("tx_count_1h", 0)
            wvol = es.get("whale_volume_usd_24h", 0)
            wvol_s = f"${wvol/1e6:.1f}M" if wvol >= 1e6 else f"${wvol/1e3:.0f}K"
            lines.append(
                f"   🔍 Velocity: {vel:.1f}x | Whales(1h): {whale} | "
                f"Addrs(24h): {uniq}"
            )
            lines.append(
                f"   🐳 Tx(1h): {tx1h} | WhaleVol(24h): {wvol_s}"
            )

    # ④ Binance Futures
    if bk["binance"] > 0:
        w_pct = int(weights["binance"] * 100)
        lines.append(
            f"{_src_emoji(bk['binance'])} Binance: `{bk['binance']}/100` (وزن {w_pct}%)"
        )
        if bin_i:
            pc = bin_i.get("price_change_pct", 0)
            qv = bin_i.get("quote_volume", 0)
            vr = bin_i.get("volume_rank", 0)
            qv_s = f"${qv/1e9:.2f}B" if qv >= 1e9 else f"${qv/1e6:.1f}M"
            lines.append(
                f"   🐋 24h: {pc:+.2f}% | Vol: {qv_s} | Rank #{vr}"
            )

    # ⑤ CoinPaprika
    if bk["coinpaprika"] > 0:
        w_pct = int(weights["coinpaprika"] * 100)
        lines.append(
            f"{_src_emoji(bk['coinpaprika'])} CoinPaprika: `{bk['coinpaprika']}/100` (وزن {w_pct}%)"
        )
        if cp:
            gr = cp.get("gainer_rank", 0)
            mr = cp.get("mc_rank", 0)
            p24 = cp.get("percent_24h", 0)
            lines.append(
                f"   📊 Gainer #{gr} | MC #{mr} | 24h: {p24:+.2f}%"
            )

    lines.append("")

    # Price summary
    price = 0
    if ds and ds.get("price_usd"):
        price = ds["price_usd"]
    elif bin_i and bin_i.get("last_price"):
        price = bin_i["last_price"]
    elif cp and cp.get("price"):
        price = cp["price"]

    if price > 0:
        if price < 0.01:
            price_str = f"${price:.8f}".rstrip('0').rstrip('.')
        elif price < 1:
            price_str = f"${price:.6f}".rstrip('0').rstrip('.')
        else:
            price_str = f"${price:,.4f}"
        lines.append(f"💰 السعر: `{price_str}`")

    if bin_i and bin_i.get("price_change_pct") is not None:
        lines.append(f"📈 24س: {bin_i['price_change_pct']:+.2f}%")
    elif cp and cp.get("percent_24h") is not None:
        lines.append(f"📈 24س: {cp['percent_24h']:+.2f}%")

    lines.append("")

    # Wall street insight
    if score >= 92:
        if is_evm and bk["etherscan"] >= 80:
            lines.append("🎯 *تحليل وول ستريت:* on-chain whale activity ممتازة + إجماع مصادر "
                        "= نمط Wintermute. دخول الحيتان مؤكّد. تحقّق يدوي قبل الدخول.")
        else:
            lines.append("🎯 *تحليل وول ستريت:* 4+ مصادر متفقة بقوة. صفقة قنّاصة. "
                        "تحقّق يدوي قبل الدخول.")
    elif score >= 85:
        lines.append("🎯 *تحليل وول ستريت:* منطقة دخول الحيتان. on-chain volume يدعم.")
    elif score >= 75:
        lines.append("🎯 *تحليل وول ستريت:* watchlist للمتداولين الكبار — مراقبة لا دخول.")
    else:
        lines.append("🎯 *تحليل وول ستريت:* إشارة عادية. retail-friendly.")

    # ── v4.0: Massive cross-exchange data ──
    massive_info = item.get("massive_info", {})
    if massive_info and massive_info.get("price"):
        price = massive_info.get("price", 0)
        change = massive_info.get("change_24h", 0)
        high = massive_info.get("high_24h", 0)
        low = massive_info.get("low_24h", 0)
        vol = massive_info.get("volume_24h", 0)

        if price >= 100:
            p_str, h_str, l_str = f"${price:,.2f}", f"${high:,.2f}", f"${low:,.2f}"
        elif price >= 1:
            p_str, h_str, l_str = f"${price:.4f}", f"${high:.4f}", f"${low:.4f}"
        else:
            p_str, h_str, l_str = f"${price:.6f}", f"${high:.6f}", f"${low:.6f}"

        sign = "+" if change >= 0 else ""
        arrow = "🟢" if change >= 0 else "🔴"
        vol_m = vol / 1_000_000

        lines.append("")
        lines.append("💎 *Massive (Cross-Exchange):*")
        lines.append(f"   السعر: `{p_str}` {arrow} {sign}{change:.2f}%")
        lines.append(f"   24h: `{l_str}` ↔ `{h_str}`")
        lines.append(f"   Volume: `${vol_m:.1f}M`")

    # ── v5.0: Specialized AI Council (3 experts, tier-based) ──
    ai = item.get("ai")
    claude_data = item.get("claude")
    openai_data = item.get("openai")
    has_council = bool(ai or claude_data or openai_data)

    def _fmt_price(val):
        """Format price for display."""
        if val is None or val == "null" or val == "":
            return None
        try:
            num = float(val)
            if num >= 100:
                return f"${num:,.2f}"
            elif num >= 1:
                return f"${num:.4f}"
            elif num > 0:
                return f"${num:.6f}".rstrip("0").rstrip(".")
            return None
        except (ValueError, TypeError):
            return None

    if has_council:
        lines.append("")
        # Council header with tier badge
        tier = item.get("ai_tier", "tier_quality")
        if tier == "tier_council" or (claude_data and openai_data):
            lines.append("🤝 *Council of AI Experts (3/3):*")
        elif tier == "tier_strategy" or claude_data:
            lines.append("🤝 *Council of AI Experts (2/3):*")
        else:
            lines.append("🤖 *AI Analysis:*")

    # 🟢 Gemini — Quality Detector
    if ai:
        quality = ai.get("quality", "MIXED")
        risk = ai.get("risk", "medium")
        rec = ai.get("recommendation_ar", "")
        reasoning = ai.get("reasoning_ar", "")

        q_emoji = {"ORGANIC": "🟢", "PUMPED": "🔴", "MIXED": "🟡"}.get(quality, "⚪")
        r_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "extreme": "🔴"}.get(risk, "⚪")

        lines.append("")
        lines.append("🟢 *Gemini (Quality Detector):*")
        lines.append(f"   {q_emoji} Quality: `{quality}`")
        lines.append(f"   {r_emoji} Risk: `{risk}`")
        if rec:
            lines.append(f"   🎯 توصية: {rec}")
        if reasoning:
            lines.append(f"   💭 _{reasoning}_")

    # 🟣 Claude — Wintermute Strategist
    if claude_data:
        scenario = claude_data.get("scenario_ar", "")
        risks = claude_data.get("risks_ar", "")
        historical = claude_data.get("historical_ar", "")
        target_24h = claude_data.get("target_pct_24h")
        target_48h = claude_data.get("target_pct_48h")
        resistance = claude_data.get("key_resistance")
        support = claude_data.get("key_support")
        confidence = claude_data.get("confidence", "medium")
        agree = claude_data.get("agree_with_gemini", True)

        lines.append("")
        lines.append("🟣 *Claude (Wintermute Strategist):*")

        # Targets
        target_lines = []
        if target_24h is not None:
            try:
                t24 = float(target_24h)
                sign = "+" if t24 >= 0 else ""
                target_lines.append(f"24h: `{sign}{t24:.1f}%`")
            except (ValueError, TypeError):
                pass
        if target_48h is not None:
            try:
                t48 = float(target_48h)
                sign = "+" if t48 >= 0 else ""
                target_lines.append(f"48h: `{sign}{t48:.1f}%`")
            except (ValueError, TypeError):
                pass
        if target_lines:
            lines.append(f"   📊 *Targets:* {' · '.join(target_lines)}")

        if scenario:
            lines.append(f"   🎯 *السيناريو:* {scenario}")

        # Key levels
        r_str = _fmt_price(resistance)
        s_str = _fmt_price(support)
        if r_str or s_str:
            lvl_parts = []
            if s_str:
                lvl_parts.append(f"Support `{s_str}`")
            if r_str:
                lvl_parts.append(f"Resistance `{r_str}`")
            lines.append(f"   📈 *مستويات:* {' ↔ '.join(lvl_parts)}")

        if risks:
            lines.append(f"   ⚠️ *المخاطر:* {risks}")
        if historical:
            lines.append(f"   📚 *سياق:* {historical}")

        agree_str = "متفق مع Gemini" if agree else "*يخالف Gemini*"
        lines.append(f"   🎚 ثقة: `{confidence}` · {agree_str}")

    # 🔵 OpenAI — Trade Executor (golden tier only)
    if openai_data:
        entry = openai_data.get("entry")
        target_1 = openai_data.get("target_1")
        target_2 = openai_data.get("target_2")
        stop_loss = openai_data.get("stop_loss")
        position = openai_data.get("position_size_ar", "")
        time_window = openai_data.get("time_window_ar", "")
        conviction = openai_data.get("conviction", "medium")
        action = openai_data.get("action_ar", "")

        lines.append("")
        lines.append("🔵 *GPT-4o (Trade Executor):*")

        if action:
            lines.append(f"   🎯 *توصية:* {action}")

        # Trade plan
        e_str = _fmt_price(entry)
        t1_str = _fmt_price(target_1)
        t2_str = _fmt_price(target_2)
        sl_str = _fmt_price(stop_loss)

        if e_str:
            plan_lines = [f"Entry: `{e_str}`"]
            if t1_str:
                plan_lines.append(f"T1: `{t1_str}`")
            if t2_str:
                plan_lines.append(f"T2: `{t2_str}`")
            if sl_str:
                plan_lines.append(f"SL: `{sl_str}`")
            lines.append(f"   📈 *الخطة:* {' · '.join(plan_lines)}")

        # Calculate R/R if possible
        try:
            if entry and target_1 and stop_loss:
                e_f = float(entry)
                t1_f = float(target_1)
                sl_f = float(stop_loss)
                if e_f > sl_f:  # long
                    reward = t1_f - e_f
                    risk_amt = e_f - sl_f
                    if risk_amt > 0:
                        rr = reward / risk_amt
                        lines.append(f"   ⚖️ *R/R:* `{rr:.2f}` (مكافأة/مخاطرة)")
        except (ValueError, TypeError, ZeroDivisionError):
            pass

        if position:
            lines.append(f"   💰 *حجم الصفقة:* {position}")
        if time_window:
            lines.append(f"   ⏰ *التوقيت:* {time_window}")

        lines.append(f"   🎚 قناعة: `{conviction}`")

    # ── Council Verdict (when 3 AIs present) ──
    if ai and claude_data and openai_data:
        gemini_quality = ai.get("quality", "MIXED")
        claude_agrees = claude_data.get("agree_with_gemini", True)
        claude_conf = claude_data.get("confidence", "medium")
        openai_conv = openai_data.get("conviction", "medium")

        lines.append("")
        if (gemini_quality == "ORGANIC" and claude_agrees
                and claude_conf == "high" and openai_conv == "high"):
            verdict = "🎯 *إجماع 3/3 — قناعة عالية* ⭐"
        elif gemini_quality == "PUMPED":
            verdict = "🚨 *تحذير: Gemini يكشف PUMP — تجنّب!*"
        elif claude_agrees:
            verdict = "✅ *Claude متفق — إشارة قوية*"
        else:
            verdict = "⚠️ *Claude يخالف — تحقق إضافي مطلوب*"
        lines.append(f"🤝 *Council Verdict:* {verdict}")

    # ── v4.0: Portfolio Position (DCA integration) ──
    portfolio = item.get("portfolio")
    if portfolio:
        amount = portfolio.get("amount", 0)
        avg_buy = portfolio.get("avg_buy_price", 0)
        pnl_pct = portfolio.get("current_pnl_pct", 0)
        exchange = portfolio.get("exchange", "")

        pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
        pnl_sign = "+" if pnl_pct >= 0 else ""

        lines.append("")
        lines.append("💼 *من محفظتك (DCA BOT):*")
        if amount and amount > 0:
            if amount >= 1:
                lines.append(f"   🪙 الكمية: `{amount:.4f} {sym}`")
            else:
                lines.append(f"   🪙 الكمية: `{amount:.6f} {sym}`")
        if avg_buy > 0:
            if avg_buy >= 1:
                lines.append(f"   💰 متوسط الشراء: `${avg_buy:.4f}`")
            else:
                lines.append(f"   💰 متوسط الشراء: `${avg_buy:.6f}`")
        lines.append(f"   📊 PnL: {pnl_emoji} `{pnl_sign}{pnl_pct:.2f}%`")
        if exchange:
            lines.append(f"   🏦 Exchange: `{exchange}`")

    lines.append("")
    lines.append("⚠️ _تنفيذ يدوي — تعليمي فقط، ليس نصيحة مالية._")

    return "\n".join(lines)


def build_alert_buttons(item: Dict[str, Any]) -> Optional[InlineKeyboardMarkup]:
    sym = item["symbol"]
    chain = item["chain"]
    is_evm = item["is_evm"]
    ds  = item.get("ds_info", {})
    llama = item.get("llama_info", {})
    bin_i = item.get("bin_info", {})
    cp = item.get("cp_info", {})
    es = item.get("es_info", {})

    rows = []

    # Row 1: Trading
    btns1 = []
    if bin_i and bin_i.get("symbol_full"):
        btns1.append(InlineKeyboardButton(
            "📊 Binance Fut", url=f"https://www.binance.com/en/futures/{bin_i['symbol_full']}"
        ))
    else:
        btns1.append(InlineKeyboardButton(
            "📊 Binance", url=f"https://www.binance.com/en/trade/{sym}_USDT"
        ))
    if ds and ds.get("pair_url"):
        btns1.append(InlineKeyboardButton("💧 DexScreener", url=ds["pair_url"]))
    rows.append(btns1)

    # Row 2: On-chain explorer (for EVM tokens) + DefiLlama
    btns2 = []
    if is_evm and ds and ds.get("base_token_address"):
        btns2.append(InlineKeyboardButton(
            "🔍 Explorer",
            url=_explorer_url(chain, ds["base_token_address"])
        ))
    if llama and llama.get("url"):
        btns2.append(InlineKeyboardButton("🦙 DefiLlama", url=llama["url"]))
    if btns2:
        rows.append(btns2)

    # Row 3: CoinPaprika
    if cp and cp.get("id"):
        rows.append([InlineKeyboardButton(
            "📊 CoinPaprika", url=f"https://coinpaprika.com/coin/{cp['id']}/"
        )])

    return InlineKeyboardMarkup(rows) if rows else None


# ══════════════════════════════════════════════════════════════════
# 9. SCANNER JOB
# ══════════════════════════════════════════════════════════════════

async def scanner_job(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data or {}
    chat_id = job_data.get("chat_id")
    if not chat_id:
        return

    cfg = chat_config.get(chat_id, {})
    if not cfg.get("active"):
        return

    mode = cfg.get("mode", "عادي")
    log.info(f"[SCAN] start chat={chat_id} mode={mode}")

    try:
        loop = asyncio.get_event_loop()

        # DexScreener FIRST (provides addresses for Etherscan)
        ds_data = await loop.run_in_executor(None, fetch_dexscreener_data)

        # Then 5 in parallel (Etherscan needs DS data, Massive is independent)
        llama_task   = loop.run_in_executor(None, fetch_defillama_data)
        es_task      = loop.run_in_executor(None, fetch_etherscan_data, ds_data)
        bin_task     = loop.run_in_executor(None, fetch_binance_data)
        cp_task      = loop.run_in_executor(None, fetch_coinpaprika_data)
        massive_task = loop.run_in_executor(None, fetch_massive_data)

        llama_data, es_data, bin_data, cp_data, massive_data = await asyncio.gather(
            llama_task, es_task, bin_task, cp_task, massive_task
        )

        aggregated = aggregate_hype_signals(
            ds_data, llama_data, es_data, bin_data, cp_data, massive_data
        )

        global last_results
        last_results = aggregated[:MAX_RESULTS_KEPT]

        sent_count = 0
        for item in aggregated:
            sym = item["symbol"]

            ok, reason = passes_mode_filter(item, mode)
            if not ok:
                continue

            if is_in_cooldown(sym):
                continue

            # ── v5.0: Run AI Council (tier-based escalation) ──
            # tier_quality (≥75): Gemini
            # tier_strategy (≥85): + Claude
            # tier_council (≥92):  + OpenAI
            try:
                item = await loop.run_in_executor(None, run_ai_council, item)
            except Exception as e:
                log.warning(f"[COUNCIL] {sym}: {e}")

            # ── v4.0: Enrich with portfolio data ──
            try:
                portfolio_pos = get_portfolio_position(sym)
                if portfolio_pos:
                    item["portfolio"] = portfolio_pos
                    log.info(f"[PORTFOLIO] {sym} found in user holdings")
            except Exception as e:
                log.debug(f"[PORTFOLIO] {sym}: {e}")

            try:
                msg = format_alert(item, mode)
                buttons = build_alert_buttons(item)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=msg,
                    parse_mode="Markdown",
                    reply_markup=buttons,
                    disable_web_page_preview=True,
                )
                mark_seen(sym)
                alert_history.append({
                    "ts":     now_iso(),
                    "symbol": sym,
                    "score":  item["score"],
                    "mode":   mode,
                    "is_evm": item.get("is_evm", False),
                })
                if len(alert_history) > 100:
                    alert_history.pop(0)
                sent_count += 1
            except Exception as e:
                log.warning(f"[ALERT] failed {sym}: {e}")

        log.info(f"[SCAN] done. {len(aggregated)} signals, {sent_count} alerts sent")

    except Exception as e:
        log.exception(f"[SCAN] error: {e}")


# ══════════════════════════════════════════════════════════════════
# 10. TELEGRAM HANDLERS
# ══════════════════════════════════════════════════════════════════

async def cmd_start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    es_status = ("✅" if ETHERSCAN_KEY else "⚪")
    massive_status = ("✅" if POLYGON_API_KEY else "⚪")
    gem_status = ("✅" if GEMINI_API_KEY else "⚪")
    cl_status = ("✅" if CLAUDE_API_KEY else "⚪")
    oa_status = ("✅" if OPENAI_API_KEY else "⚪")

    msg = (
        "🔥 *HYPE_BOT v5.0* — Specialized AI Council\n\n"
        "كاشف الهايب احترافي بـ 6 مصادر + 3 AI خبراء.\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "*المصادر (6) — chain-aware:*\n"
        "💧 DexScreener    `30%`  on-chain DEX volume\n"
        "🦙 DefiLlama      `18%`  TVL change\n"
        f"🔍 Etherscan      `18%`  whale activity {es_status}\n"
        "🐋 Binance Fut.   `12%`  OI + futures\n"
        "📊 CoinPaprika    `7%`   retail trending\n"
        f"💎 Massive        `15%`  cross-exchange {massive_status}\n\n"
        "*🤝 AI Council (specialized roles):*\n"
        f"🟢 Gemini   {gem_status}  Quality Detector (≥75)\n"
        f"🟣 Claude   {cl_status}  Wintermute Strategist (≥85)\n"
        f"🔵 GPT-4o   {oa_status}  Trade Executor (≥92)\n\n"
        "💼 *Portfolio:* DCA integration\n\n"
        "*أوضاع الكشف (tier-based AI):*\n"
        "🟢 `هايب`          ≥65  Sources only\n"
        "⚖️ `هايب متوازن`    ≥75  + Gemini\n"
        "💎 `هايب جودة`      ≥85  + Claude\n"
        "👑 `هايب ذهبي`      ≥92  + GPT-4o (Council كامل)\n\n"
        "*الأوامر:*\n"
        "`/test`        فحص شامل (6 + AI Council)\n"
        "`/scan SYMBOL` فحص يدوي لعملة + AI ⭐\n"
        "`/movers`      Top gainers cross-exchange ⭐\n"
        "`/esdebug`     تشخيص Etherscan\n"
        "`حالة`         حالة المصادر\n"
        "`نتائج`        آخر 10 إشارات\n"
        "`top10`        أعلى 10 عملات هايب\n"
        "`سجل`          سجل التنبيهات\n"
        "`وقف`          إيقاف الكشف\n\n"
        "⚠️ _تنفيذ يدوي — تعليمي فقط_"
    )
    await u.message.reply_text(msg, parse_mode="Markdown")


async def cmd_test(u: Update, c: ContextTypes.DEFAULT_TYPE):
    msg = await u.message.reply_text("⏳ فحص المصادر الخمسة...")

    loop = asyncio.get_event_loop()
    ds = await loop.run_in_executor(None, fetch_dexscreener_data)
    llama = await loop.run_in_executor(None, fetch_defillama_data)
    es = await loop.run_in_executor(None, fetch_etherscan_data, ds)
    bin_d = await loop.run_in_executor(None, fetch_binance_data)
    cp = await loop.run_in_executor(None, fetch_coinpaprika_data)

    s = source_status

    def line(name: str, key: str, count_label: str) -> str:
        info = s[key]
        icon = "✅" if info.get("ok") else "❌"
        cnt = info.get("count", 0)
        out = f"{icon} *{name}*: {cnt} {count_label}"
        err = info.get("error")
        if err:
            out += f"\n   _{str(err)[:80]}_"
        return out

    lines = ["🔍 *نتيجة الفحص:*\n"]
    lines.append(line("DexScreener", "dexscreener", "رمز"))
    lines.append(line("DefiLlama",   "defillama",   "بروتوكول"))
    if ETHERSCAN_KEY:
        lines.append(line("Etherscan", "etherscan", "EVM token"))
    else:
        lines.append("⚪ *Etherscan*: معطّل (لا يوجد مفتاح ETHERSCAN_KEY)")
    lines.append(line("Binance",     "binance",     "زوج USDT"))
    lines.append(line("CoinPaprika", "coinpaprika", "عملة"))

    # v4.0: Massive (cross-exchange)
    if POLYGON_API_KEY:
        lines.append(line("Massive", "massive", "ticker"))
    else:
        lines.append("⚪ *Massive*: معطّل (لا يوجد POLYGON_API_KEY)")

    # v5.0: AI Council status
    lines.append("")
    lines.append("*🤝 AI Council (Specialized):*")
    if GEMINI_API_KEY:
        lines.append("🟢 Gemini (Quality): ✅ مفعّل · score ≥75")
    else:
        lines.append("🟢 Gemini (Quality): ⚪ معطّل (GEMINI_API_KEY)")
    if CLAUDE_API_KEY:
        lines.append("🟣 Claude (Strategy): ✅ مفعّل · score ≥85")
    else:
        lines.append("🟣 Claude (Strategy): ⚪ معطّل (CLAUDE_API_KEY)")
    if OPENAI_API_KEY:
        lines.append("🔵 OpenAI (Executor): ✅ مفعّل · score ≥92")
    else:
        lines.append("🔵 OpenAI (Executor): ⚪ معطّل (OPENAI_API_KEY)")

    # v4.0: Portfolio status
    lines.append("")
    portfolio = load_dca_portfolio()
    if portfolio:
        n_holdings = len(portfolio.get("holdings", []))
        lines.append(f"💼 *Portfolio (DCA):* ✅ {n_holdings} عملة")
    else:
        lines.append("💼 *Portfolio (DCA):* ⚪ غير متصل")

    active_count = sum(1 for v in s.values() if v.get("ok"))
    expected = 6 if (ETHERSCAN_KEY and POLYGON_API_KEY) else (5 if ETHERSCAN_KEY else 4)
    ai_count = sum(1 for k in [GEMINI_API_KEY, CLAUDE_API_KEY, OPENAI_API_KEY] if k)
    lines.append("")
    if active_count >= expected - 1 and ai_count == 3:
        lines.append(f"🎯 *الحالة:* ممتازة ({active_count}/6 + Council 3/3) ⭐")
    elif active_count >= expected - 1:
        lines.append(f"✅ *الحالة:* جيدة ({active_count}/6 + AI {ai_count}/3)")
    elif active_count >= expected // 2:
        lines.append(f"⚠️ *الحالة:* مقبولة ({active_count}/6)")
    else:
        lines.append(f"🚨 *الحالة:* ضعيفة ({active_count}/5)")

    await msg.delete()
    await u.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_esdebug(u: Update, c: ContextTypes.DEFAULT_TYPE):
    """Etherscan diagnostic — verifies key + endpoint + chain support."""
    if not ETHERSCAN_KEY:
        await u.message.reply_text(
            "⚪ `ETHERSCAN_KEY` غير موجود في environment.\n"
            "أضفه في Railway → Variables.",
            parse_mode="Markdown"
        )
        return

    msg = await u.message.reply_text("⏳ تشخيص Etherscan V2...")

    loop = asyncio.get_event_loop()

    def _test_chain(chainid: int, chain_name: str) -> dict:
        """Light test: query block number (universal, works on all EVM chains)."""
        try:
            url = ETHERSCAN_BASE
            params = {
                "chainid": chainid,
                "module": "proxy",
                "action": "eth_blockNumber",
                "apikey": ETHERSCAN_KEY,
            }
            r = requests.get(url, params=params, timeout=10)
            body_preview = (r.text or "")[:160].replace("\n", " ")
            # eth_blockNumber returns {"jsonrpc":"2.0","id":N,"result":"0x..."}
            ok = (r.status_code == 200 and
                  '"result":"0x' in (r.text or ""))
            return {
                "chain": chain_name,
                "chainid": chainid,
                "status": str(r.status_code),
                "body": body_preview,
                "ok": ok,
            }
        except Exception as e:
            return {
                "chain": chain_name,
                "chainid": chainid,
                "status": "EXCEPTION",
                "body": f"{type(e).__name__}: {str(e)[:120]}",
                "ok": False,
            }

    # Test 3 main EVM chains
    test_chains = [
        (1, "Ethereum"),
        (56, "BSC"),
        (137, "Polygon"),
    ]

    results = await asyncio.gather(*[
        loop.run_in_executor(None, _test_chain, cid, name)
        for cid, name in test_chains
    ])

    key_len = len(ETHERSCAN_KEY)
    key_preview = (f"{ETHERSCAN_KEY[:6]}...{ETHERSCAN_KEY[-4:]}"
                   if key_len > 10 else "(short)")
    has_whitespace = ETHERSCAN_KEY != ETHERSCAN_KEY.strip()

    lines = [
        "🔬 *Etherscan V2 Diagnostic*",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🔑 Key length: `{key_len}` chars",
        f"🔑 Preview: `{key_preview}`",
    ]
    if has_whitespace:
        lines.append("⚠️ *تحذير*: الـ key فيه whitespace!")
    lines.append("")
    lines.append(f"🌐 URL: `{ETHERSCAN_BASE}`")
    lines.append("")

    for r in results:
        icon = "✅" if r["ok"] else "❌"
        lines.append(f"{icon} *{r['chain']}* (chainid={r['chainid']})")
        lines.append(f"   Status: `{r['status']}`")
        body_clean = r["body"][:100].replace("`", "'")
        lines.append(f"   Body: `{body_clean}`")
        lines.append("")

    # Recommendation
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    ok_count = sum(1 for r in results if r["ok"])
    if ok_count == 3:
        lines.append("✅ *النتيجة*: Etherscan V2 يعمل بشكل ممتاز على جميع الـ EVM chains.")
    elif ok_count >= 1:
        lines.append(f"⚠️ *النتيجة*: {ok_count}/3 شبكات تعمل. الباقي قد يكون rate-limited.")
    else:
        statuses = [r["status"] for r in results]
        if "401" in statuses or "403" in statuses:
            lines.append("🔐 *النتيجة*: مشكلة auth — تحقق من ETHERSCAN_KEY.")
        elif "429" in statuses:
            lines.append("⏱ *النتيجة*: rate limit — انتظر دقيقة.")
        else:
            lines.append("❓ *النتيجة*: غير واضح. أرسل screenshot لي.")

    await msg.delete()
    await u.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_scan(u: Update, c: ContextTypes.DEFAULT_TYPE):
    """v4.0: Manual scan for a specific coin → full analysis with all 6 sources + AI."""
    args = c.args
    if not args:
        await u.message.reply_text(
            "*Usage:* `/scan SYMBOL`\n\n"
            "أمثلة:\n"
            "`/scan BTC`\n"
            "`/scan HYPE`\n"
            "`/scan RENDER`\n\n"
            "_فحص شامل بـ 6 مصادر + AI + portfolio_",
            parse_mode="Markdown"
        )
        return

    sym = args[0].upper()
    msg = await u.message.reply_text(
        f"⏳ *فحص شامل لـ {sym}...*\n"
        "💧 DexScreener → 🦙 DefiLlama → 🐋 Binance\n"
        "📊 CoinPaprika → 💎 Massive → 🤖 AI",
        parse_mode="Markdown"
    )

    try:
        loop = asyncio.get_event_loop()

        # Fetch all 6 sources in parallel
        ds_data      = await loop.run_in_executor(None, fetch_dexscreener_data)
        llama_task   = loop.run_in_executor(None, fetch_defillama_data)
        es_task      = loop.run_in_executor(None, fetch_etherscan_data, ds_data)
        bin_task     = loop.run_in_executor(None, fetch_binance_data)
        cp_task      = loop.run_in_executor(None, fetch_coinpaprika_data)
        massive_task = loop.run_in_executor(None, fetch_massive_data)

        llama_data, es_data, bin_data, cp_data, massive_data = await asyncio.gather(
            llama_task, es_task, bin_task, cp_task, massive_task
        )

        aggregated = aggregate_hype_signals(
            ds_data, llama_data, es_data, bin_data, cp_data, massive_data
        )

        # Find the requested symbol
        target = None
        for item in aggregated:
            if item["symbol"] == sym:
                target = item
                break

        if not target:
            await msg.delete()
            await u.message.reply_text(
                f"❌ *لا توجد بيانات كافية لـ {sym}*\n\n"
                f"الأسباب المحتملة:\n"
                f"• العملة غير موجودة في أي مصدر\n"
                f"• Score أقل من 30 (لا يستحق التتبع)\n"
                f"• الرمز غير صحيح",
                parse_mode="Markdown"
            )
            return

        # ── v5.0: Run AI Council with progress updates ──
        score = target.get("score", 0)
        tier = determine_ai_tier(score)

        # For manual /scan, force at least Gemini analysis (even if score <75)
        # so user always gets an AI verdict on demand
        if score < 75 and GEMINI_API_KEY:
            try:
                await msg.edit_text(
                    f"⏳ *فحص شامل لـ {sym}* (score={score})\n"
                    "🟢 Gemini يحلّل الجودة...",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            try:
                gem = await loop.run_in_executor(None, gemini_analyze_hype, target)
                if gem:
                    target["ai"] = gem
                    target["ai_tier"] = "tier_quality_manual"
            except Exception as e:
                log.warning(f"[SCAN-AI] Gemini {sym}: {e}")

        elif tier == "tier_quality":
            try:
                await msg.edit_text(
                    f"⏳ *فحص شامل لـ {sym}*\n"
                    "🟢 Gemini يحلّل الجودة...",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            target = await loop.run_in_executor(None, run_ai_council, target)

        elif tier == "tier_strategy":
            try:
                await msg.edit_text(
                    f"⏳ *فحص شامل لـ {sym}*\n"
                    "🟢 Gemini → 🟣 Claude يحلل...",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            target = await loop.run_in_executor(None, run_ai_council, target)

        elif tier == "tier_council":
            try:
                await msg.edit_text(
                    f"⏳ *فحص شامل لـ {sym}* 👑\n"
                    "🟢 Gemini → 🟣 Claude → 🔵 GPT-4o\n"
                    "_قد يستغرق 15-30 ثانية_",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            target = await loop.run_in_executor(None, run_ai_council, target)

        # Add portfolio info
        portfolio_pos = get_portfolio_position(sym)
        if portfolio_pos:
            target["portfolio"] = portfolio_pos

        # Format and send
        formatted = format_alert(target, "manual")
        buttons = build_alert_buttons(target)

        await msg.delete()
        await u.message.reply_text(
            formatted,
            parse_mode="Markdown",
            reply_markup=buttons,
            disable_web_page_preview=True,
        )

    except Exception as e:
        log.exception(f"[SCAN] {sym}: {e}")
        try:
            await msg.delete()
        except Exception:
            pass
        await u.message.reply_text(
            f"⚠️ *خطأ في الفحص:* `{str(e)[:80]}`",
            parse_mode="Markdown"
        )


async def cmd_movers(u: Update, c: ContextTypes.DEFAULT_TYPE):
    """v4.0: Show top crypto gainers from Massive."""
    if not POLYGON_API_KEY:
        await u.message.reply_text(
            "⚠️ *Massive غير مفعّل*\n\n"
            "أضف `POLYGON_API_KEY` في Railway لتفعيل هذه الميزة.",
            parse_mode="Markdown"
        )
        return

    msg = await u.message.reply_text("⏳ جاري جلب Top Movers...")

    try:
        loop = asyncio.get_event_loop()
        movers = await loop.run_in_executor(None, massive_get_top_movers, 10)

        if not movers:
            await msg.delete()
            await u.message.reply_text(
                "⚠️ *لا توجد بيانات حالياً*\n\nحاول مرة أخرى بعد دقيقة.",
                parse_mode="Markdown"
            )
            return

        lines = ["📈 *Top Crypto Gainers*",
                 f"🕐 {now_iso()[:16].replace('T', ' ')}",
                 "💎 _Massive cross-exchange data_",
                 "━━━━━━━━━━━━━━━━━━━━",
                 ""]

        for i, m in enumerate(movers, 1):
            sym = m["symbol"]
            change = m["change_pct"]
            price = m["price"]

            if price >= 100:
                p_str = f"${price:,.2f}"
            elif price >= 1:
                p_str = f"${price:.4f}"
            else:
                p_str = f"${price:.6f}"

            sign = "+" if change >= 0 else ""
            arrow = "🟢" if change >= 0 else "🔴"
            lines.append(f"{i}. *{sym}* — `{p_str}` {arrow} `{sign}{change:.2f}%`")

        lines.append("")
        lines.append("💡 _استخدم `/scan SYMBOL` للتحليل الكامل_")

        await msg.delete()
        await u.message.reply_text(
            "\n".join(lines),
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )

    except Exception as e:
        log.exception(f"[MOVERS] {e}")
        try:
            await msg.delete()
        except Exception:
            pass
        await u.message.reply_text(f"⚠️ خطأ: `{str(e)[:80]}`",
                                   parse_mode="Markdown")


async def handle_msg(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not u.message or not u.message.text:
        return

    text    = u.message.text.strip()
    text_l  = text.lower()
    chat_id = u.effective_chat.id

    # ── تفعيل ──
    if text.startswith("هايب") or text_l in ("hype", "start hype"):
        mode = "عادي"
        if "متوازن" in text or "balance" in text_l:
            mode = "متوازن"
        elif "جودة" in text or "quality" in text_l:
            mode = "جودة"
        elif "ذهبي" in text or "gold" in text_l:
            mode = "ذهبي"

        cfg = MODES[mode]
        chat_config[chat_id] = {
            "active": True, "mode": mode, "min_score": cfg["min"],
        }

        for j in c.job_queue.get_jobs_by_name(f"hype_{chat_id}"):
            j.schedule_removal()

        c.job_queue.run_repeating(
            scanner_job,
            interval=SCAN_INTERVAL_SEC,
            first=10,
            data={"chat_id": chat_id},
            name=f"hype_{chat_id}",
        )

        sources_info = ("5/5 مصادر (EVM) أو 4/5 (non-EVM)"
                        if ETHERSCAN_KEY else "4/5 مصادر (Etherscan معطّل)")

        await u.message.reply_text(
            f"🚨 *تم تفعيل كاشف الهايب*\n\n"
            f"⚙️ الوضع: {cfg['label']}\n"
            f"🎯 الحد الأدنى: `{cfg['min']}/100`\n"
            f"📊 الحد الأدنى للمصادر: `{cfg['min_sources']}`\n"
            f"📡 المصادر: `{sources_info}`\n"
            f"⏱ المسح: كل {SCAN_INTERVAL_SEC // 60} دقائق\n"
            f"❄️ Cooldown: ساعة لكل عملة\n\n"
            f"⚠️ تنفيذ يدوي — تعليمي فقط\n"
            f"للإيقاف: `وقف`",
            parse_mode="Markdown"
        )
        return

    # ── إيقاف ──
    if text_l in ("وقف", "ايقاف", "إيقاف", "stop"):
        chat_config[chat_id] = {"active": False, "mode": "عادي", "min_score": 65}
        for j in c.job_queue.get_jobs_by_name(f"hype_{chat_id}"):
            j.schedule_removal()
        await u.message.reply_text("⛔ *تم إيقاف كاشف الهايب*", parse_mode="Markdown")
        return

    # ── حالة ──
    if text_l in ("حالة", "status"):
        s = source_status
        lines = ["📡 *حالة المصادر الـ5:*\n"]

        sources_order = [
            ("💧 DexScreener", "dexscreener"),
            ("🦙 DefiLlama",   "defillama"),
            ("🔍 Etherscan",   "etherscan"),
            ("🐋 Binance",     "binance"),
            ("📊 CoinPaprika", "coinpaprika"),
        ]

        for name, key in sources_order:
            info = s[key]
            icon = "✅" if info.get("ok") else "❌"
            cnt = info.get("count", 0)
            last = info.get("last_check", "—")
            if last and last != "—":
                try:
                    dt = datetime.fromisoformat(last)
                    last = dt.strftime("%H:%M:%S")
                except Exception:
                    pass
            lines.append(f"{icon} *{name}*: {cnt} عنصر | {last}")
            err = info.get("error")
            if err and not info.get("ok"):
                lines.append(f"   _{str(err)[:80]}_")

        cfg = chat_config.get(chat_id, {})
        lines.append("")
        if cfg.get("active"):
            lines.append(
                f"🟢 الكاشف نشط — وضع: *{cfg.get('mode', 'عادي')}* "
                f"(≥{cfg.get('min_score', 65)})"
            )
        else:
            lines.append("⚪ الكاشف متوقف")

        active_cooldowns = sum(1 for sym in seen_coins if is_in_cooldown(sym))
        lines.append(f"❄️ عملات في cooldown: {active_cooldowns}")

        # Show weights summary
        lines.append("")
        lines.append("⚖️ *الأوزان النشطة:*")
        if ETHERSCAN_KEY:
            lines.append(f"EVM: 💧35% 🦙20% 🔍20% 🐋15% 📊10%")
            lines.append(f"non-EVM: 💧45% 🦙25% 🔍0% 🐋18% 📊12%")
        else:
            lines.append(f"الكل: 💧45% 🦙25% 🔍0% 🐋18% 📊12% (Etherscan معطّل)")

        await u.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    # ── نتائج ──
    if text_l in ("نتائج", "results"):
        if not last_results:
            await u.message.reply_text(
                "⚪ لا توجد نتائج بعد.\nفعّل الكشف بـ: `هايب`",
                parse_mode="Markdown"
            )
            return
        lines = [f"📊 *آخر مسح ({len(last_results)} إشارة):*\n"]
        for i, item in enumerate(last_results[:10], 1):
            grade = _grade_label(item["score"])
            evm_tag = "🟢 EVM" if item.get("is_evm") else "🔵 non-EVM"
            lines.append(
                f"{i}. *{item['symbol']}* `{item['score']}/100` "
                f"({item['sources_count']}/5) {grade} {evm_tag}"
            )
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    # ── top10 ──
    if text_l in ("top10", "top 10", "أفضل 10", "أعلى 10"):
        if not last_results:
            await u.message.reply_text(
                "⚪ لا توجد نتائج بعد.\nفعّل الكشف بـ: `هايب`",
                parse_mode="Markdown"
            )
            return
        lines = ["🏆 *أعلى 10 عملات هايب:*\n"]
        for i, item in enumerate(last_results[:10], 1):
            bk = item["breakdown"]
            evm_tag = "🟢" if item.get("is_evm") else "🔵"
            lines.append(f"{i}. {evm_tag} *{item['symbol']}* `{item['score']}/100`")
            lines.append(
                f"   💧{bk['dexscreener']:.0f} 🦙{bk['defillama']:.0f} "
                f"🔍{bk['etherscan']:.0f} 🐋{bk['binance']:.0f} "
                f"📊{bk['coinpaprika']:.0f}"
            )
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    # ── سجل ──
    if text_l in ("سجل", "history"):
        if not alert_history:
            await u.message.reply_text("⚪ لم تُرسل أي تنبيهات بعد.")
            return
        lines = [f"📜 *آخر التنبيهات ({len(alert_history)}):*\n"]
        for h in alert_history[-10:][::-1]:
            try:
                dt = datetime.fromisoformat(h["ts"])
                t = dt.strftime("%H:%M")
            except Exception:
                t = "—"
            evm_tag = "🟢" if h.get("is_evm") else "🔵"
            lines.append(f"• `{t}` {evm_tag} *{h['symbol']}* {h['score']}/100 ({h['mode']})")
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    await u.message.reply_text(
        "🤖 لم أفهم الأمر.\n\nأرسل `/start` لرؤية القائمة الكاملة.",
        parse_mode="Markdown"
    )


async def error_handler(update, context):
    log.warning(f"[ERR] {context.error}")
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text("⚠️ خطأ مؤقت. حاول مرة أخرى.")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════
# 11. MAIN
# ══════════════════════════════════════════════════════════════════

async def _post_init(app):
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        log.info("✅ Webhook cleared")
    except Exception as e:
        log.warning(f"webhook clear failed: {e}")


def _print_banner():
    es_status = "✅" if ETHERSCAN_KEY else "⚪"
    massive_status = "✅" if POLYGON_API_KEY else "⚪"
    gem_status = "✅" if GEMINI_API_KEY else "⚪"
    cl_status = "✅" if CLAUDE_API_KEY else "⚪"
    oa_status = "✅" if OPENAI_API_KEY else "⚪"
    portfolio_status = ("✅" if os.path.exists(
        os.path.join(DCA_DATA_DIR, "portfolio_latest.json")) else "⚪")

    print("=" * 70)
    print("  🔥 HYPE_BOT v5.0 — Specialized AI Council ✅")
    print("=" * 70)
    print(f"  المصادر (6) — chain-aware:")
    print(f"    💧 DexScreener  : ✅ (30% EVM / 40% non-EVM)")
    print(f"    🦙 DefiLlama    : ✅ (18% EVM / 22% non-EVM)")
    print(f"    🔍 Etherscan V2 : {es_status} (18% EVM / 0% non-EVM)")
    print(f"    🐋 Binance Fut. : ✅ (12% EVM / 15% non-EVM)")
    print(f"    📊 CoinPaprika  : ✅ (7%  EVM / 8%  non-EVM)")
    print(f"    💎 Massive      : {massive_status} (15% all chains)")
    print(f"  🤝 AI Council (specialized):")
    print(f"    🟢 Gemini       : {gem_status} Quality Detector  (score ≥75)")
    print(f"    🟣 Claude       : {cl_status} Wintermute Strategist (score ≥85)")
    print(f"    🔵 GPT-4o       : {oa_status} Trade Executor    (score ≥92)")
    print(f"  Portfolio:")
    print(f"    💼 DCA link     : {portfolio_status}  ({DCA_DATA_DIR}/portfolio_latest.json)")
    print(f"  EVM chains      : ETH, BSC, Polygon, Arbitrum, Optimism,")
    print(f"                    Base, Avalanche, Fantom, Linea, Blast")
    print(f"  الأوضاع         : 4 (65 / 75 / 85 / 92)")
    print(f"  المسح           : كل {SCAN_INTERVAL_SEC // 60} دقائق")
    print(f"  Cooldown        : ساعة لكل عملة")
    print(f"  Min Liquidity   : ${MIN_LIQUIDITY_USD:,}")
    print("=" * 70)
    print("  أرسل /start في تيليقرام لبدء الاستخدام")
    print("=" * 70)


def main():
    if not BOT_TOKEN:
        print("=" * 70)
        print("  ❌ ERROR: BOT_TOKEN غير موجود في environment")
        print("  أضفه في Railway → Variables → BOT_TOKEN")
        print("=" * 70)
        return

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(_post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("test", cmd_test))
    app.add_handler(CommandHandler("esdebug", cmd_esdebug))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("movers", cmd_movers))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_msg
    ))
    app.add_error_handler(error_handler)

    _print_banner()

    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
