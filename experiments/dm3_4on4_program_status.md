# DM3 4on4 stand-in program — status & resumption (2026-06-14)

Cold-start state for the learned-brain DM3 4on4 stand-in program. Program of record:
`docs/12_DM3_4ON4_STANDIN_PROGRAM.md` (on `main`). Decision record: `docs/08_DECISION_LOG.md`
(2026-06-14 entry, Decision Point Alpha → Megalodon Milton). This file = "where we are, what's
proven, what's next, and where everything lives" so a fresh agent can resume without the chat.

## Git / worktree state

- **`main`** tip `e73efc8` — `docs: DM3 4on4 stand-in program (docs/12) + Decision Point Alpha (#172)`.
  PR #172 merged by explicit owner override ahead of the #170 Codex review (recorded on the PR).
- **ML work** lives in a separate worktree: **`C:\Users\benya\projects\quakeworld\komodobots-ml`**
  on branch **`ml/dm3-4on4-standin`** (pushed to `origin` 2026-06-14; #170 review deferred — see
  "Pending / open"). Commits beyond `main`:
  - `9bb4a14` stage0: data census, 526-edge probe, 4on4 anchor build (3 spikes)
  - `647de66` stage2-prep: build MOVE BC pool dataset + label-integrity yield
  - `6eb5155` harden: promote 4on4 gate anchor (8 players, v32) + 2x MOVE clean-yield
  - `0b20414` stage2: train MOVE BC policy → GO (beats air-law prior on both gates)
- The **main checkout** (`…\komodobots`) has unrelated pre-existing dirty files from a prior
  session (docs/03/05/07, several lab/scripts/tests, ztricks.json, untracked replay/ + a test) —
  **left untouched**, not ours to commit.

## What is PROVEN (this session)

- **Risk #1 (corpus exists?) — RETIRED.** 472 self-POV 4on4 dm3 demos, **37.56M usercmd frames**,
  255 distinct players. `.qwz` decompression solved (Qizmo 2.91). Learned MOVE + aim-tracking BC
  are data-feasible. Artifacts: `experiments/stage0/data-census/`.
- **Risk #2 (526 a physics ceiling?) — RETIRED.** 526 qu/s at the dm3 SNG→RL edge is reachable
  with margin (human 528, validated 529 on pmove_sim; free-air optimum 552; run-up gives 342
  air-frames vs 208 needed). Binding constraint = **controller quality / corridor navigation**, not
  accel/geometry. Artifacts: `experiments/stage0/edge-526/`.
- **Gate anchor (risk #6) — promoted off diagnostic-only.** 8 elite players × 8–14 dm3 4on4 demos,
  schema **v32**, all M/E/A/P bands cleared the ≥5-players/≥5-demos floor, G-P1 positioning pass
  added, plane stated per metric. `references/dm3_4on4_anchors.json` (+ README, extract script).
- **MOVE BC dataset.** Pool over 465 dm3 self-POV demos (37.3M frames). Clean physics-faithful
  yield improved **2.88M → 5.85M frames (~22.6 h @ 72 Hz)** via a per-frame clean mask. Dominant
  contamination = player-collision 78.6% (intrinsic to 4on4). `experiments/stage2/move-bc-dataset/`.
- **Stage 2 — MOVE BC policy trained, verdict GO.** MoveMLP (18.4k params). Open-loop retention
  **0.180 vs air-law prior 0.074 (~2.4×)**; closed-loop beats the hand-mover at every horizon, 1 s
  avg 243 ≈ human 257. docs/12 KILL (BC < prior) did not fire. `experiments/stage2/move-bc-train/`.

## Key findings / caveats to carry forward

1. **~1 s offline-sim validation ceiling (substrate).** `pmove_sim` is worldmodel-only (no
   lifts/submodels/player collision), so beyond ~1 s even *recorded human inputs* drift out of
   route/bands. Closed-loop sim validates only ~1 s horizons. **Full-route validation needs either
   submodel physics in pmove_sim or the live KTX path.** Surfaced, not tuned around.
2. **Cross-population caveat.** Gate anchor = **modern** hub players (Milton/reppie/andeh/XantoM/
   bps/realpit/carapace/yeti, via QW Hub CDN MVDs, since local modern-KTX corpus was thin and the
   classic `.qwz` are POV/movement-only, predating the KTX damage stream). MOVE BC corpus =
   **classic-era** POV players (akke/ParadokS/crit…). Different populations; elite bhop movement is
   fairly era-stable but it's a systematic offset to watch.
3. **POV state is action-labels-only.** Shard `onground`/`pm_code` are degenerate (POV
   svc_playerinfo carries no server ground flags) — dropped as features; sim derives ground from
   geometry. AIM target-selection still needs POV×MVD fusion (Stage 3).
4. **Per-player demo depth is thin** → realistic shape is pool-pretrain + per-player fine-tune, not
   single-elite clone from scratch.

## WSL2 artifact locations (gitignored / not in repo)

- `~/komodobots-ml-venv` — scoped venv, **torch 2.6.0+cu124**, CUDA verified on the RTX 4090.
- `~/move_bc_shards/` — 9.1 GB NDJSON (state,action) shards (465 dm3 demos).
- `~/move_bc_dataset.npz` (35 MB) — packed clean training set; `~/move_bc_policy.pt` (78 KB) — the trained MoveMLP.
- `~/ctv_decomp/` — ~5.6 GB, 478 decompressed self-POV `.qwd`; `~/qizmo_bundle/` — Qizmo 2.91 decompressor.
- mvd_analyzer `analysis.json` (v32) for the anchor demos live under the main checkout's gitignored `artifacts/`.

## Pending / open

- **Branch pushed** to `origin/ml/dm3-4on4-standin` (2026-06-14). Consolidation done.
- **#170 review deferred deliberately** ("too early" — owner call). Not opening a PR to `main`
  yet, so the #170 gate is not tripped; the cross-model review happens when an ML PR is actually
  raised, not before. (The Codex #172 post-hoc dispatch is likewise not being waited on.)

## Progress since checkpoint (2026-06-14)

- **Closed-loop ceiling root-caused** (see `experiments/stage2/move-bc-train/
  closed-loop-ceiling-diagnosis.md`). The `recorded`-human controller itself drifts to 88.9 qu by
  2 s while the single-player SNG→RL route stays at 0.2 qu over ~9 s — so the ceiling is the sim
  **omitting physics**, dominated by **opponent-player collision (78.6 % of dataset contamination)**,
  not brush submodels and not the physics core. Absolute trajectory-match is also chaos-capped
  long-horizon regardless of collision → the gate metric should migrate to route-completion +
  speed-band retention (distributional).
- **Multi-physent trace foundation built** in `scripts/pmove_sim.py`: `player_trace` now iterates
  world + a physent list (nearest-hit wins); `PhysEnt`, `build_box_hull` (Quake `SV_InitBoxHull`
  port), `make_player_physent` (Minkowski-expanded opponent box), `Pmove.load_submodels()` (6 dm3
  brush submodels, at-rest). **Worldmodel-only default is byte-identical to the validated baseline**
  (full `run_pmove_validation.py` regression: human 0.204/0.121/0.178, bot anchored p95 0.004,
  edge 529.08 — all unchanged). Tests: `tests/test_physent_collision.py` (regression + swept box
  block + submodel opt-in), ALL PASS.

## The forward fork (corrected build order)

1. ~~Consolidate (push)~~ — DONE.
2. **Opponent-ghost collision (the 78.6 % piece) — THE NEXT DECISION.** Needs a **POV↔MVD per-tick
   opponent-position sync** (POV `.qwd` timeline ↔ MVD all-player positions) to inject opponents as
   box physents. The trace machinery is ready; the sync pipeline is not built. High reuse: it is
   **also the Stage-3 AIM target-selection prerequisite**. Success metric: the `recorded`-human
   closed-loop route_err at 2 s drops materially from 88.9 qu.
3. **Distributional closed-loop gate** — route-segment completion + speed-band retention over many
   starts (docs/12 G-M1), replacing absolute position-match past ~1 s. Cheap, on-box.
4. **Moving submodels** (lift timing from KTX QC) — last, lowest yield (submodels are secondary to
   players).
5. **Live KTX path** / **Stage 3 learned AIM** — after validation is trustworthy.

Recommendation: (2) the POV↔MVD opponent sync is the real next build (unblocks both honest
closed-loop validation *and* Stage-3 AIM) — but it is a new data pipeline, so it is the next
decision to greenlight. (3) can land in parallel cheaply.

## Reproduce / verify quickly

- Anchor: `python scripts/extract_dm3_4on4_anchors.py` (consumes v32 analysis.json + manifest).
- Clean-yield: `experiments/stage2/move-bc-dataset/analyze_clean_yield.py` (shard-based, ~282 s full corpus).
- Stage-2 retrain/eval: `experiments/stage2/move-bc-train/{build_dataset,train,eval_openloop,eval_closedloop}.py` in the WSL venv.
- 526 probe: `experiments/stage0/edge-526/probe_edge_526.py`.
