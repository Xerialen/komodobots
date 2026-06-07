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
Phasekeeper implements stage work -> Code Sentinel reviews/hardens and comments a review-gate decision -> GitHub Actions apply labels and Merge Warden merges if gates pass -> Phasekeeper starts the next stage from updated main
```

Role boundaries are mandatory:

- Phasekeeper implements the current stage, updates docs/evidence, opens or updates the stage PR, and responds to review feedback that stays inside the same stage.
- Code Sentinel reviews and hardens PRs for code slop, validation gaps, documentation gaps, and north-star drift, then comments a review-gate decision. It must not directly change code, apply labels, or merge.
- GitHub Actions own review-gate label mutations, escalation labels, and second-opinion request comments.
- Merge Warden performs the final deterministic merge gate and merges only when all gates pass.
- Gemini is an on-demand second opinion only. It does not implement, set review-gate labels, or merge.

Hard separation:

- Phasekeeper must not merge.
- Code Sentinel must not merge, implement feature work, push commits, or apply labels.
- Gemini must not set review-gate labels, push commits, or act as merge authority.
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

## Blocker criteria

A blocker is a merge-stopping issue. Code Sentinel may block only for these criteria:

- P0 correctness or security regression: the PR likely breaks intended behavior, weakens safety/security, corrupts data/evidence, or creates a credible execution risk.
- Validation failure or missing required evidence: required checks fail, relevant tests fail, claimed behavior is not demonstrated, validation was skipped without justification, or no real output supports an important claim.
- Stage/scope violation: the PR implements later-stage work, mixes unrelated stages, or expands scope beyond the approved stage in a way that prevents safe review.
- Documentation/evidence gap for a meaningful change: code, config, workflow, experiment, architecture, environment, or assumption changes lack the required routed documentation or evidence record.
- Review/merge automation risk: workflow, permission, label, merge, or agent-role changes could allow stale approvals, accidental merges, privilege confusion, or unbounded automation.
- Unresolved actionable review feedback that would change merge safety.

Non-blocking issues must not keep the PR from merging. Examples: wording preferences, minor style issues, optional refactors, speculative improvements, follow-up experiments, or documentation polish that does not affect the ability to understand, validate, or safely merge the PR.

When blocking, Code Sentinel must provide a numbered `BLOCKERS:` list. Phasekeeper should address only that list inside the same PR unless Benjamin explicitly approves scope expansion.

## Second-opinion rule

Gemini may be used only as an on-demand second opinion. Invoke it manually on a PR with:

```text
/gemini review
/gemini summary
```

A second opinion may also be requested when Code Sentinel comments this exact line on a PR:

```text
SECOND_OPINION: requested
```

The `Review Gate Labeler` workflow translates that comment into the neutral label `opinion: requested`, and the `Request Second Opinion` workflow translates that label into a single `/gemini review` PR comment. Do not repeatedly request the same second opinion.

Use a second opinion when a PR is high-risk, changes review/merge automation, changes agent instructions or role boundaries, changes validation/scoring/experiment methodology, touches security-sensitive or execution-sensitive code, performs a large rewrite, or when Code Sentinel is uncertain.

Before approving a PR, Code Sentinel must decide whether the PR requires a second opinion. If required and no Gemini response is present, Code Sentinel must comment `SECOND_OPINION: requested`, comment `REVIEW_GATE: gate: blocked`, and explain that final approval is blocked pending second opinion.

After Gemini responds, Code Sentinel must reconcile the second opinion and still make the final review-gate decision. Gemini never sets `gate: ready`, never sets `gate: blocked`, and never merges.

## Anti-ping-pong escalation rule

The loop should run autonomously unless escalation is mandatory.

Maximum Code Sentinel blocked review cycles per PR: 2.
Maximum Gemini second-opinion reviews per PR: 2.

Escalation ladder:

1. First Code Sentinel block: Phasekeeper may fix the numbered `BLOCKERS:` list.
2. Second Code Sentinel block: Code Sentinel must request Gemini as the first escalation point if Gemini has not already reviewed the current dispute.
3. After Gemini responds: Phasekeeper may make one Gemini-informed correction attempt.
4. If the PR is still blocked after the Gemini-informed correction attempt, or if Code Sentinel and Gemini cannot converge after two Gemini reviews, Code Sentinel must stop the loop and require human decision.

Human escalation is mandatory when any of these are true:

- Code Sentinel has blocked twice and Gemini has already reviewed the disputed blocker set.
- Gemini has reviewed twice and the agents still disagree about merge safety.
- The same blocker class remains after two correction attempts.
- The next action requires a product/stage/scope decision rather than an engineering correction.
- The safe fix requires splitting, restarting, or materially changing the PR scope.

When human escalation is required, Code Sentinel must comment:

```text
ESCALATION: human-required
REVIEW_GATE: gate: blocked
```

The `Review Gate Labeler` workflow applies `cycle: needs-human`. At that point Phasekeeper must not continue automatic fix attempts. Benjamin decides whether to continue, split the PR, close/restart it, accept risk, or request another review.

## Review gate decision rule

Every Code Sentinel PR review must leave a clear review comment that ends with exactly one final review-gate decision line:

```text
REVIEW_GATE: gate: ready
```

or:

```text
REVIEW_GATE: gate: blocked
```

Code Sentinel must not apply the labels directly. The `Review Gate Labeler` workflow consumes the decision comment and applies exactly one final review-gate label:

```text
gate: ready
gate: blocked
```

Optional transient label:

```text
gate: reviewing
```

Escalation label:

```text
cycle: needs-human
```

The final labels are mutually exclusive. The workflow removes `gate: blocked` and `gate: reviewing` before applying `gate: ready`; it removes `gate: ready` and `gate: reviewing` before applying `gate: blocked`. A PR must never intentionally keep both `gate: ready` and `gate: blocked`.

Use `REVIEW_GATE: gate: ready` only when the PR meets the "Merge gate rule" below. Use `REVIEW_GATE: gate: blocked` only for a blocker under the blocker criteria above, missing required second opinion, or required human escalation. The merge executor consumes only the neutral label state; it does not depend on a specific agent name.

A pushed commit invalidates the prior review gate. `.github/workflows/review-gate-reset.yml` clears `gate: ready` and `gate: blocked` and sets `gate: reviewing` whenever new commits are pushed to a PR branch.

## Review guidelines

These guide Code Sentinel on every PR review.

Review focus, in priority order:

- Correctness and security regressions. (P0)
- Validation gaps: claims without evidence, missing or auto-skipped tests, no real run output. (P0)
- North-star drift: work that does not produce evidence toward the believable-bots question. (P1)
- Documentation gaps: code/config/experiment changes that did not update the routed doc. (P1)
- Code slop: dead code, needless complexity, duplicated logic. (P2)

End every review with the final decision line described above.

If a second opinion was required, also summarize how Gemini's feedback was handled before setting the final review gate.

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
- The workflow-applied label `gate: ready` is present.
- `gate: blocked` is absent.
- `cycle: needs-human` is absent.
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
