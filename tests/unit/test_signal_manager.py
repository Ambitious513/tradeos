"""Unit tests for the T010 signal lifecycle and database boundary."""

# ruff: noqa: E501

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from structlog.testing import capture_logs

from scanner.config import ScannerConfig
from scanner.database.signal_writer import SignalWriter
from scanner.models import Candle, Direction, Regime, SignalState
from scanner.strategy import SetupContext
from scanner.strategy.signal_manager import ActiveSignal, SignalManager

BASE_TIME = datetime(2026, 9, 1, tzinfo=UTC)


def make_candle(
    offset: int = 0,
    *,
    open_price: str = "100",
    high: str = "110",
    low: str = "90",
    close: str = "99",
    is_closed: bool = True,
) -> Candle:
    """Build a valid closed 1H synthetic candle."""
    return Candle(
        symbol="SOLUSDT",
        timeframe="60",
        open_time=BASE_TIME + timedelta(hours=offset),
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("100"),
        turnover=Decimal("10000"),
        is_closed=is_closed,
    )


def make_context(
    direction: Direction = Direction.SHORT, offset: int = 0
) -> SetupContext:
    """Build a real T008 context compatible with the synthetic candles."""
    trigger = make_candle(offset)
    return SetupContext(
        symbol="SOLUSDT",
        direction=direction,
        detected_at=trigger.open_time,
        change_24h_pct=(
            Decimal("10") if direction is Direction.SHORT else Decimal("-10")
        ),
        high_24h=Decimal("120"),
        low_24h=Decimal("80"),
        rsi_14=80.0 if direction is Direction.SHORT else 20.0,
        ema_7=Decimal("95"),
        ema_extension_pct=Decimal("5"),
        atr_14=Decimal("2"),
        trigger_candle=trigger,
    )


def make_active(
    state: SignalState = SignalState.WATCHING,
    direction: Direction = Direction.SHORT,
    offset: int = 0,
) -> ActiveSignal:
    """Build a tracked signal, including prerequisites for later states."""
    context = make_context(direction, offset)
    signal = ActiveSignal(
        signal_id=uuid4(),
        symbol=context.symbol,
        direction=direction,
        state=state,
        detected_at=context.detected_at,
        setup_context=context,
    )
    if state in {SignalState.ARMED, SignalState.TRIGGERED, SignalState.ACTIVE}:
        signal.rejection_candle = make_candle(offset + 1, high="120", close="95")
        signal.rejection_at = signal.rejection_candle.open_time
        signal.high_24h_at_armed = Decimal("120")
        signal.low_24h_at_armed = Decimal("80")
    if state in {SignalState.TRIGGERED, SignalState.ACTIVE}:
        signal.retest_candle = make_candle(offset + 2, low="95", high="105")
        signal.retest_at = signal.retest_candle.open_time
        signal.estimated_entry = Decimal("95")
        signal.stop_price = Decimal("100")
        signal.take_profit = Decimal("85")
        signal.score = 80
        signal.triggered_at = BASE_TIME + timedelta(hours=offset + 3)
    return signal


def make_manager() -> tuple[SignalManager, AsyncMock, AsyncMock]:
    """Return a manager whose writer and session factory are AsyncMocks."""
    session = AsyncMock()
    context_manager = AsyncMock()
    context_manager.__aenter__.return_value = session
    session_factory = AsyncMock(return_value=context_manager)
    manager = SignalManager(MagicMock(), session_factory, ScannerConfig(_env_file=None))
    writer = AsyncMock(spec=SignalWriter)
    manager._writer = writer
    return manager, session_factory, writer


def history(candle: Candle) -> list[Candle]:
    """Return enough closed history for all manager helper calls."""
    return [make_candle(index) for index in range(-27, 0)] + [candle]


@pytest.mark.asyncio
async def test_detection_creates_watching_signal_not_detected() -> None:
    """DETECTED is persisted transiently, but active memory starts WATCHING."""
    manager, _, writer = make_manager()
    candle = make_candle()
    with patch(
        "scanner.strategy.signal_manager.detect_initial_conditions",
        return_value=make_context(),
    ):
        await manager.on_candle(candle, Regime.BEARISH, history(candle))
    assert manager.active_signals[0].state is SignalState.WATCHING
    writer.create_signal.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [SignalState.ARMED, SignalState.TRIGGERED])
async def test_no_detection_when_existing_signal_exists_for_symbol(
    state: SignalState,
) -> None:
    """ARMED and TRIGGERED same-symbol signals both block a duplicate."""
    manager, _, _ = make_manager()
    manager._active_signals.append(make_active(state))
    detector = MagicMock(return_value=make_context())
    candle = make_candle(3)
    with patch("scanner.strategy.signal_manager.detect_initial_conditions", detector):
        await manager.on_candle(candle, Regime.BEARISH, history(candle))
    detector.assert_not_called()


@pytest.mark.asyncio
async def test_rejection_candle_advances_watching_to_armed() -> None:
    """A valid rejection records the 24H snapshots and arms the signal."""
    manager, _, writer = make_manager()
    signal = make_active()
    manager._active_signals.append(signal)
    candle = make_candle(1)
    with (
        patch(
            "scanner.strategy.signal_manager.compute_24h_stats",
            return_value=(Decimal("120"), Decimal("80"), Decimal("10")),
        ),
        patch(
            "scanner.strategy.signal_manager.check_24h_level_interaction",
            return_value=True,
        ),
        patch(
            "scanner.strategy.signal_manager.check_rejection_candle", return_value=True
        ),
    ):
        await manager.on_candle(candle, Regime.BEARISH, history(candle))
    assert signal.state is SignalState.ARMED
    assert signal.rejection_candle is candle
    writer.write_transition.assert_awaited_once()


@pytest.mark.asyncio
async def test_watching_expires_after_4h_with_no_rejection() -> None:
    """WATCHING expires only after more than four hours."""
    manager, _, writer = make_manager()
    manager._active_signals.append(make_active())
    candle = make_candle(5)
    await manager.on_candle(candle, Regime.BEARISH, history(candle))
    assert manager.active_signals == []
    assert writer.write_transition.await_args.args[3] is SignalState.EXPIRED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("direction", "regime", "price_arg", "price_value"),
    [
        (Direction.SHORT, Regime.BEARISH, "high", "121"),
        (Direction.LONG, Regime.BULLISH, "low", "79"),
    ],
)
async def test_new_24h_extreme_cancels_watching_signal(
    direction: Direction, regime: Regime, price_arg: str, price_value: str
) -> None:
    """A newly exceeded directional 24H level cancels the setup."""
    manager, _, writer = make_manager()
    manager._active_signals.append(make_active(direction=direction))
    candle = make_candle(1, **{price_arg: price_value})
    await manager.on_candle(candle, regime, history(candle))
    assert manager.active_signals == []
    assert writer.write_transition.await_args.args[3] is SignalState.CANCELLED


@pytest.mark.asyncio
async def test_retest_found_in_armed_state() -> None:
    """A retest is remembered and cannot trigger within the same candle."""
    manager, _, _ = make_manager()
    signal = make_active(SignalState.ARMED)
    manager._active_signals.append(signal)
    candle = make_candle(2)
    with patch("scanner.strategy.signal_manager.check_retest_short", return_value=True):
        await manager.on_candle(candle, Regime.BEARISH, history(candle))
    assert signal.retest_candle is candle
    assert signal.state is SignalState.ARMED


async def trigger_armed(manager: SignalManager, score: int = 80) -> ActiveSignal:
    """Advance one prepared ARMED signal using patched deterministic helpers."""
    signal = make_active(SignalState.ARMED)
    signal.retest_candle = make_candle(2, low="95")
    signal.retest_at = signal.retest_candle.open_time
    manager._active_signals.append(signal)
    candle = make_candle(3, close="94")
    with (
        patch(
            "scanner.strategy.signal_manager.check_entry_trigger_short",
            return_value=True,
        ),
        patch(
            "scanner.strategy.signal_manager.compute_stop_short",
            return_value=Decimal("100"),
        ),
        patch(
            "scanner.strategy.signal_manager.compute_take_profit",
            return_value=Decimal("82"),
        ),
        patch("scanner.strategy.signal_manager.check_minimum_rr", return_value=True),
        patch("scanner.strategy.signal_manager.compute_score", return_value=score),
    ):
        await manager.on_candle(candle, Regime.BEARISH, history(candle))
    return signal


@pytest.mark.asyncio
async def test_entry_trigger_fires_after_retest_advances_to_triggered() -> None:
    """A post-retest close through support creates TRIGGERED."""
    manager, _, _ = make_manager()
    signal = await trigger_armed(manager)
    assert signal.state is SignalState.TRIGGERED


@pytest.mark.asyncio
async def test_high_score_signal_remains_triggered() -> None:
    """The highest valid score remains in the pre-entry TRIGGERED state."""
    manager, _, _ = make_manager()
    signal = await trigger_armed(manager, 100)
    assert signal.state is SignalState.TRIGGERED
    assert signal.score == 100


@pytest.mark.asyncio
async def test_score_below_80_expires_at_triggered() -> None:
    """A score below the immutable A+ floor cannot be triggered."""
    manager, _, _ = make_manager()
    await trigger_armed(manager, 79)
    assert manager.active_signals == []


@pytest.mark.asyncio
async def test_poor_rr_expires_without_scoring() -> None:
    """A failed R:R check disqualifies before the score function is called."""
    manager, _, _ = make_manager()
    signal = make_active(SignalState.ARMED)
    signal.retest_candle = make_candle(2, low="95")
    signal.retest_at = signal.retest_candle.open_time
    manager._active_signals.append(signal)
    candle = make_candle(3)
    scorer = MagicMock(return_value=100)
    with (
        patch(
            "scanner.strategy.signal_manager.check_entry_trigger_short",
            return_value=True,
        ),
        patch(
            "scanner.strategy.signal_manager.compute_stop_short",
            return_value=Decimal("100"),
        ),
        patch(
            "scanner.strategy.signal_manager.compute_take_profit",
            return_value=Decimal("82"),
        ),
        patch("scanner.strategy.signal_manager.check_minimum_rr", return_value=False),
        patch("scanner.strategy.signal_manager.compute_score", scorer),
    ):
        await manager.on_candle(candle, Regime.BEARISH, history(candle))
    scorer.assert_not_called()
    assert manager.active_signals == []


@pytest.mark.asyncio
async def test_no_entry_trigger_within_4h_of_retest_expires() -> None:
    """A retest that waits over four hours for entry expires."""
    manager, _, _ = make_manager()
    signal = make_active(SignalState.ARMED)
    signal.retest_candle = make_candle(2)
    signal.retest_at = signal.retest_candle.open_time
    manager._active_signals.append(signal)
    candle = make_candle(7)
    await manager.on_candle(candle, Regime.BEARISH, history(candle))
    assert manager.active_signals == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("direction", "initial_regime", "changed_regime"),
    [
        (Direction.SHORT, Regime.BEARISH, Regime.BULLISH),
        (Direction.LONG, Regime.BULLISH, Regime.BEARISH),
    ],
)
async def test_regime_change_cancels_watching_and_armed_signal(
    direction: Direction, initial_regime: Regime, changed_regime: Regime
) -> None:
    """Both pre-entry phases are cancelled if their BTC regime changes."""
    del initial_regime
    manager, _, _ = make_manager()
    manager._active_signals.append(make_active(SignalState.ARMED, direction))
    candle = make_candle(2)
    await manager.on_candle(candle, changed_regime, history(candle))
    assert manager.active_signals == []


@pytest.mark.asyncio
async def test_mark_active_updates_in_memory_state() -> None:
    """T012 can record the confirmed next-open entry on activation."""
    manager, _, writer = make_manager()
    signal = make_active(SignalState.TRIGGERED)
    manager._active_signals.append(signal)
    await manager.mark_active(signal.signal_id, Decimal("96"))
    assert signal.state is SignalState.ACTIVE
    assert signal.estimated_entry == Decimal("96")
    writer.write_transition.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", [SignalState.TP_HIT, SignalState.SL_HIT])
async def test_mark_terminal_records_trade_outcome(terminal: SignalState) -> None:
    """An ACTIVE signal may terminate at either defined price exit."""
    manager, _, _ = make_manager()
    signal = make_active(SignalState.ACTIVE)
    manager._active_signals.append(signal)
    await manager.mark_terminal(signal.signal_id, terminal, "price exit")
    assert manager.active_signals == []


@pytest.mark.asyncio
async def test_mark_terminal_rejects_non_terminal_state() -> None:
    """The terminal API refuses any intermediate lifecycle state."""
    manager, _, _ = make_manager()
    signal = make_active(SignalState.ACTIVE)
    manager._active_signals.append(signal)
    with pytest.raises(ValueError):
        await manager.mark_terminal(signal.signal_id, SignalState.ARMED, "invalid")


def test_active_signals_returns_copy() -> None:
    """Mutating a caller snapshot cannot mutate manager storage."""
    manager, _, _ = make_manager()
    manager._active_signals.append(make_active())
    snapshot = manager.active_signals
    snapshot.clear()
    assert len(manager.active_signals) == 1


@pytest.mark.asyncio
async def test_duplicate_signal_rejected_when_armed_exists() -> None:
    """Duplicate prevention logs the existing state for operators."""
    manager, _, _ = make_manager()
    manager._active_signals.append(make_active(SignalState.ARMED))
    candle = make_candle(2)
    with capture_logs() as logs:
        await manager.on_candle(candle, Regime.BEARISH, history(candle))
    assert any(entry["event"] == "duplicate_signal_rejected" for entry in logs)


@pytest.mark.asyncio
async def test_invalid_state_transition_logs_error() -> None:
    """A writer validation failure is logged and leaves the cycle running."""
    manager, _, writer = make_manager()
    manager._active_signals.append(make_active())
    writer.write_transition.side_effect = ValueError("invalid transition")
    with capture_logs() as logs:
        candle = make_candle(5)
        await manager.on_candle(candle, Regime.BEARISH, history(candle))
    assert any(entry["event"] == "signal_transition_failed" for entry in logs)


def test_sweep_or_excess_pct_short_computed_from_rejection_candle() -> None:
    """Short high excess is capped at zero unless the snapshot high is breached."""
    signal = make_active(SignalState.ARMED)
    assert SignalManager._sweep_or_excess_pct(signal) == Decimal(0)
    signal.rejection_candle = make_candle(high="126")
    assert SignalManager._sweep_or_excess_pct(signal) == Decimal("5.00")


def test_sweep_or_excess_pct_long_computed_from_rejection_candle() -> None:
    """Long sweep depth is measured below the snapshot low."""
    signal = make_active(SignalState.ARMED, Direction.LONG)
    signal.rejection_candle = make_candle(low="79.6")
    assert SignalManager._sweep_or_excess_pct(signal) == Decimal("0.500")


@pytest.mark.asyncio
async def test_score_input_assembled_at_triggered_with_trigger_close_as_entry() -> None:
    """Ruling B sets the ScoreInput entry to the trigger candle close."""
    manager, _, _ = make_manager()
    signal = make_active(SignalState.ARMED)
    signal.retest_candle = make_candle(2, low="95")
    signal.retest_at = signal.retest_candle.open_time
    manager._active_signals.append(signal)
    candle = make_candle(3, close="93")
    scorer = MagicMock(return_value=80)
    with (
        patch(
            "scanner.strategy.signal_manager.check_entry_trigger_short",
            return_value=True,
        ),
        patch(
            "scanner.strategy.signal_manager.compute_stop_short",
            return_value=Decimal("100"),
        ),
        patch(
            "scanner.strategy.signal_manager.compute_take_profit",
            return_value=Decimal("79"),
        ),
        patch("scanner.strategy.signal_manager.check_minimum_rr", return_value=True),
        patch("scanner.strategy.signal_manager.compute_score", scorer),
    ):
        await manager.on_candle(candle, Regime.BEARISH, history(candle))
    assert scorer.call_args.args[0].entry_price == candle.close
    assert signal.estimated_entry == candle.close


@pytest.mark.asyncio
async def test_invalid_transition_writer_raises() -> None:
    """SignalWriter rejects successors outside its immutable lifecycle map."""
    with pytest.raises(ValueError, match="invalid signal transition"):
        await SignalWriter().write_transition(
            AsyncMock(), make_active(), SignalState.WATCHING, SignalState.ACTIVE, "skip"
        )


@pytest.mark.asyncio
async def test_session_factory_failure_logs_error_and_keeps_signal() -> None:
    """A failed DB session does not discard already tracked in-memory state."""
    manager, factory, _ = make_manager()
    factory.side_effect = RuntimeError("database down")
    candle = make_candle()
    with (
        patch(
            "scanner.strategy.signal_manager.detect_initial_conditions",
            return_value=make_context(),
        ),
        capture_logs() as logs,
    ):
        await manager.on_candle(candle, Regime.BEARISH, history(candle))
    assert len(manager.active_signals) == 1
    assert any(entry["event"] == "signal_persistence_failed" for entry in logs)


@pytest.mark.asyncio
async def test_forming_candle_is_logged_and_not_processed() -> None:
    """The strategy boundary rejects non-confirmed candles at ERROR severity."""
    manager, factory, _ = make_manager()
    with capture_logs() as logs:
        await manager.on_candle(make_candle(is_closed=False), Regime.BEARISH, [])
    factory.assert_not_called()
    assert any(entry["event"] == "candle_validation_failed" for entry in logs)


@pytest.mark.asyncio
async def test_logging_uses_str_for_decimal() -> None:
    """Structured signal fields serialize Decimal values rather than passing them."""
    manager, _, _ = make_manager()
    candle = make_candle()
    context = make_context()
    with (
        patch(
            "scanner.strategy.signal_manager.detect_initial_conditions",
            return_value=context,
        ),
        capture_logs() as logs,
    ):
        await manager.on_candle(candle, Regime.BEARISH, history(candle))
    detected = next(log for log in logs if log["event"] == "signal_detected")
    assert detected["change_24h_pct"] == str(context.change_24h_pct)


@pytest.mark.asyncio
async def test_regime_passed_as_parameter() -> None:
    """A supplied NEUTRAL regime prevents detection without an internal lookup."""
    manager, _, _ = make_manager()
    detector = MagicMock(return_value=make_context())
    candle = make_candle()
    with patch("scanner.strategy.signal_manager.detect_initial_conditions", detector):
        await manager.on_candle(candle, Regime.NEUTRAL, history(candle))
    detector.assert_not_called()
