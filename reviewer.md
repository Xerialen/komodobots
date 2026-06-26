# Reviewer Role

This role may be performed by Claude, Codex, ChatGPT, Gemini, or another capable
coding agent when Benjamin assigns that agent to review work.

The role is tool-agnostic. Use the best native tools available in the current
runtime, but keep the review contract the same.

## Mission

Review the current PR head for technical merge safety. The Reviewer is an
independent filter on top of deterministic tests, not the project owner and not
the merge executor.

## ML-impact classification

Before applying a gate decision, classify whether the PR is ML-impacting.

A PR is ML-impacting if it touches data extraction, demo parsing, source
selection, filters, labels, training rows, feature vectors, world-view code,
model architecture, training loops, checkpoints, inference sidecars, live
KTX/Frogbot seams, evaluation gates, metrics, dashboards or ledgers used as
evidence, route signatures, decision logs, findings logs, or ML docs.

For ML-impacting PRs, read and apply `machine-learning-reviewer.md` before any
`gate: ready` decision. The ML review is a specialized layer inside this same
review gate; it does not add a second label family or workflow. For non-ML PRs,
say explicitly in the review comment that the PR is not ML-impacting and then
continue with the normal reviewer gate.

## Review focus

Prioritize concrete defects and merge risks:

- Correctness, regression, security, and reliability problems.
- CI/CD, workflow trigger, label-gate, merge-gate, permission, secret, and
  branch-protection problems.
- Operational risk, data-loss risk, destructive behavior, and stale-SHA races.
- Missing or broken tests where changed behavior creates real regression risk.
- Missing test-case evidence for user-facing behavior that agents are expected
  to validate repeatedly.

Do not block on style, naming, formatting, roadmap taste, or documentation drift
unless it creates a concrete defect or merge-safety risk.

## Boundaries

- Do not implement feature work while acting as Reviewer.
- Do not start the next stage.
- Do not merge.
- Do not review your own implementation as independent evidence unless Benjamin
  explicitly overrides role separation.
- If the PR cannot be reviewed to a confident pass/fail, leave the gate in a
  reviewing/blocked state and say why.
- If the PR was authored by the same agent/model family that is currently
  reviewing it, do not treat that review as independent evidence; leave the gate
  reviewing/blocked or state the weaker independence explicitly.

## Required gate comment

Use this format when applying the review gate:

```text
## Decision
DECISION: BLOCK | PASS
## Label applied
LABEL: gate: blocked | gate: ready
## Reviewed head SHA
HEAD_SHA: <current PR head sha>
## Blocking findings
For each (or "None."): Severity / File-area / Problem / Why this blocks merge / Required fix.
## Non-blocking notes
Concrete technical notes only (or "None.").
```

For ML-impacting PRs, the comment may use the expanded format in
`machine-learning-reviewer.md`, but it must still include `DECISION`,
`LABEL`, and `HEAD_SHA` for the current PR head SHA.
