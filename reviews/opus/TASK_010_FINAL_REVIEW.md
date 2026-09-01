# TASK_010_FINAL_REVIEW.md
# Reviewer: Lead CTO (Opus/Fable)
# Task ID: T010
# Date: 2026-09-01

---

## Summary

CTO final review of T010 SignalManager. Verifying all three rulings, complete
state machine coverage, correct event ordering, import contract stability, and
the one contract deviation (triggered_at field).

---

## Findings

| # | Area | Status | Detail |
|---|---|---|---|
| C-01 | 226 tests pass; 30 new | ✅ PASS | Zero regression |
| C-02 | Ruling A: DETECTED transient | ✅ PASS | Active list always holds WATCHING+ |
| C-03 | Ruling B: score at TRIGGERED; trigger.close as entry | ✅ PASS | Lines 375, 405 |
| C-04 | Ruling C: sweep/excess formulae correct | ✅ PASS | Lines 608-618 |
| C-05 | Step order: expire → ARMED → WATCHING → detect | ✅ PASS | Lines 125-128 |
| C-06 | All state transitions irreversible | ✅ PASS | `_transition()` never decrements state |
| C-07 | All transitions logged with reason + timestamp | ✅ PASS | `_transition()` lines 464-491 |
| C-08 | Regime change cancels WATCHING + ARMED + TRIGGERED + ACTIVE | ✅ PASS | `_regime_is_invalid` runs first in `_expire_or_cancel_stale` |
| C-09 | New 24H extreme cancels setup | ✅ PASS | `_makes_new_24h_extreme` uses armed snapshot |
| C-10 | Duplicate block: WATCHING/ARMED/TRIGGERED/ACTIVE | ✅ PASS | Line 317-322 set |
| C-11 | R:R < 2:1 expires before scoring | ✅ PASS | Lines 385-399 |
| C-12 | Score < 80 → EXPIRED | ✅ PASS | Lines 429-437 |
| C-13 | `mark_active()` advances TRIGGERED → ACTIVE | ✅ PASS | Lines 132-146 |
| C-14 | `mark_terminal()` validates ACTIVE state | ✅ PASS | Lines 163-164 |
| C-15 | `SignalWriter` never commits | ✅ PASS | Commit at signal_manager.py:523 only |
| C-16 | `_valid_transitions` covers all spec-required paths | ✅ PASS | Includes TRIGGERED→CANCELLED |
| C-17 | Sonnet + Gemini reviews passed | ✅ PASS | All checks clear |

---

## Contract Deviation: `triggered_at` Field

`ActiveSignal` includes a `triggered_at: datetime | None` field not specified in
the task contract. This is a correct and necessary addition — without it, the
1H TRIGGERED→EXPIRED expiration window (STRATEGY_SPEC §10: "entry must execute
within 1 candle open") cannot be implemented. **Accepted. No correction required.**

---

## Notable Observations

- **Event-then-persist pattern**: in-memory state transitions happen before DB
  writes. DB failure does not roll back in-memory state. This is the right choice
  at this layer — in-memory is authoritative; the DB is a mirror. T012 does not
  depend on DB state for signal routing.

- **`inspect.isawaitable` in `_persist()`**: handles both sync context managers
  (unit tests) and async context managers (production `AsyncSession`). The cast
  is necessary for mypy. This pattern is correct and deliberate.

---

## Release Decision

**APPROVED**

All 21 acceptance criteria verified (AC-001 through AC-021).
226/226 tests pass. All three ruling compliance checks confirmed.
T012 (ScanLoop) is now unblocked.

---
