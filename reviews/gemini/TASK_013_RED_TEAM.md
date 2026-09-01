# TASK_013_RED_TEAM.md
# Reviewer: GEMINI (Adversarial / Failure Isolation)
# Task ID: T013
# Date: 2026-09-01

---

## Summary

Adversarial review of T013 AlertEngine. Primary focus: failure isolation,
channel independence, 4xx disabling, 5xx retry guard, and edge-case message
formatting. No quant review required (no trading logic).

---

## Findings

| # | Area | Status | Detail |
|---|---|---|---|
| R-01 | Outer `try/except Exception` on every `send_*` | ✅ PASS | Lines 171-186, 195-206, 215-234, 238-247 |
| R-02 | `asyncio.gather(return_exceptions=True)` | ✅ PASS | Line 255-258; exceptions never surface from gather |
| R-03 | Telegram failure does not block Discord | ✅ PASS | Gather isolates each coroutine; return_exceptions=True |
| R-04 | 4xx → `_enabled = False` | ✅ PASS | Lines 66-71; subsequent sends return at line 35 |
| R-05 | 4xx disabled flag survives second call | ✅ PASS | `_enabled` is instance state; persists across calls |
| R-06 | 5xx → single retry guard via `retry=True` flag | ✅ PASS | Lines 78-94; no infinite recursion possible |
| R-07 | 5xx retry exception caught | ✅ PASS | Lines 85-93: TimeoutError + Exception both caught in retry path |
| R-08 | Empty token/chat_id → channel is None | ✅ PASS | Lines 157-162: bool("") = False; channel not constructed |
| R-09 | Empty webhook → channel is None | ✅ PASS | Line 161 |
| R-10 | All channels disabled → debug log + return | ✅ PASS | Lines 252-254 |
| R-11 | `_post()` creates new ClientSession per call | ✅ PASS | Acceptable for low-frequency alerts; no session leak |
| R-12 | ValueError on invalid outcome in position_closed | ✅ PASS | Line 224: caught by outer except at line 233 |
| R-13 | 311 total tests / 26 new | ✅ PASS | Zero regression |
| R-14 | aiohttp in pyproject.toml | ✅ PASS | As declared by Codex |

---

## Findings Requiring Attention (Non-Blocking)

### F-01 — TP PnL hardcoded `+$` prefix

`send_position_closed` at line 219: `pnl = f"+${net_pnl:.4f}"` for TP_HIT.

If `net_pnl` is negative (theoretically possible on a hairline TP with large fees),
the message reads "+$-0.0012" which is confusing. In practice, a negative TP net_pnl
would only occur if fees exceed gross profit — RiskEngine's effective_risk guard
makes this extremely unlikely.

**Severity**: Cosmetic. Non-blocking for paper trading.
**Recommendation**: Replace with `f"${net_pnl:+.4f}"` which correctly renders
sign for any value, or add an explicit `if net_pnl >= 0: "+" else ""` guard.

### F-02 — `asyncio.sleep(1)` inside retry blocks event loop briefly

The `await asyncio.sleep(1)` in `_handle_status` (line 81) delays the gather by 1
second on any 5xx response. In a tight candle-processing cycle this is acceptable
(alerts are non-critical path), but worth noting.

**Severity**: Low. Non-blocking. Alerting is already off the critical path.

---

## Critical Issues

**None.**

---

## Release Recommendation

**APPROVED** — Failure isolation is complete and correct.

---
