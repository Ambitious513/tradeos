# RISK_SPEC.md — A+ Scanner Risk Specification
# Version: 1.0 (GATE-1 APPROVED)
# Authority: Lead CTO
# Last Updated: 2026-08-31

---

> **PROTECTED DOCUMENT**
> Risk limits require Human Approval (GATE-5) before modification.
> See AGENTS.md Article 6.

> **PRIORITY**: Risk controls have UNCONDITIONAL priority over strategy signals.
> A strategy signal that cannot pass risk validation is REJECTED. Period.

---

## 1. CORE RISK PARAMETERS

| Parameter | Value | Notes |
|---|---|---|
| Risk per trade | $5.00 USD | Fixed; not a percentage |
| Daily trade limit | 5 trades | Calendar day, UTC midnight reset |
| Daily loss limit | -$25.00 USD | 5 × max risk; halt day on breach |
| Daily profit lock | +$50.00 USD | 10:1 daily profit:risk; halt new setups |
| Taker fee per side | 0.055% | Bybit USDT linear default |
| Slippage per fill | 0.05% | Conservative estimate |
| Minimum R:R | 2.0 | Hard disqualification below this |

---

## 2. POSITION SIZING FORMULA

### Step 1: Risk Distance

```python
risk_distance = abs(entry_price - stop_price)
risk_distance_pct = risk_distance / entry_price
```

### Step 2: Gross Position Size (USDT notional)

```python
risk_usd = 5.00  # fixed
position_size_usdt = risk_usd / risk_distance_pct
```

### Step 3: Quantity (contracts)

```python
raw_qty = position_size_usdt / entry_price
```

### Step 4: Exchange Precision Rounding

```python
# Round DOWN to nearest lot_size increment (never round up — never risk more than $5)
qty = floor(raw_qty / lot_size) * lot_size
```

### Step 5: Minimum Order Validation

```python
if qty < min_order_qty:
    raise DisqualifiedError("Position size below exchange minimum")
```

### Step 6: Fee Calculation

```python
taker_fee_rate = 0.00055
fee_entry = qty * entry_price * taker_fee_rate
fee_exit = qty * tp_or_sl_price * taker_fee_rate
total_fee = fee_entry + fee_exit
```

### Step 7: Slippage Estimate

```python
slippage_rate = 0.0005
slippage_entry = qty * entry_price * slippage_rate
slippage_exit = qty * tp_or_sl_price * slippage_rate
total_slippage = slippage_entry + slippage_exit
```

### Step 8: Effective Risk Validation

```python
effective_risk = risk_usd + total_fee + total_slippage
# Log effective_risk for monitoring
# If effective_risk > risk_usd * 1.5: log WARNING (unexpectedly wide fees/slippage)
```

---

## 3. DAILY RISK TRACKING

The risk engine maintains a `DailySession` object that resets at UTC midnight.

```python
@dataclass
class DailySession:
    date: date                    # UTC date
    trades_taken: int             # count of completed fills
    realized_pnl: Decimal         # sum of closed trade PnL (after fees)
    open_positions_count: int     # currently open paper/live positions
    is_halted: bool               # True = no new signals accepted today
    halt_reason: str | None       # human-readable halt reason
```

### Halt Conditions (trigger `is_halted = True`)

```
Condition 1: trades_taken >= 5         → "Daily trade limit reached"
Condition 2: realized_pnl <= -25.00    → "Daily loss limit reached"
Condition 3: realized_pnl >= +50.00    → "Daily profit lock triggered"
Condition 4: Risk engine exception     → "Risk engine failure"
```

When halted:
- No new DETECTED signals are accepted
- Existing ACTIVE positions continue to run (exits are not blocked)
- System sends alert notification
- Halt resets at UTC midnight

---

## 4. STOP LOSS SPECIFICATION

### Short Setup Stop

```python
# Structural stop
structural_stop = max(candle[-1].high, candle[-2].high, candle[-3].high)
structural_stop = structural_stop * (1 + 0.001)  # +0.1% buffer

# ATR stop
atr_stop = entry_price + (1.5 * atr14)

# Use the wider stop (further from entry for safety)
stop_price = max(structural_stop, atr_stop)
```

### Long Setup Stop

```python
# Structural stop
structural_stop = min(candle[-1].low, candle[-2].low, candle[-3].low)
structural_stop = structural_stop * (1 - 0.001)  # -0.1% buffer

# ATR stop
atr_stop = entry_price - (1.5 * atr14)

# Use the wider stop (further from entry for safety)
stop_price = min(structural_stop, atr_stop)
```

---

## 5. TAKE PROFIT SPECIFICATION

```python
# Short
risk_distance = stop_price - entry_price  # positive
take_profit = entry_price - (2.0 * risk_distance)

# Long
risk_distance = entry_price - stop_price  # positive
take_profit = entry_price + (2.0 * risk_distance)

# Validation
rr_ratio = (abs(entry_price - take_profit)) / (abs(entry_price - stop_price))
if rr_ratio < 2.0:
    raise DisqualifiedError(f"R:R {rr_ratio:.2f} below minimum 2.0")
```

---

## 6. EXCHANGE PRECISION

Stop and take profit prices must be rounded to the symbol's `tick_size`:

```python
# Round stop/TP to nearest tick_size
# For SHORT: round stop UP (further from entry), round TP DOWN (closer to entry) — conservative
# For LONG: round stop DOWN (further from entry), round TP UP (closer to entry) — conservative

def round_to_tick(price: Decimal, tick_size: Decimal, direction: str) -> Decimal:
    ticks = price / tick_size
    if direction == "up":
        return ceil(ticks) * tick_size
    else:
        return floor(ticks) * tick_size
```

---

## 7. DUPLICATE SIGNAL PREVENTION

```python
def is_duplicate(symbol: str, direction: Direction, active_signals: list[Signal]) -> bool:
    for signal in active_signals:
        if signal.symbol == symbol:
            if signal.state in [ARMED, TRIGGERED, ACTIVE]:
                return True
    return False
```

A new setup for a symbol where an active signal already exists is **REJECTED**.

---

## 8. RISK ENGINE FAILURE BEHAVIOR

```
ANY of the following → immediate NO TRADE:

- DivisionByZero in position sizing
- Negative position size
- qty is NaN or Infinity
- stop_price == entry_price (zero risk distance)
- stop_price on wrong side of entry
- take_profit on wrong side of entry
- qty < min_order_qty
- Risk engine raises any unhandled exception
- DailySession.is_halted == True

On any failure:
  1. Log ERROR with full context (symbol, entry, stop, calculation step)
  2. Set signal state to CANCELLED with reason "risk_engine_failure"
  3. Send system alert to operators
  4. Do NOT raise exception to caller (return None gracefully)
```

---

## 9. MARGIN AND LEVERAGE

Paper trading operates with:
```
Leverage: 1x (no leverage assumed)
Margin type: Isolated
Margin required: position_size_usdt / leverage
```

Note: Actual margin requirements depend on exchange leverage settings.
For paper trading, leverage = 1× (conservative). Actual live execution leverage
must be separately configured and human-approved.

---

## 10. MINIMUM TRADE VIABILITY CHECK

Before any signal reaches TRIGGERED state, verify:

```python
def is_viable(risk_calc: RiskCalculation, symbol_info: SymbolInfo) -> bool:
    checks = [
        risk_calc.qty >= symbol_info.min_order_qty,
        risk_calc.rr_ratio >= 2.0,
        risk_calc.risk_usd <= 5.01,  # sanity check (fee rounding tolerance)
        risk_calc.stop_price > 0,
        risk_calc.tp_price > 0,
        risk_calc.entry_price > 0,
        # Short specific
        (risk_calc.direction == SHORT and risk_calc.stop_price > risk_calc.entry_price),
        # Long specific
        (risk_calc.direction == LONG and risk_calc.stop_price < risk_calc.entry_price),
    ]
    return all(checks)
```

---

## 11. OPEN QUESTIONS FOR GATE-1 REVIEW

1. Confirm $5 risk per trade is correct
2. Confirm 5 trades per day as maximum
3. Confirm -$25 daily loss limit (= 5 max losses)
4. Confirm +$50 daily profit lock
5. Confirm 0.055% taker fee rate (or provide different rate)
6. Confirm 0.05% slippage assumption
7. Confirm 2.0:1 minimum R:R hard floor
8. Confirm 1× leverage assumption for paper trading

---

*End of RISK_SPEC.md v0.1-DRAFT*

