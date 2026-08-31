# TASK CONTRACT
# ═══════════════════════════════════════════════════════════════
# Task ID:        T002
# Task Name:      Project Foundation
# Status:         APPROVED — 2026-08-31
# Priority:       P0 — Blocks all subsequent tasks
# Owner Agent:    CODEX
# Reviewer:       GEMINI (adversarial / config safety review)
# CTO Review:     OPUS / FABLE
# Created By:     Lead CTO (Opus/Fable)
# Created Date:   2026-08-31
# Target Branch:  feature/t002-foundation
# ═══════════════════════════════════════════════════════════════

---

## 1. Objective

Build the complete Python project skeleton for the A+ Scanner.

This task produces the importable package, configuration system, structured logging,
async database abstraction, core data models, and test framework scaffold.

**No trading logic is implemented in this task.**
All outputs are pure infrastructure. The scanner cannot process a single candle until
this task is complete and approved.

---

## 2. Background

GATE-1 has been approved by the human on 2026-08-31. The strategy specification is locked.
The project now requires a clean, testable Python foundation before any indicator, regime,
or strategy module can be built.

This task creates the skeleton that all subsequent tasks (T003–T018) will build upon.
Every future agent will `import` from this foundation. Getting this right is critical.

---

## 3. Source-of-Truth Documents

The agent MUST read the following before writing a single line of code:

| Document | Purpose |
|---|---|
| `AGENTS.md` | Operating constitution — coding standards, escalation rules |
| `docs/SYSTEM_ARCHITECTURE.md` | Directory structure (Section 6), module responsibilities |
| `docs/DATA_CONTRACT.md` | Candle, Stats24H field definitions (Section 3) |
| `docs/STRATEGY_SPEC.md` | Approved strategy constants — config values must match exactly |
| `docs/RISK_SPEC.md` | Approved risk constants — config values must match exactly |

Do NOT read or modify:
- `A+ SCANNER — ANTIGRAVITY MASTER BUILD BRIEF v1.0.md` (superseded by specs above)

---

## 4. Scope

This task produces the project skeleton only. It is infrastructure — no strategy logic,
no exchange calls, no indicators, no signal detection.

---

## 5. Allowed Files / Directories

The agent may create files ONLY within:

```
pyproject.toml
README.md
.env.example
.gitignore
src/
src/scanner/
src/scanner/__init__.py
src/scanner/config.py
src/scanner/logging_setup.py
src/scanner/models.py
src/scanner/database/
src/scanner/database/__init__.py
src/scanner/database/connection.py
src/scanner/database/migrations.py
src/scanner/database/models.py
tests/
tests/__init__.py
tests/conftest.py
tests/unit/
tests/unit/__init__.py
tests/unit/test_config.py
tests/unit/test_models.py
tests/unit/test_database.py
tests/strategy/__init__.py
tests/risk/__init__.py
tests/integration/__init__.py
tests/backtest/__init__.py
tests/reliability/__init__.py
tests/fixtures/
tests/fixtures/README.md
```

---

## 6. Forbidden Files / Directories

The agent must NOT create or modify any file outside Section 5.

Explicitly forbidden:

```
docs/STRATEGY_SPEC.md          — PROTECTED (GATE-1 approved, immutable)
docs/RISK_SPEC.md              — PROTECTED
docs/SYSTEM_ARCHITECTURE.md   — read only
docs/DATA_CONTRACT.md          — read only
AGENTS.md                      — PROTECTED
MASTER_PROJECT_BRIEF.md        — PROTECTED
tasks/                         — do not create or modify task files
reviews/                       — do not create review files
skills/                        — no skills created during this task
src/scanner/market_data/       — T003/T004 scope
src/scanner/indicators/        — T006 scope
src/scanner/regime/            — T007 scope
src/scanner/strategy/          — T008–T010 scope
src/scanner/risk/              — T011 scope
src/scanner/scoring/           — T012 scope
src/scanner/alerts/            — T013 scope
src/scanner/execution/         — T015 scope
src/scanner/backtest/          — T014 scope
src/scanner/observability/     — T016 scope
```

If implementing this task requires touching a forbidden file, STOP and escalate.

---

## 7. Requirements

### R-001 — pyproject.toml

Produce a complete, installable `pyproject.toml`:
- Package name: `a-plus-scanner`
- Python: `>=3.11`
- Build system: `hatchling` (preferred) or `setuptools`
- Source layout: `src/`

**Runtime dependencies** (declare all explicitly — versions pinned to minor):
```
pydantic>=2.0,<3.0
pydantic-settings>=2.0,<3.0
sqlalchemy>=2.0,<3.0
aiosqlite>=0.19,<1.0
python-dotenv>=1.0,<2.0
httpx>=0.25,<1.0
websockets>=12.0,<14.0
structlog>=23.0,<25.0
tenacity>=8.0,<10.0
```

**Development dependencies** (under `[project.optional-dependencies]` or `[dependency-groups]`):
```
pytest>=7.0,<9.0
pytest-asyncio>=0.21,<1.0
pytest-cov>=4.0,<6.0
mypy>=1.0,<2.0
ruff>=0.1,<1.0
black>=23.0,<25.0
```

### R-002 — Configuration System (`src/scanner/config.py`)

Use `pydantic-settings`. All strategy and risk constants sourced from approved specs.

```python
class ScannerConfig(BaseSettings):
    # ── Environment ──────────────────────────────────────────────
    environment: str = "development"   # "development" | "paper" | "live"
    log_level: str = "INFO"

    # ── Exchange ─────────────────────────────────────────────────
    # CRITICAL: testnet MUST default True. Live requires explicit override.
    bybit_api_key: str = ""
    bybit_api_secret: str = ""
    bybit_testnet: bool = True

    # ── Strategy Constants (GATE-1 approved — IMMUTABLE) ─────────
    # Source: docs/STRATEGY_SPEC.md v1.0, Section 1-8
    btc_neutral_threshold_pct: float = 1.5
    pump_threshold_pct: float = 8.0
    dump_threshold_pct: float = 8.0
    rsi_overbought: float = 75.0
    rsi_oversold: float = 25.0
    ema7_extension_pct: float = 3.0
    atr_stop_multiplier: float = 1.5
    min_rr_ratio: float = 2.0
    setup_expiration_hours: int = 4
    aplus_score_threshold: int = 80
    universe_min_volume_usd: float = 50_000_000.0

    # ── Risk Constants (GATE-1 approved — IMMUTABLE) ──────────────
    # Source: docs/RISK_SPEC.md v1.0
    risk_per_trade_usd: float = 5.00
    daily_loss_limit_usd: float = -25.00
    daily_profit_lock_usd: float = 50.00
    max_trades_per_day: int = 5
    taker_fee_rate: float = 0.00055
    slippage_rate: float = 0.0005

    # ── Alerts ────────────────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
```

**Immutability note**: These constants match STRATEGY_SPEC.md v1.0 exactly. Do not adjust
values. If a value conflicts with the spec, STOP and escalate.

### R-003 — Structured Logging (`src/scanner/logging_setup.py`)

- Use `structlog` for all logging throughout the project
- All events must include: `timestamp`, `level`, `component`, `event`
- JSON format in production/paper; human-readable in development
- `get_logger(component: str) -> structlog.BoundLogger` factory function
- Zero raw `print()` statements anywhere in the codebase

### R-004 — Core Data Models (`src/scanner/models.py`)

Pure Python dataclasses and enums — no ORM dependencies in this file.
Fields sourced from `docs/DATA_CONTRACT.md` Section 3 and 4.

```python
@dataclass(frozen=True)
class Candle:
    symbol: str
    timeframe: str
    open_time: datetime        # UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal
    is_closed: bool            # MUST be True before strategy use

@dataclass(frozen=True)
class Stats24H:
    symbol: str
    high_24h: Decimal
    low_24h: Decimal
    change_pct_24h: float
    volume_24h_usd: Decimal
    timestamp: datetime

class Regime(str, Enum):
    BULLISH   = "BULLISH"
    BEARISH   = "BEARISH"
    NEUTRAL   = "NEUTRAL"
    UNDEFINED = "UNDEFINED"

class Direction(str, Enum):
    LONG  = "LONG"
    SHORT = "SHORT"

class SignalState(str, Enum):
    DETECTED  = "DETECTED"
    WATCHING  = "WATCHING"
    ARMED     = "ARMED"
    TRIGGERED = "TRIGGERED"
    ACTIVE    = "ACTIVE"
    TP_HIT    = "TP_HIT"
    SL_HIT    = "SL_HIT"
    EXPIRED   = "EXPIRED"
    CANCELLED = "CANCELLED"

TERMINAL_STATES: frozenset[SignalState] = frozenset({
    SignalState.TP_HIT,
    SignalState.SL_HIT,
    SignalState.EXPIRED,
    SignalState.CANCELLED,
})
```

Make `Candle` and `Stats24H` frozen dataclasses (immutable after creation).

### R-005 — Database Layer (`src/scanner/database/`)

**`connection.py`** — async SQLAlchemy engine + session factory:
- Default: SQLite (`sqlite+aiosqlite:///./scanner.db`)
- Connection string must be configurable via env var `DATABASE_URL`
- Expose `AsyncSession` factory via `get_session()` async context manager

**`models.py`** — SQLAlchemy ORM models:

```
Signal          — id (UUID PK), symbol, direction, state, detected_at,
                  entry_price, stop_price, tp_price, score,
                  expiration_time, created_at, updated_at
StateTransition — id, signal_id (FK→Signal), from_state, to_state,
                  reason, timestamp
Trade           — id (UUID PK), signal_id (FK→Signal), direction,
                  qty, entry_price, exit_price, pnl_usd, fee_usd,
                  slippage_usd, opened_at, closed_at
DailySession    — id, date (UNIQUE), trades_taken, realized_pnl,
                  is_halted, halt_reason, created_at, updated_at
AuditLog        — id, component, event, level, data_json, timestamp
```

Use `Decimal`-compatible column types (NUMERIC/String) — never Float for prices.

**`migrations.py`** — `create_all_tables(engine)` async function:
- Creates all tables using SQLAlchemy metadata
- Idempotent — safe to call on existing database (use `checkfirst=True`)

### R-006 — Test Scaffold (`tests/`)

`tests/conftest.py` must provide shared pytest fixtures:
- `config` — ScannerConfig with safe test defaults
- `db_engine` — async in-memory SQLite engine (`:memory:`)
- `db_session` — async session bound to `db_engine`
- `sample_candle(is_closed=True)` — factory fixture returning a valid Candle
- `sample_btc_candle(is_closed=True)` — BTC/USDT 4H candle factory

`pytest-asyncio` mode: `asyncio_mode = "auto"` in `pyproject.toml` or `conftest.py`.

`tests/fixtures/README.md` must document the fixture format for future agents (T008+).

### R-007 — Support Files

`.env.example`:
```
ENVIRONMENT=development
LOG_LEVEL=INFO
BYBIT_API_KEY=
BYBIT_API_SECRET=
BYBIT_TESTNET=true
DATABASE_URL=sqlite+aiosqlite:///./scanner.db
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
DISCORD_WEBHOOK_URL=
```

`.gitignore` must exclude: `.env`, `__pycache__/`, `.mypy_cache/`, `*.db`,
`dist/`, `build/`, `.ruff_cache/`, `.coverage`, `htmlcov/`.

`README.md` — minimal project overview with setup instructions.

---

## 8. Non-Goals

The agent must NOT:
- Implement any trading strategy logic
- Implement any exchange API calls (REST or WebSocket)
- Implement any indicators (EMA, RSI, ATR)
- Create the BTC regime classifier
- Create the signal state machine
- Create the risk engine
- Create the alert system
- Create the paper trader or backtest engine
- Connect to Bybit or any external service
- Request, store, or use real API keys with trading permissions
- Modify any protected file (see Section 6)
- Add dependencies not listed in R-001
- Modify strategy constants from the approved values in R-002

---

## 9. Interfaces / Contracts

Downstream tasks will import from this foundation. The following contracts must be stable:

```python
# config — consumed by all modules
from scanner.config import ScannerConfig

# models — consumed by all strategy/risk/data modules
from scanner.models import Candle, Stats24H, Regime, Direction, SignalState, TERMINAL_STATES

# logging — consumed by all modules
from scanner.logging_setup import get_logger

# database — consumed by persistence layer (T005+)
from scanner.database.connection import get_session
from scanner.database.migrations import create_all_tables
from scanner.database import models as db_models
```

These import paths are the public API of this task. Do not change them after delivery.

---

## 10. Acceptance Criteria

| AC-ID | Criterion | Verification |
|---|---|---|
| AC-001 | `pip install -e ".[dev]"` succeeds | CI install step |
| AC-002 | `from scanner.config import ScannerConfig; ScannerConfig()` works | `test_config.py` |
| AC-003 | `bybit_testnet` defaults to `True` | `test_config.py::test_testnet_default` |
| AC-004 | `environment` defaults to `"development"` | `test_config.py::test_environment_default` |
| AC-005 | All GATE-1 constants match `STRATEGY_SPEC.md v1.0` exactly | `test_config.py::test_strategy_constants` |
| AC-006 | All risk constants match `RISK_SPEC.md v1.0` exactly | `test_config.py::test_risk_constants` |
| AC-007 | Config values overridable via env vars | `test_config.py::test_env_override` |
| AC-008 | `from scanner.models import Candle, Regime, Direction, SignalState` works | `test_models.py` |
| AC-009 | `SignalState` enum contains all 9 required states | `test_models.py::test_signal_states_complete` |
| AC-010 | `Candle` is frozen (immutable after creation) | `test_models.py::test_candle_frozen` |
| AC-011 | `create_all_tables()` succeeds on fresh in-memory SQLite | `test_database.py` |
| AC-012 | `create_all_tables()` is idempotent (safe to call twice) | `test_database.py::test_idempotent` |
| AC-013 | Signal ORM model can be inserted and queried | `test_database.py::test_signal_crud` |
| AC-014 | DailySession ORM model can be inserted and queried | `test_database.py::test_daily_session_crud` |
| AC-015 | `pytest tests/unit/` exits 0 (all unit tests pass) | CI test step |
| AC-016 | `ruff check src/` exits 0 | CI lint step |
| AC-017 | `black --check src/` exits 0 | CI lint step |
| AC-018 | No `print()` calls in `src/` | `ruff` rule or grep check |
| AC-019 | No ORM imports in `src/scanner/models.py` | manual / grep |
| AC-020 | No files modified outside Section 5 allowed list | diff check |

---

## 11. Required Tests

### `tests/unit/test_config.py`

```
test_config_loads_with_defaults
test_testnet_default_is_true
test_environment_default_is_development
test_strategy_constants_match_spec     # verifies each constant against STRATEGY_SPEC.md values
test_risk_constants_match_spec         # verifies each constant against RISK_SPEC.md values
test_env_override_works                # monkeypatch env var, verify override
test_empty_api_keys_acceptable         # no credentials required for development
```

### `tests/unit/test_models.py`

```
test_candle_creation
test_candle_is_frozen
test_stats24h_creation
test_regime_enum_values               # BULLISH, BEARISH, NEUTRAL, UNDEFINED
test_direction_enum_values            # LONG, SHORT
test_signal_state_enum_all_nine_states
test_terminal_states_set_correct
```

### `tests/unit/test_database.py`

```
test_create_all_tables_succeeds
test_create_all_tables_idempotent
test_signal_insert_and_query
test_state_transition_insert
test_trade_insert_and_query
test_daily_session_insert_and_query
test_audit_log_insert
```

All database tests must use in-memory SQLite — no file system side effects.

---

## 12. Expected Deliverables

```
pyproject.toml                              NEW
README.md                                   NEW
.env.example                                NEW
.gitignore                                  NEW
src/scanner/__init__.py                     NEW
src/scanner/config.py                       NEW
src/scanner/logging_setup.py               NEW
src/scanner/models.py                       NEW
src/scanner/database/__init__.py            NEW
src/scanner/database/connection.py          NEW
src/scanner/database/migrations.py         NEW
src/scanner/database/models.py              NEW
tests/__init__.py                           NEW
tests/conftest.py                           NEW
tests/unit/__init__.py                      NEW
tests/unit/test_config.py                   NEW
tests/unit/test_models.py                   NEW
tests/unit/test_database.py                 NEW
tests/strategy/__init__.py                  NEW
tests/risk/__init__.py                      NEW
tests/integration/__init__.py               NEW
tests/backtest/__init__.py                  NEW
tests/reliability/__init__.py               NEW
tests/fixtures/README.md                    NEW
```

No other files.

---

## 13. Failure / Escalation Conditions

STOP work and escalate to CTO (do not guess) if:

| Condition | Action |
|---|---|
| A dependency version conflict prevents installation | Report exact conflict; suggest resolution |
| A strategy constant in `STRATEGY_SPEC.md` differs from what R-002 specifies | Report discrepancy; do NOT change either document |
| The database schema requires a column type incompatible with `Decimal` precision | Report and propose type strategy |
| Any acceptance criterion is ambiguous or contradictory | Report before writing code |
| Implementing any requirement would require touching a forbidden file | STOP immediately |

**Default escalation format:**
```
STATUS: BLOCKED
TASK: T002
ISSUE: [precise description]
FILE AFFECTED: [path]
WHAT I NEED: [specific decision or clarification]
```

---

## 14. Completion Report Requirements

On task completion, the agent must provide:

```
Task:       T002 — Project Foundation
Agent:      CODEX
Branch:     feature/t002-foundation

Summary:    [2-4 sentence description of what was built]

Files Created:      [list]
Files Modified:     [list — should be empty for T002]

Requirements Completed:  [R-001 ✅ / R-002 ✅ / ...]
Tests Run:               [list test files and count]
Tests Passed:            [count]
Tests Failed:            [count + names + errors if any]

Known Issues:            [none, or list]
Out-of-Scope Findings:   [anything discovered that future tasks need to know]
Potential Risks:         [any concerns for downstream tasks]

Recommended Next Step:   T003 (Bybit REST Client) / T004 (Bybit WebSocket) — parallel
```

---

## 15. Review Plan

### Step 1 — Automated (before human review)

```
pytest tests/unit/ --cov=src/scanner --cov-report=term-missing
ruff check src/
black --check src/
mypy src/ --strict (or document any waivers)
```

All must pass before review is requested.

### Step 2 — GEMINI Adversarial Review

Focus areas:
- `bybit_testnet=True` default is enforced and cannot be silently bypassed
- Config validation rejects invalid values (negative risk, zero score threshold)
- Database connection failure is handled gracefully (not a silent crash)
- No credentials appear in any committed file
- `.env` is excluded from `.gitignore`

Output: `reviews/gemini/TASK_002_RED_TEAM.md`

### Step 3 — CTO Review (Opus/Fable)

Focus areas:
- All strategy constants exactly match `STRATEGY_SPEC.md v1.0`
- All risk constants exactly match `RISK_SPEC.md v1.0`
- Import contracts (Section 9) are stable
- No strategic scope creep

Output: `reviews/opus/TASK_002_FINAL_REVIEW.md`

### Release Decision

```
APPROVED            — all AC pass, no blocking review findings
APPROVED_WITH_FIXES — minor findings; fixes applied before T003 starts
REJECTED            — restart task (not patch)
BLOCKED             — upstream issue; cannot proceed
```

---

## 16. Skill Extraction Decision

After T002 is APPROVED:

**Skill: NOT REQUIRED for this task.**

Rationale: Python project scaffolding is generic. The specific patterns here (pydantic-settings,
structlog, SQLAlchemy async) may be extracted into skills after T003–T005 validate the
infrastructure works end-to-end. Premature skill creation risks documenting patterns that
need refinement.

Revisit after T005 completes.

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

*End of Task Contract — T002 Project Foundation*
*This document is the authoritative handoff for Codex. Read AGENTS.md and all Source-of-Truth*
*documents listed in Section 3 before writing code.*

