"""
╔═══════════════════════════════════════════════════════════════════╗
║                       HYPE_BOT v1.0                              ║
║          كاشف الهايب — Whale-Style Signal Scanner                ║
║                                                                   ║
║  4 مصادر مدمجة بأوزان احترافية:                                 ║
║    💧 DexScreener  — 35%  (on-chain volume, hardest to fake)    ║
║    🌌 LunarCrush   — 30%  (Galaxy Score, social momentum)       ║
║    📰 CryptoPanic  — 20%  (news catalyst)                       ║
║    📈 CoinGecko    — 15%  (retail trending — confirmation)      ║
║                                                                   ║
║  4 أوضاع كشف بمنطق الحيتان (high-conviction only):              ║
║    🟢 هايب          ≥65  (filter retail noise)                  ║
║    ⚖️ هايب متوازن    ≥75  (whale watchlist)                     ║
║    💎 هايب جودة      ≥85  (whale entry zone)                    ║
║    👑 هايب ذهبي      ≥92  (sniper signals, 4/4 sources)        ║
║                                                                   ║
║  للأغراض التعليمية فقط — ليس نصيحة مالية                        ║
╚═══════════════════════════════════════════════════════════════════╝
"""

import os
import time
import asyncio
import logging
import json
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

# ── API Keys (from Railway Variables) ──
BOT_TOKEN        = os.environ.get("BOT_TOKEN", "").strip()
LUNARCRUSH_KEY   = os.environ.get("LUNARCRUSH_KEY", "").strip()
CRYPTOPANIC_KEY  = os.environ.get("CRYPTOPANIC_KEY", "").strip()
COINGECKO_KEY    = os.environ.get("COINGECKO_KEY", "").strip()

# ── Endpoints ──
CG_BASE   = "https://api.coingecko.com/api/v3"
LC_BASE   = "https://lunarcrush.com/api4/public"
DS_BASE   = "https://api.dexscreener.com"
CP_BASE   = "https://cryptopanic.com/api/v1"

# ── Source Weights (whale-style) ──
W_DEX     = 0.35
W_LC      = 0.30
W_CP      = 0.20
W_CG      = 0.15

# ── Mode Thresholds ──
MODES = {
    "عادي":    {"min": 65, "min_sources": 2, "label": "🟢 عادي",      "min_per_source": 0},
    "متوازن":  {"min": 75, "min_sources": 3, "label": "⚖️ متوازن",    "min_per_source": 50},
    "جودة":    {"min": 85, "min_sources": 3, "label": "💎 جودة",      "min_per_source": 60},
    "ذهبي":    {"min": 92, "min_sources": 4, "label": "👑 ذهبي",      "min_per_source": 70},
}

# ── Operational Constants ──
SCAN_INTERVAL_SEC = 300                  # دورة المسح الكاملة كل 5 دقائق
COOLDOWN_HOURS    = 1                    # ساعة لكل عملة (تعديل المستخدم)
MAX_RESULTS_KEPT  = 50                   # آخر 50 نتيجة في الذاكرة
MIN_LIQUIDITY_USD = 100_000              # سيولة DEX دنيا (anti-rug)
MAX_AGE_DAYS      = 365                  # العملات الجديدة جداً مستبعدة

# ── Blacklist (stablecoins + wrapped) ──
BLACKLIST = {
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDD", "USDP",
    "WBTC", "WETH", "STETH", "WSTETH", "WBNB", "WMATIC", "USDE",
    "GUSD", "PYUSD", "FRAX", "SUSDS",
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

# Last scan results (list of dicts)
last_results: List[Dict[str, Any]] = []

# Source health status
source_status: Dict[str, Dict[str, Any]] = {
    "coingecko":   {"ok": False, "last_check": None, "error": None},
    "lunarcrush":  {"ok": False, "last_check": None, "error": None},
    "dexscreener": {"ok": False, "last_check": None, "error": None},
    "cryptopanic": {"ok": False, "last_check": None, "error": None},
}

# Alert history (last 100)
alert_history: List[Dict[str, Any]] = []


# ══════════════════════════════════════════════════════════════════
# 3. HTTP HELPER
# ══════════════════════════════════════════════════════════════════

# Persistent session for connection pooling
_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; HypeBot/1.0)",
    "Accept": "application/json",
})


def safe_get(url: str, params: Optional[dict] = None,
             headers: Optional[dict] = None,
             timeout: tuple = (5, 20),
             retries: int = 2) -> Optional[Any]:
    """طلب آمن مع إعادة المحاولة."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            h = dict(_session.headers)
            if headers:
                h.update(headers)
            r = _session.get(url, params=params, headers=h, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429:  # rate limit — wait and retry
                last_err = f"429 rate limit"
                time.sleep(2 ** attempt)
                continue
            elif r.status_code in (401, 403):
                return {"_auth_error": r.status_code, "_text": r.text[:200]}
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


# ══════════════════════════════════════════════════════════════════
# 4. SOURCE FETCHERS (4 sources)
# ══════════════════════════════════════════════════════════════════

# ── ① CoinGecko Trending ──
def fetch_coingecko_trending() -> Dict[str, Dict]:
    """
    GET /search/trending → top 15 trending coins by 24h search volume.
    Returns: {symbol_upper: {rank, name, market_cap_rank, score}}
    """
    headers = {}
    if COINGECKO_KEY:
        headers["x-cg-demo-api-key"] = COINGECKO_KEY

    data = safe_get(f"{CG_BASE}/search/trending", headers=headers)
    if not data or "_auth_error" in (data or {}):
        source_status["coingecko"] = {
            "ok": False,
            "last_check": now_iso(),
            "error": data.get("_text", "unreachable") if data else "unreachable",
        }
        return {}

    out = {}
    coins = data.get("coins", [])
    for idx, entry in enumerate(coins[:15]):
        item = entry.get("item", {})
        sym = (item.get("symbol") or "").upper()
        if not sym or sym in BLACKLIST:
            continue
        out[sym] = {
            "rank": idx + 1,                              # 1..15
            "name": item.get("name", ""),
            "cg_id": item.get("id", ""),
            "market_cap_rank": item.get("market_cap_rank") or 9999,
            "thumb": item.get("thumb", ""),
            "score": item.get("score", 0),                # internal CG score
        }

    source_status["coingecko"] = {
        "ok": True, "last_check": now_iso(), "error": None
    }
    log.info(f"[CG] {len(out)} trending coins fetched")
    return out


# ── ② LunarCrush Galaxy Score ──
def fetch_lunarcrush_data() -> Dict[str, Dict]:
    """
    GET /coins/list/v2 → top coins with social metrics.
    Returns: {symbol_upper: {galaxy_score, alt_rank, social_volume, ...}}
    """
    if not LUNARCRUSH_KEY:
        source_status["lunarcrush"] = {
            "ok": False, "last_check": now_iso(),
            "error": "no API key (optional but recommended)",
        }
        return {}

    headers = {"Authorization": f"Bearer {LUNARCRUSH_KEY}"}
    data = safe_get(f"{LC_BASE}/coins/list/v2",
                    params={"limit": 100, "sort": "galaxy_score"},
                    headers=headers)

    if not data or "_auth_error" in (data or {}):
        source_status["lunarcrush"] = {
            "ok": False, "last_check": now_iso(),
            "error": data.get("_text", "auth/unreachable") if data else "unreachable",
        }
        return {}

    out = {}
    items = data.get("data", []) if isinstance(data, dict) else []
    for c in items:
        sym = (c.get("symbol") or "").upper()
        if not sym or sym in BLACKLIST:
            continue
        out[sym] = {
            "galaxy_score":      float(c.get("galaxy_score") or 0),       # 0-100
            "alt_rank":          int(c.get("alt_rank") or 9999),
            "social_volume_24h": float(c.get("interactions_24h") or 0),
            "social_dominance":  float(c.get("social_dominance") or 0),
            "sentiment":         float(c.get("sentiment") or 50),         # 0-100
            "price":             float(c.get("price") or 0),
            "percent_change_24h": float(c.get("percent_change_24h") or 0),
        }

    source_status["lunarcrush"] = {
        "ok": True, "last_check": now_iso(), "error": None
    }
    log.info(f"[LC] {len(out)} coins with Galaxy Score fetched")
    return out


# ── ③ DexScreener Boosted Tokens + Volume Surge ──
def fetch_dexscreener_data() -> Dict[str, Dict]:
    """
    1) Get top boosted tokens (proxy for trending DEX activity)
    2) For each unique token, fetch pair data with volume metrics
    Returns: {symbol_upper: {volume_h1, volume_h6, vol_change_pct, liquidity_usd, ...}}
    """
    # Step 1: top boosted tokens
    boosts = safe_get(f"{DS_BASE}/token-boosts/top/v1")
    if not boosts or "_auth_error" in (boosts or {}):
        source_status["dexscreener"] = {
            "ok": False, "last_check": now_iso(),
            "error": "boosts unreachable",
        }
        return {}

    # Boosts is a list of {chainId, tokenAddress, amount, totalAmount, ...}
    addresses = []
    if isinstance(boosts, list):
        for b in boosts[:30]:  # top 30 boosted
            addr = b.get("tokenAddress")
            chain = b.get("chainId")
            if addr and chain:
                addresses.append((chain, addr, b.get("totalAmount", 0)))

    out = {}
    # Step 2: fetch pair data for each address
    for chain, addr, boost_amount in addresses[:25]:
        pair_data = safe_get(f"{DS_BASE}/latest/dex/tokens/{addr}", retries=1)
        if not pair_data or "pairs" not in pair_data:
            continue
        pairs = pair_data.get("pairs") or []
        if not pairs:
            continue

        # Pick the pair with highest liquidity
        best = max(pairs, key=lambda p: float(
            (p.get("liquidity") or {}).get("usd") or 0
        ))

        base_token = best.get("baseToken", {}) or {}
        sym = (base_token.get("symbol") or "").upper()
        if not sym or sym in BLACKLIST:
            continue

        liquidity = float((best.get("liquidity") or {}).get("usd") or 0)
        if liquidity < MIN_LIQUIDITY_USD:
            continue  # filter rugs / dead tokens

        # Volume metrics
        vol = best.get("volume", {}) or {}
        v_h1  = float(vol.get("h1") or 0)
        v_h6  = float(vol.get("h6") or 0)
        v_h24 = float(vol.get("h24") or 0)

        # Volume surge: compare h1 to h6 average
        avg_h1_from_h6 = (v_h6 / 6.0) if v_h6 > 0 else 0
        vol_change_pct = ((v_h1 - avg_h1_from_h6) / avg_h1_from_h6 * 100) \
            if avg_h1_from_h6 > 0 else 0

        # Price change
        pc = best.get("priceChange", {}) or {}
        price_change_h1  = float(pc.get("h1") or 0)
        price_change_h24 = float(pc.get("h24") or 0)

        # Pair age
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
        "ok": True, "last_check": now_iso(), "error": None
    }
    log.info(f"[DS] {len(out)} tokens with volume data fetched")
    return out


# ── ④ CryptoPanic News Buzz ──
def fetch_cryptopanic_data() -> Dict[str, Dict]:
    """
    GET /posts/?filter=hot → hot news posts with currency tags.
    Returns: {symbol_upper: {hot_count, votes_positive, votes_negative, sentiment_ratio}}
    """
    if not CRYPTOPANIC_KEY:
        source_status["cryptopanic"] = {
            "ok": False, "last_check": now_iso(),
            "error": "no API key (optional but recommended)",
        }
        return {}

    data = safe_get(f"{CP_BASE}/posts/", params={
        "auth_token": CRYPTOPANIC_KEY,
        "filter": "hot",
        "public": "true",
    })

    if not data or "_auth_error" in (data or {}):
        source_status["cryptopanic"] = {
            "ok": False, "last_check": now_iso(),
            "error": data.get("_text", "auth/unreachable") if data else "unreachable",
        }
        return {}

    # Aggregate per symbol
    agg: Dict[str, Dict] = defaultdict(lambda: {
        "hot_count": 0,
        "votes_positive": 0,
        "votes_negative": 0,
        "votes_important": 0,
        "latest_title": "",
        "latest_url": "",
    })

    posts = data.get("results", []) if isinstance(data, dict) else []
    for post in posts[:50]:  # top 50 hot posts
        currencies = post.get("currencies") or []
        votes = post.get("votes") or {}
        for cur in currencies:
            sym = (cur.get("code") or "").upper()
            if not sym or sym in BLACKLIST:
                continue
            agg[sym]["hot_count"] += 1
            agg[sym]["votes_positive"] += int(votes.get("positive") or 0)
            agg[sym]["votes_negative"] += int(votes.get("negative") or 0)
            agg[sym]["votes_important"] += int(votes.get("important") or 0)
            if not agg[sym]["latest_title"]:
                agg[sym]["latest_title"] = post.get("title", "")[:120]
                agg[sym]["latest_url"]   = post.get("url", "")

    # Compute sentiment ratio (-1..+1)
    out = {}
    for sym, d in agg.items():
        pos, neg = d["votes_positive"], d["votes_negative"]
        total = pos + neg
        sentiment_ratio = ((pos - neg) / total) if total > 0 else 0.0
        d["sentiment_ratio"] = sentiment_ratio
        out[sym] = dict(d)

    source_status["cryptopanic"] = {
        "ok": True, "last_check": now_iso(), "error": None
    }
    log.info(f"[CP] {len(out)} symbols with hot news fetched")
    return out


# ══════════════════════════════════════════════════════════════════
# 5. SOURCE SCORERS (each returns 0..max_weight*100 normalized)
# ══════════════════════════════════════════════════════════════════
# Each scorer outputs 0..100 (raw), then aggregator multiplies by weight

def score_coingecko(sym: str, cg_data: Dict[str, Dict]) -> float:
    """
    CG Trending rank → 0..100 score.
    Rank 1 = 100 pts | Rank 15 = 30 pts | Not trending = 0
    """
    info = cg_data.get(sym)
    if not info:
        return 0.0
    rank = info.get("rank", 16)
    if rank > 15:
        return 0.0
    # Linear: rank 1 → 100 | rank 15 → 30
    return max(0.0, 100.0 - ((rank - 1) * (70.0 / 14.0)))


def score_lunarcrush(sym: str, lc_data: Dict[str, Dict]) -> float:
    """
    Galaxy Score (0-100) is a direct quality signal.
    Boost for high social_dominance and bullish sentiment.
    """
    info = lc_data.get(sym)
    if not info:
        return 0.0

    galaxy = info.get("galaxy_score", 0)            # 0-100
    sentiment = info.get("sentiment", 50)           # 0-100
    social_dom = info.get("social_dominance", 0)    # %
    alt_rank = info.get("alt_rank", 9999)

    # Base = Galaxy Score
    score = galaxy

    # Sentiment modifier: > 60 boosts up to +5, < 40 reduces up to -5
    if sentiment > 60:
        score += min(5.0, (sentiment - 60) / 8.0)
    elif sentiment < 40:
        score -= min(5.0, (40 - sentiment) / 8.0)

    # Social dominance boost: > 1% = strong attention
    if social_dom > 1.0:
        score += min(5.0, social_dom * 2.0)

    # AltRank top 50 boost
    if alt_rank <= 50:
        score += 5.0
    elif alt_rank <= 100:
        score += 2.0

    return max(0.0, min(100.0, score))


def score_dexscreener(sym: str, ds_data: Dict[str, Dict]) -> float:
    """
    DEX volume surge is the strongest whale signal.
    Volume change % h1-vs-avg: 100% = 50 | 500% = 80 | 1000%+ = 100
    Plus liquidity & price-change confirmation.
    """
    info = ds_data.get(sym)
    if not info:
        return 0.0

    vol_change = info.get("vol_change_pct", 0)         # %
    liquidity  = info.get("liquidity_usd", 0)
    price_h1   = info.get("price_change_h1", 0)
    price_h24  = info.get("price_change_h24", 0)
    boost      = info.get("boost_amount", 0)
    age_days   = info.get("age_days", 0)

    # Base: volume surge (capped logarithmically)
    if vol_change <= 0:
        base = 20.0  # token is in boosted list = some attention
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

    # Liquidity tier (whale concern: > $1M is healthy)
    if liquidity >= 5_000_000:
        base += 3.0
    elif liquidity >= 1_000_000:
        base += 2.0
    elif liquidity < 250_000:
        base -= 5.0  # low liquidity = manipulation risk

    # Price-volume agreement: volume up + price up = real demand
    if vol_change > 100 and price_h1 > 5:
        base += 5.0
    elif vol_change > 100 and price_h1 < -5:
        base -= 3.0   # volume spike but price dump = distribution

    # 24h trend confirmation
    if price_h24 > 20:
        base += 2.0

    # Boost amount (whales paying for visibility)
    if boost >= 500:
        base += 3.0
    elif boost >= 100:
        base += 1.5

    # Age penalty for very new tokens (rug risk)
    if age_days < 7:
        base -= 8.0
    elif age_days < 30:
        base -= 3.0

    return max(0.0, min(100.0, base))


def score_cryptopanic(sym: str, cp_data: Dict[str, Dict]) -> float:
    """
    News buzz score: hot post count + sentiment + importance votes.
    """
    info = cp_data.get(sym)
    if not info:
        return 0.0

    hot_count       = info.get("hot_count", 0)
    sentiment_ratio = info.get("sentiment_ratio", 0)    # -1..+1
    important       = info.get("votes_important", 0)

    # Base: hot count (capped at 10 posts)
    if hot_count <= 0:
        return 0.0
    base = min(60.0, hot_count * 12.0)   # 1 post=12, 5 posts=60

    # Sentiment modifier (-15..+25)
    base += sentiment_ratio * 20.0

    # Importance votes (whale-curated signal)
    if important >= 10:
        base += 15.0
    elif important >= 5:
        base += 8.0
    elif important >= 1:
        base += 3.0

    return max(0.0, min(100.0, base))


# ══════════════════════════════════════════════════════════════════
# 6. AGGREGATOR (combine 4 sources into unified score)
# ══════════════════════════════════════════════════════════════════

def aggregate_hype_signals(
    cg_data: Dict[str, Dict],
    lc_data: Dict[str, Dict],
    ds_data: Dict[str, Dict],
    cp_data: Dict[str, Dict],
) -> List[Dict[str, Any]]:
    """
    Combine all 4 sources for every unique symbol → ranked list.
    Returns: [{symbol, score, sources_count, breakdown, ds_info, lc_info, ...}]
    """
    # Collect all unique symbols across sources
    all_syms = set()
    all_syms.update(cg_data.keys())
    all_syms.update(lc_data.keys())
    all_syms.update(ds_data.keys())
    all_syms.update(cp_data.keys())

    results = []
    for sym in all_syms:
        s_cg = score_coingecko(sym, cg_data)
        s_lc = score_lunarcrush(sym, lc_data)
        s_ds = score_dexscreener(sym, ds_data)
        s_cp = score_cryptopanic(sym, cp_data)

        # Count sources where score >= 30 (meaningful presence)
        sources_count = sum(1 for s in (s_cg, s_lc, s_ds, s_cp) if s >= 30)

        # Weighted unified score
        unified = (
            s_cg * W_CG +
            s_lc * W_LC +
            s_ds * W_DEX +
            s_cp * W_CP
        )

        if unified < 30:  # don't waste memory on weak signals
            continue

        results.append({
            "symbol":         sym,
            "score":          round(unified, 1),
            "sources_count":  sources_count,
            "breakdown": {
                "coingecko":   round(s_cg, 1),
                "lunarcrush":  round(s_lc, 1),
                "dexscreener": round(s_ds, 1),
                "cryptopanic": round(s_cp, 1),
            },
            "cg_info": cg_data.get(sym, {}),
            "lc_info": lc_data.get(sym, {}),
            "ds_info": ds_data.get(sym, {}),
            "cp_info": cp_data.get(sym, {}),
        })

    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ══════════════════════════════════════════════════════════════════
# 7. FILTERS (apply mode-specific rules)
# ══════════════════════════════════════════════════════════════════

def passes_mode_filter(item: Dict[str, Any], mode: str) -> tuple:
    """
    Returns (passed: bool, reason: str)
    Filters: min_score, min_sources, min_per_source.
    """
    cfg = MODES.get(mode, MODES["عادي"])

    if item["score"] < cfg["min"]:
        return False, f"score {item['score']} < {cfg['min']}"

    if item["sources_count"] < cfg["min_sources"]:
        return False, f"sources {item['sources_count']}/{cfg['min_sources']}"

    # In stricter modes, every active source must clear the floor
    if cfg["min_per_source"] > 0:
        active_scores = [
            v for v in item["breakdown"].values() if v >= 30
        ]
        if active_scores:
            min_active = min(active_scores)
            if min_active < cfg["min_per_source"]:
                return False, f"weakest source {min_active} < {cfg['min_per_source']}"

    return True, "ok"


def is_in_cooldown(symbol: str) -> bool:
    """Check if symbol was alerted in last COOLDOWN_HOURS."""
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
    """Build the full alert message in Arabic Markdown."""
    sym       = item["symbol"]
    score     = item["score"]
    sources   = item["sources_count"]
    bk        = item["breakdown"]
    ds        = item["ds_info"]
    lc        = item["lc_info"]
    cg        = item["cg_info"]
    cp        = item["cp_info"]

    grade = _grade_label(score)
    lines = []
    lines.append(f"🔥 *إشارة HYPE* — `{sym}`")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🎯 السكور الموحّد: *{score}/100* {grade}")
    lines.append(f"📊 المصادر المتفقة: *{sources}/4*")
    lines.append("")

    # Source breakdown
    lines.append("*التفصيل (whale-weighted):*")
    if bk["dexscreener"] > 0:
        lines.append(
            f"{_src_emoji(bk['dexscreener'])} DexScreener: `{bk['dexscreener']}/100`"
            f" (وزن 35%)"
        )
        if ds:
            vol_change = ds.get("vol_change_pct", 0)
            liq        = ds.get("liquidity_usd", 0)
            ph1        = ds.get("price_change_h1", 0)
            chain      = ds.get("chain", "?")
            lines.append(
                f"   💧 Volume +{vol_change:.0f}% | Liq ${liq/1000:.0f}K | "
                f"H1: {ph1:+.1f}% | {chain}"
            )

    if bk["lunarcrush"] > 0:
        lines.append(
            f"{_src_emoji(bk['lunarcrush'])} LunarCrush: `{bk['lunarcrush']}/100`"
            f" (وزن 30%)"
        )
        if lc:
            galaxy = lc.get("galaxy_score", 0)
            altrnk = lc.get("alt_rank", 0)
            sent   = lc.get("sentiment", 0)
            lines.append(
                f"   🌌 Galaxy: {galaxy:.0f} | AltRank #{altrnk} | "
                f"Sentiment: {sent:.0f}/100"
            )

    if bk["cryptopanic"] > 0:
        lines.append(
            f"{_src_emoji(bk['cryptopanic'])} CryptoPanic: `{bk['cryptopanic']}/100`"
            f" (وزن 20%)"
        )
        if cp:
            hot = cp.get("hot_count", 0)
            ratio = cp.get("sentiment_ratio", 0)
            sent_label = "إيجابي" if ratio > 0.2 else "سلبي" if ratio < -0.2 else "محايد"
            lines.append(f"   📰 {hot} خبر حار | شعور: {sent_label}")

    if bk["coingecko"] > 0:
        lines.append(
            f"{_src_emoji(bk['coingecko'])} CoinGecko: `{bk['coingecko']}/100`"
            f" (وزن 15%)"
        )
        if cg:
            rank = cg.get("rank", 0)
            mc_rank = cg.get("market_cap_rank", 0)
            lines.append(f"   📈 Trending #{rank} | MC Rank #{mc_rank}")

    lines.append("")

    # Price summary if DEX data available
    if ds and ds.get("price_usd"):
        price = ds.get("price_usd")
        price_str = f"${price:.8f}".rstrip('0').rstrip('.') if price < 0.01 else f"${price:,.4f}"
        lines.append(f"💰 السعر: `{price_str}`")
        lines.append(f"📈 24س: {ds.get('price_change_h24', 0):+.2f}%")

    lines.append("")

    # Whale insight by mode
    if score >= 92:
        lines.append("🎯 *تحليل وول ستريت:* 4 مصادر متفقة بقوة. هذا نمط صفقة قنّاصة — "
                    "الحيتان تتموضع. تحقّق يدوي قبل الدخول.")
    elif score >= 85:
        lines.append("🎯 *تحليل وول ستريت:* منطقة دخول الحيتان. تأكد من DEX volume يستمر.")
    elif score >= 75:
        lines.append("🎯 *تحليل وول ستريت:* watchlist للمتداولين الكبار — مراقبة لا دخول.")
    else:
        lines.append("🎯 *تحليل وول ستريت:* إشارة عادية. retail-friendly.")

    lines.append("")
    lines.append("⚠️ _تنفيذ يدوي — تعليمي فقط، ليس نصيحة مالية._")

    return "\n".join(lines)


def build_alert_buttons(item: Dict[str, Any]) -> Optional[InlineKeyboardMarkup]:
    """Inline buttons for chart links."""
    sym = item["symbol"]
    ds  = item.get("ds_info", {})
    cg  = item.get("cg_info", {})

    rows = []
    btns = []

    # Binance link (universal)
    btns.append(InlineKeyboardButton(
        "📊 Binance", url=f"https://www.binance.com/en/trade/{sym}_USDT"
    ))

    # DexScreener
    if ds and ds.get("pair_url"):
        btns.append(InlineKeyboardButton("💧 DexScreener", url=ds["pair_url"]))

    rows.append(btns[:2])
    btns2 = []

    # CoinGecko
    if cg and cg.get("cg_id"):
        btns2.append(InlineKeyboardButton(
            "📈 CoinGecko", url=f"https://www.coingecko.com/en/coins/{cg['cg_id']}"
        ))

    # LunarCrush
    btns2.append(InlineKeyboardButton(
        "🌌 LunarCrush", url=f"https://lunarcrush.com/coins/{sym.lower()}"
    ))

    if btns2:
        rows.append(btns2)

    return InlineKeyboardMarkup(rows) if rows else None


# ══════════════════════════════════════════════════════════════════
# 9. SCANNER JOB (periodic)
# ══════════════════════════════════════════════════════════════════

async def scanner_job(context: ContextTypes.DEFAULT_TYPE):
    """Main scanner: fetch all sources → aggregate → filter → alert."""
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
        # Fetch all 4 sources (run in thread pool to avoid blocking)
        loop = asyncio.get_event_loop()
        cg_data = await loop.run_in_executor(None, fetch_coingecko_trending)
        lc_data = await loop.run_in_executor(None, fetch_lunarcrush_data)
        ds_data = await loop.run_in_executor(None, fetch_dexscreener_data)
        cp_data = await loop.run_in_executor(None, fetch_cryptopanic_data)

        # Aggregate
        aggregated = aggregate_hype_signals(cg_data, lc_data, ds_data, cp_data)

        # Persist for `نتائج` and `top10` commands
        global last_results
        last_results = aggregated[:MAX_RESULTS_KEPT]

        # Filter & alert
        sent_count = 0
        for item in aggregated:
            sym = item["symbol"]

            ok, reason = passes_mode_filter(item, mode)
            if not ok:
                continue

            if is_in_cooldown(sym):
                continue

            # Send alert
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

START_MSG = (
    "🔥 *HYPE\\_BOT v1\\.0* — Whale\\-Style Signal Scanner\n\n"
    "أكشف العملات اللي عليها هايب من 4 مصادر مدمجة بأوزان احترافية\\.\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "*المصادر \\& الأوزان:*\n"
    "💧 DexScreener   `35%`  on\\-chain volume \\(الأقوى\\)\n"
    "🌌 LunarCrush    `30%`  Galaxy Score\n"
    "📰 CryptoPanic   `20%`  News buzz\n"
    "📈 CoinGecko     `15%`  Retail trending\n\n"
    "*أوضاع الكشف \\(whale\\-style\\):*\n"
    "🟢 `هايب`           ≥65  عادي\n"
    "⚖️ `هايب متوازن`     ≥75  watchlist للحيتان\n"
    "💎 `هايب جودة`       ≥85  منطقة دخول المحترفين\n"
    "👑 `هايب ذهبي`       ≥92  صفقات قناصة \\(نادر\\)\n\n"
    "*أوامر إضافية:*\n"
    "`/test`     فحص اتصال المصادر\n"
    "`حالة`      حالة المصادر الـ4\n"
    "`نتائج`     آخر 5 إشارات\n"
    "`top10`     أعلى 10 عملات هايب الآن\n"
    "`وقف`       إيقاف الكشف\n\n"
    "⚠️ _تنفيذ يدوي — تعليمي فقط، ليس نصيحة مالية_"
)


async def cmd_start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(START_MSG, parse_mode="MarkdownV2")


async def cmd_test(u: Update, c: ContextTypes.DEFAULT_TYPE):
    """Quick connectivity test to all 4 sources."""
    msg = await u.message.reply_text("⏳ فحص المصادر الأربعة...")

    loop = asyncio.get_event_loop()
    cg = await loop.run_in_executor(None, fetch_coingecko_trending)
    lc = await loop.run_in_executor(None, fetch_lunarcrush_data)
    ds = await loop.run_in_executor(None, fetch_dexscreener_data)
    cp = await loop.run_in_executor(None, fetch_cryptopanic_data)

    def stat(d):
        return d.get("ok", False)

    lines = ["🔍 *نتيجة الفحص:*\n"]
    s = source_status

    icon_cg = "✅" if stat(s["coingecko"])   else "❌"
    icon_lc = "✅" if stat(s["lunarcrush"])  else "❌"
    icon_ds = "✅" if stat(s["dexscreener"]) else "❌"
    icon_cp = "✅" if stat(s["cryptopanic"]) else "❌"

    lines.append(f"{icon_cg} *CoinGecko*: {len(cg)} عملة trending")
    if not stat(s["coingecko"]):
        lines.append(f"   _خطأ: {s['coingecko'].get('error', 'unknown')[:80]}_")

    lines.append(f"{icon_lc} *LunarCrush*: {len(lc)} عملة بـ Galaxy Score")
    if not stat(s["lunarcrush"]):
        lines.append(f"   _ملاحظة: {s['lunarcrush'].get('error', '')[:80]}_")

    lines.append(f"{icon_ds} *DexScreener*: {len(ds)} رمز بـ volume data")
    if not stat(s["dexscreener"]):
        lines.append(f"   _خطأ: {s['dexscreener'].get('error', '')[:80]}_")

    lines.append(f"{icon_cp} *CryptoPanic*: {len(cp)} رمز بأخبار حارة")
    if not stat(s["cryptopanic"]):
        lines.append(f"   _ملاحظة: {s['cryptopanic'].get('error', '')[:80]}_")

    active_count = sum(1 for x in (icon_cg, icon_lc, icon_ds, icon_cp) if x == "✅")
    lines.append("")
    if active_count >= 3:
        lines.append(f"🎯 *الحالة:* ممتازة ({active_count}/4 مصادر شغّالة)")
    elif active_count >= 2:
        lines.append(f"⚠️ *الحالة:* مقبولة ({active_count}/4) — يفضّل تفعيل الباقي")
    else:
        lines.append(f"🚨 *الحالة:* ضعيفة ({active_count}/4) — تحقق من المفاتيح")

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
    # "هايب" / "هايب متوازن" / "هايب جودة" / "هايب ذهبي"
    if text.startswith("هايب") or text_l in ("hype", "start hype"):
        # parse mode
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

        # Stop existing job for this chat
        for j in c.job_queue.get_jobs_by_name(f"hype_{chat_id}"):
            j.schedule_removal()

        # Start new repeating job
        c.job_queue.run_repeating(
            scanner_job,
            interval=SCAN_INTERVAL_SEC,
            first=10,    # first scan after 10 seconds
            data={"chat_id": chat_id},
            name=f"hype_{chat_id}",
        )

        await u.message.reply_text(
            f"🚨 *تم تفعيل كاشف الهايب*\n\n"
            f"⚙️ الوضع: {cfg['label']}\n"
            f"🎯 الحد الأدنى: `{cfg['min']}/100`\n"
            f"📊 الحد الأدنى للمصادر: `{cfg['min_sources']}/4`\n"
            f"⏱ المسح: كل {SCAN_INTERVAL_SEC // 60} دقائق\n"
            f"❄️ Cooldown: ساعة واحدة لكل عملة\n\n"
            f"⚠️ سيرسل تنبيهات للعملات بسكور موحّد ≥ {cfg['min']}\n"
            f"⚠️ التنفيذ يدوي — تعليمي فقط\n\n"
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
        lines = ["📡 *حالة المصادر:*\n"]
        for name, info in [
            ("DexScreener", s["dexscreener"]),
            ("LunarCrush",  s["lunarcrush"]),
            ("CryptoPanic", s["cryptopanic"]),
            ("CoinGecko",   s["coingecko"]),
        ]:
            icon = "✅" if info.get("ok") else "❌"
            last = info.get("last_check", "—")
            if last and last != "—":
                try:
                    dt = datetime.fromisoformat(last)
                    last = dt.strftime("%H:%M:%S")
                except Exception:
                    pass
            lines.append(f"{icon} *{name}*: {last}")
            err = info.get("error")
            if err and not info.get("ok"):
                lines.append(f"   _{str(err)[:80]}_")

        # Active scanner status
        cfg = chat_config.get(chat_id, {})
        lines.append("")
        if cfg.get("active"):
            lines.append(
                f"🟢 الكاشف نشط — وضع: *{cfg.get('mode', 'عادي')}* "
                f"(≥{cfg.get('min_score', 65)})"
            )
        else:
            lines.append("⚪ الكاشف متوقف")

        # Cooldown info
        active_cooldowns = sum(
            1 for sym in seen_coins if is_in_cooldown(sym)
        )
        lines.append(f"❄️ عملات في cooldown: {active_cooldowns}")

        await u.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    # ── نتائج ──
    if text_l in ("نتائج", "results", "آخر النتائج"):
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
                f"({item['sources_count']}/4) {grade}"
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
        lines = ["🏆 *أعلى 10 عملات هايب الآن:*\n"]
        for i, item in enumerate(last_results[:10], 1):
            bk = item["breakdown"]
            lines.append(
                f"{i}. *{item['symbol']}* `{item['score']}/100`\n"
                f"   💧{bk['dexscreener']:.0f} 🌌{bk['lunarcrush']:.0f} "
                f"📰{bk['cryptopanic']:.0f} 📈{bk['coingecko']:.0f}"
            )
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    # ── سجل التنبيهات ──
    if text_l in ("سجل", "history", "الإشارات السابقة"):
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
            lines.append(
                f"• `{t}` *{h['symbol']}* {h['score']}/100 "
                f"({h['mode']})"
            )
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    # ── help/unknown ──
    await u.message.reply_text(
        "🤖 لم أفهم الأمر.\n\nأرسل `/start` لرؤية القائمة الكاملة.",
        parse_mode="Markdown"
    )


async def error_handler(update, context):
    """Global error handler — log and continue."""
    log.warning(f"[ERR] {context.error}")
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ خطأ مؤقت. حاول مرة أخرى."
            )
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════
# 11. POST INIT (delete webhook, prevent Conflict)
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
    cg_status = "✅" if COINGECKO_KEY   else "⚪ (بدون مفتاح، rate-limited)"
    lc_status = "✅" if LUNARCRUSH_KEY  else "❌ (مفقود — مصدر معطّل)"
    cp_status = "✅" if CRYPTOPANIC_KEY else "❌ (مفقود — مصدر معطّل)"

    print("=" * 65)
    print("  🔥 HYPE_BOT v1.0 — Running ✅")
    print("=" * 65)
    print(f"  المصادر       : 4 (Whale-weighted)")
    print(f"    💧 DexScreener  : ✅ (مجاني، بدون مفتاح)")
    print(f"    🌌 LunarCrush   : {lc_status}")
    print(f"    📰 CryptoPanic  : {cp_status}")
    print(f"    📈 CoinGecko    : {cg_status}")
    print(f"  الأوضاع       : 4 (65 / 75 / 85 / 92)")
    print(f"  المسح         : كل {SCAN_INTERVAL_SEC // 60} دقائق")
    print(f"  Cooldown      : ساعة لكل عملة")
    print(f"  السيولة الدنيا: ${MIN_LIQUIDITY_USD:,}")
    print("=" * 65)
    print("  أرسل /start في تيليقرام لبدء الاستخدام")
    print("=" * 65)


def main():
    if not BOT_TOKEN:
        print("=" * 65)
        print("  ❌ ERROR: BOT_TOKEN غير موجود في environment")
        print("  أضفه في Railway → Variables → BOT_TOKEN")
        print("=" * 65)
        return

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(_post_init)
        .build()
    )

    # Handlers
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
