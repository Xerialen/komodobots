# Stage 2 — Learned MOVE behavioural-cloning policy (MLMove-style discrete BC)

Implements references/12 Stage 2 ("Learned MOVE (residual upgrade)"). Trains a small
discrete-action behavioural-cloning policy on the clean elite self-POV dm3 4on4
corpus, then runs both Stage-2 gates: open-loop action reproduction / replay
divergence vs the analytic **air-law prior** (the KILL criterion), and the
**closed-loop MOVE gate** in `pmove_sim` with simulated-state feedback.

**Verdict: GO** — keep the learned MOVE as the Stage-2 residual upgrade. BC
strictly beats the air-law prior on open-loop retention *and* closed-loop
sustained speed, so the references/12 KILL condition (`BC < air-law prior`) is not
triggered. The closed-loop route-retention ceiling beyond ~1 s is a *substrate*
limit (the worldmodel-only sim, which the recorded human inputs also cannot beat),
not a policy failure — surfaced as a finding, not tuned around.

## Files (commit-candidate)
- `build_dataset.py` — reproduces the canonical per-frame clean mask from the
  shards and packs a velocity-relative feature + discrete-action `.npz`.
- `train.py` — `MoveMLP` (3 discrete heads), by-demo split, CUDA training.
- `eval_openloop.py` — gate (a): action reproduction + replay retention vs the
  mode-10 (recorded) baseline and the air-law prior.
- `eval_closedloop.py` — gate (b): closed-loop simulated-state-feedback rollout,
  sustained-speed vs the promoted anchor bands, with a horizon sweep.
- `results.json` — consolidated metrics + go/no-go (canonical).
- `train_metrics.json`, `openloop_metrics.json`, `closedloop_metrics.json`,
  `closedloop_h77.json`, `closedloop_h154.json` — raw run outputs.
- The model checkpoint (`~/move_bc_policy.pt`, 78 KB) and packed dataset
  (`~/move_bc_dataset.npz`, 35 MB) live in **WSL `~/`** (gitignored), NOT in git.

## Environment (authorized, verified)
- venv: `~/komodobots-ml-venv` in WSL2 Ubuntu-24.04 (scoped, not system-wide).
- torch `2.6.0+cu124`, numpy `2.4.4`.
- `torch.cuda.is_available() == True`; device `NVIDIA GeForce RTX 4090`
  (24 GB, driver 595.79, capability (8,9)); GPU matmul executed; training ran on
  `cuda`. (Heavy compute in WSL2 per hosting policy.)

## Reproduce (from repo root, in WSL)
```bash
V=~/komodobots-ml-venv/bin/python
P=experiments/stage2/move-bc-train
$V $P/build_dataset.py   --workers 16 --out ~/move_bc_dataset.npz
$V $P/train.py           --epochs 15  --out ~/move_bc_policy.pt
$V $P/eval_openloop.py   --n-demos 20 --max-frames 30000 --out ~/move_bc_openloop.json
$V $P/eval_closedloop.py --n-demos 20 --horizon 77 --starts-per-demo 8 --out ~/move_bc_closedloop_h77.json
```

## Data
- Training set = the clean MOVE frames from
  `experiments/stage2/move-bc-dataset/clean-segment-index.json`: **5,847,254
  clean frames** across **462 demos** (254 distinct players), quality tiers A/B/C.
- The per-frame clean mask is reproduced *exactly* (`build_dataset.py` re-runs
  `pmove_sim` with the same `reanchor_every=77` + teleport reanchor, `err<=4qu`,
  maximal clean runs `>= 24` frames) — the packed total matches
  `improved_clean_frames = 5847254` to the frame.
- **Shard-state caveat (real, not a bug):** every shard row carries
  `onground=false` and `pm_code=0` — the `.qwd` POV `svc_playerinfo` recovery
  does not carry server-side ground/pmove flags. So `onground` is *not* used as
  a feature (constant, uninformative); `pmove_sim` derives the true ground state
  from dm3 geometry each tick during the gates.

## Featurization (state-only, velocity-relative, map-agnostic)
6-dim, exactly the *state* side of `scripts/fit_air_law.py::frame_quantities`:
`hspeed/320`, `vz/320`, `lvm_sin`, `lvm_cos` (look-lead = signed angle between
view-yaw and velocity-heading, as sin/cos so it wraps safely), `moving` (|v_h|>=1
flag), `pitch/90`. The action-side wishdir-vs-velocity *rotation* is the label
space, never an input, so the policy can't cheat by reading its own action.

## Action space (MLMove-style discrete) and the MOVE/AIM view coupling
Three discrete heads predicting the human usercmd:
- `fwd` ∈ {back, none, forward} (3-way)
- `side` ∈ {left, none, right} (3-way)
- `jump` ∈ {0, 1} (`BUTTON_JUMP`)

**Justification.** QW air-accel gain (`900 - cs²`) is dominated by wishdir
*direction*, not the 320-vs-400 magnitude (both saturate `wishspeed`), so a
sign-quantised discrete vocabulary loses almost nothing — confirmed: replaying
the *recorded* actions sign-quantised vs exact gives 0.225 vs 0.229 retention.
`up`/`attack` are not part of the MOVE micro-action; aim/fire is AIM's job.

**View-yaw coupling — Option (a) (chosen, justified).** MOVE predicts
fwd/side/jump *conditioned on* the current view (the view enters the feature via
`lvm`), and both gates **replay the human view-yaw**. Learned view control
(a view-yaw-rate output) is **AIM, explicitly deferred to Stage 3** per references/12;
predicting it here would conflate the MOVE gate with un-validated aim synthesis.

## Architecture
`MoveMLP`: `6 → 128 → 128 → {3,3,2}` heads, ReLU. **18,440 params** — a few tiny
matmuls per tick, trivially inside the eventual ~0.5 ms/tick CPU budget (MLMove's
existence proof at scale). Stateless by design: the action is dominated by the
current velocity-relative state, and statelessness avoids hidden-state carry in
the closed-loop replay. A GRU variant is a documented follow-up if the closed-loop
gate later shows the MLP needs phase memory for serpentine cadence.

## Training
- **Split BY DEMO** (held-out demos) — never by frame; frames within a match are
  autocorrelated, so a frame split would leak. 393 train demos / 69 val demos;
  5.05 M train / 0.79 M val frames.
- Inverse-frequency class weights (jump is ~3.3% positive — without weighting the
  policy collapses to "never jump" and kills bhop).
- Adam, lr 1e-3, batch 8192, 15 epochs (whole train set resident on GPU; ~1.7 s/epoch).
- **Held-out val accuracy (best):** fwd **0.872**, side **0.864**, jump **0.94+**
  (mean **0.8916**). Loss/NLL curves in `train_metrics.json`.

## Gate (a) — open-loop (held-out demos)
Replace the recorded usercmd with each controller, replay through `pmove_sim`
(human view + msec), measure per-frame retention (`err<=4qu`, the canonical
`analyze_clean_yield` metric):

| controller | mean clean-frame-frac | median | frame-err p95 (qu) |
|---|---|---|---|
| recorded exact (mode-10 ceiling) | 0.229 | 0.188 | 129 |
| recorded sign-quantised | 0.225 | 0.188 | 129 |
| **BC policy** | **0.180** | **0.188** | 164 |
| air-law prior | 0.074 | 0.076 | 265 |

Action reproduction (held-out): fwd 0.67, side 0.64, jump 0.85.

**BC retention (0.180) ≥ air-law prior (0.074), ~2.4×; median matches recorded.
→ PASS (KILL criterion not triggered).**

## Gate (b) — closed-loop MOVE gate (REAL Stage-2 acceptance)
Policy drives `pmove_sim` with the **sim's own state fed back** each tick (no
re-anchor), human view replayed, from 8 random start states × 20 held-out demos.
Sustained horizontal speed (qu/s) vs the promoted anchor pool band
(avg 252–316, p95 462–560; MVD event-rate plane — see plane caveat in JSON):

| horizon | recorded avg | air-law avg | **BC avg** | BC p95 | BC route-err (qu) |
|---|---|---|---|---|---|
| 1.0 s (77 t) | 257 (in-band) | 205 | **243** | 313 | 184 (= air-law) |
| 2.0 s (154 t) | 245 | 152 | **218** | 322 | 406 |
| 5.0 s (385 t) | 221 | 106 | **149** | 302 | 672 |

- **BC sustained speed ≥ air-law (hand-mover proxy) at every horizon** — the
  Stage-2 "M-bands ≥ hand-mover" criterion.
- At **1 s** BC avg **243 ≈ recorded 257** (recorded is in-band) and BC
  route-err matches air-law — strong at the realistic live-bridge re-observation
  cadence.
- Neither BC, air-law, *nor the recorded human inputs* land in-band beyond ~1 s,
  and all drift: the offline worldmodel-only sim (no submodels/lifts/player
  collision) cannot hold a human route over multi-second closed-loop. This is a
  **substrate ceiling** (references/12: surface, don't tune around it), not a policy
  failure.

## Go / No-Go
**GO** — keep learned MOVE as the Stage-2 residual upgrade. BC strictly beats the
air-law prior on open-loop retention and closed-loop sustained speed, so references/12's
KILL (`BC < air-law prior → keep hand-mover`) does **not** fire.

**Caveats carried forward:** (1) closed-loop route retention beyond ~1 s is
substrate-limited — the live bridge should re-observe true state at ~1 s cadence,
and/or add the references/12 DAgger / residual stabiliser before relying on long open
horizons; (2) anchor speed bands are on the MVD event-rate plane while the sim is
sampled at the recorded ~13 ms tick — comparable but not an identical estimator,
so band membership is reported with that caveat; (3) learned AIM (view control)
remains deferred to Stage 3 — these gates replay the human view.
