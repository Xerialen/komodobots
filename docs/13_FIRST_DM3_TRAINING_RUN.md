# First DM3 MOVE Training Run — Implementation Plan

**Status:** implementation plan (not yet executed as the canonical clean run).
**Target repo:** `komodobots-ml` worktree at `/mnt/c/Users/benya/projects/quakeworld/komodobots-ml`, branch `ml/dm3-4on4-standin`.
**Companion (this repo):** the seam / runner / dashboard.

> **Context found during research.** A complete Stage-2 MOVE-BC run **already executed** and returned **GO** (`experiments/stage2/move-bc-train/results.json`, `train_metrics.json`, `closedloop_metrics.json`; checkpoint `~/move_bc_policy.pt` exists on the 4090). That run trained on the *pre-allowlist* pool (462 demos). This plan documents the **first run on the committed clean `dm3_4on4_clean_allowlist.txt` corpus** — the canonical, reproducible "ONLY dm3 4on4" run, end-to-end through both offline gates **and** the in-lab 4v4 behavioral check. The 39 excluded demos are ~0.49% of frames, so the clean checkpoint is expected to be behaviorally near-identical to the pooled one; the *value* is provenance alignment (checkpoint matches the committed corpus definition), not a metric jump. Stated, not hidden.

---

## 1. Objective & scope

**Objective.** Train the Stage-2 **MOVE** policy — a small discrete behavioural-cloning controller that imitates elite human dm3 4on4 movement micro-commands — on the committed clean dm3 corpus, on the RTX 4090, and validate it through (a) the open-loop reproduction/retention gate, (b) the closed-loop `pmove_sim` MOVE gate, and (c) an in-lab 4v4 dm3 behavioral check whose ledger renders on the dashboard.

**What MOVE is (verified in code).** `MoveMLP` (`experiments/stage2/move-bc-train/train.py:41-54`): a `6 → 128 → 128 → {3,3,2}` ReLU MLP, **18,440 params**, three discrete action heads:
- `fwd` ∈ {back, none, fwd} (3-way)
- `side` ∈ {left, none, right} (3-way)
- `jump` ∈ {0, 1} = `BUTTON_JUMP`

Input is a 6-dim **state-only, velocity-relative, map-agnostic** feature vector (`build_dataset.py:14-23`, `train.py:37`): `["hspeed/320","vz/320","lvm_sin","lvm_cos","moving","pitch/90"]`, where `lvm` is the signed angle between view-yaw and velocity-heading (the QW air-accel control axis), encoded as sin/cos so it wraps safely.

**Explicitly out of scope (Stage-3+, do not build here):**
- **Aim / view control.** The policy outputs **move only**. View-yaw enters as an *input feature* (`lvm`) and is **replayed from the human** in both gates and in the live seam (`docs/15_LIVE_VALIDATION_LOOP.md:79-88`). Learned view-yaw is AIM, deferred to Stage 3.
- **View/aim believability coupling** (DeepFrag's primary bot-detector) — a **Stage-3 acceptance metric, not a v1 gate** (`docs/15:84-88`). It only bites once synthesized view exists.
- **DECIDE / economy, team coordination, learned multi-bot** (`docs/12` §5, §7 Stages 4–5).
- **The cracked bhop formula.** It will later slot into the `airlaw_action` seam; do **not** block on it.
- **Architecture changes** (GRU variant) — a documented follow-up only if closed-loop later shows the MLP needs phase memory (`train.py:10-12`).

**Kill criterion (carried from docs/12 Stage 2).** If BC open-loop retention `<` the analytic air-law prior, the learned MOVE is abandoned and the hand-mover is kept (`eval_openloop.py:310-312`). The prior pooled run did **not** trip this (BC 0.180 vs air-law 0.074).

---

## 2. Data selection

**Corpus = the committed clean dm3 4on4 self-POV index** (no separate copy — the cleaned corpus *is* the committed index).

- **Clean-frame index:** `experiments/stage2/move-bc-dataset/clean-segment-index.json` — schema `komodobots.stage2.move_bc_clean_index.v1`. **465 demos**, **5,847,254 clean frames**; tier split A=2,664,030 / B=2,480,400 / C=702,824 frames; by-demo A=169, B=199, C=97. Each entry `{demo, cov, frames, base_clean, imp_clean, imp_runs, tier}`.
- **Clean "ONLY dm3 4on4" allowlist (the new filter):** `experiments/stage2/move-bc-dataset/dm3_4on4_clean_allowlist.txt` — **433 demos kept**, 39 excluded (22 trick, 7 wrong-map, 5 CTF, 2 3v3, 1 domination, 1 howto, 1 comedy; `dm3_4on4_clean_selection.md:5-19`). Removes contaminants the pooled run still contained.
- **Player attribution:** `experiments/stage2/move-bc-dataset/selfpov_4on4_demolist.tsv` (472 rows, `<player>\t<demo.qwd>`), consumed by `build_dataset.py:209-215`. **Caveat:** the `player` column is a filename heuristic, unreliable for some demos — fine for a *pooled* run, not for per-player tiering (out of scope here).

**Counts for this run (clean intersection):** demos in the clean index **and** on the allowlist **and** with a shard. Expect ~430 demos / ~5.8M clean frames.

**Train/val split — BY DEMO, never by frame** (`train.py:14-16, 57-64`). Frames inside one match are autocorrelated, so a frame split leaks and inflates val accuracy. Default `--val-frac 0.15`, `--seed 0` → ~365 train / ~65 val demos, deterministic per seed (same held-out demos across train/eval).

---

## 3. Data prep (exact commands)

All heavy compute runs **in WSL2 Ubuntu-24.04** via the scoped venv `~/komodobots-ml-venv`. Repo reachable at `/mnt/c/Users/benya/projects/quakeworld/komodobots-ml` inside WSL.

**Status — most prep is already done on the 4090:** shards `~/move_bc_shards/` (472 `.ndjson`, 9.1 GB); packed `~/move_bc_dataset.npz` (`X=(5847254,6) float32`, `Y=(5847254,3)`); decompressed `~/ctv_decomp/` (478 `.qwd`).

### 3a — (only if shards are missing) extract POV `.qwd` → NDJSON shards
```bash
V=~/komodobots-ml-venv/bin/python
cd /mnt/c/Users/benya/projects/quakeworld/komodobots-ml
$V scripts/build_training_dataset.py --demo-dir ~/ctv_decomp --out-dir ~/move_bc_shards --workers 16
# -> ~/move_bc_shards/<demo-stem>.ndjson (one per demo) + manifest.json
```
> Shards already exist (472). Skip unless rebuilding. Note: every shard row carries `onground=false`, `pm_code=0` — the `.qwd` `svc_playerinfo` recovery does not carry server ground/pmove flags, so `onground` is deliberately **not** a feature; `pmove_sim` re-derives true ground state from dm3 geometry in the gates (`build_dataset.py:25-30`).

### 3b — pack clean features + labels → `.npz` (the run-defining step)
`build_dataset.py` re-derives the exact per-frame clean mask (`pmove_sim` replay, `reanchor_every=77` + teleport reanchor, `err ≤ 4 qu`, maximal clean runs `≥ 24` frames — `build_dataset.py:68-70, 104-131`) and emits packed `X, Y, demo_id, tier_id, demos`.

```bash
V=~/komodobots-ml-venv/bin/python
cd /mnt/c/Users/benya/projects/quakeworld/komodobots-ml
P=experiments/stage2/move-bc-train ; D=experiments/stage2/move-bc-dataset

# 1) build an allowlist-filtered clean index (one demo filename per allowlist line)
$V - <<'PY'
import json, pathlib
base = pathlib.Path("experiments/stage2/move-bc-dataset")
idx  = json.loads((base/"clean-segment-index.json").read_text())
allow = {l.strip() for l in (base/"dm3_4on4_clean_allowlist.txt").read_text().splitlines() if l.strip()}
idx["demos"] = [d for d in idx["demos"] if d["demo"] in allow]
(base/"clean-segment-index.dm3_4on4.json").write_text(json.dumps(idx))
print("kept demos:", len(idx["demos"]))
PY

# 2) pack the clean dm3-4on4 dataset
$V $P/build_dataset.py \
    --shard-dir   ~/move_bc_shards \
    --clean-index $D/clean-segment-index.dm3_4on4.json \
    --demo-list   $D/selfpov_4on4_demolist.tsv \
    --bsp         /mnt/c/nQuake/qw/maps/dm3.bsp \
    --workers 16 \
    --out ~/move_bc_dataset_dm3_4on4.npz
# prints: wrote ...: X=(~5.8M,6) Y=(~5.8M,3) demos=~430 + fwd/side/jump label balance
```
> To exactly reproduce the prior pooled `.npz`, omit step (1) and use the default `--clean-index` with `--out ~/move_bc_dataset.npz`. **Default recommendation: do the clean-allowlist run** so the committed corpus definition and the trained checkpoint match. `build_dataset.py:201` defaults `--bsp /mnt/c/nQuake/qw/maps/dm3.bsp`; only demos in the clean index **and** with a shard are packed.

---

## 4. Training config

**Script:** `experiments/stage2/move-bc-train/train.py`. **CUDA is required and asserted** — `train.py:113-114`: `assert device == "cuda", "CUDA required for this run"`. Runs on the **4090, NOT the cloud box** (cloud box has no GPU).

- `MoveMLP(hidden=128)`, 18,440 params; three `CrossEntropyLoss` heads summed (`train.py:142-144, 163`).
- **Inverse-frequency class weights per head** (`train.py:67-71, 133-136`) — essential because jump is ~3.3% positive; without it the policy collapses to "never jump" and kills bhop. Prior weights: `jump=[0.52, 14.93]`.
- Adam, **lr 1e-3** (`--lr`, `train.py:104`); whole train set GPU-resident (~140 MB).
- Defaults (`train.py:102-108`): `--epochs 12 --batch 8192 --hidden 128 --val-frac 0.15 --seed 0 --tiers 0,1,2`. **Use `--epochs 15` for parity with the prior GO run.**
- Best-mean-val-accuracy checkpoint saved to `--out` (`train.py:179-187`); metrics JSON to `--metrics-out`.

```bash
V=~/komodobots-ml-venv/bin/python
cd /mnt/c/Users/benya/projects/quakeworld/komodobots-ml
P=experiments/stage2/move-bc-train
$V $P/train.py \
    --data        ~/move_bc_dataset_dm3_4on4.npz \
    --out         ~/move_bc_policy_dm3_4on4.pt \
    --metrics-out ~/move_bc_policy_dm3_4on4.train.json \
    --epochs 15 --batch 8192 --lr 1e-3 --hidden 128 --val-frac 0.15 --seed 0 --tiers 0,1,2
```

---

## 5. Compute & environment

- **Box:** the RTX 4090 workstation, WSL2 Ubuntu-24.04. **Not** the AWS cloud box (no GPU).
- **venv:** `~/komodobots-ml-venv`, **torch 2.6.0+cu124, numpy 2.4.4**; runtime device `NVIDIA GeForce RTX 4090`.
- **Invocation from Windows:** `wsl.exe -d Ubuntu-24.04 -e bash -lc '… ~/komodobots-ml-venv/bin/python …'`.
- **Runtime:** training is trivial — ~1.7 s/epoch GPU-resident, so **15 epochs ≈ 30–60 s** wall. Dataset packing (3b) is the long pole: 16 workers over ~430 shards through `pmove_sim` ≈ a few minutes. Closed-loop eval ≈ 73 s.

---

## 6. Success criteria & evaluation

Three layers, in order. Run them all; report each verdict.

### (a) Open-loop reproduction / retention gate — the KILL gate
`eval_openloop.py` replays each controller through `pmove_sim` on held-out demos (human view + msec), measuring per-frame clean retention (`err ≤ 4 qu`).
```bash
$V $P/eval_openloop.py --data ~/move_bc_dataset_dm3_4on4.npz \
    --ckpt ~/move_bc_policy_dm3_4on4.pt --shard-dir ~/move_bc_shards \
    --n-demos 20 --max-frames 30000 --out ~/move_bc_openloop_dm3_4on4.json
```
**Acceptance (`eval_openloop.py:309-312`):** `bc_beats_airlaw_prior = (BC mean clean-frame-frac ≥ air-law prior)`. PASS if true; **KILL per docs/12 if false.** Prior-run targets (expect parity): BC retention **0.180** vs air-law **0.074** (~2.4×); action reproduction fwd 0.67 / side 0.64 / jump 0.85. Best mean val acc ≈ **0.89** (fwd ~0.872, side ~0.864, jump ~0.94). Treat as reference bands; large deviation means the data or class weights changed.

### (b) Closed-loop MOVE gate — the real Stage-2 acceptance
`eval_closedloop.py` drives `pmove_sim` with the sim's own state fed back each tick (human view replayed), from random starts × held-out demos.
```bash
$V $P/eval_closedloop.py --data ~/move_bc_dataset_dm3_4on4.npz \
    --ckpt ~/move_bc_policy_dm3_4on4.pt --n-demos 20 --horizon 385 --starts-per-demo 8 \
    --anchors references/dm3_4on4_anchors.json --out ~/move_bc_closedloop_dm3_4on4_h385.json
$V $P/eval_closedloop.py --data ~/move_bc_dataset_dm3_4on4.npz \
    --ckpt ~/move_bc_policy_dm3_4on4.pt --n-demos 20 --horizon 77 --starts-per-demo 8 \
    --out ~/move_bc_closedloop_dm3_4on4_h77.json
```
**Anchor bands (verified):** `references/dm3_4on4_anchors.json` (schema v2, **promoted**, 8 players, n=84): avg horizontal speed **252.3–315.6 qu/s**, p95 **461.5–560.0 qu/s**.
**Acceptance (`eval_closedloop.py:201-204`):** `bc_ge_airlaw_sustained_speed` **and** `bc_ge_airlaw_route_retention`. In-band is the **stretch goal**, not the gate. Prior run: at **1 s**, BC avg **243 ≈ recorded 257** (in-band), route-err = air-law; BC ≥ air-law at every horizon. **Known substrate ceiling:** beyond ~1 s, neither BC, air-law, *nor the recorded human* hold the route in the worldmodel-only sim (opponent collision is omitted — 78.6% of dataset contamination). **Surface this as a finding; do not tune around it.**

### (c) In-lab behavioral check — the 4v4 ledger the dashboard renders
This is the "does it move like a dm3 player in a real teamed game" check, and the honest gap is here. Runner: `scripts/run_4v4_validation_lab.py`. It runs a lab-only KTX 4v4 dm3 match (`k_defmode 4on4`, `teamplay 2`, 8 Frogbots split 4v4), copies the KTX JSON sidecar, and rebuilds the `4v4-validation.json` ledger (schema `komodobots.4v4_validation.v1`) the dashboard renders — both the dock panel `FourVFourValidationPanel.tsx` and the full-page evidence view `FourVFourEvidence.tsx` (`/botlab/?evidence=1`).
```bash
python scripts/run_4v4_validation_lab.py \
    --host servexeri --map dm3 --timelimit 5 \
    --komodobot-slot 1 --controller-version move-bc-dm3-4on4 --team1 TeamA --team2 TeamB
# -> artifacts/4v4-validation-runs/<run_id>/ (demo.mvd, ktxstats.json, run-summary.md)
# -> lab/dashboard/public/data/4v4-validation.json (ledger; previous_valid_run_id chains the deltas)
```

**What "the policy learned dm3 movement" looks like:**
1. **Offline:** (a) PASS (BC ≥ air-law, KILL not tripped) **and** (b) BC ≥ air-law on speed and route at the 1 s cadence, BC ~in-band at 1 s.
2. **In-lab:** the tracked komodobot slot completes a valid 4v4 dm3 match (clean `damage.matrix`: enemy damage present, intra-team ≈ 0 — the R-T team check), survives/laps, is **not bottom-of-lobby on movement**; composite **z ≥ −1** vs the Frogbot baseline; RL/LG accuracy within ~1σ (movement must not corrupt stock aim).
3. **Believability:** `docs/16` G-MV checks — **G-MV1 (no face-and-run collapse) is the hard fail**: airborne `|wrap180(yaw − atan2(vy,vx))|` must be human-shaped, not ~0. Band-pass is necessary-not-sufficient.

> **HONEST GAP — the learned policy is not yet wired into the live slot.** `run_4v4_validation_lab.py` currently spawns the komodobot slot as a **plain Frogbot** (`addbot 20 <team>`) tagged "komodobot" by label only — it sets **no per-slot moveprobe cvar and loads no learned policy.** Driving the slot from the learned policy is **PR #190 "Drive 4v4 Komodobot slot from WSL" (open)**, and a live per-tick learned-policy bridge is an **unbuilt new capability** (`docs/12:135-136, 238-241`). Until #190 lands and a policy-feeding controller exists, layer (c) can only run as a **mode-10 `.cmds` replay** of the policy's rollout (open-loop) or a labeled-Frogbot smoke check. **State which variant you ran; do not report a Frogbot-in-disguise run as a learned-MOVE validation.**

---

## 7. Artifacts

WSL `~/` (gitignored, 4090-local):
- `~/move_bc_dataset_dm3_4on4.npz`, `~/move_bc_policy_dm3_4on4.pt`, and the `*.train.json` / `*.openloop.json` / `*.closedloop_h{77,385}.json` metrics.

Committed (small JSON/MD only — never `.npz`/`.pt`):
- Updated `experiments/stage2/move-bc-train/{results.json, train_metrics.json, openloop_metrics.json, closedloop_metrics.json}` for the clean run.
- **Regenerate `TRAINED_DEMOS.md` + `trained-demos.tsv`** via `build_trained_demos_manifest.py` — a standing requirement after every training run; it stamps dataset + checkpoint sha256.
- A short run note (experiment README or `docs/07_FINDINGS_LOG.md`): corpus = clean allowlist, demo/frame counts, the three verdicts, and which layer-(c) variant ran.

In-lab (this repo): `artifacts/4v4-validation-runs/<run_id>/` + the rebuilt `lab/dashboard/public/data/4v4-validation.json` + a screenshot of the rendered evidence view (`/botlab/?evidence=1`).

---

## 8. Risks / unknowns & fallbacks

1. **Live learned-policy seam not built (highest; blocks layer-c on the real policy).** Per-slot moveprobe is real (`control_bridge.py`), but `run_4v4_validation_lab.py` does not use it for the policy and no live per-tick learned-policy mode exists in `bot_movement.c`. **Fallback:** validate in-lab via **mode-10 `.cmds` replay** of the closed-loop rollout; treat the full live closed-loop check as gated on PR #190 + the live-bridge spike.
2. **Closed-loop route retention beyond ~1 s is substrate-limited** — opponent collision omitted from `pmove_sim`. The gate already accounts for this (acceptance is "≥ air-law," not "in-band long-horizon"). **Surface, don't tune.** Path forward: re-observe true state at ~1 s cadence live, and/or a DAgger/residual stabiliser.
3. **Anchor measurement-plane mismatch.** Bands are on the MVD event-rate finite-difference plane (~13 ms); the sim is sampled at the recorded ~13 ms tick — comparable, not identical. Report band membership with this caveat; never cross-plane pass/fail.
4. **Clean run ≈ pooled run.** 39 excluded contaminants ≈ 0.49% of frames → near-identical behavior to `~/move_bc_policy.pt`. If you only want a fresh stamped artifact, that's expected; the value is provenance alignment.
5. **Player attribution is a filename heuristic** — fine for this pooled run, a blocker for per-player tiering (out of scope).
6. **`onground`/`pm_code` are constant-zero in shards by design** (POV recovery limitation); handled (not a feature; sim re-derives ground state) — flagged so a reviewer doesn't mistake it for a bug.
7. **Believability despite band-passing** — `docs/16` texture gate guards this; G-MV1 (no face-and-run) is the hard fail. For a mode-10 replay bot texture is inherited from the human (passes trivially); it only becomes a real test for the learned policy under synthesized view (Stage-3).

**Net.** Offline layers (a)+(b) are runnable today on the 4090 and expected to PASS/GO at parity with the prior pooled run; in-lab layer (c) is runnable as a replay/smoke check now and as a true live learned-MOVE check only once PR #190 and the live-bridge spike land. Report exactly which was executed.
