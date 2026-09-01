# TASK_010_RED_TEAM.md
# Reviewer: GEMINI (Adversarial / Reliability)
# Task ID: T010
# Date: 2026-09-01

---

## Summary

Adversarial review of T010 SignalManager. Focus: event batching isolation,
terminal signal list leak, session commit placement, ARMED with no rejection_at,
same-candle retest+trigger, and session_factory failure modes.

---

## Findings

| # | Area | Status | Detail |
|---|---|---|---|
| R-01 | ACTIVE signal not cancelled on regime change | ✅ PASS | `_signals_for_symbol` includes ACTIVE; `_regime_is_invalid` checks it |
| R-02 | Terminal signals removed before `_persist()` | ✅ PASS | `_remove_terminal_signals()` line 129 called before `_persist()`; events already collected |
| R-03 | `session_factory` raises → log ERROR, no crash | ✅ PASS | Lines 524-529: bare `except Exception` logs `signal_persistence_failed` |
| R-04 | `ValueError` in `write_transition` isolated per event | ✅ PASS | Lines 516-522: inner try/except per event; other events in batch still written |
| R-05 | ARMED signal with `rejection_at is None` (defensive) | ✅ PASS | Line 208: `rejection_at is not None` guard prevents nonsensical expiration on an ARMED signal that somehow has no rejection time |
| R-06 | Score outside [20,100] → EXPIRED | ✅ PASS | Lines 410-423 |
| R-07 | Same candle can't satisfy retest + trigger | ✅ PASS | `continue` at line 260 prevents same-candle trigger after same-candle retest |
| R-08 | Signals in terminal state not re-evaluated | ✅ PASS | `_signals_for_symbol` line 539 filters `signal.state not in TERMINAL_STATES` |
| R-09 | `active_signals` returns copy | ✅ PASS | `list(self._active_signals)` at line 109 |
| R-10 | `mark_terminal` rejects non-ACTIVE signal | ✅ PASS | Lines 163-164 |
| R-11 | `mark_terminal` rejects non-terminal state | ✅ PASS | Lines 152-161 |
| R-12 | `_require_signal` raises on unknown UUID | ✅ PASS | Line 548 |
| R-13 | 226 total tests / 30 new | ✅ PASS | Zero regression |
| R-14 | `session.commit()` called once per `_persist()` batch | ✅ PASS | Line 523; outside per-event try/except; entire batch committed atomically |
| R-15 | `commit()` not called by `SignalWriter` | ✅ PASS | `signal_writer.py` has no `commit()` call |
| R-16 | `_makes_new_24h_extreme` uses armed-time snapshot | ✅ PASS | Lines 569/571: `high_24h_at_armed or setup_context.high_24h` — falls back to detection-time level if not yet armed |
| R-17 | `_persist` handles `inspect.isawaitable` for test compatibility | ✅ PASS | Lines 498-502: allows sync CM (mock) and async CM (production) |

---

## Critical Issues

**None.**

---

## Positive Findings

1. **`_PersistenceEvent` union type** (`_CreateEvent | _TransitionEvent`): event
   collection pattern separates "what happened" from "write to DB". This means
   a session failure does not lose the in-memory state — signals are already
   transitioned before `_persist()` is called. DB and in-memory can diverge on
   failure, but in-memory is authoritative and the DB write will be attempted
   on the next cycle. Acceptable for this stage of the pipeline.

2. **`_VALID_TRANSITIONS` dict in `signal_writer.py`**: transition validation is
   centralized in one data structure. Adding or removing a valid transition touches
   exactly one dict entry. Any call with an invalid transition raises `ValueError`
   with a clear message.

3. **`triggered_at` field on `ActiveSignal`**: not in the original contract spec but
   correctly added for the 1H TRIGGERED→EXPIRED expiration window. This is a necessary
   field that the contract omitted.

4. **TRIGGERED → CANCELLED included**: `_VALID_TRANSITIONS[TRIGGERED]` includes
   `CANCELLED`. This correctly handles regime change on a signal that has already
   triggered but not yet been executed by T012.

---

## Recommendations

1. **T012 note**: `mark_active()` updates `signal.estimated_entry` with the
   confirmed entry (line 138). T012 must also pass the confirmed entry to T011
   (RiskEngine) for final position sizing. The estimated entry at scoring time
   and the confirmed entry at execution time may differ slightly.

2. **Unbounded accumulation on persistent DB failure**: if `session_factory`
   fails on every call, signals accumulate in `_active_signals` indefinitely.
   T012 (ScanLoop) should monitor `len(signal_manager.active_signals)` and
   alert if it grows beyond a reasonable bound.

---

## Release Recommendation

**APPROVED** — All adversarial checks pass.

---
