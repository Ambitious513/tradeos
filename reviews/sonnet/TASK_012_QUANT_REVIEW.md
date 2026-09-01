# TASK_012_QUANT_REVIEW.md
# Reviewer: SONNET (Integration / Statistical)
# Task ID: T012
# Date: 2026-09-01

---

## Summary

Integration review of T012 ScanLoop. Focus: step order in _process_candle,
promotion condition timing, PnL formula, daily limit boundary conditions,
and 4H regime detection.

---

## Step Order Verification (R-002)

`_process_candle` lines 110-139:

| Step | Code | Status |
|---|---|---|
| is_closed guard | line 112 | ✅ |
| DailySession reset | line 114 | ✅ Candle date, not wall clock |
| 4H BTC regime refresh | lines 115-116 | ✅ |
| timeframe != "60" → return | lines 117-118 | ✅ BTCUSDT 4H processed for regime only |
| _promote_triggered_signals | line 119 | ✅ BEFORE new detections |
| _check_active_signals | line 120 | ✅ BEFORE new detections |
| is_halted → return | lines 121-122 | ✅ New detections blocked when halted |
| on_candle + exception guard | lines 123-133 | ✅ |
| _handle_triggered | line 134 | ✅ AFTER on_candle |

Contract order: expire/cancel → ARMED → WATCHING → detect is handled inside
`signal_manager.on_candle()`. ScanLoop step order is correct at its layer. ✅

---

## TRIGGERED → ACTIVE Promotion (Decision B)

`_promote_triggered_signals` line 151:
```python
if signal.triggered_at is None or signal.triggered_at >= candle.open_time:
    continue
```
`>=` means: signals triggered ON this candle (same open_time) are NOT promoted.
Only signals triggered on a PRIOR candle (triggered_at < open_time) are promoted.
This correctly implements "entry = next candle open". ✅

Zero-entry guard (line 143): `candle.open <= 0 → ERROR + return`. ✅

---

## TP/SL Hit Detection (Decision C)

| Condition | Code | Status |
|---|---|---|
| LONG SL | `candle.low <= stop_price` line 240 | ✅ Inclusive |
| LONG TP | `candle.high >= take_profit` line 241 | ✅ Inclusive |
| SHORT SL | `candle.high >= stop_price` line 243 | ✅ Inclusive |
| SHORT TP | `candle.low <= take_profit` line 244 | ✅ Inclusive |
| SL wins both | `SL_HIT if sl_hit else TP_HIT` line 247 | ✅ |

---

## PnL Formula Verification

`_net_pnl` lines 280-295 — per contract spec "entry fee already paid":

```
fee_cost = qty × exit_price × fee_rate × 2
slippage_cost = qty × exit_price × slippage_rate × 2
net_pnl = gross_pnl - fee_cost - slippage_cost
```

LONG TP example: entry=100, exit=110, qty=2.5, fee_rate=0.00055:
  gross = (110-100) × 2.5 = 25.00
  fee   = 2.5 × 110 × 0.00055 × 2 = 0.3025
  slip  = 2.5 × 110 × 0.0005 × 2 = 0.275
  net   = 24.4225 ✅ (matches contract spec formula exactly)

LONG SL example: entry=100, exit=98, qty=2.5:
  gross = (98-100) × 2.5 = -5.00
  fee   = 2.5 × 98 × 0.00055 × 2 = 0.2695
  slip  = 2.5 × 98 × 0.0005 × 2 = 0.245
  net   = -5.5145 ✅ (approximately matches risk engine's effective_risk estimate)

---

## Daily Limit Boundaries

`_halt_session_if_needed` calls `risk_engine.check_daily_limits()` which uses
inclusive `>=`/`<=` boundaries (verified in T011 review). ✅
Called AFTER each terminal outcome — correct sequencing. ✅

---

## 4H BTC Boundary Detection

`_is_4h_btc_close` lines 307-313:
  `symbol == "BTCUSDT" AND hour % 4 == 0 AND minute == 0`
Matches Decision A exactly. Initial regime classified before WS loop. ✅

---

## Critical Issues

**None.**

---

## Release Recommendation

**APPROVED** — All step orders, timing conditions, and PnL formulas verified.

---
