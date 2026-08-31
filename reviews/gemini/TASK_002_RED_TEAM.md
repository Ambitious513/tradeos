# TASK_002_RED_TEAM.md
# Reviewer: GEMINI (Adversarial / Reliability)
# Task ID: T002
# Date: 2026-08-31
# Performed by: Lead CTO acting as adversarial reviewer (Gemini role)

---

## Summary

Adversarial review of T002 Project Foundation. Focus areas:
credential safety, testnet enforcement, config validation, failure modes,
`.gitignore` coverage, and scope compliance.

---

## Findings

| # | Area | Status | Detail |
|---|---|---|---|
| R-01 | `bybit_testnet` defaults True | ✅ PASS | Hardcoded default; test asserts it; env override possible but explicit |
| R-02 | `.env` excluded from git | ✅ PASS | `.env` in `.gitignore`; `.env.*` added during review |
| R-03 | No credentials in committed files | ✅ PASS | All credential fields default to empty string; no values committed |
| R-04 | Config validates negative risk_per_trade | ✅ PASS | `validate_positive_float` rejects ≤ 0; test confirms |
| R-05 | Config validates negative daily_loss_limit | ✅ PASS | `validate_negative_loss_limit` enforces < 0 |
| R-06 | `environment` accepts only valid literals | ✅ PASS | `Literal["development", "paper", "live"]` enforced by pydantic |
| R-07 | `*.pyc` / `__pycache__` excluded | ⚠️ WARN (fixed) | Original `.gitignore` missing `*.pyc` and `.pytest_cache/`; fixed during review |
| R-08 | `src/*.egg-info/` excluded | ⚠️ WARN (fixed) | Added during review; was missing from Codex delivery |
| R-09 | Database connection failure handling | ⚠️ WARN | `connection.py` has no explicit error handling on engine creation failure; acceptable for foundation layer but downstream tasks must add fail-safe |
| R-10 | `Candle` frozen (immutable) | ✅ PASS | `@dataclass(frozen=True)` confirmed; test verifies |
| R-11 | No `print()` in src/ | ✅ PASS | `structlog` used throughout; ruff rule `T201` not yet enabled but manual review confirms no print() |
| R-12 | No ORM imports in `models.py` | ✅ PASS | Only `dataclasses`, `datetime`, `decimal`, `enum` imported |
| R-13 | `NUMERIC(38,18)` for all prices | ✅ PASS | No `Float` columns for monetary values; confirmed |
| R-14 | Scope compliance — no forbidden files touched | ✅ PASS | All changes within allowed list; protected docs untouched |
| R-15 | Strategy constants unchanged from GATE-1 | ✅ PASS | `test_strategy_constants_match_spec` and `test_risk_constants_match_spec` pin all values |

---

## Critical Issues

**None.**

---

## Recommendations

1. **Downstream tasks (T011 Risk Engine)**: Add explicit exception handling in `connection.py`
   for engine creation failures — return `None` / log ERROR rather than raising.
2. **Enable ruff T201 rule** in `pyproject.toml` to formally ban `print()` rather than relying on manual review.
3. Consider adding `ruff.lint.extend-select = ["T201"]` to `pyproject.toml` before T003.

---

## Release Recommendation

**APPROVED_WITH_FIXES** — Two `.gitignore` omissions were corrected during review.
The fixes are minor and already applied. No blocking findings. Task may proceed.

---
