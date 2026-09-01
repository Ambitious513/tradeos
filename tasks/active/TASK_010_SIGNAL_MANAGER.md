# TASK CONTRACT
# ═══════════════════════════════════════════════════════════════
# Task ID:        T010
# Task Name:      SignalManager — Signal State Machine
# Status:         APPROVED — 2026-09-01
# Priority:       P1
# Owner Agent:    CODEX
# Reviewer:       SONNET (quant), GEMINI (adversarial), CTO (final)
# Created By:     Lead CTO (Opus/Fable)
# Created Date:   2026-09-01
# Depends On:     T008 APPROVED, T009 APPROVED
# Blocks:         T012 (ScanLoop)
# ═══════════════════════════════════════════════════════════════

---

## 1. Objective

Implement the signal state machine, in-memory signal tracking, and the
database write layer for signal creation and state transitions.

---

## 2. Background and CTO Rulings

This contract resolves all three questions from the Codex BLOCKED report.

### Ruling A — DETECTED → WATCHING

DETECTED is a transient state. In the same processing cycle that initial
conditions are confirmed, the signal is immediately written as DETECTED then
advanced to WATCHING. The WATCHING state persists until a rejection candle is
found or the setup expires. **DETECTED is written to the DB but never held in
the in-memory active list — the signal is in WATCHING from the moment it is
placed in the active list.**

```
New candle arrives
    → detect_initial_conditions() returns SetupContext
    → create Signal (DETECTED)
    → write to DB (state=DETECTED)
    → transition to WATCHING (same cycle)
    → write transition to DB (WATCHING)
    → add to active signals list
```

### Ruling B — Score Timing and Entry Price at TRIGGERED

Scoring occurs at **TRIGGERED state**, not ARMED. The trigger candle has
just closed; the entry will be placed at the open of the NEXT candle. Because
the next open is unknown, use **trigger_candle.close as the estimated entry
price** for scoring and stop/TP computation.

```
At TRIGGERED:
  estimated_entry = trigger_candle.close
  atr_14          = setup_context.atr_14   (from DETECTED)
  stop_price      = compute_stop_short/long(estimated_entry, recent_3_candles, atr_14)
  take_profit     = compute_take_profit(estimated_entry, stop_price, direction)
  rr_ok           = check_minimum_rr(estimated_entry, stop_price, take_profit, direction)
  if not rr_ok: EXPIRE the signal
  score           = compute_score(ScoreInput(...))
  if score < 80:  EXPIRE the signal
  else: advance to TRIGGERED (stored as in_memory signal state)
```

The actual confirmed entry price (next candle open) is recorded when T012
receives the candle and updates the signal to ACTIVE.

### Ruling C — sweep_or_excess_pct for ScoreInput

This value measures how far the setup penetrated the 24H level:

```
SHORT: excess_pct = max((rejection_candle.high - high_24h) / high_24h * 100, Decimal(0))
       (how far above the 24H high the rejection candle went; capped at 0 if it
        only came close but didn't breach)

LONG:  sweep_depth_pct = (low_24h - rejection_candle.low) / low_24h * 100
       (how far below the 24H low the sweep went; always >= 0.1% by LONG-005)
```

Both are Decimal and always >= 0 when the condition was met at ARMED state.

---

## 3. Source-of-Truth Documents

| Document | Sections Required |
|---|---|
| `AGENTS.md` | All |
| `docs/STRATEGY_SPEC.md` | §6 (state machine), §10 (expiration), SHORT-010, LONG-011 |
| `docs/DATA_CONTRACT.md` | All — log levels |
| `src/scanner/models.py` | `SignalState`, `Direction`, `TERMINAL_STATES` |
| `src/scanner/database/models.py` | `Signal` ORM, `StateTransition` ORM |
| `src/scanner/strategy/setup_detector.py` | `SetupContext`, all detection functions |
| `src/scanner/strategy/score_engine.py` | `ScoreInput`, `compute_score`, `is_a_plus` |

---

## 4. Scope

In-memory signal lifecycle management and database writes for signal records
and state transitions only. No order placement. No position tracking.

---

## 5. Allowed Files / Directories

```
src/scanner/strategy/signal_manager.py     NEW
src/scanner/database/signal_writer.py      NEW
tests/unit/test_signal_manager.py          NEW
src/scanner/strategy/__init__.py           UPDATE (add SignalManager)
```

---

## 6. Forbidden Files / Directories

```
docs/STRATEGY_SPEC.md            — PROTECTED
AGENTS.md                        — PROTECTED
src/scanner/strategy/setup_detector.py  — do not modify (T008)
src/scanner/strategy/score_engine.py    — do not modify (T009)
src/scanner/models.py            — do not modify
src/scanner/database/models.py   — do not modify
```

---

## 7. Requirements

### R-001 — ActiveSignal In-Memory Dataclass

```python
@dataclass
class ActiveSignal:
    """In-memory representation of one live signal.

    Mutable — state transitions update this object in place.
    Separate from the SQLAlchemy ORM model (scanner.database.models.Signal).
    """
    signal_id: UUID                      # stable identifier; written to DB
    symbol: str
    direction: Direction
    state: SignalState                   # current state
    detected_at: datetime                # UTC; 4H expiration measured from here
    setup_context: SetupContext          # from T008.detect_initial_conditions()

    # Set when WATCHING → ARMED
    rejection_candle: Candle | None = None
    rejection_at: datetime | None = None
    high_24h_at_armed: Decimal | None = None   # snapshot of 24H high at ARMED
    low_24h_at_armed: Decimal | None = None    # snapshot of 24H low at ARMED

    # Set when retest is found (within ARMED state)
    retest_candle: Candle | None = None
    retest_at: datetime | None = None

    # Set at TRIGGERED
    score: int | None = None
    estimated_entry: Decimal | None = None
    stop_price: Decimal | None = None
    take_profit: Decimal | None = None
```

### R-002 — SignalManager Class

```python
class SignalManager:
    """Drive the A+ signal state machine for all active symbols.

    Receives closed candles and regime updates; advances signals through
    WATCHING → ARMED → TRIGGERED → ACTIVE; expires and cancels as required.
    """

    def __init__(
        self,
        candle_store: CandleStore,
        session_factory: Callable[[], AsyncContextManager[AsyncSession]],
        config: ScannerConfig,
    ) -> None: ...

    @property
    def active_signals(self) -> list[ActiveSignal]:
        """Return a copy of the current in-memory signal list."""
        ...

    async def on_candle(
        self,
        candle: Candle,
        regime: Regime,
        candles_1h: list[Candle],
    ) -> None:
        """Process one new closed 1H candle for one symbol.

        Steps (in order):
          1. Expire and cancel stale signals for this symbol
          2. Advance ARMED signals (check retest; check entry trigger)
          3. Advance WATCHING signals (check rejection candle)
          4. Try to detect a new initial setup (if no WATCHING/ARMED signal for symbol)
          5. Write all state changes to DB in one session

        Args:
            candle:     The newly closed 1H candle for a symbol.
            regime:     Current BTC regime (from RegimeDetector.classify()).
            candles_1h: Full recent 1H candle history for this symbol
                        (from CandleStore.get_closed_candles()).
        """

    async def mark_active(self, signal_id: UUID, confirmed_entry: Decimal) -> None:
        """Advance a TRIGGERED signal to ACTIVE with the confirmed entry price.

        Called by T012 (ScanLoop) when the next candle opens and the entry
        price is confirmed. Updates in-memory state and DB.
        """

    async def mark_terminal(
        self,
        signal_id: UUID,
        terminal_state: SignalState,
        reason: str,
    ) -> None:
        """Advance an ACTIVE signal to TP_HIT, SL_HIT, or CANCELLED.

        terminal_state must be in TERMINAL_STATES; raises ValueError otherwise.
        """
```

### R-003 — State Machine Rules (STRATEGY_SPEC §6 + §10)

All rules are IMMUTABLE per AGENTS.md Article 5.

**DETECTED → WATCHING**:
- Automatic, same cycle as initial detection (Ruling A)
- `detected_at` = trigger_candle.open_time
- 4H expiration clock starts at `detected_at`

**WATCHING → ARMED** (per SHORT-004+005 / LONG-004+005+006):
- `check_24h_level_interaction()` AND `check_rejection_candle()` (SHORT)
  OR `check_liquidity_sweep()` AND `check_bullish_rejection_candle()` (LONG)
- Snapshot `high_24h_at_armed` and `low_24h_at_armed` from candles at this moment
- Set `rejection_candle` and `rejection_at`

**WATCHING → EXPIRED** (SHORT-010 §10):
- `candle.open_time - detected_at > timedelta(hours=4)` AND no rejection found
- Also: new 24H high (SHORT) or new 24H low (LONG) invalidates setup

**ARMED → TRIGGERED** (Ruling B + SHORT-007 / LONG-008):
- `retest_candle` must be set first (retest found in prior candle)
- `check_entry_trigger_short/long()` → True
- Compute estimated_entry, stop, TP; check R:R; call compute_score()
- Score >= 80 → advance to TRIGGERED; else → EXPIRED

**ARMED → EXPIRED**:
- No retest within 4H of `rejection_at`
- OR: no entry trigger within 4H of `retest_at`
- OR: new 24H high (SHORT) or new 24H low (LONG)

**TRIGGERED → ACTIVE**:
- Called by T012 via `mark_active()` when next candle opens

**TRIGGERED → EXPIRED**:
- If T012 does not call `mark_active()` within 1H of TRIGGERED (rare; defensive)

**Any state → CANCELLED**:
- BTC regime changes from BULLISH (LONG) or BEARISH (SHORT)
- Checked at start of `on_candle()` for each active signal

**Duplicate prevention** (RISK-007):
- Do NOT create a new signal for symbol X if an ARMED, TRIGGERED, or ACTIVE
  signal already exists for symbol X

### R-004 — SignalWriter

```python
class SignalWriter:
    """Write signal records and state transitions to the database.

    Receives an open AsyncSession. Does NOT commit — caller owns the transaction.
    """

    async def create_signal(
        self,
        session: AsyncSession,
        signal: ActiveSignal,
    ) -> None:
        """Insert a new Signal ORM row with state=DETECTED.
        Then insert a StateTransition row for DETECTED → WATCHING.
        """

    async def write_transition(
        self,
        session: AsyncSession,
        signal: ActiveSignal,
        from_state: SignalState,
        to_state: SignalState,
        reason: str,
    ) -> None:
        """Insert one StateTransition row.

        Raises ValueError if to_state is not a valid successor of from_state.
        """
```

**Valid transitions** (enforced by `write_transition`):

```
DETECTED  → WATCHING
WATCHING  → ARMED | EXPIRED | CANCELLED
ARMED     → TRIGGERED | EXPIRED | CANCELLED
TRIGGERED → ACTIVE | EXPIRED
ACTIVE    → TP_HIT | SL_HIT | CANCELLED
```

### R-005 — Logging Requirements

Use `get_logger("strategy.signal_manager")`.

```
INFO:  signal_detected    — symbol, direction, change_24h_pct, rsi_14
INFO:  signal_watching    — signal_id, symbol
INFO:  signal_armed       — signal_id, symbol, rejection_at
INFO:  signal_triggered   — signal_id, symbol, score, estimated_entry, stop_price
INFO:  signal_expired     — signal_id, symbol, state, reason
INFO:  signal_cancelled   — signal_id, symbol, reason
INFO:  signal_active      — signal_id, symbol, confirmed_entry
WARN:  duplicate_signal_rejected — symbol, existing_state
```

All Decimal values logged as `str()`.

### R-006 — Error Handling

- If `session_factory` raises: log ERROR; do not crash; signals remain in-memory
- If `write_transition` raises an invalid transition: log ERROR; do not crash
- If `compute_score` returns a score outside [20, 100]: log ERROR; treat as EXPIRED

---

## 8. Non-Goals

- Do NOT place orders on the exchange (T012)
- Do NOT track PnL or active position (T012)
- Do NOT implement daily trade/loss limits (T012)
- Do NOT implement the scan loop (T012)

---

## 9. Acceptance Criteria

| AC-ID | Criterion | Test |
|---|---|---|
| AC-001 | DETECTED created + immediately transitioned to WATCHING | `test_detection_creates_watching_signal` |
| AC-002 | Rejection candle on WATCHING → ARMED transition | `test_rejection_advances_watching_to_armed` |
| AC-003 | No rejection within 4H → EXPIRED | `test_watching_expires_after_4h` |
| AC-004 | Retest found in ARMED, entry trigger fires → TRIGGERED | `test_entry_trigger_advances_armed_to_triggered` |
| AC-005 | Score >= 80 → remains TRIGGERED | `test_high_score_signal_stays_triggered` |
| AC-006 | Score < 80 → EXPIRED | `test_low_score_signal_expires` |
| AC-007 | R:R < 2:1 → EXPIRED before scoring | `test_poor_rr_expires_before_score` |
| AC-008 | No retest within 4H of rejection → EXPIRED | `test_armed_expires_if_no_retest` |
| AC-009 | Regime change → CANCELLED | `test_regime_change_cancels_signal` |
| AC-010 | New 24H high (SHORT) → CANCELLED | `test_new_24h_high_cancels_short` |
| AC-011 | New 24H low (LONG) → CANCELLED | `test_new_24h_low_cancels_long` |
| AC-012 | Duplicate ARMED/TRIGGERED/ACTIVE blocks new WATCHING | `test_duplicate_signal_rejected` |
| AC-013 | `mark_active()` advances TRIGGERED → ACTIVE | `test_mark_active_updates_state` |
| AC-014 | `mark_terminal()` rejects non-terminal state | `test_mark_terminal_rejects_invalid_state` |
| AC-015 | `active_signals` returns a copy (not internal list) | `test_active_signals_is_copy` |
| AC-016 | `write_transition` rejects invalid succession | `test_invalid_transition_raises` |
| AC-017 | All Decimal values logged as str | `test_logging_uses_str_for_decimal` |
| AC-018 | No 1H confirmation of regime from T007 (regime is passed as parameter) | `test_regime_passed_as_parameter` |
| AC-019 | `mypy src/ --strict` passes | CI |
| AC-020 | `ruff check src/` passes | CI |
| AC-021 | Full suite >= 225 tests passing | `pytest tests/ -v` |

---

## 10. Required Tests

**File**: `tests/unit/test_signal_manager.py`

Use `unittest.mock.AsyncMock` for `session_factory` and `SignalWriter`.
Use real `SetupContext` objects built from synthetic candles.

```
test_detection_creates_watching_signal_not_detected
test_no_detection_when_armed_signal_exists_for_symbol
test_no_detection_when_triggered_signal_exists_for_symbol
test_rejection_candle_advances_watching_to_armed
test_watching_expires_after_4h_with_no_rejection
test_new_24h_high_cancels_watching_short_signal
test_new_24h_low_cancels_watching_long_signal
test_retest_found_in_armed_state
test_entry_trigger_fires_after_retest_advances_to_triggered
test_high_score_signal_remains_triggered
test_score_below_80_expires_at_triggered
test_poor_rr_expires_without_scoring
test_no_entry_trigger_within_4h_of_retest_expires
test_regime_change_cancels_watching_signal
test_regime_change_cancels_armed_signal
test_mark_active_updates_in_memory_state
test_mark_terminal_tp_hit
test_mark_terminal_sl_hit
test_mark_terminal_rejects_non_terminal_state
test_active_signals_returns_copy
test_duplicate_signal_rejected_when_armed_exists
test_invalid_state_transition_logs_error
test_sweep_or_excess_pct_short_computed_from_rejection_candle
test_sweep_or_excess_pct_long_computed_from_rejection_candle
test_score_input_assembled_at_triggered_with_trigger_close_as_entry
```

---

## 11. Expected Deliverables

```
src/scanner/strategy/signal_manager.py     NEW
src/scanner/database/signal_writer.py      NEW
tests/unit/test_signal_manager.py          NEW
src/scanner/strategy/__init__.py           UPDATED
```

---

## 12. Escalation Conditions

STOP and escalate if:

| Condition | Action |
|---|---|
| `SignalState` or `TERMINAL_STATES` in models.py differ from expected | Quote models.py; escalate |
| `Signal` or `StateTransition` ORM fields differ from what signal_writer needs | Quote database/models.py; escalate |
| Any expiration window other than 4H appears in the spec | Quote spec line; escalate |

---

## 13. Completion Report Requirements

```
Task:       T010 — SignalManager
Agent:      CODEX

Summary:    [2-3 sentences]

Files Created/Modified:  [list]
Tests Added:             [count — target ≥ 25]
Tests Run:               pytest tests/ -v — [N] passed (target ≥ 225)
Tests Failed:            0

State Machine Verification:
  DETECTED→WATCHING: same-cycle ✅ / signal in WATCHING in active list ✅
  ARMED→TRIGGERED: score computed at trigger close ✅ / score < 80 → EXPIRED ✅
  Regime cancel: WATCHING + ARMED both cancelled on regime change ✅
  Duplicate block: new detection rejected when ARMED exists ✅

Recommended Next Step: T012 (ScanLoop) — T011 is parallel
```

---

## 14. Review Plan

### SONNET Quantitative Review

Focus:
- Expiration arithmetic: `candle.open_time - detected_at > timedelta(hours=4)` vs `>= 4`
- sweep_or_excess_pct formulae for both directions
- estimated_entry = trigger_candle.close — is this the right proxy?
- Score computed once per TRIGGERED transition; not recomputed on each candle

### GEMINI Adversarial Review

Focus:
- What if `on_candle` is called for a symbol with no initial detection ever? (No-op)
- What if `session_factory` raises on every call? Signals accumulate in memory unbounded?
- What if retest_candle and entry trigger fire on the same candle?
- What if all signals are TERMINAL after `on_candle`? active_signals → []

### CTO Review

Focus:
- Ruling A compliance: DETECTED is transient; never in active list
- Ruling B compliance: score at TRIGGERED, estimated_entry = trigger_close
- Ruling C compliance: sweep_or_excess_pct correct formula per direction

---

## 15. Status / Sign-off

| Role | Status | Date |
|---|---|---|
| CTO (created) | ✅ READY | 2026-09-01 |
| Implementation | ⏳ PENDING | — |
| Sonnet quant | ⏳ PENDING | — |
| Gemini adversarial | ⏳ PENDING | — |
| CTO final | ⏳ PENDING | — |
| **Release Decision** | ⏳ PENDING | — |

---

*End of Task Contract — T010 SignalManager*

