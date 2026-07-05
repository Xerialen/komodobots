# DM3 4on4 Stand-In Bot — program design (Megalodon Milton)

Status: program design. Created 2026-06-14. Supersedes the external-sources research note
(`docs/11`, on branch `claude/research-humanoid-mlmove-9glc6p`), whose literature folds in as
§9 here.

This doc defines the program to build a **live 4on4 DM3 "stand-in" bot** via machine learning,
consolidating the lab's breakthroughs, the QuakeWorld-ecosystem sources, the learned-brain
architecture, the staged roadmap, and the goal-true competence gates.

> **Provenance / honesty note.** This design was adversarially scrutinised by a 15-agent review
> (5 critique lenses → independent verification → synthesis). Verdict: **revise, not replace** —
> the architecture is sound; the fixes were about *sequencing and honesty*. Three verification
> corrections are baked in below: (1) the feared "no elite DM3 POV corpus" is **false** — 99 4v4
> dm3 demos exist on disk (the real issue is a self-POV-vs-spectator filter + `.qwz` decompression);
> (2) a carry-corrected per-player rating **already exists** (`fantasyquake/scripts/rate_individual.py`);
> (3) a monolithic-sim alternative's "already built" premise was unverifiable on disk. See
> `docs/08_DECISION_LOG.md` for the decision record.

---

## 1. North-star placement (Decision Point Alpha)

Per `docs/00`, komodobots exists to investigate **believable QuakeWorld bots as stand-ins for real
players**, along the chain **Bunnyjumping → Movement Realism → Player Realism → Simulation
Realism**, with a **Decision Point Alpha** choosing FantasyQuake vs Megalodon Milton — *on lab
evidence, not assumptions*.

The lab has produced that evidence on the Movement-Realism rung — **two real-map breakthroughs,
both about preserving/measuring the human signal, not raw speed**:

- **ztricks (mode 25)** — the *teaching principle*: bunnyjumping is **synchronized movement**
  (preserve human mouse/jump/side timing; add speed only via phase-gated strength), plus the
  **QWD segmentation/interpolation method** that turns a POV `.qwd` into a controller-ready trace
  (`experiments/ktx_moveprobe/evidence/bunnyjump-code-replication-20260613.md`,
  `…/qwd-segmentation-interpolation-procedure-20260613.md`).
- **dm3 (SNG→RL observability)** — the *honest scoreboard*: a goal-true, contamination-resistant
  instrument that caught its own stray-teleport contamination and produced a grounded physics
  verdict (`experiments/dm3_sng_to_rl_observability/README.md`).

On this evidence the project **makes Decision Point Alpha toward Megalodon Milton first**: learn /
recreate the behaviour of the strongest players, prove it on DM3, then add a skill-down knob.

---

## 2. Goal (locked)

> A **live 4on4 DM3 stand-in** bot you can drop into a mix when short — **1 → 1-per-team →
> 4-as-a-unit** — that **moves, aims, and understands DM3 objectives/economy**, built via **ML**,
> **Megalodon-Milton-first** (max skill), proven **all the way on DM3**, with a **skill-down knob
> later**.

**Honest scope.** A **learned _individual_ brain (move + aim + economy) running under a _heuristic_
team protocol.** **Learned team coordination is explicit out-of-scope research** — no QW data source
pairs synchronized all-four-players intent (single-POV `.qwd` = one player's usercmds; MVD = all
positions, no intent/usercmds), so team play can only be *scored* on MVD outcomes, never *trained*
from coordination labels with today's data. In real DM3 4on4, coordination/timing **is** the skill,
so the team layer encodes the doctrine a mix calls aloud — **armor-side ownership, mega-anchor vs
quad-runner, RL-control rotation** — and the bot is gated on **obeying** those calls.

**Acceptance = goal-true competence metrics** (objective per-skill gates; no human panel) — but
**band-passing is necessary-not-sufficient**: a believability/texture gate (§6) guards against
"passes every band, still reads as a bot." Discipline carried from the dm3 instrument: measure the
real objective, never a proxy that masks failure; **if a target is unreachable under the substrate,
surface it as a finding — don't tune around it.**

### Clone-selection axis (corrected)
"Clone the best players" is re-scoped to **"clone players with the strongest per-skill DM3
signatures."** Selection uses **`fantasyquake/scripts/rate_individual.py`** (carry-corrected
per-player DDR/EWep/frag signal) and/or 1on1 DeepFrag tier — **not** the team-W/L OpenSkill rating
(`fantasyquake/scripts/rate_4on4.py`), which can rank a carried passenger as "best."

---

## 3. Sources (verified on disk under `…/quakeworld/`)

| Source | Path | Role |
|---|---|---|
| komodobots lab | `…/komodobots` | the seam, sim, instruments, integration |
| KTX | `…/engine/ktx` | host substrate; seam `src/bot_movement.c::BotSetCommand → trap_SetBotCMD`; 32-bot, hosts live without humans; `bot_aim.c`/`bot_botthink.c`/`bot_botweap.c` |
| ezquake-source | `…/engine/ezquake-source` | usercmd/demo ground truth (`src/cl_demo.c::CL_WriteDemoCmd`) |
| mvd_analyzer | `…/tools/mvd_analyzer` | Go, Schema v32, REST+MCP — macro/economy signal: `damage` (per-hit, given/taken, EWep buckets, matrix), `items`, `timelineAnalysis.regionControl`, `locGraph`, `frags`, `streams`; **no usercmd labels** |
| deepfrag | `…/tools/deepfrag` | 1on1 OpenSkill (`rate.py`; DDR / perf-delta formulas) |
| fantasyquake | `…/fantasyquake/scripts/` | `rate_4on4.py` (team W/L) **and `rate_individual.py` (per-player — the clone-selection axis)** |
| demoparser / demopasha | `…/engine/demoparser`, `…/tools/demopasha` | data quality; `--dump-moments`; byte-perfect MVD+BSP (GPU-validated, 4090) |
| External literature | §9 | MLMove (transformer team-move BC), Pearce (BC + inverse-dynamics), Humanoid (comparator) |

All quoted thresholds here (human bands ~283–314 avg / ~506–535 p95 qu/s; 526 qu/s edge) are
**PROVISIONAL** pending the §7 Stage-0 anchor build; `scripts/verify_route.py` today anchors to a
*single* human `.cmds` replay. Pin the exact MVD field names from
`…/tools/mvd_analyzer/mvd-analytics/RESULT_SCHEMA.md` before implementing any gate.

---

## 4. Proven / prior / open / vacuum

- **Proven:** the synchronization principle; the QWD→trace method; exact-usercmd extraction
  (`tools/qwd_usercmd`); time-alignment (hardened by #128); a runnable (state,action) BC dataset
  builder (`scripts/build_training_dataset.py`); validated offline physics (`scripts/pmove_sim.py`
  on dm3 BSP via `scripts/bsp_geom.py`); analytic air-law prior (`scripts/fit_air_law.py`); the dm3
  goal-true instrument (`experiments/dm3_sng_to_rl_observability/scripts/*`).
- **Prior, not match data (re-labeled — was overclaimed "proven"):** the "29 demos / 22,749 paired
  frames" corpus (`docs/06`) is the **single-author ztricks _trick-drill_ set** — a **movement
  _prior_ for pretraining, NOT the match-behaviour corpus.** "Clone the best via BC" is **Open**
  until the self-POV *match* yield is measured (§7 spike 3).
- **Open:** strict sustained-speed; **dm3 air-transition retention** (bot through-air p50 ~122 vs
  human ~433 qu/s); whether a *believable approach* reaches the launch-edge speed at *that*
  geometry; closed-loop BC drift; the live learned-policy bridge cost.
- **Vacuum:** neural training (no torch today), the decision layer, aim synthesis, live game-state
  input to the bot, multi-bot coordination, live replanning, 4on4 objective/economy scoring.

---

## 5. Architecture — learned individual brain, 3-tier hierarchy

Data-forced split (no frame in any demo carries joint move+aim+macro labels):

```
DECIDE-economy (macro)  ~2–5 Hz   ← MVD (all-player, unlabeled)   [outcome-derived intent labels]
        │ → world-space target_point + symbolic intent {get_item, engage, disengage, hold, regroup}
        ▼   ACTUATOR-AGNOSTIC contract (never leg-level commands → MOVE can be swapped underneath)
AIM head + MOVE micro   ~72–77 Hz ← POV .qwd (labeled)            [MLMove-style discrete BC]
        ▼   trap_SetBotCMD(fwd, side, up, buttons, impulse)
TEAM = heuristic blackboard (NOT learned): armor-side ownership, mega-anchor/quad-runner, RL rotation
```

- **BC-first** (matches "be a believable human," not an RL optimiser). RL is adopted **narrowly**
  as a Stage-0 *oracle* (§7), not a global strategy.
- **Live bridge (corrected).** The mode-10 precedent is **over-credited**: mode-10 merely indexes a
  preloaded `.cmds` array (no inference); mode-19's air-law is an **offline-fit table compiled into
  C, not live-loaded**; the patch warns against the per-tick `cvar()` hot-path pattern. A learned
  policy reacting to live bot state is structurally **mode-12** (closed-loop). So **"live-load +
  per-tick-evaluate a learned policy at 8 slots" is a NEW capability** — benchmarked in §7 spike 2
  (prefer a quantized lookup table indexed by discretized state; drop the mode-10 claim if it is
  live matmul). The 4090 is **offline-only** (training + batch `pmove_sim` rollout); all training in
  WSL2 per the machine hosting policy.

### Data construction
- **MOVE** (labeled): `tools/qwd_usercmd → scripts/build_training_dataset.py`; every action stream
  re-validated in `pmove_sim`. Corpus = **self-POV** demos of strong per-skill players (after the
  §7 provenance filter). The ztricks set is a **pretraining prior**, not match data.
- **AIM** → **"target-relative angle-trajectory imitation."** `.qwd` stores *absolute post-mouse*
  view angles (no mouse deltas), so split two sub-problems: (a) **aim-tracking dynamics** —
  learnable from the absolute angle stream, no target needed; (b) **target-selection / lead** —
  POV×MVD fusion **scoped to fire/pre-fire frames only**, under a stated target-error budget, gated
  on verified self-POV + a near-coincident MVD opponent sample. **Hand-aim on a learned target is
  the EXPECTED interim outcome** until fusion error is measured below threshold. Acceptance =
  **outcome distributions** (LG% / RL direct-hit in the human band via `damage`), not angle fidelity.
- **DECIDE** → **"heuristic outcome-derived intent labels"** (not literal Pearce inverse-dynamics).
  `target_point` = the loc reached next; `intent` by rules over `items`/`damage`/distance events.
  Validate the rules predict the *next macro transition* above a baseline on held-out MVD, and
  **add an abandoned-intent negative class** (went-for-RA-got-contested-peeled-off) so the bot
  decides soundly *when losing the item race*. Train on **actuator-agnostic** targets so swapping
  learned MOVE in later does not force DECIDE retraining.
- **MVD→MOVE inverse-control pseudo-labels:** **speculative, gated** on the self-POV corpus + the
  526 findings (it is circular on the same uncertain physics, and `pmove_sim` does not collide
  submodels/players — exactly dm3's lift/contest geometry). Validate first as a **known-answer test
  on the ztricks demos** (recovered usercmds must match recorded within tolerance); accept only on
  submodel-free / opponent-free trajectory segments.

---

## 6. Goal-true competence gates

Per gate: **signal source → threshold tied to a reference → contamination guard.** Every E/P/T gate
**fail-closes** (required `mvd_analyzer` section present + non-empty, else **reject the run** like
G-ALIGN) so a missing signal cannot silently pass a partial. Pin exact field names from
`RESULT_SCHEMA.md` before implementing.

- **M — Movement / route.** G-M1 route completion (extend `verify_route.py` to the core dm3 routes);
  G-M2 hard-gap launch speed (≥ census required, `None`-fails); G-M3 sustained-speed signature (air
  vs non-air reported separately). **M3 / P-bands scored on the SAME plane the anchor is derived on**
  — reconstruct human 100 Hz trace-equivalents via `pmove_sim`, or score the bot on the MVD plane —
  no cross-plane pass/fail. Until the pool is large, require the bot inside the **empirical
  per-player min/max** and mark M3/P diagnostic-only.
- **E — Economy.** Base on **ground-truth KTX item signals** (`items` took/respawn timeline,
  `backpacks` xferRL/xferLG); **`timelineAnalysis.regionControl` demoted to diagnostic-only
  cross-check** (derived proxy, hard-zero in 4on4). G-E1 item-control share (RA/YA/mega/quad/RL);
  G-E2 respawn-timing (bot must be *approaching* the loc before respawn — `streams`/`locGraph`);
  G-E3 quad control (a quad pickup with no in-window `damage` counts against).
- **A — Aim / combat.** G-A1 **DDR** = `damage` given/taken (DeepFrag's own formula); G-A2 frag
  efficiency from `match.players[]` **v19-corrected `kills`/`deaths`/`suicides`** (suicides capped —
  no fall-feeding); G-A3 weapon-appropriate engagement (`damage` EWep buckets, gated on the bot
  actually holding the weapon via `weaponPickups`/inventory). **G-A4 replaced** — drop
  "duel vs DeepFrag-expected" (team rating is carry-confounded) → **per-engagement DDR/EWep
  distribution-matching vs the elite 4on4 reference players.**
- **P — Positioning.** G-P1 presence vs human inter-player spread (PVS-aware `locGraph`;
  **diagnostic-only** until the reference pool widens); G-P2 map-state posture (armed → contest
  regions, unarmed → routes to weapons).
- **T — Team (outcome-only, MVD-scored).** G-T1 anti-stacking economy; G-T2 spatial spread; G-T3
  coordinated trades (`frags` clustering + `damage` matrix, identity from **bot-side per-slot
  moveprobe logs**, not MVD name canon); plus a **team-discipline gate** — does the bot *obey* the
  blackboard calls?
- **Believability / texture gate (on the labeled POV plane ~72–77 Hz).** Angle-velocity +
  settle-time distributions at fire frames vs the elite reference; DECIDE target-switch-rate
  intent-coherence. **Band-passing is necessary-not-sufficient.** If a human panel is truly off the
  table, reserve a small periodic human spot-check as a calibration backstop for these objective
  texture metrics.
- **G-ALIGN meta-gate.** Trace-plane (per-bot 100 Hz `build_trace.py`) and match-plane
  (`mvd_analyzer`) must agree at sampled wall-clock anchors (`streams.global`); else reject (never
  averaged).
- **Closed-loop MOVE gate (distinct from open-loop).** Run the trained policy in `pmove_sim` with
  **simulated-state feedback** (not human state) and require route retention over a budgeted horizon
  before any live run; consider DAgger / a residual stabiliser.

**Skill-down knob** (deferred, designed-in): every gate is "distance to a reference distribution," so
skill-down = "aim at a lower individual-rating tier / wider band" — a single strength/precision
scalar per tier, auditable and monotone.

---

## 7. Roadmap (cheapest-disconfirming-first; kill-criteria + effort bands)

The **fastest credible stand-in is NOT the learned mover** — it is the Stage-1 hand-mover + stock
Frogbot combat + blackboard that survives, obeys, takes its armor, and shoots. Learned tiers are
*quality upgrades* layered on that. A real mix values, in order: **survive/obey > economy > aim >
elite movement.** (Effort bands S/M/L are rough relative sizes, not calendar estimates.)

| Stage | Build | Gate / Verify (acceptance) | Kill / fallback | Effort |
|---|---|---|---|---|
| **0 — Spikes (no torch yet)** | 4 cheap, high-info probes (below) | each spike has its own go/no-go | — | M |
| **1 — First live droppable bot** | **mode-20 hand-mover + scripted route + stock Frogbot aim/combat + heuristic blackboard**, live 4on4 dm3 | full M/E/A/P/T + G-ALIGN; **early team-discipline gate**: doesn't feed, obeys blackboard, takes its armor | if live bridge / gate harness fail → fix before any learned tier | M |
| **2 — Learned MOVE (residual upgrade)** | learned micro-controller replaces hand-mover; stock combat stays | closed-loop MOVE gate in `pmove_sim` → live; M-bands ≥ hand-mover, air-transition closer to human | if BC < air-law prior or fails closed-loop → keep hand-mover; MOVE stays research | L |
| **3 — Learned AIM head** | target-relative angle-trajectory imitation; stock combat = fallback | offline angle reproduction; live G-A1/G-A2 in band | **hand-aim-on-learned-target is the expected interim**; if fusion target-error > budget → stay on stock/hand aim | L |
| **4 — Learned DECIDE-economy** | outcome-intent BC on MVD → actuator-agnostic target+intent at 2–5 Hz, replacing the scripted route | **composite S1 checkpoint** (move ∧ aim ∧ economy together) over ≥3 clean runs | if intent rules don't beat baseline next-transition prediction → keep blackboard-only macro | L |
| **5 — Multi-bot** | per-slot replication (patch already per-slot) + blackboard | **S2** (1-per-team: per-slot attribution valid) → **S3** (4-as-unit: G-T1/2/3 + team-tier E/A) | learned team layer stays out-of-scope; blackboard only | L |
| **(later) Skill-down** | parametric relaxation vs the same gates | hits a named lower individual-rating tier on demand | — | M |

### Stage-0 spikes (highest-leverage; all cheap, all before torch)
1. **526-reachability as _geometry_, not "KTX accel ceiling."** KTX already sustains ~810 / peak
   1452 qu/s on trick.bsp (mode-20) — 2–3× above 526. Re-frame: *can a believable approach reach the
   required speed at THIS dm3 launch-edge given run-up distance + through-air retention?* Probe in
   `pmove_sim` / a mode-20-style hand controller on the actual dm3 edge geometry. **Adopt RL-in-sim
   narrowly here as the speed-ceiling ORACLE** (PPO against `verify_route`/`route_metrics` rewards):
   an exhaustive-RL shortfall is the cleanest proof of a physics ceiling, with no data confound. If a
   hand controller hits it, the Stage-1+ movement blocker retires for free; if not, the hardest
   finding lands in week 1.
2. **Live-bridge benchmark.** Prove a new moveprobe mode can **live-load a quantized policy table and
   evaluate it per-tick, closed-loop, at 8 slots within the ~0.5 ms budget** on the target host,
   without the mode-11/12 corridor collapse. Pick the representation here; drop the mode-10 claim if
   it is live inference.
3. **Data census + self-POV provenance filter.** Decompress `.qwz`; classify **self-POV vs
   spectator/autotrack** (nonzero fwd/side fraction, view-angle continuity, demo client slot vs
   tracked entity) — only self-POV feeds MOVE/AIM BC. Size the corpus (frames AND distinct players
   AND distinct situations) and set an **infeasibility floor**: *if < N self-POV 4on4 demos survive
   → learned MOVE/AIM-of-elites is abandoned; fall back to hand controllers + stock combat.*
4. **Anchor build.** `references/dm3_4on4_anchors.json` from **≥ N elite players with per-player
   spread reported**, **re-derived on the same plane the bot is scored on.** Hard exit gate; until it
   exists, all bands are provisional.

### Alternatives considered (folded in; full record in `docs/08`)
- **Reuse-Frogbot → adopt as sequencing/fallback, not terminal:** Stages 1–3 use stock Frogbot
  aim+combat (the seam already leaves `self->fb.firing` sourced from Frogbot); learned AIM defers to
  the same `desired_angle` write-point. A bridge, not a destination (Frogbot aim has a
  Div-1-recognisable signature the believability gate must eventually catch).
- **RL-in-sim → adopt narrowly** as the Stage-0 526 oracle only; reward-hacking against the no-panel
  gates is the risk the believability gate guards.
- **DECIDE-first → adopt the front-loading + actuator-agnostic contract**, so the macro brain trains
  on abundant MVD early and isn't paid for twice when MOVE is swapped.
- **Monolith-in-a-sim → rejected** (its "already built in qw-sim" premise is absent on disk; stacks
  two sim→live transfer gaps; its one good idea — offline 526 answer — is covered by spike 1).

---

## 8. Risks (ranked)
1. **Self-POV match-corpus yield** for learned MOVE/AIM-of-elites — gated by spike 3 with an explicit
   infeasibility floor + hand-controller fallback.
2. **526 at the believable dm3 edge** — re-framed as geometry + retention, answered in spike 1.
3. **Live learned-policy bridge cost** — unproven capability; spike 2 benchmarks it.
4. **Closed-loop BC drift** — the new closed-loop MOVE gate.
5. **Believability despite band-passing** — the new texture gate; band-pass is necessary-not-sufficient.
6. **Measurement plane / anchor thinness** — same-plane scoring + per-player-spread anchor +
   fail-closed gates.
7. **Learned team play has no data path** — explicitly out-of-scope; blackboard + obey-gate instead.

---

## 9. Method & validation sources (folded from `docs/11`)

Deep-research pass on sources Benjamin supplied plus one-hop references, framed against this program.
The three primary pages (`quakeworld.nu/forum/topic/7524`, `arxiv.org/abs/2408.13934`,
`davidbdurst.com/mlmove/`) return HTTP 403 to automated fetch; claims below were corroborated from
the GitHub repos, secondary writeups, and archives. Facts not readable from a primary source are
flagged **unverified**.

### 9a. MLMove — Durst, Xie et al., *Learning to Move Like Professional CS Players* (2024)
SIGGRAPH SCA 2024; CGF DOI 10.1111/cgf.15173; arXiv 2408.13934; MIT code `github.com/David-Durst/csknow`.
A compute-efficient **transformer** behavioural-cloning of CS:GO **team movement**: per-player
embedding → encoder over all players → next movement command as a **discrete distribution over
(direction, speed, jump/crouch)**. Trained on **123 h of pro play**; generates both teams in ~0.5 ms
amortised on one CPU core. Validated by a within-subjects **human-likeness study** (rated 16–59% more
human-like by TrueSkill than scripted RuleMove / stock GameBot) plus distribution-matching. It does
**not** aim/shoot, and CS has **no air-accel / bhop** — so MLMove proves human-like *macro
positioning*, not movement *micro-physics*. **Reuse for us:** the discrete-action BC shape (→ MOVE),
the tiny-CPU-at-inference existence proof (→ live bridge), and especially the **human-likeness +
distribution-matching evaluation** philosophy (→ the believability/texture gate and "distribution,
not single number").

### 9b. Pearce & Zhu — *CS Deathmatch with Large-Scale Behavioural Cloning* (2021)
IEEE CoG 2022; arXiv 2104.04258; code `github.com/TeaPearce/Counter-Strike_Behavioural_Cloning`; HF
dataset. CNN+LSTM from pixels; ~4M frames; key idea = **recover ground-truth actions from logged
metadata** (inverse-dynamics) when raw inputs are unlabelled. **Reuse for us:** the
inverse-dynamics-from-metadata idea is the principled bridge for MVD-only data (DECIDE intent
recovery, and the speculative MVD→MOVE pseudo-label lever) — though we have the easier privilege of
exact usercmds in POV `.qwd`, so we do **not** imitate the pixel/vision stack.

### 9c. Humanoid (QuakeWorld bot, `lemonjuiced`)
Forum thread #7524; distributed as a downloadable client-side mod. **Working conclusion: a
hand-crafted / scripted bot, not a learned controller** (QuakeBotArchive / QWiki frame it as a
classic bot). **Unverified** against the thread text (fetch-blocked). **Reuse for us:** value is as a
*realism comparator* (a long-standing bot reputed to feel difficult), not an architecture.

### 9d. One-hop references
**CSKnow** (`David-Durst/csknow`, MIT) — the reusable pipeline shape parser→CSV→model→vis, structurally
like our `qwd_usercmd`→JSON→scripts→lab. **demoinfocs-golang** — CS demo parser (analogue to our
MVD/QWD parsers). **DeepMind Quake III RL** (arXiv 1807.01281) — the RL-at-scale counterpoint we
deliberately avoid on cost grounds. **Quake-1 movement-physics RL** (HN item 23052152) — on-topic
QW-movement-RL lead, **not yet read**; relevant to the §7 spike-1 RL-in-sim oracle.

### 9e. Net reuse mapping
Transfers well: **imitation over RL** (cost + believability); **inverse-dynamics for unlabelled
state** (Pearce → DECIDE/pseudo-labels); **tiny discrete-action BC at inference** (MLMove → MOVE +
live bridge); **distribution-match / human-likeness evaluation** (MLMove → believability gate).
Transfers partially: MLMove is *macro* movement, not QW micro-physics — its outer loop maps to DECIDE,
not to the bhop inner loop. Does not transfer: CS movement physics, learned CS weights/action
constants, pixel input, Humanoid internals.

---

## 10. Deliverable / review

This program is **documentation**; no ML/training code, the new moveprobe mode, the gate harness, or
the Stage-0 spikes are written by this doc — those are the roadmap's steps, each under its own PR with
its own acceptance gates. Per #170 (cross-model independent review), this doc — authored by Claude —
**must be reviewed by a non-Claude model (e.g. Codex) before it merges to `main`.**
