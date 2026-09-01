# TASK_011_RED_TEAM.md
# Reviewer: GEMINI (Adversarial / Reliability)
# Task ID: T011
# Date: 2026-09-01

---

## Summary

Adversarial review of T011 RiskEngine. Focus: division-by-zero guards,
lot_size/tick_size zero guards, post-rounding geometry re-check, layered
effective_risk handling, exception containment, and config field names.

---

## Findings

| # | Area | Status | Detail |
|---|---|---|---|
| R-01 | `tick_size <= 0` guard | ✅ PASS | Line 209: raises ValueError inside `_round_price`; caught by calculate() exception handler |
| R-02 | `lot_size <= 0` guard | ✅ PASS | Line 156: explicit reject before division |
| R-03 | `entry == stop` zero risk distance | ✅ PASS | Line 245: `entry == stop → reject` before division |
| R-04 | `risk_distance_pct = 0` (stop == entry after rounding) | ✅ PASS | Post-rounding geometry re-check at lines 151-155 catches this |
| R-05 | Post-rounding geometry re-check | ✅ PASS | Lines 151-155: rounding could theoretically flip geometry; re-checked |
| R-06 | qty floors to 0.0 (very large risk distance) | ✅ PASS | Line 163: `qty < min_order_qty` catches qty=0 |
| R-07 | effective_risk > 1.5× — WARNING then hard reject | ✅ PASS | Line 174 warns; line 267 rejects in viability. Signal never reaches T012 |
| R-08 | All Decimal arithmetic; no float in sizing | ✅ PASS | Entire calculate() is Decimal; config floats converted via Decimal(str()) at __init__ |
| R-09 | Config field names: `risk_per_trade_usd`, `taker_fee_rate` | ✅ PASS | Lines 67-68: confirmed against actual ScannerConfig |
| R-10 | `approve()` never raises — bare except | ✅ PASS | Lines 111-119: catches Exception; returns RiskDecision(False) |
| R-11 | `calculate()` never raises — bare except | ✅ PASS | Lines 197-204: same pattern |
| R-12 | `check_daily_limits` checks `is_halted` first | ✅ PASS | Line 123 — halt_reason propagated if set |
| R-13 | `DailySession.halt()` is irreversible | ✅ PASS | No un-halt method exists |
| R-14 | `RiskCalculation.stop_price` is rounded price | ✅ PASS | Line 186: `stop_price=rounded_stop` |
| R-15 | `RiskCalculation.take_profit` is rounded price | ✅ PASS | Line 187: `take_profit=rounded_tp` |
| R-16 | 256 total tests / 30 new | ✅ PASS | Zero regression |

---

## Critical Issues

**None.**

---

## Positive Findings

1. **Double geometry validation in `calculate()`**: pre-rounding (lines 143-147)
   and post-rounding (lines 151-155). The pre-rounding check catches obvious
   misconfiguration early; the post-rounding check catches the edge case where
   rounding flips a price to the wrong side of entry. Conservative and correct.

2. **`_reject()` static helper** (line 283): centralises log + return for all
   rejection paths. No rejection path can forget to log.

3. **Layered effective_risk handling**: `calculate()` warns (WARNING) but still
   returns a calculation. `approve()` then calls `_validate_viability()` which
   hard-rejects. The caller of `calculate()` directly (if used standalone) gets
   the calculation with a warning; the caller of `approve()` gets a rejection.
   This is correct layered design — `calculate()` is informational, `approve()` is authoritative.

---

## Recommendations

1. **T012 note**: `DailySession` is passed by reference. T012 must call
   `daily_session.halt(reason)` when `check_daily_limits` returns False — the
   risk engine does NOT auto-halt the session. This is the correct design
   (T011 is pure computation), but T012 must not forget it.

2. **T012 note**: `RiskCalculation.entry_price` is the estimated entry
   (trigger candle close from T010). The actual entry (next candle open) should
   be used for position sizing in live execution. For paper trading this difference
   is acceptable.

---

## Release Recommendation

**APPROVED** — All adversarial checks pass.

---
