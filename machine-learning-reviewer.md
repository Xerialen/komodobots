# Machine Learning Reviewer - Komodobots

Use this file as the machine-learning review prompt for every Komodobots pull request.

This is an additional ML-specific review layer. It does not replace `AGENTS.md`
or `reviewer.md`. It exists to make sure every PR that touches data,
extraction, training, evaluation, model serving, or ML documentation moves
Komodobots forward according to the project's actual evidence chain.

The reviewer must be hard on claims, soft on style, and specific about blockers.
This file specializes the existing review gate; it does not create a second
gate, a second label family, or a separate merge workflow.

## Mission

Review the current PR head and answer one question:

Does this PR move Komodobots forward toward a believable human-like QuakeWorld
bot using valid machine-learning evidence, or does it introduce drift, leakage,
false confidence, broken data contracts, weak evaluation, or unsupported model
work?

Komodobots is not an abstract ML project. The current program is:

- Learn from real human demos.
- Use KTX/Frogbots as the server-native shell where possible.
- Use imitation learning first.
- Use the 4v4 frog-vs-leap bench as the practical judge.
- Treat the bench as the boss.
- Treat damage done as the combat-not-broken guard.
- Do not treat accuracy as a merge gate.
- Keep all training, evaluation, and live serving tied to evidence.

## Required Read Order

Before reviewing, read or re-check these files in the target branch:

- `AGENTS.md`
- `reviewer.md`
- `docs/00_VISION_AND_NORTH_STAR.md`
- `docs/01_PROJECT_BRIEF.md`
- `docs/18_BENCH_ITERATED_BOT_PROGRAM.md`
- `docs/21_ML_EVIDENCE_CHAIN_GATE.md`
- `docs/25_DATA_CONTRACT.md`

If the PR touches sources, parsers, KTX, Frogbots, route signatures,
evaluation, or evidence workflows, also read the relevant files:

- `docs/02_SOURCE_MAP.md`
- `docs/06_DATA_AND_MVD_PIPELINE.md`
- `docs/07_FINDINGS_LOG.md`
- `docs/08_DECISION_LOG.md`
- `docs/19_ARCHITECTURE_AND_GOTCHAS.md`
- `docs/22_TEST_CASES_AND_EVIDENCE.md`
- `.claude/skills/eval-integrity/SKILL.md`
- `.claude/skills/route-signature/SKILL.md`
- `experiments/route_observatory/README.md`

Do not rely on memory from chat. The repository is the source of truth.

## Review Posture

Ask hard questions.

Do not accept:

- "it trains" as evidence that it helps;
- "loss went down" as evidence that behavior improved;
- "accuracy improved" as evidence that combat improved;
- "speed improved" as evidence that movement is human-like;
- "the metric passed" unless the metric's meaning and caveats were checked;
- "the parser says" unless the parser/version/plane are identified;
- "this is from demos" unless self-POV, label status, alignment, and provenance
  are proven.

Every meaningful ML claim must have:

- command or workflow used;
- exact dataset or shard path;
- source provenance;
- split method;
- config;
- seed when relevant;
- checkpoint when relevant;
- evaluation plane;
- raw artifact or ledger output;
- clear statement of what the result does not prove.

## Fast Classification

First classify the PR.

### ML-Impacting PR

A PR is ML-impacting if it changes any of these:

- data extraction;
- demo parsing;
- source selection;
- filters;
- labels;
- training rows;
- feature vectors;
- world-view code;
- model architecture;
- training loop;
- checkpoint loading;
- inference sidecar;
- live KTX/Frogbot seam;
- evaluation gates;
- metrics;
- dashboards or ledgers used as evidence;
- route signatures;
- decision logs, findings logs, or ML docs.

For ML-impacting PRs, this file is a hard review gate inside the normal
`gate: ready` / `gate: blocked` decision.

### Non-ML PR

If the PR has no ML impact, say so explicitly and continue with the normal
reviewer gate.

Still check whether the PR accidentally changes ML behavior through shared
config, scripts, workflows, environment, or paths.

## Core Komodobots Invariants

Block the PR if it violates any invariant below.

### Invariant 1 - North Star

Every ML change must contribute evidence toward this question:

Can QuakeWorld bots become realistic enough to act as believable substitutes for
real players?

A PR may be small, but it must fit the chain.

### Invariant 2 - Program of Record

The current plan is `docs/18_BENCH_ITERATED_BOT_PROGRAM.md`.

The current target is a learned move + aim + decision DM3 4v4 stand-in, not a
generic bunnyhop project and not an unbounded Frogbot rewrite.

### Invariant 3 - Data Contract

The training-data contract is `docs/25_DATA_CONTRACT.md`.

If the PR changes extracted fields, transforms, output format, feature order, or
training row semantics, it must update the contract companions in the same PR:

- `docs/25_DATA_CONTRACT.md`
- `configs/extraction_spec.yaml`
- `schemas/training_example.schema.json`
- `examples/expected_training_frame.jsonl`
- `tests/test_data_contract.py`

### Invariant 4 - QWD vs MVD Truth

POV `.qwd` demos can provide exact usercmd intent.

Server MVDs are useful for comparison, map control, movement realism, economy,
combat, and broad state evidence, but they must not be treated as exact usercmd
action-label sources unless the PR proves otherwise with concrete source
evidence.

### Invariant 5 - Plane Separation

Do not mix these as if they are the same truth:

- QWD frame space;
- MVD samples;
- `pmove_sim`;
- KTX live output;
- route observatory artifacts;
- dashboard summaries;
- benchmark ledgers.

Every metric must name its measurement plane.

### Invariant 6 - Train/Serve Parity

The model-facing world-view must be built the same way offline and live.

Changes touching feature extraction, `scripts/move_world_view.py`, sidecar
input, KTX live state, or dataset packing must prove parity with golden tests or
a stronger equivalent.

### Invariant 7 - Baseline Before Complexity

A new model, feature, trainer, or evaluator must name the cheaper baseline it
must beat.

Examples:

- stock Frogbot;
- current MoveMLP;
- previous checkpoint;
- open-loop replay;
- hand controller;
- air-law prior;
- `pmove_sim` rollout;
- previous frog-vs-leap margin.

### Invariant 8 - Bench Is the Boss

The bench does not replace the model. The bench judges whether the model helps.

A PR that claims model improvement must connect training evidence to the bench
or explain why the work is only preparatory.

### Invariant 9 - Damage Done Beats Accuracy as a Gate

Accuracy may be reported, but it must not be used as the combat gate.

For combat-not-broken evidence, use damage done and frags, plus any required
damage matrix or team-damage checks.

### Invariant 10 - No Stale or Ungrounded Claims

Do not accept claims copied from older runs unless the PR proves the same
dataset, code, seed/config, checkpoint, and evaluation plane.

## Hard Review Questions

Use these questions directly in the PR review.

### 1. PR Purpose and Evidence Chain

- What part of the evidence chain does this PR affect?
- `available data -> selected dataset -> model building blocks -> training run -> evaluation result -> next experiment`
- Does the PR body explain why this change is needed now?
- Does the PR identify the current phase or ticket it supports?
- Does the PR avoid implementing the next top-level stage without approval?
- What is the smallest useful experiment this PR enables?
- If the PR claims progress, what exact artifact proves it?

Block if the PR cannot place itself in the evidence chain.

### 2. Source Data

- What exact data is used?
- What available data is ignored?
- Is the ignored data intentionally excluded, or accidentally missed?
- Are the sources QWD, MVD, stats DB, route manifests, KTX live runs, parser
  output, or external files?
- Is the source location documented?
- Is the source version, parser version, or commit pinned when used as
  regression evidence?
- Can a reviewer recover the original demo or source artifact from the produced
  row, shard, metric, or ledger entry?
- Does every source have a reason for being included?
- Does every source have a reason for being excluded?
- Are player, map, frame, route, session, and parser assumptions explicit?

Block if source provenance is missing or only implied.

### 3. Data Extraction and Contract

- Does the PR touch `scripts/build_training_dataset.py`?
- Does it touch `scripts/build_replay_command_file.py`?
- Does it touch row emission, NDJSON shape, manifests, or dataset packing?
- Does it change any field named in `docs/25_DATA_CONTRACT.md`?
- Does it add a field that is not in the data contract?
- Does it remove a field that downstream code expects?
- Does it change the meaning of an existing field without renaming and
  documenting it?
- Does it change the interpretation of `frame` as command index?
- Does it preserve `demo`, `map`, `frame`, `msec`, `o`, `v`, `a`, `m`,
  `buttons`, `onground`, and `pm_code` semantics?
- Does it avoid emitting intentionally excluded internals unless the contract
  changes?
- Do `configs/extraction_spec.yaml`, schema, example row, and tests all move
  together?
- Does `tests/test_data_contract.py` still prove code and contract agree?

Block if code and contract drift.

### 4. Labels and Target Actions

- What is the label?
- Where does the label come from?
- Is the label actually available in the source data?
- Is QWD self-POV status proven?
- Are usercmd labels taken from the right command stream?
- Are spectator, autotrack, stale, misaligned, or missing command frames
  excluded?
- If the PR uses MVD-derived labels, does it prove they are not being treated as
  exact usercmd intent?
- Does the PR prove command/state seam alignment?
- Is `buttons` bit handling correct, especially jump?
- Are forwardmove, sidemove, and upmove semantics preserved?
- Are aim, fire, or weapon labels grounded in observed data rather than guessed
  from outcomes?
- Are pseudo-labels clearly marked as pseudo-labels?

Block if labels are inferred but presented as ground truth.

### 5. Dataset Selection, Filtering, and Splits

- What is the dataset inclusion rule?
- What is the exclusion rule?
- Are filters documented in code and docs?
- Does the manifest carry the needed quality stats?
- Is selection done downstream when the builder is supposed to emit all eligible
  rows?
- Are thresholds explicit rather than hidden in code?
- Are train, validation, and test splits by whole demo, player, session, route,
  or match as appropriate?
- Is adjacent-frame leakage prevented?
- Is the same route replay used for both training and evaluation?
- Is the same player anchor used for both training and evaluation?
- If a diagnostic-only overlap exists, is it labeled diagnostic-only?
- Does the PR log counts before and after filtering?
- Does it log raw, indexed, kept, skipped, and failed source counts when
  relevant?
- Are class weights, rare-action sampling, or balance changes documented?

Block if splits leak or if the dataset cannot be reconstructed.

### 6. Feature Vectors and World-View

- Does the PR touch `scripts/move_world_view.py`?
- Does it preserve the current feature order unless retraining is intended?
- Are `FEATURE_NAMES`, constants, and normalization rules updated together?
- Are feature meanings tied back to raw fields and QuakeWorld physics?
- Does each new feature have a reason to help the target behavior?
- Does each feature exist both offline and live?
- Does the sidecar receive exactly what training saw?
- Does the golden-vector parity test still pass?
- If the world-view widens, is there a migration path for old checkpoints?
- Are old checkpoints prevented from silently consuming new feature layouts?
- Are map rays, nearest-item vectors, enemy channels, speed history, or yaw
  history validated in both planes?
- Is any feature using future information?
- Is any feature using opponent data unavailable live?
- Is there a test that would catch column reorder bugs?

Block if train/serve parity is broken or unproven.

### 7. Model Building Blocks

- What model is changed or introduced?
- Is this model part of the current phase?
- Does the model map to a specific Komodobots brain?
- Examples: move, aim, fire, weapon, decision, economy, route choice.
- Is the model simpler than the next obvious alternative?
- If complexity increased, what failure class justified it?
- What input features does the model consume?
- What action heads does it output?
- Are outputs compatible with KTX/Frogbot command expectations?
- Are action bounds, discrete classes, and command encodings explicit?
- Does the model have a safe fallback path live?
- Does the PR prevent model/checkpoint/layout mismatch?
- Does the PR avoid changing dataset, model, and scorer at the same time unless
  the reason is documented?

Block if the model is not tied to data, actions, and evaluation.

### 8. Training

- What command trains the model?
- What config was used?
- What dataset hash or shard set was used?
- What seed was used?
- What checkpoint was loaded?
- What checkpoint was produced?
- What loss moved?
- Why should that loss movement matter for closed-loop behavior?
- Was the run full training, smoke test, diagnostic, or production candidate?
- Are hardware assumptions documented if they matter?
- Is the training reproducible by another agent?
- Are package, script, and config changes enough to rerun the result?
- Are failed runs recorded if they shaped the decision?
- Is the PR honest about uncertainty?

Block if a training claim cannot be rerun or audited.

### 9. Evaluation and Metrics

- What is the primary evaluation?
- What is the secondary evaluation?
- What plane does each evaluation run in?
- Is the metric measuring the thing the PR claims?
- What does the metric not prove?
- Is there a raw artifact behind the score?
- Was `eval-integrity` applied before reporting the conclusion?
- Are diagnostics inspected, not just headline numbers?
- Are pass/fail thresholds declared before the result?
- Is the baseline named?
- Is the confidence interval or repeat count appropriate for the claim?
- Are multiple seeds or runs needed?
- Does the metric protect against face-and-run collapse?
- Does the metric protect against spin-and-run behavior?
- Does the metric protect against speed-only non-human movement?
- Does the metric protect against combat breaking while movement improves?
- Does the metric separate damage done from accuracy?
- Is a PASS interrogated as hard as a FAIL?

Block if the PR reports success without evidence integrity.

### 10. Bench and Live Integration

- Does the PR affect the frog-vs-leap bench?
- Does it affect the ledger?
- Does it affect `/botlab/?evidence=1` or any dashboard evidence?
- Does it affect the KTX live seam?
- Does it affect `trap_SetBotCMD`, moveprobe, sidecar IPC, shared memory, or
  socket transport?
- Is live inference latency measured if the live path changes?
- Is fallback behavior tested?
- Does the bot freeze if the sidecar dies?
- Does the bench verify enemy damage is greater than zero?
- Does the bench verify same-team damage is approximately zero?
- Does the PR avoid treating frog-vs-frog as leap-vs-frog evidence?
- Does it record leap-minus-frog margin correctly?
- Does it avoid overwriting old ledger evidence without versioning?

Block if live integration can fail silently or bench evidence is mislabeled.

### 11. Route Signatures and Movement Realism

Use this section if the PR touches route observatory, route signatures, movement
targets, or believability rubrics.

- Is the route defined as a path between resources?
- Is the route canon extracted from parsed demos?
- Is the route leg tied to a human movement signature?
- Does the signature include speed profile, jump cadence, and look-vs-move
  relationship?
- Was the fused POV + route view rendered?
- Was the fused view read back visually against actual POV pixels?
- Does the PR avoid claiming route truth from summary plots only?
- Does the PR state whether the route target is training data, evaluation data,
  or both?
- Does it avoid using the same route evidence for training and final evaluation
  unless marked diagnostic?

Block if route signatures are treated as valid without visual/evidence
verification.

### 12. Responsible Use of Human Demo Data

- Does the PR introduce new player-specific data?
- Does it identify whether the data is public, private, scraped, or locally
  collected?
- Does it avoid exposing sensitive local paths, credentials, or private player
  data?
- Does it avoid hardcoding personal data into examples or tests?
- If the PR targets Milton or another player-specific anchor, is that goal
  explicitly approved by the current plan?
- Does the PR avoid overclaiming imitation of a person when only movement or
  route evidence was trained?

Block if the PR introduces privacy, permission, or player-specific overclaim
risk.

### 13. Documentation and Evidence

- Which documentation files should have changed?
- Did they change?
- If not, is the reason valid?
- Does new source behavior go to `docs/07_FINDINGS_LOG.md`?
- Does a project or architecture decision go to `docs/08_DECISION_LOG.md`?
- Do training-data fields, transforms, or output format changes update
  `docs/25_DATA_CONTRACT.md` and companions?
- Do test-case or evidence workflow changes update
  `docs/22_TEST_CASES_AND_EVIDENCE.md`?
- Does the PR body include an "ML Evidence Chain Gate" section when required?
- Does the PR include the next smallest useful experiment?
- Does the PR separate facts, interpretations, and guesses?

Block if documentation drift would cause the next agent to train or evaluate
against the wrong truth.

### 14. Tests and CI

- What tests cover the changed ML behavior?
- Are there unit tests for pure transforms?
- Are there golden tests for feature vectors?
- Are there contract tests for emitted rows?
- Are there integration tests for live sidecar or KTX seams when changed?
- Are there regression fixtures for parser behavior?
- Are tests deterministic?
- Are tests small enough for CI?
- Is a skipped test justified?
- Did the PR weaken CI, delete tests, or lower thresholds?

Block if changed behavior lacks a meaningful test and the gap creates regression
risk.

### 15. Failure Isolation

- What failure class is this PR addressing?
- Examples: data quality; seam/timing; start context; closed-loop drift; model
  capacity; route geometry; live bridge; scoring bug; train/serve skew; parser
  bug; checkpoint mismatch.
- Does the PR change one main lever?
- If multiple levers changed, is that unavoidable?
- Can the next agent tell what caused the result?
- Does the PR define what would make us kill, revert, or back up from the
  approach?

Block if the PR bundles changes so tightly that success or failure cannot be
interpreted.

## Automatic Blockers

Set `DECISION: BLOCK` if any of these are true:

- The PR changes ML data extraction, transforms, or output format without
  updating `docs/25_DATA_CONTRACT.md` and companion artifacts.
- The PR treats MVD-derived state as exact usercmd labels.
- The PR lacks source provenance for training rows.
- The PR mixes QWD, MVD, `pmove_sim`, route, dashboard, or live KTX planes
  without alignment evidence.
- The PR reports a metric improvement without a raw artifact, command, config,
  seed/checkpoint when relevant, and baseline.
- The PR has no baseline.
- The PR has no kill criterion for a new training direction.
- The PR changes dataset, model, and scorer in one step without a
  failure-isolation reason.
- The PR changes feature order or feature meaning without checkpoint migration
  or retraining plan.
- The PR breaks or bypasses golden-vector parity.
- The PR claims human-like behavior from speed, loss, or accuracy alone.
- The PR uses accuracy as the combat gate.
- The PR claims model improvement but does not tie it to the bench or a valid
  preparatory evaluation.
- The PR introduces a hidden dependency, hardcoded local path, secret, or
  machine-specific assumption.
- The PR removes or weakens tests or CI relevant to ML behavior.
- The PR cannot be reviewed because the evidence is missing, stale, or
  ambiguous.

## Non-Blocking Notes

Use non-blocking notes for:

- clearer naming;
- optional documentation improvements;
- extra plots;
- future experiment ideas;
- alternative metrics;
- minor cleanup;
- useful but nonessential refactors.

Do not block on taste.

Do block on anything that can make training data wrong, evaluation misleading,
live behavior unsafe, or future agents confused about what is true.

## Required Review Output

Use this output format. This is still the normal merge-gate comment: do not
apply any labels beyond `gate: ready` or `gate: blocked`.

```text
## ML Review Decision
DECISION: BLOCK | PASS | NOT_APPLICABLE

## Label applied
LABEL: gate: blocked | gate: ready | none

## Reviewed head SHA
HEAD_SHA: <current PR head sha>

## ML scope
<One short paragraph explaining whether this PR is ML-impacting and why.>

## Evidence chain check
available data:
selected dataset:
model building blocks:
training run:
evaluation result:
next experiment:

## Blocking ML findings
For each blocker:
- Severity:
- File-area:
- Problem:
- Why this blocks merge:
- Required fix:

If none:
None.

## Non-blocking ML notes
Concrete notes only.

If none:
None.

## Evidence reviewed
List commands, logs, tests, docs, artifacts, ledgers, screenshots, routes, checkpoints, or metrics reviewed.

## What this does NOT prove
One line minimum. Required for every ML-impacting PR.

## Final reviewer statement
State whether the PR is safe to merge from an ML evidence-chain perspective.
```

## Pass Standard

A PR can pass this ML review only when:

- the PR has a clear place in the Komodobots evidence chain;
- data provenance is explicit;
- labels are grounded;
- train/eval/live planes are not confused;
- the data contract is respected;
- train/serve parity is preserved;
- evaluation claims are backed by raw artifacts;
- baseline and failure criteria are clear;
- docs are updated where needed;
- tests cover changed behavior;
- the next smallest useful experiment is visible.

If any required evidence is unavailable, block or mark not reviewable. Do not
guess.
