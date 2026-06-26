# 28 — Megalodon Milton: the MLOps bot program (program of record)

**Status:** program of record (owner re-plan, 2026-06-26). **Supersedes `docs/18_BENCH_ITERATED_BOT_PROGRAM.md`**
(the human-like bench-iterated program) and the `docs/09_ROADMAP.md` stage ladder, both kept as history.
Source: the owner's four phase documents + one testing blueprint (see "Source documents" below).

## The goal (north star)

We are **no longer** building a *believable / human-like* bot. The goal is the **strongest QuakeWorld bot
possible** — it may **move, aim and play better than the best humans** ("plays perfectly"). The codename is
**Megalodon Milton** (the apex-predator version of the elite player Milton — surpass him, don't imitate him).

There is exactly **one binding constraint: information honesty.** The bot may act only on what it can
**see or hear itself, or read in the teamsay chat** — never on privileged/omniscient engine state. Skill is
unbounded; information is not.

## Method

**Reinforcement learning on rewards**, not input-mimicking / behaviour-cloning. We reward what we want
(velocity, progress) and penalise what we don't (collisions, wasted time), and let the agent *discover*
elite mechanics (strafe jumping, bunnyhop) itself. The 534M-tick human corpus and the QWD POV ground truth
become **targets to beat and references to score against**, not transitions to clone.

## Architecture & training order (modular, bottom-up, freeze-as-you-go)

Replacing the Frogbot with one monolithic network would cause **catastrophic forgetting** — learning to aim
would overwrite the weights that walk. So Megalodon Milton is a **modular hierarchy of ≥3 specialised
brains**, trained **strictly bottom-up, freezing each before the next**:

1. **Movement Controller ("Motor Cortex") — Brain 1.** Master bhop / strafe-jump / node-to-node movement on
   the Route Canon until it *mimics or surpasses* elite human speed. **This entire program (Phases 1–4 below)
   is Brain 1's lifecycle.** Its weights are then **frozen** — the Phase-3 quantize→ONNX artifact *is* the
   frozen, reliable movement tool the higher brains call. **Within Brain 1, base highways and each trick jump
   are separate, individually-frozen policies** (the *trickjump-separation* rule) so learning a trick can
   never overwrite base-route bhop.
2. **Aiming & Combat Controller — Brain 2.** Trained *with movement frozen*: weapon select, crosshair
   tracking, fire. Then frozen.
3. **Strategy & Teamplay Controller ("Commander") — Brain 3.** Macro game state → decides *where to go / who
   to attack*, issuing commands to the frozen movement + aim brains. It does not know how to jump or shoot.

### Near-term = hybrid; higher brains are built *on demand*

Today the **Frogbot is the temporary Commander + aim placeholder** and the ML Motor Cortex owns only
movement. The **handoff toggle** (Phase 1, T3.1 / #422): the Frogbot picks a destination, checks whether the
route is a trained "Highway", and if so **yields movement** to the Motor Cortex.

**We keep the Frogbot doing aim + where-to-go for as long as it is good enough.** The moment it can't do its
part we build that brain ourselves — and there are **two triggers, either of which forces it**:

- **(a) Performance** — the Frogbot's aim/decisions cap "plays perfectly" (they are not elite).
- **(b) Information-honesty** — the Frogbot's navigation is **omniscient** (it queries full map state for
  free), which an honest agent may not do; so an honest Commander brain may be *required regardless of skill*.

When triggered, we build **Combat first, then Commander, each only after the brain below is frozen** —
strictly bottom-up. Brains 2 and 3 are therefore **contingent, triggered future epics**, but the order
(movement frozen → combat → command) is fixed. This is both the catastrophic-forgetting fix and the reason
we don't rebuild the whole simulation at once.

## Validation (route-first; the 4v4 bench is demoted)

The dm3 **4on4 believability bench is removed from the early-stage training/eval loop** — it is a slow,
noisy signal this early. Instead:

- **Route-isolated scoring.** Isolate the bot on a single Route Canon **"Highway"** and grade its trajectory
  **objectively and instantly by MSE / RMSE against the elite-human ground truth** (Phase 2, T5.2 / #428).
- **4v4 returns only in Phase 4** as a *live monitoring / drift-detection* signal (not a training gate).
- **Every attempt is recorded and viewable.** Even though MSE is the objective gate, **every run records an
  MVD published to komodolab** (Phase 1, T3.3 / #424), so the owner can watch it — *especially any run we
  claim is succeeding*. **No success claim without a linked, viewable recording.**

## The four phases

GitHub milestones **Phase 1–4** (#4–#7); workstream label **`mlops-pivot`**; epics #414–#417; tickets
#418–#434. Each phase has a distinct live test (from the testing Blueprint).

### Phase 1 — ML Movement Controller (Data & Architecture) · milestone #4 · epic #414
Foundational: pristine normalised ground-truth data (no training/serving skew) + prove an ML model can drive
the Frogbot movement without crashing.
- **M1 Data Pipeline & Feature Store (P1.1):** T1.1 Feature-Registry→JSON + generate-first auditor (#418);
  T1.2 Unify MVD/QWD ETLs into one shared catalog writer (#419).
- **M2 Route Canon & Ground-Truth Signatures (P1.2):** T2.1 Define "Highway" nodes / Route Canon DB (#420);
  T2.2 Automate the POV-fusion pipeline (#421).
- **M3 Initial Prototype / PoC (P1.3):** T3.1 Commander/Motor-Cortex handoff toggle (#422); T3.2 Baseline PPO
  reward & scoring — the "plumbing test" (#423); T3.3 Attempt recording & komodolab gallery (#424).
- **Live test:** visual integrity / "plumbing" — `pov_fuse` contact sheet + pixel checks (eval-integrity) +
  by-eye sanity. Not testing whether the bot is *good* yet.

### Phase 2 — Velocity Optimisation (RL) · milestone #5 · epic #415
Heavy PPO RL to learn elite mechanics and surpass human speed; reward shaping + automated tuning.
- **M4 Training Loop & Offline Store (P2.1):** T4.1 Materialize denormalized Parquet offline feature store
  (#425); T4.2 Establish experiment tracking — MLflow/W&B (#426).
- **M5 Reward Shaping & Automated Tuning (P2.2):** T5.1 Phase-2 PPO reward signals — Velocity+ / Progress+ /
  Collision− / Time− (#427); T5.2 Automated evaluation metrics — route-isolated MSE/RMSE, **no 4v4** (#428);
  T5.3 Systematic hyperparameter tuning — Bayesian/Random search (#429).
- **Live test:** automated mathematical scoring with the bot isolated on a single Highway, graded by
  MSE/RMSE. **4v4 removed from the training eval loop.**

### Phase 3 — Low-Latency Optimisation · milestone #6 · epic #416
Freeze + optimise Brain 1 for the high server tick rate.
- **M6 Low-Latency Inference (P3.1):** T6.1 Compress / quantize the trained model — fp32→int8 (#430); T6.2
  Export to ONNX (+ KV caching if a Transformer) (#431).
- **Live test:** isolated inference latency benchmark — **<100 ms** end-to-end (online feature store + model
  → engine).

### Phase 4 — Deployment & MLOps · milestone #7 · epic #417
Production lifecycle: deploy, monitor, detect drift, continuously retrain.
- **M7 Production & Continuous Training (P4.1):** T7.1 CI/CD deployment pipeline (#432); T7.2 Live monitoring
  dashboard (#433); T7.3 Continuous-training (CT) loop (#434).
- **Live test:** **live 4v4 matches** in production + drift detection (win rate, pathing deviation, latency).
  This is where macro-level strategy + overall believability are finally validated.
- **After this, bottom-up:** if/when the Frogbot can't do its aim or where-to-go part (performance OR
  honesty), the **Combat** then **Commander** brains get built (contingent future epics; see "Architecture").

## Source documents

The authoritative source is the owner's re-plan (in Drive), transcribed here:
- `P1 - Architecting the QuakeWorld Machine Learning Movement Controller.docx`
- `P2 - Velocity Optimisation: Reinforcement Learning and Feature Store Architecture.docx`
- `P3 - Forging the Silicon Reflex: Low-Latency Model Optimisation.docx`
- `P4 - Evolution of the Machine: QuakeWorld Bot Deployment and MLOps.docx`
- `P1,2,3,4 - Blueprint for MLOps Bot Validation.docx` (the per-phase testing strategy)

## How this supersedes the prior program

`docs/18` (human-like, 4v4-judged) and the `docs/09` stage ladder remain as **history**. The goal changed
from *believable* to *information-honest superhuman*, the method from BC to RL, and the early validation from
the 4v4 bench to route-isolated MSE. The **data line is unchanged and still valid**: `docs/25_DATA_CONTRACT.md`
and `docs/27_DEMO_EXTRACTION_SPEC.md` define the corpus the RL method consumes — they are consumed, not
discarded. This document is the live index; the GitHub milestones/epics/tickets are the executable form.
