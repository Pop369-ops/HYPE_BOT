# 🔥 HYPE_BOT v3.0 — Wintermute-Style Whale Scanner

كاشف الهايب من 5 مصادر مدمجة بأوزان احترافية ديناميكية (chain-aware).

## 📡 المصادر (5)

| # | المصدر | EVM | non-EVM | API Key |
|---|---|---|---|---|
| 1 | 💧 **DexScreener** | 35% | 45% | ❌ مجاني |
| 2 | 🦙 **DefiLlama** | 20% | 25% | ❌ مجاني |
| 3 | 🔍 **Etherscan V2** | 20% | 0% | ✅ ETHERSCAN_KEY |
| 4 | 🐋 **Binance Futures** | 15% | 18% | ❌ مجاني |
| 5 | 📊 **CoinPaprika** | 10% | 12% | ❌ مجاني |

**75% on-chain coverage** = معمارية بمعايير صناديق التحوط الكمية.

## ⛓ EVM Chains المدعومة

Ethereum, BSC, Polygon, Arbitrum, Optimism, Base, Avalanche, Fantom, Linea, Blast (10 شبكات).

## 🎯 الأوضاع

| الوضع | السكور |
|---|---|
| 🟢 هايب | ≥65 |
| ⚖️ هايب متوازن | ≥75 |
| 💎 هايب جودة | ≥85 |
| 👑 هايب ذهبي | ≥92 |

## 🔑 Environment Variables

```
BOT_TOKEN          (إلزامي)
ETHERSCAN_KEY      (موصى به — V2 API يدعم 50+ chain)
```

## 🌐 Region

`europe-west4` على Railway (لـ Binance access).

## 📝 الأوامر

| الأمر | الوظيفة |
|---|---|
| `/start` | القائمة الرئيسية |
| `/test` | فحص اتصال المصادر الـ5 |
| `/esdebug` | تشخيص Etherscan V2 (3 chains) |
| `هايب` / `هايب متوازن` / `هايب جودة` / `هايب ذهبي` | تفعيل وضع الكشف |
| `حالة` | حالة المصادر + الأوزان النشطة |
| `نتائج` | آخر 10 إشارات |
| `top10` | أعلى 10 عملات هايب مع breakdown |
| `سجل` | سجل التنبيهات |
| `وقف` | إيقاف الكاشف |

## 🐋 منطق Wintermute المدمج

- **Velocity ratio** (1h tx vs 24h hourly average) — السرعة عاملاً للهايب
- **Whale tx count** (transfers ≥$10K) — حركة الكبار في الساعة الأخيرة
- **Unique addresses** (24h) — تنوّع المشاركين (مؤشّر منع التلاعب)
- **TVL change** (1d/7d) — تدفّقات DeFi المؤسسية
- **Volume rank** (Binance Futures) — اهتمام futures market

## ⚠️ Disclaimer

للأغراض التعليمية فقط — ليس نصيحة مالية.
