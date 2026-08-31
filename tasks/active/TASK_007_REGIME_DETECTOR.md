# TASK CONTRACT
# ═══════════════════════════════════════════════════════════════
# Task ID:        T007
# Task Name:      BTC Regime Detector
# Status:         READY (activate after T006 APPROVED)
# Priority:       P1 — T008-T010 cannot proceed without regime signal
# Owner Agent:    CODEX
# Reviewer:       SONNET (quant), GEMINI (adversarial), CTO (final)
# Created By:     Lead CTO (Opus/Fable)
# Created Date:   2026-08-31
# Target Branch:  feature/t007-regime-detector
# Depends On:     T005 APPROVED, T006 APPROVED
# Blocks:         T008 (SetupDetector), T009, T010 (strategy modules)
# ═══════════════════════════════════════════════════════════════

---

## 1. Objective

Implement the BTC 4H regime classifier.

The RegimeDetector reads BTC 4H closed candles from the CandleStore and
classifies the current market regime as BULLISH, BEARISH, NEUTRAL, or
UNDEFINED. The regime is the outermost filter: only signals that match
the regime direction are allowed to proceed to strategy evaluation.

---

## 2. Background

The A+ Scanner strategy requires a market regime filter before any trade
signal is evaluated. Per STRATEGY_SPEC.md §3:

- **BULLISH regime**: BTC EMA stack aligned bullish AND 24H change not in
  pump zone — LONG signals only
- **BEARISH regime**: BTC EMA stack aligned bearish AND 24H change not in
  dump zone — SHORT signals only
- **NEUTRAL**: BTC 24H change within ±1.5% — NO TRADE
- **UNDEFINED**: insufficient data, BTC data unavailable, or EMA stack
  not aligned in either direction — NO TRADE

The regime is computed on-demand when `classify()` is called. It does not
self-update; the caller (scan loop, T012) calls `classify()` on each cycle.

---

## 3. Source-of-Truth Documents

| Document | Sections Required |
|---|---|
| `AGENTS.md` | All — coding standards, escalation |
| `docs/STRATEGY_SPEC.md` | §3 (BTC Regime Classification — all rules) |
| `docs/DATA_CONTRACT.md` | §7 (freshness), §10 (BTC unavailable → UNDEFINED) |
| `src/scanner/models.py` | `Regime` enum: BULLISH, BEARISH, NEUTRAL, UNDEFINED |
| `src/scanner/config.py` | `regime_neutral_zone_pct=1.5`, `regime_pump_threshold_pct=8.0` |
| `src/scanner/indicators/__init__.py` | `ema` function (T006) |
| `src/scanner/candle_store/candle_store.py` | `CandleStore.get_closed_candles()`, `is_ready()` |

---

## 4. Scope

One class: `RegimeDetector`. No signal logic. No trade management.
No 1H confirmation logic (1H confirmation is T008's responsibility).

---

## 5. Allowed Files / Directories

```
src/scanner/regime/__init__.py          NEW
src/scanner/regime/detector.py          NEW
tests/unit/test_regime_detector.py     NEW
```

---

## 6. Forbidden Files / Directories

```
docs/STRATEGY_SPEC.md         — PROTECTED
docs/RISK_SPEC.md             — PROTECTED
AGENTS.md                     — PROTECTED
MASTER_PROJECT_BRIEF.md       — PROTECTED
src/scanner/indicators/       — do not modify (T006 output)
src/scanner/candle_store/     — do not modify (T005 output)
src/scanner/market_data/      — do not modify
src/scanner/config.py         — do not modify
src/scanner/models.py         — do not modify
src/scanner/strategy/         — T008-T010 scope
tasks/                        — do not touch
reviews/                      — do not touch
```

---

## 7. Requirements

### R-001 — RegimeDetector Class

```python
from decimal import Decimal
from scanner.candle_store.candle_store import CandleStore
from scanner.config import ScannerConfig
from scanner.models import Candle, Regime

class RegimeDetector:
    """Classify the current BTC 4H market regime for the A+ Scanner."""

    BTC_SYMBOL = "BTCUSDT"
    PRIMARY_INTERVAL = "240"   # 4H in minutes
    MIN_CANDLES = 200          # EMA200 warmup requirement

    def __init__(self, candle_store: CandleStore, config: ScannerConfig) -> None:
        """Create a detector backed by the live CandleStore."""
        ...

    def classify(self) -> Regime:
        """Return the current BTC 4H market regime.

        Returns:
            Regime.BULLISH  — EMA stack bullish + 24H change not pumped
            Regime.BEARISH  — EMA stack bearish + 24H change not dumped
            Regime.NEUTRAL  — 24H change within neutral zone (±1.5%)
            Regime.UNDEFINED — insufficient data, indicators unavailable,
                               or EMA stack mixed (not cleanly bullish/bearish)
        """
        ...

    @property
    def last_regime(self) -> Regime:
        """Return the most recently computed regime (UNDEFINED before first call)."""
        ...

    @property
    def last_classified_at(self) -> datetime | None:
        """Return UTC timestamp of last classify() call, or None."""
        ...
```

### R-002 — Classification Logic

Read STRATEGY_SPEC.md §3 exactly. The logic is:

**Step 1 — Data availability check:**
```
candles = candle_store.get_closed_candles("BTCUSDT", "240", 200)
if len(candles) < 200:
    return Regime.UNDEFINED  # EMA200 warmup not met
```

**Step 2 — Compute 24H price change:**
```
# Most recent two candles give us a proxy for 24H change.
# HOWEVER: the correct 24H change comes from the 24H ticker
# (Stats24H), NOT from a single candle comparison.
#
# T005 does not yet surface Stats24H; use the last close
# vs the close 24H ago (24 × 1H candles back, or 6 × 4H candles back)
# as the 4H-resolution approximation:

close_now    = candles[-1].close
close_24h_ago = candles[-7].close   # 6 periods × 4H = 24H lookback
                                     # candles[-7] is the open of 24H ago

change_pct = (close_now - close_24h_ago) / close_24h_ago * 100
```

**Step 3 — Neutral zone check (highest priority):**
```
if abs(change_pct) <= config.regime_neutral_zone_pct:   # ±1.5%
    return Regime.NEUTRAL
```

**Step 4 — Compute EMA stack:**
```
ema7   = ema(candles, period=7)
ema14  = ema(candles, period=14)
ema28  = ema(candles, period=28)
ema200 = ema(candles, period=200)

if any(v is None for v in [ema7, ema14, ema28, ema200]):
    return Regime.UNDEFINED
```

**Step 5 — Pump/dump zone check:**
```
if change_pct >= config.regime_pump_threshold_pct:   # +8% or more
    return Regime.UNDEFINED   # extreme pump — no trade regardless of stack

if change_pct <= -config.regime_pump_threshold_pct:  # -8% or worse
    return Regime.UNDEFINED   # extreme dump — no trade
```

**Step 6 — EMA stack classification:**
```
bullish_stack = ema7 > ema14 > ema28 > ema200
bearish_stack = ema7 < ema14 < ema28 < ema200

if change_pct > config.regime_neutral_zone_pct and bullish_stack:
    return Regime.BULLISH

if change_pct < -config.regime_neutral_zone_pct and bearish_stack:
    return Regime.BEARISH

return Regime.UNDEFINED   # mixed stack or direction mismatch
```

### R-003 — Caching

`classify()` stores the result in `_last_regime` and the call timestamp
in `_last_classified_at` before returning. These are exposed via the
`last_regime` and `last_classified_at` properties.

`classify()` is NOT idempotent — it always re-reads candles from the
CandleStore and recomputes. Caching with TTL is T012's responsibility.

### R-004 — Structured Logging

Use `get_logger("regime.detector")`:

```
INFO:  regime_classified — regime, change_pct (str), ema7, ema14, ema28, ema200
INFO:  regime_undefined_insufficient_data — candle_count, required=200
INFO:  regime_undefined_pump_detected — change_pct (str)
INFO:  regime_undefined_mixed_stack — ema7, ema14, ema28, ema200
```

All Decimal/float values must be logged as `str()` — do not pass raw
Decimal or float to structlog.

### R-005 — Public Interface

```python
# src/scanner/regime/__init__.py
from scanner.regime.detector import RegimeDetector
__all__ = ["RegimeDetector"]
```

Downstream imports: `from scanner.regime import RegimeDetector`

---

## 8. Non-Goals

- Do NOT implement 1H confirmation logic (that is T008's job)
- Do NOT implement signal scoring (T008-T010 scope)
- Do NOT cache the regime with a TTL (T012 scope)
- Do NOT subscribe to WebSocket or call REST directly
- Do NOT modify `Regime` enum (it is already defined in `scanner.models`)
- Do NOT compute RSI or ATR (not needed for regime classification)

---

## 9. Interfaces / Contracts

```python
from scanner.regime import RegimeDetector
from scanner.models import Regime

detector = RegimeDetector(candle_store=store, config=config)
regime: Regime = detector.classify()

assert regime in (Regime.BULLISH, Regime.BEARISH, Regime.NEUTRAL, Regime.UNDEFINED)
```

Import path must remain stable after delivery.

---

## 10. Acceptance Criteria

| AC-ID | Criterion | Verification |
|---|---|---|
| AC-001 | Returns UNDEFINED when fewer than 200 candles | `test_undefined_on_insufficient_data` |
| AC-002 | Returns NEUTRAL when \|change_pct\| <= 1.5% | `test_neutral_zone_positive` + `test_neutral_zone_negative` |
| AC-003 | Returns UNDEFINED when change_pct >= +8% (pump) | `test_pump_zone_returns_undefined` |
| AC-004 | Returns UNDEFINED when change_pct <= -8% (dump) | `test_dump_zone_returns_undefined` |
| AC-005 | Returns BULLISH when stack aligned + change_pct in (1.5%, 8%) | `test_bullish_regime_full_alignment` |
| AC-006 | Returns BEARISH when stack aligned + change_pct in (-8%, -1.5%) | `test_bearish_regime_full_alignment` |
| AC-007 | Returns UNDEFINED when stack is mixed (not cleanly bull/bear) | `test_undefined_mixed_ema_stack` |
| AC-008 | Returns UNDEFINED when any EMA is None | `test_undefined_when_ema_returns_none` |
| AC-009 | `last_regime` is UNDEFINED before first `classify()` | `test_last_regime_initial_state` |
| AC-010 | `last_regime` updated after `classify()` | `test_last_regime_updated_after_classify` |
| AC-011 | `last_classified_at` is None before first call | `test_last_classified_at_initial_none` |
| AC-012 | `last_classified_at` set to UTC after call | `test_last_classified_at_set_after_classify` |
| AC-013 | Logs INFO with full EMA values on BULLISH | `test_bullish_logs_info` |
| AC-014 | Logs INFO with insufficient data on UNDEFINED | `test_undefined_logs_info` |
| AC-015 | `mypy src/ --strict` passes | CI |
| AC-016 | `ruff check src/` passes | CI |
| AC-017 | Full suite ≥ 130 tests passing | `pytest tests/ -v` |

---

## 11. Required Tests

**File**: `tests/unit/test_regime_detector.py`

Use `unittest.mock.MagicMock` for `CandleStore` and helpers to produce
synthetic candle sequences. All tests are synchronous (classify() is sync).

```
test_undefined_when_fewer_than_200_candles
test_neutral_when_change_within_positive_1_5_pct
test_neutral_when_change_within_negative_1_5_pct
test_neutral_at_exact_boundary_1_5_pct
test_undefined_when_change_exceeds_pump_threshold_8_pct
test_undefined_when_change_below_dump_threshold_neg_8_pct
test_bullish_regime_when_stack_aligned_and_positive_change
test_bearish_regime_when_stack_aligned_and_negative_change
test_undefined_when_ema_stack_partially_mixed
test_undefined_when_ema_returns_none_insufficient_data
test_last_regime_is_undefined_before_first_classify
test_last_regime_updated_after_classify_call
test_last_classified_at_is_none_before_classify
test_last_classified_at_set_to_utc_after_classify
test_regime_logs_info_on_bullish
test_regime_logs_info_on_insufficient_data
test_classify_does_not_raise_on_empty_store
```

---

## 12. Expected Deliverables

```
src/scanner/regime/__init__.py         NEW
src/scanner/regime/detector.py         NEW
tests/unit/test_regime_detector.py    NEW
```

---

## 13. Failure / Escalation Conditions

STOP and escalate if:

| Condition | Action |
|---|---|
| STRATEGY_SPEC.md §3 contains ambiguity about EMA stack definition | Quote exact text and escalate |
| The 24H change proxy (6 × 4H lookback) conflicts with how STRATEGY_SPEC.md defines 24H change | Escalate — do not substitute a different formula |
| `Regime` enum is missing a required state | Escalate — do not modify `scanner.models` without authorization |
| CandleStore.get_closed_candles() signature differs from T005 delivery | Escalate — do not adapt without authorization |

---

## 14. Completion Report Requirements

```
Task:       T007 — BTC Regime Detector
Agent:      CODEX

Summary:    [2-3 sentences]

Files Created:      [list]
Tests Added:        [count and names]
Tests Run:          pytest tests/ -v — [N] passed (target ≥ 130)
Tests Failed:       0

Regime Classification Verification:
  BULLISH scenario: [candle setup description] → BULLISH ✅
  BEARISH scenario: [candle setup description] → BEARISH ✅
  NEUTRAL scenario: [change_pct = X%] → NEUTRAL ✅
  UNDEFINED (pump): [change_pct = +8.1%] → UNDEFINED ✅
  UNDEFINED (mixed EMA): [stack setup] → UNDEFINED ✅

Recommended Next Step: T008 (SetupDetector) — both T006 and T007 approved
```

---

## 15. Review Plan

### Automated

```bash
pytest tests/unit/test_regime_detector.py -v --cov=src/scanner/regime
ruff check src/scanner/regime/
black --check src/scanner/regime/
mypy src/ --strict
```

### SONNET Quantitative Review

Focus:
- 24H proxy formula: is `candles[-7]` correct for a 6×4H lookback?
- Neutral zone: is boundary inclusive (`<=`) or exclusive (`<`)?
- Pump zone: does `>= 8%` (not `> 8%`) match STRATEGY_SPEC.md exactly?
- EMA stack: is `ema7 > ema14 > ema28 > ema200` the exact condition?
- Step ordering: does neutral zone check happen BEFORE EMA computation?

Output: `reviews/sonnet/TASK_007_QUANT_REVIEW.md`

### GEMINI Adversarial Review

Focus:
- What if BTCUSDT has exactly 200 candles but they're all the same price?
- What if close_24h_ago == 0 (division by zero in change_pct)?
- What if candles[-7] doesn't exist (fewer than 7 candles)?
- Pump check before EMA check — could this hide a bug?

Output: `reviews/gemini/TASK_007_RED_TEAM.md`

### CTO Review

Focus:
- STRATEGY_SPEC.md §3 compliance — every rule implemented exactly
- UNDEFINED returned defensively in all ambiguous cases
- No 1H confirmation logic leaked in (that is T008's job)

Output: `reviews/opus/TASK_007_FINAL_REVIEW.md`

---

## 16. Skill Extraction Decision

After T007 approval: **DEFERRED** — combine into `skills/technical-indicators/SKILL.md`
alongside T006. Regime detection is tightly coupled to the indicator functions.

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

*End of Task Contract — T007 BTC Regime Detector*
