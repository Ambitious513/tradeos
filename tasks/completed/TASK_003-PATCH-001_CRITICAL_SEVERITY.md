# TASK CONTRACT
# ═══════════════════════════════════════════════════════════════
# Task ID:        T003-PATCH-001
# Task Name:      REST Client CRITICAL Log Severity Patch
# Status:         APPROVED — 2026-08-31
# Priority:       P1 — must complete before T005 activates
# Owner Agent:    CODEX
# Reviewer:       CTO (self-review permitted for targeted patch only)
# Created By:     Lead CTO (Opus/Fable)
# Created Date:   2026-08-31
# Target Branch:  fix/t003-patch-001-critical-severity
# Depends On:     T003 APPROVED, T004 APPROVED
# Blocks:         T005
# ═══════════════════════════════════════════════════════════════

---

## 1. Objective

Apply a targeted log-severity correction to `bybit_rest.py`: OHLC violations and
zero/negative price candles must be logged at CRITICAL, not ERROR.

This patch resolves the non-blocking deviation identified during T004 review.

---

## 2. Background

During T004 review, a secondary finding was raised:

> T003 `bybit_rest.py` logs `ERROR` for all candle validation failures.
> DATA_CONTRACT.md §10 requires `CRITICAL` for:
> - Price = 0 or negative
> - OHLC violation (high < low, etc.)
>
> The candle is correctly discarded in all cases — only the log severity is wrong.
> T003 was APPROVED because safety behavior was correct. This patch fixes severity only.

---

## 3. Source-of-Truth Documents

| Document | Sections Required |
|---|---|
| `docs/DATA_CONTRACT.md` | §8 (severity table), §10 (CRITICAL classification) |
| `src/scanner/market_data/bybit_rest.py` | `_normalize_candle()`, `_invalid_candle_field()` |
| `tests/unit/test_bybit_rest.py` | `test_invalid_candle_*` tests |

---

## 4. Scope

One file changed in `src/`. One file updated in `tests/`. Nothing else.

---

## 5. Allowed Files / Directories

```
src/scanner/market_data/bybit_rest.py    MODIFIED — severity only
tests/unit/test_bybit_rest.py           MODIFIED — assert CRITICAL in relevant tests
```

---

## 6. Forbidden Files / Directories

Everything not listed in Section 5. In particular:
```
src/scanner/market_data/bybit_ws.py        — do not touch
src/scanner/market_data/stale_detector.py  — do not touch
src/scanner/market_data/models.py          — do not touch
src/scanner/config.py                      — do not touch
src/scanner/models.py                      — do not touch
docs/                                      — do not touch
tasks/                                     — do not touch
reviews/                                   — do not touch
```

---

## 7. Requirements

### R-001 — Updated Severity in `_normalize_candle()`

In `bybit_rest.py`, the `_normalize_candle()` method currently calls
`logger.error("candle_validation_failed", ...)` for all validation failures.

After this patch, severity must depend on the failure type:

```python
# _invalid_candle_field() returns the first failing field name (str) or None
# Patch: the caller must now also know the severity.

# Required logic after patch:

CRITICAL_FIELDS = {"open", "high", "low"}  # price=0 or OHLC violation

invalid_field = self._invalid_candle_field(candle)
if invalid_field is not None:
    if invalid_field in CRITICAL_FIELDS:
        logger.critical(
            "candle_validation_failed",
            symbol=symbol,
            field=invalid_field,
            value=str(getattr(candle, invalid_field)),
        )
    else:
        logger.error(
            "candle_validation_failed",
            symbol=symbol,
            field=invalid_field,
            value=str(getattr(candle, invalid_field)),
        )
    return None
```

> **Why open/high/low only?**
> - `open <= 0` → price is zero or negative → CRITICAL (DATA_CONTRACT.md §10)
> - `high < open` or `high < close` → OHLC violation → CRITICAL (DATA_CONTRACT.md §10)
> - `low > open` or `low > close` or `low > high` → OHLC violation → CRITICAL (DATA_CONTRACT.md §10)
> - `volume < 0` or `turnover < 0` → anomalous but not CRITICAL → ERROR
> - `is_closed` check in REST client: already asserts `is_closed=True` during construction;
>   this field is set to True by the client, so this check never fails — keep as-is

### R-002 — Updated Tests

Update `tests/unit/test_bybit_rest.py`:

1. `test_invalid_candle_discarded` (AC-007): verify CRITICAL is logged when high < low
2. Add `test_invalid_candle_logs_critical` (AC-021): assert `log_level == "critical"` for
   OHLC violation via structlog `capture_logs`
3. Add `test_zero_price_logs_critical`: assert `log_level == "critical"` for open=0
4. Add `test_negative_volume_logs_error`: assert `log_level == "error"` for volume=-1

No existing tests may be removed. Total test count must be ≥ 25.

---

## 8. Non-Goals

- Do NOT refactor `_normalize_candle()` beyond the severity change
- Do NOT change the discard behavior (candle is already correctly discarded)
- Do NOT change any REST endpoint logic
- Do NOT touch any other file

---

## 9. Interfaces / Contracts

No interface changes. Public API is identical before and after.

---

## 10. Acceptance Criteria

| AC-ID | Criterion | Verification |
|---|---|---|
| AC-001 | OHLC violation (H < L) → `logger.critical()` called | `test_invalid_candle_logs_critical` |
| AC-002 | Price = 0 → `logger.critical()` called | `test_zero_price_logs_critical` |
| AC-003 | Volume < 0 → `logger.error()` called (not critical) | `test_negative_volume_logs_error` |
| AC-004 | Candle still discarded in all cases | existing tests still pass |
| AC-005 | Full suite ≥ 65 tests pass (62 + 3 new) | `pytest tests/ -v` |
| AC-006 | `mypy src/ --strict` passes | CI |
| AC-007 | `ruff check src/` passes | CI |

---

## 11. Required Tests

```
test_invalid_candle_logs_critical       # OHLC violation → log level is "critical"
test_zero_price_logs_critical           # open=0 → log level is "critical"
test_negative_volume_logs_error         # volume<0 → log level is "error"
```

All via structlog `capture_logs` context manager.

---

## 12. Expected Deliverables

```
src/scanner/market_data/bybit_rest.py    MODIFIED (severity only; ~10 lines changed)
tests/unit/test_bybit_rest.py           MODIFIED (3 new tests added)
```

---

## 13. Failure / Escalation Conditions

If the severity fix requires structural changes beyond `_normalize_candle()`, STOP and
escalate. The patch must be surgical — if it cannot be done in ~10 lines, something is wrong.

---

## 14. Completion Report Requirements

```
Task:       T003-PATCH-001
Agent:      CODEX
Summary:    [1-2 sentences]

Files Modified:   [list]
Lines Changed:    [approximate]
Tests Added:      [3 tests listed by name]
Tests Run:        pytest tests/ -v — [N] passed
Tests Failed:     0
```

---

## 15. Review Plan

CTO self-review only (AGENTS.md §3.1 exception for targeted patches < 20 lines).
No separate Gemini review required for this patch.

---

## 16. Skill Extraction Decision

N/A — patch too small to warrant a skill.

---

## 17. Status / Sign-off

| Role | Name | Status | Date |
|---|---|---|---|
| CTO (task created) | Opus/Fable | ✅ READY | 2026-08-31 |
| Implementation | Codex | ⏳ PENDING | — |
| Release Decision | CTO | ⏳ PENDING | — |

---

*End of Task Contract — T003-PATCH-001 REST Client CRITICAL Log Severity Patch*

