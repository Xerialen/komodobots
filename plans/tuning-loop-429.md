# T5.3 (#429) — the automated tuning loop: bots self-learn bunnyhop without human guessing

## Mission link

docs/28 Phase 2 (M5): "reward shaping + automated tuning". Every training run's hyperparameters were
hand-picked until now. `ml/tune_onspeed.py` replaces the guesser: it samples configurations, trains each via
`ml/rl_onspeed.py`, grades every run by the HONEST route-grade on held-out routes (#428 relative,
selection-wired in #472), journals everything in the #426 experiment registry, seed-verifies the finalists
and re-grades the single winner on a tertiary never-ranked route set. Dual pre-review folded (auditor:
SOUND-WITH-FIXES, all four must-fixes in; NotebookLM: sound for v1 with the guards below).

**Ticket-wording supersession (stated, not silent):** #429's verification says "minimises the MSE score".
That predates D5/#469 — adherence-MSE is speed-blind (`route_grade.py` docstring documents the observed R5
failure: a bot can hug the route at half speed and win on MSE). The objective is the honest route-grade
ordering (`seg_faster_frac`, then `median_speedup_ratio`, then LOWER route-RMSE — the same
`grade_key` the checkpoint selector and the registry use), maximised on held-out routes. docs/28's T5.3 line
already says "Bayesian/Random search" with no MSE (verified — no docs/28 edit needed).

## THE DECISION — search strategy

- **Random search (CHOSEN for v1):** stdlib, deterministic + resumable, a proven strong baseline at this
  dimensionality (~7 tuned params), zero new deps, trivially auditable. AGAINST: sample-inefficient vs
  Bayesian at large budgets.
- **Bayesian (optuna etc.):** fewer trials to a good config, BUT a third-party dep on the training box,
  sampler state complicates resume/reproducibility, and the gate can't floor-test the optimizer. Deferred —
  the sampler is one function; swapping it later touches nothing else. (mode23_sweep's stage-2
  local-refinement-around-the-leader is the cheap in-repo upgrade pattern when wanted.)
- **Hyperband / successive halving:** REJECTED by the NotebookLM review — early-stopping trials
  institutionalizes the screening trap (below) for PPO.
- **Grid:** dominated by random search at fixed budget; no adaptivity.

## The honesty spine (both reviews folded)

- **NO reduced-step screening tier (nblm):** PPO learning curves CROSS — an early leader can be a memorized
  suboptimum. Every trial runs ONE full documented step budget (`--trial-steps`, default 200k, journaled per
  run). Fewer trials per night; the sweep is resumable and spans nights.
- **Trial 0 = the incumbent default config** — the control / "live point" (the ML gate's named-baseline
  invariant), inside the same environment group.
- **Driver-owned trial identity (auditor MF-1):** `config_id` is NOT computable pre-launch (it hashes the
  fully-resolved reward config incl. the data-derived band + the full trainer args). Identity = the
  deterministic `--out-ckpt` path (`ckpts/t<index>_s<seed>.pt`); the resume done-set matches on it;
  `config_id` is read BACK from the journal for seed-grouping. Crashed trials (start-without-final) are
  re-run on resume, and counted in the verdict.
- **Buffer-capped minibatch grid (auditor MF-2):** at the fixed rollout geometry (12 envs × 256 steps) the
  buffer is 3072 — the grid is {384, 768, 1536, 3072}; anything above is a silent full-batch alias.
- **kl_coef/ceiling pairing (auditor MF-3):** `kl_coef` is categorical {0.0, 0.02, 0.05, 0.1} INCLUDING the
  anchor-off arm (the owner's decision-B lane); the eligibility ceiling is PAIRED (1e9 when 0.0, else the
  0.32 default) — a low anchor coefficient under an unraised ceiling makes late reward-best iters ineligible
  (the documented d1-d3-d5 trap).
- **Seed-averaged finalists (nblm):** top-K (default 3) configs re-run to `--verify-seeds` (default 5) total
  seeds; sweep score = MEAN grade key; the verdict ALSO reports the WORST seed + spread (a fragile winner —
  one elite seed, the rest failing — is flagged, never hidden in a mean). All runs at the same full steps →
  same `config_id` groups them (no screening-generation split).
- **Tertiary test set (nblm, multiple-comparisons guard):** ranking N configs against one held-out route set
  can overfit the winner to those routes. The final winner (only it) is re-graded once on the NEXT disjoint
  holdout chunk (`--select-holdout-offset = n_reset_segments + select_grade_segments`, new eval CLI flag);
  the verdict reports both grades.
- **Winner keep:** best-seed ckpt copied read-only to `winners/` + sha256 (the registry `verify` lineage
  guard); resume-safe.
- **Refusals:** no code version resolvable → the sweep REFUSES TO START (every record would be
  provenance-incomplete = ineligible). More than one `environment_hash` in the journal → the verdict REFUSES
  a winner and lists the groups (mirrors the registry `best`).
- **Hard-coded honesty:** `superhuman_claim: false` + the sim-fidelity caveat in every verdict. The absolute
  claim needs the live engine + a recording + pov_fuse — never this driver.

## Pre-registered ranking rule (declared BEFORE any sweep runs — the gate asks for this; ALL EXECUTABLE)

Eligibility: completed + provenance-complete + route-graded with ≥ the selector's min valid references
(registry `eligible`). Ranking: mean `grade_key` over a config's eligible runs, within ONE environment
group. **The crown is restricted to the seed-VERIFIED finalist set** — after verification seeds land, a
previously lower-ranked single-seed config can top the full ranking; it is surfaced in the verdict as a
note ("verify it next pass"), never crowned unverified (Codex #474 P1-2). **Off-ramp (enforced in code,
`TERTIARY_OFFRAMP_FRACTION = 0.5`):** tertiary `seg_faster_frac` below half the ranked value →
`winner=None`, `refusal="overfit_to_ranking_routes: …"`, the refused candidate kept in the verdict for
audit, nothing blessed into `winners/`; a MISSING tertiary grade refuses too (fail closed). Seed
verification fills the FULL `--verify-seeds` quota on resume — already-complete candidate seeds never
consume it, crashed ones are replaced by the next candidate (bounded 4x). **Crownable requires the full
quota of completed, still-eligible runs** (checked both when the finalist finishes verifying AND again at
verdict time): persistent verification crashes → `winner=None` + an under-verified refusal pointing at
resume — a one-seed finalist is never crowned (Codex #474 round-2).

## Search space v1 (`komodobots.tune_space.v1` — embedded in every verdict)

| Param | Range | Why |
|---|---|---|
| lr | log-uniform [1e-5, 3e-4] | default 3e-4 at the top; R4/R5 ran 1e-4 |
| clip | uniform [0.1, 0.3] | around the 0.2 default |
| kl_coef | {0.0, 0.02, 0.05, 0.1} | incl. anchor-off (decision-B lane) |
| kl_anchor_ceiling | paired: 1e9 if kl_coef==0 else 0.32 | eligibility trap guard |
| ent_coef | log-uniform [1e-4, 3e-2] | default 0.01 inside |
| minibatch | {384, 768, 1536, 3072} | ≤ the 3072 rollout buffer |
| w_press | uniform [0.5, 3.0] | THE R5 lever (anti-bulldoze strength), default 1.0 |

Fixed per sweep (journaled; several are environment_hash pins): steps/trial, n_envs 12, rollout_steps 256,
ppo_epochs 4, vf_coef 0.5, horizon 385, ep_horizon 385, n_reset_segments (FORWARDED by the driver — see
the pool budget below; 30 on the current val slice), select_grade_segments 12, select_grade_min_valid 3,
split "val", map dm3, db/bsp/norm/anchors/init_ckpt, target_kl 0.03.

## Pool budget (learned from the FIRST real sweep, 20260702 — an honest full-refusal)

The reset states, the ranking holdout and the tertiary test set all draw from ONE shared ordering (the
same `select_start_segments` qualifier behind both `build_segments` and the eval — disjointness is exact).
The val dm3-slice pool measured **54 qualifying episodes at horizon 385**; the trainer's default
`--n-reset-segments 64` consumed everything, the skip-64 ranking holdout came up EMPTY (n_segments=0 in
every journal record), selection fell back on every trial, and the verdict refused all 30 runs — the
guards worked, the budget was wrong. **Rule: `n_reset_segments + 2 × select_grade_segments ≤ pool`**
(ranking chunk + tertiary chunk sit consecutively after the reset prefix). For this db/split:
**30 + 12 + 12 = 54**. The driver now FORWARDS `--n-reset-segments` to every trial. Measure a new pool
with `rl_onspeed.build_segments(db, split, coords, horizon, 99999)`; growing the pool (more demos in the
slice / a dedicated eval split) is a data-line follow-up.

## Run cost + budget (non-gating operator note)

Two indicative sources, both pre-#472 (no route-grade selection overhead): R3–R5 log-entry deltas suggest
~4–5 min per 200k-step run; the runbook memory's measured iter rate (≈3.5 s/iter at 2048 steps/iter)
suggests ~10–15 min. Treat both as indicative — the sweep self-measures (`wall_time_s` in every journal
record); size `--trials`/`--max-hours` from trial 0–2's real numbers. ~30–50 trials ≈ nblm's
meaningful-search floor for this dimensionality; `--max-hours` + the done-set make multi-night sweeps safe.

## Pinnacle sweep recipe (serial, one GPU; run env = /home/xerial/rl-onspeed, NOT a git repo)

```bash
# on aws-dev: sync main into the run env WITH the provenance stamp (back up first if unsure)
cd /home/ubuntu/projects/komodobots && git fetch origin main
git archive origin/main ml experiments scripts | ssh pinnacle-gpu 'tar -x -C /home/xerial/rl-onspeed/'
git rev-parse origin/main | ssh pinnacle-gpu 'cat > /home/xerial/rl-onspeed/CODE_VERSION'

# on pinnacle, from /home/xerial/rl-onspeed, in tmux (venv python has torch; system python3 does NOT):
/home/xerial/komodobots-ml-venv/bin/python -u ml/tune_onspeed.py \
  --sweep-dir /home/xerial/rl-onspeed/sweeps/$(date +%Y%m%d) \
  --init-ckpt /home/xerial/rl-onspeed/ckpts/rl_round6_r4init.pt \
  --db /home/xerial/komodobots/data/catalog/dm3_4on4_slice.sqlite \
  --bsp /home/xerial/komodo-v5-build/dm3.bsp \
  --norm-artifact /home/xerial/komodo-v5-build/gold/norm/normalization_stats.json \
  --anchors /home/xerial/komodobots/references/dm3_4on4_anchors.json \
  --resource-coords /home/xerial/rl-onspeed/data/catalog/resource_coords.dm3.json \
  --n-reset-segments 30 \
  --trials 30 --trial-steps 200000 --max-hours 8
```

(`CODE_VERSION` at the tree root is what the registry's code-version resolution reads on this non-git box;
without it every record is provenance-incomplete and the sweep refuses to start.)

Constraints: trials are strictly SERIAL (one GPU; one JSONL journal — concurrent appends could interleave).
Stop with SIGINT/SIGTERM — the sweep resumes via the done-set. Long sweeps: a hard-killed trial can leak a
`NamedTemporaryFile` ckpt in $TMPDIR (the trainer cleans up in `finally`) — check $TMPDIR occasionally.
`experiment_registry.py list/best/diff/verify --registry <sweep>/experiment_registry.jsonl` is the read path.

## Explicitly NOT in scope

Bayesian sampling (sampler swap later), parallel multi-GPU trials, live-engine validation of the winner
(owner-gated: recording + pov_fuse), automatic docs/ticket updates from sweep results, bsp content hashing
(the environment pin covers db/norm/anchors sha256 + code version; the bsp is pinned by path only — known
limitation, noted).
