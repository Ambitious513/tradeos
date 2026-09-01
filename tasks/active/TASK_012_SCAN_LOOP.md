# TASK CONTRACT
# ═══════════════════════════════════════════════════════════════
# Task ID:        T012
# Task Name:      ScanLoop — Main Orchestration Loop
# Status:         APPROVED — 2026-09-01
# Priority:       P1
# Owner Agent:    CODEX
# Reviewer:       SONNET (integration), GEMINI (adversarial), CTO (final)
# Created By:     Lead CTO (Opus/Fable)
# Created Date:   2026-09-01
# Depends On:     T005, T007, T010, T011 (all APPROVED)
# Blocks:         T013 (Alerts), T014 (Backtest)
# ═══════════════════════════════════════════════════════════════

---

## 1. Objective

Implement the main async orchestration loop that connects all approved
components into an end-to-end paper trading scanner:

```
WebSocket candles
    → RegimeDetector
    → SignalManager.on_candle()
    → RiskEngine.approve()        (when TRIGGERED signal detected)
    → SignalManager.mark_active() (confirmed entry = next candle open)
    → TP/SL monitoring            (on each closed candle for ACTIVE signals)
    → SignalManager.mark_terminal()
    → DailySession lifecycle
```

T012 does NOT implement live order placement, Telegram/Discord alerts
(T013), or the backtest engine (T014).

---

## 2. Background and CTO Design Decisions

### Decision A — Regime Refresh Timing

BTC regime is re-classified on every new 4H closed candle.
4H candle detection: a candle is a 4H close when its `open_time` is
evenly divisible by 4 hours (i.e. `open_time.hour % 4 == 0` AND
`open_time.minute == 0`). The regime is cached between 4H closes.
Stale regime (no 4H close in > 4H + 5 min) → `Regime.UNDEFINED` →
`on_candle()` is still called but no new detections occur.

### Decision B — TRIGGERED → ACTIVE Promotion

When a signal is TRIGGERED on closed candle N, the confirmed entry is
the open of candle N+1. Since we process only closed candles, we learn
candle N+1's open when candle N+1 closes (the `Candle.open` field).

Rule: after processing each closed candle, check for TRIGGERED signals
whose `triggered_at` is BEFORE the current candle's `open_time`. These
signals must be promoted to ACTIVE using `current_candle.open` as the
confirmed entry.

```
candle N closes  → signal becomes TRIGGERED (triggered_at = N.open_time)
candle N+1 closes (open_time = N.open_time + 1H)
    → signal.triggered_at < candle_N1.open_time → promote
    → confirmed_entry = candle_N1.open
```

### Decision C — TP/SL Hit Detection (Paper Trading)

For each closed 1H candle that belongs to a symbol with an ACTIVE signal:

```python
# LONG ACTIVE:
sl_hit = candle.low  <= signal.stop_price
tp_hit = candle.high >= signal.take_profit

# SHORT ACTIVE:
sl_hit = candle.high >= signal.stop_price
tp_hit = candle.low  <= signal.take_profit

# If both hit in same candle: SL wins (conservative)
# realized_pnl on TP:
#   LONG:  take_profit - confirmed_entry   (per unit, times qty, minus fees)
#   SHORT: confirmed_entry - take_profit
# realized_pnl on SL:
#   LONG:  stop_price - confirmed_entry
#   SHORT: confirmed_entry - stop_price
# Apply taker_fee (both sides) and slippage (both sides) from config
```

### Decision D — DailySession Lifecycle

One `DailySession` per UTC calendar day, reset at midnight.
After each terminal outcome (TP_HIT or SL_HIT), update `realized_pnl`
and `trades_taken`. Check `RiskEngine.check_daily_limits()` after each
update; halt if a limit is now breached.

CANCELLED signals do NOT count as a trade and do NOT affect PnL.
EXPIRED signals do NOT count as a trade.

---

## 3. Source-of-Truth Documents

| Document | Sections Required |
|---|---|
| `AGENTS.md` | All |
| `docs/STRATEGY_SPEC.md` | §6 (state machine), §10 (expiration), REGIME-001 |
| `docs/RISK_SPEC.md` | §3 (daily session), §8 (failure behavior) |
| All approved T005-T011 interfaces | See §9 of this contract |

---

## 4. Scope

```
src/scanner/scan_loop.py              NEW — ScanLoop class
tests/unit/test_scan_loop.py          NEW — mocked component tests
```

---

## 5. Forbidden Files / Directories

```
docs/STRATEGY_SPEC.md       — PROTECTED
docs/RISK_SPEC.md           — PROTECTED
AGENTS.md                   — PROTECTED
src/scanner/strategy/       — do not modify (T008-T010)
src/scanner/risk/           — do not modify (T011)
src/scanner/regime/         — do not modify (T007)
src/scanner/candle_store/   — do not modify (T005)
src/scanner/market_data/    — do not modify (T003-T004)
```

---

## 6. Requirements

### R-001 — ScanLoop Class

```python
class ScanLoop:
    """Orchestrate the full A+ paper-trading pipeline from candle to terminal outcome.

    Source: tasks/active/TASK_012_SCAN_LOOP.md
    """

    def __init__(
        self,
        config: ScannerConfig,
        candle_store: CandleStore,
        universe_manager: UniverseManager,
        ws_client: BybitWebSocketClient,
        regime_detector: RegimeDetector,
        signal_manager: SignalManager,
        risk_engine: RiskEngine,
        session_factory: Callable[[], AsyncContextManager[AsyncSession]],
    ) -> None: ...

    async def run(self) -> None:
        """Start the loop: pre-fill candles, subscribe WS, process until shutdown.

        Startup sequence (in order):
          1. Refresh universe (UniverseManager.get_universe())
          2. Pre-fill candles via REST for all universe symbols + BTCUSDT
             (CandleStore.prefill() or equivalent)
          3. Classify initial BTC regime
          4. Subscribe WS to all 1H streams (universe symbols + BTCUSDT)
          5. Enter main candle processing loop
          6. Refresh universe every 24H (subscribe new, ignore removed)
        """

    async def shutdown(self) -> None:
        """Signal the loop to stop after current candle completes."""

    @property
    def daily_session(self) -> DailySession:
        """Return the current DailySession (reset at UTC midnight automatically)."""
```

### R-002 — Candle Processing Pipeline

```python
async def _process_candle(self, candle: Candle) -> None:
    """Handle one newly closed 1H candle.

    Steps (in order):
      1. Reset DailySession if UTC date changed since last candle
      2. If candle is a 4H BTC close: re-classify regime; update cached regime
      3. _promote_triggered_signals(candle)   → TRIGGERED → ACTIVE
      4. _check_active_signals(candle)        → TP/SL monitoring
      5. If daily_session.is_halted: skip steps 6-7 for new detections
      6. signal_manager.on_candle(candle, self._regime, candles_1h)
      7. _handle_triggered(candle)            → risk approval for newly TRIGGERED signals
    """
```

### R-003 — TRIGGERED → ACTIVE Promotion

```python
async def _promote_triggered_signals(self, candle: Candle) -> None:
    """Promote TRIGGERED signals to ACTIVE using current candle.open.

    Condition: signal.state == TRIGGERED
               AND signal.triggered_at < candle.open_time
               AND signal.symbol == candle.symbol

    Calls: signal_manager.mark_active(signal.signal_id, candle.open)
    Logs:  INFO signal_entry_confirmed — signal_id, symbol, confirmed_entry
    """
```

### R-004 — Risk Approval for Newly TRIGGERED Signals

```python
async def _handle_triggered(self, candle: Candle) -> None:
    """Run risk approval for signals that became TRIGGERED this candle cycle.

    For each TRIGGERED signal for candle.symbol:
      1. signal.triggered_at == candle.open_time  (triggered on THIS candle)
      2. Retrieve symbol_info from CandleStore or REST
      3. Call risk_engine.approve(
             entry_price   = signal.estimated_entry,
             stop_price    = signal.stop_price,
             take_profit   = signal.take_profit,
             direction     = signal.direction,
             symbol_info   = symbol_info,
             daily_session = self._daily_session,
         )
      4. If not approved:
             signal_manager.mark_terminal(signal.signal_id, CANCELLED, decision.reason)
             log INFO risk_rejected
      5. If approved:
             Store decision.calculation for later PnL computation
             (Promotion to ACTIVE happens on NEXT candle via _promote_triggered_signals)
             log INFO risk_approved_awaiting_entry
    """
```

### R-005 — TP/SL Monitoring

```python
async def _check_active_signals(self, candle: Candle) -> None:
    """Evaluate TP and SL levels for all ACTIVE signals on candle.symbol.

    Hit detection (Decision C):
      LONG:  sl_hit = candle.low  <= signal.stop_price
             tp_hit = candle.high >= signal.take_profit
      SHORT: sl_hit = candle.high >= signal.stop_price
             tp_hit = candle.low  <= signal.take_profit

    Priority: if sl_hit AND tp_hit → SL wins (conservative paper assumption)

    PnL calculation (per unit, then times qty):
      TP LONG:  take_profit - confirmed_entry
      SL LONG:  stop_price  - confirmed_entry
      TP SHORT: confirmed_entry - take_profit
      SL SHORT: confirmed_entry - stop_price
      fee_usd = qty * exit_price * taker_fee_rate * 2  (entry already paid)
      slippage_usd = qty * exit_price * slippage_rate * 2
      net_pnl = gross_pnl - fee_usd - slippage_usd

    Updates:
      daily_session.realized_pnl += net_pnl
      daily_session.trades_taken += 1
      Check daily limits; halt session if breached
      signal_manager.mark_terminal(signal_id, TP_HIT or SL_HIT, reason)
    """
```

### R-006 — DailySession Lifecycle

```python
def _get_or_reset_daily_session(self) -> DailySession:
    """Return current session; replace with fresh session if UTC date changed.

    Fresh DailySession has: trades_taken=0, realized_pnl=0, is_halted=False.
    Called at the start of _process_candle for every candle.
    """
```

### R-007 — Regime Refresh

```python
def _is_4h_btc_close(self, candle: Candle) -> bool:
    """Return True if candle is a closed 4H boundary for BTCUSDT.

    Conditions:
      candle.symbol == "BTCUSDT"
      candle.open_time.hour % 4 == 0
      candle.open_time.minute == 0
    """

def _refresh_regime(self) -> None:
    """Re-classify BTC regime; update self._regime.

    If RegimeDetector.classify() raises: self._regime = Regime.UNDEFINED; log ERROR.
    """
```

### R-008 — Logging

Use `get_logger("scan_loop")`.

```
INFO:  scan_loop_started          — universe_size, initial_regime
INFO:  candle_processed           — symbol, open_time (DEBUG-level frequency)
INFO:  regime_updated             — regime, change_24h_pct
INFO:  risk_approved_awaiting_entry — signal_id, symbol, estimated_entry, stop, tp
INFO:  risk_rejected              — signal_id, symbol, reason
INFO:  signal_entry_confirmed     — signal_id, symbol, confirmed_entry
INFO:  position_closed_tp         — signal_id, symbol, net_pnl, daily_pnl
INFO:  position_closed_sl         — signal_id, symbol, net_pnl, daily_pnl
INFO:  daily_session_halted       — reason, realized_pnl, trades_taken
INFO:  daily_session_reset        — date
WARN:  symbol_info_unavailable    — symbol (when REST fallback needed and fails)
ERROR: regime_refresh_failed      — exception_type, message
ERROR: risk_engine_error          — symbol, exception_type
```

All Decimal values logged as `str()`.

---

## 7. Non-Goals

- Do NOT implement Telegram or Discord alerting (T013)
- Do NOT implement backtest candle replay (T014)
- Do NOT place real exchange orders
- Do NOT implement the WebSocket reconnection logic (already in T004)
- Do NOT track margin or leverage

---

## 8. Acceptance Criteria

| AC-ID | Criterion | Test |
|---|---|---|
| AC-001 | 4H BTC close triggers regime reclassification | `test_regime_refreshed_on_4h_btc_close` |
| AC-002 | Non-4H candle does NOT refresh regime | `test_regime_not_refreshed_on_1h_candle` |
| AC-003 | TRIGGERED signal promoted with next candle open | `test_triggered_promoted_on_next_candle` |
| AC-004 | Risk rejected → signal CANCELLED | `test_risk_rejection_cancels_triggered_signal` |
| AC-005 | LONG TP hit: sl_hit=False, tp_hit=True | `test_long_tp_hit_detected` |
| AC-006 | LONG SL hit: sl_hit=True, tp_hit=False | `test_long_sl_hit_detected` |
| AC-007 | SHORT TP hit: candle.low <= take_profit | `test_short_tp_hit_detected` |
| AC-008 | SHORT SL hit: candle.high >= stop_price | `test_short_sl_hit_detected` |
| AC-009 | Both TP and SL hit same candle → SL wins | `test_sl_wins_when_both_hit` |
| AC-010 | net_pnl = gross - fees - slippage | `test_pnl_calculation_correct` |
| AC-011 | DailySession reset at UTC midnight | `test_daily_session_resets_at_midnight` |
| AC-012 | Loss limit breached → session halted | `test_loss_limit_halts_session` |
| AC-013 | Halted session → no new signal detections | `test_halted_session_blocks_detection` |
| AC-014 | CANCELLED/EXPIRED signals do not count as trades | `test_cancelled_does_not_increment_trades` |
| AC-015 | `shutdown()` stops the loop cleanly | `test_shutdown_stops_loop` |
| AC-016 | `mypy src/ --strict` passes | CI |
| AC-017 | `ruff check src/` passes | CI |
| AC-018 | Full suite >= 285 tests passing | `pytest tests/ -v` |

---

## 9. Required Tests

**File**: `tests/unit/test_scan_loop.py`

Use `unittest.mock.AsyncMock` for all component dependencies.
Do NOT test WS reconnection (T004 scope).

```
test_4h_btc_close_triggers_regime_refresh
test_non_btc_candle_does_not_trigger_regime_refresh
test_non_4h_btc_candle_does_not_trigger_regime_refresh
test_triggered_signal_promoted_to_active_on_next_candle
test_risk_rejection_cancels_triggered_signal
test_risk_approval_stores_calculation
test_long_tp_hit_closes_signal
test_long_sl_hit_closes_signal
test_short_tp_hit_closes_signal
test_short_sl_hit_closes_signal
test_sl_wins_when_both_hit_same_candle
test_net_pnl_long_tp_correct
test_net_pnl_long_sl_correct
test_net_pnl_short_tp_correct
test_net_pnl_short_sl_correct
test_daily_session_resets_when_date_changes
test_loss_limit_reached_halts_session
test_profit_lock_reached_halts_session
test_trade_limit_reached_halts_session
test_halted_session_skips_new_signal_detection
test_cancelled_signal_does_not_increment_trades_taken
test_expired_signal_does_not_increment_trades_taken
test_regime_undefined_on_refresh_failure
test_shutdown_sets_stop_flag
test_daily_pnl_accumulates_across_multiple_trades
test_only_active_signals_monitored_for_tp_sl
```

---

## 10. Escalation Conditions

STOP and escalate if:

| Condition | Action |
|---|---|
| BybitWebSocketClient does not expose a subscribe-by-symbol interface | Quote ws_client API; escalate |
| CandleStore.get_closed_candles returns forming candle | Quote candle_store API; confirm is_closed filtering |
| SymbolInfo unavailable at risk-approval time | Use REST fallback; if REST fails, CANCEL signal + log WARN |

---

## 11. Completion Report Requirements

```
Task:       T012 — ScanLoop
Agent:      CODEX

Summary: [2-3 sentences]

Files Created:  [list]
Tests Added:    [count — target >= 26]
Tests Run:      pytest tests/ -v — [N] passed (target >= 285)
Tests Failed:   0

Pipeline Verification:
  4H close → regime refresh: ✅
  TRIGGERED → ACTIVE on next candle.open: ✅
  SL wins when both hit: ✅
  net_pnl: gross - fee - slippage ✅
  Halted session blocks new detections: ✅

Recommended Next Step: T013 (Alert Engine)
```

---

## 12. Review Plan

### SONNET Integration Review
- Step order in _process_candle: reset session → 4H check → promote → TP/SL → halt check → detect → handle_triggered
- PnL formula: gross_pnl ± fees ± slippage signs correct per direction
- DailySession boundary: `<=` for loss limit, `>=` for profit lock and trade count

### GEMINI Adversarial Review
- What if signal_manager raises inside on_candle? Log error; do not crash loop
- What if RiskEngine raises? Already guarded inside approve(); logs ERROR; decision.approved=False
- What if two ACTIVE signals exist for same symbol? (should not happen via duplicate guard in T010; log ERROR if detected)
- What if candle.open == 0? (guard in promotion step — do not promote with zero entry)

### CTO Review
- Decision A/B/C compliance verified
- CANCELLED/EXPIRED do not affect DailySession trades_taken or realized_pnl
- SL wins when both hit (paper-conservative)

---

## 13. Status / Sign-off

| Role | Status | Date |
|---|---|---|
| CTO (created) | ✅ READY | 2026-09-01 |
| Implementation | ⏳ PENDING | — |
| Sonnet integration | ⏳ PENDING | — |
| Gemini adversarial | ⏳ PENDING | — |
| CTO final | ⏳ PENDING | — |
| **Release Decision** | ⏳ PENDING | — |

---

*End of Task Contract — T012 ScanLoop*

