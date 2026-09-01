# TASK_014_QUANT_REVIEW.md
# Reviewer: SONNET (Quantitative / Look-Ahead Bias — MANDATORY)
# Task ID: T014
# Date: 2026-09-01

---

## Summary

Mandatory look-ahead bias audit of T014 BacktestEngine. Ten checklist items
required by the Task Contract. One FAIL — a one-character BTC buffer advance
condition error. All other items pass.

---

## Mandatory Look-Ahead Bias Checklist

| # | Item | Status | Detail |
|---|---|---|---|
| L-01 | Buffer advance is irreversible | ✅ PASS | Line 110-116: ValueError on out-of-order or equal open_time. Deque, no random access. |
| L-02 | candle[i+1] not in sym_buffer at step i | ✅ PASS | Line 252 advances BEFORE line 275 detection. Future candles never advanced. |
| L-03 | BTC buffer not ahead of 1H simulation time | ❌ FAIL | See Critical Issue below. |
| L-04 | 24H stats from revealed candles only | ✅ PASS | SignalManager receives `sym_buffer.get(200)` — buffer contains only revealed candles. |
| L-05 | Indicator values from buffer contents only | ✅ PASS | Indicators receive same `sym_buffer.get(200)` slice. No external data access. |
| L-06 | Entry price is candle[i+1].open, not candle[i].close | ✅ PASS | Line 351: `mark_active(signal.signal_id, candle.open)` where triggered_at < open_time. |
| L-07 | TP/SL detection uses candle high/low (not close) | ✅ PASS | Lines 372-376: candle.low / candle.high for LONG/SHORT. |
| L-08 | Warmup period prevents detection for first N candles | ✅ PASS | Line 258-259: `if index < min_warmup_candles: continue`. |
| L-09 | Sharpe uses 365-day annualisation with Decimal arithmetic | ✅ PASS | Lines 608-622: UTC date grouping; `Decimal(365).sqrt()`; returns 0 if < 2 days. |
| L-10 | Profit factor and win rate handle zero-trade edge cases | ✅ PASS | Lines 552-565: early return with all-zero metrics if no trades. |

---

## Critical Issue — L-03: BTC Buffer Look-Ahead Bias

**Location**: `_advance_btc_to()` line 312

**Current code**:
```python
if btc_candle.open_time > target_time:
    return
```

**Effect**: When processing 1H candle with `open_time = T` (a 4H boundary),
this includes the BTC 4H candle with `open_time = T`. That BTC candle's
CLOSE occurs at T+4H — future data relative to the simulation.

**Live system behaviour**: In the approved ScanLoop, regime is refreshed when
a closed 1H candle arrives at a 4H boundary. The BTC CandleStore at that
moment contains only 4H candles that have been received as fully closed.
The most recent closed 4H BTC candle has `open_time = T−4H` (closed at T).
The 4H candle with `open_time = T` is still forming.

**Correct condition**:
```python
if btc_candle.open_time >= target_time:   # was: > target_time
    return
```

This excludes the forming 4H BTC candle (open_time = T), retaining only
candles with open_time < T. The most recent available would be open_time = T−4H,
which closed at T — consistent with live system data availability.

**Severity**: MODERATE. In trending markets, regime at T and T+4H are usually
the same direction; the bias rarely causes wrong regime classification. In
choppy markets near a regime boundary, it can cause the regime to flip one
4H period earlier than it would in live trading, producing signals that would
not have been generated live.

**Ruling**: One-character fix required before APPROVED status is granted.

---

## Additional Observations (Non-Blocking)

### O-01 — Fee Formula More Accurate Than ScanLoop

`_record_trade()` lines 480-482:
```python
notional = calculation.qty * (signal.estimated_entry + exit_price)
fee_cost = notional * fee_rate
```
This computes `fee = qty × (entry + exit) × fee_rate` — the correct symmetric
formula. The live ScanLoop uses `qty × exit_price × fee_rate × 2` (approximation).
The backtest formula is MORE accurate and should be considered for live PnL
reconciliation in a future task. No action required for T014.

### O-02 — `is_closed` Guard in BTC Advance Is Redundant for Historical Data

Line 315: `if btc_candle.is_closed: btc_buffer.advance(btc_candle)`.
For historical REST data, all candles are closed. The guard is correct
but functionally inert. It provides useful future-proofing if forming BTC
candles are ever passed in. No action required.

---

## Release Recommendation

**APPROVED_WITH_FIXES** — One-character BTC buffer fix required.

Required fix: Line 312: `> target_time` → `>= target_time`.
No other changes required.

---
