# TASK_GRAPH.md — A+ Scanner Development Task Graph
# Version: 0.1-DRAFT
# Authority: Lead CTO
# Last Updated: 2026-08-31

---

## DEPENDENCY LEGEND

```
A → B         B depends on A (A must complete before B starts)
A ⇒ B         B depends on A but may start in parallel with A's testing phase
A ∥ B         A and B may execute in parallel
[GATE-N]      Human approval required before proceeding past this point
```

## TASK STATUS LEGEND

```
[ ] Not started
[/] In progress
[x] Complete (APPROVED)
[!] Blocked
[~] APPROVED_WITH_FIXES
```

---

## PHASE 0 — SPECIFICATION (CURRENT)

```
T001 Specification Audit + Strategy Spec        [CURRENT — this document is T001 output]
    Recommended Agent: Opus/Fable (CTO)
    Dependencies: MASTER_PROJECT_BRIEF.md
    Output: docs/STRATEGY_SPEC.md (v0.1-DRAFT)
    Status: [x] GATE-1 APPROVED 2026-08-31

                [GATE-1: ✅ APPROVED 2026-08-31 — Implementation may proceed]
```

---

## PHASE 1 — FOUNDATION

```
T002 Project Foundation  [x] APPROVED 2026-08-31`r`n    Recommended Agent: Codex`r`n    Dependencies: T001 + GATE-1
    Scope:
        - pyproject.toml / requirements.txt
        - src/scanner/ package skeleton
        - Configuration system (pydantic-settings or similar)
        - Structured logging setup
        - Environment variable handling (.env support)
        - SQLite database abstraction (initial)
        - pytest test framework setup
    Parallel with: (none — foundational)
    Output: Importable scanner package, passing pytest scaffold

T003 Market Data — Bybit REST Client
    Recommended Agent: Codex
    Dependencies: T002
    Scope:
        - BybitRESTClient class
        - Candle fetch (OHLCV)
        - Symbol info fetch
        - Rate limit handling
        - Retry logic with exponential backoff
        - Unit tests (mocked HTTP)
    Parallel with: T004 (after T002)
    Review Required: Gemini (API failure review)

T004 Market Data — Bybit WebSocket Client
    Recommended Agent: Codex
    Dependencies: T002
    Scope:
        - BybitWebSocketClient class
        - Subscribe to kline streams
        - Reconnect handling
        - Stale data detection
        - Unit tests (mocked WS)
    Parallel with: T003
    Review Required: Gemini (reliability review)

T005 Market Data — Candle Store + Universe Manager
    Recommended Agent: Codex
    Dependencies: T003 ∥ T004
    Scope:
        - CandleStore (in-memory ring buffer per symbol)
        - StaleDataDetector
        - UniverseManager (daily refresh, volume filter)
        - Integration: REST + WebSocket → CandleStore
    Parallel with: (serial after T003 and T004)
```

---

## PHASE 2 — INDICATORS

```
T006 Indicator Engine
    Recommended Agent: Codex
    Dependencies: T005
    Review Required: Sonnet (formula correctness audit)
    Scope:
        - EMA(7, 14, 28) — Wilder's exponential method
        - RSI(14) — Wilder's smoothing
        - ATR(14) — Wilder's smoothing
        - 24H High/Low/Change (rolling window)
        - Volume average (20-period)
        - warmup_complete flag
        - Comprehensive unit tests with reference values
    Output: IndicatorValues dataclass per symbol per timeframe
    Critical: Reference values from known external source must be used for unit tests

                [Sonnet must audit indicator formulas before T007 begins]
```

---

## PHASE 3 — BTC REGIME

```
T007 BTC Regime Classifier
    Recommended Agent: Codex
    Dependencies: T006
    Review Required: Sonnet + Gemini
    Scope:
        - RegimeClassifier class
        - BULLISH / BEARISH / NEUTRAL / UNDEFINED logic
        - EMA stack evaluation (4H)
        - 24H threshold evaluation
        - Staleness → UNDEFINED
        - Fail-safe: UNDEFINED → halt scanning
        - Unit tests (all regime scenarios from TEST_SPEC REG-001 → REG-010)
    Output: Regime enum + classifier class
```

---

## PHASE 4 — STRATEGY MODULES

```
T008 Exhaustion Short Detector
    Recommended Agent: Codex
    Dependencies: T007
    Review Required: Sonnet (strategy compliance) + Gemini (edge cases)
    Scope:
        - ShortDetector class (stateless)
        - All SHORT-001 through SHORT-005 conditions
        - Rejection candle detection
        - Unit tests: SHT-001 → SHT-026 from TEST_SPEC
    MUST NOT: implement state machine logic
    Strategy compliance: verified against docs/STRATEGY_SPEC.md Section 4

T009 Exhaustion Long Detector
    Recommended Agent: Codex
    Dependencies: T007
    Review Required: Sonnet + Gemini
    Scope:
        - LongDetector class (stateless)
        - All LONG-001 through LONG-006 conditions
        - Sweep + reversal detection
        - Unit tests: mirror of short tests
    Parallel with: T008 (both depend only on T007)

T010 Signal State Machine
    Recommended Agent: Codex
    Dependencies: T008 ∥ T009
    Review Required: Sonnet + Gemini
    Scope:
        - SignalStateMachine class
        - All 9 states: DETECTED, WATCHING, ARMED, TRIGGERED, ACTIVE,
          TP_HIT, SL_HIT, EXPIRED, CANCELLED
        - Retest logic (SHORT-006, LONG-007)
        - Entry trigger logic (SHORT-007, LONG-008)
        - Expiration logic (SHORT-010, LONG-011)
        - BTC regime change → CANCELLED
        - State transition logging
        - Unit tests: SSM-001 → SSM-010
        - Replay tests: RPL-001 → RPL-008
```

---

## PHASE 5 — RISK AND SCORING

```
T011 Risk Engine
    Recommended Agent: Codex
    Dependencies: T010
    Review Required: Sonnet (formula audit) + Gemini (failure mode audit)
    Scope:
        - RiskEngine class
        - Position sizing formula (RISK_SPEC Section 2)
        - Fee + slippage calculation
        - Exchange precision rounding (floor for qty)
        - Daily session tracking (DailySession)
        - All halt conditions
        - Duplicate signal prevention
        - Failure → return None (never raise to caller)
        - Unit tests: RISK-001 → RISK-015
    Priority: Risk controls OVERRIDE strategy signals

T012 Scoring Engine
    Recommended Agent: Codex
    Dependencies: T010
    Review Required: Sonnet (scoring weights audit)
    Scope:
        - ScoringEngine class
        - 8-criteria scoring matrix (STRATEGY_SPEC Section 8)
        - Score breakdown dict
        - is_aplus flag (score >= 80)
        - Disqualification on score < 80
        - Unit tests for each scoring criterion
    Parallel with: T011
```

---

## PHASE 6 — ALERTING

```
T013 Alert Engine
    Recommended Agent: Codex
    Dependencies: T011 ∥ T012
    Scope:
        - TelegramAlerter class
        - DiscordAlerter class
        - Structured signal payload formatting
        - Failure isolation (alert failure must NOT crash scanner)
        - Unit tests (mocked HTTP)
    Review Required: Gemini (failure isolation review)
```

---

## PHASE 7 — BACKTEST ENGINE

```
T014 Backtest Engine
    Recommended Agent: Codex (implementation) + Sonnet (design review before coding)
    Dependencies: T010 ∥ T011 ∥ T012
    Review Required: Sonnet (look-ahead bias audit — MANDATORY) + Gemini
    Scope:
        - BacktestEngine class
        - Uses identical strategy/risk/scoring modules (no separate copy)
        - Sequential candle processing (oldest first)
        - 24H stats computed from past candles only
        - Entry fills at next candle open
        - Trade log with full state history
        - Equity curve generation
        - Performance metrics: win rate, avg R, max drawdown, Sharpe
        - Integrity tests: BIT-001 → BIT-006
    CRITICAL: Sonnet must sign off on no-look-ahead-bias before this task is APPROVED

                [GATE-2: Human reviews backtest engine validation results]
```

---

## PHASE 8 — PAPER TRADING

```
T015 Paper Trading Engine
    Recommended Agent: Codex
    Dependencies: T014 + GATE-2
    Review Required: Sonnet + Gemini
    Scope:
        - PaperTrader class
        - Simulated fills at next candle open
        - TP/SL hit detection on candle high/low
        - Fee + slippage simulation
        - Daily PnL tracking
        - Position persistence (survives restart)
        - Session summary reports
        - Unit tests: PPT-001 → PPT-005

                [GATE-3: Human approves paper trading start]
```

---

## PHASE 9 — OBSERVABILITY

```
T016 Observability Layer
    Recommended Agent: Codex
    Dependencies: T013 (can start after T013)
    Scope:
        - Structured JSON logging (all components)
        - Health check HTTP endpoint
        - Daily summary report (via alert channel)
        - Scanner status dashboard (terminal UI)
        - Component status tracking
    Review Required: Gemini (reliability)
    Parallel with: T015 (no dependency)
```

---

## PHASE 10 — INTEGRATION AND VALIDATION

```
T017 Integration Test Suite
    Recommended Agent: Codex (tests) + Gemini (review)
    Dependencies: All T001-T016 complete
    Scope:
        - End-to-end integration tests
        - Testnet data pipeline
        - Reliability tests: REL-001 → REL-010
        - Integration tests: INT-001 → INT-007
    Review Required: Gemini

T018 Full System Validation
    Recommended Agent: Sonnet (quant) + Gemini (adversarial)
    Dependencies: T017
    Scope:
        - Run backtest over 90 days of historical data
        - Audit for look-ahead bias
        - Statistical analysis of results
        - Risk-adjusted performance metrics
        - Edge case stress test
    Output: Validation report (reviews/sonnet/ + reviews/gemini/)
    CTO Final Review: reviews/opus/TASK_018_FINAL_REVIEW.md

                [GATE-3 confirmed after T018 passes]
```

---

## PARALLEL EXECUTION MAP

```
T001 (Spec Audit) → [GATE-1]
                        ↓
T002 (Foundation)
    ↓          ↓
T003          T004
(REST)        (WS)
    ↓          ↓
         T005 (CandleStore + Universe)
              ↓
         T006 (Indicators)
              ↓
         T007 (BTC Regime)
              ↓
         T008 ∥ T009
      (Short) ∥ (Long Detector)
              ↓
         T010 (State Machine)
              ↓
         T011 ∥ T012
       (Risk) ∥ (Scoring)
              ↓
         T013 (Alerts)   T014 (Backtest Engine)
              ↓                   ↓
              ↓____________T015 (Paper Trading)
                                  ↓
         T016 ∥ T017 (Observability ∥ Integration Tests)
                                  ↓
                           T018 (Full Validation)
                                  ↓
                              [GATE-3]
```

---

## AGENT ASSIGNMENT SUMMARY

| Task | Recommended Agent | Review Agent(s) |
|---|---|---|
| T001 | Opus/Fable (CTO) | Human (GATE-1) |
| T002 | Codex | Gemini |
| T003 | Codex | Gemini |
| T004 | Codex | Gemini |
| T005 | Codex | Gemini |
| T006 | Codex | **Sonnet** (formulas critical) |
| T007 | Codex | Sonnet + Gemini |
| T008 | Codex | Sonnet + Gemini |
| T009 | Codex | Sonnet + Gemini |
| T010 | Codex | Sonnet + Gemini |
| T011 | Codex | **Sonnet + Gemini** (risk critical) |
| T012 | Codex | Sonnet |
| T013 | Codex | Gemini |
| T014 | Codex | **Sonnet** (look-ahead bias critical) |
| T015 | Codex | Sonnet + Gemini |
| T016 | Codex | Gemini |
| T017 | Codex + Gemini | Sonnet |
| T018 | Sonnet + Gemini | Opus/Fable (CTO) |

---

*End of TASK_GRAPH.md v0.1-DRAFT*


