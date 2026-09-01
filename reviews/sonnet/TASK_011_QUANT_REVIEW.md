# TASK_011_QUANT_REVIEW.md
# Reviewer: SONNET (Quantitative / Statistical)
# Task ID: T011
# Date: 2026-09-01

---

## Summary

Quantitative review of T011 RiskEngine. Focus: 8-step position sizing formula,
rounding sequencing, fee formula, R:R computation from rounded prices, and
daily limit boundaries.

---

## Step-by-Step Sizing Verification (RISK_SPEC §2)

| Step | Code | Status |
|---|---|---|
| 1a — risk_distance | `abs(entry_price - rounded_stop)` line 158 | ✅ Uses rounded stop (correct) |
| 1b — risk_distance_pct | `risk_distance / entry_price` line 159 | ✅ |
| 2 — position_size_usdt | `risk_usd / risk_distance_pct` line 160 | ✅ |
| 3 — raw_qty | `position_size_usdt / entry_price` line 161 | ✅ |
| 4 — qty (floor) | `_floor_to_increment(raw_qty, lot_size)` line 162 | ✅ ROUND_FLOOR — never up |
| 5 — min order check | `qty < min_order_qty → reject` line 163 | ✅ |
| 6 — fee | `qty×entry×fee_rate + qty×rounded_tp×fee_rate` lines 166-168 | ✅ Both sides; TP as exit |
| 7 — slippage | `qty×entry×slippage_rate + qty×rounded_tp×slippage_rate` lines 169-171 | ✅ Both sides |
| 8 — effective risk | `risk_usd + fee + slippage` line 173 | ✅ |

**Note on rounding sequence**: stop and TP are rounded BEFORE risk_distance is
computed (line 148-150 before line 158). Position size is therefore based on the
actual rounded stop distance — what will genuinely be used in execution. ✅

---

## Known Values Verification

Entry=100, Stop=102, TP=96, lot_size=0.01, fee_rate=0.00055, slippage=0.0005:
```
risk_distance_pct = 2 / 100 = 0.02
position_size_usdt = 5.00 / 0.02 = 250.00
raw_qty = 250.00 / 100 = 2.50
qty (floored to 0.01) = 2.50
fee = 2.5×100×0.00055 + 2.5×96×0.00055 = 0.1375 + 0.132 = 0.2695 ✅
slippage = 2.5×100×0.0005 + 2.5×96×0.0005 = 0.125 + 0.12 = 0.245 ✅
effective_risk = 5.00 + 0.2695 + 0.245 = 5.5145 ✅
```

---

## Daily Limit Boundaries

| Condition | Code | Op | Status |
|---|---|---|---|
| trades_taken >= 5 | `>= self._max_trades_per_day` | `>=` inclusive | ✅ |
| realized_pnl <= -25.00 | `<= self._daily_loss_limit` | `<=` inclusive | ✅ |
| realized_pnl >= +50.00 | `>= self._daily_profit_lock` | `>=` inclusive | ✅ |

All boundaries inclusive — correct per RISK_SPEC §3. ✅

---

## Price Rounding

| Price | Direction | Code | Status |
|---|---|---|---|
| SHORT stop | CEIL | `_round_price(stop, tick, "up")` line 230 | ✅ |
| SHORT TP | CEIL | `_round_price(tp, tick, "up")` line 231 | ✅ CTO ruling |
| LONG stop | FLOOR | `_round_price(stop, tick, "down")` line 234 | ✅ |
| LONG TP | FLOOR | `_round_price(tp, tick, "down")` line 235 | ✅ CTO ruling |

---

## R:R Ratio

Line 181: `rr_ratio = abs(entry_price - rounded_tp) / risk_distance`

`risk_distance` is already from rounded stop (line 158). ✅
R:R is computed on rounded prices. ✅
Minimum R:R check in viability uses `self._min_rr_ratio = Decimal(str(config.min_rr_ratio))`. ✅

---

## Critical Issues

**None.**

---

## Release Recommendation

**APPROVED** — All 8 sizing steps correct. Rounding before R:R. Inclusive daily limits.

---
