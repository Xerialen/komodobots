# Gemini Instructions

Read `AGENTS.md` first. It is the repository source of truth for project goals, roles, documentation rules, and workflow expectations.

This file should remain intentionally small.

## Role: on-demand second opinion

**Gemini is an on-demand second opinion**, provided by the Gemini Code Assist GitHub app. It does NOT auto-review every PR (see `.gemini/config.yaml`) and it is NOT part of the autonomous Coder -> Reviewer -> merge loop.

- Invoke it deliberately on a PR with `/gemini review` (or `/gemini summary`) when you want an extra perspective alongside Codex's adversarial review.
- Gemini never merges and never posts the `MERGER:` verdict. Only the Reviewer (Codex) posts that verdict; only the deterministic merge executor (`.github/workflows/codex-merge.yml`) merges.
