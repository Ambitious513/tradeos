# TASK CONTRACT
# ═══════════════════════════════════════════════════════════════
# Task ID:        T013
# Task Name:      Alert Engine — Telegram + Discord Signal Notifications
# Status:         APPROVED — 2026-09-01
# Priority:       P1
# Owner Agent:    CODEX
# Reviewer:       GEMINI (failure isolation), CTO (final)
# Created By:     Lead CTO (Opus/Fable)
# Created Date:   2026-09-01
# Depends On:     T010 APPROVED (SignalManager/ActiveSignal)
#                 T011 APPROVED (RiskCalculation, DailySession)
#                 T002 APPROVED (ScannerConfig, get_logger)
# Blocks:         Nothing (T014+ are v1.1 tasks, separate track)
# ═══════════════════════════════════════════════════════════════

---

## 1. Objective

Implement a failure-isolated alert engine that sends structured notifications to
Telegram and Discord when key signal lifecycle events occur.

A failure in the alert engine (network error, bad token, timeout, encoding error)
must NEVER raise to the caller, NEVER crash the scan loop, and NEVER cause a trade
to be missed. Alerting is best-effort observability — not a control path.

---

## 2. Background

`ScannerConfig` already contains:
```
telegram_bot_token: str = ""    # empty = Telegram disabled
telegram_chat_id:   str = ""    # empty = Telegram disabled
discord_webhook_url: str = ""   # empty = Discord disabled
```

If a channel is unconfigured (empty string), it is silently skipped.
Both channels may be active simultaneously.

---

## 3. Source-of-Truth Documents

| Document | Sections Required |
|---|---|
| `AGENTS.md` | All |
| `src/scanner/config.py` | `telegram_bot_token`, `telegram_chat_id`, `discord_webhook_url` |
| `src/scanner/strategy/signal_manager.py` | `ActiveSignal` dataclass fields |
| `src/scanner/risk/risk_engine.py` | `RiskCalculation`, `DailySession` dataclass fields |
| `src/scanner/models.py` | `SignalState`, `Direction`, `Regime` |

---

## 4. Scope

```
src/scanner/alerting/__init__.py       NEW
src/scanner/alerting/alert_engine.py   NEW
tests/unit/test_alert_engine.py        NEW
```

---

## 5. Forbidden Files / Directories

```
docs/STRATEGY_SPEC.md       — PROTECTED
docs/RISK_SPEC.md           — PROTECTED
AGENTS.md                   — PROTECTED
src/scanner/scan_loop.py    — do not modify (T012)
src/scanner/strategy/       — do not modify
src/scanner/risk/           — do not modify
src/scanner/models.py       — do not modify
```

---

## 6. Requirements

### R-001 — AlertEngine Class

```python
class AlertEngine:
    """Send failure-isolated signal lifecycle alerts to Telegram and Discord.

    Never raises to caller. All network errors are caught, logged, and swallowed.
    Channels are silently skipped when unconfigured (empty token/url).
    """

    def __init__(self, config: ScannerConfig) -> None:
        """Read channel config once; build enabled channel list."""
        ...

    async def send_signal_triggered(
        self,
        signal: ActiveSignal,
        calculation: RiskCalculation,
    ) -> None:
        """Alert: A+ setup found — entry pending at next candle open.

        Sent when: ScanLoop detects a TRIGGERED signal with approved risk.
        """

    async def send_position_opened(
        self,
        signal: ActiveSignal,
        confirmed_entry: Decimal,
        calculation: RiskCalculation,
    ) -> None:
        """Alert: Position is now ACTIVE — confirmed entry price known.

        Sent when: ScanLoop calls mark_active() on a TRIGGERED signal.
        """

    async def send_position_closed(
        self,
        signal: ActiveSignal,
        outcome: SignalState,   # TP_HIT or SL_HIT
        net_pnl: Decimal,
        daily_pnl: Decimal,
    ) -> None:
        """Alert: Position closed at TP or SL.

        Sent when: ScanLoop calls mark_terminal() with TP_HIT or SL_HIT.
        """

    async def send_daily_halted(
        self,
        session: DailySession,
    ) -> None:
        """Alert: Daily session halted — no more trades today.

        Sent when: ScanLoop calls _halt_session_if_needed().
        """
```

### R-002 — Message Formatting

Each alert event has a fixed plain-text template. Use emoji for readability.
All Decimal values rendered with 2–4 decimal places as appropriate.

**TRIGGERED template**:
```
🎯 A+ SIGNAL TRIGGERED
Symbol:    {symbol}
Direction: {direction} ({regime})
Entry:     ~{estimated_entry:.4f} USDT (next open)
Stop:      {stop_price:.4f} USDT
Target:    {take_profit:.4f} USDT
R:R:       {rr_ratio:.2f}:1
Score:     {score}/100
Qty:       {qty}
Risk:      ${effective_risk_usd:.4f}
```

**POSITION OPENED template**:
```
✅ POSITION OPENED
Symbol:    {symbol}
Direction: {direction}
Entry:     {confirmed_entry:.4f} USDT
Stop:      {stop_price:.4f} USDT
Target:    {take_profit:.4f} USDT
```

**TP HIT template**:
```
💰 TAKE PROFIT HIT
Symbol:    {symbol}
Direction: {direction}
Net PnL:   +${net_pnl:.4f}
Daily PnL: ${daily_pnl:.4f}
```

**SL HIT template**:
```
🛑 STOP LOSS HIT
Symbol:    {symbol}
Direction: {direction}
Net PnL:   ${net_pnl:.4f}
Daily PnL: ${daily_pnl:.4f}
```

**DAILY HALTED template**:
```
⛔ DAILY HALT — NO MORE TRADES
Reason:      {halt_reason}
Realized:    ${realized_pnl:.4f}
Trades:      {trades_taken}
```

### R-003 — Telegram Transport

```python
class _TelegramChannel:
    """Send messages via Telegram Bot API using aiohttp."""

    _API_URL = "https://api.telegram.org/bot{token}/sendMessage"
    _TIMEOUT_SECONDS = 5.0

    async def send(self, text: str) -> None:
        """POST message to Telegram. Catch ALL exceptions — never raise."""
```

Payload: `{"chat_id": chat_id, "text": text, "parse_mode": "HTML"}`

Failure behavior:
- HTTP 4xx (bad token, bad chat_id): log ERROR once; disable channel for session
- HTTP 5xx: log WARNING; retry once after 1s; then swallow
- Network timeout: log WARNING; swallow
- Any other exception: log ERROR; swallow

### R-004 — Discord Transport

```python
class _DiscordChannel:
    """Send messages via Discord Incoming Webhook using aiohttp."""

    _TIMEOUT_SECONDS = 5.0

    async def send(self, text: str) -> None:
        """POST message to Discord webhook. Catch ALL exceptions — never raise."""
```

Payload: `{"content": text}`

Same failure behavior as Telegram (see R-003).

### R-005 — HTTP Dependency

Use `aiohttp` for all HTTP calls. Add `aiohttp` to `pyproject.toml` dependencies.
Do NOT use `httpx`, `requests`, or any other HTTP library.
Do NOT use `urllib` directly.

### R-006 — Disabled Channel Behaviour

```python
# At __init__ time:
self._telegram_enabled = bool(config.telegram_bot_token and config.telegram_chat_id)
self._discord_enabled  = bool(config.discord_webhook_url)

# At send time — if channel not enabled: return silently, log DEBUG
```

No exception or warning is raised when a channel is unconfigured.

### R-007 — Failure Isolation Contract

Every `send_*` method in `AlertEngine` must:
1. Wrap the entire body in `try/except Exception`
2. On exception: `logger.error("alert_send_failed", channel=..., event=..., exception_type=..., message=...)`
3. Return `None` — never re-raise

### R-008 — Logging

Use `get_logger("alerting")`.

```
DEBUG: alert_channel_disabled  — channel, reason
INFO:  alert_sent              — channel, event, symbol
WARN:  alert_http_5xx          — channel, status_code, event
WARN:  alert_retry             — channel, event
ERROR: alert_send_failed       — channel, event, exception_type, message
ERROR: alert_4xx_disabling     — channel, status_code (disable for session)
```

### R-009 — Public Interface

```python
# src/scanner/alerting/__init__.py
from scanner.alerting.alert_engine import AlertEngine
__all__ = ["AlertEngine"]
```

---

## 7. Non-Goals

- Do NOT alert on EXPIRED or CANCELLED signals (noise)
- Do NOT format as Markdown tables (plain text + emoji only)
- Do NOT implement SMS, email, or any other channel
- Do NOT block the event loop — all HTTP calls are async
- Do NOT retry more than once on 5xx
- Do NOT implement persistent retry queues
- Do NOT rate-limit messages (out of scope for paper trading volumes)

---

## 8. Acceptance Criteria

| AC-ID | Criterion | Test |
|---|---|---|
| AC-001 | Disabled Telegram: send returns silently | `test_telegram_disabled_returns_silently` |
| AC-002 | Disabled Discord: send returns silently | `test_discord_disabled_returns_silently` |
| AC-003 | Network exception inside send_signal_triggered → no raise | `test_network_error_does_not_raise` |
| AC-004 | HTTP 4xx → channel disabled for session; log ERROR | `test_4xx_disables_channel` |
| AC-005 | HTTP 5xx → retry once; log WARN; swallow | `test_5xx_retries_once` |
| AC-006 | send_signal_triggered formats correct fields | `test_triggered_message_contains_required_fields` |
| AC-007 | send_position_opened formats correct fields | `test_opened_message_contains_required_fields` |
| AC-008 | TP_HIT message uses 💰 emoji; SL_HIT uses 🛑 | `test_outcome_emoji_correct` |
| AC-009 | send_daily_halted formats halt_reason and trades_taken | `test_halted_message_correct` |
| AC-010 | Both channels send simultaneously (not sequentially) | `test_both_channels_send_concurrently` |
| AC-011 | Exception in Telegram does not prevent Discord send | `test_telegram_failure_does_not_block_discord` |
| AC-012 | `mypy src/ --strict` passes | CI |
| AC-013 | `ruff check src/` passes | CI |
| AC-014 | Full suite >= 311 tests passing | `pytest tests/ -v` |

---

## 9. Required Tests

**File**: `tests/unit/test_alert_engine.py`

All HTTP calls mocked with `unittest.mock.AsyncMock` / `aioresponses` (or `AsyncMock`
patching `aiohttp.ClientSession`).

```
test_telegram_disabled_when_token_empty
test_telegram_disabled_when_chat_id_empty
test_discord_disabled_when_webhook_empty
test_send_triggered_returns_silently_when_all_disabled
test_network_timeout_in_telegram_does_not_raise
test_network_timeout_in_discord_does_not_raise
test_generic_exception_in_telegram_does_not_raise
test_generic_exception_in_discord_does_not_raise
test_4xx_response_disables_telegram_channel
test_5xx_response_triggers_one_retry_telegram
test_5xx_retry_still_fails_swallowed_silently
test_triggered_message_contains_symbol
test_triggered_message_contains_direction
test_triggered_message_contains_entry_stop_tp
test_triggered_message_contains_rr_and_score
test_opened_message_contains_confirmed_entry
test_tp_hit_uses_correct_emoji_and_pnl
test_sl_hit_uses_correct_emoji_and_pnl
test_daily_halted_contains_reason_and_trades
test_both_channels_called_on_triggered_event
test_telegram_exception_does_not_block_discord_send
test_discord_exception_does_not_block_telegram_send
test_decimal_values_formatted_to_4dp
test_send_position_closed_positive_pnl_formatting
test_send_position_closed_negative_pnl_formatting
test_alert_engine_logs_sent_on_success
```

---

## 10. Escalation Conditions

| Condition | Action |
|---|---|
| `aiohttp` not available or version conflict | Quote pyproject.toml; escalate |
| `ActiveSignal` does not expose `.score` field | Quote signal_manager.py fields; escalate — do NOT invent field |
| `ActiveSignal` does not expose `.regime` field | Same — escalate |

---

## 11. Completion Report Requirements

```
Task:       T013 — Alert Engine
Agent:      CODEX

Summary: [2-3 sentences]

Files Created:  [list]
Tests Added:    [count — target >= 26]
Tests Run:      pytest tests/ -v — [N] passed (target >= 311)
Tests Failed:   0

Failure Isolation Verified:
  Network timeout → no raise: ✅
  4xx → channel disabled: ✅
  Telegram failure → Discord still sends: ✅

Recommended Next Step: Await v1.1 human decisions (T014 blocked).
```

---

## 12. Review Plan

### GEMINI Adversarial Review (primary — failure isolation critical)
- Every `send_*` method: does it have a bare `except Exception` at top level?
- Does Telegram 4xx actually disable the channel for subsequent sends?
- Does channel A failure actually not prevent channel B from executing?
- Is `asyncio.gather` (or equivalent) used to send both channels concurrently?
- Does a malformed message (None field, encoding error) get caught before the HTTP call?

### CTO Review
- aiohttp dependency added to pyproject.toml
- No blocking HTTP calls (all async)
- Disabled channel: returns silently, no WARNING
- Both channels concurrent (not sequential)
- All Decimal rendered as strings before formatting

---

## 13. Status / Sign-off

| Role | Status | Date |
|---|---|---|
| CTO (created) | ✅ READY | 2026-09-01 |
| Implementation | ⏳ PENDING | — |
| Gemini adversarial | ⏳ PENDING | — |
| CTO final | ⏳ PENDING | — |
| **Release Decision** | ⏳ PENDING | — |

---

*End of Task Contract — T013 Alert Engine*

