# SYSTEM_ARCHITECTURE.md — A+ Scanner System Architecture
# Version: 1.0 (GATE-1 APPROVED)
# Authority: Lead CTO
# Last Updated: 2026-08-31

---

## 1. DESIGN PHILOSOPHY

The A+ Scanner is designed around three core architectural principles:

1. **Strategy Independence**: Core strategy logic must be completely decoupled from execution, alerting, and data concerns. The same strategy module runs in backtesting, paper trading, and live scanning without modification.

2. **Fail-Safe by Default**: Every component that can fail must have a defined failure behavior. The default behavior on any failure is NO TRADE.

3. **HERMES/TradingOS Compatibility**: The scanner is designed as a standalone module with clean external interfaces. Future integration into the TradingOS/HERMES multi-agent system requires only an adapter layer.

---

## 2. COMPONENT MAP

```
┌─────────────────────────────────────────────────────────────────┐
│                        A+ SCANNER                               │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │  Market Data │    │   BTC Regime │    │ Symbol Universe  │  │
│  │   Module     │───▶│   Classifier │    │   Manager        │  │
│  └──────┬───────┘    └──────┬───────┘    └────────┬─────────┘  │
│         │                  │                      │            │
│         ▼                  ▼                      ▼            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   Indicator Engine                        │  │
│  │           EMA7, EMA14, EMA28, RSI14, ATR14               │  │
│  │              24H High/Low/Change, Volume                  │  │
│  └──────────────────────────┬───────────────────────────────┘  │
│                             │                                   │
│              ┌──────────────┴───────────────┐                  │
│              ▼                              ▼                   │
│  ┌───────────────────┐          ┌────────────────────┐         │
│  │  Exhaustion Short │          │  Exhaustion Long   │         │
│  │  Detector         │          │  Detector          │         │
│  └─────────┬─────────┘          └──────────┬─────────┘         │
│            └──────────────┬───────────────-┘                   │
│                           ▼                                     │
│              ┌────────────────────────┐                         │
│              │  Signal State Machine  │                         │
│              │  DETECTED→WATCHING→    │                         │
│              │  ARMED→TRIGGERED→      │                         │
│              │  ACTIVE/TP/SL/EXPIRED  │                         │
│              └────────────┬───────────┘                         │
│                           │                                     │
│              ┌────────────┴───────────┐                         │
│              ▼                        ▼                         │
│  ┌───────────────────┐    ┌──────────────────────┐             │
│  │   Scoring Engine  │    │    Risk Engine        │             │
│  │   (A+ Score)      │    │  (Position Sizing,    │             │
│  └─────────┬─────────┘    │   Daily Limits, Fees) │             │
│            └──────┬───────┴────────┬──────────────┘             │
│                   ▼               ▼                             │
│       ┌───────────────┐  ┌────────────────────┐                │
│       │ Alert Engine  │  │  Execution Layer   │                │
│       │ Telegram/     │  │  (Paper / Future   │                │
│       │ Discord       │  │   Live)            │                │
│       └───────────────┘  └─────────┬──────────┘                │
│                                    ▼                            │
│                     ┌──────────────────────────┐               │
│                     │   Persistence Layer       │               │
│                     │   (SQLite / PostgreSQL)   │               │
│                     └──────────────────────────┘               │
│                                                                 │
│  ┌────────────────────────────────────────────────────────┐    │
│  │              Observability Layer                        │    │
│  │         Logging | Metrics | Health | Dashboard          │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌────────────────────────────────────────────────────────┐    │
│  │              Backtest Engine                            │    │
│  │   (uses same Strategy modules, isolated data feed)     │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. MODULE SPECIFICATIONS

### 3.1 Market Data Module

**Responsibility**: Fetch, validate, normalize, and serve OHLCV data.

**Sub-components**:
- `BybitRESTClient`: Historical candle fetching, symbol info, rate limiting
- `BybitWebSocketClient`: Real-time candle streaming, reconnect handling
- `CandleStore`: In-memory + persistent candle buffer per symbol
- `StaleDataDetector`: Monitors candle freshness; raises alerts on staleness

**Interfaces**:
```python
class MarketDataProvider(Protocol):
    def get_candles(symbol: str, timeframe: str, limit: int) -> list[Candle]: ...
    def get_latest_candle(symbol: str, timeframe: str) -> Candle | None: ...
    def get_24h_stats(symbol: str) -> Stats24H: ...
    def is_fresh(symbol: str, timeframe: str, max_age_seconds: int) -> bool: ...
```

**Data Types**:
```python
@dataclass
class Candle:
    symbol: str
    timeframe: str
    open_time: datetime  # UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal
    is_closed: bool  # MUST be True before strategy use

@dataclass
class Stats24H:
    symbol: str
    high_24h: Decimal
    low_24h: Decimal
    change_pct_24h: float
    volume_24h_usd: Decimal
    timestamp: datetime
```

**Failure Behavior**: On data fetch failure, mark data as stale. Strategy components receive `is_fresh=False` and must refuse to generate signals.

---

### 3.2 Symbol Universe Manager

**Responsibility**: Maintain the list of eligible trading symbols.

**Interface**:
```python
class UniverseManager(Protocol):
    def get_active_symbols() -> list[str]: ...
    def refresh() -> None: ...
    def is_eligible(symbol: str) -> bool: ...
```

**Logic**: Refreshes daily (UTC 00:05). Falls back to prior list on failure.

---

### 3.3 Indicator Engine

**Responsibility**: Calculate all technical indicators from raw candle data.

**Indicators**:
- EMA(7), EMA(14), EMA(28) — exponential moving averages (all timeframes)
- RSI(14) — Wilder's smoothing method
- ATR(14) — Wilder's smoothing method
- 24H high, 24H low, 24H change
- Rolling volume average (20-period)

**Interface**:
```python
class IndicatorSet(Protocol):
    def compute(candles: list[Candle]) -> IndicatorValues: ...

@dataclass
class IndicatorValues:
    symbol: str
    timeframe: str
    timestamp: datetime
    ema7: Decimal
    ema14: Decimal
    ema28: Decimal
    rsi14: float
    atr14: Decimal
    high_24h: Decimal
    low_24h: Decimal
    change_24h_pct: float
    volume_avg_20: Decimal
    current_volume: Decimal
    warmup_complete: bool  # False if insufficient candles
```

**Rule**: Strategy components must check `warmup_complete == True` before using indicator values.

---

### 3.4 BTC Regime Classifier

**Responsibility**: Classify current BTC market regime as BULLISH, BEARISH, or NEUTRAL.

**Interface**:
```python
class RegimeClassifier(Protocol):
    def classify(btc_indicators: IndicatorValues, btc_4h_candle: Candle) -> Regime: ...

class Regime(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    UNDEFINED = "UNDEFINED"  # data failure
```

**Evaluation**: On every closed 4H BTC candle.

**Failure Behavior**: If BTC data is unavailable → `UNDEFINED` → scanner halts all signal generation.

---

### 3.5 Exhaustion Short Detector

**Responsibility**: Evaluate individual symbols for short setup conditions.

**Inputs**: IndicatorValues (1H), Stats24H, current Regime

**Output**: `SetupCandidate | None`

**Logic** (stateless — processes one symbol per call):
```
Check: REGIME == BEARISH
Check: 24H change >= +8%
Check: RSI14 >= 75
Check: EMA7 extension >= 3%
Check: 24H high proximity <= 0.5%
→ If all pass: return SetupCandidate(direction=SHORT, state=DETECTED)
```

---

### 3.6 Exhaustion Long Detector

**Responsibility**: Mirror of Short Detector for long setups.

**Logic**:
```
Check: REGIME == BULLISH
Check: 24H change <= -8%
Check: RSI14 <= 25
Check: EMA7 extension >= 3% (below EMA7)
Check: 24H low proximity <= 0.5%
→ If all pass: return SetupCandidate(direction=LONG, state=DETECTED)
```

---

### 3.7 Signal State Machine

**Responsibility**: Track every active setup through its lifecycle states.

**States**: `DETECTED → WATCHING → ARMED → TRIGGERED → ACTIVE → [TP_HIT | SL_HIT | EXPIRED | CANCELLED]`

**Interface**:
```python
class SignalStateMachine(Protocol):
    def process(signal: Signal, new_candle: Candle, regime: Regime) -> Signal: ...
    def get_active_signals() -> list[Signal]: ...
    def cancel_all(reason: str) -> None: ...

@dataclass
class Signal:
    id: UUID
    symbol: str
    direction: Direction
    state: SignalState
    detected_at: datetime
    entry_price: Decimal | None
    stop_price: Decimal | None
    tp_price: Decimal | None
    score: int | None
    expiration_time: datetime
    state_history: list[StateTransition]
```

---

### 3.8 Scoring Engine

**Responsibility**: Calculate A+ score for a setup. Disqualify if score < 80.

**Interface**:
```python
class ScoringEngine(Protocol):
    def score(candidate: SetupCandidate, indicators: IndicatorValues) -> ScoredSetup: ...

@dataclass
class ScoredSetup:
    setup: SetupCandidate
    score: int  # 0-100
    breakdown: dict[str, int]
    is_aplus: bool  # score >= 80
```

---

### 3.9 Risk Engine

**Responsibility**: Calculate position size, validate limits, and gate all trade execution.

**Interface**:
```python
class RiskEngine(Protocol):
    def calculate(signal: Signal) -> RiskCalculation | None: ...
    def can_trade(session: TradingSession) -> bool: ...

@dataclass
class RiskCalculation:
    symbol: str
    direction: Direction
    entry_price: Decimal
    stop_price: Decimal
    tp_price: Decimal
    qty: Decimal  # exchange-rounded
    risk_usd: Decimal
    fee_usd: Decimal
    slippage_usd: Decimal
    total_cost_usd: Decimal
    rr_ratio: float
```

**Failure Behavior**: Any exception → return None → NO TRADE.

---

### 3.10 Alert Engine

**Responsibility**: Send structured signal notifications.

**Channels**: Telegram, Discord (extensible)

**Payload** (structured):
```
SYMBOL | DIRECTION | SCORE
Entry: $X.XX
Stop:  $X.XX (X.X%)
Target: $X.XX (X.X%)
R:R: X.X:1
Risk: $X.XX | Size: X.X contracts
BTC Regime: BEARISH/BULLISH
Setup: Exhaustion Short/Long
```

**Failure Behavior**: Log error, continue scanning. Alert failure MUST NOT stop the scanner.

---

### 3.11 Paper Trading Engine

**Responsibility**: Simulate trade execution without exchange connection.

**Simulates**: Entry fills, TP/SL exits, fees (0.055% taker × 2 sides), slippage (0.05%)

**Tracking**: Open positions, closed positions, daily PnL, running equity curve

**Interface**:
```python
class PaperTrader(Protocol):
    def open_position(risk: RiskCalculation, candle: Candle) -> PaperPosition: ...
    def update(position: PaperPosition, candle: Candle) -> PaperPosition: ...
    def get_session_summary() -> SessionSummary: ...
```

---

### 3.12 Backtest Engine

**Responsibility**: Replay historical candles through the strategy pipeline.

**Critical Requirements**:
- Uses identical strategy module code as live scanner
- No lookahead bias — processes candles sequentially, oldest first
- 24H high/low computed from data available AT THAT CANDLE, not future data
- Simulates realistic fills (next-candle open)
- Records full signal history with state transitions
- Produces equity curve, trade log, and performance metrics

**Interface**:
```python
class BacktestEngine(Protocol):
    def run(
        symbols: list[str],
        start: datetime,
        end: datetime,
        data_source: HistoricalDataProvider
    ) -> BacktestResult: ...
```

---

### 3.13 Persistence Layer

**Responsibility**: Store signals, trades, candle cache, configuration, and audit logs.

**Primary storage**: SQLite (development), PostgreSQL (production-ready)

**Tables**:
- `signals` — full signal lifecycle with state history
- `trades` — paper and (future) live trade records
- `candle_cache` — persisted candle buffer
- `daily_sessions` — daily risk tracking (PnL, trade count)
- `audit_log` — all state transitions and decisions

---

### 3.14 Observability Layer

**Responsibility**: Health monitoring, structured logging, metrics, dashboard.

**Components**:
- Structured JSON logging (no raw print statements)
- Health endpoint (HTTP) — reports component status
- Daily summary report (via alert channels)
- Scanner status dashboard (terminal UI or web)

---

## 4. DATA FLOW

```
1. Market Data Module fetches candles (WebSocket + REST fallback)
2. Indicator Engine computes indicators for all active symbols
3. BTC Regime Classifier evaluates BTC/USDT 4H
4. If NEUTRAL or UNDEFINED → skip all setup scanning
5. Universe Manager provides eligible symbol list
6. For each eligible symbol:
   a. Short Detector evaluates (if BEARISH)
   b. Long Detector evaluates (if BULLISH)
   c. New candidates enter Signal State Machine
7. Signal State Machine processes all active signals against new candle
8. Scoring Engine scores new DETECTED candidates
9. Candidates with score < 80 are DISQUALIFIED
10. Risk Engine validates TRIGGERED signals
11. Alert Engine sends notifications for TRIGGERED signals
12. Paper Trader executes simulated trades
13. Persistence Layer records everything
14. Observability Layer reports health
```

---

## 5. HERMES/TRADINGOS INTEGRATION DESIGN

The scanner exposes a clean event-based interface for future integration:

```python
class ScannerEventBus(Protocol):
    def on_signal_detected(callback: Callable[[Signal], None]) -> None: ...
    def on_signal_triggered(callback: Callable[[Signal, RiskCalculation], None]) -> None: ...
    def on_signal_cancelled(callback: Callable[[Signal, str], None]) -> None: ...
    def on_regime_change(callback: Callable[[Regime, Regime], None]) -> None: ...
```

The HERMES orchestrator subscribes to these events. The scanner has no knowledge of HERMES internals.

---

## 6. PROJECT DIRECTORY STRUCTURE (Target)

```
a-plus-scanner/
├── AGENTS.md
├── MASTER_PROJECT_BRIEF.md
├── docs/
│   ├── STRATEGY_SPEC.md
│   ├── SYSTEM_ARCHITECTURE.md
│   ├── DATA_CONTRACT.md
│   ├── RISK_SPEC.md
│   ├── TEST_SPEC.md
│   ├── TASK_GRAPH.md
│   └── CHANGELOG.md
├── src/
│   └── scanner/
│       ├── __init__.py
│       ├── config.py
│       ├── market_data/
│       │   ├── __init__.py
│       │   ├── bybit_rest.py
│       │   ├── bybit_ws.py
│       │   ├── candle_store.py
│       │   └── models.py
│       ├── indicators/
│       │   ├── __init__.py
│       │   ├── ema.py
│       │   ├── rsi.py
│       │   ├── atr.py
│       │   └── stats24h.py
│       ├── regime/
│       │   ├── __init__.py
│       │   └── classifier.py
│       ├── strategy/
│       │   ├── __init__.py
│       │   ├── short_detector.py
│       │   ├── long_detector.py
│       │   ├── state_machine.py
│       │   └── models.py
│       ├── scoring/
│       │   ├── __init__.py
│       │   └── engine.py
│       ├── risk/
│       │   ├── __init__.py
│       │   └── engine.py
│       ├── alerts/
│       │   ├── __init__.py
│       │   ├── telegram.py
│       │   └── discord.py
│       ├── execution/
│       │   ├── __init__.py
│       │   └── paper_trader.py
│       ├── backtest/
│       │   ├── __init__.py
│       │   └── engine.py
│       ├── persistence/
│       │   ├── __init__.py
│       │   ├── database.py
│       │   └── models.py
│       └── observability/
│           ├── __init__.py
│           ├── logging.py
│           ├── health.py
│           └── metrics.py
├── tests/
│   ├── unit/
│   ├── strategy/
│   ├── risk/
│   ├── integration/
│   └── backtest/
├── tasks/
│   ├── active/
│   ├── completed/
│   └── rejected/
├── reviews/
│   ├── opus/
│   ├── sonnet/
│   └── gemini/
├── skills/
├── pyproject.toml
└── README.md
```

---

*End of SYSTEM_ARCHITECTURE.md v0.1-DRAFT*

