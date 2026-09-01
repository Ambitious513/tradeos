# TASK CONTRACT
# ═══════════════════════════════════════════════════════════════
# Task ID:        T006
# Task Name:      Technical Indicators
# Status:         APPROVED — 2026-09-01
# Priority:       P1 — T007, T008-T010 all depend on this
# Owner Agent:    CODEX
# Reviewer:       SONNET (quantitative / look-ahead bias review)
# CTO Review:     OPUS / FABLE
# Created By:     Lead CTO (Opus/Fable)
# Created Date:   2026-08-31
# Target Branch:  feature/t006-indicators
# Depends On:     T005 APPROVED
# Blocks:         T007 (uses EMA), T008-T010 (use all indicators)
# ═══════════════════════════════════════════════════════════════

---

## 1. Objective

Implement pure, stateless indicator functions for EMA, RSI, and ATR.

All functions are pure: they accept a list of closed candles ordered
oldest-first and return a single computed value or None when insufficient
data is available. No side effects. No I/O. No state.

---

## 2. Background

Indicators are the lowest-level computation layer. They are consumed by:
- T007 (RegimeDetector) — EMA7, EMA14, EMA28, EMA200 on BTC 4H candles
- T008 (SetupDetector) — RSI14, ATR14, EMA7 extension on symbol 1H candles
- T014 (Backtest Engine) — same functions, different data source

Because the backtest reuses these exact functions, look-ahead bias is the
primary risk. Every function must only use candles[0..n-1] to compute a
value at candle[n-1] — never candle[n] or beyond.

---

## 3. Source-of-Truth Documents

| Document | Sections Required |
|---|---|
| `AGENTS.md` | All — coding standards, escalation |
| `docs/STRATEGY_SPEC.md` | §3 (BTC regime — EMA stack), §4 (entry triggers — RSI, ATR, EMA7 extension) |
| `docs/TEST_SPEC.md` | UNIT-003, UNIT-004, UNIT-005 |
| `src/scanner/models.py` | `Candle` — fields: open, high, low, close, volume |
| `src/scanner/config.py` | `rsi_overbought=75`, `rsi_oversold=25`, `atr_stop_multiplier=1.5`, `ema7_extension_pct=3.0` |

---

## 4. Scope

Pure indicator functions only. No strategy logic. No signal detection.
No candle fetching. No database access. No config dependency in function
signatures — config values are thresholds for callers, not embedded here.

---

## 5. Allowed Files / Directories

```
src/scanner/indicators/__init__.py     NEW
src/scanner/indicators/ema.py          NEW
src/scanner/indicators/rsi.py          NEW
src/scanner/indicators/atr.py          NEW
tests/unit/test_indicators.py         NEW
```

---

## 6. Forbidden Files / Directories

```
docs/STRATEGY_SPEC.md         — PROTECTED
docs/RISK_SPEC.md             — PROTECTED
AGENTS.md                     — PROTECTED
MASTER_PROJECT_BRIEF.md       — PROTECTED
src/scanner/candle_store/     — do not modify
src/scanner/market_data/      — do not modify
src/scanner/config.py         — do not modify
src/scanner/models.py         — do not modify
src/scanner/regime/           — T007 scope
src/scanner/strategy/         — T008-T010 scope
tasks/                        — do not touch
reviews/                      — do not touch
```

---

## 7. Requirements

### R-001 — EMA (`src/scanner/indicators/ema.py`)

```python
from decimal import Decimal
from scanner.models import Candle

def ema(candles: list[Candle], period: int) -> Decimal | None:
    """Compute EMA of closing prices over `period` using the standard
    smoothing multiplier k = 2 / (period + 1).

    Args:
        candles: Closed candles ordered oldest-first.
        period:  Number of periods. Must be >= 1.

    Returns:
        EMA value as Decimal, or None if len(candles) < period.

    Notes:
        - Seeds with SMA of the first `period` candles.
        - Each subsequent candle applies: ema = close * k + prev_ema * (1 - k)
        - Uses Decimal arithmetic throughout — no float intermediate values.
        - Only candles[0..len-1] are accessed (no look-ahead).
    """
```

**Formula:**
```
k = 2 / (period + 1)
seed = mean(close[0..period-1])           # SMA seed
ema[i] = close[i] * k + ema[i-1] * (1-k) for i in [period..n-1]
return ema[n-1]
```

**Precision**: Use `Decimal` throughout. Multiplier `k` must also be
`Decimal`. Use `Decimal(2) / Decimal(period + 1)`.

**Minimum data**: Return `None` if `len(candles) < period`.

### R-002 — RSI (`src/scanner/indicators/rsi.py`)

```python
def rsi(candles: list[Candle], period: int = 14) -> float | None:
    """Compute RSI(period) using Wilder's Smoothed Moving Average method.

    Args:
        candles: Closed candles ordered oldest-first.
        period:  Lookback period. Default 14 per strategy spec.

    Returns:
        RSI as float in [0.0, 100.0], or None if insufficient data.

    Notes:
        - Requires len(candles) >= period + 1 (need period price changes)
        - Seeds with simple average of first `period` gains and losses
        - Each subsequent step: avg_gain = (prev_avg_gain*(period-1) + gain) / period
        - Returns 100.0 if avg_loss == 0 (all gains); 0.0 if avg_gain == 0 (all losses)
        - No look-ahead: uses candles[0..len-1] only
    """
```

**Formula (Wilder's Smoothed MA):**
```
changes = [close[i] - close[i-1] for i in 1..n]
gains   = [max(c, 0) for c in changes]
losses  = [abs(min(c, 0)) for c in changes]

# Seed (simple average of first `period` values)
avg_gain = mean(gains[0..period-1])
avg_loss = mean(losses[0..period-1])

# Subsequent candles
for i in period..len(changes)-1:
    avg_gain = (avg_gain * (period-1) + gains[i]) / period
    avg_loss = (avg_loss * (period-1) + losses[i]) / period

rs = avg_gain / avg_loss
rsi = 100 - (100 / (1 + rs))
```

**Edge cases:**
- `avg_loss == 0`: return `100.0`
- `avg_gain == 0 and avg_loss == 0`: return `50.0` (no movement)
- `len(candles) < period + 1`: return `None`

**Return type**: `float` (RSI is a percentage; Decimal is unnecessary overhead).

### R-003 — ATR (`src/scanner/indicators/atr.py`)

```python
def atr(candles: list[Candle], period: int = 14) -> Decimal | None:
    """Compute ATR(period) using Wilder's Smoothed Moving Average method.

    Args:
        candles: Closed candles ordered oldest-first. Must include high,
                 low, and close fields.
        period:  Smoothing period. Default 14 per strategy spec.

    Returns:
        ATR as Decimal, or None if insufficient data.

    Notes:
        - True Range = max(high-low, |high-prev_close|, |low-prev_close|)
        - Requires len(candles) >= period + 1
        - Seeds with simple mean of first `period` True Range values
        - Wilder smoothing: atr = (prev_atr*(period-1) + tr) / period
        - Uses Decimal throughout; no float intermediate values
    """
```

**Formula:**
```
TR[i] = max(high[i]-low[i], |high[i]-close[i-1]|, |low[i]-close[i-1]|)
        for i in 1..n  (requires previous close)

seed_atr = mean(TR[1..period])
for i in period+1..n-1:
    atr = (prev_atr * (period-1) + TR[i]) / period
return atr
```

**Minimum data**: Return `None` if `len(candles) < period + 1`.

### R-004 — Public Interface (`src/scanner/indicators/__init__.py`)

```python
from scanner.indicators.ema import ema
from scanner.indicators.rsi import rsi
from scanner.indicators.atr import atr

__all__ = ["ema", "rsi", "atr"]
```

Downstream tasks import: `from scanner.indicators import ema, rsi, atr`

### R-005 — No Look-Ahead Guarantee

Every function must only access `candles[0..len(candles)-1]`.

No function may:
- Access future candles based on index beyond the input list
- Use `datetime` of future candles
- Sort the input list (callers are responsible for ordering oldest-first)
- Modify the input list

Functions are pure: same input always produces same output.

### R-006 — No Float for Price Arithmetic

EMA and ATR must use `Decimal` for all price and intermediate arithmetic.
RSI is permitted to use `float` internally (it is a percentage, not a price).

### R-007 — Invalid Input Handling

```python
# All functions must validate period > 0
if period < 1:
    raise ValueError(f"period must be >= 1, got {period}")

# Empty list → return None (do not raise)
if not candles:
    return None
```

---

## 8. Non-Goals

- Do NOT implement MACD, Bollinger Bands, or any other indicator not listed above
- Do NOT embed config thresholds (rsi_overbought=75, etc.) inside indicator functions
- Do NOT add a `ScannerConfig` parameter to any indicator function
- Do NOT implement scoring logic (T008-T010 scope)
- Do NOT access the database, network, or filesystem

---

## 9. Interfaces / Contracts

```python
from scanner.indicators import ema, rsi, atr

# EMA
ema_7: Decimal | None  = ema(candles, period=7)
ema_14: Decimal | None = ema(candles, period=14)
ema_28: Decimal | None = ema(candles, period=28)
ema_200: Decimal | None = ema(candles, period=200)

# RSI
rsi_14: float | None = rsi(candles, period=14)

# ATR
atr_14: Decimal | None = atr(candles, period=14)
```

These paths and signatures must remain stable after delivery.

---

## 10. Acceptance Criteria

| AC-ID | Criterion | Verification |
|---|---|---|
| AC-001 | `ema(candles, 14)` returns None if fewer than 14 candles | `test_ema_insufficient_data` |
| AC-002 | `ema` seed matches SMA of first `period` closes | `test_ema_seed_equals_sma` |
| AC-003 | `ema` uses Decimal arithmetic, not float | `test_ema_returns_decimal` |
| AC-004 | `ema` formula produces correct known value (hand-calculated) | `test_ema_known_value` |
| AC-005 | `rsi` returns None if fewer than period+1 candles | `test_rsi_insufficient_data` |
| AC-006 | `rsi` returns 100.0 when all closes are rising | `test_rsi_all_gains_returns_100` |
| AC-007 | `rsi` returns 0.0 when all closes are falling | `test_rsi_all_losses_returns_0` |
| AC-008 | `rsi` returns 50.0 when no movement | `test_rsi_no_movement_returns_50` |
| AC-009 | `rsi` known value matches reference (±0.01 tolerance) | `test_rsi_known_value` |
| AC-010 | `atr` returns None if fewer than period+1 candles | `test_atr_insufficient_data` |
| AC-011 | `atr` true range uses prev_close correctly | `test_atr_true_range_uses_prev_close` |
| AC-012 | `atr` uses Decimal arithmetic | `test_atr_returns_decimal` |
| AC-013 | `atr` known value matches reference | `test_atr_known_value` |
| AC-014 | `period < 1` raises `ValueError` on all functions | `test_invalid_period_raises` |
| AC-015 | Empty candle list returns None (not raises) | `test_empty_candles_returns_none` |
| AC-016 | No look-ahead: functions do not reorder input list | `test_input_list_not_mutated` |
| AC-017 | `mypy src/ --strict` passes | CI |
| AC-018 | `ruff check src/` passes | CI |
| AC-019 | Full suite ≥ 110 tests passing | `pytest tests/ -v` |

---

## 11. Required Tests

**File**: `tests/unit/test_indicators.py`

Use deterministic synthetic candle sequences. Hand-compute expected values for
AC-004, AC-009, AC-013 — include the hand calculation as a comment in the test.

```
test_ema_returns_none_when_insufficient_data
test_ema_seed_is_sma_of_first_period_closes
test_ema_returns_decimal_not_float
test_ema_known_value_5_period              # hand-calculated, comment in test
test_ema_period_1_equals_last_close
test_ema_does_not_mutate_input_list

test_rsi_returns_none_when_insufficient_data
test_rsi_all_gains_returns_100
test_rsi_all_losses_returns_0
test_rsi_no_movement_returns_50
test_rsi_known_value_14_period            # hand-calculated, comment in test
test_rsi_value_in_valid_range             # 0.0 <= rsi <= 100.0

test_atr_returns_none_when_insufficient_data
test_atr_true_range_gap_up_uses_prev_close
test_atr_true_range_gap_down_uses_prev_close
test_atr_returns_decimal_not_float
test_atr_known_value_3_period             # hand-calculated, comment in test

test_invalid_period_zero_raises_value_error
test_invalid_period_negative_raises_value_error
test_empty_candle_list_returns_none
```

---

## 12. Expected Deliverables

```
src/scanner/indicators/__init__.py     NEW
src/scanner/indicators/ema.py          NEW
src/scanner/indicators/rsi.py          NEW
src/scanner/indicators/atr.py          NEW
tests/unit/test_indicators.py         NEW
```

---

## 13. Failure / Escalation Conditions

STOP and escalate if:

| Condition | Action |
|---|---|
| STRATEGY_SPEC.md requires an indicator not listed here | Document; do not implement without authorization |
| EMA/RSI formula variant ambiguity (e.g., Cutler's RSI vs Wilder's) | Use Wilder's as specified; do not substitute |
| Float vs Decimal for intermediate RSI calculation causes precision issues | Document; Decimal is acceptable for RSI internals if needed |

---

## 14. Completion Report Requirements

```
Task:       T006 — Technical Indicators
Agent:      CODEX

Summary:    [1-2 sentences]

Files Created:      [list]
Tests Added:        [count and names]
Tests Run:          pytest tests/ -v — [N] passed (target ≥ 110)
Tests Failed:       0

Known Value Verification:
  EMA(5, synthetic): expected [X], got [Y]
  RSI(14, synthetic): expected [X], got [Y]
  ATR(3, synthetic): expected [X], got [Y]

Recommended Next Step: T007 (RegimeDetector)
```

---

## 15. Review Plan

### Automated

```bash
pytest tests/unit/test_indicators.py -v --cov=src/scanner/indicators
ruff check src/scanner/indicators/
black --check src/scanner/indicators/
mypy src/ --strict
```

### SONNET Quantitative Review

This is the primary quantitative review. Focus:
- EMA formula correctness (SMA seed, k multiplier, update rule)
- RSI formula correctness (Wilder's SMA, not simple MA)
- ATR true range: all three components present, prev_close used correctly
- No look-ahead bias: function only reads past candles
- Decimal precision: no silent float conversion in price arithmetic
- Edge cases: period=1, all-same prices, zero-volume candles

Output: `reviews/sonnet/TASK_006_QUANT_REVIEW.md`

### GEMINI Adversarial Review

Focus:
- Period=1 edge case: EMA period 1 = last close price?
- RSI with flat prices (all changes = 0): returns 50.0?
- ATR with gap up/down (prev_close outside high-low range): TR is abs(high-prev_close)?
- Input list mutation: functions must not sort or modify their argument

Output: `reviews/gemini/TASK_006_RED_TEAM.md`

### CTO Review

Focus:
- Wilder's SMA (not simple rolling MA) for RSI and ATR — these are specifically required
- Decimal for EMA seed (must be Decimal SMA, not float)
- Known-value test hand calculations are actually correct

Output: `reviews/opus/TASK_006_FINAL_REVIEW.md`

---

## 16. Skill Extraction Decision

After T006 approval: **SKILL CANDIDATE** — `skills/technical-indicators/SKILL.md`
Wilder's RSI + ATR implementation in Python with Decimal precision is reusable.
Create after T007 is also approved (indicators validated end-to-end in regime detection).

---

## 17. Status / Sign-off

| Role | Name | Status | Date |
|---|---|---|---|
| CTO (task created) | Opus/Fable | ✅ READY | 2026-08-31 |
| Implementation | Codex | ⏳ PENDING | — |
| Quant Review | Sonnet | ⏳ PENDING | — |
| Adversarial Review | Gemini | ⏳ PENDING | — |
| CTO Final Review | Opus/Fable | ⏳ PENDING | — |
| **Release Decision** | | ⏳ PENDING | — |

---

*End of Task Contract — T006 Technical Indicators*

