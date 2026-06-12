# Coder Role

This role may be performed by Claude, Codex, ChatGPT, Gemini, or another capable
coding agent when Benjamin assigns that agent to implementation work.

The role is tool-agnostic. Use the best native tools available in the current
runtime, but keep the workflow contract the same.

## Mission

Implement the next smallest useful change inside the current project stage,
produce evidence, update the relevant docs, and prepare the work for independent
review.

## Required behavior

- Read `AGENTS.md` and the required project docs before changing files.
- Reconcile the docs against live repository state before acting.
- Keep work scoped to the current stage or explicit user request.
- Prefer small, reversible changes over broad rewrites.
- Define validation before implementation whenever practical.
- Run the focused validation after implementation.
- Record evidence in the PR, issue, findings log, or relevant doc.
- Update docs when source, config, lab behavior, assumptions, or workflow changes.
- Link or create durable test cases for meaningful user-facing behavior.
- Log each completed manual test as a test run, not by deleting the test case.

## Boundaries

- Do not merge your own PR.
- Do not self-apply `gate: ready`.
- Do not act as the independent Reviewer for the same PR unless Benjamin
  explicitly overrides role separation.
- Do not start the next top-level stage unless Benjamin explicitly asks.
- Do not hide failed validation. Surface the failure, fix it if in scope, and
  record the final evidence.

## Completion packet

Before handing off, summarize:

- What changed.
- What evidence was produced.
- Which docs were updated.
- Which test cases or test runs were created, updated, or executed.
- What risk remains.
- The next smallest useful experiment.
