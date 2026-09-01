# TASK_009_QUANT_REVIEW.md
# Reviewer: SONNET (Quantitative / Statistical)
# Task ID: T009
# Date: 2026-09-01

---

## Summary

Quantitative review of T009 ScoreEngine. Focus: SCORE-001 tier correctness,
highest-tier-only selection, directional RSI logic, wick direction, and
volume strict vs inclusive comparison.

---

## Tier Verification — SCORE-001

### BTC Regime Alignment (20 pts, always)
Line 30: hardcoded `20` in the sum — correct. A setup cannot exist without regime
alignment, so this is always awarded. ✅

### 24H Move Magnitude (up to 15 pts)

Spec: `>= 12%: 15; >= 10%: 10; >= 8%: 5`

```python
_score_decimal_tiers(abs(change_24h_pct),
    ((Decimal("12"), 15), (Decimal("10"), 10), (Decimal("8"), 5))
)
```

`_score_decimal_tiers` iterates descending; first match wins → highest tier only. ✅
Uses `abs(change_24h_pct)` — handles both pump and dump symmetrically. ✅
All thresholds inclusive (`>=`). ✅

### RSI Extreme (up to 15 pts)

Spec: `>= 80 or <= 20: 15; >= 77 or <= 23: 10; >= 75 or <= 25: 5`

SHORT path (lines 61-67): `>= 80` → 15; `>= 77` → 10; `>= 75` → 5. ✅
LONG path (lines 68-74): `<= 20` → 15; `<= 23` → 10; `<= 25` → 5. ✅
Both use `float` comparisons (RSI is `float`). ✅
Highest tier returned first due to if-elif structure. ✅

### EMA Extension (up to 10 pts)

Spec: `>= 5%: 10; >= 4%: 7; >= 3%: 5`

```python
_score_decimal_tiers(extension_pct, ((Decimal("5"), 10), (Decimal("4"), 7), (Decimal("3"), 5)))
```
Uses `SetupContext.ema_extension_pct` — already direction-adjusted (positive for both
SHORT and LONG by `compute_ema_extension`). ✅

### Sweep / High Excess (up to 10 pts)

Spec: `>= 0.5%: 10; >= 0.25%: 5; >= 0.1%: 2`

```python
_score_decimal_tiers(sweep_or_excess_pct,
    ((Decimal("0.5"), 10), (Decimal("0.25"), 5), (Decimal("0.1"), 2))
)
```
Caller (T010) is responsible for computing the directional value and passing it in.
0.1% tier → 2 pts (not 0, not 5). ✅

### Rejection Wick (up to 10 pts)

Spec: `wick >= 2× body: 10; wick >= 1.5× body: 5`

Line 96: `body = abs(candle.close - candle.open)` — direction-neutral body. ✅
SHORT wick: `candle.high - candle.open` (upper wick). ✅
LONG wick: `candle.open - candle.low` (lower wick). ✅

**Note on SHORT wick formula**: SHORT-005 defines `upper_wick = candle.high - candle.open`.
For a bearish candle, `candle.open > candle.close`, so upper wick is above open.
The formula `candle.high - candle.open` is correct for bearish candles. ✅

Doji guard (line 96-97): `if body == 0: return 0` — correct, avoids division. ✅

### Volume Confirmation (up to 10 pts)

Spec: `rejection vol > 1.5× avg: 10; > 1.2× avg: 5`

Note: **strictly greater** (`>`) per spec, not `>=`. Lines 113-116 use `>`. ✅
`avg_volume_20 is None → 0 pts` (line 111-112). ✅ Matches ruling.

### R:R Ratio (up to 10 pts)

Spec: `>= 3:1: 10; >= 2.5:1: 7; >= 2:1: 5`

Lines 122-129: `abs(reward) / abs(risk)`. ✅
Zero-risk guard (lines 123-124). ✅
Minimum 2:1 → 5 pts; the `check_minimum_rr` in T008 ensures setup is disqualified
at < 2:1 before scoring, so `_score_rr` returning 0 at < 2:1 is the correct safety net.

---

## `_score_decimal_tiers` Helper

Lines 132-137: Iterates descending threshold list; returns first matching score.
- Descending order is caller's responsibility (tiers must be passed highest-first).
- All call sites verified: `(12,15),(10,10),(8,5)` — descending ✅

---

## Critical Issues

**None.**

---

## Release Recommendation

**APPROVED** — All 8 SCORE-001 criteria implemented at the correct tiers with
correct direction-awareness and highest-tier-only selection.

---
