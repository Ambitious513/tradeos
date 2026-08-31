# A+ Scanner

The A+ Scanner is a deterministic, safety-first scanner for approved crypto-market
setups. This repository currently contains its project foundation only; it does not
connect to exchanges or execute trades.

## Setup

Use Python 3.11 or newer, then install the package and development tools:

```powershell
pip install -e ".[dev]"
Copy-Item .env.example .env
pytest tests/unit/
```

`BYBIT_TESTNET` defaults to `true`. Do not add credentials to `.env.example`.
