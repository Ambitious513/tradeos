# TASK CONTRACT
# ═══════════════════════════════════════════════════════════════
# Task ID:        T004
# Task Name:      Bybit WebSocket Client
# Status:         READY
# Priority:       P1 — Critical path; T005 depends on this
# Owner Agent:    CODEX
# Reviewer:       GEMINI (reliability / reconnect / failure review)
# CTO Review:     OPUS / FABLE
# Created By:     Lead CTO (Opus/Fable)
# Created Date:   2026-08-31
# Target Branch:  feature/t004-bybit-ws
# Depends On:     T002 APPROVED
# Parallel With:  T003 (Bybit REST Client)
# ═══════════════════════════════════════════════════════════════

---

## 1. Objective

Build a resilient async Bybit WebSocket client that streams real-time 1H and 4H
kline (candle) updates for a dynamic set of symbols.

The client must reconnect automatically on disconnect, detect stale streams,
and emit `Candle` objects to a caller-supplied callback. It must NEVER execute
trades. It must NEVER connect to the mainnet unless `bybit_testnet=False` is
explicitly set.

---

## 2. Background

T002 delivered the foundation. T003 delivers REST (parallel). T004 delivers
WebSocket streaming, which is the primary real-time data source for the live scanner.

The WebSocket client is consumed by T005 (CandleStore), which merges WS real-time
updates with REST historical data into a unified candle buffer.

The most important reliability requirement: the scanner must never silently lose
data. Every disconnect must trigger reconnect; every stale stream must trigger
a health alert.

---

## 3. Source-of-Truth Documents

| Document | Sections Required |
|---|---|
| `AGENTS.md` | All — coding standards, escalation, completion report |
| `docs/DATA_CONTRACT.md` | §2 (WS endpoint), §3.3 (candle types — CRITICAL), §7 (freshness), §10 (failure modes) |
| `docs/SYSTEM_ARCHITECTURE.md` | §3.1 (MarketDataProvider interface) |
| `docs/TEST_SPEC.md` | INT-003, INT-004, REL-002, REL-003 |
| `src/scanner/config.py` | `bybit_testnet`, `environment` |
| `src/scanner/models.py` | `Candle` — especially `is_closed` field |

---

## 4. Scope

Real-time kline streaming via Bybit V5 WebSocket public endpoint.
Subscription management, reconnect handling, stale detection, and candle emission.
No order streams. No private WebSocket channels. No REST calls (use T003 client for that).

---

## 5. Allowed Files / Directories

```
src/scanner/market_data/bybit_ws.py          NEW
src/scanner/market_data/stale_detector.py    NEW
tests/unit/test_bybit_ws.py                 NEW
tests/fixtures/bybit_ws_kline_message.json   NEW
tests/fixtures/bybit_ws_kline_closed.json    NEW
```

Note: `src/scanner/market_data/__init__.py` and `models.py` are created by T003.
If T003 is not yet merged, coordinate — do not duplicate those files.

---

## 6. Forbidden Files / Directories

```
docs/STRATEGY_SPEC.md          — PROTECTED
docs/RISK_SPEC.md              — PROTECTED
AGENTS.md                      — PROTECTED
MASTER_PROJECT_BRIEF.md        — PROTECTED
src/scanner/config.py          — do not modify
src/scanner/models.py          — do not modify
src/scanner/market_data/bybit_rest.py — T003 scope; do not modify
src/scanner/market_data/models.py     — T003 scope; read only
src/scanner/database/          — not in scope
src/scanner/indicators/        — T006 scope
tasks/                         — do not create or modify task files
reviews/                       — do not create review files
skills/                        — no skills this task
```

---

## 7. Requirements

### R-001 — WebSocket Endpoint Configuration

```python
TESTNET_WS_URL = "wss://stream-testnet.bybit.com/v5/public/linear"
MAINNET_WS_URL = "wss://stream.bybit.com/v5/public/linear"

# Selected from ScannerConfig.bybit_testnet at construction.
# Same safety guard as T003 R-011:
# bybit_testnet=False requires environment='live' — raise RuntimeError otherwise.
```

### R-002 — BybitWebSocketClient Class

```python
CanvasCallback = Callable[[Candle], Awaitable[None]]

class BybitWebSocketClient:
    def __init__(
        self,
        config: ScannerConfig,
        on_candle: CanvasCallback,  # called for every candle update (forming or closed)
    ) -> None: ...

    async def subscribe(self, symbols: list[str], intervals: list[str]) -> None:
        # Subscribe to kline streams for given symbols and intervals
        # intervals: ["60"] for 1H, ["240"] for 4H, or both
        # Topic format: "kline.{interval}.{symbol}" e.g. "kline.60.SOLUSDT"
        ...

    async def unsubscribe(self, symbols: list[str], intervals: list[str]) -> None: ...

    async def run_forever(self) -> None:
        # Main loop: connect → subscribe → receive → reconnect on failure
        # Never returns unless explicitly stopped
        ...

    async def stop(self) -> None: ...  # graceful shutdown

    @property
    def is_connected(self) -> bool: ...

    @property
    def subscribed_topics(self) -> frozenset[str]: ...
```

### R-003 — Candle Emission

For every incoming kline WebSocket message:

1. Parse the message into a raw kline dict
2. Normalize to a `Candle` object (from `scanner.models`)
3. Set `is_closed` from the message's `"confirm"` field:
   - `"confirm": true` → `is_closed = True` (candle just closed)
   - `"confirm": false` → `is_closed = False` (candle updating mid-period)
4. **Validate OHLC integrity only** — do NOT check `is_closed` at this layer:
   - OHLC violation or zero/negative price → discard; log **CRITICAL** (per §10)
   - Other OHLC/volume failures → discard; log **ERROR** (per §8)
   - `is_closed` is intentionally excluded from WS-layer validation — forming
     candles (`is_closed=False`) are valid transport updates and must be emitted
5. **Call `on_candle(candle)`** with the result — both forming and closed candles

> **Architecture note:** The `is_closed == True` rule in DATA_CONTRACT.md §8 applies
> to the **strategy pipeline** (T008+), not to the transport layer.
> The WebSocket client is a transport — it emits faithfully.
> CandleStore (T005) is responsible for filtering forming vs closed candles
> before passing to strategy modules.

The caller (`CandleStore`, T005) decides whether to act on forming vs closed candles.
The WebSocket client emits ALL updates — filtering is the caller's responsibility.

### R-004 — Reconnect Logic

```
Disconnect detected (any of):
  - WebSocket closed by server
  - Network error / OSError
  - No message received for > 30 seconds (heartbeat timeout)

On disconnect:
  1. Log WARNING with reason
  2. Wait: exponential backoff — 1s, 2s, 4s, 8s, max 30s
  3. Reconnect to same URL
  4. Re-subscribe to all previously subscribed topics
  5. Log INFO: "Reconnected and re-subscribed to N topics"
  6. Continue run_forever() loop

Maximum reconnect attempts: unlimited (scanner must run 24/7)
```

### R-005 — Heartbeat / Ping-Pong

```
Bybit requires a ping every 20 seconds to keep the connection alive.
Send: {"op": "ping"} every 20s
Expect: {"op": "pong"} response within 5s
If pong not received within 5s: treat as disconnect → reconnect (R-004)
```

### R-006 — Stale Stream Detection (`stale_detector.py`)

```python
class StaleStreamDetector:
    def __init__(self, max_silence_seconds: int = 70) -> None:
        # 70s = 1H candle period + 10s buffer
        ...

    def record_message(self, symbol: str, interval: str) -> None:
        # Update last-seen timestamp for this topic
        ...

    def get_stale_topics(self) -> list[str]:
        # Return list of topics silent for > max_silence_seconds
        ...

    def is_stale(self, symbol: str, interval: str) -> bool: ...
```

When stale topics are detected:
- Log WARNING for each stale topic
- The `run_forever()` loop checks staleness every 60s
- If ANY 4H BTC topic is stale: log ERROR (regime data at risk)

### R-007 — Structured Logging

Use `get_logger("market_data.ws")`:

```
INFO:     Connected to WebSocket URL
INFO:     Subscribed to N topics: [list]
INFO:     Candle received — symbol, interval, is_closed, close_price
INFO:     Reconnected — topics re-subscribed
WARNING:  Disconnect detected — reason, reconnect attempt N
WARNING:  Stale topic — symbol, interval, seconds_since_last_message
ERROR:    Candle validation failure (general) — symbol, field, value
ERROR:    BTC 4H topic stale — regime data at risk
ERROR:    Candle callback raised exception — exception type and message
CRITICAL: OHLC violation (high < low, etc.) — symbol, field, value
CRITICAL: Price = 0 or negative — symbol, field, value
```

> **Correction (2026-08-31):** "Invalid candle discarded — WARNING" was a CTO authoring
> error. DATA_CONTRACT.md §10 (higher authority) specifies CRITICAL for OHLC violations
> and zero/negative prices. DATA_CONTRACT.md §8 specifies ERROR for other validation
> failures. Specific cases in §10 override the general rule in §8.

### R-008 — Callback Exception Isolation

If `on_candle(candle)` raises any exception:
- Log ERROR with exception details
- Do NOT propagate the exception to the WebSocket receive loop
- Continue processing subsequent messages

The WebSocket client must NEVER crash due to a callback bug.

### R-009 — Graceful Shutdown

`stop()` must:
1. Set a stop flag
2. Send WebSocket close frame
3. Wait for `run_forever()` to exit (with timeout)
4. Log INFO: "WebSocket client stopped"

### R-010 — Testnet Safety Guard

Same as T003 R-011:
```python
if not config.bybit_testnet and config.environment != "live":
    raise RuntimeError(
        "bybit_testnet=False requires environment='live'. "
        "Safety guard against accidental mainnet connections."
    )
```

---

## 8. Non-Goals

- Do NOT implement REST API calls (T003)
- Do NOT implement candle storage or caching (T005)
- Do NOT implement private WebSocket channels (account data, orders)
- Do NOT implement order placement of any kind
- Do NOT implement the stale-data policy enforcement (that is T005's job)
- Do NOT implement indicator computation (T006)
- Do NOT modify `scanner.models` or `scanner.config`
- Do NOT implement authentication for private WS channels

---

## 9. Interfaces / Contracts

Downstream tasks (T005) import:

```python
from scanner.market_data.bybit_ws import BybitWebSocketClient
from scanner.market_data.stale_detector import StaleStreamDetector
```

These paths must remain stable after delivery.

---

## 10. Acceptance Criteria

| AC-ID | Criterion | Verification |
|---|---|---|
| AC-001 | Client instantiates with default config | `test_bybit_ws.py::test_client_init` |
| AC-002 | Testnet WS URL used when `bybit_testnet=True` | `test_bybit_ws.py::test_uses_testnet_url` |
| AC-003 | Mainnet blocked in non-live environment | `test_bybit_ws.py::test_mainnet_blocked` |
| AC-004 | Closed candle emitted with `is_closed=True` | `test_bybit_ws.py::test_closed_candle_emitted` |
| AC-005 | Forming candle emitted with `is_closed=False` | `test_bybit_ws.py::test_forming_candle_emitted` |
| AC-006 | Invalid candle discarded; callback not called | `test_bybit_ws.py::test_invalid_candle_discarded` |
| AC-007 | Reconnect triggered on disconnect (mocked) | `test_bybit_ws.py::test_reconnect_on_disconnect` |
| AC-008 | Re-subscription after reconnect | `test_bybit_ws.py::test_resubscribe_after_reconnect` |
| AC-009 | Ping sent every 20s | `test_bybit_ws.py::test_ping_sent` |
| AC-010 | Stale topic detected after silence | `test_bybit_ws.py::test_stale_detection` |
| AC-011 | Callback exception does not crash WS loop | `test_bybit_ws.py::test_callback_exception_isolated` |
| AC-012 | `stop()` exits `run_forever()` cleanly | `test_bybit_ws.py::test_graceful_stop` |
| AC-013 | Structured log on connect | assert via `LogCapture` |
| AC-014 | Structured log on disconnect/reconnect | assert via `LogCapture` |
| AC-015 | `mypy src/ --strict` passes | CI |
| AC-016 | No raw `print()` in new files | `ruff check` |
| AC-017 | No real network calls in tests | all WS mocked |

---

## 11. Required Tests

**File**: `tests/unit/test_bybit_ws.py`

All tests must mock the WebSocket connection. Use `unittest.mock` with `AsyncMock`
or a purpose-built fake WS transport.

```
test_client_init_default
test_uses_testnet_url
test_mainnet_blocked_in_non_live_env
test_closed_candle_parsed_and_emitted
test_forming_candle_parsed_and_emitted
test_invalid_candle_ohlc_violation_discarded
test_invalid_candle_not_forwarded_to_callback
test_disconnect_triggers_reconnect
test_reconnect_resubscribes_all_topics
test_ping_pong_sent_on_schedule
test_pong_timeout_triggers_reconnect
test_stale_detector_record_and_query
test_stale_detector_is_stale_after_silence
test_stale_detector_btc_stale_logs_error
test_callback_exception_does_not_crash_loop
test_stop_exits_run_forever
test_structured_log_on_connect
test_structured_log_on_disconnect
```

**Fixtures** (add to `tests/fixtures/`):
- `bybit_ws_kline_message.json` — forming candle WS message (`"confirm": false`)
- `bybit_ws_kline_closed.json` — closed candle WS message (`"confirm": true`)

---

## 12. Expected Deliverables

```
src/scanner/market_data/bybit_ws.py          NEW
src/scanner/market_data/stale_detector.py    NEW
tests/unit/test_bybit_ws.py                 NEW
tests/fixtures/bybit_ws_kline_message.json   NEW
tests/fixtures/bybit_ws_kline_closed.json    NEW
```

---

## 13. Failure / Escalation Conditions

STOP and escalate if:

| Condition | Action |
|---|---|
| Bybit WS message format differs from expected | Document; do not invent a format |
| `websockets` library behavior makes ping/pong unimplementable as described | Report; propose alternative |
| Reconnect logic creates a feedback loop (e.g., reconnects before subscription completes) | Report; escalate before implementing workaround |
| Any requirement needs changes to `scanner.models` or `scanner.config` | STOP immediately |
| T003 and T004 `__init__.py` conflict (both creating `market_data/__init__.py`) | Coordinate; do not duplicate; escalate if uncertain |

---

## 14. Completion Report Requirements

```
Task:       T004 — Bybit WebSocket Client
Agent:      CODEX
Branch:     feature/t004-bybit-ws

Summary:    [2-4 sentences]

Files Created:      [list]
Files Modified:     [list]

Requirements Completed:  [R-001 ✅ through R-010 ✅]
Tests Run:               [file names and counts]
Tests Passed:            [count]
Tests Failed:            [count + names + errors]

Known Issues:            [none or list]
Out-of-Scope Findings:   [anything T005 needs to know about WS behavior]
Potential Risks:         [reconnect edge cases, Bybit WS quirks]

Recommended Next Step:   T005 (CandleStore) — after T003 also complete
```

---

## 15. Review Plan

### Automated

```bash
pytest tests/unit/test_bybit_ws.py -v --cov=src/scanner/market_data/bybit_ws
ruff check src/scanner/market_data/
black --check src/scanner/market_data/
mypy src/ --strict
```

### GEMINI Adversarial Review

Focus:
- Reconnect loop: can it spin infinitely without backoff? Can it silently not reconnect?
- Callback exception isolation: does a buggy callback actually leave the WS loop running?
- Testnet safety: can `bybit_testnet=False` reach mainnet in paper mode?
- Stale detection: does it actually fire? Is the silence threshold correct?
- Ping timeout: what happens if pong never arrives?
- Thread safety: `asyncio` usage is correct (no blocking calls in async context)

Output: `reviews/gemini/TASK_004_RED_TEAM.md`

### CTO Review

Focus:
- `is_closed` set correctly from `"confirm"` field
- Forming candle passed through (not filtered) — filtering is T005's job
- Stale BTC 4H topic logs ERROR (critical for regime safety)
- Import contracts stable

Output: `reviews/opus/TASK_004_FINAL_REVIEW.md`

---

## 16. Skill Extraction Decision

After T004 approval: **SKILL CANDIDATE** — deferred.

Combine T003 + T004 learnings into `skills/bybit-market-data/SKILL.md` after both
are approved. That skill should cover: REST rate limiting, WS reconnect pattern,
testnet safety guard, candle normalization, and stale detection.

---

## 17. Status / Sign-off

| Role | Name | Status | Date |
|---|---|---|---|
| CTO (task created) | Opus/Fable | ✅ READY | 2026-08-31 |
| Implementation | Codex | ⏳ PENDING | — |
| Adversarial Review | Gemini | ⏳ PENDING | — |
| CTO Final Review | Opus/Fable | ⏳ PENDING | — |
| **Release Decision** | | ⏳ PENDING | — |

---

*End of Task Contract — T004 Bybit WebSocket Client*
