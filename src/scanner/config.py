"""Application configuration sourced from environment variables."""

from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScannerConfig(BaseSettings):
    """Validated runtime configuration for the scanner.

    Strategy and risk defaults are fixed to the approved GATE-1 specifications.
    Environment variables can configure deployments but cannot make invalid risk
    values acceptable.
    """

    environment: Literal["development", "paper", "live"] = "development"
    log_level: str = "INFO"

    bybit_api_key: str = ""
    bybit_api_secret: str = ""
    bybit_testnet: bool = True
    database_url: str = "sqlite+aiosqlite:///./scanner.db"

    btc_neutral_threshold_pct: float = 1.5
    pump_threshold_pct: float = 8.0
    dump_threshold_pct: float = 8.0
    rsi_overbought: float = 75.0
    rsi_oversold: float = 25.0
    ema7_extension_pct: float = 3.0
    atr_stop_multiplier: float = 1.5
    min_rr_ratio: float = 2.0
    setup_expiration_hours: int = 4
    aplus_score_threshold: int = 80
    universe_min_volume_usd: float = 50_000_000.0
    universe_new_listing_days: int = 30  # include symbols listed within this many days

    risk_per_trade_usd: float = 5.00
    daily_loss_limit_usd: float = -25.00
    daily_profit_lock_usd: float = 50.00
    max_trades_per_day: int = 5
    taker_fee_rate: float = 0.00055
    slippage_rate: float = 0.0005

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @field_validator(
        "btc_neutral_threshold_pct",
        "pump_threshold_pct",
        "dump_threshold_pct",
        "rsi_overbought",
        "rsi_oversold",
        "ema7_extension_pct",
        "atr_stop_multiplier",
        "min_rr_ratio",
        "universe_min_volume_usd",
        "risk_per_trade_usd",
        "daily_profit_lock_usd",
        "taker_fee_rate",
        "slippage_rate",
    )
    @classmethod
    def validate_positive_float(cls, value: float) -> float:
        """Reject non-positive values for positive operational thresholds."""
        if value <= 0:
            raise ValueError("value must be greater than zero")
        return value

    @field_validator(
        "setup_expiration_hours", "aplus_score_threshold", "max_trades_per_day"
    )
    @classmethod
    def validate_positive_int(cls, value: int) -> int:
        """Reject zero and negative count-based limits."""
        if value <= 0:
            raise ValueError("value must be greater than zero")
        return value

    @field_validator("daily_loss_limit_usd")
    @classmethod
    def validate_negative_loss_limit(cls, value: float) -> float:
        """Require the daily-loss halt threshold to remain negative."""
        if value >= 0:
            raise ValueError("daily loss limit must be negative")
        return value
