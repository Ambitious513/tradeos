"""Tests for the approved configuration defaults."""

from pydantic import ValidationError

from scanner.config import ScannerConfig


def test_config_loads_with_defaults(config: ScannerConfig) -> None:
    """Configuration loads without API credentials."""
    assert config.bybit_api_key == ""


def test_testnet_default_is_true(config: ScannerConfig) -> None:
    """Development must use the Bybit testnet unless explicitly overridden."""
    assert config.bybit_testnet is True


def test_environment_default_is_development(config: ScannerConfig) -> None:
    """The default execution environment is development."""
    assert config.environment == "development"


def test_strategy_constants_match_spec(config: ScannerConfig) -> None:
    """All approved GATE-1 strategy constants retain their prescribed values."""
    assert config.btc_neutral_threshold_pct == 1.5
    assert config.pump_threshold_pct == 8.0
    assert config.dump_threshold_pct == 8.0
    assert config.rsi_overbought == 75.0
    assert config.rsi_oversold == 25.0
    assert config.ema7_extension_pct == 3.0
    assert config.atr_stop_multiplier == 1.5
    assert config.min_rr_ratio == 2.0
    assert config.setup_expiration_hours == 4
    assert config.aplus_score_threshold == 80
    assert config.universe_min_volume_usd == 50_000_000.0


def test_risk_constants_match_spec(config: ScannerConfig) -> None:
    """All approved GATE-1 risk constants retain their prescribed values."""
    assert config.risk_per_trade_usd == 5.0
    assert config.daily_loss_limit_usd == -25.0
    assert config.daily_profit_lock_usd == 50.0
    assert config.max_trades_per_day == 5
    assert config.taker_fee_rate == 0.00055
    assert config.slippage_rate == 0.0005


def test_env_override_works(monkeypatch: object) -> None:
    """Environment variables override the default configuration values."""
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")  # type: ignore[attr-defined]
    monkeypatch.setenv("BYBIT_TESTNET", "false")  # type: ignore[attr-defined]
    config = ScannerConfig(_env_file=None)
    assert config.log_level == "DEBUG"
    assert config.bybit_testnet is False


def test_empty_api_keys_acceptable(config: ScannerConfig) -> None:
    """Local development does not require exchange credentials."""
    assert config.bybit_api_key == ""
    assert config.bybit_api_secret == ""


def test_invalid_risk_values_are_rejected() -> None:
    """Invalid safety limits fail validation rather than being silently accepted."""
    try:
        ScannerConfig(_env_file=None, risk_per_trade_usd=-1.0)
    except ValidationError:
        return
    raise AssertionError("negative risk_per_trade_usd was accepted")
