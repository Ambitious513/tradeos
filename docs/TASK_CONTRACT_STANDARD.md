# TASK_CONTRACT_STANDARD.md — A+ Scanner Task Contract Standard
# Version: 1.0
# Authority: Lead CTO
# Last Updated: 2026-08-31

---

## PURPOSE

This document defines the canonical format for all Task Contracts in the A+ Scanner project.

Every implementation task must have exactly one Task Contract file located at:

```
tasks/active/TASK_<ID>_<NAME>.md
```

The Task Contract is the **single authoritative handoff document** between the CTO and any
implementation or review agent. It replaces verbal instructions, conversational prompts, and
separate contract files.

A future agent should be able to receive `AGENTS.md` + the Task Contract and know exactly
what it must do — with no additional context required.

---

## TASK CONTRACT TEMPLATE

Copy this template exactly for each new task. All sections are mandatory.
Remove only sections that genuinely do not apply (e.g., Skill Extraction for a pure doc task)
and note the removal reason.

---

```markdown
# TASK CONTRACT
# ═══════════════════════════════════════════════════════════════
# Task ID:        T<NNN>
# Task Name:      <Short name>
# Status:         DRAFT | READY | IN_PROGRESS | REVIEW | APPROVED | REJECTED | BLOCKED
# Priority:       P0 (blocks all) | P1 (critical path) | P2 (parallel) | P3 (nice-to-have)
# Owner Agent:    CODEX | SONNET | GEMINI | OPUS
# Reviewer:       <agent name>
# CTO Review:     OPUS / FABLE
# Created By:     Lead CTO (Opus/Fable)
# Created Date:   YYYY-MM-DD
# Target Branch:  feature/t<nnn>-<slug>
# ═══════════════════════════════════════════════════════════════

---

## 1. Objective

[1-3 sentences. What is being built or analyzed. What problem does it solve?
What does "done" look like from the outside?]

---

## 2. Background

[Why does this task exist now? What preceded it? What depends on it?
Reference the TASK_GRAPH.md entry. Include any important context the agent
needs that is not in the spec documents.]

---

## 3. Source-of-Truth Documents

The agent MUST read these before beginning:

| Document | Sections Relevant |
|---|---|
| `AGENTS.md` | All (coding standards, escalation, reporting) |
| `docs/STRATEGY_SPEC.md` | [relevant sections] |
| `docs/SYSTEM_ARCHITECTURE.md` | [relevant sections] |
| `docs/DATA_CONTRACT.md` | [relevant sections] |
| `docs/RISK_SPEC.md` | [relevant sections] |
| `docs/TEST_SPEC.md` | [relevant test IDs] |

Add or remove rows as appropriate.
Never assume the agent has read previous conversations.

---

## 4. Scope

[1 paragraph: what category of work this task covers.
Be explicit about what is IN scope vs what is NOT scope (Section 8).]

---

## 5. Allowed Files / Directories

The agent may ONLY create or modify files within:

```
[list every allowed path explicitly]
[be specific — prefer listing files over directories where practical]
```

---

## 6. Forbidden Files / Directories

The agent must NOT touch any of the following:

```
docs/STRATEGY_SPEC.md          — PROTECTED (GATE-1 approved, immutable)
docs/RISK_SPEC.md              — PROTECTED
AGENTS.md                      — PROTECTED
MASTER_PROJECT_BRIEF.md        — PROTECTED
[list all other forbidden paths for this task]
```

**Rule**: If implementing a requirement requires touching a forbidden file, STOP and escalate.

---

## 7. Requirements

[Number each requirement with R-<NNN>. Be precise and implementation-complete.
A good requirement can be directly turned into code without interpretation.
Include exact values, method signatures, class names, enum values where relevant.
Reference the spec document and section for each requirement.]

### R-001 — <Requirement Name>

[Description. Include code signatures, formulas, exact thresholds where applicable.
Reference: docs/STRATEGY_SPEC.md §X.Y or docs/DATA_CONTRACT.md §Z]

### R-002 — <Requirement Name>

[...]

---

## 8. Non-Goals

The agent must NOT:
- [explicit prohibition 1]
- [explicit prohibition 2]
- [...]

Every prohibition should correspond to a risk of scope creep or a common mistake.

---

## 9. Interfaces / Contracts

[What import paths / class names / function signatures must remain stable after this task?
Downstream tasks depend on these. List them explicitly.]

```python
# Example:
from scanner.module import ClassName
from scanner.module import function_name
```

[If this task has no stable public interface, state "None — internal implementation only".]

---

## 10. Acceptance Criteria

Every criterion must be objectively verifiable.

| AC-ID | Criterion | Verification Method |
|---|---|---|
| AC-001 | [specific, measurable outcome] | [test name / command / manual check] |
| AC-002 | [...] | [...] |

Avoid vague criteria like "works correctly" or "handles errors".
Each AC should map to at least one test in Section 11.

---

## 11. Required Tests

[List every test that must exist and pass before the task can be APPROVED.
Group by test file. Use the test naming convention from TEST_SPEC.md where applicable.]

### `tests/<category>/test_<module>.py`

```
test_<scenario_1>
test_<scenario_2>
test_<edge_case>
```

**Minimum coverage**: 80% line coverage on all new modules.

---

## 12. Expected Deliverables

[List every file the agent is expected to create or materially modify.
Mark each as NEW or MODIFIED.]

```
path/to/file.py     NEW
path/to/other.py    MODIFIED
```

No files outside Section 5 should appear here.

---

## 13. Failure / Escalation Conditions

STOP and escalate to CTO — do NOT guess — if:

| Condition | Action |
|---|---|
| [specific ambiguity or conflict] | Report to CTO |
| [dependency missing] | Report to CTO |
| [forbidden file must be changed] | STOP immediately |

**Escalation format:**
```
STATUS: BLOCKED
TASK: T<NNN>
ISSUE: [precise description]
FILE AFFECTED: [path if applicable]
WHAT I NEED: [specific decision or clarification]
```

---

## 14. Completion Report Requirements

On task completion, the agent must submit:

```
Task:       T<NNN> — <Name>
Agent:      <agent name>
Branch:     feature/t<nnn>-<slug>

Summary:    [2-4 sentences]

Files Created:        [list]
Files Modified:       [list]

Requirements Completed:   [R-001 ✅ / R-002 ✅ / ...]
Tests Run:               [list test files and totals]
Tests Passed:            [count]
Tests Failed:            [count + names + error messages if any]

Known Issues:            [none, or list]
Out-of-Scope Findings:   [anything future tasks need to know]
Potential Risks:         [concerns for downstream tasks]

Recommended Next Step:   [specific next task or action]
```

The task is NOT approved merely because the agent reports success.
CTO and reviewer(s) must sign off (Section 17).

---

## 15. Review Plan

### Automated (must pass before human review)

```bash
pytest tests/<scope>/ --cov=src/scanner/<module> --cov-report=term-missing
ruff check src/
black --check src/
mypy src/ --strict
```

### Independent Review

| Reviewer | Focus | Output File |
|---|---|---|
| GEMINI | [adversarial / reliability / edge cases] | `reviews/gemini/TASK_<ID>_RED_TEAM.md` |
| SONNET (if quant) | [formula correctness / backtest bias] | `reviews/sonnet/TASK_<ID>_QUANT_REVIEW.md` |
| OPUS | [strategy compliance / architecture] | `reviews/opus/TASK_<ID>_FINAL_REVIEW.md` |

### Release Decision Options

```
APPROVED            — all AC pass; no blocking findings
APPROVED_WITH_FIXES — approved pending specific documented fixes
REJECTED            — does not meet criteria; must be restarted (not patched)
BLOCKED             — upstream dependency or unresolvable ambiguity
```

---

## 16. Skill Extraction Decision

After task approval:

```
SKILL REQUIRED     — task produced generalizable reusable knowledge
SKILL NOT REQUIRED — task was project-specific scaffolding
SKILL UPDATE       — existing skill needs revision based on this task
```

If required:
- Create `skills/<skill-name>/SKILL.md`
- Follow AGENTS.md Article 14 for skill creation rules
- Skill is NOT required to be complete before task is marked APPROVED

---

## 17. Status / Sign-off

| Role | Name | Status | Date |
|---|---|---|---|
| CTO (task created) | Opus/Fable | ⏳ / ✅ READY | YYYY-MM-DD |
| Implementation | <agent> | ⏳ PENDING | — |
| Reviewer | <agent> | ⏳ PENDING | — |
| CTO Final Review | Opus/Fable | ⏳ PENDING | — |
| **Release Decision** | | ⏳ PENDING | — |
```

---

## TASK STATUS DEFINITIONS

| Status | Meaning |
|---|---|
| `DRAFT` | Being written by CTO; not yet ready for agent assignment |
| `READY` | Complete; assigned to implementation agent; work may begin |
| `IN_PROGRESS` | Agent is actively working |
| `REVIEW` | Implementation complete; awaiting reviewer(s) |
| `APPROVED` | All criteria met; ready to archive |
| `APPROVED_WITH_FIXES` | Approved pending documented specific fixes |
| `REJECTED` | Does not meet criteria; must be restarted |
| `BLOCKED` | Cannot proceed; upstream dependency or escalation pending |

---

## TASK LIFECYCLE

```
CTO writes Task Contract (status: DRAFT)
    ↓
CTO sets status: READY
    ↓
Handoff to Owner Agent
    ↓
Agent implements (status: IN_PROGRESS)
    ↓
Agent submits Completion Report (status: REVIEW)
    ↓
Automated tests run
    ↓
Independent reviewer(s) file review artifacts
    ↓
CTO final review
    ↓
Release Decision: APPROVED / APPROVED_WITH_FIXES / REJECTED / BLOCKED
    ↓
[If APPROVED]
Task archived to tasks/completed/
TASK_GRAPH.md updated
CHANGELOG.md updated
Skill extraction decision made
Next task activated
```

---

## AGENT HANDOFF INSTRUCTION (minimal)

When handing a READY task to an agent, use this minimal prompt:

```
Implement tasks/active/TASK_<ID>_<NAME>.md.

Read AGENTS.md and all Source-of-Truth documents listed in Section 3 of the Task Contract.

Work only within the scope defined in Sections 5 and 6.

Do not modify protected files.

Run all required tests before reporting completion.

Return the Completion Report defined in Section 14.

Stop and escalate rather than guessing if you encounter ambiguity.
```

Do NOT write a new long-form prompt. The Task Contract already contains all necessary information.

---

## PROTECTED FILES (never modifiable by implementation agents)

```
docs/STRATEGY_SPEC.md
docs/RISK_SPEC.md
AGENTS.md
MASTER_PROJECT_BRIEF.md
```

Any task that requires changes to these files must go through the Strategy Change Proposal
process defined in AGENTS.md Article 6.

---

*End of TASK_CONTRACT_STANDARD.md v1.0*
