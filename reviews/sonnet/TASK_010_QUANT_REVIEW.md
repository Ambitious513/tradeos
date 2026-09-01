# TASK_010_QUANT_REVIEW.md
# Reviewer: SONNET (Quantitative / Statistical)
# Task ID: T010
# Date: 2026-09-01

---

## Summary

Quantitative review of T010 SignalManager. Focus: state transition order,
expiration arithmetic, ruling compliance (A/B/C), score timing, and
sweep/excess formula correctness.

---

## Ruling Compliance

### Ruling A — DETECTED is Transient

`_detect_new_signal()` lines 336-345: signal created with `state=SignalState.WATCHING`.
`DETECTED` never appears in `_active_signals`. DB only sees `DETECTED` via `create_signal()`
which writes the ORM row as DETECTED then immediately appends a DETECTED→WATCHING transition.

✅ PASS

### Ruling B — Score at TRIGGERED, estimated_entry = trigger_candle.close

`_score_and_trigger()` line 375: `estimated_entry = candle.close`. ✅
`ScoreInput.entry_price = estimated_entry` (line 405). ✅
Stop computed from `estimated_entry` (lines 377-383). ✅
R:R checked before scoring (lines 385-399). ✅

### Ruling C — sweep_or_excess_pct Formulae

`_sweep_or_excess_pct()` lines 602-618:

SHORT: `max((rejection.high - high_24h) / high_24h × 100, 0)` ✅
LONG:  `(low_24h - rejection.low) / low_24h × 100` ✅

Zero guards on `high_24h == 0` and `low_24h == 0`. ✅

---

## Step Order in on_candle()

Lines 125-130:
1. `_expire_or_cancel_stale` — regime/level/expiration checks first ✅
2. `_advance_armed` — retest + trigger ✅
3. `_advance_watching` — rejection detection ✅
4. `_detect_new_signal` — new detection last ✅

New detection happens AFTER all existing signals are advanced. A symbol with an ARMED signal cannot generate a second signal on the same cycle (duplicate check at line 312-332).

---

## Expiration Arithmetic

| Window | Code | Op | Status |
|---|---|---|---|
| WATCHING 4H (no rejection) | `candle.open_time - detected_at > timedelta(hours=4)` | `>` | ✅ Strictly > 4H |
| ARMED 4H (no retest) | `candle.open_time - rejection_at > timedelta(hours=4)` | `>` | ✅ |
| ARMED 4H (no trigger after retest) | `candle.open_time - retest_at > timedelta(hours=4)` | `>` | ✅ |
| TRIGGERED 1H (no activation) | `candle.open_time - triggered_at > timedelta(hours=1)` | `>` | ✅ |

All use strictly `>` — consistent and conservative (one extra candle of grace). ✅

---

## Retest-Then-Trigger on Same Candle

Lines 256-263: if retest is JUST found, `continue` is called — entry trigger not
checked on same candle. This is correct: the retest and entry trigger must occur on
separate candles. ✅

---

## Regime Change → CANCELLED (All States)

`_regime_is_invalid()` (line 558-563) is called at the START of `_expire_or_cancel_stale`
for ALL non-terminal signals. WATCHING, ARMED, TRIGGERED, and ACTIVE signals are all
cancelled on regime change. ✅

---

## Critical Issues

**None.**

---

## Release Recommendation

**APPROVED** — All ruling compliance verified. Expiration arithmetic correct.
Step order is correct. Score timing matches Ruling B exactly.

---
