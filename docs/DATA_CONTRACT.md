# DATA_CONTRACT.md — A+ Scanner Data Contract
# Version: 1.0 (GATE-1 APPROVED)
# Authority: Lead CTO
# Last Updated: 2026-08-31

---

## 1. OVERVIEW

This document defines every data field consumed by the A+ Scanner, its source, required freshness, and failure semantics.

All data must be validated before entering the strategy pipeline. Invalid or stale data must never silently produce signals.

---

## 2. DATA SOURCE

**Exchange**: Bybit USDT Linear Perpetuals (production endpoint: `https://api.bybit.com`)

**Testnet**: `https://api-testnet.bybit.com` (used during development/testing ONLY)

**WebSocket**: `wss://stream.bybit.com/v5/public/linear`

---

## 3. CANDLE DATA FIELDS

### 3.1 OHLCV Candle Schema

```
Field           Type        Source          Required
──────────────────────────────────────────────────────
symbol          str         API             REQUIRED
timeframe       str         API             REQUIRED  (e.g., "60" = 1H, "240" = 4H)
open_time       datetime    API (UTC ms)    REQUIRED
open            Decimal     API             REQUIRED
high            Decimal     API             REQUIRED
low             Decimal     API             REQUIRED
close           Decimal     API             REQUIRED
volume          Decimal     API (contracts) REQUIRED
turnover        Decimal     API (USDT)      REQUIRED
is_closed       bool        Derived         REQUIRED  — only True candles enter strategy
```

### 3.2 Timeframes Used

| Timeframe | API Code | Purpose |
|---|---|---|
| 1H | "60" | Primary setup detection (all altcoins) |
| 4H | "240" | BTC regime classification |

### 3.3 Candle Types — Critical Distinction

```
HISTORICAL CANDLE:   Fetched from REST API, fully closed, used for warmup
CONFIRMED CANDLE:    Closed candle (is_closed=True), safe for strategy evaluation
FORMING CANDLE:      Current incomplete candle (is_closed=False) — NEVER used in strategy
REAL-TIME TICK:      WebSocket kline update — ONLY used to update forming candle state
```

**Rule**: Strategy logic must ONLY consume candles where `is_closed=True`.

**Enforcement**: Every strategy method must assert `candle.is_closed == True` at entry.

---

## 4. INDICATOR DATA FIELDS

### 4.1 EMA Fields

```
Field           Type        Computed From   Timeframe   Warmup
──────────────────────────────────────────────────────────────────
ema7            Decimal     close prices    1H, 4H      14 candles min
ema14           Decimal     close prices    1H, 4H      28 candles min
ema28           Decimal     close prices    1H, 4H      56 candles min
```

**Method**: Exponential moving average with multiplier k = 2/(period+1)
**Seed**: First close value as initial EMA seed

### 4.2 RSI Field

```
Field           Type        Computed From   Timeframe   Warmup
─────────────────────────────────────────────────────────────────
rsi14           float       close prices    1H          28 candles min (2× period)
```

**Method**: Wilder's smoothing (not simple moving average)
**Range**: 0.0 – 100.0 (exclusive boundaries technically; treat 0/100 as extreme)

### 4.3 ATR Field

```
Field           Type        Computed From   Timeframe   Warmup
─────────────────────────────────────────────────────────────────
atr14           Decimal     OHLC prices     1H          28 candles min
```

**Method**: Wilder's smoothing of True Range
**True Range**: MAX(H-L, |H-prev_C|, |L-prev_C|)

### 4.4 24H Statistics Fields

```
Field               Type        Source          Window
─────────────────────────────────────────────────────────────────
high_24h            Decimal     Computed        Rolling 24H (24 × 1H candles)
low_24h             Decimal     Computed        Rolling 24H (24 × 1H candles)
change_pct_24h      float       Computed        (close_now - close_24h_ago) / close_24h_ago × 100
volume_24h_usd      Decimal     Computed        Sum of turnover over 24H
```

**IMPORTANT**: `high_24h` and `low_24h` are computed from the 24 most recently CLOSED candles.
The forming (current) candle is EXCLUDED from 24H statistics.

**Backtest compliance**: In backtest mode, 24H stats use ONLY data available at the time of
the candle being evaluated. Future candles are NEVER accessed.

### 4.5 Volume Fields

```
Field               Type        Source          Purpose
─────────────────────────────────────────────────────────────────
volume_current      Decimal     Candle.volume   Current closed candle volume
volume_avg_20       Decimal     Computed        20-period simple average of volume
volume_ratio        float       Computed        volume_current / volume_avg_20
```

---

## 5. SYMBOL METADATA FIELDS

These fields are fetched from the Bybit instruments info endpoint:

```
Field               Type        Source              Usage
─────────────────────────────────────────────────────────────────────────
symbol              str         Bybit instruments   Symbol identifier
base_coin           str         Bybit instruments   e.g., "BTC"
quote_coin          str         Bybit instruments   e.g., "USDT"
status              str         Bybit instruments   Must be "Trading"
tick_size           Decimal     Bybit instruments   Minimum price movement (for stop/TP rounding)
lot_size            Decimal     Bybit instruments   Minimum quantity increment
min_order_qty       Decimal     Bybit instruments   Minimum order size (disqualify if below)
max_leverage        float       Bybit instruments   Max available leverage
contract_type       str         Bybit instruments   Must be "LinearPerpetual"
```

---

## 6. ORDER BOOK DATA

Order book data is NOT required for v1.0 of the scanner.

It may be added in a future version for:
- Spread estimation
- Slippage modeling
- Liquidity depth verification

**[AMB-FUTURE]**: Order book integration is deferred. Document in TASK_GRAPH as a future enhancement.

---

## 7. DATA FRESHNESS REQUIREMENTS

| Data Type | Maximum Age | On Staleness |
|---|---|---|
| 1H candle (current symbol) | 65 minutes | Skip symbol; log WARNING |
| 4H BTC candle (regime) | 245 minutes | Regime = UNDEFINED; halt all scanning |
| Symbol universe | 25 hours | Use previous list; log WARNING |
| Symbol metadata | 25 hours | Use cached; log WARNING |
| 24H stats | 65 minutes | Skip symbol; log WARNING |

---

## 8. DATA VALIDATION RULES

Every candle entering the **strategy pipeline** must pass:

```python
# Required validations (applied at strategy pipeline entry — T008+):
assert candle.is_closed == True   # ← strategy pipeline only; NOT transport layer
assert candle.open > 0
assert candle.high >= candle.open
assert candle.high >= candle.close
assert candle.low <= candle.open
assert candle.low <= candle.close
assert candle.low <= candle.high
assert candle.volume >= 0
assert candle.turnover >= 0
assert candle.open_time is not None
```

> **Scope of `is_closed == True`:**
> This rule applies at the **strategy pipeline entry** (T008+) and in the REST client
> (which only returns closed candles). It does NOT apply to the WebSocket transport
> layer (T004). The WS client receives and emits both forming (`is_closed=False`) and
> closed (`is_closed=True`) candles faithfully. CandleStore (T005) is responsible for
> filtering forming candles before passing to strategy modules.

**On validation failure**: Discard candle, do not generate signal.

**Log severity** (read §8 and §10 together — §10 overrides for specific cases):

| Failure | Log Level | Applies To |
|---|---|---|
| Price = 0 or negative | CRITICAL | Transport + strategy pipeline |
| OHLC violation (high < low, etc.) | CRITICAL | Transport + strategy pipeline |
| Any other §8 validation failure | ERROR | Transport + strategy pipeline |
| Parse/normalization failure (bad row shape) | WARNING | Transport + strategy pipeline |
| `is_closed == False` at strategy pipeline entry | ERROR | Strategy pipeline only (not WS transport) |

---

## 9. HISTORICAL DATA REQUIREMENTS

For reliable indicator computation:

```
Minimum history per symbol:
  1H timeframe: 100 closed candles (for indicator warmup + 24H stats)
  4H timeframe: 60 closed candles (for BTC regime EMA stack)

Recommended history for backtest:
  1H timeframe: 2000+ candles (~83 days)
  4H timeframe: 500+ candles (~83 days)
```

---

## 10. DATA FAILURE MODES AND RESPONSES

| Failure Mode | Detection | Response |
|---|---|---|
| REST API timeout | HTTP timeout > 10s | Retry × 3 with exponential backoff; fall back to WebSocket |
| WebSocket disconnect | No message > 30s | Reconnect with exponential backoff; request REST candle fill |
| Missing candle (gap) | Gap > 1 candle duration | Log ERROR; disqualify symbol for current scan cycle |
| Price = 0 or negative | Validation | Discard; log CRITICAL |
| OHLC violation (H < L) | Validation | Discard; log CRITICAL |
| BTC data unavailable | Freshness check | Regime = UNDEFINED; NO TRADE |
| Rate limit exceeded | HTTP 429 | Backoff per Bybit spec; log WARNING |

---

## 11. BACKTEST vs LIVE DATA DISTINCTION

```
In live mode:
  - Data comes from WebSocket (real-time) + REST (historical fill)
  - is_closed is set by WebSocket "confirm" flag
  - Forming candle is tracked but never used in strategy

In backtest mode:
  - All data comes from historical files or REST API
  - Every candle in sequence is treated as "just closed"
  - The engine processes candles strictly sequentially (t=0, t=1, t=2, ...)
  - At candle t, only candles [0..t] are visible — NEVER candle [t+1..N]
  - 24H stats at candle t use candles [t-24..t-1] (not including t's data)
```

---

*End of DATA_CONTRACT.md v0.1-DRAFT*

