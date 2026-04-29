# 🔥 HYPE_BOT v5.0 — Specialized AI Council

كاشف الهايب احترافي بـ **6 مصادر + 3 AI خبراء متخصصين + Portfolio**.

## 🤝 AI Council (Specialized Roles)

| AI | الدور | يفعّل عند | التخصص |
|---|---|---|---|
| 🟢 **Gemini 2.5 Flash** | Quality Detector | score ≥75 | ORGANIC vs PUMPED |
| 🟣 **Claude Opus 4.5** | Wintermute Strategist | score ≥85 | سيناريو + سياق تاريخي |
| 🔵 **GPT-4o** | Trade Executor | score ≥92 | Entry/T1/T2/SL + R/R |

**Tier-based routing** يوفّر التكلفة:
```
score 75-84  → 🟢 Gemini فقط
score 85-91  → 🟢 + 🟣 Claude
score 92+    → 🟢 + 🟣 + 🔵 (Council كامل)
```

## 📡 المصادر (6) — Chain-Aware Weights

| # | المصدر | EVM | non-EVM | API Key |
|---|---|---|---|---|
| 1 | 💧 **DexScreener** | 30% | 40% | ❌ مجاني |
| 2 | 🦙 **DefiLlama** | 18% | 22% | ❌ مجاني |
| 3 | 🔍 **Etherscan V2** | 18% | 0% | ✅ ETHERSCAN_KEY |
| 4 | 🐋 **Binance Futures** | 12% | 15% | ❌ مجاني |
| 5 | 📊 **CoinPaprika** | 7% | 8% | ❌ مجاني |
| 6 | 💎 **Massive.com** | 15% | 15% | ✅ POLYGON_API_KEY |

## 💼 Portfolio Integration (DCA Bot)

كل تنبيه يتم إثرائه بـ:
- 🪙 الكمية الحالية
- 💰 متوسط سعر الشراء
- 📊 PnL %
- 🏦 Exchange

## 🎯 الأوضاع

| الوضع | السكور | AI Layer |
|---|---|---|
| 🟢 هايب | ≥65 | لا AI |
| ⚖️ هايب متوازن | ≥75 | + 🟢 Gemini |
| 💎 هايب جودة | ≥85 | + 🟣 Claude |
| 👑 هايب ذهبي | ≥92 | + 🔵 GPT-4o (Council كامل) |

## 🔑 Environment Variables

```bash
# إلزامية
BOT_TOKEN              من BotFather

# موصى بشدة
ETHERSCAN_KEY          مجاني — etherscan.io
POLYGON_API_KEY        من اشتراك Massive ($49/شهر)

# AI Council (موصى بشدة)
GEMINI_API_KEY         مجاني — Google AI Studio
CLAUDE_API_KEY         من console.anthropic.com
OPENAI_API_KEY         من platform.openai.com

# اختيارية
DCA_DATA_DIR=/data     لربط محفظة DCA_BOT
```

## 🌐 Region

`europe-west4` على Railway.

## 📝 الأوامر

| الأمر | الوظيفة |
|---|---|
| `/start` | القائمة الرئيسية |
| `/test` | فحص شامل (6 مصادر + AI Council 3/3) |
| `/scan SYMBOL` ⭐ | فحص يدوي + AI tier حسب score |
| `/movers` ⭐ | Top gainers cross-exchange (Massive) |
| `/esdebug` | تشخيص Etherscan V2 |
| `هايب` / `هايب متوازن` / `هايب جودة` / `هايب ذهبي` | تفعيل وضع |
| `حالة` | حالة المصادر |
| `نتائج` | آخر 10 إشارات |
| `top10` | أعلى 10 عملات هايب |
| `سجل` | سجل التنبيهات |
| `وقف` | إيقاف الكشف |

## 🐋 منطق Wintermute المدمج

- **Velocity ratio** (1h tx vs 24h hourly avg) — السرعة
- **Whale tx count** (transfers ≥$10K) — حركة الكبار
- **Unique addresses** (24h) — تنوّع المشاركين
- **TVL change** (1d/7d) — تدفّقات DeFi المؤسسية
- **Cross-exchange momentum** (Massive) — اتجاه شامل
- **AI Council** — quality + strategy + execution

## 🎯 شكل التنبيه (golden tier)

```
🔥 إشارة HYPE — RENDER 👑
🎯 السكور: 95.5/100

[Sources breakdown]
[Massive cross-exchange]

🤝 Council of AI Experts (3/3):

🟢 Gemini (Quality Detector):
   ORGANIC growth, medium risk
   حركة عضوية قوية

🟣 Claude (Wintermute Strategist):
   Targets: 24h +8.5% · 48h +18%
   Support $4.50 ↔ Resistance $5.20
   نمط مشابه لـ MATIC يونيو 2021

🔵 GPT-4o (Trade Executor):
   Entry $4.85 · T1 $5.15 · T2 $5.50 · SL $4.55
   R/R: 2.0
   حجم: 2-5% من المحفظة
   التوقيت: دخول الآن، خروج 24-48h

🤝 Council Verdict: 🎯 إجماع 3/3 — قناعة عالية ⭐

💼 من محفظتك: 25.5 RENDER @ $4.20 (+15.5%)
```

## 💰 التكلفة الشهرية المتوقعة

```
Etherscan:  $0      (مجاني)
Massive:    $49     (Currencies Starter)
Gemini:     $0      (Free tier)
Claude:     ~$3     (للأخبار score ≥85)
OpenAI:     ~$2     (للأخبار score ≥92)
Railway:    ~$0.50  (per bot)
─────────────────────────
الإجمالي:   ~$55/mo
```

## ⚠️ Disclaimer

للأغراض التعليمية فقط — ليس نصيحة مالية.
