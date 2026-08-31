# TASK_005_RED_TEAM.md
# Reviewer: GEMINI (Adversarial / Reliability)
# Task ID: T005
# Date: 2026-08-31

---

## Summary

Adversarial review of T005 CandleStore + UniverseManager. Focus areas: gap detection
correctness, FIFO eviction, forming-candle isolation, BTC bypass, dedup logic,
failure handling, and scope compliance.

---

## Findings

| # | Area | Status | Detail |
|---|---|---|---|
| R-01 | Gap formula correct | ✅ PASS | Line 141: `gap_candles = (elapsed_ms // interval_ms) - 1`. If elapsed = 2×interval, gap_candles=1 (one missing). Correct |
| R-02 | Gap only triggered on forward-looking arrivals | ✅ PASS | Line 96: `candle.open_time > latest.open_time` guard before gap check. Backward insertions fall through to dedup |
| R-03 | Gap fill `end_time_ms` excludes new candle | ✅ PASS | Line 148: `end_time_ms = new_candle.open_time_ms - 1`. REST returns candles strictly before new candle |
| R-04 | Forming candles never enter closed buffer | ✅ PASS | `on_candle` line 87: `if not candle.is_closed: _forming_candles[key] = candle; return`. Never reaches buffer |
| R-05 | Defensive forming-candle-in-buffer check | ✅ PASS | `get_closed_candles()` lines 112-114: re-filters buffer for is_closed; logs ERROR if mismatch |
| R-06 | FIFO eviction evicts oldest | ✅ PASS | `_insert_closed` line 193: buffer sorted by open_time; `del buffer[:max(0, len-buffer_size)]` removes from front (oldest) |
| R-07 | Dedup by open_time — duplicate rejected | ✅ PASS | Two guards: `on_candle` line 92 (live path) and `_insert_closed` line 189 (shared path) |
| R-08 | BTC always included after volume filter | ✅ PASS | `universe_manager.py` line 66: `qualified_symbols.add("BTCUSDT")` after set comprehension |
| R-09 | BTC prefill failure → ERROR | ✅ PASS | `_log_prefill_failure()` line 204: `if symbol == "BTCUSDT": logger.error(...)` |
| R-10 | Non-BTC prefill failure → WARNING, init continues | ✅ PASS | `logger.warning(...)` then `continue` to next symbol |
| R-11 | Cache returned on refresh failure | ✅ PASS | `universe_manager.py` line 48-52: `if self._symbols: return self.symbols` |
| R-12 | `UniverseRefreshError` on failure with no cache | ✅ PASS | Line 57: raises when `self._symbols` is empty |
| R-13 | `symbols` property returns a copy | ✅ PASS | `return list(self._symbols)` — caller cannot mutate internal state |
| R-14 | Gap fill failure → ERROR; new candle still stored | ✅ PASS | `_fill_gap_if_needed` line 156-163: `except BybitAPIError: logger.error; return`. `_insert_closed` called after at line 99 |
| R-15 | `_minimum_turnover` uses Decimal (not float) | ✅ PASS | `Decimal(str(config.universe_min_volume_usd))` — correct; avoids float comparison with `Decimal` ticker values |
| R-16 | No database writes | ✅ PASS | All state in `_closed_buffers`, `_forming_candles` — pure in-memory dicts |
| R-17 | No asyncio.Lock on buffers | ✅ PASS | Single event loop; no threading primitives used |
| R-18 | 91/91 tests pass; 96% coverage | ✅ PASS | Zero regression across full suite |
| R-19 | Scope compliance | ✅ PASS | 6 new files only; market_data/ untouched |

---

## Critical Issues

**None.**

---

## Positive Findings (beyond spec)

1. **`excluded_symbols: frozenset[str] | None`** parameter on `UniverseManager.__init__`:
   not required by the spec, but correct to add — a configurable exclusion list will be
   needed in production. Using `frozenset` is the right type. **Retained.**

2. **`get_forming_candle(symbol, interval)`**: exposed for display-only consumers as
   noted in R-005. Not required by spec but costs nothing and will be useful for T012
   (scan loop) to show a "current candle" in monitoring output. **Retained.**

3. **Double dedup guard**: both `on_candle` (line 92) and `_insert_closed` (line 189)
   check for duplicate `open_time`. The `on_candle` guard short-circuits before the
   gap check, which is correct — a duplicate live update should not trigger a gap fill.
   The `_insert_closed` guard provides a safety net for the gap-fill insertion path.
   Slightly redundant but correct and harmless at buffer_size=200.

---

## Recommendations

1. **Gap formula edge case**: if `elapsed_ms` is exactly `2 × interval_ms`, `gap_candles = 1`.
   If `elapsed_ms` is `1 × interval_ms + 1ms` (rounding), `gap_candles = 0` and no gap fill
   fires. This is correct behaviour — one candle duration elapsed means consecutive candles,
   not a gap. However, T006/T007 writers should be aware that minor clock drift between
   Bybit WS message timestamps and the expected candle boundary can cause `elapsed_ms` to
   fall slightly below `interval_ms`. Log in T006 integration tests.

2. **Large gap fills** can evict older history by design (noted by Codex). T007
   (RegimeDetector) requires 60 × 4H candles; T006 requires 100 × 1H candles. If a
   sustained gap fill of 100+ candles occurs, history may drop below the indicator
   warmup minimum. `is_ready()` will return False and protect downstream. Acceptable.

3. **"BTCUSDT" hardcoded** — same note as T004. T007 must confirm this matches Bybit's
   actual BTC perpetual symbol name.

---

## Release Recommendation

**APPROVED** — All adversarial checks pass. Implementation is correct and robust.

---
