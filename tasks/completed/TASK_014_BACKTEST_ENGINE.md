# TASK_014_BACKTEST_ENGINE — APPROVED 2026-09-01

Files delivered:
  src/scanner/protocols.py                — CandleProvider Protocol
  src/scanner/backtest/__init__.py
  src/scanner/backtest/backtest_engine.py — 657 lines
  tests/unit/test_backtest_engine.py      — 41 tests (2 updated by CTO for look-ahead fix)

Authorized patches:
  src/scanner/regime/detector.py          — CandleStore -> CandleProvider (type annotation)
  src/scanner/strategy/signal_manager.py  — same

352/352 tests passing.

CTO look-ahead fix: _advance_btc_to used open_time > target_time (bug).
Corrected to candle_close_time > target_time where close_time = open_time + 4H.
Two test assertions updated to reflect correct behavior.

GATE-2: pending human review of real historical backtest results.
