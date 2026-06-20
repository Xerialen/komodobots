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

## Agent roles and autonomous loop

This repository uses tool-agnostic roles. Benjamin may assign any capable agent
to either implementation or review work.

- **Coder Agent** - follows `coder.md`.
- **Reviewer Agent** - follows `reviewer.md`.
- **Merge executor** - deterministic GitHub Action; it does not implement or
  review.

The same agent must not act as both Coder and independent Reviewer for the same
PR unless Benjamin explicitly overrides role separation.

Beyond not being the same agent, the Reviewer should ideally run on a *different
LLM* than the Coder (for example, a Claude-authored PR reviewed by Codex or
Gemini, and a Codex-authored PR reviewed by Claude). A model reviewing its own
work is the weakest form of independence. Different-LLM review is strongly
preferred; if no different-model reviewer is available, a different agent or
session is an acceptable fallback, but note it as a weaker review.

Two gates must both pass to merge, and they are deliberately layered per best practice: a deterministic machine check is the real authority, the AI review is an advisory filter on top.

1. **Deterministic CI floor** - `.github/workflows/pr-tests.yml` runs the stdlib unit suite on a hosted runner for every PR. This is the hard, machine-checked gate.
2. **Reviewer filter** - a neutral PR label applied after a technical merge-safety review. The terminal labels are `gate: ready` or `gate: blocked`.

The deterministic merge executor (`.github/workflows/review-gate-merge.yml`, no LLM, no API tokens) merges only when `gate: ready` is present, `gate: blocked` is absent, the PR's base is **`main` or `dev`**, the PR is mergeable, and **every non-gate check (including `PR Tests`) is passing**. Both bases auto-merge so the staged-agent line (which targets `dev`) lands without a manual "fallback merge"; a `dev`->`main` PR whose head is a long-lived branch is never `--delete-branch`'d. It re-evaluates on `gate: ready` label events from both PR and issue-label webhook surfaces, `PR Tests` completion events, and a best-effort 5-minute reconciler for already-ready PRs. Label/CI events that arrive inside the 300-second ready-label cooldown sleep once, then re-read GitHub state and re-run the full gate, so merge does not depend on cron firing exactly on time. Branch protection would normally enforce this natively, but it requires GitHub Pro/public; the executor provides the same gate on the free private plan. **Gemini** is an **on-demand second opinion only** (`/gemini review`) - it does not auto-review and never merges.

```text
Coder Agent implements -> reset sets `gate: reviewing` -> Reviewer Agent reviews and applies `gate: ready` or `gate: blocked` -> deterministic Action merges on `gate: ready` if `PR Tests` and all other non-gate checks pass -> a Coder Agent starts the next stage from the updated base (`dev` for stage work; promoted to `main` via an umbrella `dev`->`main` PR)
```

Role boundaries are mandatory:

- Coder Agent implements the current stage, updates docs/evidence, opens or updates the stage PR, and responds to review feedback that stays inside the same stage.
- Reviewer Agent reviews only technical merge safety: correctness, regressions, security, reliability, CI/CD, GitHub Actions logic, workflow triggers, label/merge-gate logic, permissions, secrets, branch-protection assumptions, operational/deployment risk, data-loss/destructive behavior, and tests for changed behavior.
- Review automation or the assigned Reviewer posts the required structured review comment for the current head SHA and applies exactly one terminal label: `gate: ready` or `gate: blocked`.
- The merge executor (a deterministic, no-LLM Action) performs the final gate check and merges only when `gate: ready` is set and all gates pass.
- Gemini is an on-demand second opinion (`/gemini review`) - not part of the autonomous loop, and never merges.

Hard separation:

- Coder must not merge and must not self-apply `gate: ready`.
- Reviewer must not implement feature work or start the next stage.
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

The merge gate is a neutral PR label applied after reviewing the PR's current head SHA:

```text
gate: reviewing  -> transient; set when a PR opens, reopens, becomes ready for review, or receives new commits
gate: ready      -> Reviewer Agent found no blocking technical merge-safety issue for the reviewed head SHA
gate: blocked    -> Reviewer Agent found at least one blocking technical merge-safety issue for the reviewed head SHA
```

A pushed commit invalidates any previous decision: `review-gate-reset.yml` clears `gate: ready`/`gate: blocked` and sets `gate: reviewing`, so the gate always reflects the current head. If Codex cannot complete the review, leave `gate: reviewing` in place and say why; do not default to pass.

A **draft** PR is advisory-only: open a PR non-draft when you want it reviewed-and-merged, and never apply `gate: ready` to a draft. The merge executor skips drafts; does not treat `ready_for_review` as a merge trigger (Reset Review Gate owns that event); and authorizes only when the `gate: ready` label, plus the latest head-bound gate verdict, both post-date the most recent draft->ready promotion AND that latest verdict is itself a PASS (a later BLOCK vetoes an earlier PASS even if the `gate: blocked` label write failed). `gate-draft-guard.yml` also strips `gate: ready` and restores `gate: reviewing` if the label is ever applied to a draft.

Per-PR lifecycle:

```text
push/open PR -> reset to `gate: reviewing` -> Reviewer Agent reviews current head SHA and applies `gate: ready` or `gate: blocked` -> deterministic Action waits out the ready-label cooldown when needed, revalidates current GitHub state, then merges on `gate: ready` plus green `PR Tests` and no failing non-gate checks; the 5-minute reconciler is a best-effort backup
```

## Review guidelines

These guide the Reviewer Agent on every PR review. Do not review plan, roadmap, scope, architecture-plan deviation, north-star drift, or documentation drift. Do not block on style, naming, or formatting unless it creates a concrete defect risk.

Review focus, in priority order:

- Correctness, regression, security, or reliability defects.
- CI/CD, GitHub Actions, workflow trigger, label-gate, merge-gate, permission, secret, or branch-protection assumption defects.
- Operational/deployment risk, data-loss risk, destructive behavior, or stale-SHA/race-condition defects.
- Missing or broken tests for changed behavior when that creates concrete merge risk.

Block only for concrete merge blockers: runtime errors, broken or missing tests for changed behavior, security/permission risk, broken workflow/merge-gate logic, unsafe secrets, stale-SHA/race conditions, destructive behavior, incomplete implementation, or behavior that contradicts explicit technical acceptance criteria.

The required review comment format is:

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
Concrete technical notes only (or "None."). No plan-deviation notes.
```

## Merge gate rule

The merge executor may merge only when all are true:

- Target repository and PR are unambiguous.
- PR is open and non-draft.
- PR targets the correct base branch — `dev` for stage work, or `main` (both auto-merge).
- PR is mergeable.
- `PR Tests` is present and all its runs pass.
- No other non-gate check is failing.
- The `gate: ready` label is present and `gate: blocked` is absent.

The merge executor skips silently unless every gate passes. It comments only on an actual merge.

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
- Test-case or evidence workflow change -> update `docs/09_TEST_CASES_AND_EVIDENCE.md`
- Web/UI validation workflow change -> update `docs/10_AGENT_WEB_TESTING.md`

## Verification workflow

No theoretical code. Everything important must be proven.

Before modifying source, define how the change will be validated. Where possible, run the validation first to establish the current baseline or failure mode.

After implementing, run the validation again. If validation fails, fix the issue or document the blocker. Do not declare success without real output.

Record terminal output, logs, metrics, screenshots, MVD-analysis output, or other evidence in the relevant doc or PR comment.

**Eval integrity (mandatory on every data evaluation).** Before stating any conclusion, headline, or recommendation from a metric, gate, benchmark, eval, training run, or measurement — positive OR negative — apply the `eval-integrity` skill (`.claude/skills/eval-integrity/SKILL.md`): validate the metric's MEANING not just its value (open the caveats / `diagnostics_not_gated` fields and state what a pass does NOT prove); tag every number's provenance (run / seed / split / checkpoint) and never carry a number from one run into a claim about another; inspect the ground-truth artifact (the trajectory, the raw rows, the actual output) not just the summary score; interrogate a PASS as hard as a FAIL; and keep wording within the evidence (a passing proxy is not "the goal" / "human-level"). Every eval report must include a one-line "What this does NOT prove:". This rule exists because a passing gate was once reported as "human-level" when the underlying behavior failed — see the skill.

For test-case driven work, keep the durable test case and log each execution as
a test run. See `docs/09_TEST_CASES_AND_EVIDENCE.md`.

For web/UI changes, validate in a real browser and record the tool, URL,
viewport, console/network state, and screenshot or geometry evidence. See
`docs/10_AGENT_WEB_TESTING.md`.

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
