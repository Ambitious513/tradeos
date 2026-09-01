"""Structural protocols for dependency injection and backtest isolation."""

from typing import Protocol

from scanner.models import Candle


class CandleProvider(Protocol):
    """Expose the closed-candle read surface needed by scanner components."""

    def get_closed_candles(self, symbol: str, interval: str, n: int) -> list[Candle]:
        """Return up to ``n`` closed candles for one symbol and interval."""
