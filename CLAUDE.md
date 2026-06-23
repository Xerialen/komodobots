# Claude Instructions

Read `AGENTS.md` first. It is the repository source of truth for project goals, roles, documentation rules, and workflow expectations.

This file should remain intentionally small.

## Role selection

Claude is not permanently assigned to one repository role.

When Benjamin assigns this session as implementation work, follow `coder.md`.
When Benjamin assigns this session as review work, follow `reviewer.md`.
When Benjamin assigns this session as a consistency / goal-anchor audit, follow
`auditor.md`.
If no role is explicit, infer the role from the request and keep the role
boundary visible.

Hard rule: do not act as both Coder and independent Reviewer for the same PR
unless Benjamin explicitly overrides role separation.

Before changing any data extraction, transform, training-data, or model-prep code, read
`docs/20_DATA_CONTRACT.md` and obey its anti-drift rule (contract + schema + example + tests
move in the same PR).

Claude-specific guidance:

- Prefer updating documentation alongside code.
- Explain reasoning and uncertainty clearly.
- Reference evidence when making architecture recommendations.
