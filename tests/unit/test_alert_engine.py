"""AsyncMock-only tests for failure-isolated alert delivery."""

import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from structlog.testing import capture_logs

from scanner.alerting import AlertEngine
from scanner.config import ScannerConfig
from scanner.models import Direction, Regime, SignalState
from scanner.risk import DailySession, RiskCalculation


def configured(**overrides: str) -> AlertEngine:
    """Build an engine with credential strings supplied by each test."""
    values = {
        "telegram_bot_token": "token",
        "telegram_chat_id": "chat",
        "discord_webhook_url": "https://discord.example/webhook",
    }
    values.update(overrides)
    return AlertEngine(ScannerConfig(_env_file=None, **values))


def signal() -> SimpleNamespace:
    """Build a triggered signal snapshot sufficient for alert formatting."""
    return SimpleNamespace(
        symbol="SOLUSDT",
        direction=Direction.SHORT,
        score=85,
        estimated_entry=Decimal("100"),
        stop_price=Decimal("102"),
        take_profit=Decimal("96"),
    )


def calculation() -> RiskCalculation:
    """Build one approved risk calculation used only for display fields."""
    return RiskCalculation(
        symbol="SOLUSDT",
        direction=Direction.SHORT,
        entry_price=Decimal("100"),
        stop_price=Decimal("102"),
        take_profit=Decimal("96"),
        qty=Decimal("2.5"),
        position_size_usdt=Decimal("250"),
        risk_distance_pct=Decimal("0.02"),
        fee_cost_usd=Decimal("0.2695"),
        slippage_cost_usd=Decimal("0.245"),
        effective_risk_usd=Decimal("5.5145"),
        rr_ratio=Decimal("2"),
    )


def halted_session() -> DailySession:
    """Build a daily session snapshot after an immutable risk halt."""
    return DailySession(
        date=date(2026, 9, 1),
        trades_taken=5,
        realized_pnl=Decimal("-25"),
        is_halted=True,
        halt_reason="Daily loss limit reached",
    )


@pytest.mark.asyncio
async def test_telegram_disabled_when_token_empty() -> None:
    """Telegram is not constructed if its bot credential is absent."""
    engine = configured(telegram_bot_token="")
    assert engine._telegram is None


@pytest.mark.asyncio
async def test_telegram_disabled_when_chat_id_empty() -> None:
    """Telegram requires both a token and a destination chat ID."""
    engine = configured(telegram_chat_id="")
    assert engine._telegram is None


@pytest.mark.asyncio
async def test_discord_disabled_when_webhook_empty() -> None:
    """Discord is not constructed without a webhook URL."""
    engine = configured(discord_webhook_url="")
    assert engine._discord is None


@pytest.mark.asyncio
async def test_send_triggered_returns_silently_when_all_disabled() -> None:
    """Unconfigured channels make alerting a silent no-op."""
    engine = configured(
        telegram_bot_token="", telegram_chat_id="", discord_webhook_url=""
    )
    await engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH)


@pytest.mark.asyncio
async def test_network_timeout_in_telegram_does_not_raise() -> None:
    """Telegram timeouts are swallowed by the transport boundary."""
    engine = configured(discord_webhook_url="")
    assert engine._telegram is not None
    engine._telegram._post = AsyncMock(side_effect=asyncio.TimeoutError())
    await engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH)


@pytest.mark.asyncio
async def test_network_timeout_in_discord_does_not_raise() -> None:
    """Discord timeouts are swallowed by the transport boundary."""
    engine = configured(telegram_bot_token="", telegram_chat_id="")
    assert engine._discord is not None
    engine._discord._post = AsyncMock(side_effect=asyncio.TimeoutError())
    await engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH)


@pytest.mark.asyncio
async def test_generic_exception_in_telegram_does_not_raise() -> None:
    """Unexpected Telegram errors remain observability-only failures."""
    engine = configured(discord_webhook_url="")
    assert engine._telegram is not None
    engine._telegram._post = AsyncMock(side_effect=RuntimeError("offline"))
    await engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH)


@pytest.mark.asyncio
async def test_generic_exception_in_discord_does_not_raise() -> None:
    """Unexpected Discord errors remain observability-only failures."""
    engine = configured(telegram_bot_token="", telegram_chat_id="")
    assert engine._discord is not None
    engine._discord._post = AsyncMock(side_effect=RuntimeError("offline"))
    await engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH)


@pytest.mark.asyncio
async def test_4xx_response_disables_telegram_channel() -> None:
    """A permanent Telegram credential failure disables future attempts."""
    engine = configured(discord_webhook_url="")
    assert engine._telegram is not None
    post = AsyncMock(return_value=401)
    engine._telegram._post = post
    with capture_logs() as logs:
        await engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH)
        await engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH)
    assert post.await_count == 1
    assert any(entry["event"] == "alert_4xx_disabling" for entry in logs)


@pytest.mark.asyncio
async def test_4xx_response_disables_discord_channel() -> None:
    """A permanent Discord credential failure also prevents future retries."""
    engine = configured(telegram_bot_token="", telegram_chat_id="")
    assert engine._discord is not None
    post = AsyncMock(return_value=404)
    engine._discord._post = post
    await engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH)
    await engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH)
    assert post.await_count == 1


@pytest.mark.asyncio
async def test_5xx_response_triggers_one_retry_telegram() -> None:
    """One server failure causes exactly one non-blocking retry."""
    engine = configured(discord_webhook_url="")
    assert engine._telegram is not None
    post = AsyncMock(side_effect=[503, 200])
    engine._telegram._post = post
    with patch("scanner.alerting.alert_engine.asyncio.sleep", new=AsyncMock()) as sleep:
        await engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH)
    assert post.await_count == 2
    sleep.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_5xx_retry_still_fails_swallowed_silently() -> None:
    """The bounded retry cannot leak a final server failure to callers."""
    engine = configured(discord_webhook_url="")
    assert engine._telegram is not None
    engine._telegram._post = AsyncMock(side_effect=[503, 503])
    with patch("scanner.alerting.alert_engine.asyncio.sleep", new=AsyncMock()):
        await engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH)


@pytest.mark.asyncio
async def test_triggered_message_contains_symbol() -> None:
    """Triggered messages identify the tradable market symbol."""
    engine = configured(discord_webhook_url="")
    assert engine._telegram is not None
    post = AsyncMock(return_value=200)
    engine._telegram._post = post
    await engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH)
    assert "SOLUSDT" in post.await_args.args[0]["text"]


@pytest.mark.asyncio
async def test_triggered_message_contains_direction() -> None:
    """Triggered messages include direction and the supplied BTC regime."""
    engine = configured(discord_webhook_url="")
    assert engine._telegram is not None
    post = AsyncMock(return_value=200)
    engine._telegram._post = post
    await engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH)
    assert "SHORT (BEARISH)" in post.await_args.args[0]["text"]


@pytest.mark.asyncio
async def test_triggered_message_contains_entry_stop_tp() -> None:
    """Triggered messages expose all three actionable price levels."""
    engine = configured(discord_webhook_url="")
    assert engine._telegram is not None
    post = AsyncMock(return_value=200)
    engine._telegram._post = post
    await engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH)
    text = post.await_args.args[0]["text"]
    assert "~100.0000" in text and "102.0000" in text and "96.0000" in text


@pytest.mark.asyncio
async def test_triggered_message_contains_rr_and_score() -> None:
    """Score and post-rounding reward-to-risk are rendered in their templates."""
    engine = configured(discord_webhook_url="")
    assert engine._telegram is not None
    post = AsyncMock(return_value=200)
    engine._telegram._post = post
    await engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH)
    text = post.await_args.args[0]["text"]
    assert "2.00:1" in text and "85/100" in text


@pytest.mark.asyncio
async def test_opened_message_contains_confirmed_entry() -> None:
    """Opening message shows the later confirmed, not estimated, entry."""
    engine = configured(discord_webhook_url="")
    assert engine._telegram is not None
    post = AsyncMock(return_value=200)
    engine._telegram._post = post
    await engine.send_position_opened(signal(), Decimal("100.25"), calculation())
    assert "100.2500" in post.await_args.args[0]["text"]


@pytest.mark.asyncio
async def test_tp_hit_uses_correct_emoji_and_pnl() -> None:
    """Profitable closure uses the TP emoji and explicit positive sign."""
    engine = configured(discord_webhook_url="")
    assert engine._telegram is not None
    post = AsyncMock(return_value=200)
    engine._telegram._post = post
    await engine.send_position_closed(
        signal(), SignalState.TP_HIT, Decimal("1.2"), Decimal("5")
    )
    text = post.await_args.args[0]["text"]
    assert "💰" in text and "+$1.2000" in text


@pytest.mark.asyncio
async def test_sl_hit_uses_correct_emoji_and_pnl() -> None:
    """Loss closure uses the SL emoji and preserves its signed numeric value."""
    engine = configured(discord_webhook_url="")
    assert engine._telegram is not None
    post = AsyncMock(return_value=200)
    engine._telegram._post = post
    await engine.send_position_closed(
        signal(), SignalState.SL_HIT, Decimal("-1.2"), Decimal("3")
    )
    text = post.await_args.args[0]["text"]
    assert "🛑" in text and "$-1.2000" in text


@pytest.mark.asyncio
async def test_daily_halted_contains_reason_and_trades() -> None:
    """Daily halt alerts retain the exact operator-facing reason and count."""
    engine = configured(discord_webhook_url="")
    assert engine._telegram is not None
    post = AsyncMock(return_value=200)
    engine._telegram._post = post
    await engine.send_daily_halted(halted_session())
    text = post.await_args.args[0]["text"]
    assert "Daily loss limit reached" in text and "Trades:      5" in text


@pytest.mark.asyncio
async def test_both_channels_called_on_triggered_event() -> None:
    """Configured channels each receive the same triggered notification."""
    engine = configured()
    assert engine._telegram is not None and engine._discord is not None
    telegram_post = AsyncMock(return_value=200)
    discord_post = AsyncMock(return_value=200)
    engine._telegram._post = telegram_post
    engine._discord._post = discord_post
    await engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH)
    telegram_post.assert_awaited_once()
    discord_post.assert_awaited_once()


@pytest.mark.asyncio
async def test_both_channels_send_concurrently() -> None:
    """Mutually waiting mocks prove send uses concurrent rather than serial work."""
    engine = configured()
    assert engine._telegram is not None and engine._discord is not None
    telegram_started = asyncio.Event()
    discord_started = asyncio.Event()

    async def telegram_post(_: object) -> int:
        telegram_started.set()
        await discord_started.wait()
        return 200

    async def discord_post(_: object) -> int:
        discord_started.set()
        await telegram_started.wait()
        return 200

    engine._telegram._post = AsyncMock(side_effect=telegram_post)
    engine._discord._post = AsyncMock(side_effect=discord_post)
    await asyncio.wait_for(
        engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH), 0.2
    )


@pytest.mark.asyncio
async def test_telegram_exception_does_not_block_discord_send() -> None:
    """Channel-local Telegram failure does not short-circuit Discord delivery."""
    engine = configured()
    assert engine._telegram is not None and engine._discord is not None
    engine._telegram._post = AsyncMock(side_effect=RuntimeError("bad token"))
    discord_post = AsyncMock(return_value=200)
    engine._discord._post = discord_post
    await engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH)
    discord_post.assert_awaited_once()


@pytest.mark.asyncio
async def test_discord_exception_does_not_block_telegram_send() -> None:
    """Channel-local Discord failure does not short-circuit Telegram delivery."""
    engine = configured()
    assert engine._telegram is not None and engine._discord is not None
    telegram_post = AsyncMock(return_value=200)
    engine._telegram._post = telegram_post
    engine._discord._post = AsyncMock(side_effect=RuntimeError("bad webhook"))
    await engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH)
    telegram_post.assert_awaited_once()


@pytest.mark.asyncio
async def test_decimal_values_formatted_to_4dp() -> None:
    """Decimal prices and effective risk retain fixed alert precision."""
    engine = configured(discord_webhook_url="")
    assert engine._telegram is not None
    post = AsyncMock(return_value=200)
    engine._telegram._post = post
    await engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH)
    assert "Risk:      $5.5145" in post.await_args.args[0]["text"]


@pytest.mark.asyncio
async def test_alert_engine_logs_sent_on_success() -> None:
    """Successful delivery retains a channel/event/symbol audit record."""
    engine = configured(discord_webhook_url="")
    assert engine._telegram is not None
    engine._telegram._post = AsyncMock(return_value=200)
    with capture_logs() as logs:
        await engine.send_signal_triggered(signal(), calculation(), Regime.BEARISH)
    assert any(entry["event"] == "alert_sent" for entry in logs)
