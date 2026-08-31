"""Normalized metadata models returned by public market-data endpoints."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class SymbolInfo:
    """Trading metadata for a Bybit linear perpetual instrument."""

    symbol: str
    base_coin: str
    quote_coin: str
    status: str
    tick_size: Decimal
    lot_size: Decimal
    min_order_qty: Decimal
    max_leverage: float
    contract_type: str


@dataclass(frozen=True)
class Ticker24H:
    """Twenty-four-hour ticker values returned by the Bybit public API."""

    symbol: str
    last_price: Decimal
    high_24h: Decimal
    low_24h: Decimal
    volume_24h: Decimal
    turnover_24h: Decimal
    price_change_pct_24h: float
    timestamp: datetime
