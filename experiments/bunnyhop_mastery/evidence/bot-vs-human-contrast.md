# Bot vs human bunnyhop contrast — the mastery gap (2026-06-07, corrected 2026-06-08)

Input to the `bunnyhop-mastery-panel`. **Correction (2026-06-08):** an earlier version of
this doc claimed the human "carves a bounded ~354 qu radius arc." That was an artifact of
dividing the *median instantaneous* turn rate (which is strafe OSCILLATION) into speed.
Adversarial path-shape analysis (below) overturned it: the human's real path is **large
overlapping loops filling a ~1750 qu box, net rotation ≈ 0.5 turns**. Keeping the false
metric out of the controller design is the whole point of validating before building.

## Human fingerprint (trick5.cmds, fine-grained 77 fps, VALIDATED)

`scripts/extract_bunnyhop_fingerprint.py` reproduces the known benchmark as a built-in gate
(peak **1087.6** ≈ 1088, p50 **880.2** ≈ 880, ±5% PASS).

- Horizontal speed: peak **1088**, p95 1058, **p50 880** qu/s.
- Jump cadence **84.7/min** (52 hops over 36.8 s); view-yaw offset p50 **45°** (strafe).
- **Path shape (the corrected crux), via `scripts/plot_path_ascii.py`:**
  - **Net rotation over the whole run: −192° = 0.53 turns** (NOT a tight repeated circle).
  - Net displacement **475 qu** over **30,034 qu** path → **straightness 0.016** (NOT a
    straight runway either).
  - Bounding box **1749 × 1788 qu** — the path is **confined to a ~1750 qu square** and
    traces **two large overlapping (counter-rotating) loops**, ~800 qu radius each, whose
    rotations cancel to ≈0 net. See `human-trick5-path.txt`.
  - Instantaneous turn rate median 145°/s is the **strafe oscillation**, not path curvature.

## Bot current behaviour (mode-13, best runs)

- 60 s run: p50 535, max 656. **Long (180 s) run: p50 collapses to 292, max 598.**
- The collapse is the tell: mode-13's one-way circle-strafe + `acos(K/|v|)` angle turns
  *less* as speed grows → **radius grows as v² and net rotation accumulates** → it spirals
  outward, slams a trick.bsp wall (single-frame −324 qu/s drop), resets, re-accelerates.

## The reframe (overturns BOTH the loop's "map geometry" AND the "bounded carve" claim)

- The loop blamed a hard ~600 "map geometry" cap. **False:** the human sustains 880 in the
  *same* confined ~1750 qu box. The space is not the limit.
- The gap is **radius/area management**: the human keeps its loops *inside the box* by
  **counter-rotating** (net rotation ≈ 0), holding ~800 qu loops that fit; the bot
  **spirals outward** (net rotation accumulates, radius grows as v²) and leaves the area.
- **Crucial physics caveat for controller design:** under standard QW air accel (air
  wishspeed capped ~30), the max *air* turn rate at ~895 qu/s is only ~19°/s — far below
  what a uniform ~800 qu circle at 880 needs (~63°/s). So the human's net turning is **not**
  a uniform air-strafe curve; it is **varying-curvature multi-loop** (tighter, slower
  segments at the loop ends; near-straight fast segments between). A single constant
  wish-angle / constant turn-rate servo therefore likely **cannot** reproduce it — which is
  why the panel's analytic air-servo is suspect and the `replay-seed` proposal (borrow the
  human's actual input/path stream with closed-loop correction) was the physics-skeptic
  judge's top pick.

## The decisive experiment (revised)

Not a straight line, and not a constant-rate carve. The question is whether the bot can hold
a **confined, area-bounded loop pattern** (net rotation near 0, staying inside ~1750 qu) while
sustaining ~880 — and whether that is reachable by a *controller* at all or needs **path
replay**. Two candidate first runs:
1. **replay-seed (mode 12, already exists):** replay the human trick5 stream with bounded
   per-frame correction; measure how far past the ~2.7 s open-loop lockstep it sustains the
   confined ~880 loops. Proves a bounded 880 pattern is reproducible on this map at all.
2. **alternation/area control on mode 13:** make the strafe flip keep net rotation ≈ 0 inside
   a box (counter-rotating loops) rather than spiral; measure sustained p50 and wall-hit resets.

## Bot↔human comparison (headline numbers)

| metric | human trick5 | bot 60 s | bot 180 s |
|---|---:|---:|---:|
| p50 hspeed (qu/s) | 880 | 535 | 292 |
| peak/max (qu/s) | 1088 | 656 | 598 |
| net rotation | ≈0.5 turns (counter-rotating loops) | accumulates (spiral) | accumulates (spiral) |
| path | confined ~1750 qu box | spirals out | spirals out → resets |
| sustained? | yes (36 s) | until 1st wall | no — repeated resets |

Artifacts (this folder): `fingerprint-human-trick5.{json,md}`, `human-trick5-path.txt`.
