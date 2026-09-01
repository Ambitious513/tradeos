# STRATEGY_V1_1_IMPACT_REPORT.md
# A+ Scanner — v1.1 Feature Expansion Change Impact Report
# Authority: Lead CTO (Opus/Fable)
# Date: 2026-09-01
# Status: PENDING HUMAN APPROVAL
# Source Document: "A+ Scanner v1.1 — Additional Setup Specs" (provided by Human)

---

> **PROTECTED PROCESS**
> This document is the output of a formal Change Impact Review per AGENTS.md Article 6.
> No implementation may proceed until all items marked "REQUIRES HUMAN APPROVAL" are resolved.

---

## EXECUTIVE SUMMARY

v1.1 introduces three scan modes (SHORT_EXHAUSTION / LONG_PULLBACK / RANGE_GRID) gated
by BTC regime. It is architecturally sound and directionally correct. However it contains:

- **4 items requiring Human Approval** (risk model, R:R floor, NEUTRAL-regime trading,
  LONG setup replacement)
- **15 items requiring CTO clarification** (ambiguities that cannot be resolved by
  inference alone)
- **0 items that can proceed to implementation immediately**

CODEX HANDOFF: **NOT READY** until blocking items resolved.

---

## SECTION 1 — CLASSIFICATION TABLE

| Change Area | Classification | Human Approval Required? |
|---|---|---|
| ModeSelector module (new) | ARCHITECTURE CHANGE | NO — after strategy approved |
| NEUTRAL regime → active trade (RANGE_GRID) | STRATEGY CHANGE | YES |
| LONG_EXHAUSTION → LONG_PULLBACK in BULLISH | STRATEGY CHANGE | YES |
| BTC regime definition (mixed EMA + 24H edge case) | CLARIFICATION REQUIRED | YES (after clarified) |
| RANGE_GRID setup rules | STRATEGY CHANGE (new rules) | YES |
| LONG_PULLBACK setup rules | STRATEGY CHANGE (new rules) | YES |
| Risk model: $5 fixed → % account | RISK CHANGE | YES (GATE-5) |
| R:R: global 2.0 floor → 1.0-1.2 for Grid | RISK CHANGE | YES (GATE-5) |
| Max 2 positions per coin | RISK CHANGE | YES |
| Scoring: new mode-specific criteria | STRATEGY CHANGE | YES |
| RSI6 indicator | ARCHITECTURE CHANGE + CLARIFICATION | YES (after clarified) |
| ATR% definition | CLARIFICATION REQUIRED | NO (after clarified) |
| Range calculation (7D 4H lookback) | ARCHITECTURE CHANGE | NO — after strategy approved |
| Listing filter 48H | STRATEGY CHANGE | YES (minor — replaces 24H) |
| Alert schema extensions | ARCHITECTURE CHANGE | NO |
| Task graph restructure | TASK GRAPH CHANGE | NO (CTO authority) |

---

## SECTION 2 — CONFLICT ANALYSIS

---

### CONFLICT-001 — BTC Regime: NEUTRAL is now an ACTIVE trade zone

**SEVERITY: CRITICAL — STRATEGY CHANGE**

| | Current (v1.0 APPROVED) | Proposed (v1.1) |
|---|---|---|
| Rule | REGIME-001: NEUTRAL = any condition not satisfying BULLISH or BEARISH. **No trade when NEUTRAL.** | NEUTRAL = -1.5% ≤ 24H ≤ +1.5%. RANGE_GRID scans and trades. |
| AMB | AMB-002: Neutral zone confirmed as ±1.5% 24H — no-trade | Neutral becomes an active regime |

**Conflict**: The current locked rule (GATE-1 APPROVED) treats NEUTRAL as a no-trade state.
v1.1 converts NEUTRAL into an active trading regime. This changes a fundamental gate.

**Why It Matters**: All downstream logic (signal manager, scan loop, risk engine) currently
passes `regime == NEUTRAL → no new detections`. Allowing trades in NEUTRAL removes a
safety buffer and requires a full architecture change.

**Recommended Resolution**: Formal Strategy Change Proposal. Define exact NEUTRAL detection
criteria and RANGE_GRID activation conditions. Separate approval from BULLISH/BEARISH changes.

**Requires Human Approval: YES**

---

### CONFLICT-002 — LONG setup: LONG_EXHAUSTION replaced by LONG_PULLBACK

**SEVERITY: CRITICAL — STRATEGY CHANGE**

| | Current (v1.0 APPROVED) | Proposed (v1.1) |
|---|---|---|
| Rule | LONG-001..011: Bullish regime → altcoin that dumped ≥8% with RSI ≤25 and EMA extension | BULLISH → LONG_PULLBACK: price 2-4% above EMA7; 4H wick touches EMA7 or EMA14 |
| Effect | Exhaustion long on oversold dumps | Pullback/mean-reversion long |

**Conflict**: v1.1 does not retain the LONG_EXHAUSTION setup. The Bullish regime now
maps exclusively to LONG_PULLBACK. All existing LONG rules (LONG-001 through LONG-011)
are superseded.

**Why It Matters**: T008/T009/T010 already implement LONG_EXHAUSTION at 285 passing tests.
Replacing — not adding — means existing code is DEPRECATED, not extended.

**Recommended Resolution**: Explicit human confirmation that LONG_EXHAUSTION is retired.
If confirmed: deprecate LONG-001..011, implement LONG_PULLBACK as the sole BULLISH setup.

**Requires Human Approval: YES**

---

### CONFLICT-003 — Risk Model: Fixed Dollar → Percentage of Account

**SEVERITY: CRITICAL — RISK CHANGE (GATE-5)**

| | Current (v1.0 APPROVED) | Proposed (v1.1) |
|---|---|---|
| Rule | RISK-001: risk_usd = $5.00 fixed (AMB-023, IMMUTABLE) | Trend Mode = 1% account risk; Grid Mode = 0.5% account risk |
| Infrastructure | No account balance tracking exists | Requires account balance query per trade |

**Conflict**: The $5.00 fixed risk is a GATE-1 locked decision (AMB-023). v1.1 replaces it
with a percentage model requiring live account balance data.

**New infrastructure required**:
- `BybitRESTClient.get_wallet_balance()` (not currently implemented)
- Account balance cache (stale balance → what fallback?)
- % computation: `risk_usd = balance * 0.01` or `balance * 0.005`
- Paper trading: what balance do we assume? (e.g. $1000 starting capital?)

**Recommended Resolution**:
1. Confirm paper trading starting balance (suggest: $1000 USDT)
2. Formally replace AMB-023 / RISK-001 via Strategy Change Proposal
3. Define fallback when balance query fails (suggest: use prior balance, log WARNING)

**Requires Human Approval: YES (GATE-5)**

---

### CONFLICT-004 — R:R Floor: 2.0 global minimum vs 1.0-1.2 for Grid

**SEVERITY: CRITICAL — RISK CHANGE (GATE-5)**

| | Current (v1.0 APPROVED) | Proposed (v1.1) |
|---|---|---|
| Rule | AMB-016 / RISK-002: Minimum R:R = 2.0:1. Disqualify if below. | RANGE_GRID: 1.0:1 to 1.2:1 R:R |
| Scope | Global rule | Mode-specific exception |

**Conflict**: The 2.0:1 floor is a GATE-1 locked decision. RANGE_GRID proposes an explicit
exception for mean-reversion trades where price targets the range midpoint.

**Why It Matters**: Allowing 1:1 R:R requires higher win rate to be profitable. The original
2:1 floor was set specifically to provide positive expectancy with a 35%+ win rate. Grid mode
with 1:1 R:R requires >50% win rate to break even (before fees).

**CTO Note**: This is mathematically sound ONLY if the RANGE_GRID strategy demonstrates
>50% win rate in backtesting. Do not approve R:R exception without backtest evidence.

**Recommended Resolution**: Approve as mode-specific exception ONLY after v1.1 backtest
validates RANGE_GRID win rate > 50% with fees. Backtest-gated approval.

**Requires Human Approval: YES (GATE-5) — backtest evidence required**

---

### CONFLICT-005 — BTC Regime: Unresolved Edge Cases in v1.1 Definition

**SEVERITY: HIGH — CLARIFICATION REQUIRED**

**Current v1.0** (APPROVED): NEUTRAL = any condition not satisfying full BULLISH or BEARISH.
This explicitly covers: mixed EMA stack, 24H between ±1.5%, close inside EMA zone.

**v1.1 proposes**:
```
BULLISH = 24H > +1.5% AND Price > EMA7 > EMA14 > EMA28
BEARISH = 24H < -1.5% AND Price < EMA7 < EMA14 < EMA28
NEUTRAL = -1.5% ≤ 24H ≤ +1.5%
```

**Unresolved case**: 24H > +1.5% but EMA stack is mixed (e.g. EMA7 > EMA14 but EMA14 < EMA28).
- In v1.0: this is NEUTRAL (not BULLISH, falls to catch-all)
- In v1.1: 24H > +1.5% would NOT be NEUTRAL (NEUTRAL is only ±1.5%), but EMA stack is not
  aligned, so not BULLISH either. **No classification.**

**CTO Resolution Required**: When 24H is outside ±1.5% but EMA stack is not cleanly aligned,
the regime must deterministically resolve to ONE of: BULLISH / BEARISH / NEUTRAL / UNDEFINED.

**Recommended**: Keep the v1.0 fall-through logic: if 24H > +1.5% but stack mixed → NEUTRAL.
BULLISH and BEARISH require BOTH conditions. Mixed EMA stack → NEUTRAL regardless of 24H.

**Also unresolved**: Does v1.1 remove UNDEFINED? Current UNDEFINED handles stale data.
**CTO position**: UNDEFINED must be retained for stale data / missing BTC feeds.

**Requires Human Approval: YES (after explicit resolution)**

---

## SECTION 3 — CLARIFICATIONS REQUIRED

Items that cannot proceed to implementation without explicit answers.
Human and CTO answers required before any Task Contract is written.

---

### CLR-001 — RSI6: Timeframe

**What v1.1 says**: RSI6 (new indicator, appears in LONG_PULLBACK or RANGE_GRID conditions)
**What is missing**: Timeframe (1H or 4H?)

**Why it matters**: RSI6 on 1H vs 4H will produce entirely different values. Different
warmup requirements, different sensitivity. Cannot be assumed.

**Required answer**: Is RSI6 calculated on 1H candles or 4H candles?
And: Is RSI6 used in LONG_PULLBACK detection, RANGE_GRID detection, or both?

---

### CLR-002 — ATR%: Definition

**What v1.1 says**: ATR14 > 3%, ATR14 > 8%
**What is missing**: Is "ATR14 > 3%" defined as `(ATR14 / close) × 100 > 3`?

**Current v1.0 definition**: ATR is calculated in price units (not percent). Stop uses
`1.5 × ATR14` in price units (SHORT-008, LONG-009). No ATR% concept exists in v1.0.

**Why it matters**: ATR% is a normalised volatility measure. The formula must be explicit
to avoid implementation ambiguity.

**Required answer**: Confirm `atr_pct = (ATR14 / close) × 100`. Specify whether `close`
is the most recent close or the candle's close.

---

### CLR-003 — ATR Thresholds: Which Conditions Use Which Threshold

**What v1.1 says**: ATR14 > 3% and ATR14 > 8% are mentioned
**What is missing**: Which setup uses which threshold? What is the direction (> or <?

- Is ATR14 > 3% a MINIMUM volatility requirement for LONG_PULLBACK?
- Is ATR14 > 8% a MAXIMUM volatility exclusion (too volatile for RANGE_GRID)?
- Or are these both exclusion filters?

**Required answer**: For each threshold (3% and 8%), specify the setup, the condition
(> or <), and whether it qualifies or disqualifies.

---

### CLR-004 — LONG_PULLBACK: Eligibility vs Entry Timing

**What v1.1 says**:
- Eligibility: Price 2-4% above EMA7
- Entry: 4H wick touches EMA7 or EMA14

**The logical tension**: If eligibility requires price to be 2-4% ABOVE EMA7,
and entry requires price to TOUCH EMA7, this implies a pullback sequence:

  Detection (price is 2-4% above EMA7)
      → WATCHING (price pulls back toward EMA7)
      → ARMED (4H wick touches EMA7 or EMA14)
      → TRIGGERED (what candle closes to trigger entry?)

**Required answers**:
1. Is the "2-4% above EMA7" evaluated on 1H or 4H candles?
2. The "4H wick touches EMA7" — is EMA7 the 4H EMA7 or the 1H EMA7?
3. What constitutes the TRIGGERED state for LONG_PULLBACK? (What closes where?)
4. What is the stop placement for LONG_PULLBACK? (ATR-based? Below EMA14?)
5. What is the take profit for LONG_PULLBACK? (Previous high? EMA28? Fixed R:R?)
6. What is the expiration window for LONG_PULLBACK?
7. Does LONG_PULLBACK have a RSI condition, or is RSI not required?

---

### CLR-005 — RANGE_GRID: Entry Direction Confirmation

**What v1.1 says**:
- Price > RangeHigh + 2% → short entry
- Price < RangeLow - 2% → long entry

**CTO interpretation**: This is a **breakout fade / mean-reversion** strategy.
When price breaks above the 7-day range by 2%, we SHORT expecting it to return to range.
When price breaks below by 2%, we LONG expecting recovery.

**Required confirmation**: Is this interpretation correct? This is NOT traditional
grid trading (grid trading enters at multiple price levels inside a range). The name
"RANGE_GRID" may be misleading if the intent is breakout fade.

---

### CLR-006 — RANGE_GRID: ATR Validation Threshold

**What v1.1 says**: ATR validation for range definition
**What is missing**: What ATR threshold disqualifies the range?

Example: If ATR14 > 8% (too volatile), the coin is not "ranging" and RANGE_GRID
should not scan it. But the threshold and the comparison direction are undefined.

**Required answer**: What is the ATR condition that makes a coin eligible for RANGE_GRID?

---

### CLR-007 — RANGE_GRID: Stop and Take Profit Rules

**What v1.1 says**: R:R = 1.0:1 to 1.2:1
**What is missing**: Exact stop placement and take profit calculation.

Options:
a. Stop = RangeHigh + X% (beyond breakout); TP = RangeMid
b. Stop = entry + ATR×multiplier; TP = entry - 1.0×risk
c. Something else entirely

**Required answer**: Exact stop and TP formulas for RANGE_GRID longs and shorts.

---

### CLR-008 — RANGE_GRID: Backtesting and Look-Ahead Bias

**What v1.1 says**: 7-day lookback, 4H candles, RangeHigh/RangeLow
**Concern**: A 7-day lookback on 4H candles = 42 candles. In backtesting, must use
only candles PRIOR to the detection candle (candle index -42 to -1).

This is the same look-ahead-bias protection required for all other indicators.
However, the Range calculation is different from simple rolling stats — it
computes a structural range reference.

**Required confirmation**: This is noted for Sonnet quant review — NOT blocking,
but must be explicitly tested in backtest with look-ahead guard.

---

### CLR-009 — Max 2 Positions: Exact Rule

**What v1.1 says**: Max 2 positions per coin
**Current rule (RISK-007)**: Rejects new signal if ACTIVE or ARMED/TRIGGERED for same symbol.
**v1.1 interpretation required**:

Option A: Allow up to 2 concurrent ACTIVE positions per symbol (requires layering/averaging)
Option B: Allow up to 2 total entries per day per symbol (resets at midnight)
Option C: Allow a second setup attempt while first is WATCHING (not yet ACTIVE)

**Why it matters**: Option A would require significant SignalManager and RiskEngine changes.
Options B/C are simpler and less risky.

**Required answer**: What exactly does "max 2 positions per coin" mean?

---

### CLR-010 — Listing Filter: Exact Bybit Field

**What v1.1 says**: NOT in first 48h of listing
**Current rule**: SHORT-001 edge case: symbol listed < 24H ago: disqualify (1H only)
**v1.1 change**: 48H and applies to ALL modes

**Bybit API field**: `launchTime` (milliseconds Unix timestamp) from instruments_info endpoint.
Formula: `(current_time - launchTime) / 3600000 < 48` → disqualify

**CTO determination**: This is **CLARIFICATION ONLY** — the field exists. The change from
24H to 48H is a minor strategy change. This can be approved as part of the broader
strategy change proposal without a separate human decision gate.

---

### CLR-011 — RANGE_GRID: Scoring Criteria

**What v1.1 says**: New scan mode
**What is missing**: RANGE_GRID scoring criteria (the existing SCORE-001 is designed for
exhaustion setups with RSI, pump/dump, and sweep depth — inapplicable to grid trades).

**Required answer**: What are the scoring criteria (0-100) for a RANGE_GRID setup?
Does the same 80-point threshold apply?

---

### CLR-012 — LONG_PULLBACK: Scoring Criteria

Same issue as CLR-011 but for LONG_PULLBACK.
The existing SCORE-001 requires: 24H move (pump/dump), RSI extreme, sweep depth, 
rejection candle quality. None of these apply directly to a pullback setup.

**Required answer**: Scoring criteria for LONG_PULLBACK.

---

### CLR-013 — SHORT_EXHAUSTION: Unchanged?

**What v1.1 says**: BEARISH → SHORT_EXHAUSTION
**Current approved spec**: BEARISH → SHORT (SECTION 4, SHORT-001..010)

**CTO determination**: SHORT_EXHAUSTION is the SAME setup as the current approved SHORT.
The v1.1 is simply renaming it and placing it under the mode architecture.

**Required confirmation**: Are SHORT-001..010 rules preserved exactly in v1.1, with only
the addition of the mode-selector gating?

---

### CLR-014 — Pump/Dump Gate at ±8%: Still Present in v1.1?

**Current v1.0**: 24H ≥ +8% → UNDEFINED regime (pump disqualification for BTC)
**v1.1 regime definition does not mention ±8% gate**

**CTO question**: Is the pump/dump UNDEFINED gate (which protects against extreme BTC moves)
still in effect in v1.1, or does the new regime definition replace it?

The current implementation in T007 (`detector.py`) uses pump/dump gate logic that was
approved in T007 GATE-1. If v1.1 removes it, a change proposal is required.

---

### CLR-015 — Daily Limits: Per-Mode or Unified?

**Current**: 5 trades/day, -$25 loss, +$50 profit lock — unified across all setups
**v1.1 introduces**: 3 modes with different risk profiles

**Required answer**: Do all three modes share the unified daily limits, or does each
mode have separate limits?

---

## SECTION 4 — MODE ARCHITECTURE RECOMMENDATION

### Recommended Design: Small Dedicated ModeSelector Module

```
BTC REGIME (T007 — RegimeDetector, refreshed every 4H)
    ↓
ModeSelector (new small module — pure function)
    ├── BULLISH  → ScanMode.LONG_PULLBACK
    ├── BEARISH  → ScanMode.SHORT_EXHAUSTION
    ├── NEUTRAL  → ScanMode.RANGE_GRID
    └── UNDEFINED → ScanMode.HALTED
```

**Recommended location**: `src/scanner/mode_selector.py` (~30 lines, pure function)
**NOT in T007**: RegimeDetector should remain pure classification only.
**NOT in T008**: SetupDetector should not carry routing logic.

```python
from enum import Enum
from scanner.models import Regime

class ScanMode(str, Enum):
    LONG_PULLBACK     = "LONG_PULLBACK"
    SHORT_EXHAUSTION  = "SHORT_EXHAUSTION"
    RANGE_GRID        = "RANGE_GRID"
    HALTED            = "HALTED"

def select_mode(regime: Regime) -> ScanMode:
    mapping = {
        Regime.BULLISH: ScanMode.LONG_PULLBACK,
        Regime.BEARISH: ScanMode.SHORT_EXHAUSTION,
        Regime.NEUTRAL: ScanMode.RANGE_GRID,
    }
    return mapping.get(regime, ScanMode.HALTED)
```

This enforces the invariant: exactly one active scan mode per confirmed 4H BTC regime.
The ScanLoop receives the mode at the start of each processing cycle and passes it to
the appropriate detector.

**One-way gate**: HALTED mode → no detections fired, no risk approved, no signals created.

---

## SECTION 5 — ANALYSIS BY REVIEW ITEM (A through K)

### A. RISK MODEL — Verdict: GATE-5 REQUIRED

The v1.1 risk model (1% / 0.5% account) is fundamentally incompatible with the
current infrastructure. It requires:
1. Live account balance query (REST endpoint not yet implemented)
2. Paper trading starting balance definition
3. Fallback behavior when balance is unavailable
4. A formal change to AMB-023 (locked GATE-1 decision)

**Cannot proceed without explicit human approval and balance definition.**

---

### B. R:R — Verdict: GATE-5 REQUIRED, backtest-gated

The 2.0:1 global floor is AMB-016, GATE-1 locked. A mode-specific exception at 1.0-1.2
is mathematically valid ONLY if win rate > 50% is demonstrated. Cannot be approved
speculatively. Backtest must validate RANGE_GRID before R:R exception is approved.

---

### C. BTC REGIME — Verdict: CLARIFICATION THEN APPROVAL

The v1.1 regime definition collapses NEUTRAL into a simple 24H range check. The
edge case (24H > 1.5% but mixed EMA) must be resolved before any implementation.

**CTO recommended rule** (requires human confirmation):
```
BULLISH:   24H > +1.5% AND EMA7 > EMA14 > EMA28 AND close > EMA7
BEARISH:   24H < -1.5% AND EMA7 < EMA14 < EMA28 AND close < EMA7
NEUTRAL:   24H between -1.5% and +1.5% (inclusive), OR mixed EMA stack
UNDEFINED: Stale data / BTC feed error / |24H| >= 8%
```
(Note: UNDEFINED still required for data integrity. NEUTRAL remains the catch-all for
"not clearly directional".)

---

### D. LONG_PULLBACK — Verdict: 7 clarifications required (CLR-004)

The setup has an eligibility detection stage and an entry trigger stage, but the
intermediate states, trigger candle, stop, TP, and expiration are all undefined.
Cannot write a Task Contract without answers to CLR-004 questions 1-7.

---

### E. RSI6 — Verdict: Timeframe undefined (CLR-001)

RSI6 requires: period=6, method=Wilder's, timeframe=?
Implementation is trivial once timeframe is specified (same code as RSI14, different period).

---

### F. ATR — Verdict: Definition and thresholds undefined (CLR-002, CLR-003)

ATR14 exists (implemented in T006). ATR-as-percent requires a new derived computation.
The threshold usage (qualifying vs disqualifying, which setup) must be explicit.

---

### G. RANGE DEFINITION — Verdict: No look-ahead bias risk in live mode

For LIVE/PAPER scanning: the 7-day lookback (42 4H candles before detection candle) is
historical data and cannot be look-ahead biased if correctly queried.

For BACKTESTING: the range must be computed using only candles with index < detection index.
Sonnet quant review must verify this during T023 (Backtest).

**CandleStore**: 4H candle buffer currently initialised but the store capacity may need
to increase from 200 to accommodate 42+ candles comfortably. (200 is sufficient: 42 ≪ 200.)

---

### H. RANGE_GRID ENTRY — CTO Interpretation

Based on "Price > RangeHigh + 2%" → SHORT and "Price < RangeLow - 2%" → LONG:

This is a **breakout fade / mean-reversion** strategy. The 2% buffer ensures the breakout
is confirmed before fading. Target is mean-reversion toward RangeMid or opposite range boundary.

This is NOT:
- Traditional grid trading (multiple entries inside range)
- Trend following (would go LONG on breakout above, not SHORT)

**Confirmed classification**: Breakout Fade / Mean Reversion.
Requires explicit human confirmation before implementation (CLR-005).

---

### I. MAX 2 POSITIONS — Verdict: Ambiguous (CLR-009)

Current RISK-007 allows max 1 active/armed/triggered signal per symbol.
v1.1 "max 2" is ambiguous. Most likely intent: max 2 ACTIVE positions per symbol
(one from each direction, or two entries on the same trade idea).

**Cannot implement without explicit rule**. Change to RISK-007 requires human approval.

---

### J. LISTING FILTER — Verdict: 48H, implementable with existing data

`launchTime` field is available on Bybit instruments_info endpoint.
Formula: `hours_since_listing = (now_ms - launch_time_ms) / 3_600_000`
Filter: `hours_since_listing < 48` → disqualify symbol entirely.

**Minor strategy change** (24H → 48H). Included in broader strategy change proposal.

---

### K. TASK NUMBERING — Resolved

**Current approved tasks**: T001-T012
**Planned next**: T013 Alert Engine (unchanged — not affected by v1.1)

**v1.1 tasks** (after human approval, after T013):
```
T013  Alert Engine          (unchanged — implement now, independent)
T014  v1.1 Spec Update      (canonicalize strategy/risk after human approval)
T015  ModeSelector Module   (new, ~30 lines, pure function)
T016  RegimeDetector v1.1   (edge-case rules, NEUTRAL catch-all, UNDEFINED retention)
T017  RSI6 Indicator        (new indicator — T006 extension)
T018  SetupDetector v1.1    (LONG_PULLBACK + RANGE_GRID detectors; SHORT unchanged)
T019  ScoreEngine v1.1      (mode-specific scoring criteria)
T020  RiskEngine v1.1       (% account risk, mode-specific R:R, max 2 positions)
T021  SignalManager v1.1    (mode routing, mode-specific state paths)
T022  ScanLoop v1.1         (ModeSelector integration, all three mode pipelines)
T023  Backtest Engine       (v1.1 validation, GATE-2 candidate)
T024  Paper Trading         (GATE-3 candidate)
```

T013 can proceed immediately (no strategy dependency).
T014 through T022 are BLOCKED on human approval of strategy/risk changes.
T023 must validate RANGE_GRID win rate before GATE-5 R:R exception is approved.

---

## SECTION 6 — TASK GRAPH CHANGES (Proposed)

Task graph update required in `docs/TASK_GRAPH.md` after human approval:

```
[CURRENT]
T012 (ScanLoop) → T013 (Alerts) → T014 (Backtest) → T015 (Paper)

[PROPOSED AFTER v1.1 APPROVAL]
T012 (ScanLoop v1.0) → T013 (Alerts)
                           ↓
                      T014 (v1.1 Spec)
                           ↓
               T015 (ModeSelector)
                           ↓
              T016 (Regime v1.1)
                           ↓
    T017 (RSI6)  ∥  T018 (SetupDetector v1.1)
                           ↓
               T019 (ScoreEngine v1.1)
                           ↓
               T020 (RiskEngine v1.1)
                           ↓
               T021 (SignalManager v1.1)
                           ↓
               T022 (ScanLoop v1.1)
                           ↓
              T023 (Backtest — GATE-2)
                           ↓
              T024 (Paper Trading — GATE-3)
```

---

## SECTION 7 — BLOCKING ISSUES (CODEX CANNOT START)

| # | Blocker | Resolves By |
|---|---|---|
| B-001 | NEUTRAL regime → active trade requires Human Approval | Human decision |
| B-002 | LONG_EXHAUSTION → LONG_PULLBACK replacement requires Human Approval | Human decision |
| B-003 | Risk model: $5 fixed → % account requires GATE-5 | Human decision |
| B-004 | R:R exception for RANGE_GRID requires GATE-5 + backtest evidence | Backtest gate |
| B-005 | Max 2 positions ambiguity (CLR-009) | Human clarification |
| B-006 | BTC regime edge case: 24H > 1.5% + mixed EMA → classification? | Human confirmation |
| B-007 | LONG_PULLBACK: 7 sub-rules undefined (CLR-004) | Human specification |
| B-008 | RANGE_GRID: stop, TP, scoring undefined (CLR-006, CLR-007, CLR-011) | Human specification |
| B-009 | RSI6 timeframe undefined (CLR-001) | Human clarification |
| B-010 | ATR% definition undefined (CLR-002, CLR-003) | Human clarification |
| B-011 | LONG_PULLBACK scoring undefined (CLR-012) | Human specification |
| B-012 | Pump/dump UNDEFINED gate: retained or removed? (CLR-014) | Human confirmation |
| B-013 | SHORT_EXHAUSTION: confirmed unchanged? (CLR-013) | Human confirmation |
| B-014 | Daily limits: unified or per-mode? (CLR-015) | Human clarification |
| B-015 | Paper trading starting balance for % risk model | Human specification |

---

## SECTION 8 — WHAT CAN PROCEED NOW

**T013 Alert Engine** is fully independent of v1.1 changes. Its scope (Telegram/Discord
alerts for triggered signals) is compatible with all three modes — the alert schema
simply needs a `mode` field added later. T013 can be implemented immediately.

After T013, everything waits for human decisions on B-001 through B-015.

---

## SECTION 9 — BACKTEST REQUIREMENTS (v1.1)

Because v1.1 changes trade frequency and market-regime behavior, separate backtests
are required per mode:

```
Mode            Metrics Required
─────────────────────────────────────────────────────────────────
SHORT_EXHAUSTION  trade count, win rate, profit factor, avg R,
LONG_PULLBACK     expectancy, max drawdown, PnL, trade frequency
RANGE_GRID        (plus: for RANGE_GRID — win rate must exceed 50%)

All modes        Performance by BTC regime (BULLISH/BEARISH/NEUTRAL periods)
Aggregate        Combined system equity curve
```

v1.0 backtest (if any) does NOT validate v1.1. Separate validation required.

**GATE-2 approval requires**: All three mode backtests reviewed by Sonnet (quant) and
Gemini (adversarial) + CTO final review before paper trading begins.

---

## STATUS AND SIGN-OFF

| Role | Status | Date |
|---|---|---|
| CTO Impact Review | ✅ COMPLETE | 2026-09-01 |
| Human review of blocking items | ⏳ PENDING | — |
| Strategy Change Proposal | ⏳ PENDING (human decisions first) | — |
| Task Contracts (T014-T022) | 🚫 BLOCKED | — |
| Codex implementation | 🚫 BLOCKED | — |

---

*End of STRATEGY_V1_1_IMPACT_REPORT.md*
*CTO: A+ Scanner v1.1 impact analysis complete. Awaiting human decisions on 15 blocking items.*
