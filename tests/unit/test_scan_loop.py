"""Mocked orchestration tests for the T012 closed-candle scan loop."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from scanner.config import ScannerConfig
from scanner.market_data.models import SymbolInfo
from scanner.models import Candle, Direction, Regime, SignalState
from scanner.risk import DailySession, RiskCalculation, RiskDecision
from scanner.scan_loop import ScanLoop

BASE_TIME = datetime(2026, 9, 1, tzinfo=UTC)


def candle(
    offset: int = 0,
    *,
    symbol: str = "SOLUSDT",
    timeframe: str = "60",
    open_price: str = "100",
    high: str = "105",
    low: str = "95",
    close: str = "100",
) -> Candle:
    """Build one confirmed candle for deterministic paper-trading tests."""
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        open_time=BASE_TIME + timedelta(hours=offset),
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("100"),
        turnover=Decimal("10000"),
        is_closed=True,
    )


def info() -> SymbolInfo:
    """Build the exchange metadata used for risk approval mocks."""
    return SymbolInfo(
        symbol="SOLUSDT",
        base_coin="SOL",
        quote_coin="USDT",
        status="Trading",
        tick_size=Decimal("0.01"),
        lot_size=Decimal("0.01"),
        min_order_qty=Decimal("0.01"),
        max_leverage=50.0,
        contract_type="LinearPerpetual",
    )


def calculation(
    *, qty: str = "1", entry: str = "100", stop: str = "98", tp: str = "104"
) -> RiskCalculation:
    """Build an approved calculation used only to supply quantity and prices."""
    return RiskCalculation(
        symbol="SOLUSDT",
        direction=Direction.LONG,
        entry_price=Decimal(entry),
        stop_price=Decimal(stop),
        take_profit=Decimal(tp),
        qty=Decimal(qty),
        position_size_usdt=Decimal("100"),
        risk_distance_pct=Decimal("0.02"),
        fee_cost_usd=Decimal("0"),
        slippage_cost_usd=Decimal("0"),
        effective_risk_usd=Decimal("5"),
        rr_ratio=Decimal("2"),
    )


def signal(
    state: SignalState,
    *,
    direction: Direction = Direction.LONG,
    signal_id: UUID | None = None,
    triggered_at: datetime | None = None,
    entry: str = "100",
    stop: str = "98",
    tp: str = "104",
) -> SimpleNamespace:
    """Build a minimal active-signal snapshot exposed by the manager property."""
    return SimpleNamespace(
        signal_id=signal_id or uuid4(),
        symbol="SOLUSDT",
        direction=direction,
        state=state,
        triggered_at=triggered_at,
        estimated_entry=Decimal(entry),
        stop_price=Decimal(stop),
        take_profit=Decimal(tp),
    )


def make_loop() -> tuple[ScanLoop, MagicMock, MagicMock, MagicMock]:
    """Build ScanLoop with all component operations mocked or async-mocked."""
    config = ScannerConfig(_env_file=None)
    candle_store = MagicMock()
    candle_store.get_closed_candles.return_value = [candle()]
    candle_store.initialize = AsyncMock()
    candle_store.run_forever = AsyncMock()
    candle_store.stop = AsyncMock()
    universe_manager = MagicMock()
    universe_manager.refresh = AsyncMock()
    universe_manager.symbols = ["SOLUSDT", "BTCUSDT"]
    ws_client = MagicMock()
    rest_client = MagicMock()
    rest_client.get_instruments_info = AsyncMock(return_value=[info()])
    regime_detector = MagicMock()
    regime_detector.classify.return_value = Regime.BULLISH
    signal_manager = MagicMock()
    signal_manager.active_signals = []
    signal_manager.on_candle = AsyncMock()
    signal_manager.mark_active = AsyncMock()
    signal_manager.mark_terminal = AsyncMock()
    signal_manager.cancel = AsyncMock()
    risk_engine = MagicMock()
    risk_engine.approve.return_value = RiskDecision(True, "approved", calculation())
    risk_engine.check_daily_limits.return_value = RiskDecision(True, "clear")
    loop = ScanLoop(
        config,
        candle_store,
        universe_manager,
        ws_client,
        rest_client,
        regime_detector,
        signal_manager,
        risk_engine,
        AsyncMock(),
    )
    loop._symbol_info_cache["SOLUSDT"] = info()
    return loop, signal_manager, risk_engine, regime_detector


@pytest.mark.asyncio
async def test_process_4h_btc_close_triggers_regime_refresh() -> None:
    """Processing the qualifying BTC candle calls the regime detector once."""
    loop, _, _, detector = make_loop()
    await loop._process_candle(candle(symbol="BTCUSDT", timeframe="240"))
    detector.classify.assert_called_once()


def test_non_btc_candle_does_not_trigger_regime_refresh() -> None:
    """Only BTC can satisfy the regime-boundary predicate."""
    loop, _, _, _ = make_loop()
    assert not loop._is_4h_btc_close(candle())


def test_non_4h_btc_candle_does_not_trigger_regime_refresh() -> None:
    """A BTC candle outside the four-hour clock boundary is ignored."""
    loop, _, _, _ = make_loop()
    assert not loop._is_4h_btc_close(candle(1, symbol="BTCUSDT", timeframe="240"))


@pytest.mark.asyncio
async def test_triggered_signal_promoted_to_active_on_next_candle() -> None:
    """Decision B promotes a prior trigger using the following candle open."""
    loop, manager, _, _ = make_loop()
    item = signal(SignalState.TRIGGERED, triggered_at=BASE_TIME)
    manager.active_signals = [item]
    await loop._promote_triggered_signals(candle(1, open_price="101"))
    manager.mark_active.assert_awaited_once_with(item.signal_id, Decimal("101"))


@pytest.mark.asyncio
async def test_risk_rejection_cancels_triggered_signal() -> None:
    """A failed risk decision cancels its newly triggered signal."""
    loop, manager, risk_engine, _ = make_loop()
    item = signal(SignalState.TRIGGERED, triggered_at=BASE_TIME)
    manager.active_signals = [item]
    risk_engine.approve.return_value = RiskDecision(False, "below minimum")
    await loop._handle_triggered(candle())
    manager.cancel.assert_awaited_once_with(item.signal_id, "below minimum")


@pytest.mark.asyncio
async def test_risk_approval_stores_calculation() -> None:
    """An approved trigger retains quantity details for later paper PnL."""
    loop, manager, _, _ = make_loop()
    item = signal(SignalState.TRIGGERED, triggered_at=BASE_TIME)
    manager.active_signals = [item]
    await loop._handle_triggered(candle())
    assert loop._risk_calculations[item.signal_id] == calculation()


@pytest.mark.asyncio
async def test_missing_symbol_info_cancels_triggered_signal() -> None:
    """A trigger without cached instrument precision fails safe before sizing."""
    loop, manager, risk_engine, _ = make_loop()
    item = signal(SignalState.TRIGGERED, triggered_at=BASE_TIME)
    manager.active_signals = [item]
    loop._symbol_info_cache.clear()
    await loop._handle_triggered(candle())
    manager.cancel.assert_awaited_once_with(
        item.signal_id, "symbol information unavailable"
    )
    risk_engine.approve.assert_not_called()


@pytest.mark.asyncio
async def test_long_tp_hit_closes_signal() -> None:
    """A long target is hit by the candle high."""
    loop, manager, _, _ = make_loop()
    item = signal(SignalState.ACTIVE)
    manager.active_signals = [item]
    loop._risk_calculations[item.signal_id] = calculation()
    await loop._check_active_signals(candle(high="104", low="99"))
    manager.mark_terminal.assert_awaited_once()
    assert manager.mark_terminal.await_args.args[1] is SignalState.TP_HIT


@pytest.mark.asyncio
async def test_long_sl_hit_closes_signal() -> None:
    """A long stop is hit by the candle low."""
    loop, manager, _, _ = make_loop()
    item = signal(SignalState.ACTIVE)
    manager.active_signals = [item]
    loop._risk_calculations[item.signal_id] = calculation()
    await loop._check_active_signals(candle(high="103", low="98"))
    assert manager.mark_terminal.await_args.args[1] is SignalState.SL_HIT


@pytest.mark.asyncio
async def test_short_tp_hit_closes_signal() -> None:
    """A short target is hit by the candle low."""
    loop, manager, _, _ = make_loop()
    item = signal(SignalState.ACTIVE, direction=Direction.SHORT, stop="102", tp="96")
    manager.active_signals = [item]
    loop._risk_calculations[item.signal_id] = calculation(tp="96", stop="102")
    await loop._check_active_signals(candle(high="101", low="96"))
    assert manager.mark_terminal.await_args.args[1] is SignalState.TP_HIT


@pytest.mark.asyncio
async def test_short_sl_hit_closes_signal() -> None:
    """A short stop is hit by the candle high."""
    loop, manager, _, _ = make_loop()
    item = signal(SignalState.ACTIVE, direction=Direction.SHORT, stop="102", tp="96")
    manager.active_signals = [item]
    loop._risk_calculations[item.signal_id] = calculation(tp="96", stop="102")
    await loop._check_active_signals(candle(high="102", low="97"))
    assert manager.mark_terminal.await_args.args[1] is SignalState.SL_HIT


@pytest.mark.asyncio
async def test_sl_wins_when_both_hit_same_candle() -> None:
    """Decision C resolves an intrabar TP/SL collision in favor of the stop."""
    loop, manager, _, _ = make_loop()
    item = signal(SignalState.ACTIVE)
    manager.active_signals = [item]
    loop._risk_calculations[item.signal_id] = calculation()
    await loop._check_active_signals(candle(high="105", low="97"))
    assert manager.mark_terminal.await_args.args[1] is SignalState.SL_HIT


@pytest.mark.parametrize(
    ("direction", "terminal", "entry", "stop", "tp", "expected"),
    [
        (Direction.LONG, SignalState.TP_HIT, "100", "98", "104", "3.7816"),
        (Direction.LONG, SignalState.SL_HIT, "100", "98", "104", "-2.2058"),
        (Direction.SHORT, SignalState.TP_HIT, "100", "102", "96", "3.7984"),
        (Direction.SHORT, SignalState.SL_HIT, "100", "102", "96", "-2.2142"),
    ],
)
def test_net_pnl_directional_outcomes(
    direction: Direction,
    terminal: SignalState,
    entry: str,
    stop: str,
    tp: str,
    expected: str,
) -> None:
    """Paper PnL subtracts two-sided exit fee and slippage for every outcome."""
    loop, _, _, _ = make_loop()
    item = signal(
        SignalState.ACTIVE, direction=direction, entry=entry, stop=stop, tp=tp
    )
    loop._risk_calculations[item.signal_id] = calculation(entry=entry, stop=stop, tp=tp)
    assert loop._net_pnl(item, terminal) == Decimal(expected)


def test_daily_session_resets_when_date_changes() -> None:
    """A new candle date creates a clean UTC daily session."""
    loop, _, _, _ = make_loop()
    loop._daily_session = DailySession(date(2026, 9, 1), trades_taken=4)
    reset = loop._get_or_reset_daily_session(date(2026, 9, 2))
    assert reset.date == date(2026, 9, 2)
    assert reset.trades_taken == 0


@pytest.mark.asyncio
async def test_loss_limit_reached_halts_session() -> None:
    """A terminal loss causes the scan loop to halt future detections."""
    loop, manager, risk_engine, _ = make_loop()
    item = signal(SignalState.ACTIVE)
    manager.active_signals = [item]
    loop._risk_calculations[item.signal_id] = calculation()
    risk_engine.check_daily_limits.return_value = RiskDecision(
        False, "Daily loss limit reached"
    )
    await loop._check_active_signals(candle(high="103", low="98"))
    assert loop.daily_session.is_halted


def test_profit_lock_reached_halts_session() -> None:
    """A profit-lock decision is retained as the current daily halt reason."""
    loop, _, risk_engine, _ = make_loop()
    risk_engine.check_daily_limits.return_value = RiskDecision(
        False, "Daily profit lock triggered"
    )
    loop._halt_session_if_needed()
    assert loop.daily_session.halt_reason == "Daily profit lock triggered"


def test_trade_limit_reached_halts_session() -> None:
    """A trade-limit decision marks the in-memory session unavailable."""
    loop, _, risk_engine, _ = make_loop()
    risk_engine.check_daily_limits.return_value = RiskDecision(
        False, "Daily trade limit reached"
    )
    loop._halt_session_if_needed()
    assert loop.daily_session.is_halted


@pytest.mark.asyncio
async def test_halted_session_skips_new_signal_detection() -> None:
    """A halted day still monitors positions but never invokes new detection."""
    loop, manager, _, _ = make_loop()
    loop.daily_session.halt("limit")
    await loop._process_candle(candle())
    manager.on_candle.assert_not_awaited()


@pytest.mark.parametrize("state", [SignalState.CANCELLED, SignalState.EXPIRED])
@pytest.mark.asyncio
async def test_non_trade_terminal_states_do_not_increment_trades(
    state: SignalState,
) -> None:
    """Cancelled and expired snapshots are excluded from active-outcome monitoring."""
    loop, manager, _, _ = make_loop()
    manager.active_signals = [signal(state)]
    await loop._check_active_signals(candle(high="105", low="95"))
    assert loop.daily_session.trades_taken == 0


def test_regime_undefined_on_refresh_failure() -> None:
    """A detector exception degrades the cache to the no-trade regime."""
    loop, _, _, detector = make_loop()
    detector.classify.side_effect = RuntimeError("unavailable")
    loop._refresh_regime()
    assert loop._regime is Regime.UNDEFINED


@pytest.mark.asyncio
async def test_shutdown_sets_stop_flag() -> None:
    """Shutdown asks the long-running orchestration loop to exit."""
    loop, _, _, _ = make_loop()
    await loop.shutdown()
    assert loop._stop_requested


@pytest.mark.asyncio
async def test_daily_pnl_accumulates_across_multiple_trades() -> None:
    """Sequential terminal outcomes accumulate PnL within one UTC session."""
    loop, manager, _, _ = make_loop()
    first = signal(SignalState.ACTIVE, signal_id=uuid4())
    second = signal(SignalState.ACTIVE, signal_id=uuid4())
    manager.active_signals = [first]
    loop._risk_calculations[first.signal_id] = calculation()
    await loop._check_active_signals(candle(high="104", low="99"))
    first_pnl = loop.daily_session.realized_pnl
    manager.active_signals = [second]
    loop._risk_calculations[second.signal_id] = calculation()
    await loop._check_active_signals(candle(high="104", low="99"))
    assert loop.daily_session.realized_pnl == first_pnl * Decimal(2)


@pytest.mark.asyncio
async def test_only_active_signals_monitored_for_tp_sl() -> None:
    """WATCHING and TRIGGERED signals never receive terminal TP/SL outcomes."""
    loop, manager, _, _ = make_loop()
    manager.active_signals = [
        signal(SignalState.WATCHING),
        signal(SignalState.TRIGGERED),
    ]
    await loop._check_active_signals(candle(high="105", low="95"))
    manager.mark_terminal.assert_not_awaited()


@pytest.mark.asyncio
async def test_active_signal_without_risk_calculation_is_cancelled() -> None:
    """A corrupted active snapshot cannot silently produce paper-trading PnL."""
    loop, manager, _, _ = make_loop()
    item = signal(SignalState.ACTIVE)
    manager.active_signals = [item]
    await loop._check_active_signals(candle(high="105", low="95"))
    manager.mark_terminal.assert_awaited_once_with(
        item.signal_id,
        SignalState.CANCELLED,
        "missing approved risk calculation",
    )
    assert loop.daily_session.trades_taken == 0


@pytest.mark.asyncio
async def test_run_initializes_candles_metadata_and_regime() -> None:
    """Startup refreshes universe and metadata before opening the stream task."""
    loop, _, _, detector = make_loop()
    await loop.run()
    assert loop._candle_store.initialize.await_count == 2
    loop._rest_client.get_instruments_info.assert_awaited_once()
    detector.classify.assert_called_once()
