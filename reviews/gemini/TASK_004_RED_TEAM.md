# TASK_004_RED_TEAM.md
# Reviewer: GEMINI (Adversarial / Reliability)
# Task ID: T004
# Date: 2026-08-31
# Performed by: Lead CTO acting as adversarial reviewer (Gemini role)

---

## Summary

Adversarial review of T004 Bybit WebSocket Client. Focus areas: testnet safety,
reconnect loop correctness, ping/pong timeout handling, callback isolation,
stale detection integrity, three-tier severity enforcement, and scope compliance.

---

## Findings

| # | Area | Status | Detail |
|---|---|---|---|
| R-01 | Testnet safety guard | ✅ PASS | Lines 53-57: identical guard to T003; `bybit_testnet=False` requires `environment="live"` |
| R-02 | Reconnect never spins without backoff | ✅ PASS | Line 127: `delay = min(2**(attempt-1), 30)` → 1s, 2s, 4s, 8s, 16s, 30s cap; `asyncio.sleep()` called before re-connect |
| R-03 | Reconnect is unlimited | ✅ PASS | `while not self._stop_requested` — runs until `stop()` called; no max-attempt cap |
| R-04 | Re-subscription after reconnect | ✅ PASS | Lines 114-115: after connection established, if `_topics` non-empty, `_send_operation("subscribe", ...)` called |
| R-05 | Ping sent every 20s | ✅ PASS | Lines 171-175: `loop.time()` monotonic check; `_send_raw({"op":"ping"})` |
| R-06 | Pong timeout triggers reconnect | ✅ PASS | `_await_pong()` raises `asyncio.TimeoutError` after 5s; caught by outer reconnect handler (line 123) |
| R-07 | Callback exception cannot crash WS loop | ✅ PASS | Lines 254-259: bare `except Exception` in `_emit_kline`; logs ERROR and continues |
| R-08 | `is_closed` NOT validated at transport | ✅ PASS | `_validation_failure()` checks open≤0, OHLC, volume<0, turnover<0 — no `is_closed` check |
| R-09 | Forming candles emitted | ✅ PASS | `confirm=false` → `is_closed=False`; `_boolean_value()` enforces actual bool type (not truthy string) |
| R-10 | CRITICAL for price=0/OHLC violation | ✅ PASS | Lines 309-318: `logger.critical(...)` for open≤0, high violations, low violations |
| R-11 | ERROR for volume/turnover < 0 | ✅ PASS | Lines 319-322: `logger.error("candle_validation_failed", ...)` |
| R-12 | WARNING for parse failure | ✅ PASS | Lines 290-294: `logger.warning("candle_normalization_failed", ...)` |
| R-13 | BTC 4H stale → ERROR | ✅ PASS | Lines 344-350: `symbol == "BTCUSDT" and interval == "240"` → `logger.error("btc_4h_topic_stale", regime_data_at_risk=True)` |
| R-14 | Other stale → WARNING | ✅ PASS | Lines 351-352: `logger.warning("stale_topic", ...)` |
| R-15 | `stop()` waits with timeout | ✅ PASS | `asyncio.shield(run_task)` prevents cancellation; `asyncio.wait_for(..., 5s)` prevents hang |
| R-16 | No trading/private endpoints | ✅ PASS | Only public kline stream; no account/order topics |
| R-17 | No raw `print()` | ✅ PASS | `ruff check` confirmed; structlog used exclusively |
| R-18 | Scope compliance | ✅ PASS | 5 new files only; no forbidden files touched |
| R-19 | 62 tests pass; no live network | ✅ PASS | `_WebSocketTransport` Protocol enables full mocking without real WS |

---

## Critical Issues

**None.**

---

## Positive Findings (beyond spec)

1. **`_WebSocketTransport` Protocol** (lines 35-46): dependency-injection via Protocol
   makes the client fully testable without monkey-patching `websockets`. This is the
   correct architectural choice — the client never imports a concrete transport in tests.

2. **`_boolean_value()` enforces `isinstance(value, bool)`** (line 384): prevents a
   string `"true"` or integer `1` from the `confirm` field being silently accepted as
   a boolean. Bybit could theoretically change the field type; this guard would catch it.

3. **`watch_topic` uses `setdefault`** (line 18): re-subscribing does not reset the
   staleness clock. If T005 calls `subscribe()` after reconnect, topics that were already
   streaming won't appear artificially fresh.

4. **`asyncio.shield` in `stop()`** (line 156): prevents `wait_for` from cancelling the
   run task if the timeout fires. The run loop exits cleanly via `_stop_requested` flag
   rather than being forcibly cancelled.

5. **`_await_pong()` processes intervening messages** (lines 205-210): kline updates
   received while waiting for pong are not discarded — they are handled normally. No
   data loss during heartbeat cycles.

---

## Recommendations

1. **T005 (CandleStore)**: Subscribe before calling `run_forever()` as noted in the
   Codex out-of-scope finding. This is the correct usage pattern.
2. **Integration tests**: Unit tests are mocked only. Testnet integration verification
   required per TEST_SPEC.md INT-003 and INT-004 before paper trading.
3. **`_log_stale_topics`**: Symbol hardcoded to `"BTCUSDT"`. Verify this matches the
   universe symbol naming in T005 (e.g., confirm it is not `"BTC-USDT"` or `"BTCPERP"`).

---

## Release Recommendation

**APPROVED** — All adversarial checks pass. Implementation quality exceeds the contract.
No blocking findings.

---
