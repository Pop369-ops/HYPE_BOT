"""
╔═══════════════════════════════════════════════════════════════════╗
║                       HYPE_BOT v2.0                              ║
║       كاشف الهايب — Whale-Style Multi-Source Scanner             ║
║                                                                   ║
║  5 مصادر مدمجة بأوزان احترافية ديناميكية:                       ║
║    💧 DexScreener  — 40% (50% بدون LC)  on-chain volume         ║
║    🦙 DefiLlama    — 20% (25% بدون LC)  TVL change              ║
║    🌌 LunarCrush   — 20% (اختياري)       Galaxy Score           ║
║    🐋 Binance Fut. — 12% (15% بدون LC)  OI + price action       ║
║    📊 CoinPaprika  —  8% (10% بدون LC)  top gainers             ║
║                                                                   ║
║  4 أوضاع كشف بمنطق الحيتان (high-conviction only):              ║
║    🟢 هايب          ≥65  filter retail noise                    ║
║    ⚖️ هايب متوازن    ≥75  whale watchlist                       ║
║    💎 هايب جودة      ≥85  whale entry zone                      ║
║    👑 هايب ذهبي      ≥92  sniper signals                        ║
║                                                                   ║
║  100% مجاني (LunarCrush اختياري)                                 ║
║  للأغراض التعليمية فقط — ليس نصيحة مالية                        ║
╚═══════════════════════════════════════════════════════════════════╝
"""

import os
import time
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from collections import defaultdict

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
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

# ── API Keys (only BOT_TOKEN required, LunarCrush optional) ──
BOT_TOKEN        = os.environ.get("BOT_TOKEN", "").strip()
LUNARCRUSH_KEY   = os.environ.get("LUNARCRUSH_KEY", "").strip()

# ── Endpoints (all free, no auth needed except LC) ──
DS_BASE   = "https://api.dexscreener.com"
LLAMA_BASE = "https://api.llama.fi"
BIN_FAPI  = "https://fapi.binance.com/fapi/v1"
CP_BASE   = "https://api.coinpaprika.com/v1"
LC_BASE   = "https://lunarcrush.com/api4/public"

# ── Source Weights (dynamic, computed at runtime) ──
# Base weights when LunarCrush IS available (5-source mode):
W_5SRC = {
    "dexscreener": 0.40,
    "defillama":   0.20,
    "lunarcrush":  0.20,
    "binance":     0.12,
    "coinpaprika": 0.08,
}

# Fallback weights when LunarCrush IS NOT available (4-source mode):
W_4SRC = {
    "dexscreener": 0.50,
    "defillama":   0.25,
    "lunarcrush":  0.00,    # disabled
    "binance":     0.15,
    "coinpaprika": 0.10,
}

def get_weights() -> Dict[str, float]:
    """Return active weights based on LC key availability."""
    return W_5SRC if LUNARCRUSH_KEY else W_4SRC


# ── Mode Thresholds (whale-style, conviction-based) ──
MODES = {
    "عادي":    {"min": 65, "min_sources": 2, "label": "🟢 عادي",   "min_per_source": 0},
    "متوازن":  {"min": 75, "min_sources": 3, "label": "⚖️ متوازن", "min_per_source": 50},
    "جودة":    {"min": 85, "min_sources": 3, "label": "💎 جودة",   "min_per_source": 60},
    "ذهبي":    {"min": 92, "min_sources": 4, "label": "👑 ذهبي",   "min_per_source": 70},
}

# ── Operational Constants ──
SCAN_INTERVAL_SEC = 300                  # full scan cycle every 5 minutes
COOLDOWN_HOURS    = 1                    # 1 hour per coin (user pref)
MAX_RESULTS_KEPT  = 50
MIN_LIQUIDITY_USD = 100_000              # DEX rug filter
MIN_BINANCE_VOL   = 500_000              # min 24h quote volume

# ── Blacklist (stablecoins + wrapped + obvious junk) ──
BLACKLIST = {
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDD", "USDP",
    "WBTC", "WETH", "STETH", "WSTETH", "WBNB", "WMATIC", "USDE",
    "GUSD", "PYUSD", "FRAX", "SUSDS", "SUSDE", "USDS", "RLUSD",
    "USD0", "USDX", "EURS", "EURT",
}

# ── Timezone ──
TZ_RIYADH = timezone(timedelta(hours=3))


# ══════════════════════════════════════════════════════════════════
# 2. GLOBAL STATE
# ══════════════════════════════════════════════════════════════════

# {chat_id: {"active": bool, "mode": str, "min_score": int}}
chat_config: Dict[int, Dict[str, Any]] = {}

# {symbol: timestamp_iso} — cooldown tracker
seen_coins: Dict[str, str] = {}

# Last scan results
last_results: List[Dict[str, Any]] = []

# Source health status (5 sources now)
source_status: Dict[str, Dict[str, Any]] = {
    "dexscreener": {"ok": False, "last_check": None, "error": None, "count": 0},
    "defillama":   {"ok": False, "last_check": None, "error": None, "count": 0},
    "lunarcrush":  {"ok": False, "last_check": None, "error": None, "count": 0},
    "binance":     {"ok": False, "last_check": None, "error": None, "count": 0},
    "coinpaprika": {"ok": False, "last_check": None, "error": None, "count": 0},
}

# Alert history (last 100)
alert_history: List[Dict[str, Any]] = []


# ══════════════════════════════════════════════════════════════════
# 3. HTTP HELPER
# ══════════════════════════════════════════════════════════════════

_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; HypeBot/2.0)",
    "Accept": "application/json",
})


def safe_get(url: str, params: Optional[dict] = None,
             headers: Optional[dict] = None,
             timeout: tuple = (5, 20),
             retries: int = 2) -> Optional[Any]:
    """طلب آمن مع إعادة المحاولة وحماية من rate limits."""
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
            elif r.status_code in (401, 403):
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


def now_str() -> str:
    return datetime.now(TZ_RIYADH).strftime("%H:%M:%S")


def normalize_sym(s: str) -> str:
    """Strip USDT/BUSD suffix and uppercase."""
    s = (s or "").upper().strip()
    for suffix in ("USDT", "BUSD", "USDC", "USD"):
        if s.endswith(suffix) and len(s) > len(suffix):
            return s[:-len(suffix)]
    return s


# ══════════════════════════════════════════════════════════════════
# 4. SOURCE FETCHERS (5 sources, all returning {SYM_UPPER: data_dict})
# ══════════════════════════════════════════════════════════════════

# ── ① DexScreener: Boosted tokens + volume surge ──
def fetch_dexscreener_data() -> Dict[str, Dict]:
    """
    1) GET top boosted tokens (proxy for paid attention)
    2) For each, fetch full pair data with volumes/liquidity/price-change
    Returns: {symbol_upper: {volume metrics, liquidity, price_change, ...}}
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

        # Pick highest-liquidity pair
        best = max(pairs, key=lambda p: float(
            (p.get("liquidity") or {}).get("usd") or 0
        ))

        base_token = best.get("baseToken", {}) or {}
        sym = (base_token.get("symbol") or "").upper()
        if not sym or sym in BLACKLIST:
            continue

        liquidity = float((best.get("liquidity") or {}).get("usd") or 0)
        if liquidity < MIN_LIQUIDITY_USD:
            continue  # filter rugs

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
            "chain":             chain,
            "pair_url":          best.get("url", ""),
            "age_days":          age_days,
            "pair_address":      best.get("pairAddress", ""),
        }

    source_status["dexscreener"] = {
        "ok": True, "last_check": now_iso(), "error": None, "count": len(out),
    }
    log.info(f"[DS] {len(out)} tokens fetched")
    return out


# ── ② DefiLlama: TVL changes per protocol ──
def fetch_defillama_data() -> Dict[str, Dict]:
    """
    GET /protocols → all protocols with TVL + change_1h/1d/7d.
    Aggregate by symbol (multi-protocol tokens like UNI sum across protocols).
    Returns: {symbol_upper: {tvl, change_1d, change_7d, name, category, chains, ...}}
    """
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

    # Aggregate by symbol — take the highest-TVL protocol per symbol
    by_sym: Dict[str, Dict] = {}
    for p in data:
        sym = (p.get("symbol") or "").upper()
        if not sym or sym == "-" or sym in BLACKLIST:
            continue
        tvl = float(p.get("tvl") or 0)
        if tvl < 100_000:  # filter dust protocols
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
    log.info(f"[LLAMA] {len(by_sym)} protocols with TVL fetched")
    return by_sym


# ── ③ LunarCrush: Galaxy Score (optional, with key) ──
def fetch_lunarcrush_data() -> Dict[str, Dict]:
    """
    GET /coins/list/v2 → top 100 coins by Galaxy Score.
    Returns: {symbol_upper: {galaxy_score, alt_rank, sentiment, ...}}
    """
    if not LUNARCRUSH_KEY:
        source_status["lunarcrush"] = {
            "ok": False, "last_check": now_iso(),
            "error": "no API key (optional)", "count": 0,
        }
        return {}

    headers = {"Authorization": f"Bearer {LUNARCRUSH_KEY}"}
    data = safe_get(f"{LC_BASE}/coins/list/v2",
                    params={"limit": 100, "sort": "galaxy_score"},
                    headers=headers)

    if not data or "_auth_error" in (data or {}):
        source_status["lunarcrush"] = {
            "ok": False, "last_check": now_iso(),
            "error": data.get("_text", "auth/unreachable")[:80] if data else "unreachable",
            "count": 0,
        }
        return {}

    out = {}
    items = data.get("data", []) if isinstance(data, dict) else []
    for c in items:
        sym = (c.get("symbol") or "").upper()
        if not sym or sym in BLACKLIST:
            continue
        out[sym] = {
            "galaxy_score":      float(c.get("galaxy_score") or 0),
            "alt_rank":          int(c.get("alt_rank") or 9999),
            "social_volume_24h": float(c.get("interactions_24h") or 0),
            "social_dominance":  float(c.get("social_dominance") or 0),
            "sentiment":         float(c.get("sentiment") or 50),
            "price":             float(c.get("price") or 0),
            "percent_change_24h": float(c.get("percent_change_24h") or 0),
        }

    source_status["lunarcrush"] = {
        "ok": True, "last_check": now_iso(), "error": None, "count": len(out),
    }
    log.info(f"[LC] {len(out)} coins with Galaxy Score fetched")
    return out


# ── ④ Binance Futures: 24h ticker (price, volume, OI signal) ──
def fetch_binance_data() -> Dict[str, Dict]:
    """
    GET /fapi/v1/ticker/24hr → all USDT-perp tickers.
    Computes per-symbol: price_change %, volume rank, volume vs market median.
    Returns: {symbol_upper: {price_change_pct, quote_volume, volume_rank, ...}}
    """
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

    # Filter USDT pairs only
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

    # Sort by volume to compute rank
    usdt_pairs.sort(key=lambda x: x["quote_vol"], reverse=True)
    total = len(usdt_pairs)

    out = {}
    for rank, p in enumerate(usdt_pairs, 1):
        sym = p["symbol"]
        if not sym or sym in BLACKLIST:
            continue
        out[sym] = {
            "symbol_full":  p["symbol_full"],
            "price_change_pct": p["price_chg"],
            "quote_volume": p["quote_vol"],
            "last_price":   p["last_price"],
            "high":         p["high"],
            "low":          p["low"],
            "trades":       p["trades"],
            "volume_rank":  rank,
            "total_pairs":  total,
        }

    source_status["binance"] = {
        "ok": True, "last_check": now_iso(), "error": None, "count": len(out),
    }
    log.info(f"[BIN] {len(out)} USDT-perp pairs fetched")
    return out


# ── ⑤ CoinPaprika: Top gainers + global market data ──
def fetch_coinpaprika_data() -> Dict[str, Dict]:
    """
    GET /tickers → top 2000 coins by mcap with 24h % change.
    Sort to identify top gainers.
    Returns: {symbol_upper: {price, percent_change_24h, gainer_rank, mc_rank, ...}}
    """
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

    # Extract relevant fields
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
        if mc < 1_000_000:  # dust filter
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

    # Sort by 24h % change (descending) for gainer rank
    sorted_by_gain = sorted(coins, key=lambda x: x["pct_24h"], reverse=True)
    gainer_rank_map = {c["symbol"]: idx + 1 for idx, c in enumerate(sorted_by_gain)}

    out = {}
    for c in coins:
        out[c["symbol"]] = {
            "id":            c["id"],
            "name":          c["name"],
            "price":         c["price"],
            "percent_24h":   c["pct_24h"],
            "mcap":          c["mcap"],
            "volume_24h":    c["volume"],
            "mc_rank":       c["rank"],
            "gainer_rank":   gainer_rank_map.get(c["symbol"], 9999),
        }

    source_status["coinpaprika"] = {
        "ok": True, "last_check": now_iso(), "error": None, "count": len(out),
    }
    log.info(f"[CP] {len(out)} coins fetched (sorted by gain)")
    return out


# ══════════════════════════════════════════════════════════════════
# 5. SOURCE SCORERS (each → 0..100 raw)
# ══════════════════════════════════════════════════════════════════

def score_dexscreener(sym: str, ds_data: Dict[str, Dict]) -> float:
    """
    Whale signal: on-chain volume surge + liquidity quality + price-vol agreement.
    """
    info = ds_data.get(sym)
    if not info:
        return 0.0

    vol_change = info.get("vol_change_pct", 0)
    liquidity  = info.get("liquidity_usd", 0)
    price_h1   = info.get("price_change_h1", 0)
    price_h24  = info.get("price_change_h24", 0)
    boost      = info.get("boost_amount", 0)
    age_days   = info.get("age_days", 0)

    # Base: volume surge
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

    # Liquidity tier
    if liquidity >= 5_000_000:
        base += 3.0
    elif liquidity >= 1_000_000:
        base += 2.0
    elif liquidity < 250_000:
        base -= 5.0

    # Price-volume agreement
    if vol_change > 100 and price_h1 > 5:
        base += 5.0
    elif vol_change > 100 and price_h1 < -5:
        base -= 3.0

    if price_h24 > 20:
        base += 2.0

    # Boost amount
    if boost >= 500:
        base += 3.0
    elif boost >= 100:
        base += 1.5

    # Age penalty (rug risk)
    if age_days < 7:
        base -= 8.0
    elif age_days < 30:
        base -= 3.0

    return max(0.0, min(100.0, base))


def score_defillama(sym: str, llama_data: Dict[str, Dict]) -> float:
    """
    TVL change is the strongest institutional whale signal.
    Whales position via DeFi protocols — TVL inflow precedes price.
    """
    info = llama_data.get(sym)
    if not info:
        return 0.0

    tvl       = info.get("tvl", 0)
    chg_1d    = info.get("change_1d", 0)
    chg_7d    = info.get("change_7d", 0)
    mcap      = info.get("mcap", 0)

    # Base: TVL change 1d
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

    # 7d trend confirmation
    if chg_7d > 30:
        base += 5.0
    elif chg_7d > 15:
        base += 3.0
    elif chg_7d < -20:
        base -= 5.0

    # TVL tier (size matters for quality)
    if tvl >= 1_000_000_000:    # >$1B
        base += 5.0
    elif tvl >= 100_000_000:    # >$100M
        base += 3.0
    elif tvl >= 10_000_000:     # >$10M
        base += 1.0
    elif tvl < 1_000_000:       # <$1M = risky
        base -= 5.0

    return max(0.0, min(100.0, base))


def score_lunarcrush(sym: str, lc_data: Dict[str, Dict]) -> float:
    """Galaxy Score is a direct quality signal (when LC available)."""
    info = lc_data.get(sym)
    if not info:
        return 0.0

    galaxy = info.get("galaxy_score", 0)
    sentiment = info.get("sentiment", 50)
    social_dom = info.get("social_dominance", 0)
    alt_rank = info.get("alt_rank", 9999)

    score = galaxy

    if sentiment > 60:
        score += min(5.0, (sentiment - 60) / 8.0)
    elif sentiment < 40:
        score -= min(5.0, (40 - sentiment) / 8.0)

    if social_dom > 1.0:
        score += min(5.0, social_dom * 2.0)

    if alt_rank <= 50:
        score += 5.0
    elif alt_rank <= 100:
        score += 2.0

    return max(0.0, min(100.0, score))


def score_binance(sym: str, bin_data: Dict[str, Dict]) -> float:
    """
    Binance Futures whale positioning: 24h price % + volume rank.
    High volume + strong move = institutional flow.
    """
    info = bin_data.get(sym)
    if not info:
        return 0.0

    price_chg = info.get("price_change_pct", 0)
    qvol      = info.get("quote_volume", 0)
    vol_rank  = info.get("volume_rank", 9999)
    total     = info.get("total_pairs", 1)

    # Base: 24h % change (absolute value matters — both pumps and dumps are signals)
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

    # Volume rank tier (top 10% of pairs = whale interest)
    rank_pct = (vol_rank / total * 100) if total > 0 else 100
    if rank_pct <= 5:
        base += 8.0
    elif rank_pct <= 10:
        base += 5.0
    elif rank_pct <= 25:
        base += 2.0
    elif rank_pct > 75:
        base -= 5.0

    # Direction signal (positive change preferred for hype)
    if price_chg > 0:
        base += 2.0

    # Massive volume boost
    if qvol >= 500_000_000:    # >$500M = top tier
        base += 5.0
    elif qvol >= 100_000_000:  # >$100M
        base += 3.0

    return max(0.0, min(100.0, base))


def score_coinpaprika(sym: str, cp_data: Dict[str, Dict]) -> float:
    """
    CoinPaprika gainer rank: where does this coin sit in 24h gainers?
    Top-N gainers = retail attention building.
    """
    info = cp_data.get(sym)
    if not info:
        return 0.0

    pct_24h     = info.get("percent_24h", 0)
    gainer_rank = info.get("gainer_rank", 9999)
    mc_rank     = info.get("mc_rank", 9999)
    mcap        = info.get("mcap", 0)

    # Base: gainer rank
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

    # % change confirmation
    if pct_24h < 2:
        base *= 0.5  # gainer rank but tiny move = dead
    elif pct_24h > 30:
        base += 5.0

    # MC tier
    if mc_rank <= 50:
        base += 3.0
    elif mc_rank > 1000:
        base -= 3.0

    return max(0.0, min(100.0, base))


# ══════════════════════════════════════════════════════════════════
# 6. AGGREGATOR (with dynamic weights)
# ══════════════════════════════════════════════════════════════════

def aggregate_hype_signals(
    ds_data: Dict[str, Dict],
    llama_data: Dict[str, Dict],
    lc_data: Dict[str, Dict],
    bin_data: Dict[str, Dict],
    cp_data: Dict[str, Dict],
) -> List[Dict[str, Any]]:
    """
    Combine 5 sources with dynamic weights → ranked list.
    """
    weights = get_weights()

    # All unique symbols
    all_syms = set()
    all_syms.update(ds_data.keys())
    all_syms.update(llama_data.keys())
    all_syms.update(lc_data.keys())
    all_syms.update(bin_data.keys())
    all_syms.update(cp_data.keys())

    results = []
    for sym in all_syms:
        s_ds    = score_dexscreener(sym, ds_data)
        s_llama = score_defillama(sym, llama_data)
        s_lc    = score_lunarcrush(sym, lc_data)
        s_bin   = score_binance(sym, bin_data)
        s_cp    = score_coinpaprika(sym, cp_data)

        # Count meaningful sources (≥30 pts)
        all_scores = [s_ds, s_llama, s_lc, s_bin, s_cp]
        sources_count = sum(1 for s in all_scores if s >= 30)

        # Weighted unified score
        unified = (
            s_ds    * weights["dexscreener"] +
            s_llama * weights["defillama"] +
            s_lc    * weights["lunarcrush"] +
            s_bin   * weights["binance"] +
            s_cp    * weights["coinpaprika"]
        )

        if unified < 30:
            continue

        results.append({
            "symbol":         sym,
            "score":          round(unified, 1),
            "sources_count":  sources_count,
            "breakdown": {
                "dexscreener": round(s_ds, 1),
                "defillama":   round(s_llama, 1),
                "lunarcrush":  round(s_lc, 1),
                "binance":     round(s_bin, 1),
                "coinpaprika": round(s_cp, 1),
            },
            "ds_info":    ds_data.get(sym, {}),
            "llama_info": llama_data.get(sym, {}),
            "lc_info":    lc_data.get(sym, {}),
            "bin_info":   bin_data.get(sym, {}),
            "cp_info":    cp_data.get(sym, {}),
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ══════════════════════════════════════════════════════════════════
# 7. FILTERS
# ══════════════════════════════════════════════════════════════════

def passes_mode_filter(item: Dict[str, Any], mode: str) -> tuple:
    cfg = MODES.get(mode, MODES["عادي"])

    if item["score"] < cfg["min"]:
        return False, f"score {item['score']} < {cfg['min']}"

    if item["sources_count"] < cfg["min_sources"]:
        return False, f"sources {item['sources_count']}/{cfg['min_sources']}"

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


def format_alert(item: Dict[str, Any], mode: str) -> str:
    """Build Arabic alert in Markdown."""
    sym       = item["symbol"]
    score     = item["score"]
    sources   = item["sources_count"]
    bk        = item["breakdown"]
    ds        = item["ds_info"]
    llama     = item["llama_info"]
    lc        = item["lc_info"]
    bin_i     = item["bin_info"]
    cp        = item["cp_info"]

    weights = get_weights()
    grade = _grade_label(score)
    has_lc = bool(LUNARCRUSH_KEY)

    lines = []
    lines.append(f"🔥 *إشارة HYPE* — `{sym}`")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🎯 السكور الموحّد: *{score}/100* {grade}")
    total_sources = 5 if has_lc else 4
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
            chain = ds.get("chain", "?")
            lines.append(
                f"   💧 Vol +{vc:.0f}% | Liq ${liq/1000:.0f}K | "
                f"H1: {ph1:+.1f}% | {chain}"
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

    # ③ LunarCrush (only if available)
    if has_lc and bk["lunarcrush"] > 0:
        w_pct = int(weights["lunarcrush"] * 100)
        lines.append(
            f"{_src_emoji(bk['lunarcrush'])} LunarCrush: `{bk['lunarcrush']}/100` (وزن {w_pct}%)"
        )
        if lc:
            galaxy = lc.get("galaxy_score", 0)
            altrnk = lc.get("alt_rank", 0)
            sent = lc.get("sentiment", 0)
            lines.append(
                f"   🌌 Galaxy: {galaxy:.0f} | AltRank #{altrnk} | "
                f"Sentiment: {sent:.0f}/100"
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

    # Price summary (best source available)
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

    # Whale insight
    if score >= 92:
        lines.append("🎯 *تحليل وول ستريت:* 4+ مصادر متفقة بقوة. نمط صفقة قنّاصة — "
                    "الحيتان تتموضع. تحقّق يدوي قبل الدخول.")
    elif score >= 85:
        lines.append("🎯 *تحليل وول ستريت:* منطقة دخول الحيتان. on-chain volume يدعم.")
    elif score >= 75:
        lines.append("🎯 *تحليل وول ستريت:* watchlist للمتداولين الكبار — مراقبة لا دخول.")
    else:
        lines.append("🎯 *تحليل وول ستريت:* إشارة عادية. retail-friendly.")

    lines.append("")
    lines.append("⚠️ _تنفيذ يدوي — تعليمي فقط، ليس نصيحة مالية._")

    return "\n".join(lines)


def build_alert_buttons(item: Dict[str, Any]) -> Optional[InlineKeyboardMarkup]:
    """Inline buttons for chart links (5 sources)."""
    sym = item["symbol"]
    ds  = item.get("ds_info", {})
    llama = item.get("llama_info", {})
    bin_i = item.get("bin_info", {})
    cp = item.get("cp_info", {})

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

    # Row 2: Research
    btns2 = []
    if llama and llama.get("url"):
        btns2.append(InlineKeyboardButton("🦙 DefiLlama", url=llama["url"]))
    if cp and cp.get("id"):
        btns2.append(InlineKeyboardButton(
            "📊 CoinPaprika", url=f"https://coinpaprika.com/coin/{cp['id']}/"
        ))
    if btns2:
        rows.append(btns2)

    # Row 3: LunarCrush (if available)
    if LUNARCRUSH_KEY:
        rows.append([InlineKeyboardButton(
            "🌌 LunarCrush", url=f"https://lunarcrush.com/coins/{sym.lower()}"
        )])

    return InlineKeyboardMarkup(rows) if rows else None


# ══════════════════════════════════════════════════════════════════
# 9. SCANNER JOB
# ══════════════════════════════════════════════════════════════════

async def scanner_job(context: ContextTypes.DEFAULT_TYPE):
    """Main periodic scanner: 5 sources → aggregate → filter → alert."""
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
        ds_data    = await loop.run_in_executor(None, fetch_dexscreener_data)
        llama_data = await loop.run_in_executor(None, fetch_defillama_data)
        lc_data    = await loop.run_in_executor(None, fetch_lunarcrush_data)
        bin_data   = await loop.run_in_executor(None, fetch_binance_data)
        cp_data    = await loop.run_in_executor(None, fetch_coinpaprika_data)

        aggregated = aggregate_hype_signals(
            ds_data, llama_data, lc_data, bin_data, cp_data
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

def _build_start_msg() -> str:
    """Build /start message with current weights based on LC availability."""
    w = get_weights()
    lc_line = ""
    if LUNARCRUSH_KEY:
        lc_line = f"🌌 LunarCrush    `{int(w['lunarcrush']*100)}%`  Galaxy Score\n"
    else:
        lc_line = "🌌 LunarCrush    `معطّل`  (لا يوجد مفتاح)\n"

    return (
        "🔥 *HYPE\\_BOT v2\\.0* — Whale\\-Style Multi\\-Source Scanner\n\n"
        "أكشف العملات اللي عليها هايب من 5 مصادر مدمجة\\.\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "*المصادر \\& الأوزان:*\n"
        f"💧 DexScreener   `{int(w['dexscreener']*100)}%`  on\\-chain volume\n"
        f"🦙 DefiLlama     `{int(w['defillama']*100)}%`  TVL change\n"
        + lc_line.replace("%", "\\%").replace("(", "\\(").replace(")", "\\)").replace("-", "\\-").replace(".", "\\.").replace("`", "`") +
        f"🐋 Binance Fut\\.  `{int(w['binance']*100)}%`  OI \\+ price action\n"
        f"📊 CoinPaprika   `{int(w['coinpaprika']*100)}%`  top gainers\n\n"
        "*أوضاع الكشف \\(whale\\-style\\):*\n"
        "🟢 `هايب`           ≥65  عادي\n"
        "⚖️ `هايب متوازن`     ≥75  watchlist\n"
        "💎 `هايب جودة`       ≥85  دخول المحترفين\n"
        "👑 `هايب ذهبي`       ≥92  قنّاصة \\(نادر\\)\n\n"
        "*أوامر إضافية:*\n"
        "`/test`     فحص اتصال المصادر\n"
        "`حالة`      حالة المصادر الـ5\n"
        "`نتائج`     آخر 10 إشارات\n"
        "`top10`     أعلى 10 عملات هايب الآن\n"
        "`سجل`       سجل التنبيهات\n"
        "`وقف`       إيقاف الكشف\n\n"
        "⚠️ _تنفيذ يدوي — تعليمي فقط، ليس نصيحة مالية_"
    )


async def cmd_start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    # Use simpler Markdown to avoid escape issues
    w = get_weights()
    lc_line = (f"🌌 LunarCrush     `{int(w['lunarcrush']*100)}%`  Galaxy Score"
               if LUNARCRUSH_KEY else
               "🌌 LunarCrush     `معطّل`  (لا يوجد مفتاح)")

    msg = (
        "🔥 *HYPE_BOT v2.0* — Whale-Style Scanner\n\n"
        "كاشف الهايب من 5 مصادر مدمجة بأوزان احترافية.\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "*المصادر والأوزان:*\n"
        f"💧 DexScreener    `{int(w['dexscreener']*100)}%`  on-chain volume\n"
        f"🦙 DefiLlama      `{int(w['defillama']*100)}%`  TVL change\n"
        f"{lc_line}\n"
        f"🐋 Binance Fut.   `{int(w['binance']*100)}%`  OI + price\n"
        f"📊 CoinPaprika    `{int(w['coinpaprika']*100)}%`  top gainers\n\n"
        "*أوضاع الكشف:*\n"
        "🟢 `هايب`          ≥65  عادي\n"
        "⚖️ `هايب متوازن`    ≥75  watchlist\n"
        "💎 `هايب جودة`      ≥85  دخول المحترفين\n"
        "👑 `هايب ذهبي`      ≥92  قنّاصة (نادر)\n\n"
        "*أوامر إضافية:*\n"
        "`/test`     فحص اتصال المصادر\n"
        "`حالة`      حالة المصادر الـ5\n"
        "`نتائج`     آخر 10 إشارات\n"
        "`top10`     أعلى 10 عملات هايب\n"
        "`سجل`       سجل التنبيهات\n"
        "`وقف`       إيقاف الكشف\n\n"
        "⚠️ _تنفيذ يدوي — تعليمي فقط_"
    )
    await u.message.reply_text(msg, parse_mode="Markdown")


async def cmd_test(u: Update, c: ContextTypes.DEFAULT_TYPE):
    """Connectivity test for 5 sources."""
    msg = await u.message.reply_text("⏳ فحص المصادر الخمسة...")

    loop = asyncio.get_event_loop()
    ds    = await loop.run_in_executor(None, fetch_dexscreener_data)
    llama = await loop.run_in_executor(None, fetch_defillama_data)
    lc    = await loop.run_in_executor(None, fetch_lunarcrush_data)
    bin_d = await loop.run_in_executor(None, fetch_binance_data)
    cp    = await loop.run_in_executor(None, fetch_coinpaprika_data)

    s = source_status

    def line(name: str, key: str, count_label: str) -> str:
        info = s[key]
        icon = "✅" if info.get("ok") else "❌"
        cnt = info.get("count", 0)
        out = f"{icon} *{name}*: {cnt} {count_label}"
        err = info.get("error")
        if err and not info.get("ok"):
            out += f"\n   _{str(err)[:80]}_"
        return out

    lines = ["🔍 *نتيجة الفحص:*\n"]
    lines.append(line("DexScreener", "dexscreener", "رمز"))
    lines.append(line("DefiLlama",   "defillama",   "بروتوكول"))
    if LUNARCRUSH_KEY:
        lines.append(line("LunarCrush", "lunarcrush", "عملة"))
    else:
        lines.append("⚪ *LunarCrush*: معطّل (لا يوجد مفتاح)")
    lines.append(line("Binance",     "binance",     "زوج USDT"))
    lines.append(line("CoinPaprika", "coinpaprika", "عملة"))

    active_count = sum(1 for v in s.values() if v.get("ok"))
    expected = 5 if LUNARCRUSH_KEY else 4
    lines.append("")
    if active_count >= expected - 1:
        lines.append(f"🎯 *الحالة:* ممتازة ({active_count}/{expected})")
    elif active_count >= expected // 2:
        lines.append(f"⚠️ *الحالة:* مقبولة ({active_count}/{expected})")
    else:
        lines.append(f"🚨 *الحالة:* ضعيفة ({active_count}/{expected})")

    await msg.delete()
    await u.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_msg(u: Update, c: ContextTypes.DEFAULT_TYPE):
    """Main text-message router."""
    if not u.message or not u.message.text:
        return

    text    = u.message.text.strip()
    text_l  = text.lower()
    chat_id = u.effective_chat.id

    # ── تفعيل الكشف ──
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
            "active":    True,
            "mode":      mode,
            "min_score": cfg["min"],
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

        sources_active = "5/5 مصادر" if LUNARCRUSH_KEY else "4/5 مصادر (LC معطّل)"

        await u.message.reply_text(
            f"🚨 *تم تفعيل كاشف الهايب*\n\n"
            f"⚙️ الوضع: {cfg['label']}\n"
            f"🎯 الحد الأدنى: `{cfg['min']}/100`\n"
            f"📊 الحد الأدنى للمصادر: `{cfg['min_sources']}`\n"
            f"📡 المصادر النشطة: `{sources_active}`\n"
            f"⏱ المسح: كل {SCAN_INTERVAL_SEC // 60} دقائق\n"
            f"❄️ Cooldown: ساعة واحدة لكل عملة\n\n"
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

    # ── حالة المصادر ──
    if text_l in ("حالة", "status"):
        s = source_status
        lines = ["📡 *حالة المصادر الـ5:*\n"]

        sources_order = [
            ("💧 DexScreener", "dexscreener"),
            ("🦙 DefiLlama",   "defillama"),
            ("🌌 LunarCrush",  "lunarcrush"),
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

        # Weights summary
        w = get_weights()
        lines.append("")
        lines.append("⚖️ *الأوزان النشطة:*")
        lines.append(
            f"💧{int(w['dexscreener']*100)}% 🦙{int(w['defillama']*100)}% "
            f"🌌{int(w['lunarcrush']*100)}% 🐋{int(w['binance']*100)}% "
            f"📊{int(w['coinpaprika']*100)}%"
        )

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
            lines.append(
                f"{i}. *{item['symbol']}* `{item['score']}/100` "
                f"({item['sources_count']}/{5 if LUNARCRUSH_KEY else 4}) {grade}"
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
            lines.append(f"{i}. *{item['symbol']}* `{item['score']}/100`")
            lines.append(
                f"   💧{bk['dexscreener']:.0f} 🦙{bk['defillama']:.0f} "
                f"🌌{bk['lunarcrush']:.0f} 🐋{bk['binance']:.0f} "
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
            lines.append(f"• `{t}` *{h['symbol']}* {h['score']}/100 ({h['mode']})")
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    # ── unknown ──
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
# 11. POST INIT
# ══════════════════════════════════════════════════════════════════

async def _post_init(app):
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        log.info("✅ Webhook cleared")
    except Exception as e:
        log.warning(f"webhook clear failed: {e}")


# ══════════════════════════════════════════════════════════════════
# 12. MAIN
# ══════════════════════════════════════════════════════════════════

def _print_banner():
    w = get_weights()
    lc_status = (f"✅ مفعّل ({int(w['lunarcrush']*100)}%)"
                 if LUNARCRUSH_KEY else "⚪ معطّل (لا يوجد مفتاح)")

    print("=" * 70)
    print("  🔥 HYPE_BOT v2.0 — Running ✅")
    print("=" * 70)
    print(f"  المعمارية      : {'5 مصادر' if LUNARCRUSH_KEY else '4 مصادر'} (Whale-weighted)")
    print(f"    💧 DexScreener  : ✅ مجاني ({int(w['dexscreener']*100)}%)")
    print(f"    🦙 DefiLlama    : ✅ مجاني ({int(w['defillama']*100)}%)")
    print(f"    🌌 LunarCrush   : {lc_status}")
    print(f"    🐋 Binance Fut. : ✅ مجاني ({int(w['binance']*100)}%)")
    print(f"    📊 CoinPaprika  : ✅ مجاني ({int(w['coinpaprika']*100)}%)")
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
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_msg
    ))
    app.add_error_handler(error_handler)

    _print_banner()

    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
