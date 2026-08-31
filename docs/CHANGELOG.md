# CHANGELOG.md — A+ Scanner
# Format: [VERSION] DATE — Description

---

## [0.1.0] 2026-08-31

### Initialization — Project Governance and Specification

**Agent**: Lead CTO (Opus/Fable)
**Phase**: T001 — Specification Audit and Project Initialization
**Gate**: Pending GATE-1 (Human Strategy Approval)

#### Created

- `AGENTS.md` — Agent operating constitution (v1.0)
- `docs/STRATEGY_SPEC.md` — Deterministic strategy specification (v0.1-DRAFT)
- `docs/SYSTEM_ARCHITECTURE.md` — System component architecture (v0.1-DRAFT)
- `docs/DATA_CONTRACT.md` — Market data field definitions (v0.1-DRAFT)
- `docs/RISK_SPEC.md` — Risk management specification (v0.1-DRAFT)
- `docs/TEST_SPEC.md` — Testing requirements specification (v0.1-DRAFT)
- `docs/TASK_GRAPH.md` — Development task dependency graph (v0.1-DRAFT)
- `docs/CHANGELOG.md` — This file
- `tasks/active/TASK_001_SPECIFICATION_AUDIT.md` — First formal task
- Directory structure: `tasks/`, `reviews/`, `skills/`

#### Ambiguities Identified and Resolved (Proposed)

28 ambiguities identified (AMB-001 through AMB-028).
All resolutions are PROPOSED — pending GATE-1 human review.
See `docs/STRATEGY_SPEC.md` Section 0 (Ambiguity Register).

#### Status

PENDING GATE-1 — No implementation may begin until human approves strategy specification.

---

## [1.0.0] 2026-08-31

### GATE-1 APPROVED — Strategy Specification Locked

**Agent**: Human (final authority)
**Phase**: GATE-1 — Strategy Specification Review and Approval

#### Approved

All 28 ambiguity resolutions in `docs/STRATEGY_SPEC.md` confirmed by human.
All strategy parameters are now IMMUTABLE without a formal Strategy Change Proposal.

#### Key Decisions Locked

| Parameter | Value |
|---|---|
| BTC regime timeframe | 4H primary, 1H confirmation |
| Neutral zone | ±1.5% 24H change |
| Pump/dump threshold | ±8% |
| RSI thresholds | 75 (short) / 25 (long) |
| EMA7 extension | 3% |
| Stop method | MAX(structural, 1.5×ATR14) |
| Minimum R:R | 2.0:1 |
| Setup expiration | 4 hours |
| Daily loss limit | -$25.00 USD |
| Daily profit lock | +$50.00 USD |
| A+ score threshold | 80/100 |
| Risk per trade | $5.00 USD |

#### Updated Files

- `docs/STRATEGY_SPEC.md` → v1.0 (GATE-1 APPROVED); Section 11 replaced with approval record
- `docs/RISK_SPEC.md` → v1.0 (GATE-1 APPROVED)
- `docs/DATA_CONTRACT.md` → v1.0 (GATE-1 APPROVED)
- `docs/TEST_SPEC.md` → v1.0 (GATE-1 APPROVED)
- `docs/SYSTEM_ARCHITECTURE.md` → v1.0 (GATE-1 APPROVED)
- `docs/TASK_GRAPH.md` → GATE-1 marked passed
- `tasks/completed/TASK_001_SPECIFICATION_AUDIT.md` → Archived as APPROVED
- `docs/CHANGELOG.md` → This entry

#### Status

**GATE-1 PASSED. Implementation may begin. Next: T002 (Foundation) — assign to Codex.**

---

## [0.2.0] 2026-08-31

### T002 APPROVED — Project Foundation

**Agent**: Codex (implementation) | Gemini (adversarial review) | CTO Opus (final review)
**Release Decision**: APPROVED
**Tests**: 22 passed / 0 failed | Coverage: 86%

#### Files Created by Codex

- `pyproject.toml` — hatchling build, all dependencies declared with version pins
- `README.md` — project overview and setup instructions
- `.env.example` — safe credential template
- `.gitignore` — expanded during review (*.pyc, .pytest_cache/, src/*.egg-info/ added)
- `src/scanner/__init__.py`
- `src/scanner/config.py` — pydantic-settings with GATE-1 constants; validators reject invalid values
- `src/scanner/logging_setup.py` — structlog JSON/pretty logging
- `src/scanner/models.py` — frozen Candle, Stats24H, Regime, Direction, SignalState, TERMINAL_STATES
- `src/scanner/database/__init__.py`
- `src/scanner/database/connection.py` — async SQLAlchemy engine + session factory
- `src/scanner/database/migrations.py` — idempotent create_all_tables()
- `src/scanner/database/models.py` — Signal, StateTransition, Trade, DailySession, AuditLog ORM models
- `tests/conftest.py` + all test package __init__.py files
- `tests/unit/test_config.py`, `test_models.py`, `test_database.py`
- `tests/fixtures/README.md`

#### Review Artifacts

- `reviews/gemini/TASK_002_RED_TEAM.md` — APPROVED_WITH_FIXES (2 gitignore gaps fixed)
- `reviews/opus/TASK_002_FINAL_REVIEW.md` — APPROVED

#### Skill Extraction

NOT REQUIRED for this task (see T002 Section 16). Revisit after T005.

#### Next Tasks

T003 (Bybit REST Client) and T004 (Bybit WebSocket) — parallel, assign to Codex.

#### Governance Update

Added `docs/AGENT_WORKFLOW.md` and `docs/TASK_CONTRACT_STANDARD.md`.
Updated `AGENTS.md` to v1.1 with Task Contract workflow in Article 8.

---

## [0.3.0] 2026-08-31

### T003 APPROVED — Bybit REST Client

**Agent**: Codex (implementation) | Gemini (adversarial review) | CTO Opus (final review)
**Release Decision**: APPROVED
**Tests**: 44 full suite / 22 T003-specific — 0 failed | REST client coverage: 80%

#### Files Created by Codex

- `src/scanner/market_data/__init__.py`
- `src/scanner/market_data/bybit_rest.py` — async Bybit V5 REST client (511 lines)
  - `BybitRESTClient`: `get_klines()`, `get_instruments_info()`, `get_tickers_24h()`, `get_server_time()`
  - `BybitAPIError` exception
  - `_EndpointRateLimiter`: per-endpoint asyncio lock with conservative intervals
  - Tenacity retry policy: 3 attempts, exponential backoff, 4xx not retried
  - Testnet safety guard: `bybit_testnet=False` requires `environment="live"`
  - Candle validation: parse failure → WARNING; OHLC violation → ERROR (per DATA_CONTRACT.md §8)
- `src/scanner/market_data/models.py` — `SymbolInfo`, `Ticker24H` frozen dataclasses
- `tests/unit/test_bybit_rest.py` — 22 mocked unit tests
- `tests/fixtures/bybit_candles_response.json`
- `tests/fixtures/bybit_instruments_response.json`
- `tests/fixtures/bybit_tickers_response.json`

#### Files Modified by Codex

- `pyproject.toml` — added `respx>=0.20,<1.0` to dev dependencies (authorized in contract)

#### Contract Corrections During Implementation

Two CTO authoring errors were identified and correctly escalated by Codex:
1. `pyproject.toml` missing from Section 5 Allowed Files → corrected; added
2. Candle validation log severity WARNING→ERROR conflict with DATA_CONTRACT.md §8 → ruled ERROR

#### Review Artifacts

- `reviews/gemini/TASK_003_RED_TEAM.md` — APPROVED (15 checks, 0 failures)
- `reviews/opus/TASK_003_FINAL_REVIEW.md` — APPROVED (15 checks, 0 failures)

#### Skill Extraction

DEFERRED — combine T003 + T004 into `skills/bybit-market-data/SKILL.md` after T004 approved.

#### Next

T005 (CandleStore + UniverseManager) activates after T004 is also APPROVED.

---

## [0.4.0] 2026-08-31

### T004 APPROVED — Bybit WebSocket Client

**Agent**: Codex (implementation) | Gemini (adversarial review) | CTO Opus (final review)
**Release Decision**: APPROVED
**Tests**: 62 full suite / 18 T004-specific — 0 failed | WS client coverage: 82%

#### Files Created by Codex

- `src/scanner/market_data/bybit_ws.py` — resilient async Bybit V5 WS client (387 lines)
  - `BybitWebSocketClient`: subscribe/unsubscribe, run_forever, stop
  - `_WebSocketTransport` Protocol: enables mocked testing without monkey-patching
  - Reconnect: exponential backoff (1s→30s cap), unlimited retries, re-subscribe on reconnect
  - Ping/pong: 20s interval, 5s pong timeout triggers reconnect
  - Three-tier validation: CRITICAL (OHLC/price=0) / ERROR (volume) / WARNING (parse)
  - `is_closed` NOT validated at transport layer — forming candles emitted faithfully
  - BTC 4H stale → ERROR; other stale → WARNING
  - Callback exception isolation: WS loop never crashes from on_candle errors
- `src/scanner/market_data/stale_detector.py` — `StaleStreamDetector` (50 lines)
- `tests/unit/test_bybit_ws.py` — 18 mocked unit tests
- `tests/fixtures/bybit_ws_kline_message.json`
- `tests/fixtures/bybit_ws_kline_closed.json`

#### Contract Corrections During Implementation (3 CTO authoring errors)

1. R-007 severity: WARNING → CRITICAL (OHLC/price=0) + ERROR (general) per DATA_CONTRACT.md §10/§8
2. R-003: `is_closed` excluded from transport validation; forming candles are valid
3. DATA_CONTRACT.md §8: clarified pipeline scope; added severity table with `Applies To` column

#### Review Artifacts

- `reviews/gemini/TASK_004_RED_TEAM.md` — APPROVED (19 checks, 0 failures)
- `reviews/opus/TASK_004_FINAL_REVIEW.md` — APPROVED (17 checks, 0 failures)

#### Open Items for Downstream

- Verify `"BTCUSDT"` symbol naming matches Bybit perpetual naming (T005/T007)
- Integration tests against testnet WS required before paper trading
- T003-PATCH-001: fix CRITICAL log severity for REST client OHLC/zero-price cases

#### Next

T003-PATCH-001 (non-blocking fix), then T005 (CandleStore + UniverseManager).

---
