# T4.2 (#426) — the experiment run-journal: no good training config is ever lost

## Why / what feeds what

The systematic hyperparameter-tuning loop (T5.3 / #429) will run hundreds of PPO training loops on the
offline 4090, each with different settings, and must keep whichever scores best on the **honest route-grade**
(#428, now driving checkpoint SELECTION via #472). That needs a durable, queryable record of every run's
**(config → honest-grade result → checkpoint)**. #426 has no upstream deps and gates #429.

## THE DECISION — tracking tool (owner sign-off surfaced in the PR; docs/28 updated in the same PR)

- **Weights & Biases** — FOR: ticket option, best UI. AGAINST: **cloud** — run data leaves the box; the RL
  runs live on an offline home 4090 deliberately; needs network/auth; a data-egress decision.
- **MLflow (local)** — FOR: ticket option, rich UI. AGAINST: heavy non-stdlib dependency — cannot gate in
  the stdlib CI floor; a server/store to operate; exceeds what a single-box sequential search consumes.
- **CHOSEN: minimal stdlib JSONL run-registry** (`ml/pipeline/experiment_registry.py`) — two appended
  records per run (start + final) + a query CLI (`list` / `best` / `diff` / `verify`). FOR: stdlib → gates
  in the CI floor; no cloud; exactly what #429 consumes; the repo has ALREADY run a resumable ranked sweep
  on plain JSONL (`scripts/mode23_sweep.py` — config-id hashing, resume-by-id, ranking); `rl_onspeed`
  already builds a run-meta dict at save (ml/rl_onspeed.py:859 on the pre-#472 main), so config+result are
  formalise+persist. AGAINST: no web UI; the provenance spine (run_id, code version, data hashes, seed
  capture, status) is NEW code we own. This is a **deliberate deviation** from the ticket's literal
  "MLflow or Weights & Biases".

## The honesty spine (auditor + NotebookLM review, folded)

Dual pre-review 2026-07-01: **auditor** (code-truth vs origin/main, verdict SOUND-WITH-FIXES) +
**NotebookLM** (methodology: "stdlib registry is sufficient at this scale" + named guards). All must-fixes
are in the design below:

- **code_version trap (auditor MF-2):** the pinnacle run dir is a `git archive` sync — NOT a git checkout —
  so `git rev-parse` fails exactly where real runs happen, and the existing `git_sha()` helper would
  silently return "UNKNOWN" (what the ML gate blocks on). Resolution order: `--git-sha` arg > a
  `CODE_VERSION` file at the tree root (**the sync recipe must write it**: `git rev-parse HEAD >
  CODE_VERSION` before shipping) > `git rev-parse`. All missing → the record is written with
  `provenance_incomplete: true`, visible in `list`, **ineligible** for `best`/ranking.
- **Failed runs are recorded (auditor MF-4):** a `start` record is appended when training begins; a run
  with no `final` = crashed or still running — visible, marked `incomplete`. The ML gate asks "are failed
  runs recorded if they shaped the decision?" — they are.
- **Full config, not a cherry-picked list (auditor MF-5):** the start record persists the complete resolved
  `vars(args)` + the fully-resolved reward config — seed, minibatch, rollout_steps, horizon,
  n_reset_segments, db, norm_artifact included by construction.
- **environment_hash guard (NotebookLM C1):** sha256 over (code version, db/norm/anchors sha256s, the
  eval-route pins: split/horizon/holdout-skip/segment count). `best` NEVER ranks across different
  environment hashes — it refuses and lists the groups. Apples-to-oranges comparisons are structurally
  impossible to make silently.
- **Lucky-seed guard hook (NotebookLM C2):** `config_id` excludes the seed and output paths, so
  seed-replicates of one configuration share an id — #429 re-runs top configs across seeds and groups by
  it. (The re-run policy itself is #429 scope.)
- **Artifact lineage (NotebookLM C3):** the final record pins the ckpt path + sha256 + size; `verify`
  recomputes and flags MISSING/MISMATCH. (Immutable copies/chmod of winner ckpts = #429 driver policy.)
- **Nullable grade (auditor MF-1):** `result.route_grade_summary` is None unless `--select-by-route-grade`
  graded the selected candidate — the journal works under every selection mode.
- **Naming (auditor b):** "registry" alone is taken (the FEATURE registry) — module + file are
  `experiment_registry` and the record schema is the repo-convention string
  `komodobots.experiment_run.v1` (model-card precedent), not a bare int.

## Wiring (additive; zero behavior change to training/selection)

`train()` calls `start_run` right after env construction and `finalize_run` right after `save_rl_ckpt` —
both wrapped so a journal failure warns loudly but never kills a training run. New CLI: `--registry`
(default `auto` = `experiment_registry.jsonl` next to `--out-ckpt`; `off` disables) and `--git-sha`.
The registry module never imports torch (torch version is read from `sys.modules` if already loaded).

## Verification

- Floor (the merge gate, `tests/`): 16 stdlib tests — start/final join + crashed-run visibility, torn-tail
  tolerance, schema guard, seed-invariant config_id, environment-group refusal, provenance-incomplete
  ineligibility, CODE_VERSION resolution, ckpt sha256 tamper/missing detection, config diff, CLI smoke,
  path resolution, JSON-serializable records.
- `ml/rl_onspeed.py` wiring: py_compile + review (torch-gated; the integration is call-through into the
  floor-tested module). Any registry lines shown in the PR are labeled SYNTHETIC (from the unit tests) —
  no run-based claims.
- First real journal record: the next pinnacle training run (#429 work) — the sync step gains
  `git rev-parse HEAD > CODE_VERSION`.

## Explicitly NOT in scope (named, not silent)

- The tuning loop itself (#429): the search driver, seed-averaging re-runs, winner-ckpt immutability.
- Any UI. `list`/`best`/`diff`/`verify` are the owner's and the loop's read path.
- Retro-import of pre-journal runs.
