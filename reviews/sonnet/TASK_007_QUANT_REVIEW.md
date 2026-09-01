# TASK_007_QUANT_REVIEW.md
# Reviewer: SONNET (Quantitative / Statistical)
# Task ID: T007
# Date: 2026-09-01

---

## Summary

Quantitative review of T007 BTC Regime Detector. Focus: classification step
ordering, 24H proxy formula, boundary inclusivity, threshold sign conventions,
and EMA stack logic versus STRATEGY_SPEC.md §3.

---

## Step-Order Verification

Contract R-002 specifies six steps. Verified against `detector.py`:

| Step | Contract | Implementation | Status |
|---|---|---|---|
| 1 | Insufficient data (<200) → UNDEFINED | Lines 49-55 | ✅ PASS |
| 2 | 24H change proxy (candles[-7]) | Lines 57-62 | ✅ PASS |
| 3 | Neutral zone check BEFORE EMA | Line 64 (before line 67) | ✅ PASS |
| 4 | Compute EMA7/14/28/200 | Lines 67-70 | ✅ PASS |
| 5 | Pump/dump check AFTER EMA | Line 77 (after line 70) | ✅ PASS |
| 6 | EMA stack classification | Lines 83-92 | ✅ PASS |

---

## Formula Verification

### 24H Proxy

```
change_pct = (candles[-1].close - candles[-7].close) / candles[-7].close × 100
```

`candles[-7]` is the candle opened 6 × 4H = 24H ago. With 200 candles available,
index -7 is always valid. Correct.

**Quantitative note on the proxy**: Using `candles[-7].close` as "24H ago" is an
approximation. The exact 24H ago open would be `candles[-7].open` (start of that bar)
rather than `candles[-7].close`. However, the task contract explicitly specifies
`candles[-7].close` as the reference, and this is consistent with the convention of
using closing prices throughout the pipeline. **Accepted as specified.**

### Neutral Zone Boundary

Line 64: `abs(change_pct) <= self._neutral_threshold`

Neutral zone is **inclusive** at ±1.5%. Change of exactly 1.5% → NEUTRAL. This is
the correct defensive default — at the exact boundary, no trade is taken. ✅

### Pump/Dump Zone Boundary

Line 77: `change_pct >= self._pump_threshold or change_pct <= -self._dump_threshold`

Pump check is **inclusive** at +8% (≥ 8.0 → UNDEFINED). Dump check uses
`-self._dump_threshold` where `dump_threshold_pct` is stored as positive `8.0`, so
this checks `change_pct <= -8.0`. **Inclusive boundary is conservative and correct.**

**Threshold sign convention**: `_dump_threshold` is stored as a positive Decimal
(e.g. `Decimal("8.0")`). The negation `-self._dump_threshold` is applied at
the comparison site (line 77). This is correct and readable.

### EMA Stack Logic

Lines 83-85:
```python
bullish_stack = ema7 > ema14 > ema28 > ema200
bearish_stack = ema7 < ema14 < ema28 < ema200
if change_pct > self._neutral_threshold and bullish_stack:
    return BULLISH
```

- Bullish: strict `>` chain — any tie returns False → UNDEFINED. Conservative. ✅
- Bearish: strict `<` chain — same. ✅
- `change_pct > neutral_threshold` (line 85): strictly greater after passing the
  `<= neutral_threshold` gate at line 64. Both boundaries are correct.
- Mixed stack falls through all conditions → UNDEFINED (lines 101-103). ✅

---

## Critical Issues

**None.**

---

## Release Recommendation

**APPROVED** — All classification logic matches STRATEGY_SPEC.md §3 exactly.
Step ordering correct. Boundaries conservative and defensively inclusive.

---
