# Plan: the Demo Extraction Specification (method-agnostic · complete · durable)

## Why this is THE priority (owner directive)

Author a **standing specification** for extracting **everything recoverable** from the demos —
complete, usable, durable — so the expensive parse is done **once** and never redone when the method
changes (AMP / RL / BC: the spec transcends the method). Two audit findings make this both necessary
and tractable:

1. **We extract ~movement only — a fraction of the demo's content.** The MVD wire format carries, per
   the in-house decoder (`mvd_analyzer-src`), per ~77 Hz frame for ALL 8 players: position +
   view-angles; health / armor / armor-type / ammo-per-type / active-weapon / items+powerups; frags,
   deaths (attacker/victim/weapon); per-hit damage matrix (KTX hidden block, ~2024+ demos); item
   pickup+respawn timeline; movers; chat/obituaries; pauses; cvars. Our catalog *schema already has
   columns* for the rich fields (health/armor/weapon in `player_ticks`/`actor_ticks`; `item_events`,
   `actor_visibility` tables) — they are **not populated** because `catalog_etl_mvd.py` requests only
   `positions,view,velocity`. So "get everything out" is largely **consuming a decode we already
   have**, not new decoders.
2. **A ground-truth INPUT corpus we don't use: 548 dm3 POV `.qwd`** (70 `.qwd` + 478 `.qwz`→`.qwd`) on
   servexeri `/mnt/usb-ssd/4on4-corpus/challenge-tv-pov-dm3/`. A first-person `.qwd` carries raw
   per-frame **usercmds** (forwardmove/sidemove/upmove/buttons/viewangles @77 Hz) — the **real
   forwardmove IDM cannot recover from MVD**, plus true viewangles = the **fidelity oracle + a
   ground-truth action-label** source. (Does NOT resurrect BC-as-method; it closes the data hole.)

So the extraction is **two-source, full-content, do-once**: broad omniscient MVD state-distribution
(all players, full game state, IDM-recovered movement) + QWD POV ground-truth input. Completeness is
**guaranteed by diffing against the full wire inventory** (the decoder Result schema = the master
list): every field accounted for as extracted / derived / excluded-with-reason.

**Scope split (owner, this session).** The owner is separately extending the analyzers (renamed
`qwd-analyzer` / `mvd-analyzer`) to emit MORE fields — a parallel track. My job is the **do-now durable
foundation** that does NOT block on it: the spec + audit framework + fidelity + derivations valid
*regardless of which fields exist*, built **forward-compatible** so new analyzer fields slot in
**additively** (the taxonomy reserves slots; the coverage table just gains rows). **Tool names are in
flux**, so the spec references decoders by **role + provenance (binary sha + schema version), never a
hardcoded tool name** — a rename can't break it. The overriding goal: **specs, plans, and the agent's
own persistent instructions/memory (incl. `CLAUDE.md`) stay durable and hold through the WHOLE
project** — Deliverable 3.

## Deliverable 1 — the Specification Document (`docs/NN_DEMO_EXTRACTION_SPEC.md`)

A standing, versioned doc = single source of truth for what we pull and how. Sections:
1. **Purpose & scope** — method-agnostic; the maximal RAW representation; models consume
   subsets/derivations. Both sources (MVD omniscient · QWD POV).
2. **Source inventory & provenance** — what each format physically carries (MVD = server/omniscient,
   NO usercmds; QWD = client POV, real usercmds); decoders + schema versions + binary shas
   (qw-analyze schema-33 `6954ffb6`; in-house `mvd_analyzer` Go Result schema); corpus locations +
   counts (6,409 4on4 MVD; 548 dm3 POV QWD) + sha/size locks.
3. **The complete field taxonomy** *(the heart)* — every recoverable quantity, by entity (self /
   all-actors / items / movers / world) and role tag [K]inematic · [A]ction · [I]ntent-goal ·
   [G]eometry · [R]egime · [C]ombat · [E]conomy-items · [M]eta. Per field: name, units, source
   (wire message / derivation), recoverability+confidence (observed / IDM-recovered /
   finite-differenced / unrecoverable), availability (always / era-gated / POV-only), role (input /
   target / filter / held-out / context), train-vs-eval plane. **Diffed against the full wire
   inventory** → coverage table.
4. **Fidelity contract** — temporal resolution (~72–77 Hz), physics-step rate, interpolation/resample
   policy, justified by the QWD-usercmd replay + the KTX server-side velocity oracle (the set-aside
   plan's Phase-A feeds this).
5. **Derivation specs** (greenfield, defined before built) — [G] geometry (wall-dist, ledge-ahead,
   ramp normal, pad/tele proximity from `dm3.bsp` traces); [R] regimes; leg-phase; [C] threat
   (nearest-enemy + LOS raycast — a deferred TODO today); [E] item respawn-ETA urgency.
6. **Hold-out / leakage / provenance rules** — MVD forwardmove never trained (only QWD POV); IDM
   labels held out (is_interp); G-MV gates eval-only; reward-leakage split; clean-movement filter def.
7. **Versioning & durability** — additive columns; raw kept maximal; derivations recomputable;
   reproducibility (binary/demo shas, decoder version); the doc IS the contract.

## Deliverable 2 — the Data format (the extracted catalog; usable + lasting)

- **Storage = the relational catalog (SQLite), extended.** Keep the maximal RAW representation; models
  derive obs from it — do NOT bake model-specific obs into extraction. Tables: `player_ticks` /
  `actor_ticks` (per-tick all actors: pos, vel(derived), angles, hspeed, onground(+proxy), waterlevel,
  **+ populate health/armor/armor_type/weapon** + derived [G]/[R] columns); `actions` (`label_source`
  = qwd_usercmd ground-truth incl. forwardmove / idm recovered / sim; confidence; is_interp;
  align_shift); `actor_visibility` (**populate the LOS raycast** for [C]); `item_events` + `items`
  ([E]/[I] timeline + timers); `damage_events` / `frags` / weapon+powerup intervals / ammo tracks
  ([C]/[E]); `episodes`/`demos`/`players`/`teams`/`maps`/`markers`/`nav_edges`; segments/legs (#334) +
  leg-phase. Optional parquet export per consumer; SQLite = source of truth.
- **Completeness principle** — extract once, maximal, raw; a field-by-field coverage report
  (extracted / derived / excluded-with-reason) proves it against the wire inventory.
- **Durability** — provenance (binary/demo shas, schema + decoder version), reproducibility; canonical
  on servexeri (~GB, not git, not aws-dev); only summary + spec committed.
- **Validation** — FK integrity; field coverage vs wire inventory; hold-out intact (MVD forwardmove
  held; IDM is_interp); fidelity reproduced (QWD replay + velocity oracle); QWD↔MVD cross-check on any
  game present in both.

## Deliverable 3 — durability / persistence (so specs, plans & CLAUDE.md last the project)

Fixes the recurring failure mode: knowledge scattered + lost (`rl-plan.md` was a lost untracked
scratch file; agent memory went stale on the RL state). Make the knowledge infrastructure durable:
1. **Spec lives durably + registered** — `docs/NN_DEMO_EXTRACTION_SPEC.md`, versioned with an
   **additive** schema (new fields append, never restructure), registered in `docs/02_SOURCE_MAP.md`
   + the evidence chain (`docs/21`) so it's authoritative, not scratch.
2. **Plans get durable homes** — planning docs committed under `plans/` (the rl-plan lesson), not left
   untracked; this spec plan + the set-aside strategic plan included.
3. **Persistent agent memory refreshed** — rewrite the top of the auto-memory `MEMORY.md` + relevant
   memory files so the project north-star is the **data-contract/spec** (not the stale RL-only
   framing); record the do-once two-source/full-content findings + the 548 QWD POV discovery + the
   "we extract only movement" gap, so a future session/compaction resumes correctly.
4. **The agent's own `CLAUDE.md`** — update `~/.claude/CLAUDE.md` (machine-local) to anchor on the spec
   as the durable project contract + the do-once-extraction principle + search-the-vault; propose (as
   a gated repo PR) registering the spec in `AGENTS.md` (shared source of truth) so every assistant
   (Claude / Codex / Gemini) reads the same contract and doesn't drift.
5. **Forward-compatible with the owner's analyzer track** — a "pending / expected fields" section in
   the spec reserves slots for the new analyzer output, so when it lands it's already accounted for
   (no redesign); decoders referenced by role + sha + schema version, never tool name.

## The work to author it (CPU/analysis; autonomous-OK; the RUN is a later gated step) — do-now items independent of the owner's analyzer track

1. **Completeness audit** — enumerate the full MVD+QWD field inventory from `mvd_analyzer-src`
   (Result / PlayerStream schema = master list) + the qw-analyze include-flags; diff vs the current
   catalog → the field-by-field gap table. (Key sub-question: how much more can the SAME
   qw-analyze/mvd_analyzer already emit that we simply don't request — likely most of it.)
2. **Two-source reconciliation** — map MVD (omniscient, IDM actions) + QWD POV (ground-truth usercmds)
   into one schema (`label_source` already distinguishes); find games present in BOTH (calibration);
   decide decoder(s) — lean on the full in-house decode for the rich fields vs the movement-only path.
3. **Fidelity experiment** — QWD-usercmd replay through `pmove_sim` vs recorded speed + KTX velocity
   oracle + MVD-step-held comparison → the fidelity-contract section + the resample decision.
4. **Derivation specs** — define [G]/[R]/leg-phase/[C]/[E] precisely (units/source/algorithm) against
   the existing trace/nav/item primitives.
5. **Write the spec + the extended schema + the coverage/validation plan.** Review (owner + Codex).
   THEN (separate, gated) execute the full extraction ONCE.

## Critical files / sources
- Wire inventory (master list): `mvd_analyzer-src/mvd-reader/` (parser/*, `MVD_FORMAT.md`),
  `mvd-analytics/result/*` (`result.go`, `streams.go` PlayerStream, `damage.go`, `items.go`),
  `RESULT_SCHEMA.md`.
- Current extraction: `scripts/catalog_etl_mvd.py`, `scripts/catalog_etl_qwd.py` +
  `tools/qwd_usercmd/qwd_usercmd.py`, `scripts/catalog_schema.sql`, `data/catalog/feature_registry.yaml` (v5).
- Derivation primitives: `scripts/pmove_sim.py` (bsp traces), `data/catalog/item_catalog.dm3.json` +
  `nav_edges.dm3.json`, `experiments/route_observatory/route_legs.py` (#334), `scripts/gmv_believability.py`.
- Corpora (servexeri): `/mnt/usb-ssd/4on4-corpus/demos/` (6,409 MVD),
  `.../challenge-tv-pov-dm3/` (548 POV QWD). Vault: `~/thevault/quakeworld/mvds.md`,
  `~/thevault/projects/mvd_analyzer.md`.

## Verification
- Spec doc exists + versioned; its field taxonomy is **diffed against the full wire inventory** (a
  coverage table: extracted / derived / excluded-with-reason).
- The deliverable schema is defined for BOTH sources with provenance (`label_source`), rich fields
  populated, context-derivation layers spec'd.
- The fidelity contract is backed by QWD-replay + velocity-oracle numbers.
- A dry coverage report on a few demos shows the extraction captures the FULL field set (not just
  movement) before the heavy run.
- Durability: the spec is versioned + registered (source-map/evidence-chain); plans live in `plans/`;
  the auto-memory + `~/.claude/CLAUDE.md` anchor on the spec; the "pending fields" reservation exists;
  nothing references a tool by name (role + sha + schema version only). A fresh session can resume
  from the persistent layer with no re-derivation.

## Constraints / honesty
- This is the do-once foundation; resist baking model-specific obs in (raw maximal + derivations
  recomputable).
- Era-gating is real: per-hit damage/economy only on ~2024+ KTX demos — spec marks availability per
  field, never assumes.
- forwardmove ground truth exists ONLY in QWD POV; MVD forwardmove stays held-out/unrecoverable — the
  spec encodes that asymmetry.
- Heavy compute servexeri/pinnacle only; never pull the GB DB to aws-dev; the full extraction RUN is a
  separate gated step after spec approval; Claude never merges / sets gate labels.

---
═══════════════ SAVED · SET ASIDE — strategic modeling plan (the method that CONSUMES this data; revisit after the spec lands) ═══════════════

# Plan: fidelity-first path to fast, believable dm3 movement (RL with a learned human prior)

## Context

**Goal (clarified with the owner).** For the **movement pillar**, the objective is **speed/skill** —
master the dm3 bunnyhop, move fast and efficiently. "Looks human" is an instrumental *constraint*
(don't be degenerate; pass as a stand-in), **not** the maximand. Combat (frags, hits, positioning)
is a separate, later pillar and is out of scope here.

**The through-line of three stalls.** Each stall has the same shape: an approach works in a
narrow / open-loop setting (replaying a recorded route, clearing one easy route) then falls apart
**in closed loop** when the bot drives itself into states the demos never covered and can't recover
(covariate shift). The supervised family (BC / reweight / GRU-seq / DAgger) is exhausted; the
RL-on-speed line (8 rounds, `feat/rl-onspeed`) solved the central over-press failure in-band but
plateaued on a hand-set **cadence-vs-launch** tension — a symptom of optimizing a **soup of
mutually-competing scalar proxies** for "human." The current reward literally sums **7 hand-set
terms** (`ml/rl_onspeed.py:460`: `r_speed, r_phi, r_strafe, r_prog, r_cad, r_press, p_hack`).

**Two complementary levers — and the owner's instinct correctly orders them.**

1. **Temporal fidelity (the owner's "interpolation" point).** Audit-confirmed in code: the corpus
   is ~72 Hz (13–14 ms ticks; `scripts/catalog_etl_mvd.py:237`); `pmove_sim` integrates **once per
   frame** at `dt = msec·0.001` with **no sub-stepping** (`scripts/pmove_sim.py:962,730`); yaw /
   sidemove / jump are **step-held** with **no temporal interpolation of inputs anywhere**
   (`catalog_etl_mvd.py:248`, `ml/eval_broad_dryroute.py:590`). QW air-acceleration integrates
   `wishdir=f(yaw)` held constant across each frame, so **if the corpus snapshot rate is coarser
   than the physics the human actually executed, the sim cannot reproduce — or learn — the true
   high-frequency air-strafe.** This is a *physics-fidelity* question (not aesthetic smoothing),
   and it can silently invalidate everything built on top. Honest caveat: fidelity is **necessary
   but not sufficient** — it removes a confound; it does not by itself fix closed-loop
   generalization. Step-held yaw per physics frame is also what the real QW engine does, so the
   real question is **rate**, not smoothing — and it is **measurable** (the QWD usercmd demos are
   ground-truth input).

2. **A learned human prior (replace the proxy soup).** Use the 534M-tick corpus as a learned
   **prior/guardrail** — an adversarial-imitation discriminator `D(state, next-state)` scoring "is
   this transition on the real human-technique manifold" — instead of the hand-set cadence/strafe/
   press bands. Under a **speed objective**, the prior's job is to keep speed-seeking on the
   manifold where the *real* fast bunnyhop lives, so RL finds real technique instead of a
   degenerate sim-exploit (orbit / pogo / bulldoze). The discriminator needs only `(s, s')` pairs —
   **no action labels** — which fits the held-out-action corpus exactly. Infra is greenfield but
   the hooks are clean: insertion at `ml/rl_onspeed.py:635` (alongside/replacing the KL-anchor); a
   per-tick `(s, s')` stream already exists (`ml/pipeline/build_features.py:_load_episode_ticks`,
   `ml/eval_broad_closedloop.py:select_start_segments`); the #334 segmenter + per-route envelopes
   (`experiments/route_observatory/route_legs.py`) give conditioning.

---

## What to sample per tick — the contextualization inventory

To make movement *interpretable* — and to define "human-like transition" **conditionally**, not as a
global average — each tick must carry not just the kinematics but the context that shaped them.
Full inventory, tagged by role: **[K]** kinematic state · **[A]** recovered action (held out of
training) · **[I]** intent/goal · **[G]** map geometry · **[R]** physics regime · **[C]** combat/threat.

1. **Self kinematics [K]** — pos x,y,z; vel vx,vy,vz (→ hspeed, vspeed); view yaw, pitch; yaw-rate
   (turn direction; finite-diff; fidelity-sensitive); face-vel angle (yaw − velocity-heading = the
   air-strafe signal); onground; per-tick msec (fidelity). *(all present today)*
2. **Recovered action [A]** — jump press (onground→jump = re-hop); strafe sign (in-regime ≥400 only);
   implied wishdir. **forwardmove is unrecoverable — an explicit hole, held out.** *(present; is_interp=1)*
3. **Intent / goal [I]** — next-resource heading + distance (goal-conditioning); route segment
   (from→to) + progress + leg-phase (launch / cruise / approach / land). *(goal present; segment = #334)*
4. **Map geometry [G]** — region, and the geometry air-strafe & trick-jumps are *relative to*:
   distance/normal to nearest wall, floor height & ledge-ahead, ramp/incline, jump-pad/teleporter
   proximity. **NOT in the corpus today** — derivable from `dm3.bsp` (already traced for onground).
   This is what makes a trick-jump interpretable (you strafe *toward* a ledge).
5. **Physics regime [R]** — speed regime (accel <400 / cruise ≥400); grounded / airborne / in-water;
   on-ramp / stairs; pre-/post-jump tick. *(derivable; partly present)*
6. **Combat / threat [C]** — health, armor (present); nearest enemy/teammate positions + distance +
   rough line-of-sight; item availability / respawn urgency; being-shot-at / shooting. **The MVD has
   all players' positions, so this is cheap to sample even though combat is the later pillar.**

**Why [C] matters even for the movement pillar:** without threat context you cannot separate "moved
this way for route/technique" from "moved this way dodging a rocket." So we **sample [C] to FILTER**
the human reference to *clean-movement* segments — the prior and the band-checks then learn pure
bunnyhop technique, not evasion. We do **not** condition the movement policy on [C] (that's the combat
pillar); it's a cut, not an input.

**Obs-space consequence (the decision this forces):** the discriminator scores the *policy's* obs, so
whatever context the reference conditions on, the policy must also see. Today that's [K]+[I] (21-dim
self + goal + entities). [G] geometry is the likely necessary addition for trick-jumps; [R] is cheap.
**Phase B decides — from the data — which context features actually predict human-ness**, and that
fixes the final discriminator/policy obs spec *before* the GPU run. This is the "all parameters on the
table before the run" gate.

---

## Deliverable reframe: a standing specification, not a one-off prep

The right artifact is a **Movement Data & Feature Specification** (`docs/NN_MOVEMENT_DATA_SPEC.md`) — a
standing document, not a throwaway prep plan. We are **not** starting from scratch: much of the
field-level contract exists, scattered and never consolidated — `data/catalog/feature_registry.yaml`
(registry **v5**: the 21-dim SELF, 13-dim ENTITY, goal fields, each with source column + norm + role),
`scripts/catalog_schema.sql` (`catalog.v1`: tables/types/FKs + provenance `label_source` /
`confidence` / `is_interp` / `onground_is_proxy`), and the `docs/` evidence chain
(`00-DATA-ARCHITECTURE`, `21_ML_EVIDENCE_CHAIN_GATE`) + `dm3_4on4_anchors.json`. **Why it feels missing
(and is incomplete):** no single doc states the *complete* state the model consumes, *at what temporal
fidelity*, and what's deliberately excluded — and the gaps are exactly the contextualization layers
([G] geometry, [R] regime, [C] threat-filter, leg-phase) + the fidelity contract, none of which exist
in code yet. The representation grew bolt-on (v1→v4→v5), one feature per experiment, because every run
chased a result — so it was never consolidated. That is plausibly *why* the runs kept hitting
representation walls.

## The plan (spec-first; Phase 0 authors the spec, A/B execute against it, C is the GPU run, D is gated live)

### Phase 0 — author the Movement Data & Feature Specification (the standing artifact)
One living doc `docs/NN_MOVEMENT_DATA_SPEC.md` = the single source of truth for what the model
consumes. It (a) **consolidates** the existing registry + schema *by reference* (do not duplicate —
point at `feature_registry.yaml` v5 + `catalog_schema.sql` as the field-level source of truth); and
(b) **adds the missing layers**, each with: definition, units, source/derivation, provenance, role
(input / target / filter / held-out), and train-vs-eval plane:
- the **fidelity contract** (the rate / interpolation decision — finalized by Phase A);
- the **[G] geometry**, **[R] regime**, **leg-phase**, and **[C] threat-as-filter** derivations
  (all greenfield per the audit) — spec'd before they are built;
- the **hold-out / leakage rules** (forwardmove never trained; G-MV gates eval-only; reward-leakage
  split) and the **clean-movement filter** definition.
Phase A/B then execute *against* this spec; it is updated as A's fidelity result and B's obs-spec
finding land. This is the "all parameters on the table before the run" gate, made durable.

### Phase A — Fidelity audit (CPU, decisive; this is a GATE, not a warm-up)
Test the owner's hypothesis by measurement before committing GPU. Concretely:
- **A1 — cmd-rate truth.** Measure the actual per-cmd `msec` distribution in the **QWD usercmd**
  corpus (`scripts/catalog_etl_qwd.py`, `ctv_decomp` dm3 demos — real inputs) vs the **MVD** 72 Hz
  snapshot cadence. Establishes whether MVD is downsampled relative to the physics the human ran.
- **A2 — replay-reproduction test.** Replay QWD **ground-truth usercmds** through `pmove_sim` and
  check it reproduces the recorded speed/trajectory (sanity on the sim itself). Then replay the
  **MVD-derived step-held yaw at 72 Hz** and compare achieved speed. **If MVD-replay loses speed
  vs QWD-replay → quantified fidelity gap → up-sampling/interpolation of the control signal to the
  physics rate is required (and A tells us the target rate).** If they match → fidelity is fine,
  proceed without it.
- **A3 — decision.** Write a short fidelity finding (with the number). Gate: only proceed to the
  GPU run once we know the sim faithfully reproduces real human speed, or have the resampling step
  that makes it so. Reuse: `scripts/pmove_sim.py` replay CLI, `ml/verify_route.load_human`,
  `scripts/features/agent_observation.yaw_rate_degps`.

### Phase B — Corpus characterization + AMP reference set (CPU; autonomous-OK)
- **B0 — sample the full inventory** (the [K][A][I][G][R][C] table above) per tick, on servexeri:
  [K][A][I] are mostly present; **derive [G] geometry from `dm3.bsp`** (extend the existing onground
  floor-trace to wall/ledge/ramp/pad proximity); **derive [C] from the other players' positions** the
  MVD already carries; label [R] regimes. Emit a contextualized per-tick stream + the #334 segments.
- **B1 — distribution pass** over the 534M ticks (never pull the DB to aws-dev): per-state air-press,
  strafe-flip cadence, jump cadence, speed, yaw-rate — conditioned on [I] segment / [R] regime / [G]
  geometry, **filtered by [C] to clean-movement segments**. **Deliverable that earns its keep:** check
  whether the hand-set G-MV bands (`scripts/gmv_believability.py`, `references/dm3_4on4_anchors.json`)
  actually match the data — I expect at least one "residual" (the cadence band the RL run fought) is a
  mis-specified gate. **+ an obs-spec finding:** which context features actually predict human-ness →
  fixes the final discriminator/policy obs before Phase C.
- **B2 — build the human `(s, s')` reference** the discriminator trains against: per-tick
  state-transition pairs in the **decided obs space** (≥ the 21-dim self / 16-tick history=336 /
  entities, plus any [G]/[R] features B1 justified), clean-movement-filtered, emitted at the
  **fidelity-correct rate** decided in A.

### Phase C — AMP-as-prior RL run (GPU on pinnacle; OWNER-GATED)
- Add a discriminator `D(s, s')` (greenfield, small MLP over the existing obs) trained adversarially
  on human (Phase B) vs policy rollout transitions; insert its term at `ml/rl_onspeed.py:635`.
- **Reward becomes:** keep the **objective + hard guardrails** (`r_speed`, `r_prog`, `p_hack`,
  launch-guard); **replace** the believability proxy soup (`r_strafe`, `r_cad`, `r_press`, and the
  KL-anchor) with the learned `D` term. Speed stays the maximand; `D` is the on-manifold constraint.
- Warm-start from the existing best ckpt (`rl_round6_r4init.pt`); keep the launch/G-MV1 guard +
  raw-validated metric vector per round (the existing overnight harness). G-MV gates become
  **eval-only judges**, not training signal (no train/eval leakage).
- Stop rule unchanged (5-run aggregate; guard-break backstops).

### Phase D — Live A/B (HUMAN-GATED)
First credible ckpt → live server via the shared-memory side-channel, sanity A/B against the
current bot. Catches the sim-to-live gap before over-investing. Never touches prod standing services.

---

## Critical files (from the code audit)
- Fidelity: `scripts/pmove_sim.py` (962 dt, 730/745 air-accel, 1021 cmd load), `scripts/catalog_etl_mvd.py`
  (237 msec, 248 yaw, 305 yaw-rate), `scripts/catalog_etl_qwd.py` (QWD usercmds), `ml/eval_broad_dryroute.py`
  (502/565 replay), `scripts/features/agent_observation.py:181` (`yaw_rate_degps`, `wrap180`).
- Prior/RL: `ml/rl_onspeed.py` (460 reward, 622–635 KL-anchor + loss = the AMP insertion point),
  `ml/pipeline/build_features.py` (`_load_episode_ticks`), `ml/eval_broad_closedloop.py`
  (`select_start_segments`), `scripts/features/agent_observation.py` (21-dim self / 336 history).
- Believability eval (becomes judge-only): `scripts/gmv_believability.py`, `references/dm3_4on4_anchors.json`.
- Segmentation/conditioning: `experiments/route_observatory/route_legs.py` (#334), `envelopes.json`.

## Verification (per phase)
- **0:** the spec doc exists; consolidates registry+schema by reference (no duplication); every added
  layer ([G] geometry, [R] regime, leg-phase, [C] threat-filter) + the fidelity contract + the
  hold-out/leakage rules has definition / units / source / role / train-vs-eval plane; reviewed before
  any extraction.
- **A:** a committed fidelity finding with the MVD-vs-QWD reproduced-speed delta; QWD-replay through
  `pmove_sim` reproduces recorded speed within tolerance; decision (resample-needed yes/no + target rate).
- **B:** the contextualized per-tick stream ([K][A][I][G][R][C]); a characterization report
  (band-vs-data table flagging any mis-specified gate) + a committed **obs-spec finding** (which
  context features predict human-ness); a clean-movement-filtered `(s,s')` human reference set at the
  fidelity-correct rate. All computed on servexeri; only summaries/specs committed (not the GB DB).
- **C:** per-round raw-validated metric vector; the learned-prior run holds launch + G-MV1, reaches the
  speed band, and does so on the human manifold (D can't trivially separate it) — compared head-to-head
  against the round-6 r4init baseline; no train/eval leakage (G-MV gates eval-only).
- **D:** live A/B sanity (human-gated); no regression of prod standing services.

## Constraints / honesty
- Fidelity is necessary-not-sufficient; do not let "interpolation" become a fourth over-promise.
- AMP is greenfield with real failure modes (discriminator over-powering, mode collapse, instability)
  — treat Phase C as a genuine experiment, not a sure thing; the Phase-A gate de-risks it.
- Heavy compute on servexeri/pinnacle only; never pull the multi-GB corpus to aws-dev. RL launch +
  GH-ticket creation owner-gated; live runs human-gated; Claude never merges / never sets gate labels.
- More action-labeled data is still NOT a BC lever — but the QWD usercmds ARE the fidelity yardstick
  in Phase A (calibration/validation, not cloning targets). That's the one refinement to the earlier
  "more action data won't help."
