# TASK_001_SPECIFICATION_AUDIT.md
# A+ Scanner — Specification Audit and Strategy Formalization
# Status: APPROVED — GATE-1 approved by Human 2026-08-31. Task archived to tasks/completed/.
# Agent: Lead CTO (Opus/Fable class)
# Created: 2026-08-31
# Updated: 2026-08-31

---

## Objective

Audit the A+ Scanner master brief for all ambiguous, missing, or contradictory requirements.
Produce a complete, deterministic strategy specification that two independent developers could
implement identically. Identify all unresolved decisions requiring human approval.

---

## Scope

**Files this task may read**:
- `A+ SCANNER — ANTIGRAVITY MASTER BUILD BRIEF v1.0.md` (source of truth)
- `MASTER_PROJECT_BRIEF.md` (canonical reference)

**Files this task may create or modify**:
- `AGENTS.md` (create)
- `docs/STRATEGY_SPEC.md` (create)
- `docs/SYSTEM_ARCHITECTURE.md` (create)
- `docs/DATA_CONTRACT.md` (create)
- `docs/RISK_SPEC.md` (create)
- `docs/TEST_SPEC.md` (create)
- `docs/TASK_GRAPH.md` (create)
- `docs/CHANGELOG.md` (create)
- `tasks/active/TASK_001_SPECIFICATION_AUDIT.md` (this file)

---

## Non-goals

- Do NOT write any Python implementation code
- Do NOT connect to any exchange API
- Do NOT create API keys or request trading permissions
- Do NOT optimize strategy parameters
- Do NOT propose strategy changes beyond clarifying existing ambiguities
- Do NOT begin T002 or any subsequent task

---

## Inputs

- `A+ SCANNER — ANTIGRAVITY MASTER BUILD BRIEF v1.0.md`

---

## Requirements

1. Read the entire master brief before writing anything
2. Identify ALL ambiguous requirements (not just obvious ones)
3. For each ambiguity: propose a deterministic resolution OR flag as requiring human decision
4. Produce a strategy spec deterministic enough that two developers produce the same behavior
5. Create project governance (AGENTS.md)
6. Design the system architecture
7. Define data contracts
8. Define risk rules
9. Define test requirements
10. Create the task dependency graph
11. Create the directory structure for the project

---

## Acceptance Criteria

- [ ] All 28+ identified ambiguities documented in STRATEGY_SPEC.md Ambiguity Register
- [ ] Every trading rule has: Rule ID, Name, Purpose, Formula, Threshold, Timeframe, Trigger, Invalidation, Edge Cases
- [ ] BTC regime: BULLISH/BEARISH/NEUTRAL defined deterministically with exact thresholds
- [ ] Exhaustion Short: all 10 rules (SHORT-001 through SHORT-010) defined
- [ ] Exhaustion Long: all 11 rules (LONG-001 through LONG-011) defined
- [ ] Signal state machine: all 9 states defined with transitions
- [ ] Risk engine: position sizing formula complete with precision and minimum order handling
- [ ] A+ scoring model: 8 criteria defined with point values totaling 100
- [ ] AGENTS.md: covers all 18 articles (roles, boundaries, reviews, gates, live policy)
- [ ] SYSTEM_ARCHITECTURE.md: all 14 components with interfaces defined
- [ ] DATA_CONTRACT.md: all data fields with source, type, freshness, failure behavior
- [ ] RISK_SPEC.md: all 10 risk rules with exact formulas
- [ ] TEST_SPEC.md: 80+ specific test cases defined by ID
- [ ] TASK_GRAPH.md: 18 tasks with dependencies, parallel execution map, agent assignments
- [ ] GATE-1 open questions documented for human review

---

## Tests Required

None — this is a specification task. The outputs are documents, not code.
Correctness is verified by human review at GATE-1.

---

## Deliverables

| File | Status |
|---|---|
| `AGENTS.md` | CREATED |
| `docs/STRATEGY_SPEC.md` | CREATED (v0.1-DRAFT) |
| `docs/SYSTEM_ARCHITECTURE.md` | CREATED (v0.1-DRAFT) |
| `docs/DATA_CONTRACT.md` | CREATED (v0.1-DRAFT) |
| `docs/RISK_SPEC.md` | CREATED (v0.1-DRAFT) |
| `docs/TEST_SPEC.md` | CREATED (v0.1-DRAFT) |
| `docs/TASK_GRAPH.md` | CREATED (v0.1-DRAFT) |
| `docs/CHANGELOG.md` | CREATED |
| `tasks/active/TASK_001_SPECIFICATION_AUDIT.md` | CREATED (this file) |
| `tasks/active/` directory | CREATED |
| `tasks/completed/` directory | CREATED |
| `tasks/rejected/` directory | CREATED |
| `reviews/opus/` directory | CREATED |
| `reviews/sonnet/` directory | CREATED |
| `reviews/gemini/` directory | CREATED |
| `skills/` directory | CREATED |

---

## Escalation Conditions

Escalate immediately if:
1. The master brief contains contradictions that cannot be resolved by interpretation
2. Any trading rule has zero deterministic interpretation (cannot propose a resolution)
3. Human preference is required before any interpretation can be made

For this task (T001), all escalations are handled by documenting in the GATE-1 open questions list.

---

## Recommended Agent

**Lead CTO / Opus / Fable class**

Rationale: T001 is a reasoning-intensive specification and architecture task requiring:
- Deep reading comprehension of an ambiguous brief
- Systematic ambiguity identification
- Architecture design across 14+ components
- Formal rule specification
- No implementation — purely analytical

---

## Completion Report

```
Status: COMPLETED (pending GATE-1 human approval)

Changed Files:
  - AGENTS.md (created)
  - docs/STRATEGY_SPEC.md (created)
  - docs/SYSTEM_ARCHITECTURE.md (created)
  - docs/DATA_CONTRACT.md (created)
  - docs/RISK_SPEC.md (created)
  - docs/TEST_SPEC.md (created)
  - docs/TASK_GRAPH.md (created)
  - docs/CHANGELOG.md (created)
  - tasks/active/TASK_001_SPECIFICATION_AUDIT.md (created)

Tests Run: None (specification task)
Tests Passed: N/A
Tests Failed: N/A

Known Issues:
  - STRATEGY_SPEC.md is v0.1-DRAFT; all 28 ambiguity resolutions are PROPOSED, not approved
  - 11 open questions require human decision at GATE-1 before implementation begins

Remaining Risks:
  - Human may disagree with proposed thresholds (RSI, pump/dump %, neutral zone)
  - Some proposals (EMA extension 3%, ATR 1.5× stop) have LOW confidence and need validation
  - Scoring weights in Section 8 are proposed; human may want different weightings

Recommended Next Step:
  GATE-1 — Human reviews docs/STRATEGY_SPEC.md and approves or adjusts proposed thresholds.
  After approval: proceed to T002 (Project Foundation) with Codex.
```

---

## GATE-1 Open Questions Summary

Review these decisions in `docs/STRATEGY_SPEC.md` Section 11:

| # | Question | Proposed Answer | Confidence |
|---|---|---|---|
| 1 | BTC regime timeframe | 4H candles | MEDIUM |
| 2 | Neutral zone threshold | ±1.5% 24H change | MEDIUM |
| 3 | Pump threshold | ≥ +8% | MEDIUM |
| 4 | Dump threshold | ≤ -8% | MEDIUM |
| 5 | RSI short threshold | RSI ≥ 75 | MEDIUM |
| 6 | RSI long threshold | RSI ≤ 25 | MEDIUM |
| 7 | EMA7 extension | ≥ 3% from EMA7 | LOW |
| 8 | Stop method | MAX(structural, 1.5×ATR14) | LOW |
| 9 | Minimum R:R | 2.0:1 | MEDIUM |
| 10 | Setup expiration | 4 hours | LOW |
| 11 | A+ score threshold | ≥ 80/100 | LOW |
| 12 | Daily loss limit | -$25 (5 losses) | LOW |
| 13 | Daily profit lock | +$50 | LOW |

**The human may change any or all of these at GATE-1.**

---

*End of TASK_001_SPECIFICATION_AUDIT.md*

