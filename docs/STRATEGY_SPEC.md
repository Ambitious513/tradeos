# STRATEGY_SPEC.md — A+ Scanner Deterministic Strategy Specification
# Version: 1.0 (GATE-1 APPROVED)
# Authority: Lead CTO
# Last Updated: 2026-08-31
# GATE-1 Approved: 2026-08-31 by Human
# Status: APPROVED — All ambiguity resolutions confirmed by human. Implementation may proceed.

---

> **PROTECTED DOCUMENT**
> Modification requires Strategy Change Proposal + Human Approval.
> See AGENTS.md Article 6.

---

## PREAMBLE — AMBIGUITY REGISTER

The following ambiguities were identified during the initial audit of the Master Brief.
All resolutions were reviewed and **APPROVED by Human at GATE-1 on 2026-08-31**.
These are now locked rules. Any change requires a formal Strategy Change Proposal (AGENTS.md Article 6).

| Ambiguity ID | Topic | Approved Resolution | Status |
|---|---|---|---|
| AMB-001 | BTC timeframe for regime | 4H candles primary; 1H for confirmation | ✅ APPROVED |
| AMB-002 | "Neutral zone" exact threshold | BTC 24H change between -1.5% and +1.5% = NEUTRAL | ✅ APPROVED |
| AMB-003 | "24H" definition | Rolling 24H window from current closed candle | ✅ APPROVED |
| AMB-004 | "Pump" exact threshold | 24H change >= +8% for short setup | ✅ APPROVED |
| AMB-005 | "Dump" exact threshold | 24H change <= -8% for long setup | ✅ APPROVED |
| AMB-006 | RSI threshold for short | RSI(14) >= 75 on 1H timeframe | ✅ APPROVED |
| AMB-007 | RSI threshold for long | RSI(14) <= 25 on 1H timeframe | ✅ APPROVED |
| AMB-008 | EMA7 extension definition | Price > EMA7 by >= 3% (short); < EMA7 by >= 3% (long) | ✅ APPROVED |
| AMB-009 | "Interaction with 24H high" | Candle high within 0.5% of 24H high, or above it | ✅ APPROVED |
| AMB-010 | Rejection definition | Bearish close; upper wick >= 1.5× body | ✅ APPROVED |
| AMB-011 | Retest definition | Price returns within 0.5% of rejection level; no new 24H high | ✅ APPROVED |
| AMB-012 | Entry trigger (short) | Confirmed 1H close below retest candle low | ✅ APPROVED |
| AMB-013 | Entry trigger (long) | Confirmed 1H close above retest candle high | ✅ APPROVED |
| AMB-014 | Liquidity sweep definition | Candle low breaches 24H low by >=0.1%; candle closes back above | ✅ APPROVED |
| AMB-015 | Stop placement | MAX(structural stop, 1.5×ATR14) — wider of the two | ✅ APPROVED |
| AMB-016 | Target / R:R ratio | Minimum 2:1 reward-to-risk; disqualify below | ✅ APPROVED |
| AMB-017 | Setup expiration | 4 hours from first DETECTED state | ✅ APPROVED |
| AMB-018 | BTC regime change mid-setup | Setup is CANCELLED immediately | ✅ APPROVED |
| AMB-019 | Multiple simultaneous setups | Allowed up to daily trade limit; ranked by score | ✅ APPROVED |
| AMB-020 | Qualifying timeframe for setups | 1H closed candles as primary setup timeframe | ✅ APPROVED |
| AMB-021 | Candle confirmation | Only CLOSED candles used; forming candle NEVER triggers entry | ✅ APPROVED |
| AMB-022 | Symbol universe definition | All Bybit USDT linear perpetuals with 24H volume >= $50M USD | ✅ APPROVED |
| AMB-023 | $5 risk — per trade or per day | Per-trade fixed risk = $5.00 USD | ✅ APPROVED |
| AMB-024 | Daily loss limit | -$25.00 USD — halt all new setups for the day | ✅ APPROVED |
| AMB-025 | Daily profit lock | +$50.00 USD — halt all new setups for the day | ✅ APPROVED |
| AMB-026 | Fees assumption | 0.055% taker fee per side (Bybit USDT linear default) | ✅ APPROVED |
| AMB-027 | Slippage assumption | 0.05% additional slippage per fill | ✅ APPROVED |
| AMB-028 | Scoring — what constitutes A+ | Score >= 80/100 required to proceed | ✅ APPROVED |

---

## SECTION 1 — BTC MARKET REGIME

### Rule ID: REGIME-001
**Name**: BTC Regime Classification
**Purpose**: Gate all setup detection on BTC market direction. No trade is taken when BTC regime is NEUTRAL or undefined.

**Inputs**:
- BTC/USDT 4H OHLCV (Bybit, confirmed closed candles only)
- EMA7(close), EMA14(close), EMA28(close) on 4H
- 24H price change from rolling 24H window

**Definitions**:

#### BULLISH
```
ALL of the following must be true on the most recent CLOSED 4H candle:
  1. EMA7 > EMA14 > EMA28  (EMA stack bullish alignment)
  2. BTC 4H close > EMA7
  3. BTC 24H change > +1.5%
```

#### BEARISH
```
ALL of the following must be true on the most recent CLOSED 4H candle:
  1. EMA7 < EMA14 < EMA28  (EMA stack bearish alignment)
  2. BTC 4H close < EMA7
  3. BTC 24H change < -1.5%
```

#### NEUTRAL
```
Any condition not satisfying full BULLISH or full BEARISH criteria.
Regime = NEUTRAL when:
  - EMA stack is mixed (not cleanly aligned either direction), OR
  - BTC 24H change is between -1.5% and +1.5%, OR
  - BTC close is within the EMA stack (EMA7 < close < EMA28 or inverted)
```

**[AMB-001 RESOLUTION]**: Primary regime uses 4H candles.
**[AMB-002 RESOLUTION]**: Neutral threshold is ±1.5% 24H change.

**Threshold**:
- Bullish requires 24H change > +1.5%
- Bearish requires 24H change < -1.5%
- Neutral: -1.5% ≤ 24H change ≤ +1.5%

**Timeframe**: 4H (primary), re-evaluated on every new closed 4H candle

**Trigger**: Regime may change only on confirmed 4H candle close

**Invalidation**: If BTC API data is stale (> 4H + 5 min), regime = UNDEFINED → NO TRADE

**Edge Cases**:
- EMA7 == EMA14: NEUTRAL
- BTC halted / data missing: UNDEFINED → NO TRADE
- Regime changes from BEARISH to BULLISH mid-scan cycle: cancel all active SHORT setups; begin scanning for LONG setups on next cycle

---

### Rule ID: REGIME-002
**Name**: BTC Confirmation Check
**Purpose**: Verify BTC regime hasn't degraded between initial scan and entry execution.

**Procedure**: Before accepting any entry trigger, re-evaluate BTC regime. If regime changed since setup detection, CANCEL the setup.

**[AMB-018 RESOLUTION]**: BTC regime change during active setup = immediate CANCEL.

---

## SECTION 2 — SYMBOL UNIVERSE

### Rule ID: UNIVERSE-001
**Name**: Tradeable Symbol Universe
**Purpose**: Define the set of coins eligible for scanning.

**Criteria** (all must be satisfied):
```
Exchange: Bybit USDT Linear Perpetuals
24H USD volume: >= $50,000,000
Settlement: USDT
Status: TRADING (not suspended, not settling)
Exclusions: BTC/USDT itself (used only as regime filter)
```

**[AMB-022 RESOLUTION]**: Volume threshold = $50M 24H USD volume.

**Refresh**: Universe list refreshed every 24H at UTC 00:05.

**Failure**: If universe refresh fails, use prior valid list. Log ERROR.

---

## SECTION 3 — SETUP TIMEFRAME

**[AMB-020 RESOLUTION]**: All setup detection occurs on **1H** (1-hour) confirmed closed candles.

**[AMB-021 RESOLUTION]**: A forming (incomplete) candle NEVER triggers any signal state. Only closed candles are evaluated.

**Candle Timing**:
- 1H candles close at the top of each UTC hour (00:00, 01:00, 02:00, …)
- Processing runs within 30 seconds of candle close
- Any processing delay > 5 minutes = stale; log WARNING

---

## SECTION 4 — EXHAUSTION SHORT SETUP

**Applicable BTC Regime**: BEARISH only

### Rule ID: SHORT-001
**Name**: 24H Pump Condition
**Purpose**: Identify altcoins that have pumped hard while BTC is bearish — high reversal probability.

**[AMB-003 RESOLUTION]**: "24H" = rolling 24-hour window ending at the close of the current evaluated 1H candle.

**[AMB-004 RESOLUTION]**: Pump threshold = 24H price change >= +8%.

```
Input:    Rolling 24H close change for the altcoin symbol
Formula:  pump_pct = (current_close - close_24h_ago) / close_24h_ago * 100
Threshold: pump_pct >= 8.0
Timeframe: 1H candle (rolling 24H lookback)
```

**Edge Cases**:
- Candle 24H ago is missing: disqualify symbol, log WARNING
- Symbol listed < 24H ago: disqualify, too new

---

### Rule ID: SHORT-002
**Name**: RSI Overbought Condition
**Purpose**: Confirm exhaustion via momentum oscillator.

**[AMB-006 RESOLUTION]**: RSI(14) on 1H timeframe >= 75.

```
Input:    RSI(14) on closed 1H candles (Wilder's smoothing method)
Threshold: RSI >= 75
Timeframe: 1H
```

**Note**: RSI period is 14 candles. Use standard Wilder's smoothing (not simple moving average).

**Edge Cases**:
- Fewer than 28 candles available (2× period warmup): disqualify
- RSI exactly 75.000: qualifies (inclusive)

---

### Rule ID: SHORT-003
**Name**: EMA7 Extension Condition (Short)
**Purpose**: Confirm price is extended above short-term mean.

**[AMB-008 RESOLUTION]**: Price must be > EMA7 by >= 3%.

```
Input:    EMA7(close) on 1H, current close price
Formula:  extension_pct = (close - EMA7) / EMA7 * 100
Threshold: extension_pct >= 3.0
Timeframe: 1H
```

**Edge Cases**:
- EMA7 = 0: error, disqualify
- Price exactly 3.0% above EMA7: qualifies (inclusive)

---

### Rule ID: SHORT-004
**Name**: 24H High Interaction
**Purpose**: Confirm price is testing the 24H high resistance zone.

**[AMB-009 RESOLUTION]**: Current 1H candle high must be within 0.5% of the rolling 24H high.

```
Input:    Rolling 24H high (highest high over 24H window)
Formula:  proximity_pct = (high_24h - candle_high) / high_24h * 100
Threshold: proximity_pct <= 0.5  (candle high within 0.5% below 24H high, OR exceeds it)
Timeframe: 1H
```

**Note**: Candle high >= 24H high also qualifies (price at or above 24H high).

---

### Rule ID: SHORT-005
**Name**: Rejection Candle (Short)
**Purpose**: Confirm bearish reversal at resistance.

**[AMB-010 RESOLUTION]**:

```
A REJECTION candle (bearish) is defined as:
  1. Candle close < candle open  (bearish close)
  2. Upper wick >= 1.5 × |candle body|
     where: upper_wick = candle_high - candle_open
            candle_body = |candle_open - candle_close|
  3. Candle must interact with 24H high (SHORT-004 satisfied)
```

**Timeframe**: 1H closed candle

**Edge Cases**:
- Doji candle (body = 0): disqualify (divide by zero risk; no clear direction)
- Candle body < minimum price precision: disqualify

---

### Rule ID: SHORT-006
**Name**: Retest (Short)
**Purpose**: Confirm failed recovery to resistance before entry.

**[AMB-011 RESOLUTION]**:

```
A RETEST is valid when:
  1. After rejection candle, price returns upward toward the rejection close level
  2. Retest candle high is within 0.5% of rejection candle close (the new resistance)
  3. Retest candle closes BELOW the rejection candle close
  4. No new 24H high is made during the retest
```

**Timeframe**: 1H closed candles following the rejection candle
**Expiration**: Retest must occur within 4 hours of rejection candle close (4 candles)

---

### Rule ID: SHORT-007
**Name**: Entry Trigger (Short)
**Purpose**: Deterministic entry rule.

**[AMB-012 RESOLUTION]**:

```
Entry is triggered when:
  1. A 1H candle CLOSES below the retest candle's low
  2. BTC regime is still BEARISH (re-checked at moment of trigger)
  3. Setup has not expired (SHORT-006 expiration)
  4. Risk engine approves (see RISK section)
```

**Entry Price**: Open of the NEXT candle after the trigger candle closes.

**[AMB-021 COMPLIANCE]**: Entry is placed at next candle open — never on a forming candle.

---

### Rule ID: SHORT-008
**Name**: Stop Loss (Short)

**[AMB-015 RESOLUTION]**:

```
Stop = MAX of:
  1. Structural stop: highest high of the last 3 candles + (0.1% × entry_price)
  2. ATR stop: entry_price + (1.5 × ATR14_1H)
```

**Purpose**: Use the wider of structural or volatility-based stop for safety.

---

### Rule ID: SHORT-009
**Name**: Take Profit (Short)

**[AMB-016 RESOLUTION]**: Minimum 2:1 R:R.

```
risk_distance = stop_price - entry_price  (positive value)
take_profit = entry_price - (2.0 × risk_distance)
```

**Minimum R:R**: If calculated R:R < 2.0, setup is DISQUALIFIED.

---

### Rule ID: SHORT-010
**Name**: Setup Expiration (Short)

**[AMB-017 RESOLUTION]**:

```
A Short setup expires if:
  1. Retest does not occur within 4 hours of rejection candle close, OR
  2. Entry trigger does not fire within 4 hours of retest, OR
  3. BTC regime changes from BEARISH
  4. A new 24H high is made (invalidates the rejection)
```

---

## SECTION 5 — EXHAUSTION LONG SETUP

**Applicable BTC Regime**: BULLISH only

### Rule ID: LONG-001
**Name**: 24H Dump Condition

**[AMB-005 RESOLUTION]**: 24H change <= -8%.

```
Formula:  dump_pct = (current_close - close_24h_ago) / close_24h_ago * 100
Threshold: dump_pct <= -8.0
```

---

### Rule ID: LONG-002
**Name**: RSI Oversold Condition

**[AMB-007 RESOLUTION]**: RSI(14) on 1H <= 25.

```
Threshold: RSI <= 25
Method: Wilder's smoothing, period 14
```

---

### Rule ID: LONG-003
**Name**: EMA7 Extension Condition (Long)

```
Formula:  extension_pct = (EMA7 - close) / EMA7 * 100
Threshold: extension_pct >= 3.0  (price >= 3% below EMA7)
```

---

### Rule ID: LONG-004
**Name**: 24H Low Interaction

```
proximity_pct = (candle_low - low_24h) / low_24h * 100
Threshold: proximity_pct <= 0.5  (candle low within 0.5% above 24H low, OR below it)
```

---

### Rule ID: LONG-005
**Name**: Liquidity Sweep

**[AMB-014 RESOLUTION]**:

```
A LIQUIDITY SWEEP is valid when:
  1. Current 1H candle low goes BELOW the rolling 24H low by >= 0.1%
  2. The same candle CLOSES ABOVE the 24H low
  (i.e., the sweep is rejected — close recovers above 24H low)
```

**Formula**:
```
sweep_depth = (low_24h - candle_low) / low_24h * 100
sweep_recovery = candle_close > low_24h
valid_sweep = (sweep_depth >= 0.1) AND (sweep_recovery == True)
```

---

### Rule ID: LONG-006
**Name**: Rejection / Reversal Candle (Long)

```
A REJECTION candle (bullish, at 24H low) is defined as:
  1. Candle close > candle open  (bullish close)
  2. Lower wick >= 1.5 × |candle body|
     where: lower_wick = candle_open - candle_low
            candle_body = |candle_open - candle_close|
  3. Liquidity sweep condition must be met (LONG-005)
```

---

### Rule ID: LONG-007
**Name**: Retest (Long)

```
A RETEST (long) is valid when:
  1. After sweep/rejection candle, price pulls back toward the sweep/rejection close level
  2. Retest candle low is within 0.5% of rejection candle close (new support)
  3. Retest candle closes ABOVE the rejection candle close
  4. No new 24H low is made during retest
```

**Expiration**: Retest must occur within 4 hours of sweep candle close.

---

### Rule ID: LONG-008
**Name**: Entry Trigger (Long)

**[AMB-013 RESOLUTION]**:

```
Entry is triggered when:
  1. A 1H candle CLOSES above the retest candle's high
  2. BTC regime is still BULLISH (re-checked at trigger)
  3. Setup has not expired
  4. Risk engine approves
```

**Entry Price**: Open of the NEXT candle after trigger candle closes.

---

### Rule ID: LONG-009
**Name**: Stop Loss (Long)

```
Stop = MIN of:
  1. Structural stop: lowest low of last 3 candles - (0.1% × entry_price)
  2. ATR stop: entry_price - (1.5 × ATR14_1H)
```

Use the WIDER stop (further from entry) for safety.

---

### Rule ID: LONG-010
**Name**: Take Profit (Long)

```
risk_distance = entry_price - stop_price  (positive value)
take_profit = entry_price + (2.0 × risk_distance)
```

Minimum R:R = 2.0. Disqualify if not achievable.

---

### Rule ID: LONG-011
**Name**: Setup Expiration (Long)

```
Long setup expires if:
  1. Retest does not occur within 4 hours of sweep candle close
  2. Entry trigger does not fire within 4 hours of retest
  3. BTC regime changes from BULLISH
  4. A new 24H low is made (invalidates sweep)
```

---

## SECTION 6 — SIGNAL STATE MACHINE

```
DETECTED   — Initial conditions met (pump/dump + RSI + EMA extension)
    ↓
WATCHING   — Waiting for 24H high/low interaction + rejection candle
    ↓
ARMED      — Rejection confirmed; waiting for retest
    ↓
TRIGGERED  — Entry trigger candle closed; order to be placed at next open
    ↓
ACTIVE     — Position is open (paper or live)
    ↓
TP_HIT     — Take profit reached (terminal)
SL_HIT     — Stop loss reached (terminal)
EXPIRED    — Setup expired before entry (terminal)
CANCELLED  — BTC regime change or invalidation event (terminal)
```

**Rules**:
- Only TRIGGERED → ACTIVE requires exchange interaction
- State transitions are irreversible (no going back to prior state)
- All state transitions must be logged with timestamp and reason

---

## SECTION 7 — RISK ENGINE

### Rule ID: RISK-001
**Name**: Fixed Dollar Risk Per Trade

**[AMB-023 RESOLUTION]**: Risk per trade = $5.00 USD fixed.

```
risk_usd = 5.00
```

### Rule ID: RISK-002
**Name**: Position Sizing

```
risk_distance_pct = |entry_price - stop_price| / entry_price
position_size_usd = risk_usd / risk_distance_pct
qty = position_size_usd / entry_price

# Then round to exchange precision for the symbol
# Then verify qty >= minimum order size for the symbol
# If qty < minimum: DISQUALIFY (log WARNING)
```

### Rule ID: RISK-003
**Name**: Fee Inclusion

**[AMB-026 RESOLUTION]**:

```
taker_fee = 0.00055  (0.055% per side)
fee_cost_usd = qty * entry_price * taker_fee * 2  (entry + exit)
effective_risk_usd = risk_usd + fee_cost_usd
```

### Rule ID: RISK-004
**Name**: Slippage Assumption

**[AMB-027 RESOLUTION]**:

```
slippage = 0.0005  (0.05% per fill)
slippage_cost_usd = qty * entry_price * slippage * 2
```

### Rule ID: RISK-005
**Name**: Daily Trade Limit

**[AMB-024, AMB-025 RESOLUTION]**:

```
max_trades_per_day = 5
daily_loss_limit_usd = -25.00
daily_profit_lock_usd = +50.00

Rules:
  - If trades_today >= max_trades_per_day: NO NEW SETUPS
  - If daily_pnl <= daily_loss_limit_usd: NO NEW SETUPS (day is done)
  - If daily_pnl >= daily_profit_lock_usd: NO NEW SETUPS (lock profits)
```

**Day boundary**: UTC midnight.

### Rule ID: RISK-006
**Name**: Risk Engine Failure Behavior

```
If any risk engine calculation fails or returns an error:
  Action: NO TRADE
  Log: ERROR with full context
  Alert: Send system alert to operators
```

### Rule ID: RISK-007
**Name**: Duplicate Signal Prevention

```
A new signal for symbol X is rejected if:
  - An ACTIVE position exists for symbol X, OR
  - A setup in state ARMED or TRIGGERED exists for symbol X
```

---

## SECTION 8 — A+ SCORING MODEL

### Rule ID: SCORE-001
**Name**: A+ Score Calculation
**Purpose**: Rank setup quality objectively. Only setups with score >= 80 are A+ grade.

**Scoring Criteria** (total possible = 100 points):

| Criteria | Points | Condition |
|---|---|---|
| BTC regime alignment | 20 | BULLISH (for long) or BEARISH (for short) — always true if setup exists |
| 24H move magnitude | 15 | >= 12%: 15pts; >= 10%: 10pts; >= 8%: 5pts |
| RSI extreme | 15 | >= 80 or <= 20: 15pts; >= 77 or <= 23: 10pts; >= 75 or <= 25: 5pts |
| EMA extension | 10 | >= 5%: 10pts; >= 4%: 7pts; >= 3%: 5pts |
| Sweep depth (long) / High excess (short) | 10 | >= 0.5%: 10pts; >= 0.25%: 5pts; >= 0.1%: 2pts |
| Rejection candle quality | 10 | Wick >= 2× body: 10pts; wick >= 1.5× body: 5pts |
| Volume confirmation | 10 | Rejection candle volume > 1.5× 20-period avg: 10pts; > 1.2×: 5pts |
| R:R ratio | 10 | >= 3:1: 10pts; >= 2.5:1: 7pts; >= 2:1: 5pts |

**Threshold**: Score >= 80 = A+ setup (proceed). Score < 80 = DISQUALIFY.

**[AMB-028 RESOLUTION]**: Minimum score for alert/paper trade = 80/100.

---

## SECTION 9 — INDICATOR DEFINITIONS

### EMA (Exponential Moving Average)

```
EMA(period, close)[0] = close[0]  (seed with first close)
EMA(period, close)[i] = close[i] * k + EMA[i-1] * (1 - k)
where k = 2 / (period + 1)
Periods used: 7, 14, 28
```

### RSI (Relative Strength Index)

```
Method: Wilder's Smoothing (not SMA-based)
Period: 14
RS = avg_gain / avg_loss  (Wilder's)
RSI = 100 - (100 / (1 + RS))
Warmup required: minimum 28 closed candles (2× period)
```

### ATR (Average True Range)

```
TR = MAX(high - low, |high - prev_close|, |low - prev_close|)
ATR = Wilder's smoothing of TR over 14 periods
Period: 14
Warmup: minimum 28 closed candles
```

---

## SECTION 10 — SIGNAL EXPIRATION SUMMARY

| Setup Phase | Expiration Rule |
|---|---|
| DETECTED → WATCHING | 4H (no rejection within 4 candles of initial detection) |
| ARMED (post-rejection) | 4H (no retest within 4 candles) |
| TRIGGERED | 1H (entry must execute within 1 candle open) |
| Any phase | BTC regime change → CANCELLED |
| Any phase | New 24H high (short) or new 24H low (long) → CANCELLED |

---

## SECTION 11 — GATE-1 APPROVAL RECORD

**GATE-1 STATUS: ✅ APPROVED**
**Approved by: Human**
**Date: 2026-08-31**
**Effect: Implementation of T002 and all subsequent tasks may proceed.**

All 28 ambiguity resolutions confirmed. The following decisions are now **IMMUTABLE** without a
formal Strategy Change Proposal (see AGENTS.md Article 6):

| Decision | Approved Value |
|---|---|
| BTC regime primary timeframe | 4H candles |
| BTC regime confirmation timeframe | 1H candles |
| Neutral zone | ±1.5% 24H change |
| Pump threshold (short) | >= +8% 24H change |
| Dump threshold (long) | <= -8% 24H change |
| RSI overbought (short) | RSI(14) >= 75 |
| RSI oversold (long) | RSI(14) <= 25 |
| EMA7 extension | >= 3% from EMA7 (either direction) |
| Stop method | MAX(structural, 1.5×ATR14) |
| Minimum R:R | 2.0:1 |
| Setup expiration | 4 hours from DETECTED |
| Multiple setups | Allowed to daily limit; score-ranked |
| Daily loss limit | -$25.00 USD |
| Daily profit lock | +$50.00 USD |
| A+ score threshold | >= 80 / 100 |
| Risk per trade | $5.00 USD fixed |
| Fees | 0.055% taker × 2 sides |
| Slippage | 0.05% × 2 sides |
| Candle confirmation | Closed candles ONLY |
| Setup timeframe | 1H |
| Symbol universe | Bybit USDT linear perps, 24H vol >= $50M |

---

*End of STRATEGY_SPEC.md v1.0 — GATE-1 APPROVED 2026-08-31*
*This document is the canonical strategy definition. No implementation may deviate from these rules.*
*Any modification requires a Strategy Change Proposal approved by a human.*
