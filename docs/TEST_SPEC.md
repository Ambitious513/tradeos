# TEST_SPEC.md — A+ Scanner Test Specification
# Version: 1.0 (GATE-1 APPROVED)
# Authority: Lead CTO
# Last Updated: 2026-08-31

---

## 1. TESTING PHILOSOPHY

Tests are the primary defense against:
- Strategy drift (code silently deviating from spec)
- Look-ahead bias in backtest
- Risk limit bypass
- Data corruption propagating to signals
- Regressions during refactoring

**Every task must include tests. No task is APPROVED without passing tests.**

Test framework: **pytest** (Python)
Coverage tracking: **pytest-cov**
Minimum coverage target: 80% for strategy and risk modules

---

## 2. UNIT TESTS

### 2.1 Indicator Tests

**File**: `tests/unit/test_indicators.py`

| Test ID | Component | Scenario | Expected |
|---|---|---|---|
| IND-001 | EMA7 | Known sequence → known output | Match reference values |
| IND-002 | EMA14 | Known sequence → known output | Match reference values |
| IND-003 | EMA28 | Known sequence → known output | Match reference values |
| IND-004 | EMA | Fewer candles than period | warmup_complete=False |
| IND-005 | RSI14 | Known sequence (Wilder's) | Match reference values |
| IND-006 | RSI | RSI below 14-period warmup | warmup_complete=False |
| IND-007 | RSI | All gains (no losses) | RSI = 100 |
| IND-008 | RSI | All losses (no gains) | RSI = 0 |
| IND-009 | ATR14 | Known OHLC → known ATR | Match reference values |
| IND-010 | ATR | Single candle (no prev_close) | Handles gracefully |
| IND-011 | 24H High | 24 candles, max is known | Correct high identified |
| IND-012 | 24H Low | 24 candles, min is known | Correct low identified |
| IND-013 | 24H Change | Close now vs close 24H ago | Correct percentage |
| IND-014 | 24H Stats | Forming candle present | Forming candle excluded |
| IND-015 | Volume avg | 20-period average | Correct arithmetic mean |

### 2.2 BTC Regime Tests

**File**: `tests/unit/test_regime.py`

| Test ID | Scenario | Expected |
|---|---|---|
| REG-001 | EMA7>EMA14>EMA28, close>EMA7, 24H change=+3% | BULLISH |
| REG-002 | EMA7<EMA14<EMA28, close<EMA7, 24H change=-3% | BEARISH |
| REG-003 | EMA7>EMA14<EMA28 (mixed stack) | NEUTRAL |
| REG-004 | 24H change=+1.2% (below threshold) | NEUTRAL |
| REG-005 | 24H change=-1.2% (above threshold) | NEUTRAL |
| REG-006 | 24H change=+1.5% (exactly at threshold) | NEUTRAL (not bullish) |
| REG-007 | 24H change=+1.51% | BULLISH (if stack aligned) |
| REG-008 | BTC data stale | UNDEFINED |
| REG-009 | EMA7==EMA14 | NEUTRAL |
| REG-010 | Close inside EMA stack | NEUTRAL |

### 2.3 Risk Engine Tests

**File**: `tests/unit/test_risk.py`

| Test ID | Scenario | Expected |
|---|---|---|
| RISK-001 | Standard short: entry=100, stop=102, risk=$5 | qty=2.5 contracts at 1x (notional $250, risk 2%) |
| RISK-002 | Quantity rounded to lot_size=0.1 | Round DOWN |
| RISK-003 | qty below min_order_qty | DisqualifiedError |
| RISK-004 | stop == entry | DisqualifiedError (zero risk distance) |
| RISK-005 | stop on wrong side (short: stop < entry) | DisqualifiedError |
| RISK-006 | R:R = 1.9 (below 2.0 minimum) | DisqualifiedError |
| RISK-007 | R:R = 2.0 exactly | PASS |
| RISK-008 | Daily trades = 5 | can_trade() = False |
| RISK-009 | Daily PnL = -$25.00 | can_trade() = False |
| RISK-010 | Daily PnL = +$50.00 | can_trade() = False |
| RISK-011 | Daily PnL = +$49.99 | can_trade() = True |
| RISK-012 | Risk engine exception (mock) | Returns None gracefully |
| RISK-013 | Fee calculation at 0.055% × 2 | Correct total fee |
| RISK-014 | Slippage at 0.05% × 2 | Correct total slippage |
| RISK-015 | Duplicate signal same symbol | REJECTED |

---

## 3. STRATEGY TESTS

### 3.1 Short Setup Tests

**File**: `tests/strategy/test_short_setup.py`

| Test ID | Scenario | Expected |
|---|---|---|
| SHT-001 | All conditions met | SetupCandidate returned (SHORT, DETECTED) |
| SHT-002 | 24H change = +7.9% | No setup (below 8% threshold) |
| SHT-003 | 24H change = +8.0% | Setup detected (inclusive) |
| SHT-004 | RSI = 74.9 | No setup |
| SHT-005 | RSI = 75.0 | Setup detected (inclusive) |
| SHT-006 | EMA extension = 2.9% | No setup |
| SHT-007 | EMA extension = 3.0% | Setup detected (inclusive) |
| SHT-008 | BTC regime = NEUTRAL | No setup (regime gate) |
| SHT-009 | BTC regime = BULLISH | No setup (wrong direction) |
| SHT-010 | RSI warmup incomplete | No setup |
| SHT-011 | Forming candle input | Error / no setup |

### 3.2 Rejection Candle Tests

| Test ID | Scenario | Expected |
|---|---|---|
| SHT-020 | Bearish close, wick=2× body | Rejection valid |
| SHT-021 | Bearish close, wick=1.5× body | Rejection valid |
| SHT-022 | Bearish close, wick=1.4× body | Rejection invalid |
| SHT-023 | Bullish close | Rejection invalid |
| SHT-024 | Doji (body=0) | Rejection invalid |
| SHT-025 | At 24H high (within 0.5%) | Rejection valid |
| SHT-026 | 0.6% below 24H high | Rejection invalid |

### 3.3 Retest Tests

| Test ID | Scenario | Expected |
|---|---|---|
| SHT-030 | Retest within 4H, closes below rejection | Retest valid |
| SHT-031 | Retest after 4H (expired) | Retest invalid; setup EXPIRED |
| SHT-032 | Retest exceeds 24H high (new high) | Setup CANCELLED |
| SHT-033 | Retest candle closes above rejection | Retest invalid |

### 3.4 Entry Trigger Tests (Short)

| Test ID | Scenario | Expected |
|---|---|---|
| SHT-040 | Candle closes below retest low, regime=BEARISH | TRIGGERED |
| SHT-041 | Candle closes below retest low, regime=NEUTRAL | CANCELLED |
| SHT-042 | Entry price = next candle open | Correct |

### 3.5 Long Setup Tests

**File**: `tests/strategy/test_long_setup.py`

Mirror of Short tests with inverted conditions (LONG-001 through LONG-011).
All equivalent tests must exist for long setups.

### 3.6 Signal State Machine Tests

**File**: `tests/strategy/test_state_machine.py`

| Test ID | Scenario | Expected |
|---|---|---|
| SSM-001 | DETECTED → WATCHING | Correct transition |
| SSM-002 | WATCHING → ARMED | Correct transition |
| SSM-003 | ARMED → TRIGGERED | Correct transition |
| SSM-004 | TRIGGERED → ACTIVE | Correct transition |
| SSM-005 | ACTIVE → TP_HIT | Correct on TP candle |
| SSM-006 | ACTIVE → SL_HIT | Correct on SL candle |
| SSM-007 | DETECTED → EXPIRED | After expiration time |
| SSM-008 | Any state → CANCELLED | On regime change |
| SSM-009 | Backward transition attempt | Raises error |
| SSM-010 | Terminal state re-processed | No transition, returns same state |

---

## 4. INTEGRATION TESTS

**File**: `tests/integration/test_bybit_data.py`

These tests run against Bybit TESTNET only.

| Test ID | Scenario | Expected |
|---|---|---|
| INT-001 | Fetch BTC/USDT 1H candles (last 100) | Returns 100 candles, all is_closed=True |
| INT-002 | Fetch symbol universe | Returns list of symbols with volume filter |
| INT-003 | WebSocket connection | Connects, receives at least 1 candle within 70s |
| INT-004 | WebSocket disconnect recovery | Reconnects and resumes within 30s |
| INT-005 | REST rate limit handling | Backoff triggered, no crash |
| INT-006 | Stale data detection | Staleness flag set after simulated gap |
| INT-007 | Symbol metadata fetch | Returns tick_size, lot_size, min_order_qty |

---

## 5. REPLAY TESTS

**File**: `tests/backtest/test_replay.py`

Replay tests run the strategy against pre-recorded fixture candle sequences and verify the exact signal outputs.

| Test ID | Scenario | Expected |
|---|---|---|
| RPL-001 | Known short setup sequence → rejection → retest → trigger | Signal reaches TRIGGERED |
| RPL-002 | Known long setup sequence (sweep → recovery → retest → trigger) | Signal reaches TRIGGERED |
| RPL-003 | Setup where BTC goes NEUTRAL mid-sequence | Signal CANCELLED at regime change |
| RPL-004 | Setup that expires (no retest within 4H) | Signal EXPIRED |
| RPL-005 | TP hit scenario | ACTIVE → TP_HIT |
| RPL-006 | SL hit scenario | ACTIVE → SL_HIT |
| RPL-007 | Duplicate symbol signal blocked | Second signal rejected |
| RPL-008 | Daily trade limit reached | 6th signal not accepted |

---

## 6. BACKTEST INTEGRITY TESTS

**File**: `tests/backtest/test_integrity.py`

These tests specifically validate that the backtest does NOT have look-ahead bias.

| Test ID | Check | Method |
|---|---|---|
| BIT-001 | No future candle access | Inject sentinel future candle; verify not used |
| BIT-002 | 24H high computed from past candles only | Verify 24H high = max of candles[t-24:t], not candles[t:] |
| BIT-003 | Entry fills at next candle open | Verify fill_price == candles[t+1].open |
| BIT-004 | Signal detection uses only closed candles | Assert is_closed=True for all evaluated candles |
| BIT-005 | Forming candle not used anywhere | Inject is_closed=False candle; verify rejected |
| BIT-006 | No survivorship bias in symbol selection | Document limitation; warn if universe not historical |

---

## 7. RELIABILITY TESTS

**File**: `tests/reliability/test_failures.py`

| Test ID | Scenario | Expected |
|---|---|---|
| REL-001 | REST API returns HTTP 500 | Retry 3×; log ERROR; skip scan cycle |
| REL-002 | WebSocket timeout (no message 30s) | Reconnect triggered |
| REL-003 | WebSocket returns malformed JSON | Log ERROR; skip candle; continue |
| REL-004 | OHLC violation in candle data | Discard candle; log ERROR |
| REL-005 | Risk engine exception | NO TRADE; log ERROR; send alert |
| REL-006 | Alert send failure (Telegram down) | Log ERROR; scanner continues |
| REL-007 | Database write failure | Log ERROR; continue (no crash) |
| REL-008 | Scanner restart mid-signal | Active signals restored from persistence |
| REL-009 | BTC data unavailable > 5 min | Regime=UNDEFINED; scanner halts signals |
| REL-010 | All symbols fail data validation | Empty scan cycle; log WARNING |

---

## 8. PAPER TRADING TESTS

**File**: `tests/execution/test_paper_trader.py`

| Test ID | Scenario | Expected |
|---|---|---|
| PPT-001 | Open long position at entry price | Position recorded correctly |
| PPT-002 | TP hit — PnL calculation | Correct PnL including fees and slippage |
| PPT-003 | SL hit — PnL calculation | Correct loss including fees and slippage |
| PPT-004 | Daily PnL tracking | Correct running total |
| PPT-005 | Daily halt triggered | No new positions after halt |

---

## 9. TEST DATA FIXTURES

Fixture candle data must be stored in `tests/fixtures/`:
- `btc_bullish_regime_4h.json` — BTC candles producing BULLISH regime
- `btc_bearish_regime_4h.json` — BTC candles producing BEARISH regime
- `btc_neutral_regime_4h.json` — BTC candles producing NEUTRAL regime
- `short_setup_complete_1h.json` — Full short setup sequence to TRIGGERED
- `long_setup_complete_1h.json` — Full long setup sequence to TRIGGERED
- `expired_setup_1h.json` — Setup that expires before trigger
- `cancelled_setup_1h.json` — Setup cancelled by regime change

All fixtures must use SYNTHETIC data (not real historical prices) to avoid copyright and privacy concerns.

---

## 10. CONTINUOUS INTEGRATION

When CI is configured:
```
pytest tests/unit/       — on every commit
pytest tests/strategy/   — on every commit
pytest tests/risk/       — on every commit
pytest tests/integration/ — on PR merge (requires testnet)
pytest tests/backtest/   — on major task completion
pytest tests/reliability/ — on major task completion
```

---

*End of TEST_SPEC.md v0.1-DRAFT*

