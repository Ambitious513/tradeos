"""Failure-isolated Telegram and Discord lifecycle alert delivery."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING

import aiohttp

from scanner.config import ScannerConfig
from scanner.logging_setup import get_logger
from scanner.models import Regime, SignalState

if TYPE_CHECKING:
    from scanner.risk.risk_engine import DailySession, RiskCalculation
    from scanner.strategy.signal_manager import ActiveSignal

logger = get_logger("alerting")


class _AlertChannel:
    """Shared aiohttp failure handling for one independently enabled channel."""

    _TIMEOUT_SECONDS = 5.0

    def __init__(self, channel: str) -> None:
        """Initialize an enabled channel with its stable structured-log name."""
        self._channel = channel
        self._enabled = True

    async def send(self, text: str, event: str, symbol: str | None = None) -> None:
        """Deliver one alert, handling every transport failure internally."""
        if not self._enabled:
            logger.debug("alert_channel_disabled", channel=self._channel, reason="4xx")
            return
        try:
            status = await self._post(self._payload(text))
            await self._handle_status(status, text, event, symbol, retry=False)
        except asyncio.TimeoutError:
            logger.warning("alert_timeout", channel=self._channel, alert_event=event)
        except Exception as error:
            logger.error(
                "alert_send_failed",
                channel=self._channel,
                alert_event=event,
                exception_type=type(error).__name__,
                message=str(error),
            )

    async def _handle_status(
        self,
        status: int,
        text: str,
        event: str,
        symbol: str | None,
        retry: bool,
    ) -> None:
        """Log a response outcome, allowing exactly one retry for server errors."""
        if 200 <= status < 300:
            logger.info(
                "alert_sent", channel=self._channel, alert_event=event, symbol=symbol
            )
            return
        if 400 <= status < 500:
            self._enabled = False
            logger.error(
                "alert_4xx_disabling", channel=self._channel, status_code=status
            )
            return
        logger.warning(
            "alert_http_5xx",
            channel=self._channel,
            status_code=status,
            alert_event=event,
        )
        if retry:
            return
        logger.warning("alert_retry", channel=self._channel, alert_event=event)
        await asyncio.sleep(1)
        try:
            retry_status = await self._post(self._payload(text))
            await self._handle_status(retry_status, text, event, symbol, retry=True)
        except asyncio.TimeoutError:
            logger.warning("alert_timeout", channel=self._channel, alert_event=event)
        except Exception as error:
            logger.error(
                "alert_send_failed",
                channel=self._channel,
                alert_event=event,
                exception_type=type(error).__name__,
                message=str(error),
            )

    async def _post(self, payload: Mapping[str, str]) -> int:
        """Post JSON with the bounded timeout required by the alert contract."""
        timeout = aiohttp.ClientTimeout(total=self._TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self._url, json=payload) as response:
                return response.status

    def _payload(self, text: str) -> Mapping[str, str]:
        """Return one channel-specific JSON request body."""
        raise NotImplementedError

    @property
    def _url(self) -> str:
        """Return the configured HTTP endpoint for this channel."""
        raise NotImplementedError


class _TelegramChannel(_AlertChannel):
    """Send alert text through the Telegram Bot API."""

    def __init__(self, token: str, chat_id: str) -> None:
        """Create one Telegram channel from configured credential strings."""
        super().__init__("telegram")
        self._token = token
        self._chat_id = chat_id

    @property
    def _url(self) -> str:
        """Return the documented Telegram Bot API endpoint."""
        return f"https://api.telegram.org/bot{self._token}/sendMessage"

    def _payload(self, text: str) -> Mapping[str, str]:
        """Format the Telegram API's required message payload."""
        return {"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"}


class _DiscordChannel(_AlertChannel):
    """Send alert text through a Discord incoming webhook."""

    def __init__(self, webhook_url: str) -> None:
        """Create one Discord channel from its configured webhook endpoint."""
        super().__init__("discord")
        self._webhook_url = webhook_url

    @property
    def _url(self) -> str:
        """Return the configured Discord incoming-webhook URL."""
        return self._webhook_url

    def _payload(self, text: str) -> Mapping[str, str]:
        """Format the Discord webhook request body."""
        return {"content": text}


class AlertEngine:
    """Send best-effort lifecycle alerts without affecting trading control flow."""

    def __init__(self, config: ScannerConfig) -> None:
        """Read channel configuration once and construct only enabled transports."""
        self._telegram: _TelegramChannel | None = None
        self._discord: _DiscordChannel | None = None
        if config.telegram_bot_token and config.telegram_chat_id:
            self._telegram = _TelegramChannel(
                config.telegram_bot_token, config.telegram_chat_id
            )
        if config.discord_webhook_url:
            self._discord = _DiscordChannel(config.discord_webhook_url)

    async def send_signal_triggered(
        self,
        signal: ActiveSignal,
        calculation: RiskCalculation,
        regime: Regime,
    ) -> None:
        """Send the approved A+ triggered alert with its contemporaneous regime."""
        try:
            text = (
                "🎯 A+ SIGNAL TRIGGERED\n"
                f"Symbol:    {signal.symbol}\n"
                f"Direction: {signal.direction.value} ({regime.value})\n"
                f"Entry:     ~{signal.estimated_entry:.4f} USDT (next open)\n"
                f"Stop:      {signal.stop_price:.4f} USDT\n"
                f"Target:    {signal.take_profit:.4f} USDT\n"
                f"R:R:       {calculation.rr_ratio:.2f}:1\n"
                f"Score:     {signal.score}/100\n"
                f"Qty:       {calculation.qty}\n"
                f"Risk:      ${calculation.effective_risk_usd:.4f}"
            )
            await self._send(text, "signal_triggered", signal.symbol)
        except Exception as error:
            self._log_event_failure("all", "signal_triggered", error)

    async def send_position_opened(
        self,
        signal: ActiveSignal,
        confirmed_entry: Decimal,
        calculation: RiskCalculation,
    ) -> None:
        """Send an ACTIVE-state message with the confirmed next-candle entry."""
        try:
            text = (
                "✅ POSITION OPENED\n"
                f"Symbol:    {signal.symbol}\n"
                f"Direction: {signal.direction.value}\n"
                f"Entry:     {confirmed_entry:.4f} USDT\n"
                f"Stop:      {calculation.stop_price:.4f} USDT\n"
                f"Target:    {calculation.take_profit:.4f} USDT"
            )
            await self._send(text, "position_opened", signal.symbol)
        except Exception as error:
            self._log_event_failure("all", "position_opened", error)

    async def send_position_closed(
        self,
        signal: ActiveSignal,
        outcome: SignalState,
        net_pnl: Decimal,
        daily_pnl: Decimal,
    ) -> None:
        """Send a TP or SL closure notification without allowing alert failures out."""
        try:
            if outcome is SignalState.TP_HIT:
                title = "💰 TAKE PROFIT HIT"
                pnl = f"+${net_pnl:.4f}"
            elif outcome is SignalState.SL_HIT:
                title = "🛑 STOP LOSS HIT"
                pnl = f"${net_pnl:.4f}"
            else:
                raise ValueError("position outcome must be TP_HIT or SL_HIT")
            text = (
                f"{title}\n"
                f"Symbol:    {signal.symbol}\n"
                f"Direction: {signal.direction.value}\n"
                f"Net PnL:   {pnl}\n"
                f"Daily PnL: ${daily_pnl:.4f}"
            )
            await self._send(text, "position_closed", signal.symbol)
        except Exception as error:
            self._log_event_failure("all", "position_closed", error)

    async def send_daily_halted(self, session: DailySession) -> None:
        """Send the current UTC session's final no-new-trades notification."""
        try:
            text = (
                "⛔ DAILY HALT — NO MORE TRADES\n"
                f"Reason:      {session.halt_reason}\n"
                f"Realized:    ${session.realized_pnl:.4f}\n"
                f"Trades:      {session.trades_taken}"
            )
            await self._send(text, "daily_halted", None)
        except Exception as error:
            self._log_event_failure("all", "daily_halted", error)

    async def _send(self, text: str, event: str, symbol: str | None) -> None:
        """Send to all configured channels concurrently and isolate each result."""
        channels = [channel for channel in (self._telegram, self._discord) if channel]
        if not channels:
            logger.debug("alert_channel_disabled", channel="all", reason="unconfigured")
            return
        await asyncio.gather(
            *(channel.send(text, event, symbol) for channel in channels),
            return_exceptions=True,
        )

    @staticmethod
    def _log_event_failure(channel: str, event: str, error: Exception) -> None:
        """Record malformed-message errors without breaking caller control flow."""
        logger.error(
            "alert_send_failed",
            channel=channel,
            alert_event=event,
            exception_type=type(error).__name__,
            message=str(error),
        )
