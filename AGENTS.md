# Agent Instructions

This file is the shared instruction contract for all coding agents working in this repository.

Tool-specific files such as `CLAUDE.md` and `codex.md` should stay thin and point back here. Do not let them drift into separate project instructions.

## Read order

Before making changes, read:

1. `docs/00_VISION_AND_NORTH_STAR.md`
2. `docs/01_PROJECT_BRIEF.md`
3. `docs/02_SOURCE_MAP.md`
4. `codex/START_HERE.md` if working through Codex
5. The relevant open PR, issue, branch, comments, latest commits, and check status

After reading docs, reconcile them against live repository state before acting. If documentation and live state disagree, trust live state and update the relevant doc before continuing.

## North star

Every task must contribute evidence toward this question:

> Can QuakeWorld bots become realistic enough to act as believable substitutes for real players?

Bunnyjumping, DM2, KTX, Frogbots, MVD analysis, route learning, and movement controllers are not end goals. They are experiments designed to answer that larger question.

## Current hypothesis

KTX/Frogbots may be usable as a server-native bot shell while replacing or enhancing the movement brain.

This is unproven.

The first project objective is to build a repeatable lab that can prove or disprove this hypothesis.

## Autonomous three-agent loop

This repository is worked by **Coder = Claude** and **adversarial Reviewer = Codex** (both run as external/cloud agents). The merge gate is a **neutral PR label**, not parsed prose: a deterministic GitHub Action (`.github/workflows/review-gate-merge.yml`, no LLM and no API tokens) merges a PR when the `gate: ready` label is present, no blocking/escalation label is present, and every gate passes. Codex cannot apply labels itself, so a second no-LLM Action (`.github/workflows/review-gate-labeler.yml`) reads Codex's native review result and stamps `gate: ready` (clean) or `gate: blocked` (findings). **Gemini** is an **on-demand second opinion only** (`/gemini review` via the Gemini Code Assist app) — it does not auto-review and never merges.

```text
Coder (Claude) implements -> Reviewer (Codex) adversarially reviews -> labeler translates Codex's verdict into a gate label -> deterministic Action merges on `gate: ready` if gates pass -> Coder starts the next stage from updated main
```

Role boundaries are mandatory:

- Coder implements the current stage, updates docs/evidence, opens or updates the stage PR, and responds to review feedback that stays inside the same stage.
- Reviewer (Codex) adversarially reviews and hardens PRs for code slop, validation gaps, documentation gaps, and north-star drift. It reviews normally — it does not need to emit any special token.
- The labeler (a deterministic, no-LLM Action) translates Codex's native review result into a `gate: ready` / `gate: blocked` label, fail-closed.
- The merge executor (a deterministic, no-LLM Action) performs the final gate check and merges only when `gate: ready` is set and all gates pass.
- Gemini is an on-demand second opinion (`/gemini review`) — not part of the autonomous loop, and never merges.

Hard separation:

- Coder must not merge and must not self-apply `gate: ready`.
- Reviewer must not implement feature work or start the next stage.
- The labeler must not implement or review; it only classifies Codex's result into a label.
- The merge executor must not implement, review, or start the next stage; it only executes a passing label gate.
- A new commit resets the gate (`.github/workflows/review-gate-reset.yml`), so a stale review can never merge newer code.

## Stage and PR rules

Use the current project stage implied by `docs/01_PROJECT_BRIEF.md`, any active roadmap/current-stage document, open issues, and open PRs.

Default invariant:

```text
One top-level project stage equals one PR.
```

A PR may contain substeps inside the same stage. A PR may propose the next stage. A PR must not implement the next top-level stage.

Stacked PRs are not the default. Do not create, continue, or merge stacked PRs unless Benjamin explicitly authorizes stacking.

## Agent polling rules

Agents may run on a loop, but they must be quiet unless useful work is available.

On every loop, first inspect repo/PR state and then choose exactly one of these outcomes:

1. Do nothing because no work is currently assigned to this role.
2. Make a small scoped change and record evidence.
3. Leave one useful review/gate comment because state changed or a blocker was found.
4. Stop and ask Benjamin because the next action requires human judgment.

Do not post repeated comments with the same conclusion. Do not create new branches or PRs when an appropriate one already exists. Do not fight another agent over the same branch.

## Review gate rule

The merge gate is a neutral PR label, applied by the no-LLM labeler from Codex's native review result (the Reviewer does not emit a custom token):

```text
gate: ready      -> Codex's review was clean; eligible to merge if all other gates pass
gate: blocked    -> Codex posted findings; must not merge until addressed and re-reviewed
gate: reviewing  -> transient; set when new commits land, cleared by the next review
```

A pushed commit invalidates any previous decision: `review-gate-reset.yml` clears `gate: ready`/`gate: blocked` and sets `gate: reviewing` on every `synchronize`, so the gate always reflects the current head. Escalation uses `cycle: needs-human`, which blocks merge regardless of the gate label.

Human override: a repo OWNER may comment `/gate ready` or `/gate blocked` to set the gate directly.

## Review guidelines

These guide the Reviewer (Codex) on every PR review.

Review focus, in priority order:

- Correctness and security regressions. (P0)
- Validation gaps: claims without evidence, missing or auto-skipped tests, no real run output. (P0)
- North-star drift: work that does not produce evidence toward the believable-bots question. (P1)
- Documentation gaps: code/config/experiment changes that did not update the routed doc. (P1)
- Code slop: dead code, needless complexity, duplicated logic. (P2)

Review normally and post your findings in the standard way — you do not need to emit any special verdict token. The no-LLM labeler translates your result into the gate label: a clean review ("no major issues") becomes `gate: ready`; any posted finding becomes `gate: blocked`. Block (post findings) for any P0. Because the labeler fails closed, an ambiguous or comment-only response leaves the PR un-readied until you give a clear clean verdict or a human overrides.

## Merge gate rule

The merge executor may merge only when all are true:

- Target repository and PR are unambiguous.
- PR is open and non-draft.
- PR targets the correct base branch, normally `main`.
- PR belongs to the intended current project stage.
- PR does not include later-stage work.
- PR is mergeable.
- Required checks pass.
- If no checks exist, that absence is explicitly noted.
- The `gate: ready` label is present and neither `gate: blocked` nor `cycle: needs-human` is set.
- No unresolved actionable review feedback remains.
- The PR body or latest agent comment records what changed, evidence produced, docs updated, validation run, stage status, and next step.

The merge executor must refuse clearly if any gate fails.

## Documentation rules

Documentation is a first-class deliverable.

Any meaningful change to code, scripts, configs, experiments, architecture, environment, or assumptions must update at least one relevant document.

Use this routing:

- New source or reference -> update `docs/02_SOURCE_MAP.md`
- Movement discovery -> update `docs/03_MOVEMENT_PROBLEM.md`
- Lab setup change -> update `docs/05_HEADLESS_TEST_ENV.md`
- MVD/data pipeline discovery -> update `docs/06_DATA_AND_MVD_PIPELINE.md`
- Experiment result -> update `docs/07_FINDINGS_LOG.md`
- Architecture/project decision -> update `docs/08_DECISION_LOG.md`

## Verification workflow

No theoretical code. Everything important must be proven.

Before modifying source, define how the change will be validated. Where possible, run the validation first to establish the current baseline or failure mode.

After implementing, run the validation again. If validation fails, fix the issue or document the blocker. Do not declare success without real output.

Record terminal output, logs, metrics, screenshots, MVD-analysis output, or other evidence in the relevant doc or PR comment.

## Before finishing any task

Answer these in the final message, PR body, PR comment, or commit summary:

- What changed?
- What evidence was produced?
- Which docs were updated?
- If no docs were updated, why not?
- What is the next smallest useful experiment?

## Do not do these first

Do not start by training Milton.
Do not start by rewriting Frogbots.
Do not start by implementing a final bunnyjump controller.
Do not treat speed alone as success.
Do not treat bunnyjumping as the project goal.

First build the laboratory.

## Preferred working style

Make small, reversible changes.
Prefer measurement before optimization.
Prefer source-grounded claims over guesses.
Record uncertainty explicitly.
Keep the larger FantasyQuake / Megalodon Milton fork visible in documentation.
