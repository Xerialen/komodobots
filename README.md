# Komodobots

Komodobots is a QuakeWorld bot research lab.

The project exists to answer one larger question:

> Can QuakeWorld bots become realistic enough to act as believable substitutes for real players?

The program of record is **`docs/18_BENCH_ITERATED_BOT_PROGRAM.md`** (greenfield, 2026-06-16): a learned move+aim+decision DM3 4on4 stand-in, modeled on real elite human demos, measured on a 4v4 bench. The data that feeds it is contracted in `docs/25_DATA_CONTRACT.md`.

This repository is not primarily about making Frogbots bunnyhop. Movement (bunnyjumping) was the first visible and measurable bottleneck on the path toward realistic player and match simulation; the earlier "DM2 big room movement lab" framing in older docs is historical context, not the current plan.

## Two possible long-term destinations

Komodobots may later support either or both of these tracks:

1. **FantasyQuake** — simulated matches, seasons, drafts, and player value based on real QuakeWorld data.
2. **Megalodon Milton** — player-specific agents that try to imitate elite players, starting with Milton, from MVD-derived evidence.

Both tracks need the same foundation: believable movement, then believable player behaviour, then believable simulation.

## Start here

Codex and human contributors should read these first:

1. [`docs/00_VISION_AND_NORTH_STAR.md`](docs/00_VISION_AND_NORTH_STAR.md)
2. [`codex/START_HERE.md`](codex/START_HERE.md)
3. [`docs/01_PROJECT_BRIEF.md`](docs/01_PROJECT_BRIEF.md)

## Current hypothesis

KTX/Frogbots may already provide the hard engine-native substrate: server physics, collision, combat, KTX rules, and MVD recording. If we can replace or enhance only the movement controller, we may avoid rebuilding a complete QuakeWorld simulation stack.

This hypothesis is unproven. The first lab must prove or disprove it.

## Mapping routes & movement signatures

Believable movement is trained and graded **per route**. Two pieces of tooling produce that ground truth from real play, and they sit at a specific point in the pipeline:

```
parsed MVD demos
   └─ route_observatory ─────────────► resource→route canon   (WHERE humans go)
         └─ route-signature skill ───► per-route movement      (HOW humans move)
                                        signature
              └─ route-conditioned BC training (GPU)           (target to imitate)
                    └─ bot trajectory vs the human envelope     (believability score)
```

- **`experiments/route_observatory/`** extracts the **route canon** — *a route is the path between two
  resources* — from parsed demos, co-canonical with the qwd named routes (see its
  [`README`](experiments/route_observatory/README.md)).
- The **`route-signature`** skill ([`.claude/skills/route-signature/SKILL.md`](.claude/skills/route-signature/SKILL.md))
  turns a route leg into its **human movement signature** (speed profile, jump cadence, look-vs-move)
  and a **fused POV+route view** you validate by eye. Use it whenever defining a route's BC target or
  its believability rubric, or fusing a POV recording against demo state. How it works: `pov_fuse_extract.py`
  slices the leg + computes the signature → `pov_fuse_render.py` builds the fused contact sheet →
  `pov_fuse_shot.js` screenshots it, which is then **read back and checked against the POV pixels**
  (eval-integrity). Worked example: [`evidence/pov_fuse_megaRL.png`](experiments/route_observatory/evidence/pov_fuse_megaRL.png).

This is **Megalodon Milton** groundwork (movement first), and the route signatures are the targets the
movement controller is trained and scored against.
