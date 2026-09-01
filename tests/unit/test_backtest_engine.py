"""Tests for the look-ahead-safe historical backtest engine."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from structlog.testing import capture_logs

from scanner.backtest.backtest_engine import (
    BacktestEngine,
    TradeRecord,
    _BacktestBuffer,
    _BacktestCandleStore,
    _null_session_factory,
    _NullAsyncSession,
)
from scanner.config import ScannerConfig
from scanner.market_data.models import SymbolInfo
from scanner.models import Candle, Direction, Regime, SignalState
from scanner.risk import DailySession, RiskCalculation, RiskEngine
from scanner.strategy.setup_detector import SetupContext
from scanner.strategy.signal_manager import ActiveSignal, SignalManager, _CreateEvent


def candle_at(hour: int) -> Candle:
    """Create one deterministic closed one-hour candle at ``hour``."""
    price = Decimal(100 + hour)
    return Candle(
        symbol="ETHUSDT",
        timeframe="60",
        open_time=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=hour),
        open=price,
        high=price + Decimal(1),
        low=price - Decimal(1),
        close=price,
        volume=Decimal(1000),
        turnover=Decimal(100000),
        is_closed=True,
    )


def test_backtest_buffer_advance_appends_oldest_first() -> None:
    """Revealed candles retain the order in which time advances."""
    buffer = _BacktestBuffer()
    first, second = candle_at(0), candle_at(1)

    buffer.advance(first)
    buffer.advance(second)

    assert buffer.get(10) == [first, second]


def test_backtest_buffer_get_returns_n_newest() -> None:
    """A bounded read contains only already revealed recent candles."""
    buffer = _BacktestBuffer()
    candles = [candle_at(hour) for hour in range(4)]
    for candle in candles:
        buffer.advance(candle)

    assert buffer.get(2) == candles[-2:]
    assert buffer.get(0) == []


def test_backtest_buffer_max_size_prunes_oldest() -> None:
    """Capacity pruning cannot expose discarded or future candles."""
    buffer = _BacktestBuffer(max_size=2)
    candles = [candle_at(hour) for hour in range(3)]
    for candle in candles:
        buffer.advance(candle)

    assert len(buffer) == 2
    assert buffer.get(10) == candles[1:]


def test_backtest_buffer_advance_cannot_go_back() -> None:
    """A later reveal makes earlier and duplicate timestamps invalid."""
    buffer = _BacktestBuffer()
    buffer.advance(candle_at(2))

    with pytest.raises(ValueError, match="strictly increasing"):
        buffer.advance(candle_at(1))
    with pytest.raises(ValueError, match="strictly increasing"):
        buffer.advance(candle_at(2))


def test_future_candle_not_in_buffer_at_current_step() -> None:
    """At step i, the next candle remains invisible until explicitly advanced."""
    buffer = _BacktestBuffer()
    current, future = candle_at(4), candle_at(5)

    buffer.advance(current)

    assert buffer.get(200) == [current]
    assert future not in buffer.get(200)


def info() -> SymbolInfo:
    """Build deterministic exchange precision metadata for replay tests."""
    return SymbolInfo(
        symbol="ETHUSDT",
        base_coin="ETH",
        quote_coin="USDT",
        status="Trading",
        tick_size=Decimal("0.01"),
        lot_size=Decimal("0.01"),
        min_order_qty=Decimal("0.01"),
        max_leverage=50.0,
        contract_type="LinearPerpetual",
    )


def engine() -> BacktestEngine:
    """Build an isolated engine with no environment-derived settings."""
    return BacktestEngine(ScannerConfig(_env_file=None), info())


def trade(
    day: int,
    net_pnl: str,
    outcome: SignalState = SignalState.TP_HIT,
    entry: str = "100",
    stop: str = "98",
) -> TradeRecord:
    """Build one completed long trade with controllable Decimal net PnL."""
    entry_price = Decimal(entry)
    stop_price = Decimal(stop)
    net = Decimal(net_pnl)
    opened = datetime(2026, 1, day, tzinfo=UTC)
    return TradeRecord(
        signal_id=uuid4(),
        symbol="ETHUSDT",
        direction=Direction.LONG,
        regime_at_detection=Regime.BULLISH,
        score=80,
        entry_candle_time=opened,
        entry_price=entry_price,
        stop_price=stop_price,
        take_profit=Decimal("104"),
        exit_candle_time=opened + timedelta(hours=1),
        exit_price=Decimal("104") if outcome is SignalState.TP_HIT else stop_price,
        outcome=outcome,
        qty=Decimal("1"),
        rr_ratio=Decimal("2"),
        gross_pnl=net,
        fee_cost=Decimal("0"),
        slippage_cost=Decimal("0"),
        net_pnl=net,
    )


def calculation() -> RiskCalculation:
    """Build a viable long risk calculation for entry and exit tests."""
    return RiskCalculation(
        symbol="ETHUSDT",
        direction=Direction.LONG,
        entry_price=Decimal("100"),
        stop_price=Decimal("98"),
        take_profit=Decimal("104"),
        qty=Decimal("1"),
        position_size_usdt=Decimal("100"),
        risk_distance_pct=Decimal("0.02"),
        fee_cost_usd=Decimal("0"),
        slippage_cost_usd=Decimal("0"),
        effective_risk_usd=Decimal("5"),
        rr_ratio=Decimal("2"),
    )


def context() -> SetupContext:
    """Build the required immutable context for a synthetic active signal."""
    candle = candle_at(0)
    return SetupContext(
        symbol="ETHUSDT",
        direction=Direction.LONG,
        detected_at=candle.open_time,
        change_24h_pct=Decimal("-8"),
        high_24h=Decimal("105"),
        low_24h=Decimal("95"),
        rsi_14=20.0,
        ema_7=Decimal("101"),
        ema_extension_pct=Decimal("3"),
        atr_14=Decimal("1"),
        trigger_candle=candle,
    )


class FakeSignalManager:
    """Small in-memory signal manager double for orchestration boundary tests."""

    def __init__(self, signals: list[ActiveSignal]) -> None:
        """Retain the supplied signal snapshot and all attempted transitions."""
        self.active_signals = signals
        self.activated: list[tuple[object, Decimal]] = []
        self.terminal: list[tuple[object, SignalState]] = []
        self.cancelled: list[object] = []

    async def mark_active(self, signal_id: object, entry: Decimal) -> None:
        """Record a next-open activation request."""
        self.activated.append((signal_id, entry))

    async def mark_terminal(
        self, signal_id: object, state: SignalState, reason: str
    ) -> None:
        """Record a completed trade transition."""
        del reason
        self.terminal.append((signal_id, state))

    async def cancel(self, signal_id: object, reason: str) -> None:
        """Record a safe cancellation request."""
        del reason
        self.cancelled.append(signal_id)


def test_btc_buffer_aligned_to_1h_candle_time() -> None:
    """BTC candles are revealed only once their close_time (open_time+4H) has passed.

    At target=05:00:
    - btc[0] open=00:00, close=04:00 — 04:00 <= 05:00 → included
    - btc[1] open=04:00, close=08:00 — 08:00 > 05:00  → still forming, excluded
    """
    buffer = _BacktestBuffer()
    pointer = [0]
    btc = [
        candle_at(0),
        candle_at(4),
        candle_at(8),
    ]
    target = candle_at(5)

    BacktestEngine._advance_btc_to(buffer, btc, target.open_time, pointer)

    assert [item.open_time for item in buffer.get(10)] == [
        btc[0].open_time,
    ]
    assert pointer == [1]


def test_forming_btc_candle_is_not_revealed_to_regime_buffer() -> None:
    """BTC regime input excludes a forming candle even once its time is reached."""
    buffer = _BacktestBuffer()
    pointer = [0]
    forming = Candle(
        symbol="BTCUSDT",
        timeframe="240",
        open_time=candle_at(0).open_time,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("1"),
        turnover=Decimal("100"),
        is_closed=False,
    )

    BacktestEngine._advance_btc_to(buffer, [forming], candle_at(0).open_time, pointer)

    assert buffer.get(200) == []
    # Pointer stays at 0: the forming candle's close_time (open_time + 4H) has not
    # yet passed, so it is held for re-examination on the next advance call.
    assert pointer == [0]


def test_backtest_store_only_returns_revealed_candles() -> None:
    """The adapter cannot bypass its buffer to obtain future history."""
    buffer = _BacktestBuffer()
    revealed, future = candle_at(0), candle_at(1)
    buffer.advance(revealed)

    assert _BacktestCandleStore(buffer).get_closed_candles("ETHUSDT", "60", 200) == [
        revealed
    ]
    assert future not in buffer.get(200)


async def test_null_async_session_absorbs_signal_writer_operations() -> None:
    """The backtest persistence session is an async no-op without a real DB."""
    async with _null_session_factory() as session:
        session.add(object())
        await session.flush()
        await session.execute(object())
        await session.commit()
        await session.rollback()


def test_null_async_session_add_is_synchronous() -> None:
    """SQLAlchemy-style add returns None immediately rather than an awaitable."""
    assert _NullAsyncSession().add(object()) is None


async def test_null_session_factory_suppresses_signal_persistence_writes() -> None:
    """SignalManager persists in memory without a DB failure log in backtests."""
    manager = SignalManager(
        _BacktestCandleStore(_BacktestBuffer()),
        _null_session_factory,  # type: ignore[arg-type]
        ScannerConfig(_env_file=None),
    )
    signal = ActiveSignal(
        signal_id=uuid4(),
        symbol="ETHUSDT",
        direction=Direction.LONG,
        state=SignalState.WATCHING,
        detected_at=candle_at(0).open_time,
        setup_context=context(),
    )

    with capture_logs() as logs:
        await manager._persist([_CreateEvent(signal)])

    assert not any(log["event"] == "signal_persistence_failed" for log in logs)


def test_daily_session_resets_at_midnight() -> None:
    """A new UTC date clears halted state, PnL, and completed-trade count."""
    previous = DailySession(
        date=date(2026, 1, 1),
        trades_taken=5,
        realized_pnl=Decimal("-25"),
        is_halted=True,
        halt_reason="Daily loss limit reached",
    )

    reset = BacktestEngine._reset_session_if_needed(previous, date(2026, 1, 2))

    assert reset == DailySession(date=date(2026, 1, 2))


def test_daily_session_is_retained_within_same_utc_day() -> None:
    """No state resets during different hours of the same UTC date."""
    session = DailySession(date=date(2026, 1, 1), trades_taken=2)

    assert BacktestEngine._reset_session_if_needed(session, date(2026, 1, 1)) is session


def test_four_hour_boundary_is_detected() -> None:
    """UTC hour zero modulo four refreshes the BTC regime."""
    assert BacktestEngine._is_4h_boundary(candle_at(4).open_time)


def test_non_four_hour_boundary_is_not_detected() -> None:
    """Intervening one-hour steps do not reclassify BTC prematurely."""
    assert not BacktestEngine._is_4h_boundary(candle_at(5).open_time)


async def test_warmup_candles_produce_no_signals() -> None:
    """A warmup longer than all supplied candles skips every detection cycle."""
    candles = [candle_at(hour) for hour in range(3)]

    result = await engine().run("ETHUSDT", candles, [], 3)

    assert result.total_signals_detected == 0


def test_zero_trades_safe_metrics() -> None:
    """Zero completed trades produce only zero-valued Decimal performance metrics."""
    metrics = BacktestEngine._compute_metrics([], [])

    assert metrics["win_rate"] == Decimal(0)
    assert metrics["profit_factor"] == Decimal(0)
    assert metrics["expectancy"] == Decimal(0)


def test_profit_factor_zero_when_no_losing_trades() -> None:
    """The no-loss edge case returns zero rather than dividing by zero."""
    metrics = BacktestEngine._compute_metrics([trade(1, "2")], [])

    assert metrics["profit_factor"] == Decimal(0)


def test_win_rate_correct_for_known_sequence() -> None:
    """Two positive trades and one negative trade produce a 2/3 win rate."""
    metrics = BacktestEngine._compute_metrics(
        [trade(1, "2"), trade(2, "3"), trade(3, "-1", SignalState.SL_HIT)], []
    )

    assert metrics["win_rate"] == Decimal(2) / Decimal(3)
    assert metrics["winning_trades"] == 2
    assert metrics["losing_trades"] == 1


def test_expectancy_has_correct_sign() -> None:
    """A net-losing series has a negative arithmetic expectancy."""
    metrics = BacktestEngine._compute_metrics(
        [trade(1, "1"), trade(2, "-3", SignalState.SL_HIT)], []
    )

    assert metrics["expectancy"] == Decimal("-1")


def test_max_drawdown_nonnegative() -> None:
    """Peak-to-trough loss is represented as a positive magnitude."""
    curve = [
        (candle_at(0).open_time, Decimal("5")),
        (candle_at(1).open_time, Decimal("2")),
    ]

    assert BacktestEngine._max_drawdown(curve) == Decimal("3")


def test_max_drawdown_zero_with_all_winners() -> None:
    """A monotonic equity curve has no peak-to-trough decline."""
    curve = [
        (candle_at(0).open_time, Decimal("2")),
        (candle_at(1).open_time, Decimal("5")),
    ]

    assert BacktestEngine._max_drawdown(curve) == Decimal(0)


def test_sharpe_zero_when_single_trading_day() -> None:
    """Annualized Sharpe is undefined and safely zero for one UTC day."""
    assert BacktestEngine._sharpe_ratio([trade(1, "2"), trade(1, "3")]) == Decimal(0)


def test_sharpe_positive_with_varying_consistent_wins() -> None:
    """Positive PnL on two UTC days yields a positive Decimal Sharpe ratio."""
    sharpe = BacktestEngine._sharpe_ratio([trade(1, "1"), trade(2, "2")])

    assert sharpe > Decimal(0)
    assert isinstance(sharpe, Decimal)


def test_equity_curve_is_immutable_tuple() -> None:
    """The public result cannot expose a mutable equity curve."""
    result = engine()._result_from_records(
        "ETHUSDT",
        [candle_at(0)],
        0,
        [trade(1, "1")],
        [(candle_at(0).open_time, Decimal("1"))],
    )

    assert isinstance(result.equity_curve, tuple)


def test_trade_records_are_immutable_frozen() -> None:
    """Completed record fields cannot be reassigned after collection."""
    record = trade(1, "1")

    with pytest.raises(Exception):
        record.net_pnl = Decimal("2")  # type: ignore[misc]


async def test_run_returns_empty_result_on_exception() -> None:
    """A malformed negative warmup is contained by the public never-raise boundary."""
    result = await engine().run("ETHUSDT", [candle_at(0)], [], -1)

    assert result.total_trades == 0
    assert result.trades == ()


def test_net_pnl_matches_gross_minus_fees_minus_slippage() -> None:
    """Trade records preserve the required Decimal net-PnL identity."""
    signal = ActiveSignal(
        signal_id=uuid4(),
        symbol="ETHUSDT",
        direction=Direction.LONG,
        state=SignalState.ACTIVE,
        detected_at=candle_at(0).open_time,
        setup_context=context(),
        score=80,
        estimated_entry=Decimal("100"),
        triggered_at=candle_at(0).open_time,
    )
    record = engine()._record_trade(
        signal, calculation(), Regime.BULLISH, candle_at(1), SignalState.TP_HIT
    )

    assert record.net_pnl == record.gross_pnl - record.fee_cost - record.slippage_cost


def test_all_metric_values_use_decimal_arithmetic() -> None:
    """Metrics return Decimal values rather than binary floats."""
    metrics = BacktestEngine._compute_metrics([trade(1, "2"), trade(2, "-1")], [])

    assert all(
        isinstance(value, Decimal)
        for value in metrics.values()
        if not isinstance(value, int)
    )


async def test_entry_price_is_next_candle_open_not_trigger_close() -> None:
    """A prior trigger is promoted using the following candle open price."""
    trigger = candle_at(0)
    next_candle = candle_at(1)
    signal = ActiveSignal(
        signal_id=uuid4(),
        symbol="ETHUSDT",
        direction=Direction.LONG,
        state=SignalState.TRIGGERED,
        detected_at=trigger.open_time,
        setup_context=context(),
        estimated_entry=trigger.close,
        triggered_at=trigger.open_time,
    )
    manager = FakeSignalManager([signal])

    await BacktestEngine._promote_triggered(
        manager,  # type: ignore[arg-type]
        {signal.signal_id: calculation()},
        next_candle,
    )

    assert manager.activated == [(signal.signal_id, next_candle.open)]
    assert next_candle.open != trigger.close


async def test_sl_wins_when_both_hit_same_candle() -> None:
    """A candle crossing both levels records the conservative stop-loss outcome."""
    signal = ActiveSignal(
        signal_id=uuid4(),
        symbol="ETHUSDT",
        direction=Direction.LONG,
        state=SignalState.ACTIVE,
        detected_at=candle_at(0).open_time,
        setup_context=context(),
        score=80,
        estimated_entry=Decimal("100"),
        triggered_at=candle_at(0).open_time,
    )
    both = Candle(
        symbol="ETHUSDT",
        timeframe="60",
        open_time=candle_at(1).open_time,
        open=Decimal("100"),
        high=Decimal("105"),
        low=Decimal("97"),
        close=Decimal("100"),
        volume=Decimal("1"),
        turnover=Decimal("100"),
        is_closed=True,
    )
    manager = FakeSignalManager([signal])
    records: list[TradeRecord] = []

    await engine()._check_active_signals(
        manager,  # type: ignore[arg-type]
        {signal.signal_id: calculation()},
        {signal.signal_id: Regime.BULLISH},
        both,
        DailySession(date=both.open_time.date()),
        records,
        [],
    )

    assert records[0].outcome is SignalState.SL_HIT
    assert manager.terminal == [(signal.signal_id, SignalState.SL_HIT)]


async def test_long_tp_hit_records_take_profit() -> None:
    """A long high at target produces a TP record using the rounded target price."""
    signal = ActiveSignal(
        signal_id=uuid4(),
        symbol="ETHUSDT",
        direction=Direction.LONG,
        state=SignalState.ACTIVE,
        detected_at=candle_at(0).open_time,
        setup_context=context(),
        score=80,
        estimated_entry=Decimal("100"),
        triggered_at=candle_at(0).open_time,
    )
    hit = Candle(
        symbol="ETHUSDT",
        timeframe="60",
        open_time=candle_at(1).open_time,
        open=Decimal("100"),
        high=Decimal("104"),
        low=Decimal("99"),
        close=Decimal("103"),
        volume=Decimal("1"),
        turnover=Decimal("100"),
        is_closed=True,
    )
    records: list[TradeRecord] = []

    await engine()._check_active_signals(
        FakeSignalManager([signal]),  # type: ignore[arg-type]
        {signal.signal_id: calculation()},
        {signal.signal_id: Regime.BULLISH},
        hit,
        DailySession(date=hit.open_time.date()),
        records,
        [],
    )

    assert records[0].outcome is SignalState.TP_HIT
    assert records[0].exit_price == Decimal("104")


async def test_long_sl_hit_records_stop_loss() -> None:
    """A long low at stop produces an SL record using the rounded stop price."""
    signal = ActiveSignal(
        signal_id=uuid4(),
        symbol="ETHUSDT",
        direction=Direction.LONG,
        state=SignalState.ACTIVE,
        detected_at=candle_at(0).open_time,
        setup_context=context(),
        score=80,
        estimated_entry=Decimal("100"),
        triggered_at=candle_at(0).open_time,
    )
    hit = Candle(
        symbol="ETHUSDT",
        timeframe="60",
        open_time=candle_at(1).open_time,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("98"),
        close=Decimal("99"),
        volume=Decimal("1"),
        turnover=Decimal("100"),
        is_closed=True,
    )
    records: list[TradeRecord] = []

    await engine()._check_active_signals(
        FakeSignalManager([signal]),  # type: ignore[arg-type]
        {signal.signal_id: calculation()},
        {signal.signal_id: Regime.BULLISH},
        hit,
        DailySession(date=hit.open_time.date()),
        records,
        [],
    )

    assert records[0].outcome is SignalState.SL_HIT
    assert records[0].exit_price == Decimal("98")


async def test_empty_run_returns_safe_zero_result() -> None:
    """An empty input is a valid zero-trade replay rather than an exception."""
    result = await engine().run("ETHUSDT", [], [])

    assert result.total_candles_processed == 0
    assert result.total_net_pnl == Decimal(0)


async def test_forming_altcoin_candle_is_not_used_for_replay() -> None:
    """A forming 1H input does not become visible to strategy calculations."""
    forming = Candle(
        symbol="ETHUSDT",
        timeframe="60",
        open_time=candle_at(0).open_time,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("1"),
        turnover=Decimal("100"),
        is_closed=False,
    )

    result = await engine().run("ETHUSDT", [forming], [], min_warmup_candles=0)

    assert result.total_signals_detected == 0
    assert result.total_trades == 0


async def test_backtest_result_start_end_match_candle_range() -> None:
    """A run retains the first and last supplied 1H timestamps in its result."""
    candles = [candle_at(0), candle_at(1)]
    result = await engine().run("ETHUSDT", candles, [], min_warmup_candles=2)

    assert result.start_time == candles[0].open_time
    assert result.end_time == candles[-1].open_time


async def test_no_rest_client_is_used_during_run() -> None:
    """Replay accepts only supplied data and exposes no REST-client dependency."""
    result = await engine().run("ETHUSDT", [candle_at(0)], [], min_warmup_candles=1)

    assert result.total_candles_processed == 1
    assert not hasattr(engine(), "_rest_client")


async def test_cancelled_signal_not_counted_as_trade() -> None:
    """A trigger without risk approval is cancelled and never becomes a trade."""
    signal = ActiveSignal(
        signal_id=uuid4(),
        symbol="ETHUSDT",
        direction=Direction.LONG,
        state=SignalState.TRIGGERED,
        detected_at=candle_at(0).open_time,
        setup_context=context(),
        triggered_at=candle_at(0).open_time,
    )
    manager = FakeSignalManager([signal])

    count = await engine()._handle_triggered(
        manager,  # type: ignore[arg-type]
        RiskEngine(ScannerConfig(_env_file=None)),
        {},
        {},
        candle_at(0),
        DailySession(date=candle_at(0).open_time.date()),
        Regime.BULLISH,
    )

    assert count == 0
    assert manager.cancelled == [signal.signal_id]


def test_expired_signal_not_counted_as_trade() -> None:
    """A pre-entry expiration has no completed-trade record or PnL effect."""
    result = engine()._result_from_records("ETHUSDT", [candle_at(0)], 0, [], [])

    assert result.total_trades == 0
    assert result.total_net_pnl == Decimal(0)


def test_daily_halt_blocks_risk_approval() -> None:
    """The approved risk module rejects new candidates once the day is halted."""
    session = DailySession(date=date(2026, 1, 1), is_halted=True, halt_reason="halted")
    decision = RiskEngine(ScannerConfig(_env_file=None)).approve(
        Decimal("100"), Decimal("98"), Decimal("104"), Direction.LONG, info(), session
    )

    assert not decision.approved
    assert decision.reason == "halted"


async def test_total_signals_detected_only_counts_risk_approved() -> None:
    """A triggered signal missing pricing data is not included in the count."""
    signal = ActiveSignal(
        signal_id=uuid4(),
        symbol="ETHUSDT",
        direction=Direction.LONG,
        state=SignalState.TRIGGERED,
        detected_at=candle_at(0).open_time,
        setup_context=context(),
        triggered_at=candle_at(0).open_time,
    )
    manager = FakeSignalManager([signal])
    count = await engine()._handle_triggered(
        manager,  # type: ignore[arg-type]
        RiskEngine(ScannerConfig(_env_file=None)),
        {},
        {},
        candle_at(0),
        DailySession(date=candle_at(0).open_time.date()),
        Regime.BULLISH,
    )

    assert count == 0
