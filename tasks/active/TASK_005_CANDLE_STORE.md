# TASK CONTRACT
# ═══════════════════════════════════════════════════════════════
# Task ID:        T005
# Task Name:      CandleStore + UniverseManager
# Status:         READY
# Priority:       P1 — Critical path; T006, T007 depend on this
# Owner Agent:    CODEX
# Reviewer:       GEMINI (data integrity / staleness / gap-fill review)
# CTO Review:     OPUS / FABLE
# Created By:     Lead CTO (Opus/Fable)
# Created Date:   2026-08-31
# Target Branch:  feature/t005-candle-store
# Depends On:     T003 APPROVED, T004 APPROVED, T003-PATCH-001 APPROVED
# Parallel With:  nothing — T005 activates T006 and T007 in parallel
# ═══════════════════════════════════════════════════════════════

---

## 1. Objective

Build two tightly-coupled components:

1. **UniverseManager** — fetches all active USDT linear perpetual symbols from Bybit,
   applies the volume filter (turnover_24h ≥ $50,000,000), and provides a refreshable
   list of tradeable symbols. BTC is always included regardless of volume.

2. **CandleStore** — maintains a rolling in-memory buffer of closed candles per symbol
   per timeframe. Subscribes to the WS client (T004) for live updates, uses the REST
   client (T003) for historical pre-fill and gap-filling. Provides strategy modules with
   a clean slice of closed candles via a single interface.

Together these components form the scanner's market data layer — the single source of
truth for all candle data consumed by indicators, regime detection, and signal strategy.

---

## 2. Background

T003 (REST) and T004 (WS) are transport clients — they fetch and emit raw candles.
T005 is the integration layer: it coordinates both transports, fills gaps, enforces
closed-candle filtering before strategy, and provides a unified query interface.

Downstream consumers:
- T006 (Indicators) — calls `get_closed_candles(symbol, interval, n)` for indicators
- T007 (RegimeDetector) — calls `get_closed_candles("BTCUSDT", "240", 60)` for EMA stack
- T008-T010 (Strategy) — calls `get_closed_candles(symbol, "60", 100)` for setups
- T014 (Backtest Engine) — uses a separate feed; does NOT use CandleStore at runtime

---

## 3. Source-of-Truth Documents

| Document | Sections Required |
|---|---|
| `AGENTS.md` | All — coding standards, escalation, completion report |
| `docs/DATA_CONTRACT.md` | §7 (freshness), §8 (validation), §9 (history), §10 (failure modes), §11 (live vs backtest) |
| `docs/SYSTEM_ARCHITECTURE.md` | §3.1 (MarketDataProvider), §3.2 (UniverseManager), §3.3 (CandleStore) |
| `docs/STRATEGY_SPEC.md` | §2 (UNIVERSE-001: volume ≥ $50M; BTC always included) |
| `docs/TEST_SPEC.md` | INT-001, INT-002, INT-005, INT-006, REL-004 |
| `src/scanner/config.py` | `universe_min_volume_usd`, `bybit_testnet`, `environment` |
| `src/scanner/models.py` | `Candle`, `Regime` |
| `src/scanner/market_data/bybit_rest.py` | `BybitRESTClient`, `Ticker24H` |
| `src/scanner/market_data/bybit_ws.py` | `BybitWebSocketClient`, `CanvasCallback` |
| `src/scanner/market_data/models.py` | `SymbolInfo`, `Ticker24H` |

---

## 4. Scope

UniverseManager + CandleStore only. No indicator computation. No regime detection.
No signal generation. No database writes (candles are in-memory only for now).

---

## 5. Allowed Files / Directories

```
src/scanner/candle_store/__init__.py           NEW
src/scanner/candle_store/candle_store.py       NEW
src/scanner/candle_store/universe_manager.py   NEW
tests/unit/test_candle_store.py               NEW
tests/unit/test_universe_manager.py           NEW
tests/fixtures/bybit_tickers_universe.json    NEW  (extended fixture with volume data)
```

---

## 6. Forbidden Files / Directories

```
docs/STRATEGY_SPEC.md         — PROTECTED
docs/RISK_SPEC.md             — PROTECTED
AGENTS.md                     — PROTECTED
MASTER_PROJECT_BRIEF.md       — PROTECTED
src/scanner/market_data/      — do not modify (T003/T004 scope)
src/scanner/config.py         — do not modify
src/scanner/models.py         — do not modify
src/scanner/database/         — not in scope (T005 is in-memory only)
src/scanner/indicators/       — T006 scope
src/scanner/regime/           — T007 scope
src/scanner/strategy/         — T008-T010 scope
tasks/                        — do not create or modify task files
reviews/                      — do not create review files
```

---

## 7. Requirements

### R-001 — UniverseManager

```python
class UniverseManager:
    def __init__(self, rest_client: BybitRESTClient, config: ScannerConfig) -> None: ...

    async def refresh(self) -> list[str]:
        """Fetch current tickers, apply volume filter, always include BTCUSDT.
        Returns sorted list of symbol strings. Caches result internally."""
        ...

    @property
    def symbols(self) -> list[str]:
        """Return the most recently cached symbol list. Empty before first refresh."""
        ...

    @property
    def last_refreshed_at(self) -> datetime | None:
        """Return the UTC timestamp of the most recent successful refresh."""
        ...
```

**Volume filter rule** (STRATEGY_SPEC.md UNIVERSE-001):
```
Include symbol if:
  ticker.turnover_24h >= config.universe_min_volume_usd (default 50,000,000)
  AND ticker symbol ends with "USDT"
  AND symbol is not in a configurable exclusion list (default empty)

Always include "BTCUSDT" regardless of volume.

On refresh failure:
  If a previous universe exists: log WARNING; return cached list
  If no previous universe exists: log ERROR; raise UniverseRefreshError
```

**Refresh frequency**: UniverseManager does not self-refresh. The caller (scan loop, T012)
is responsible for calling `refresh()` on a schedule. UniverseManager is stateless beyond
its cache.

### R-002 — UniverseRefreshError

```python
class UniverseRefreshError(Exception):
    """Universe fetch failed and no cached universe is available."""
```

### R-003 — CandleStore

```python
class CandleStore:
    def __init__(
        self,
        rest_client: BybitRESTClient,
        ws_client: BybitWebSocketClient,
        config: ScannerConfig,
        buffer_size: int = 200,   # closed candles retained per symbol per timeframe
    ) -> None: ...

    async def initialize(
        self,
        symbols: list[str],
        intervals: list[str],   # e.g. ["60", "240"]
    ) -> None:
        """Pre-fill buffers via REST, then subscribe via WS. Must be called before
        run_forever(). Symbols + intervals define the full subscription set."""
        ...

    async def run_forever(self) -> None:
        """Start the WebSocket run loop. Blocks until stop() is called."""
        ...

    async def stop(self) -> None:
        """Stop the WebSocket client gracefully."""
        ...

    def get_closed_candles(
        self,
        symbol: str,
        interval: str,
        n: int,
    ) -> list[Candle]:
        """Return the n most recent CLOSED candles for symbol/interval,
        ordered oldest-first. Returns fewer than n if buffer not yet full.
        Never raises — returns empty list if symbol/interval unknown."""
        ...

    def is_ready(self, symbol: str, interval: str, min_candles: int) -> bool:
        """Return True if the buffer has at least min_candles closed candles."""
        ...

    @property
    def subscribed_symbols(self) -> frozenset[str]: ...
```

### R-004 — Initialization (REST Pre-fill)

On `initialize(symbols, intervals)`:

1. For each `(symbol, interval)` pair:
   - Call `rest_client.get_klines(symbol, interval, limit=buffer_size)`
   - Store all returned closed candles in the buffer (oldest first)
   - Log INFO: `"candle_buffer_prefilled"`, symbol, interval, count
2. Subscribe to all `(symbols × intervals)` topics via `ws_client.subscribe()`
3. Log INFO: `"candle_store_initialized"`, symbol_count, interval_count

REST pre-fill failures (BybitAPIError) must be handled per-symbol:
- Log WARNING for the symbol; continue to next symbol
- A symbol that fails pre-fill will have an empty buffer — `is_ready()` returns False
- Do NOT abort initialization for one symbol's failure

**BTC must always be pre-filled** — if BTCUSDT pre-fill fails, log ERROR (not WARNING)
because regime detection will be unavailable.

### R-005 — Live Updates (WebSocket Callback)

The `on_candle` callback registered with `BybitWebSocketClient` must:

1. Ignore forming candles (`candle.is_closed == False`) — do NOT add to buffer
2. Accept closed candles (`candle.is_closed == True`):
   - Validate the candle is not a duplicate (same `open_time` already in buffer)
   - Detect gaps: if `open_time` skips more than one candle period, trigger gap-fill
   - Append to buffer (FIFO — drop oldest if buffer is full)
   - Log INFO: `"candle_closed_stored"`, symbol, interval, open_time

Forming candle handling:
- Track the most recent forming candle per (symbol, interval) separately
- Expose via `get_forming_candle(symbol, interval) -> Candle | None` (optional, for future display)
- Do NOT include forming candles in `get_closed_candles()` output

### R-006 — Gap Detection and Fill

A gap is detected when:
```
new_candle.open_time - latest_stored_candle.open_time > 1 × candle_period_ms
```

Candle period (ms):
```python
INTERVAL_TO_MS = {"60": 3_600_000, "240": 14_400_000}
```

On gap detected:
1. Log WARNING: `"candle_gap_detected"`, symbol, interval, gap_candles (count)
2. Call `rest_client.get_klines(symbol, interval, limit=min(gap_count+5, 200))`
   with `end_time_ms=new_candle.open_time_ms - 1`
3. Insert gap-fill candles into buffer (deduplication by `open_time`)
4. Log INFO: `"candle_gap_filled"`, symbol, interval, filled_count
5. Then append the new candle

Gap fill failures (BybitAPIError) — log ERROR; accept the new candle anyway.

### R-007 — Closed-Candle Enforcement for Strategy

`get_closed_candles()` must ONLY return candles where `is_closed == True`.

If a non-closed candle somehow enters the buffer (defensive check):
- Log ERROR: `"forming_candle_in_buffer"`, symbol, interval
- Do NOT return it from `get_closed_candles()`

This enforces the DATA_CONTRACT.md §8 `is_closed == True` rule at the strategy boundary.

### R-008 — Thread Safety

All buffer reads and writes occur within a single `asyncio` event loop. No `threading`
primitives required. `get_closed_candles()` is synchronous and called from coroutines
within the same event loop — this is safe by design.

Do NOT use `asyncio.Lock` for buffer access — it is unnecessary and adds latency.

### R-009 — Structured Logging

Use `get_logger("candle_store")` for CandleStore and `get_logger("universe_manager")`
for UniverseManager.

```
INFO:    candle_buffer_prefilled — symbol, interval, count
INFO:    candle_store_initialized — symbol_count, interval_count
INFO:    candle_closed_stored — symbol, interval, open_time (ISO string)
INFO:    candle_gap_filled — symbol, interval, filled_count
WARNING: candle_gap_detected — symbol, interval, gap_candles
WARNING: prefill_failed — symbol, interval, exception_type (non-BTC)
WARNING: universe_refresh_used_cache — reason
ERROR:   btc_prefill_failed — symbol, interval, exception_type
ERROR:   forming_candle_in_buffer — symbol, interval (defensive check)
ERROR:   gap_fill_failed — symbol, interval, exception_type
ERROR:   universe_refresh_failed_no_cache — exception_type
```

---

## 8. Non-Goals

- Do NOT implement indicator computation (T006)
- Do NOT implement regime detection (T007)
- Do NOT implement signal detection (T008-T010)
- Do NOT write candles to the database (T005 is in-memory; database persistence is T013)
- Do NOT implement universe refresh scheduling (that is the scan loop's job, T012)
- Do NOT implement position sizing (T011)
- Do NOT modify REST or WebSocket clients

---

## 9. Interfaces / Contracts

Downstream tasks import:

```python
from scanner.candle_store.candle_store import CandleStore
from scanner.candle_store.universe_manager import UniverseManager, UniverseRefreshError
```

These paths must remain stable after delivery.

Public interface summary:
```python
# CandleStore
candle_store.initialize(symbols, intervals)       # async
candle_store.run_forever()                        # async — blocks
candle_store.stop()                               # async
candle_store.get_closed_candles(symbol, interval, n) -> list[Candle]  # sync
candle_store.is_ready(symbol, interval, min_candles) -> bool           # sync
candle_store.subscribed_symbols -> frozenset[str]

# UniverseManager
universe_manager.refresh() -> list[str]           # async
universe_manager.symbols -> list[str]             # sync property
universe_manager.last_refreshed_at -> datetime | None
```

---

## 10. Acceptance Criteria

| AC-ID | Criterion | Verification |
|---|---|---|
| AC-001 | `UniverseManager.refresh()` applies volume filter | `test_universe_manager.py::test_volume_filter_applied` |
| AC-002 | BTCUSDT always included regardless of volume | `test_universe_manager.py::test_btc_always_included` |
| AC-003 | Cached list returned on REST failure | `test_universe_manager.py::test_refresh_failure_uses_cache` |
| AC-004 | `UniverseRefreshError` raised on failure with no cache | `test_universe_manager.py::test_refresh_failure_no_cache_raises` |
| AC-005 | REST pre-fill populates buffer | `test_candle_store.py::test_prefill_populates_buffer` |
| AC-006 | BTC pre-fill failure logs ERROR | `test_candle_store.py::test_btc_prefill_failure_logs_error` |
| AC-007 | Non-BTC pre-fill failure logs WARNING; init continues | `test_candle_store.py::test_prefill_failure_continues` |
| AC-008 | Forming candles ignored; not stored | `test_candle_store.py::test_forming_candle_not_stored` |
| AC-009 | Closed candles stored; `get_closed_candles` returns them oldest-first | `test_candle_store.py::test_closed_candle_stored_and_retrieved` |
| AC-010 | Duplicate candle (same open_time) not stored twice | `test_candle_store.py::test_duplicate_candle_rejected` |
| AC-011 | Buffer FIFO — oldest dropped when full | `test_candle_store.py::test_buffer_fifo_eviction` |
| AC-012 | Gap detected and filled via REST | `test_candle_store.py::test_gap_detected_and_filled` |
| AC-013 | Gap fill failure → log ERROR; new candle still stored | `test_candle_store.py::test_gap_fill_failure_candle_still_stored` |
| AC-014 | `get_closed_candles()` never returns forming candles | `test_candle_store.py::test_no_forming_in_output` |
| AC-015 | `is_ready()` returns False when buffer < min_candles | `test_candle_store.py::test_is_ready_false` |
| AC-016 | `is_ready()` returns True when buffer ≥ min_candles | `test_candle_store.py::test_is_ready_true` |
| AC-017 | Structured logs emitted at correct levels | LogCapture assertions in test suite |
| AC-018 | `mypy src/ --strict` passes | CI |
| AC-019 | `ruff check src/` passes | CI |
| AC-020 | No live network calls in tests | all HTTP and WS mocked |

---

## 11. Required Tests

**Files**: `tests/unit/test_candle_store.py`, `tests/unit/test_universe_manager.py`

All tests mock `BybitRESTClient` and `BybitWebSocketClient` via `unittest.mock.AsyncMock`.

```
# test_universe_manager.py
test_volume_filter_applied
test_btc_always_included_below_threshold
test_symbols_sorted_alphabetically
test_refresh_failure_returns_cache
test_refresh_failure_no_cache_raises_universe_refresh_error
test_last_refreshed_at_set_on_success
test_last_refreshed_at_none_before_first_refresh

# test_candle_store.py
test_prefill_populates_buffer_oldest_first
test_btc_prefill_failure_logs_error
test_non_btc_prefill_failure_logs_warning_continues
test_subscribe_called_after_prefill
test_forming_candle_not_stored_in_buffer
test_closed_candle_stored_and_returned
test_get_closed_candles_oldest_first
test_get_closed_candles_unknown_symbol_returns_empty
test_duplicate_candle_same_open_time_rejected
test_buffer_evicts_oldest_when_full
test_gap_detected_and_rest_fill_called
test_gap_fill_inserts_missing_candles
test_gap_fill_failure_logs_error_candle_still_stored
test_no_forming_candle_in_get_closed_candles_output
test_forming_candle_in_buffer_defensive_logs_error
test_is_ready_false_when_below_threshold
test_is_ready_true_when_at_or_above_threshold
test_is_ready_false_for_unknown_symbol
test_subscribed_symbols_property
```

**Fixtures**: `tests/fixtures/bybit_tickers_universe.json`
- Must include ≥5 symbols: 3 above $50M volume, 1 below, and BTCUSDT.
- Synthetic data only.

---

## 12. Expected Deliverables

```
src/scanner/candle_store/__init__.py           NEW
src/scanner/candle_store/candle_store.py       NEW
src/scanner/candle_store/universe_manager.py   NEW
tests/unit/test_candle_store.py               NEW
tests/unit/test_universe_manager.py           NEW
tests/fixtures/bybit_tickers_universe.json    NEW
```

---

## 13. Failure / Escalation Conditions

STOP and escalate if:

| Condition | Action |
|---|---|
| Gap fill requires modifying REST or WS clients | STOP — gap fill must use existing public interface only |
| Buffer requires async locking to be correct | STOP — explain the concurrency issue; do not guess |
| `is_closed` filtering cannot be enforced without WS client changes | STOP — escalate |
| BTC symbol naming differs from `"BTCUSDT"` in Bybit API | Document; do not hardcode alternatives |
| DATA_CONTRACT.md freshness requirements (§7) require a background refresh task beyond scope | Escalate — this is T012 scope |

---

## 14. Completion Report Requirements

```
Task:       T005 — CandleStore + UniverseManager
Agent:      CODEX

Summary:    [2-4 sentences]

Files Created:      [list]
Files Modified:     [list — should be none]

Requirements Completed:  [R-001 ✅ through R-009 ✅]
Tests Run:               [file names and counts]
Tests Passed:            [count — target ≥ 84: 65 existing + 19 new]
Tests Failed:            [count + names + errors]

Known Issues:            [none or list]
Out-of-Scope Findings:   [anything T006/T007 needs to know]
Potential Risks:         [gap-fill edge cases, buffer eviction behavior]

Recommended Next Step:   T006 (Indicators) + T007 (RegimeDetector) in parallel
```

---

## 15. Review Plan

### Automated

```bash
pytest tests/unit/test_candle_store.py tests/unit/test_universe_manager.py -v \
  --cov=src/scanner/candle_store
ruff check src/scanner/candle_store/
black --check src/scanner/candle_store/
mypy src/ --strict
```

### GEMINI Adversarial Review

Focus:
- Gap detection: off-by-one in period calculation?
- Duplicate deduplication: same open_time different close price (Bybit correction) — which wins?
- FIFO eviction: oldest truly dropped first?
- BTC special-case: does it actually survive the volume filter bypass?
- Forming candle: any code path where is_closed=False enters the buffer?
- Gap fill: does REST end_time_ms calculation correctly exclude the new candle?

Output: `reviews/gemini/TASK_005_RED_TEAM.md`

### CTO Review

Focus:
- `get_closed_candles()` is_closed enforcement (strategy boundary)
- Gap detection formula correctness
- REST pre-fill orders candles oldest-first before storage
- Import contracts stable for T006 and T007

Output: `reviews/opus/TASK_005_FINAL_REVIEW.md`

---

## 16. Skill Extraction Decision

After T005 approval: **SKILL CANDIDATE** — `skills/candle-store/SKILL.md`

The gap-fill + buffer eviction + WebSocket integration pattern is reusable for any
streaming candle pipeline. Create skill after T005+T006 are both approved.

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

*End of Task Contract — T005 CandleStore + UniverseManager*
