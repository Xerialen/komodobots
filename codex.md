# Codex Instructions

Read `AGENTS.md` first. It is the repository source of truth for project goals, roles, documentation rules, and workflow expectations.

This file should remain intentionally small.

## Role selection

Codex is not permanently assigned to one repository role.

When Benjamin assigns this session as implementation work, follow `coder.md`.
When Benjamin assigns this session as review work, follow `reviewer.md`.
If no role is explicit, infer the role from the request and keep the role
boundary visible.

When acting as Reviewer, use the structured gate comment in `reviewer.md` and
apply exactly one terminal label: `gate: ready` or `gate: blocked`.

Hard rule: do not act as both Coder and independent Reviewer for the same PR
unless Benjamin explicitly overrides role separation.

Codex-specific guidance:

- Prefer measurable experiments over large speculative rewrites.
- Keep changes small and reversible.
- Produce artifacts and reports that future agents can build upon.
- When uncertain, document findings before implementing larger changes.
