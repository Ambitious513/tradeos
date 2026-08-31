# Test fixtures

`tests/conftest.py` provides factories for valid normalized candles:

- `sample_candle(is_closed=True)` returns a 1H `ETHUSDT` candle.
- `sample_btc_candle(is_closed=True)` returns a 4H `BTCUSDT` candle.

Both factories use UTC timestamps and `Decimal` OHLCV values. Future strategy tests
should derive fixtures from these factories, explicitly selecting `is_closed=False`
only when testing that forming candles are rejected.
