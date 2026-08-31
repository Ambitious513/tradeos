# TASK CONTRACT
# ═══════════════════════════════════════════════════════════════
# Task ID:        T003
# Task Name:      Bybit REST Client
# Status:         READY
# Priority:       P1 — Critical path; T005 depends on this
# Owner Agent:    CODEX
# Reviewer:       GEMINI (API failure / reliability review)
# CTO Review:     OPUS / FABLE
# Created By:     Lead CTO (Opus/Fable)
# Created Date:   2026-08-31
# Target Branch:  feature/t003-bybit-rest
# Depends On:     T002 APPROVED
# Parallel With:  T004 (Bybit WebSocket)
# ═══════════════════════════════════════════════════════════════

---

## 1. Objective

Build a production-grade async Bybit REST API client that fetches OHLCV candle
data, symbol metadata, and 24H statistics for USDT linear perpetuals.

The client must handle rate limits, retries, and failures safely.
It must NEVER connect to the live Bybit endpoint unless `bybit_testnet=False`
is explicitly set. It must NEVER execute trades.

---

## 2. Background

T002 delivered the foundation package (`scanner.config`, `scanner.models`,
`scanner.logging_setup`). T003 builds the first external integration: a read-only
async HTTP client for Bybit's V5 REST API.

This client is consumed by:
- T005 (CandleStore / UniverseManager) for historical candle ingestion
- T014 (Backtest Engine) for historical data fetching
- T004 (WebSocket) uses REST as a fallback gap-fill mechanism

The client must be testable without a real Bybit connection (mocked HTTP).

---

## 3. Source-of-Truth Documents

| Document | Sections Required |
|---|---|
| `AGENTS.md` | All — coding standards, escalation, completion report |
| `docs/DATA_CONTRACT.md` | §2 (endpoints), §3 (candle schema), §5 (symbol metadata), §7 (freshness), §8 (validation), §10 (failure modes) |
| `docs/SYSTEM_ARCHITECTURE.md` | §3.1 (MarketDataProvider interface), §3.2 (UniverseManager) |
| `docs/STRATEGY_SPEC.md` | §2 (UNIVERSE-001 — volume filter $50M) |
| `docs/TEST_SPEC.md` | INT-001 to INT-007, REL-001, REL-005 |
| `src/scanner/config.py` | `bybit_testnet`, `universe_min_volume_usd` |
| `src/scanner/models.py` | `Candle`, `Stats24H` data contracts |

---

## 4. Scope

Read-only Bybit V5 REST API client. Candles, symbol info, and 24H tickers only.
No order placement. No account endpoints. No WebSocket (that is T004).

---

## 5. Allowed Files / Directories

```
src/scanner/market_data/__init__.py          NEW
src/scanner/market_data/bybit_rest.py        NEW
src/scanner/market_data/models.py            NEW
tests/unit/test_bybit_rest.py               NEW
tests/fixtures/bybit_candles_response.json   NEW
tests/fixtures/bybit_instruments_response.json NEW
tests/fixtures/bybit_tickers_response.json   NEW
```

---

## 6. Forbidden Files / Directories

```
docs/STRATEGY_SPEC.md          — PROTECTED
docs/RISK_SPEC.md              — PROTECTED
AGENTS.md                      — PROTECTED
MASTER_PROJECT_BRIEF.md        — PROTECTED
src/scanner/config.py          — do not modify (read only)
src/scanner/models.py          — do not modify (read only)
src/scanner/database/          — not in scope
src/scanner/indicators/        — T006 scope
src/scanner/regime/            — T007 scope
src/scanner/strategy/          — T008-T010 scope
src/scanner/market_data/bybit_ws.py — T004 scope
tasks/                         — do not create or modify task files
reviews/                       — do not create review files
skills/                        — no skills this task
```

If any requirement forces a change to a forbidden file, STOP and escalate.

---

## 7. Requirements

### R-001 — Endpoint Configuration

```python
# Production (default testnet=True):
TESTNET_BASE_URL  = "https://api-testnet.bybit.com"
MAINNET_BASE_URL  = "https://api.bybit.com"

# Selected at construction from ScannerConfig.bybit_testnet
# CRITICAL: If bybit_testnet is True, the mainnet URL must NEVER be used.
```

### R-002 — BybitRESTClient Class

```python
class BybitRESTClient:
    def __init__(self, config: ScannerConfig) -> None: ...

    async def get_klines(
        self,
        symbol: str,
        interval: str,     # "60" = 1H, "240" = 4H
        limit: int = 200,  # max 1000
        end_time_ms: int | None = None,  # for paginated historical fetch
    ) -> list[Candle]: ...
    # Returns closed candles only (is_closed=True for all returned)
    # Most recent candle last

    async def get_instruments_info(
        self,
        symbol: str | None = None,  # None = fetch all USDT linear
    ) -> list[SymbolInfo]: ...

    async def get_tickers_24h(
        self,
        symbol: str | None = None,  # None = fetch all
    ) -> list[Ticker24H]: ...

    async def get_server_time(self) -> int: ...  # returns UTC ms

    async def close(self) -> None: ...  # close the underlying httpx client
```

All methods must be `async`. Use `httpx.AsyncClient` internally.

### R-003 — Local Models (`src/scanner/market_data/models.py`)

Define these dataclasses for raw API responses before normalization:

```python
@dataclass(frozen=True)
class SymbolInfo:
    symbol: str
    base_coin: str
    quote_coin: str
    status: str           # "Trading" required for universe inclusion
    tick_size: Decimal
    lot_size: Decimal
    min_order_qty: Decimal
    max_leverage: float
    contract_type: str    # must be "LinearPerpetual"

@dataclass(frozen=True)
class Ticker24H:
    symbol: str
    last_price: Decimal
    high_24h: Decimal
    low_24h: Decimal
    volume_24h: Decimal
    turnover_24h: Decimal  # USDT value — used for universe volume filter
    price_change_pct_24h: float
    timestamp: datetime
```

### R-004 — Candle Normalization

`get_klines()` must:
1. Call `GET /v5/market/kline` with `category=linear`
2. Parse the raw list response
3. Normalize each row into a `Candle` dataclass (from `scanner.models`)
4. Set `is_closed=True` for ALL returned candles
   (REST API only returns completed candles — the forming candle is NOT included)
5. Sort ascending by `open_time` (oldest first)
6. Validate each candle via the rules in `DATA_CONTRACT.md §8` — discard and log
   any that fail validation (do NOT raise)
7. Return the validated list

### R-005 — Rate Limiting

```python
# Bybit V5 rate limits (conservative):
# /v5/market/kline: 120 req/min → max 1 req per 0.5s per symbol
# /v5/market/instruments-info: 10 req/min → 1 req per 6s
# /v5/market/tickers: 120 req/min → 1 req per 0.5s

# Implement a simple async rate limiter using asyncio.Semaphore or token bucket.
# On HTTP 429: back off using Retry-After header value (or 5s default), then retry.
```

### R-006 — Retry Logic

Use `tenacity` for all HTTP calls:

```python
# Retry policy:
retry_on: httpx.TimeoutException | httpx.NetworkError | HTTP 5xx
attempts: 3
wait: exponential(multiplier=1, min=1, max=10)
before_sleep: log WARNING with attempt number and exception

# Do NOT retry:
# HTTP 400 (bad request — log ERROR, raise)
# HTTP 401 (auth — log ERROR, raise)
# HTTP 403 (forbidden — log ERROR, raise)
# HTTP 429 (rate limit — wait Retry-After header, then retry — counts as attempt)
```

### R-007 — Failure Behavior

```
HTTP timeout (>10s):   retry per R-006; if all attempts fail → raise BybitAPIError
HTTP 5xx:             retry per R-006; if all attempts fail → raise BybitAPIError
HTTP 429:             wait + retry; log WARNING
HTTP 400/401/403:     log ERROR with full context; raise BybitAPIError immediately
Candle validation fail: discard that candle; log WARNING; continue with rest
Empty response:        return empty list; log WARNING
JSON parse error:     log ERROR; raise BybitAPIError
```

### R-008 — BybitAPIError Exception

```python
class BybitAPIError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        endpoint: str | None = None,
        ret_code: int | None = None,  # Bybit API retCode field
    ) -> None: ...
```

### R-009 — Structured Logging

Every significant event must be logged via `get_logger("market_data.rest")`:

```
INFO:  Successful fetch — symbol, endpoint, candle count, latency_ms
WARNING: Retry attempt — attempt number, exception type, wait_seconds
WARNING: Candle validation failure — symbol, field, value
WARNING: Empty response — symbol, endpoint
ERROR: Non-retryable HTTP error — status_code, endpoint, body excerpt
ERROR: JSON parse failure — endpoint
```

### R-010 — Context Manager Support

```python
async with BybitRESTClient(config) as client:
    candles = await client.get_klines("SOLUSDT", "60", limit=100)
# httpx client closed automatically on exit
```

Implement `__aenter__` / `__aexit__`.

### R-011 — Testnet Safety Assertion

```python
# In __init__, assert at runtime:
if not config.bybit_testnet:
    # Only allowed if environment == "live"
    if config.environment != "live":
        raise RuntimeError(
            "bybit_testnet=False requires environment='live'. "
            "This is a safety guard against accidental mainnet connections."
        )
```

This prevents any development or paper session from silently hitting mainnet.

---

## 8. Non-Goals

- Do NOT implement WebSocket streaming (T004)
- Do NOT implement candle caching or storage (T005)
- Do NOT implement any trading or order endpoints
- Do NOT implement account balance or position queries
- Do NOT implement authentication (API key signing) — read-only public endpoints only
- Do NOT implement the symbol universe filter logic (T005)
- Do NOT modify `scanner.models` or `scanner.config`

---

## 9. Interfaces / Contracts

Downstream tasks import:

```python
from scanner.market_data.bybit_rest import BybitRESTClient, BybitAPIError
from scanner.market_data.models import SymbolInfo, Ticker24H
```

`BybitRESTClient` is the only public class. `BybitAPIError` is the only public exception.
`SymbolInfo` and `Ticker24H` are the only public models from `market_data.models`.

These paths must remain stable after delivery.

---

## 10. Acceptance Criteria

| AC-ID | Criterion | Verification |
|---|---|---|
| AC-001 | `BybitRESTClient` instantiates with default config | `test_bybit_rest.py::test_client_init` |
| AC-002 | Testnet URL used when `bybit_testnet=True` | `test_bybit_rest.py::test_uses_testnet_url` |
| AC-003 | Mainnet URL blocked in development environment | `test_bybit_rest.py::test_mainnet_blocked_in_dev` |
| AC-004 | `get_klines()` returns valid `Candle` list from mocked response | `test_bybit_rest.py::test_get_klines_parses_correctly` |
| AC-005 | All returned candles have `is_closed=True` | `test_bybit_rest.py::test_candles_always_closed` |
| AC-006 | Candles returned oldest-first | `test_bybit_rest.py::test_candles_sorted_ascending` |
| AC-007 | Invalid candle (H < L) is discarded; rest returned | `test_bybit_rest.py::test_invalid_candle_discarded` |
| AC-008 | `get_instruments_info()` returns `SymbolInfo` list | `test_bybit_rest.py::test_get_instruments_info` |
| AC-009 | `get_tickers_24h()` returns `Ticker24H` list | `test_bybit_rest.py::test_get_tickers_24h` |
| AC-010 | HTTP 429 triggers wait + retry (mocked) | `test_bybit_rest.py::test_rate_limit_retry` |
| AC-011 | HTTP 500 triggers retry up to 3 attempts (mocked) | `test_bybit_rest.py::test_server_error_retry` |
| AC-012 | All 3 retries exhausted → raises `BybitAPIError` | `test_bybit_rest.py::test_retry_exhausted_raises` |
| AC-013 | HTTP 400 → immediate `BybitAPIError` (no retry) | `test_bybit_rest.py::test_400_no_retry` |
| AC-014 | Context manager closes httpx client | `test_bybit_rest.py::test_context_manager_closes` |
| AC-015 | Structured log emitted on successful fetch | assert via structlog `LogCapture` |
| AC-016 | Structured log emitted on retry | assert via structlog `LogCapture` |
| AC-017 | No raw `print()` in new files | `ruff check` |
| AC-018 | `mypy src/ --strict` passes | CI lint |
| AC-019 | `pytest tests/unit/test_bybit_rest.py` — all pass | CI test |
| AC-020 | No live network calls in unit tests | all HTTP mocked via `respx` or `httpx.MockTransport` |

---

## 11. Required Tests

**File**: `tests/unit/test_bybit_rest.py`

All tests must mock HTTP — no real network calls. Use `respx` (recommended) or
`httpx.MockTransport`. Add `respx` to `pyproject.toml` dev dependencies.

```
test_client_init_testnet_default
test_uses_testnet_url
test_mainnet_blocked_in_dev
test_mainnet_allowed_in_live_env
test_get_klines_parses_correctly
test_get_klines_decimal_precision     # prices as Decimal not float
test_candles_always_closed
test_candles_sorted_ascending
test_invalid_candle_ohlc_violation_discarded
test_invalid_candle_zero_price_discarded
test_empty_klines_response
test_get_instruments_info_parses
test_get_tickers_24h_parses
test_rate_limit_retry_waits_and_succeeds
test_server_error_retries_three_times
test_retry_exhausted_raises_bybit_api_error
test_400_raises_immediately_no_retry
test_json_parse_error_raises
test_context_manager_closes_client
test_structured_log_on_success        # uses structlog testing utilities
test_structured_log_on_retry
```

**Fixtures** (add to `tests/fixtures/`):
- `bybit_candles_response.json` — realistic V5 kline API response
- `bybit_instruments_response.json` — realistic V5 instruments-info response
- `bybit_tickers_response.json` — realistic V5 tickers response

Fixture data must be synthetic (not real market data).

---

## 12. Expected Deliverables

```
src/scanner/market_data/__init__.py              NEW
src/scanner/market_data/bybit_rest.py            NEW
src/scanner/market_data/models.py                NEW
tests/unit/test_bybit_rest.py                   NEW
tests/fixtures/bybit_candles_response.json       NEW
tests/fixtures/bybit_instruments_response.json   NEW
tests/fixtures/bybit_tickers_response.json       NEW
pyproject.toml                                   MODIFIED (add respx to dev deps)
```

---

## 13. Failure / Escalation Conditions

STOP and escalate to CTO if:

| Condition | Action |
|---|---|
| Bybit V5 API response format differs from what DATA_CONTRACT.md describes | Document exact discrepancy; do not invent a new format |
| Rate limit values in R-005 are incorrect | Verify against Bybit docs; report; do not guess |
| `httpx` + `tenacity` interaction produces unexpected behavior | Document and escalate; do not workaround silently |
| Any requirement needs changes to `scanner.models` or `scanner.config` | STOP; escalate — those are locked interfaces |
| Implementing R-011 safety guard is impossible without config changes | STOP; escalate |

**Escalation format:**
```
STATUS: BLOCKED
TASK: T003
ISSUE: [precise description]
FILE AFFECTED: [path]
WHAT I NEED: [specific decision]
```

---

## 14. Completion Report Requirements

```
Task:       T003 — Bybit REST Client
Agent:      CODEX
Branch:     feature/t003-bybit-rest

Summary:    [2-4 sentences]

Files Created:      [list]
Files Modified:     [list]

Requirements Completed:  [R-001 ✅ through R-011 ✅]
Tests Run:               [file names and counts]
Tests Passed:            [count]
Tests Failed:            [count + names + errors]

Known Issues:            [none or list]
Out-of-Scope Findings:   [anything T004/T005 needs to know]
Potential Risks:         [any Bybit API quirks discovered]

Recommended Next Step:   T005 (CandleStore) after T004 also completes
```

---

## 15. Review Plan

### Automated (must pass before review)

```bash
pytest tests/unit/test_bybit_rest.py -v --cov=src/scanner/market_data/bybit_rest
ruff check src/scanner/market_data/
black --check src/scanner/market_data/
mypy src/ --strict
```

### GEMINI Adversarial Review

Focus:
- Testnet safety guard (R-011) cannot be bypassed
- All failure paths produce logs and raise correctly (no silent swallowing)
- Retry logic does not retry on 4xx errors
- No real network calls in tests
- Rate limiter actually limits (not just a placeholder)
- `httpx.AsyncClient` is properly closed in all code paths

Output: `reviews/gemini/TASK_003_RED_TEAM.md`

### CTO Review

Focus:
- Candle normalization produces exact `Candle` dataclass from DATA_CONTRACT.md
- `is_closed=True` on all REST-returned candles
- Decimal precision preserved (no float conversion of prices)
- Import contracts in Section 9 are stable

Output: `reviews/opus/TASK_003_FINAL_REVIEW.md`

---

## 16. Skill Extraction Decision

After T003 approval: **SKILL CANDIDATE** — `skills/bybit-rest-client/SKILL.md`

Bybit REST retry/rate-limit patterns are reusable for future exchange integrations.
Defer creation until T004 is also complete so the skill covers both REST and WS patterns
together in a unified `skills/bybit-market-data/SKILL.md`.

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

*End of Task Contract — T003 Bybit REST Client*
