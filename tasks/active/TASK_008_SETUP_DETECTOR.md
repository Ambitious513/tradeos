# TASK CONTRACT
# ═══════════════════════════════════════════════════════════════
# Task ID:        T008
# Task Name:      SetupDetector — Pure Detection Functions
# Status:         READY
# Priority:       P1 — T009 and T010 depend on this
# Owner Agent:    CODEX
# Reviewer:       SONNET (quant), GEMINI (adversarial), CTO (final)
# Created By:     Lead CTO (Opus/Fable)
# Created Date:   2026-09-01
# Target Branch:  feature/t008-setup-detector
# Depends On:     T006 APPROVED, T007 APPROVED
# Blocks:         T009 (ScoreEngine), T010 (SignalManager)
# ═══════════════════════════════════════════════════════════════

---

## 1. Objective

Implement all pure, stateless condition-check functions and stop/TP calculators
for both the SHORT (SECTION 4) and LONG (SECTION 5) exhaustion setups.

T008 is the detection layer only — it does NOT own the signal state machine
(T010), signal scoring (T009), or risk sizing (T011). It provides composable
functions that T010 calls to advance signals through each state transition.

---

## 2. Background

The A+ Scanner strategy has a 6-state signal lifecycle:
```
DETECTED → WATCHING → ARMED → TRIGGERED → ACTIVE → (TP_HIT | SL_HIT | EXPIRED | CANCELLED)
```

T008 provides the boolean condition checks and numeric calculators that drive
each state transition. T010 (SignalManager) owns the state machine and calls
these functions. All T008 functions are pure: same input → same output, no
side effects, no state, no I/O.

---

## 3. Source-of-Truth Documents

| Document | Sections Required |
|---|---|
| `AGENTS.md` | All |
| `docs/STRATEGY_SPEC.md` | §3 (warmup), §4 (SHORT-001 through SHORT-010), §5 (LONG-001 through LONG-011), §9 (indicator definitions), §10 (expiration) |
| `src/scanner/models.py` | `Candle`, `Direction` |
| `src/scanner/indicators/__init__.py` | `ema`, `rsi`, `atr` |

---

## 4. Scope

Pure detection functions and one result dataclass only.
No state machine. No database access. No signal objects.

---

## 5. Allowed Files / Directories

```
src/scanner/strategy/__init__.py          NEW
src/scanner/strategy/setup_detector.py   NEW
tests/unit/test_setup_detector.py        NEW
```

---

## 6. Forbidden Files / Directories

```
docs/STRATEGY_SPEC.md         — PROTECTED
AGENTS.md                     — PROTECTED
src/scanner/indicators/       — do not modify (T006)
src/scanner/regime/           — do not modify (T007)
src/scanner/candle_store/     — do not modify (T005)
src/scanner/models.py         — do not modify
src/scanner/config.py         — do not modify
tasks/                        — do not touch
reviews/                      — do not touch
```

---

## 7. Requirements

### R-001 — SetupContext Dataclass

```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from scanner.models import Direction

@dataclass(frozen=True)
class SetupContext:
    """Carries all computed values for one potential setup.

    Produced by detect_initial_conditions(); consumed by T009 and T010.
    """
    symbol: str
    direction: Direction           # LONG or SHORT
    detected_at: datetime          # UTC timestamp of the triggering candle

    # 24H rolling stats (computed from last 24 closed 1H candles)
    change_24h_pct: Decimal        # (close_now - close_24h_ago) / close_24h_ago * 100
    high_24h: Decimal              # highest high over last 24 closed 1H candles
    low_24h: Decimal               # lowest low over last 24 closed 1H candles

    # Indicator values at detection time
    rsi_14: float
    ema_7: Decimal
    ema_extension_pct: Decimal     # |close - EMA7| / EMA7 * 100
    atr_14: Decimal

    # Triggering candle
    trigger_candle: Candle
```

### R-002 — 24H Rolling Statistics

```python
def compute_24h_stats(
    candles: list[Candle],
) -> tuple[Decimal, Decimal, Decimal] | None:
    """Compute rolling 24H high, low, and close change for the last 24 candles.

    Args:
        candles: Closed 1H candles ordered oldest-first. Must have >= 25 candles
                 (current + 24 prior for a full 24H window).

    Returns:
        (high_24h, low_24h, change_pct) as Decimals, or None if < 25 candles.
        change_pct = (candles[-1].close - candles[-25].close) / candles[-25].close * 100

    Notes:
        - high_24h = max(candle.high for candle in candles[-24:])
        - low_24h  = min(candle.low  for candle in candles[-24:])
        - change_pct uses candles[-25].close as the reference (24H ago)
        - Returns None if candles[-25].close == 0 (zero-close guard)
        - All arithmetic uses Decimal
    """
```

### R-003 — Initial Condition Detection (DETECTED state)

```python
def detect_initial_conditions(
    candles: list[Candle],
    direction: Direction,
    config: ScannerConfig,
) -> SetupContext | None:
    """Check if initial setup conditions are met on the most recent closed 1H candle.

    SHORT setup (Direction.SHORT, STRATEGY_SPEC §4):
        - SHORT-001: 24H change >= +8% (altcoin pumped)
        - SHORT-002: RSI(14) >= 75 (overbought)
        - SHORT-003: (close - EMA7) / EMA7 * 100 >= 3.0% (extended above EMA7)

    LONG setup (Direction.LONG, STRATEGY_SPEC §5):
        - LONG-001: 24H change <= -8% (altcoin dumped)
        - LONG-002: RSI(14) <= 25 (oversold)
        - LONG-003: (EMA7 - close) / EMA7 * 100 >= 3.0% (extended below EMA7)

    Warmup requirements (STRATEGY_SPEC §9):
        - Minimum 28 closed candles for RSI (2× period)
        - Minimum 28 closed candles for ATR (2× period)
        - Minimum 25 closed candles for 24H stats
        - Minimum 7 closed candles for EMA7

    Returns SetupContext if ALL three conditions satisfied; None otherwise.
    Callers must check direction against the active BTC regime before calling.
    """
```

**Exact threshold rules from STRATEGY_SPEC.md (IMMUTABLE):**

| Condition | SHORT threshold | LONG threshold | Inclusive |
|---|---|---|---|
| 24H change | `>= +8.0%` | `<= -8.0%` | ✅ inclusive |
| RSI(14) | `>= 75.0` | `<= 25.0` | ✅ inclusive |
| EMA7 extension | `>= 3.0%` | `>= 3.0%` (below) | ✅ inclusive |

**Disqualification rules:**
- Fewer than 28 candles: return None; do NOT raise
- 24H stats unavailable: return None
- EMA7 = 0: return None (zero guard)
- Any indicator returns None (insufficient data): return None

### R-004 — 24H High Interaction (SHORT-004 / LONG-004)

```python
def check_24h_level_interaction(
    candle: Candle,
    level_24h: Decimal,
    direction: Direction,
) -> bool:
    """Check if candle interacts with the 24H high (SHORT) or 24H low (LONG).

    SHORT (SHORT-004):
        proximity_pct = (high_24h - candle.high) / high_24h * 100
        Returns True if proximity_pct <= 0.5  (within 0.5% below 24H high, OR above)

    LONG (LONG-004):
        proximity_pct = (candle.low - low_24h) / low_24h * 100
        Returns True if proximity_pct <= 0.5  (within 0.5% above 24H low, OR below)

    Returns False if level_24h == 0 (zero guard).
    """
```

### R-005 — Rejection Candle (SHORT-005) / Liquidity Sweep (LONG-005)

```python
def check_rejection_candle(
    candle: Candle,
    high_24h: Decimal,
) -> bool:
    """Detect a SHORT rejection candle at the 24H high (SHORT-005).

    Conditions (ALL required):
      1. candle.close < candle.open  (bearish close)
      2. upper_wick = candle.high - candle.open
         candle_body = candle.open - candle.close  (open > close for bearish)
         upper_wick >= 1.5 * candle_body
      3. 24H high interaction (SHORT-004): proximity_pct <= 0.5%

    Returns False for doji candles (body == 0): STRATEGY_SPEC §4 SHORT-005 edge case.
    Returns False if 24H high interaction not met.
    """

def check_liquidity_sweep(
    candle: Candle,
    low_24h: Decimal,
) -> bool:
    """Detect a LONG liquidity sweep at the 24H low (LONG-005).

    Conditions (ALL required):
      1. sweep_depth = (low_24h - candle.low) / low_24h * 100 >= 0.1%
         (candle low went BELOW 24H low by >= 0.1%)
      2. candle.close > low_24h
         (candle CLOSES ABOVE 24H low — sweep rejected)

    Returns False if low_24h == 0 (zero guard).
    """

def check_bullish_rejection_candle(
    candle: Candle,
    low_24h: Decimal,
) -> bool:
    """Detect a LONG rejection/reversal candle (LONG-006).

    Conditions (ALL required):
      1. candle.close > candle.open  (bullish close)
      2. lower_wick = candle.open - candle.low
         candle_body = candle.close - candle.open
         lower_wick >= 1.5 * candle_body
      3. Liquidity sweep condition met (LONG-005)

    Returns False for doji candles (body == 0).
    """
```

### R-006 — Retest Detection (SHORT-006 / LONG-007)

```python
def check_retest_short(
    candle: Candle,
    rejection_close: Decimal,
    high_24h: Decimal,
) -> bool:
    """Detect a valid SHORT retest candle (SHORT-006).

    Conditions (ALL required):
      1. retest proximity: |candle.high - rejection_close| / rejection_close * 100 <= 0.5%
         (candle high returned within 0.5% of rejection candle close)
      2. candle.close < rejection_close
         (candle closes BELOW the rejection close — failed recovery)
      3. candle.high < high_24h
         (no new 24H high made during retest)

    Returns False if rejection_close == 0.
    """

def check_retest_long(
    candle: Candle,
    rejection_close: Decimal,
    low_24h: Decimal,
) -> bool:
    """Detect a valid LONG retest candle (LONG-007).

    Conditions (ALL required):
      1. retest proximity: |candle.low - rejection_close| / rejection_close * 100 <= 0.5%
         (candle low returned within 0.5% of rejection candle close)
      2. candle.close > rejection_close
         (candle closes ABOVE the rejection close — support holds)
      3. candle.low > low_24h
         (no new 24H low made during retest)

    Returns False if rejection_close == 0.
    """
```

### R-007 — Entry Trigger (SHORT-007 / LONG-008)

```python
def check_entry_trigger_short(
    candle: Candle,
    retest_low: Decimal,
) -> bool:
    """Detect SHORT entry trigger (SHORT-007, AMB-012).

    Returns True if candle.close < retest_low.
    (1H candle CLOSES below the retest candle's low)
    """

def check_entry_trigger_long(
    candle: Candle,
    retest_high: Decimal,
) -> bool:
    """Detect LONG entry trigger (LONG-008, AMB-013).

    Returns True if candle.close > retest_high.
    (1H candle CLOSES above the retest candle's high)
    """
```

### R-008 — Stop Loss Computation (SHORT-008 / LONG-009)

```python
def compute_stop_short(
    entry_price: Decimal,
    recent_candles: list[Candle],
    atr_14: Decimal,
) -> Decimal:
    """Compute SHORT stop loss per SHORT-008 (AMB-015).

    structural_stop = highest_high(recent_candles[-3:]) + (0.001 * entry_price)
    atr_stop        = entry_price + (1.5 * atr_14)
    stop            = MAX(structural_stop, atr_stop)

    For SHORT: stop is ABOVE entry. MAX picks the wider (safer) stop.

    Args:
        recent_candles: Must contain >= 3 candles (uses last 3). If fewer
                        than 3, uses all available.
    """

def compute_stop_long(
    entry_price: Decimal,
    recent_candles: list[Candle],
    atr_14: Decimal,
) -> Decimal:
    """Compute LONG stop loss per LONG-009 (AMB-015).

    structural_stop = lowest_low(recent_candles[-3:]) - (0.001 * entry_price)
    atr_stop        = entry_price - (1.5 * atr_14)
    stop            = MIN(structural_stop, atr_stop)

    For LONG: stop is BELOW entry. MIN picks the wider (further from entry = safer) stop.
    """
```

### R-009 — Take Profit and R:R (SHORT-009 / LONG-010)

```python
def compute_take_profit(
    entry_price: Decimal,
    stop_price: Decimal,
    direction: Direction,
) -> Decimal:
    """Compute take profit at 2:1 R:R (AMB-016).

    SHORT: risk_distance = stop_price - entry_price  (positive, stop is above entry)
           take_profit   = entry_price - (2.0 * risk_distance)

    LONG:  risk_distance = entry_price - stop_price  (positive, stop is below entry)
           take_profit   = entry_price + (2.0 * risk_distance)
    """

def check_minimum_rr(
    entry_price: Decimal,
    stop_price: Decimal,
    take_profit: Decimal,
    direction: Direction,
    min_rr: Decimal = Decimal("2.0"),
) -> bool:
    """Return True if the R:R ratio meets the minimum threshold.

    reward   = |take_profit - entry_price|
    risk     = |stop_price - entry_price|
    rr_ratio = reward / risk

    Returns False if risk == 0 (degenerate stop).
    """
```

### R-010 — Volume Confirmation Helper

```python
def compute_avg_volume(candles: list[Candle], period: int = 20) -> Decimal | None:
    """Compute the simple average volume over the last `period` candles.

    Returns None if fewer than `period` candles available.
    Used by T009 (ScoreEngine) for volume confirmation scoring.
    """
```

### R-011 — Structured Logging

Use `get_logger("strategy.setup_detector")`. All detection functions are pure
(no logging). Only top-level orchestration code (T010) logs state transitions.

T008 functions MUST NOT log. They return values and let callers decide.

### R-012 — Public Interface

```python
# src/scanner/strategy/__init__.py
from scanner.strategy.setup_detector import (
    SetupContext,
    compute_24h_stats,
    detect_initial_conditions,
    check_24h_level_interaction,
    check_rejection_candle,
    check_liquidity_sweep,
    check_bullish_rejection_candle,
    check_retest_short,
    check_retest_long,
    check_entry_trigger_short,
    check_entry_trigger_long,
    compute_stop_short,
    compute_stop_long,
    compute_take_profit,
    check_minimum_rr,
    compute_avg_volume,
)
__all__ = [...]
```

---

## 8. Non-Goals

- Do NOT implement the signal state machine (T010)
- Do NOT implement A+ scoring (T009)
- Do NOT implement risk sizing / position sizing (T011)
- Do NOT access CandleStore, database, or network
- Do NOT accept `ScannerConfig` in any pure detection function except `detect_initial_conditions()` (which needs threshold values)
- Do NOT log inside detection functions

---

## 9. Interfaces / Contracts

```python
from scanner.strategy import (
    SetupContext, detect_initial_conditions,
    check_rejection_candle, check_liquidity_sweep,
    check_retest_short, check_retest_long,
    check_entry_trigger_short, check_entry_trigger_long,
    compute_stop_short, compute_stop_long,
    compute_take_profit, check_minimum_rr,
)
```

These paths must remain stable after delivery.

---

## 10. Acceptance Criteria

| AC-ID | Criterion | Test |
|---|---|---|
| AC-001 | SHORT initial: 24H change >= 8% + RSI >= 75 + EMA ext >= 3% → SetupContext | `test_short_initial_conditions_all_met` |
| AC-002 | SHORT initial: RSI < 75 → None | `test_short_rejects_on_rsi_below_threshold` |
| AC-003 | SHORT initial: EMA extension < 3% → None | `test_short_rejects_on_ema_extension_below_threshold` |
| AC-004 | SHORT initial: 24H change < 8% → None | `test_short_rejects_on_insufficient_pump` |
| AC-005 | LONG initial: dump <= -8% + RSI <= 25 + EMA ext >= 3% below → SetupContext | `test_long_initial_conditions_all_met` |
| AC-006 | LONG initial: RSI > 25 → None | `test_long_rejects_on_rsi_above_threshold` |
| AC-007 | Fewer than 28 candles → None (warmup) | `test_insufficient_candles_returns_none` |
| AC-008 | Thresholds inclusive: RSI = 75.0 qualifies SHORT | `test_rsi_threshold_inclusive_short` |
| AC-009 | Thresholds inclusive: RSI = 25.0 qualifies LONG | `test_rsi_threshold_inclusive_long` |
| AC-010 | Short rejection candle: bearish + wick >= 1.5× body + 24H high interaction | `test_rejection_candle_short_valid` |
| AC-011 | Rejection candle: doji (body=0) → False | `test_rejection_candle_doji_rejected` |
| AC-012 | Liquidity sweep: low below 24H low by >= 0.1% AND close above | `test_liquidity_sweep_valid` |
| AC-013 | Liquidity sweep: close below 24H low → False (no recovery) | `test_liquidity_sweep_no_recovery_rejected` |
| AC-014 | Retest SHORT: within 0.5% of rejection close, closes below, no new high | `test_retest_short_valid` |
| AC-015 | Retest LONG: within 0.5% of rejection close, closes above, no new low | `test_retest_long_valid` |
| AC-016 | Entry trigger SHORT: close < retest_low → True | `test_entry_trigger_short_valid` |
| AC-017 | Entry trigger LONG: close > retest_high → True | `test_entry_trigger_long_valid` |
| AC-018 | Stop SHORT: MAX(structural, ATR-based) | `test_stop_short_uses_wider_stop` |
| AC-019 | Stop LONG: MIN(structural, ATR-based) | `test_stop_long_uses_wider_stop` |
| AC-020 | TP SHORT: entry - 2 × risk_distance | `test_take_profit_short` |
| AC-021 | TP LONG: entry + 2 × risk_distance | `test_take_profit_long` |
| AC-022 | R:R check: 2:1 → True; 1.9:1 → False | `test_minimum_rr_check` |
| AC-023 | All price arithmetic uses Decimal | `test_all_results_are_decimal` |
| AC-024 | No look-ahead in 24H stats | `test_24h_stats_uses_only_closed_candles` |
| AC-025 | `mypy src/ --strict` passes | CI |
| AC-026 | `ruff check src/` passes | CI |
| AC-027 | Full suite >= 155 tests passing | `pytest tests/ -v` |

---

## 11. Required Tests

**File**: `tests/unit/test_setup_detector.py`

All tests use synthetic `Candle` objects with controlled OHLCV values.
No mocking of CandleStore or REST client.

```
test_short_initial_conditions_all_met_returns_setup_context
test_short_rejects_when_pump_below_8_pct
test_short_rejects_when_rsi_below_75
test_short_rejects_when_ema_extension_below_3_pct
test_long_initial_conditions_all_met_returns_setup_context
test_long_rejects_when_dump_above_neg_8_pct
test_long_rejects_when_rsi_above_25
test_long_rejects_when_ema_extension_below_3_pct_below_ema
test_insufficient_candles_returns_none
test_exactly_28_candles_passes_warmup
test_rsi_75_inclusive_short_qualifies
test_rsi_25_inclusive_long_qualifies
test_pump_8pct_inclusive_short_qualifies
test_dump_neg_8pct_inclusive_long_qualifies
test_24h_stats_correct_high_low_change
test_rejection_candle_short_all_conditions_met
test_rejection_candle_short_bullish_close_rejected
test_rejection_candle_short_insufficient_wick_rejected
test_rejection_candle_doji_body_zero_rejected
test_liquidity_sweep_valid_closes_above_low
test_liquidity_sweep_no_recovery_rejected
test_liquidity_sweep_depth_below_0_1pct_rejected
test_bullish_rejection_candle_all_conditions_met
test_retest_short_valid
test_retest_short_new_24h_high_rejected
test_retest_long_valid
test_retest_long_new_24h_low_rejected
test_entry_trigger_short_close_below_retest_low
test_entry_trigger_short_close_above_rejected
test_entry_trigger_long_close_above_retest_high
test_entry_trigger_long_close_below_rejected
test_stop_short_uses_max_of_structural_and_atr
test_stop_long_uses_min_of_structural_and_atr
test_stop_short_structural_wider_than_atr
test_stop_long_structural_wider_than_atr
test_take_profit_short_correct_formula
test_take_profit_long_correct_formula
test_minimum_rr_2_to_1_returns_true
test_minimum_rr_below_2_returns_false
test_minimum_rr_degenerate_zero_risk_returns_false
test_avg_volume_correct_period
test_avg_volume_insufficient_candles_returns_none
```

---

## 12. Expected Deliverables

```
src/scanner/strategy/__init__.py          NEW
src/scanner/strategy/setup_detector.py   NEW
tests/unit/test_setup_detector.py        NEW
```

---

## 13. Failure / Escalation Conditions

STOP and escalate if:

| Condition | Action |
|---|---|
| STRATEGY_SPEC.md threshold values conflict with config defaults | Quote spec line; escalate |
| LONG-009 "wider stop" vs MIN ambiguity | "Wider" = further from entry = lower price for LONG = MIN. Quote SHORT-008 asymmetry for reference |
| `Direction` enum values differ from what strategy needs | Quote models.py; escalate |
| Stop formula would result in stop on same side as entry | This is a critical bug; escalate immediately |

---

## 14. Completion Report Requirements

```
Task:       T008 — SetupDetector
Agent:      CODEX

Summary:    [2-3 sentences]

Files Created:      [list]
Functions Delivered: [count — target ≥ 16 public functions + SetupContext]
Tests Added:        [count — target ≥ 40]
Tests Run:          pytest tests/ -v — [N] passed (target ≥ 155)
Tests Failed:       0

Threshold Verification:
  SHORT pump 8%: [candle at 8.0%] → SetupContext returned ✅
  SHORT RSI 75 inclusive: [RSI=75.0] → qualifies ✅
  LONG dump -8%: [candle at -8.0%] → SetupContext returned ✅
  Stop SHORT wider: [structural vs ATR values + winner] ✅
  Stop LONG wider: [structural vs ATR values + winner] ✅

Recommended Next Step: T009 (ScoreEngine)
```

---

## 15. Review Plan

### SONNET Quantitative Review

Focus:
- SHORT stop: is MAX(structural, ATR) correct direction for SHORT?
- LONG stop: is MIN(structural, ATR) the right operator for "wider"?
- 24H stats: does `candles[-25]` give 24H ago at 1H resolution?
- EMA7 extension: short = (close - EMA7) / EMA7; long = (EMA7 - close) / EMA7 — sign correct?
- Retest proximity: tolerance 0.5% is applied to rejection_close, not high_24h?
- Sweep depth: (low_24h - candle_low) / low_24h — correct denominator?

Output: `reviews/sonnet/TASK_008_QUANT_REVIEW.md`

### GEMINI Adversarial Review

Focus:
- Zero guards: EMA7=0, rejection_close=0, stop=entry (degenerate)
- Doji edge cases: body < minimum precision — how is body=0 detected?
- RSI exactly on threshold (75.0 for SHORT): inclusive per spec?
- Sweep depth exactly 0.1%: inclusive per spec?
- Structural stop with fewer than 3 candles: all available used?

Output: `reviews/gemini/TASK_008_RED_TEAM.md`

### CTO Review

Focus:
- Every rule from STRATEGY_SPEC §4 and §5 has a corresponding function
- No strategy rules missing; no extra rules invented
- R:R computed before score — callers must check R:R, not assume it
- Functions return primitive types or SetupContext — no state

Output: `reviews/opus/TASK_008_FINAL_REVIEW.md`

---

## 16. Skill Extraction Decision

After T008 + T009 + T010 approved: create `skills/setup-detection/SKILL.md`.
The full 6-state detection pipeline is the skill, not individual functions.

---

## 17. Status / Sign-off

| Role | Status | Date |
|---|---|---|
| CTO (created) | ✅ READY | 2026-09-01 |
| Implementation | ⏳ PENDING | — |
| Sonnet quant | ⏳ PENDING | — |
| Gemini adversarial | ⏳ PENDING | — |
| CTO final | ⏳ PENDING | — |
| **Release Decision** | ⏳ PENDING | — |

---

*End of Task Contract — T008 SetupDetector*
