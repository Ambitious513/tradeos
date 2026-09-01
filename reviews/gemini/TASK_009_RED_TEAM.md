# TASK_009_RED_TEAM.md
# Reviewer: GEMINI (Adversarial / Reliability)
# Task ID: T009
# Date: 2026-09-01

---

## Summary

Adversarial review of T009 ScoreEngine. Focus: doji body guard, zero-risk guard,
None volume handling, tier ordering, score bounds, and float comparison safety.

---

## Findings

| # | Area | Status | Detail |
|---|---|---|---|
| R-01 | Doji body=0 → 0 pts (not crash) | ✅ PASS | Line 96-97: `if body == 0: return 0` before any division |
| R-02 | Zero risk → 0 pts (not crash) | ✅ PASS | Line 123-124: `if risk == 0: return 0` |
| R-03 | `avg_volume_20 is None` → 0 pts | ✅ PASS | Line 111-112 |
| R-04 | Score sum always in [20, 100] | ✅ PASS | Min: 20 (regime only) + 0×7 = 20; Max: 20+15+15+10+10+10+10+10=100 |
| R-05 | Tier order descending | ✅ PASS | All `_score_decimal_tiers` calls verified highest-first |
| R-06 | RSI float comparisons at boundary (75.0) | ✅ PASS | `rsi_14 >= 75.0` — float comparison at exactly 75.0 is exact (75.0 is representable in IEEE 754) |
| R-07 | `abs(change_24h_pct)` for magnitude | ✅ PASS | Line 31 — handles dump (negative) and pump (positive) symmetrically |
| R-08 | Volume uses strict `>` not `>=` | ✅ PASS | Lines 113-115 — matches spec wording ">" |
| R-09 | No logging inside score functions | ✅ PASS | Zero logger calls in score_engine.py |
| R-10 | No state in ScoreEngine | ✅ PASS | All functions are module-level; `ScoreInput` is frozen |
| R-11 | `ScoreInput` frozen | ✅ PASS | `@dataclass(frozen=True)` line 10 |
| R-12 | SHORT wick direction | ✅ PASS | `candle.high - candle.open` — correct upper wick |
| R-13 | LONG wick direction | ✅ PASS | `candle.open - candle.low` — correct lower wick |
| R-14 | Score returns int, not Decimal | ✅ PASS | `_score_decimal_tiers` returns `int`; sum of ints = int |
| R-15 | 196 total tests / 24 new; 96% coverage | ✅ PASS | Zero regression |

---

## Critical Issues

**None.**

---

## Positive Findings

1. **`_score_decimal_tiers` helper**: a single function eliminates 6 nearly-identical
   if-elif chains. Any future tier change touches exactly one call site. Well-designed.

2. **Score bounds**: minimum score is 20 (regime always awarded). A setup reaching the
   score stage will always get at least 20 points. This is architecturally important —
   T010 can assert `score >= 20` as a sanity check after calling `compute_score`.

3. **Volume strict `>`**: correctly matches spec wording ("volume > 1.5×") rather than
   the common mistake of using `>=`. A setup with volume exactly equal to 1.5× average
   earns 0 pts for that dimension, not 10 pts.

---

## Recommendations

1. **T010 note**: caller must supply `sweep_or_excess_pct` correctly:
   - SHORT: `high_excess_pct = (candle.high - high_24h) / high_24h * 100` (if above 24H high)
     OR `0.0` if candle.high never exceeded (proximity only).
   - LONG: `sweep_depth_pct = (low_24h - candle.low) / low_24h * 100`
   T010 must document which value it passes and when.

2. **Maximum score validation**: T010 should assert `0 <= score <= 100` defensively,
   since `compute_score` is pure and cannot validate its own output against impossible inputs.

---

## Release Recommendation

**APPROVED** — All adversarial checks pass.

---
