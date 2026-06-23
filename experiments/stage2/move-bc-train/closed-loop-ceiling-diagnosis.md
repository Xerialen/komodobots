# Closed-loop validation ceiling — root-cause diagnosis (2026-06-14)

The Stage-2 MOVE-BC checkpoint reported a "~1 s offline closed-loop validation
ceiling." This note pins **why**, because the answer changes what we build next.
Discipline (docs/00): surface the finding, do not tune around it.

## The evidence

`eval_closedloop.py` runs three controllers through `pmove_sim` with simulated
state fed back each tick: the trained **BC** policy, the **airlaw** prior, and
**recorded** (replays the human's *exact* recorded usercmds). The `recorded`
controller is the key diagnostic — it is the human input, so any drift it shows
is the **sim missing physics**, not a policy error.

| horizon | `recorded` route_err median | `recorded` in avg-band? |
|---|---|---|
| ~1 s (h77)  | **55.5 qu** | yes |
| ~2 s (h154) | **88.9 qu** | no  |

(source: `closedloop_h77.json`, `closedloop_h154.json`)

Yet `scripts/run_pmove_validation.py` shows the **exact same sim** reproduces a
single-player human `.cmds` route (dm3 SNG→RL, ~9 s) at **max 0.204 qu** with
**no divergence**. Same physics core. The difference is entirely *what the route
contains*.

## Root cause

The single-player SNG→RL route is **dry, worldmodel-only, no opponents** → the
sim is exact. The Stage-2 closed-loop runs replay **4on4 POV shards**, where the
recorded human is continuously:

1. **colliding with opponents** — the dominant effect. The MOVE-BC clean-yield
   analysis measured **player-collision = 78.6 % of all frame contamination** in
   the 4on4 corpus. The sim does **not** trace other players, so every bump the
   human took, the sim glides through → position drift.
2. riding **brush submodels** (dm3 has 6, all movers: the RL-lift/plat shaft
   `model[1–3]` and 3 doors/buttons). The sim traces worldmodel only.
3. **bunnyhop input-chaos** — air-accel is exponentially sensitive to wish-dir;
   tiny per-tick angle error compounds within ~1–2 s (already documented in the
   pmove validation report for the quantized bot log).

(1) and (2) are **missing-physics** (fixable by adding physents). (3) is
**chaos** — irreducible, and it means *absolute trajectory-match is the wrong
long-horizon metric* regardless of collision fidelity.

## What this means for the next build (corrected)

- The earlier framing "upgrade pmove_sim with submodels" was **half-right**:
  submodels are real but **secondary**. The binding constraint is
  **opponent-player collision (78.6 %)**.
- Opponent collision needs **per-tick opponent positions** time-synced to each
  POV shard (POV `.qwd` timeline ↔ MVD all-player positions). That sync does not
  exist yet and is **also a Stage-3 AIM prerequisite** (target-selection fusion),
  so it has high reuse value.
- Even with perfect collision, the closed-loop **gate metric should migrate**
  from absolute position-error-vs-one-human to **route-segment completion +
  speed-band retention over many starts** (distributional), per references/12 G-M1 —
  because chaos (3) caps absolute-match no matter what.

## Build order (this is the corrected plan)

1. **Multi-physent trace foundation** in `pmove_sim` (DONE this session): the
   trace iterates world + a physent list, takes the nearest hit. Brush submodels
   load as static at-rest physents; a box-hull builder is ready for player boxes.
   Worldmodel-only default is byte-identical to the validated baseline (opt-in).
2. **Opponent-ghost collision**: POV↔MVD per-tick sync → inject opponents as box
   physents → re-run the `recorded` reference; success = its 2 s route_err drops
   materially from 88.9 qu. (Needs the sync pipeline — the real next decision.)
3. **Distributional closed-loop gate**: route-completion + speed-band retention
   over many starts, replacing absolute position-match past ~1 s.
4. **Moving submodels** (lift timing from KTX QC) — last, lowest yield.
