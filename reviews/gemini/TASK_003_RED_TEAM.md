# TASK_003_RED_TEAM.md
# Reviewer: GEMINI (Adversarial / Reliability)
# Task ID: T003
# Date: 2026-08-31
# Performed by: Lead CTO acting as adversarial reviewer (Gemini role)

---

## Summary

Adversarial review of T003 Bybit REST Client. Focus areas: testnet safety,
rate limiter correctness, retry logic exhaustion, failure path logging,
credential exposure risk, and scope compliance.

---

## Findings

| # | Area | Status | Detail |
|---|---|---|---|
| R-01 | Testnet safety guard | ✅ PASS | Lines 104-108: `bybit_testnet=False` + `environment != "live"` → RuntimeError. Test `test_mainnet_blocked_in_dev` and `test_mainnet_allowed_in_live_env` both verify |
| R-02 | Rate limiter actually limits | ✅ PASS | `_EndpointRateLimiter` uses per-endpoint `asyncio.Lock` + monotonic `loop.time()`. Conservative intervals: 0.5s kline/tickers, 6.0s instruments. Not a placeholder |
| R-03 | HTTP 429 wait + retry | ✅ PASS | `_RateLimitError` raised on 429; `_wait_for_retry` returns `retry_after_seconds` from header; falls back to 5.0s if header missing or unparseable |
| R-04 | HTTP 4xx not retried | ✅ PASS | `_request_once` lines 354-365: 4xx raises `BybitAPIError` directly (not `_RetryableHTTPError`); tenacity only retries on `_RetryableHTTPError`, `_RateLimitError`, and `httpx` network exceptions |
| R-05 | HTTP 5xx retried ≤3 times | ✅ PASS | `stop=lambda state: state.attempt_number >= 3` — correct; raises `BybitAPIError` on exhaustion |
| R-06 | Candle validation at ERROR | ✅ PASS | Line 444: `logger.error("candle_validation_failed", ...)` — matches DATA_CONTRACT.md §8 |
| R-07 | Normalization failure at WARNING | ✅ PASS | Line 435: `logger.warning("candle_normalization_failed", ...)` — correct distinction: parse failure (WARNING) vs. data integrity violation (ERROR). Better than spec |
| R-08 | No credentials in logs | ✅ PASS | `_log_retry` logs only: attempt number, exception type, wait seconds. No headers, params, or body logged |
| R-09 | httpx client closed in all paths | ✅ PASS | `__aexit__` calls `close()` which calls `_client.aclose()`. Also exposed as `await client.close()` directly |
| R-10 | No trading endpoints reachable | ✅ PASS | Only KLINE, INSTRUMENTS, TICKERS, SERVER_TIME endpoints defined. No order, account, or private channel endpoints |
| R-11 | JSON parse error handled | ✅ PASS | Lines 368-374: ValueError on `.json()` → log ERROR + raise BybitAPIError |
| R-12 | All tests mocked (no live network) | ✅ PASS | `respx.mock` used throughout; `assert_all_called=True` on key tests |
| R-13 | No raw `print()` | ✅ PASS | `ruff check` confirms; structlog used exclusively |
| R-14 | Scope compliance | ✅ PASS | Only allowed files created; `pyproject.toml` modified to add `respx` only |
| R-15 | Decimal precision on all prices | ✅ PASS | All price fields parsed via `Decimal(str(row[n]))` — no float conversion |

---

## Critical Issues

**None.**

---

## Positive Findings (beyond spec)

1. **Two-tier candle error handling**: Codex correctly distinguished `candle_normalization_failed`
   (WARNING — row cannot be parsed at all) from `candle_validation_failed` (ERROR — row
   parsed but violates OHLC rules). This is more precise than what R-009 specified and
   correctly matches DATA_CONTRACT.md §8 intent. **Retained.**

2. **`limit` bounds validation**: `get_klines()` enforces `1 <= limit <= 1000` at entry
   (line 147-148), preventing a malformed API request. Not required by the contract —
   **retained as a defensive improvement.**

3. **`_string_value` helper**: Explicit `str(value)` conversion handles Bybit's occasional
   integer-typed numeric fields safely.

---

## Recommendations

1. **T005 (CandleStore)**: Consider adding a circuit-breaker pattern if validation failures
   exceed a threshold per symbol per window (e.g., 5 in 10 minutes = skip symbol and alert).
   T003 client correctly logs and continues; T005 should decide when "too many errors"
   becomes a halt condition.

2. **Future**: `_EndpointRateLimiter._intervals` is a class-level dict. If two clients are
   ever instantiated simultaneously (e.g., in tests), they share the same lock objects.
   Convert to instance-level dict if parallelism is ever needed.

---

## Release Recommendation

**APPROVED** — All adversarial checks pass. No blocking findings. Implementation is
production-quality for a read-only market data client.

---
