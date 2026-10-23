---
name: project-memory
description: Keeps coding-agent context, handoffs, and technical decision history consistent across sessions. Use when starting or ending a coding task, investigating architecture, making a consequential technical choice, reviewing an existing decision, or syncing project decisions with a connected Notion MCP.
---

# Project Memory Skill

## Outcome

Keep a reliable, lightweight record of what the project is, what is happening now, and why consequential engineering choices were made. Use evidence from the repository and tools; never manufacture context.

## Source-of-truth boundaries

- Current implementation: code and tests.
- Actual changes: Git diff and commit history.
- Stable project context: `docs/project-memory/PROJECT_CONTEXT.md`.
- Current task state: `docs/project-memory/HANDOFF.md`.
- Local decision index: `docs/project-memory/DECISIONS.md`.
- Full rationale and searchable decision history: existing Notion Engineering Decision Log (or its existing equivalent).
- Work instructions: applicable `AGENTS.md` files.

If these sources conflict, inspect code, tests, docs and Git. Explain the conflict and update stale documentation only when supported by evidence.

## Start a task

1. Read `AGENTS.md` and relevant nested instructions.
2. Check `git status`; preserve uncommitted user changes.
3. Read the three project-memory files if present.
4. Inspect relevant implementation, tests, configuration and recent history.
5. Summarize the known state, task goal, constraints, unknowns and likely files to touch. Separate facts from assumptions.
6. If no project context exists, create the template files only as needed; do not fill unknown facts with guesses.

## Plan and choose

Before substantial changes, identify:
- Problem and root-cause hypothesis.
- Acceptance criteria and out-of-scope items.
- Constraints, dependencies, permissions and failure cases.
- Options, including the simplest option and no change when relevant.
- Reversibility, implementation cost, risks and evidence still needed.

Ask the user before making a high-impact, hard-to-reverse choice when intent or constraints are unclear. Small, reversible implementation details can be handled autonomously within scope.

## Record a decision

Record decisions that materially affect architecture, security, authorization, data models, APIs, reliability, performance, dependencies, deployment or operating cost. Scale detail to risk.

1. Search the existing Notion Decision Log and local index for duplicates or related/superseded records.
2. If using Notion MCP, inspect the actual database/data-source schema and existing property options before writing. Never assume property names or option values.
3. Reuse the existing database; do not create a duplicate.
4. Use the existing naming convention if one is configured. Otherwise use `DEC-NNN — Short decision title`, with a unique, stable ID.
5. Include context, problem, chosen option, rationale, alternatives rejected, trade-offs/risks, verification, implementation references, review triggers and unknowns as appropriate.
6. After writing, read back the record to verify the content and properties. If the write result is ambiguous, search before retrying to avoid duplicates.
7. Update `DECISIONS.md` with a short index entry and link to the Notion record only when a real URL/ID is returned.
8. If Notion is unavailable, keep a local draft and explicitly report that sync did not happen.

Do not rewrite history to make a past choice look inevitable. If a decision changes, mark the old one superseded and link the replacement.

## During implementation

- Keep changes within the agreed scope.
- Update handoff notes only when useful; avoid logging every trivial action.
- If implementation evidence contradicts the plan, pause and revise the plan.
- If three focused attempts fail, stop repeating the same approach and reassess the root cause.

## Verify

1. Choose tests based on changed behavior and risk.
2. Run relevant commands where the environment permits.
3. Record exact commands and actual outcomes.
4. Distinguish tests written from tests executed. Never claim a test passed without output/evidence.
5. Record failed, skipped or unavailable checks and remaining uncertainty.

## Finish and hand off

- Update project context if verified stable architecture or constraints changed.
- Update handoff with completed work, changed files, tests/results, blockers and one concrete next step if work remains.
- Update the local decision index and Notion records for consequential decisions.
- Summarize what changed, why, verification evidence and residual risks to the user.

## Notion record quality

Use the repository's actual facts and existing Notion schema. A good decision record makes clear:
- What problem was being solved and why it mattered.
- What options were considered and why they were rejected.
- What was chosen, under what assumptions, and what was deliberately not included.
- What trade-offs and failure modes remain.
- How the decision was verified and what was not verified.
- What future evidence should trigger review or replacement.
