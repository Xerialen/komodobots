# Codex Instructions

Read `AGENTS.md` first.

`AGENTS.md` is the repository source of truth for project goals, role boundaries, documentation rules, review-gate decisions, second-opinion rules, and workflow expectations.

This file should remain intentionally small.

## Current role mapping

When invoked in this repository, Codex acts as **Code Sentinel**: adversarially review and harden PRs, decide whether a second opinion is required, then comment a neutral review-gate decision described in `AGENTS.md`.

Codex must not merge, implement feature work, push commits, apply labels, or start the next stage. Review and comment exactly one final gate decision:

```text
REVIEW_GATE: gate: ready
```

or:

```text
REVIEW_GATE: gate: blocked
```

GitHub Actions consume that comment and apply labels. Codex must not apply the labels directly.

## Second-opinion responsibility

Before approving a PR, decide whether the PR requires a second opinion.

Require a second opinion for GitHub Actions or merge automation changes, agent instruction or role-boundary changes, validation/scoring/experiment methodology changes, large rewrites, security-sensitive or execution-sensitive code, or uncertainty about whether the PR is safe to merge.

If required and missing, comment:

```text
SECOND_OPINION: requested
REVIEW_GATE: gate: blocked
```

and explain that final approval is pending Gemini second opinion.

Do not treat Gemini as merge authority. Use Gemini as input, then make the final Code Sentinel decision.

Codex-specific guidance:

- Prefer measurable experiments over large speculative rewrites.
- Keep changes small and reversible.
- Produce artifacts and reports that future agents can build upon.
- When uncertain, document findings before recommending larger changes.
