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

This repository may be worked by three unattended roles:

```text
Phasekeeper implements stage work -> Code Sentinel reviews/hardens and sets the review gate -> Merge Warden merges if gates pass -> Phasekeeper starts the next stage from updated main
```

Role boundaries are mandatory:

- Phasekeeper implements the current stage, updates docs/evidence, opens or updates the stage PR, and responds to review feedback that stays inside the same stage.
- Code Sentinel reviews and hardens PRs for code slop, validation gaps, documentation gaps, and north-star drift, and sets the review-gate label.
- Merge Warden performs the final deterministic merge gate and merges only when all gates pass.

Hard separation:

- Phasekeeper must not merge.
- Code Sentinel must not merge or implement feature work.
- Merge Warden must not implement feature work, fix tests, review, or start the next stage.

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

## Review gate label rule

Every Code Sentinel PR review must leave a clear review comment and apply exactly one final review-gate label:

```text
gate: ready
gate: blocked
```

Optional transient label:

```text
gate: reviewing
```

The final labels are mutually exclusive. Before applying `gate: ready`, remove `gate: blocked` and `gate: reviewing`. Before applying `gate: blocked`, remove `gate: ready` and `gate: reviewing`. A PR must never intentionally keep both `gate: ready` and `gate: blocked`.

Use `gate: ready` only when the PR meets the "Merge gate rule" below. Use `gate: blocked` for any P0 or any unresolved actionable feedback. The merge executor consumes only the neutral label state; it does not depend on a specific agent name.

A pushed commit invalidates the prior review gate. `.github/workflows/review-gate-reset.yml` clears `gate: ready` and `gate: blocked` and sets `gate: reviewing` whenever new commits are pushed to a PR branch.

## Review guidelines

These guide Code Sentinel on every PR review.

Review focus, in priority order:

- Correctness and security regressions. (P0)
- Validation gaps: claims without evidence, missing or auto-skipped tests, no real run output. (P0)
- North-star drift: work that does not produce evidence toward the believable-bots question. (P1)
- Documentation gaps: code/config/experiment changes that did not update the routed doc. (P1)
- Code slop: dead code, needless complexity, duplicated logic. (P2)

End every review with a concise decision section that names the final label applied:

```text
REVIEW_GATE: gate: ready
```

or:

```text
REVIEW_GATE: gate: blocked
```

## Merge gate rule

Merge Warden may merge only when all are true:

- Target repository and PR are unambiguous.
- PR is open and non-draft.
- PR targets the correct base branch, normally `main`.
- PR belongs to the intended current project stage.
- PR does not include later-stage work.
- PR is mergeable.
- Required checks pass.
- If no checks exist, that absence is explicitly noted.
- Code Sentinel has set `gate: ready`.
- `gate: blocked` is absent.
- No unresolved actionable review feedback remains.
- The PR body or latest agent comment records what changed, evidence produced, docs updated, validation run, stage status, and next step.

Merge Warden must refuse clearly if any gate fails.

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
