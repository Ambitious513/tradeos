# AGENT_WORKFLOW.md — A+ Scanner Agent Workflow
# Version: 1.0
# Authority: Lead CTO
# Last Updated: 2026-08-31

---

> **This document is an extension of AGENTS.md.**
> It defines the operational workflow for task delegation, handoff, review, and closure.
> All agents must read both AGENTS.md and this document before beginning any task.

---

## 1. CTO OPERATING CYCLE

The Lead CTO (Opus/Fable) manages the project through a repeating cycle:

```
1.  Review current project state
2.  Identify the next dependency-ready task from docs/TASK_GRAPH.md
3.  Write or finalize the Task Contract (tasks/active/TASK_<ID>_<NAME>.md)
4.  Set Task Contract status to READY
5.  Hand off to Owner Agent with the minimal prompt (see Section 4)
6.  Await Completion Report
7.  Trigger automated tests
8.  Assign independent reviewer(s)
9.  Receive review artifacts
10. Perform CTO final review
11. Issue Release Decision
12. If APPROVED: archive task, update TASK_GRAPH and CHANGELOG
13. Make Skill Extraction Decision
14. Activate next task
```

The CTO does NOT personally implement tasks assigned to Codex, Sonnet, or Gemini.

---

## 2. TASK CONTRACT IS THE HANDOFF

Every implementation task is governed by exactly one Task Contract file:

```
tasks/active/TASK_<ID>_<NAME>.md
```

The Task Contract is self-contained. An agent receiving the Task Contract plus `AGENTS.md`
must have everything needed to complete the task.

Do NOT write long natural-language prompts to supplement a complete Task Contract.
Use the minimal handoff prompt defined in Section 4.

For the full Task Contract format, see: `docs/TASK_CONTRACT_STANDARD.md`.

---

## 3. TASK CREATION RULES

### When to create a Task Contract

Create the next Task Contract only when:
- All declared dependencies are complete (APPROVED)
- The preceding task's lessons and infrastructure are known
- The scope can be precisely defined

Do NOT generate all future Task Contracts in advance. Later tasks must incorporate
discoveries from earlier tasks.

### How to create a Task Contract

1. Copy the template from `docs/TASK_CONTRACT_STANDARD.md`
2. Fill in every mandatory section
3. Set status to `DRAFT` while writing
4. Verify: all acceptance criteria are objective and testable
5. Verify: allowed/forbidden file lists are complete and correct
6. Verify: strategy constants match `docs/STRATEGY_SPEC.md v1.0`
7. Set status to `READY`
8. Handoff to Owner Agent

---

## 4. MINIMAL HANDOFF PROMPT

When assigning a READY task to an agent, use this prompt — no longer:

```
Implement tasks/active/TASK_<ID>_<NAME>.md.

Read AGENTS.md and all Source-of-Truth documents listed in Section 3 of the Task Contract.

Work only within the scope defined in Sections 5 and 6.

Do not modify protected files.

Run all required tests before reporting completion.

Return the Completion Report defined in Section 14.

Stop and escalate rather than guessing if you encounter any ambiguity.
```

The Task Contract contains the full specification. Do not repeat it.

---

## 5. AGENT ROLES AND DEFAULTS

| Task Type | Owner | Reviewers |
|---|---|---|
| Architecture / specification | OPUS/FABLE | Human (gate decisions) |
| Python implementation | CODEX | GEMINI (adversarial) + OPUS (CTO) |
| Quantitative / backtest logic | CODEX | SONNET (quant) + GEMINI + OPUS |
| Indicator / formula implementation | CODEX | SONNET (formula audit) + GEMINI + OPUS |
| Risk engine | CODEX | SONNET + GEMINI (both required) + OPUS |
| Backtest engine | CODEX | SONNET (look-ahead bias — mandatory) + GEMINI + OPUS |
| Infrastructure / API | CODEX | GEMINI (reliability) + OPUS |
| Review / audit | SONNET or GEMINI | OPUS (final) |

**The implementing agent CANNOT be the sole approver of its own work.**

---

## 6. REVIEW WORKFLOW

After the agent submits a Completion Report:

```
Step 1: Automated tests
    pytest <scope> / ruff / black / mypy
    → Must pass before Step 2

Step 2: Independent review
    Assigned reviewer reads implementation + tests
    Files: reviews/<agent>/TASK_<ID>_<REVIEW_TYPE>.md
    → Must complete before Step 3

Step 3: CTO final review
    reviews/opus/TASK_<ID>_FINAL_REVIEW.md
    → Verifies spec compliance, architecture, reviewer findings

Step 4: Release Decision
    APPROVED / APPROVED_WITH_FIXES / REJECTED / BLOCKED
```

### Review Artifact Format

Every review file must contain:

```
Reviewer:
Task ID:
Date:
Summary:

Findings:
  [PASS|WARN|FAIL] Item 1
  [PASS|WARN|FAIL] Item 2
  ...

Critical Issues: [list or "None"]
Recommendations: [list or "None"]
Release Recommendation: APPROVED / APPROVED_WITH_FIXES / REJECTED / BLOCKED
```

---

## 7. REVIEWER RESPONSIBILITIES

### SONNET — Quantitative Auditor

Use for tasks involving:
- Mathematical formulas (EMA, RSI, ATR)
- Backtest logic and look-ahead bias
- Statistical correctness
- Performance metrics

SONNET must verify: formulas match spec, no future data accessed, fills are realistic.

### GEMINI — Adversarial Reviewer

Use for tasks involving:
- Exchange API integration
- WebSocket reliability
- Configuration safety
- Failure modes and edge cases
- Infrastructure robustness

GEMINI must verify: system fails safely, no silent exceptions, credentials protected.

### OPUS/FABLE — CTO

Final authority on:
- Strategy specification compliance
- Architecture integrity
- Resolving reviewer disagreements
- Release decisions

---

## 8. FIX CYCLE

If a reviewer files a FAIL finding:

```
Task status → FIX_REQUIRED
    ↓
Returned to Owner Agent
    ↓
Agent applies fix
    ↓
Agent re-runs tests
    ↓
Agent resubmits Completion Report
    ↓
Reviewer re-reviews (targeted — not full re-review unless needed)
    ↓
Release Decision
```

A task in REJECTED state must be RESTARTED — not patched. The distinction:
- `FIX_REQUIRED` → fixable within existing implementation
- `REJECTED` → fundamental design issue; start over

---

## 9. TASK CLOSURE PROCEDURE

When a task is APPROVED:

1. Update status in `tasks/active/TASK_<ID>_<NAME>.md` → `APPROVED`
2. Copy file to `tasks/completed/TASK_<ID>_<NAME>.md`
3. Update `docs/TASK_GRAPH.md` — mark task `[x]` complete
4. Update `docs/CHANGELOG.md` — add entry with: task ID, agent, date, files changed
5. Verify all review artifacts are filed under `reviews/`
6. Make Skill Extraction Decision (Section 10)
7. Activate next Task Contract

---

## 10. SKILL EXTRACTION DECISION

After each task approval, the CTO decides:

```
SKILL REQUIRED
SKILL NOT REQUIRED
SKILL UPDATE REQUIRED
```

**Create a skill when** the task produced reusable, generalizable knowledge that a future
agent could apply to a different task or project:
- A non-trivial integration pattern (e.g., Bybit WebSocket reconnect logic)
- A domain procedure (e.g., look-ahead-bias-free backtesting)
- A formula that required research or validation (e.g., Wilder's RSI implementation)

**Do NOT create a skill for**:
- Routine scaffolding (project setup, config files)
- One-off database schemas
- Normal Python packaging

**Skill location**: `skills/<skill-name>/SKILL.md`

**Skill creation does NOT block task approval.** A separate skill-extraction task may follow.

A skill may only be marked `VERIFIED` after:
- Implementation working
- Tests passing
- Independent review complete
- CTO verification

---

## 11. HUMAN APPROVAL GATES

The following transitions require explicit human approval before work proceeds:

| Gate | Trigger | Required Before |
|---|---|---|
| GATE-1 | Strategy specification finalized | ✅ PASSED 2026-08-31 |
| GATE-2 | Backtest engine validated | T014 begins |
| GATE-3 | Paper trading begins | T015 begins |
| GATE-4 | Live trading begins | Any live execution |
| GATE-5 | Risk parameters increased | Any risk limit change |
| GATE-6 | Core strategy modified | Any strategy change |

No agent may proceed past a gate without documented human approval.

---

## 12. ESCALATION PROCEDURE

Any agent that encounters an unresolvable issue must:

```
1. STOP work immediately
2. Document: STATUS: BLOCKED, TASK: T<NNN>, ISSUE: [description], WHAT I NEED: [decision]
3. Report to CTO
4. Do NOT guess or improvise
```

The default response to uncertainty is always:
```
NO TRADE   (for strategy uncertainty)
DO NOT PROCEED   (for implementation uncertainty)
```

---

## 13. PROTECTED FILES

These files may be READ by any agent but MODIFIED by no agent during ordinary tasks:

```
docs/STRATEGY_SPEC.md      — GATE-1 APPROVED; immutable strategy rules
docs/RISK_SPEC.md          — GATE-1 APPROVED; immutable risk rules
AGENTS.md                  — Operating constitution
MASTER_PROJECT_BRIEF.md    — Source brief
```

To modify any protected file: follow the Strategy Change Proposal process in AGENTS.md Article 6.

---

## 14. LIVE TRADING POLICY SUMMARY

```
Development → Unit Tests → Integration Tests → Backtest (GATE-2) →
Out-of-Sample → Real-Time Scanner → Paper Trading (GATE-3) →
Manual Live Test (GATE-4) → Optional Automated Execution
```

The system must NEVER move directly from development to live execution.
Each progression step requires the prior step to be validated.

---

*End of AGENT_WORKFLOW.md v1.0*
*This document supplements AGENTS.md. Both must be read before beginning any task.*
