# DM3 4on4 stand-in program — status & resumption (2026-06-14)

Cold-start state for the learned-brain DM3 4on4 stand-in program. Program of record:
`docs/12_DM3_4ON4_STANDIN_PROGRAM.md` (on `main`). Decision record: `docs/08_DECISION_LOG.md`
(2026-06-14 entry, Decision Point Alpha → Megalodon Milton). This file = "where we are, what's
proven, what's next, and where everything lives" so a fresh agent can resume without the chat.

## Git / worktree state

- **`main`** tip `e73efc8` — `docs: DM3 4on4 stand-in program (docs/12) + Decision Point Alpha (#172)`.
  PR #172 merged by explicit owner override ahead of the #170 Codex review (recorded on the PR).
- **ML work** lives in a separate worktree: **`C:\Users\benya\projects\quakeworld\komodobots-ml`**
  on branch **`ml/dm3-4on4-standin`**. **4 commits ahead of `main`, NOT pushed, NOT #170-reviewed:**
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

- **Codex post-hoc review of merged #172** (agent `af92b7b18fb45b83b`) — dispatched, had not
  reported back as of this checkpoint. If it surfaces a docs/12 factual issue → fix-forward.
- **#170 review of the 4 ML commits** — not yet done; required before any ML PR to `main`.
- **Branch not pushed.**

## The forward fork (undecided at checkpoint)

Per the ~1 s ceiling, further *offline* training has diminishing *validated* returns until
full-route validation exists. Candidate next moves:
1. **Consolidate** — push `ml/dm3-4on4-standin` + Codex #170 review of Stage-0→Stage-2.
2. **Live KTX path** — Stage-1 live bot infra + the deferred Stage-0 spike 2 (live-bridge
   benchmark: live-load + per-tick-evaluate a quantized policy at 8 slots within budget). Needs the
   live server (servexeri) + engine work.
3. **Upgrade pmove_sim** with lift/submodel (+ opponent) collision → extend offline closed-loop
   validation past ~1 s without the live server.
4. **Stage 3 — learned AIM head** (target-relative angle-trajectory imitation; inherits the ~1 s
   sim-validation limit until 2 or 3 is resolved).

Recommendation at checkpoint: (1) consolidate, then (2)/(3) to resolve validation before building
the next learned tier.

## Reproduce / verify quickly

- Anchor: `python scripts/extract_dm3_4on4_anchors.py` (consumes v32 analysis.json + manifest).
- Clean-yield: `experiments/stage2/move-bc-dataset/analyze_clean_yield.py` (shard-based, ~282 s full corpus).
- Stage-2 retrain/eval: `experiments/stage2/move-bc-train/{build_dataset,train,eval_openloop,eval_closedloop}.py` in the WSL venv.
- 526 probe: `experiments/stage0/edge-526/probe_edge_526.py`.
