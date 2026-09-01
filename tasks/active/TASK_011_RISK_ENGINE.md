# TASK CONTRACT
# ═══════════════════════════════════════════════════════════════
# Task ID:        T011
# Task Name:      RiskEngine — Position Sizing and Daily Limits
# Status:         READY
# Priority:       P1
# Owner Agent:    CODEX
# Reviewer:       SONNET (quant), GEMINI (adversarial), CTO (final)
# Created By:     Lead CTO (Opus/Fable)
# Created Date:   2026-09-01
# Depends On:     T002 APPROVED (models), T003 APPROVED (SymbolInfo)
# Blocks:         T012 (ScanLoop)
# ═══════════════════════════════════════════════════════════════

---

## 1. Objective

Implement the risk calculation engine: position sizing (steps 1–8 from
RISK_SPEC.md §2), exchange precision rounding (§6), daily limit checks (§3),
viability validation (§10), and failure behavior (§8).

T011 is **pure computation + in-process daily session state**.
No database access. No network calls. No exchange interaction.
T012 (ScanLoop) owns the daily session and passes it in.

---

## 2. Background

All risk rules are GATE-1 APPROVED and IMMUTABLE per AGENTS.md Article 5.
Changes to any risk parameter require GATE-5 human approval.

---

## 3. Source-of-Truth Documents

| Document | Sections Required |
|---|---|
| `AGENTS.md` | All |
| `docs/RISK_SPEC.md` | §1 (parameters), §2 (position sizing), §3 (daily session), §6 (exchange precision), §8 (failure behavior), §10 (viability check) |
| `src/scanner/market_data/models.py` | `SymbolInfo` (tick_size, lot_size, min_order_qty) |
| `src/scanner/models.py` | `Direction` |
| `src/scanner/config.py` | `ScannerConfig` (risk_usd, fee_rate, slippage_rate, etc.) |

---

## 4. Scope

Position sizing, precision rounding, daily session tracking, and viability
checks. No signal state mutation. No DB writes. No exchange calls.

---

## 5. Allowed Files / Directories

```
src/scanner/risk/__init__.py          NEW
src/scanner/risk/risk_engine.py       NEW
tests/unit/test_risk_engine.py        NEW
```

---

## 6. Forbidden Files / Directories

```
docs/RISK_SPEC.md               — PROTECTED
docs/STRATEGY_SPEC.md           — PROTECTED
AGENTS.md                       — PROTECTED
src/scanner/strategy/           — do not modify (T008-T010)
src/scanner/market_data/        — do not modify
src/scanner/models.py           — do not modify
```

---

## 7. Requirements

### R-001 — DailySession Dataclass

```python
@dataclass
class DailySession:
    """Track daily risk limits for one UTC calendar day.

    Source: docs/RISK_SPEC.md §3.
    Mutable — updated by T012 as trades close.
    """
    date: date                       # UTC date (reset key)
    trades_taken: int = 0            # count of completed fills
    realized_pnl: Decimal = field(default_factory=lambda: Decimal(0))
    open_positions_count: int = 0    # currently open paper/live positions
    is_halted: bool = False
    halt_reason: str | None = None

    def halt(self, reason: str) -> None:
        """Irreversibly halt this session with a reason string."""
        self.is_halted = True
        self.halt_reason = reason
```

### R-002 — RiskCalculation Dataclass

```python
@dataclass(frozen=True)
class RiskCalculation:
    """All computed risk values for one approved signal.

    Produced by RiskEngine.calculate(); consumed by T012.
    """
    symbol: str
    direction: Direction
    entry_price: Decimal       # estimated (trigger candle close)
    stop_price: Decimal        # rounded to tick_size
    take_profit: Decimal       # rounded to tick_size
    qty: Decimal               # floored to lot_size
    position_size_usdt: Decimal
    risk_distance_pct: Decimal
    fee_cost_usd: Decimal      # total both sides (entry + exit)
    slippage_cost_usd: Decimal # total both sides
    effective_risk_usd: Decimal
    rr_ratio: Decimal
```

### R-003 — RiskDecision Dataclass

```python
@dataclass(frozen=True)
class RiskDecision:
    """Outcome of a risk approval check.

    approved=True  → calculation is populated; proceed to T012 execution.
    approved=False → calculation is None; reason explains the rejection.
    """
    approved: bool
    reason: str
    calculation: RiskCalculation | None = None
```

### R-004 — RiskEngine Class

```python
class RiskEngine:
    """Compute position size and enforce all risk limits.

    Source: docs/RISK_SPEC.md (GATE-1 APPROVED).
    All public methods return RiskDecision — never raise to caller.
    """

    def __init__(self, config: ScannerConfig) -> None:
        """Read risk constants once from config at construction time."""
        ...

    def approve(
        self,
        entry_price: Decimal,
        stop_price: Decimal,
        take_profit: Decimal,
        direction: Direction,
        symbol_info: SymbolInfo,
        daily_session: DailySession,
    ) -> RiskDecision:
        """Run the full risk pipeline and return one decision.

        Steps (in order):
          1. check_daily_limits(daily_session)   → reject if halted
          2. validate_price_geometry(...)         → reject bad stops/TPs
          3. calculate(...)                       → size position
          4. validate_viability(calculation)      → reject if below minimums
          5. Return RiskDecision(approved=True, calculation=...) on success

        Never raises. Any unhandled exception → RiskDecision(approved=False,
        reason="risk_engine_failure: <exception type>").
        """

    def check_daily_limits(self, session: DailySession) -> RiskDecision:
        """Return approved=False if any daily halt condition is met.

        Halt conditions (RISK_SPEC.md §3):
          trades_taken >= 5         → "Daily trade limit reached"
          realized_pnl <= -25.00   → "Daily loss limit reached"
          realized_pnl >= +50.00   → "Daily profit lock triggered"
          session.is_halted         → session.halt_reason

        Returns approved=True (no calculation) if within limits.
        """

    def calculate(
        self,
        entry_price: Decimal,
        stop_price: Decimal,
        take_profit: Decimal,
        direction: Direction,
        symbol_info: SymbolInfo,
    ) -> RiskDecision:
        """Compute position size following RISK_SPEC.md §2 steps 1–8.

        Step 1: risk_distance = abs(entry_price - stop_price)
                risk_distance_pct = risk_distance / entry_price

        Step 2: position_size_usdt = risk_usd / risk_distance_pct

        Step 3: raw_qty = position_size_usdt / entry_price

        Step 4: qty = floor(raw_qty / lot_size) * lot_size
                (NEVER round up — must not risk more than risk_usd)

        Step 5: if qty < min_order_qty → reject "position size below minimum"

        Step 6: fee_cost_usd = qty * entry_price * fee_rate
                              + qty * take_profit * fee_rate
                (use take_profit as exit price — winning scenario)

        Step 7: slippage_cost_usd = qty * entry_price * slippage_rate
                                   + qty * take_profit * slippage_rate

        Step 8: effective_risk_usd = risk_usd + fee_cost_usd + slippage_cost_usd
                if effective_risk_usd > risk_usd * 1.5: log WARNING
        """
```

### R-005 — Price Rounding (RISK_SPEC.md §6)

All stop and TP prices must be rounded to `symbol_info.tick_size`.
Rounding direction is conservative (wider stop, narrower TP):

```
SHORT stop  → ceil  to tick_size  (higher = wider, further above entry)
SHORT TP    → ceil  to tick_size  (higher = closer to entry, less reward)
LONG  stop  → floor to tick_size  (lower = wider, further below entry)
LONG  TP    → floor to tick_size  (lower = closer to entry, less reward)
```

Rounding is applied BEFORE viability validation — the rounded prices are
what appear in `RiskCalculation`. R:R is computed from rounded prices.

```python
def _round_price(
    price: Decimal, tick_size: Decimal, direction: str  # "up" or "down"
) -> Decimal:
    """Round price to nearest tick_size in the specified direction."""
```

### R-006 — Price Geometry Validation

```python
def _validate_price_geometry(
    entry: Decimal, stop: Decimal, tp: Decimal, direction: Direction
) -> RiskDecision | None:
    """Return a rejected RiskDecision for impossible price geometry.

    Returns None (geometry valid) or RiskDecision(approved=False).

    Checks (RISK_SPEC.md §8):
      - entry > 0, stop > 0, tp > 0
      - SHORT: stop > entry (stop above entry)
      - SHORT: tp < entry (TP below entry)
      - LONG:  stop < entry (stop below entry)
      - LONG:  tp > entry (TP above entry)
      - risk_distance > 0 (stop != entry)
    """
```

### R-007 — Viability Check (RISK_SPEC.md §10)

```python
def _validate_viability(
    calculation: RiskCalculation, symbol_info: SymbolInfo
) -> RiskDecision | None:
    """Return rejected RiskDecision for any viability failure.

    Checks (RISK_SPEC.md §10):
      - qty >= min_order_qty  (re-checked post-rounding)
      - rr_ratio >= 2.0
      - effective_risk_usd <= risk_usd * 1.5  (hard cap, not just warning)
      - stop_price > 0, tp_price > 0, entry_price > 0
      - SHORT: stop_price > entry_price
      - LONG:  stop_price < entry_price

    Returns None (viable) or RiskDecision(approved=False, reason=...).
    """
```

### R-008 — Logging

Use `get_logger("risk.engine")`.

```
INFO:  risk_approved     — symbol, qty, entry, stop, tp, rr_ratio, effective_risk_usd
INFO:  risk_rejected     — symbol, reason
WARN:  effective_risk_wide — symbol, effective_risk_usd, risk_usd (when > 1.5×)
ERROR: risk_engine_failure — symbol, exception_type, message
```

All Decimal values logged as `str()`.

### R-009 — Public Interface

```python
# src/scanner/risk/__init__.py
from scanner.risk.risk_engine import (
    DailySession,
    RiskCalculation,
    RiskDecision,
    RiskEngine,
)
__all__ = ["DailySession", "RiskCalculation", "RiskDecision", "RiskEngine"]
```

---

## 8. Non-Goals

- Do NOT write to database (T012 persists DailySession updates)
- Do NOT mutate `DailySession` (read-only access in RiskEngine)
- Do NOT call any exchange API
- Do NOT manage signal state transitions

---

## 9. Acceptance Criteria

| AC-ID | Criterion | Test |
|---|---|---|
| AC-001 | Position size floored to lot_size, never rounded up | `test_qty_floored_to_lot_size` |
| AC-002 | qty < min_order_qty → rejected | `test_rejected_below_min_qty` |
| AC-003 | Daily halt → rejected with correct reason | `test_daily_halt_rejects` |
| AC-004 | trades_taken >= 5 → rejected | `test_trade_limit_rejects` |
| AC-005 | realized_pnl <= -25.00 → rejected | `test_loss_limit_rejects` |
| AC-006 | realized_pnl >= +50.00 → rejected | `test_profit_lock_rejects` |
| AC-007 | SHORT: stop below entry → geometry rejected | `test_short_stop_below_entry_rejected` |
| AC-008 | LONG: stop above entry → geometry rejected | `test_long_stop_above_entry_rejected` |
| AC-009 | entry == stop (zero risk) → rejected | `test_zero_risk_distance_rejected` |
| AC-010 | R:R >= 2.0 after rounding passes viability | `test_rr_passes_viability` |
| AC-011 | SHORT stop rounded ceil to tick_size | `test_short_stop_rounded_up` |
| AC-012 | LONG stop rounded floor to tick_size | `test_long_stop_rounded_down` |
| AC-013 | Fee uses entry + TP exit (both sides) | `test_fee_calculated_both_sides` |
| AC-014 | effective_risk > 1.5× risk_usd → WARNING logged | `test_wide_effective_risk_warns` |
| AC-015 | Any exception in approve() → approved=False | `test_exception_in_approve_returns_false` |
| AC-016 | All Decimal arithmetic; no float in position sizing | `test_all_arithmetic_decimal` |
| AC-017 | `mypy src/ --strict` passes | CI |
| AC-018 | `ruff check src/` passes | CI |
| AC-019 | Full suite >= 255 tests passing | `pytest tests/ -v` |

---

## 10. Required Tests

**File**: `tests/unit/test_risk_engine.py`

```
test_known_position_size_calculation
test_qty_floored_to_lot_size_not_rounded_up
test_qty_exactly_on_lot_size_boundary
test_rejected_when_qty_below_min_order_qty
test_daily_halt_flag_rejects
test_trades_taken_5_rejects
test_trades_taken_4_passes
test_realized_pnl_at_loss_limit_rejects
test_realized_pnl_just_above_loss_limit_passes
test_realized_pnl_at_profit_lock_rejects
test_short_stop_below_entry_geometry_rejected
test_long_stop_above_entry_geometry_rejected
test_entry_equals_stop_zero_distance_rejected
test_short_stop_rounded_ceil_to_tick
test_long_stop_rounded_floor_to_tick
test_short_tp_rounded_ceil_to_tick
test_long_tp_rounded_floor_to_tick
test_fee_is_entry_plus_tp_exit_both_sides
test_slippage_is_entry_plus_tp_exit_both_sides
test_effective_risk_is_risk_plus_fee_plus_slippage
test_effective_risk_above_1_5x_logs_warning
test_rr_ratio_computed_from_rounded_prices
test_approve_integrates_all_steps_returns_approved
test_exception_in_approve_returns_false_not_raise
test_all_price_fields_in_risk_calculation_are_decimal
test_known_short_example_end_to_end
test_known_long_example_end_to_end
test_daily_session_halt_method_sets_reason
```

---

## 11. Escalation Conditions

STOP and escalate if:

| Condition | Action |
|---|---|
| `ScannerConfig` does not have a field for `risk_usd`, `fee_rate`, or `slippage_rate` | Quote config.py; escalate with field names found |
| `min_order_qty` field on SymbolInfo named differently than expected | Quote market_data/models.py |
| rounding direction is ambiguous for any specific case | Quote RISK_SPEC.md §6 + describe the ambiguity |

---

## 12. Completion Report Requirements

```
Task:       T011 — RiskEngine
Agent:      CODEX

Summary:    [2-3 sentences]

Files Created:  [list]
Tests Added:    [count — target >= 28]
Tests Run:      pytest tests/ -v — [N] passed (target >= 255)
Tests Failed:   0

Known Values Verified:
  Entry=100, Stop=102, TP=96, lot_size=0.01, min_order_qty=0.01:
    risk_distance_pct = 0.02
    position_size_usdt = 250.00
    raw_qty = 2.5
    qty (floored) = 2.50 ✅
    fee_cost = 2.5*100*0.00055 + 2.5*96*0.00055 = 0.1375 + 0.132 = 0.2695
    effective_risk = 5.00 + fees + slippage ✅

Recommended Next Step: T012 (ScanLoop)
```

---

## 13. Review Plan

### SONNET Quantitative Review
- Floor division for qty: `floor(raw_qty / lot_size) * lot_size` — never rounds up
- Fee computation: qty × entry_price × fee_rate + qty × take_profit × fee_rate
- Slippage: same formula
- R:R after rounding: must use rounded stop/TP, not pre-rounding values
- Effective risk cap: > 1.5× → WARNING; no hard rejection unless viability check fails

### GEMINI Adversarial Review
- Zero risk_distance_pct (entry == stop) → division by zero guard
- qty floors to 0.0 (very large risk distance) → minimum order rejection
- lot_size = 0 → guard required
- tick_size = 0 → guard required
- Negative realized_pnl at initialization → DailySession handles correctly
- Exception inside calculate() → approve() catches and returns False

### CTO Review
- All 8 position sizing steps implemented in correct order
- Rounding applied BEFORE viability check
- Fee uses take_profit as exit price (not stop)
- Never raises to caller

---

## 14. Status / Sign-off

| Role | Status | Date |
|---|---|---|
| CTO (created) | ✅ READY | 2026-09-01 |
| Implementation | ⏳ PENDING | — |
| Sonnet quant | ⏳ PENDING | — |
| Gemini adversarial | ⏳ PENDING | — |
| CTO final | ⏳ PENDING | — |
| **Release Decision** | ⏳ PENDING | — |

---

*End of Task Contract — T011 RiskEngine*
