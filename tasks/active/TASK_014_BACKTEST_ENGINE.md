# TASK CONTRACT
# ═══════════════════════════════════════════════════════════════
# Task ID:        T014
# Task Name:      Backtest Engine — Historical Strategy Validation
# Status:         READY
# Priority:       P1
# Owner Agent:    CODEX
# Reviewer:       SONNET (look-ahead bias — MANDATORY), GEMINI (adversarial), CTO (final)
# Created By:     Lead CTO (Opus/Fable)
# Created Date:   2026-09-01
# Depends On:     T007-T013 APPROVED
# Blocks:         GATE-2 (human backtest review), T015 (Paper Trading)
# ═══════════════════════════════════════════════════════════════

---

## 1. Objective

Implement a single-symbol backtest engine that replays historical 1H candles
through the IDENTICAL approved strategy/risk/scoring modules — no separate
copies, no reimplementation. Produce a `BacktestResult` with trade records,
equity curve, and performance metrics.

**The single most important requirement**: zero look-ahead bias. At step i,
only candles[0..i] may influence any calculation. Any violation is a
CRITICAL FAILURE requiring task rejection (not patching).

---

## 2. Background and CTO Design Decisions

### Decision A — Identical Modules, No Code Duplication

The backtest uses:
- `RegimeDetector` (T007) — fed historical BTC 4H candles sequentially
- `SignalManager` (T010) — same state machine, null DB session
- `ScoreEngine` (T009) — same pure functions
- `RiskEngine` (T011) — same position sizing
- `SetupDetector` (T008) — same pure detection functions

No strategy code is reimplemented inside `backtest_engine.py`.

### Decision B — Data Contract

```
Historical data passed in as list[Candle] — oldest candle first.
BacktestEngine does NOT make REST calls during replay.
The caller (test script / CLI) is responsible for fetching data.
```

### Decision C — Sequential Candle Buffer (Look-Ahead Enforcement)

A `_BacktestBuffer` class maintains a sliding window of REVEALED candles.
At step i, the buffer contains candles[0..i] only. The window is advanced
by calling `buffer.advance(candle)` — once advanced, it cannot go back.

This is the primary look-ahead bias guard. All indicator, regime, and
stat computations read from `buffer.get(n)` which returns at most `n`
of the most recently revealed candles.

### Decision D — BTC Regime in Backtest

BTC 4H candles are passed separately (`btc_candles_4h: list[Candle]`).
The engine maintains a `_btc_buffer` advanced in parallel.
Regime is re-classified when a BTC 4H boundary is crossed, using only
BTC candles revealed up to (and including) the current simulation time.

### Decision E — SignalWriter in Backtest

Pass `session_factory=_null_session_factory` to SignalManager:

```python
from contextlib import contextmanager

@contextmanager
def _null_session_factory():
    """No-op synchronous context manager for backtest DB isolation."""
    yield None
```

All DB persistence calls in SignalWriter become no-ops.
In-memory signal state (SignalManager._active_signals) remains fully functional.

### Decision F — DailySession Reset

Reset at UTC midnight boundaries detected within the candle sequence.
Same rule as ScanLoop: candle.open_time.date() change triggers reset.
CANCELLED/EXPIRED signals do not count as trades (same as live).

### Decision G — Entry and Exit Prices

Entry: `candles[i+1].open` (next candle open after TRIGGERED) — same as live.
TP exit: `calculation.take_profit` (rounded price from RiskEngine).
SL exit: `calculation.stop_price` (rounded price from RiskEngine).
If both TP and SL hit same candle: SL wins (conservative — same as live).

### Decision H — Scope

Single-symbol per `BacktestEngine.run()` call.
Multi-symbol aggregation: caller's responsibility (loop + aggregate).
T018 (Full Validation) handles multi-symbol aggregate reporting.

---

## 3. Source-of-Truth Documents

| Document | Sections Required |
|---|---|
| `AGENTS.md` | All |
| `docs/STRATEGY_SPEC.md` | All |
| `docs/RISK_SPEC.md` | §2, §3 |
| `docs/TEST_SPEC.md` | BIT-001 → BIT-006 |
| All T007-T012 approved interfaces | See §9 |

---

## 4. Scope

```
src/scanner/backtest/__init__.py          NEW
src/scanner/backtest/backtest_engine.py   NEW
tests/unit/test_backtest_engine.py        NEW
```

---

## 5. Forbidden Files / Directories

```
docs/STRATEGY_SPEC.md       — PROTECTED
docs/RISK_SPEC.md           — PROTECTED
AGENTS.md                   — PROTECTED
src/scanner/strategy/       — do not modify
src/scanner/risk/           — do not modify
src/scanner/regime/         — do not modify
src/scanner/scan_loop.py    — do not modify
```

---

## 6. Requirements

### R-001 — TradeRecord Dataclass

```python
@dataclass(frozen=True)
class TradeRecord:
    """Immutable record of one completed paper trade in the backtest."""
    signal_id: UUID
    symbol: str
    direction: Direction
    regime_at_detection: Regime
    score: int
    entry_candle_time: datetime    # open_time of trigger candle
    entry_price: Decimal           # next candle open
    stop_price: Decimal            # rounded, from RiskCalculation
    take_profit: Decimal           # rounded, from RiskCalculation
    exit_candle_time: datetime     # candle when TP or SL was hit
    exit_price: Decimal            # take_profit or stop_price
    outcome: SignalState           # TP_HIT or SL_HIT
    qty: Decimal
    rr_ratio: Decimal
    gross_pnl: Decimal
    fee_cost: Decimal
    slippage_cost: Decimal
    net_pnl: Decimal
```

### R-002 — BacktestResult Dataclass

```python
@dataclass(frozen=True)
class BacktestResult:
    """Aggregate performance summary for one symbol over the backtest window."""
    symbol: str
    start_time: datetime
    end_time: datetime
    total_candles_processed: int
    total_signals_detected: int    # reached TRIGGERED (risk approved)
    total_trades: int              # reached TP_HIT or SL_HIT
    winning_trades: int
    losing_trades: int
    win_rate: Decimal              # winning / total_trades; 0 if no trades
    avg_win_pnl: Decimal
    avg_loss_pnl: Decimal
    profit_factor: Decimal         # gross_profit / abs(gross_loss); 0 if no losses
    expectancy: Decimal            # avg net_pnl per trade
    avg_r: Decimal                 # avg net_pnl / avg_risk_distance_usd
    max_drawdown: Decimal          # peak-to-trough on cumulative net_pnl
    sharpe_ratio: Decimal          # annualised (365 days); 0 if < 2 trades
    total_net_pnl: Decimal
    equity_curve: tuple[tuple[datetime, Decimal], ...]  # immutable
    trades: tuple[TradeRecord, ...]                      # immutable
```

### R-003 — BacktestEngine Class

```python
class BacktestEngine:
    """Replay historical candles through approved strategy modules.

    Source: tasks/active/TASK_014_BACKTEST_ENGINE.md
    All look-ahead bias guards are enforced by _BacktestBuffer.
    """

    def __init__(
        self,
        config: ScannerConfig,
        symbol_info: SymbolInfo,
    ) -> None:
        """Construct engine with config and exchange precision info.

        Components (SignalManager, RiskEngine) are created fresh per run()
        call to ensure clean state. No component is shared across runs.
        """

    async def run(
        self,
        symbol: str,
        candles_1h: list[Candle],     # symbol 1H candles, oldest first
        btc_candles_4h: list[Candle], # BTC 4H candles, oldest first
        min_warmup_candles: int = 50, # skip first N candles (indicator warmup)
    ) -> BacktestResult:
        """Replay candles sequentially and return aggregate result.

        Never raises. Any internal error → log ERROR, return empty result.
        """
```

### R-004 — _BacktestBuffer (Look-Ahead Bias Guard)

```python
class _BacktestBuffer:
    """Enforce sequential candle access — zero look-ahead bias.

    Only candles explicitly advanced into the buffer are readable.
    The buffer cannot go backwards.
    """

    def __init__(self, max_size: int = 200) -> None: ...

    def advance(self, candle: Candle) -> None:
        """Reveal one more candle. Oldest candles pruned when max_size exceeded."""

    def get(self, n: int) -> list[Candle]:
        """Return up to n most recent revealed candles, oldest first."""

    def __len__(self) -> int:
        """Return the count of currently revealed candles."""
```

### R-005 — Processing Loop (Decision A enforcement)

```python
# Pseudocode — actual implementation must follow this logic exactly
async def run(...):
    sym_buffer = _BacktestBuffer(max_size=200)
    btc_buffer = _BacktestBuffer(max_size=50)  # 7 days × 6 candles = 42 needed
    regime = Regime.UNDEFINED
    daily_session = DailySession(date=candles_1h[0].open_time.date())
    pending_activations: dict[UUID, Decimal] = {}  # signal_id -> stop_price temp ref
    risk_calculations: dict[UUID, RiskCalculation] = {}
    signal_manager = _make_signal_manager(config)
    risk_engine = RiskEngine(config)

    for i, candle in enumerate(candles_1h):
        # STEP 1: Reveal candle (look-ahead guard)
        sym_buffer.advance(candle)

        # STEP 2: Advance BTC buffer to align timestamps
        _advance_btc_to(btc_buffer, btc_candles_4h, candle.open_time)

        # STEP 3: Refresh regime if BTC 4H boundary
        if _is_4h_btc_boundary(candle.open_time):
            regime = _classify_regime(btc_buffer, config)

        # STEP 4: Skip warmup candles
        if i < min_warmup_candles:
            continue

        # STEP 5: Reset DailySession if date changed
        _reset_session_if_needed(daily_session, candle.open_time.date())

        # STEP 6: Promote TRIGGERED signals to ACTIVE (entry = this candle.open)
        await _promote_triggered(signal_manager, risk_calculations, candle)

        # STEP 7: Check ACTIVE signals for TP/SL on revealed candle
        await _check_active_signals(signal_manager, risk_calculations,
                                    candle, daily_session, trade_records)

        # STEP 8: Run detection if session not halted
        if not daily_session.is_halted:
            await signal_manager.on_candle(
                candle, regime, sym_buffer.get(200)
            )

        # STEP 9: Risk-approve newly TRIGGERED signals
        await _handle_triggered(signal_manager, risk_engine,
                                 risk_calculations, candle,
                                 daily_session, symbol_info)
```

**CRITICAL**: `sym_buffer.advance(candle)` is called FIRST — the candle is
revealed to the buffer BEFORE any computation. This mirrors live behavior
where the closed candle is already in the store when _process_candle fires.
This is NOT look-ahead bias: the current candle is the signal that triggers
the evaluation cycle.

### R-006 — BTC Buffer Alignment

```python
def _advance_btc_to(
    btc_buffer: _BacktestBuffer,
    btc_candles: list[Candle],
    target_time: datetime,
    _pointer: list[int],   # mutable pointer [index]
) -> None:
    """Advance BTC buffer to include all BTC candles with open_time <= target_time."""
    while _pointer[0] < len(btc_candles):
        btc_candle = btc_candles[_pointer[0]]
        if btc_candle.open_time <= target_time:
            btc_buffer.advance(btc_candle)
            _pointer[0] += 1
        else:
            break
```

### R-007 — Performance Metrics

```python
def _compute_metrics(trades: list[TradeRecord], equity_curve: list[...]) -> dict:
    """
    win_rate       = wins / total_trades
    avg_win_pnl    = mean(net_pnl for tp trades)
    avg_loss_pnl   = mean(net_pnl for sl trades)
    profit_factor  = sum(positive net_pnl) / abs(sum(negative net_pnl))
    expectancy     = mean(net_pnl) for all trades
    avg_r          = expectancy / mean(risk_per_trade_usd)
    max_drawdown   = max peak-to-trough decline on cumulative equity
    sharpe_ratio   = annualised Sharpe (365 days):
                     mean_daily_pnl / std_daily_pnl * sqrt(365)
                     where daily_pnl groups trade net_pnl by UTC date
                     Return 0 if fewer than 2 distinct trading days.
    """
```

**Sharpe note**: Use 365-day annualisation (crypto trades every day).
Use UTC date grouping for daily PnL. Use Decimal arithmetic throughout.
If `std_daily_pnl == 0` (all same PnL or 1 day): Sharpe = 0.

### R-008 — Null Session Factory

```python
from contextlib import contextmanager
from collections.abc import Generator
from typing import Any

@contextmanager
def _null_session_factory() -> Generator[None, None, None]:
    """No-op context manager for backtest DB isolation."""
    yield None
```

Passed as `session_factory` to SignalManager. All DB persist calls become
no-ops (SignalWriter already handles `None` session via `inspect.isawaitable`
guard in T010).

### R-009 — Logging

Use `get_logger("backtest")`.

```
INFO:  backtest_started        — symbol, total_candles, warmup
INFO:  backtest_completed      — symbol, total_trades, win_rate, total_pnl
INFO:  trade_recorded          — symbol, outcome, net_pnl
WARN:  signal_no_risk_calc     — signal_id (active signal missing calculation)
ERROR: backtest_engine_failure — symbol, exception_type, message
```

### R-010 — Public Interface

```python
# src/scanner/backtest/__init__.py
from scanner.backtest.backtest_engine import (
    BacktestEngine,
    BacktestResult,
    TradeRecord,
)
__all__ = ["BacktestEngine", "BacktestResult", "TradeRecord"]
```

---

## 7. Non-Goals

- Do NOT fetch REST data during `run()` — caller provides candles
- Do NOT write to SQLite DB (null session factory handles this)
- Do NOT produce HTML/CSV reports (raw BacktestResult only)
- Do NOT optimise strategy parameters (AGENTS.md Article 11)
- Do NOT run multi-symbol aggregation (T018 scope)
- Do NOT implement RANGE_GRID or LONG_PULLBACK (v1.1 scope)

---

## 8. Acceptance Criteria

| AC-ID | Criterion | Test |
|---|---|---|
| AC-001 | Buffer reveals candles strictly oldest-first; cannot go back | `test_buffer_advance_is_irreversible` |
| AC-002 | Candle i+1 is NOT in buffer when candle i is processed | `test_no_lookahead_future_candle_not_visible` |
| AC-003 | BTC buffer only advances to candles <= current 1H time | `test_btc_buffer_not_ahead_of_1h_time` |
| AC-004 | Entry price = candle AFTER trigger, not trigger close | `test_entry_is_next_candle_open` |
| AC-005 | SL wins when both TP and SL hit same candle | `test_sl_wins_same_candle` |
| AC-006 | CANCELLED signals do not count as trades | `test_cancelled_not_counted` |
| AC-007 | DailySession resets at UTC midnight boundary | `test_daily_session_resets` |
| AC-008 | Warmup candles skipped — no signals during warmup | `test_warmup_skips_detection` |
| AC-009 | win_rate = 0 when no trades taken | `test_zero_trades_safe_metrics` |
| AC-010 | profit_factor = 0 when no losing trades | `test_no_losses_profit_factor` |
| AC-011 | Sharpe = 0 when fewer than 2 trading days | `test_sharpe_single_day` |
| AC-012 | max_drawdown is non-negative | `test_max_drawdown_nonnegative` |
| AC-013 | Known sequence: 3 trades, 2 TP, 1 SL → win_rate = 0.667 | `test_known_sequence_metrics` |
| AC-014 | equity_curve is tuple of (datetime, Decimal) pairs | `test_equity_curve_type` |
| AC-015 | BacktestEngine.run() never raises — returns empty result on error | `test_run_never_raises` |
| AC-016 | Identical modules used — no strategy code in backtest_engine.py | Code review |
| AC-017 | `mypy src/ --strict` passes | CI |
| AC-018 | `ruff check src/` passes | CI |
| AC-019 | Full suite >= 345 tests passing | `pytest tests/ -v` |

---

## 9. Required Tests

**File**: `tests/unit/test_backtest_engine.py`

Use synthetic candle sequences — do NOT make real REST calls.
Use `Decimal` for all price values in test fixtures.

```
test_backtest_buffer_advance_appends_oldest_first
test_backtest_buffer_get_returns_n_newest
test_backtest_buffer_max_size_prunes_oldest
test_backtest_buffer_advance_cannot_go_back
test_future_candle_not_in_buffer_at_current_step
test_btc_buffer_aligned_to_1h_candle_time
test_warmup_candles_produce_no_signals
test_entry_price_is_next_candle_open_not_trigger_close
test_long_tp_hit_records_take_profit
test_long_sl_hit_records_stop_loss
test_sl_wins_when_both_hit_same_candle
test_cancelled_signal_not_counted_as_trade
test_expired_signal_not_counted_as_trade
test_daily_session_resets_at_midnight
test_daily_halt_stops_new_detections
test_win_rate_zero_when_no_trades
test_win_rate_correct_for_known_sequence
test_profit_factor_zero_when_no_losing_trades
test_expectancy_correct_sign
test_max_drawdown_nonnegative
test_max_drawdown_zero_with_all_winners
test_sharpe_zero_when_single_trading_day
test_sharpe_positive_with_consistent_wins
test_equity_curve_is_immutable_tuple
test_trade_records_immutable_frozen
test_run_returns_empty_result_on_exception
test_net_pnl_matches_gross_minus_fees_minus_slippage
test_all_decimal_arithmetic_no_float_in_metrics
test_total_signals_detected_only_counts_triggered
test_backtest_result_start_end_time_match_candle_range
```

---

## 10. Escalation Conditions

| Condition | Action |
|---|---|
| SignalManager._null_session_factory does not suppress DB writes | Quote the exception; escalate — do NOT add real DB to backtest |
| RegimeDetector requires more than `list[Candle]` passed via get_closed_candles | Quote the interface; escalate |
| Any candle[i+1] data visible at candle[i] processing step | STOP — do not proceed; this is look-ahead bias |

---

## 11. Completion Report Requirements

```
Task:       T014 — Backtest Engine
Agent:      CODEX

Summary: [2-3 sentences]

Files Created:  [list]
Tests Added:    [count — target >= 30]
Tests Run:      pytest tests/ -v — [N] passed (target >= 345)
Tests Failed:   0

Look-Ahead Bias Verification:
  Buffer advance is irreversible: ✅
  candle[i+1] not in buffer at step i: ✅
  BTC buffer not ahead of 1H time: ✅
  Entry = next candle open: ✅

Known Sequence Verification:
  3-trade sequence, 2 TP + 1 SL: win_rate=0.667 ✅
  net_pnl = gross - fee - slippage ✅

Recommended Next Step:
  SONNET look-ahead bias review (mandatory before APPROVED).
  After APPROVED: GATE-2 (human reviews backtest results).
```

---

## 12. Review Plan

### SONNET Quantitative Review (MANDATORY — GATE-2 prerequisite)

SONNET must explicitly verify EACH of the following. Any FAIL blocks APPROVED:

```
[ ] Buffer advance is irreversible (no random access)
[ ] candle[i+1].open_time not in sym_buffer at processing step i
[ ] BTC buffer only advanced to open_time <= candle_1h.open_time
[ ] 24H stats computed only from revealed candles (buffer.get(24))
[ ] Indicator values (EMA/RSI/ATR) computed only from buffer contents
[ ] Entry price is candle[i+1].open, not candle[i].close
[ ] TP/SL detection uses candle high/low (not close)
[ ] Warmup period prevents signal detection for first N candles
[ ] Sharpe uses 365-day annualisation with Decimal arithmetic
[ ] Profit factor and win rate handle zero-trade edge cases
```

### GEMINI Adversarial Review

- What if `candles_1h` is empty or has 1 element?
- What if `btc_candles_4h` is empty (no regime data)?
- What if all trades are CANCELLED (no TP/SL)?
- What if equity only goes up (max_drawdown = 0)?
- What if std_daily_pnl = 0 (all same PnL)?
- What if warmup > len(candles_1h)?

### CTO Review

- Decision A: no strategy code reimplemented in backtest_engine.py
- Decision C: _BacktestBuffer enforces look-ahead isolation
- Decision E: null session factory used correctly
- Decision G: SL wins same-candle hit confirmed
- All Decimal arithmetic, no float in metrics

---

## 13. Status / Sign-off

| Role | Status | Date |
|---|---|---|
| CTO (created) | ✅ READY | 2026-09-01 |
| Implementation | ⏳ PENDING | — |
| Sonnet quant (MANDATORY) | ⏳ PENDING | — |
| Gemini adversarial | ⏳ PENDING | — |
| CTO final | ⏳ PENDING | — |
| **Release Decision** | ⏳ PENDING | — |
| **GATE-2** | ⏳ PENDING Human Review | — |

---

*End of Task Contract — T014 Backtest Engine*
*NOTE: Sonnet quant look-ahead bias sign-off is MANDATORY before APPROVED.*
*GATE-2 requires human review of actual backtest results on real historical data.*
