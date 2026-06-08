# Step 0 finding: the human technique is a sustained circle-strafe that BUILDS speed — the "540 ceiling" was a controller artifact, not physics

Date: 2026-06-08. Source: `artifacts/replay/trick5.cmds` (the human demo, 2837 frames, 77 fps).
This was meant to be a geometry sim ("is 880 reachable on trick's straight chord?"). The cheaper
falsifier — segmenting + reading the human's actual per-frame commands — **falsified the plan's
premise** (long straights + sharp end-turns) before any sim was built. Step 0 did its job.

## What the human actually does (per-frame, warmed up, hspeed > 800)

- **forwardmove = 0** (p50/p90 = 0), **sidemove = ±400 constant** (95% of frames pure strafe).
- **view yaw rotates continuously at ~2°/frame ≈ 154°/s**, steadily (not oscillating).
- **strafe sign and turn direction are perfectly coupled:** side `+` ⇒ view turns CW; side `−`
  ⇒ view turns CCW. (Per-second table below.)
- The human **holds one (side, turn) pairing for several seconds** — a sustained circle-strafe —
  then **flips BOTH together** for the next arc. That alternation is the figure-8/S-pattern that
  keeps the path inside the ~1750-qu box.

## The decisive observation: a single-direction circle-strafe BUILDS speed

| t (s) | strafe | turn | mean hspeed |
|---:|:--:|:--:|---:|
| 15–22 | + | CW | **929 → 1072** (monotonic climb over 7 s) |
| 23–24 | − | CCW | 1068 → 823 (the direction-switch dip) |
| 29–32 | − | CCW | 923 → 976 (climbs again) |

Speed **increases throughout a sustained coupled circle-strafe** and only dips briefly at the
direction switches. There is **no ~540 plateau**. The human loops a ~875-qu-radius arc at
880–1072 qu/s — well inside the box.

## Why my earlier "ceiling" was wrong

I derived an air-strafe turn-rate cap `ω ≈ 300/v` (≈19°/s at 890) and concluded a confined circle
caps at `√(300·R) ≈ 540`. **The human turns the view at ~154°/s and sustains/builds speed — 8×
that cap.** The `300/v` model describes holding a *static* wish-dir at the speed-optimal angle; it
does **not** bound a *continuously rotating* wish-dir (a circle-strafe), where velocity chases the
rotating view at the optimal lag and keeps accelerating. The model was the wrong tool.

So the modes-13/14 results re-read correctly:
- **Mode 13** (carve around velocity, one-sided) had the accel but let radius grow unbounded →
  spiralled into walls at ~600. It was *almost* a circle-strafe but never flipped to stay confined.
- **Mode 14** (orbit) bounded the path but rotated the base heading **slowly** (~5–10°/s, by
  design) and flipped the carve **every hop** (S-strafe) → velocity stayed aligned with the slow
  heading → almost no acceleration → capped ~540. The orbit killed the very mechanism that builds
  speed.
- **v4** got the *facing* right (look along travel) but inherited the slow rotation + per-hop flip,
  so it held ~480 and never built.

The synthesis the human demonstrates: **mode-13's continuous coupled accel + mode-14's confinement
— achieved not by slowing the turn but by FLIPPING (side, turn) together every few seconds.**

## Implication for the controller (supersedes the figure-8 straight/turn state machine)

Mode 15 is simpler than the planned straight/turn machine: a **sustained circle-strafe** —
- hold `sidemove` one sign; rotate the **view continuously in the coupled direction** at the rate
  that keeps velocity lagging the view by the accel-optimal angle (the rate scales with speed; too
  slow = no accel = the mode-14 bug; too fast = velocity can't follow = speed bleeds);
- **flip both `sidemove` sign AND turn direction together** when approaching the wall (traceline)
  or on a timer, to stay confined → the figure-8 emerges from the flips, not from straights.

The key tunable is the **continuous view turn-rate** (and its speed scaling), NOT a turn-loss
budget. The geometry sim (`sim_figure8_cycle.py`) is **moot** — there is no build/bleed cycle to
budget; the circle-strafe builds continuously.

## Status of plan
Step 0 (falsifier) complete with a stronger result than expected: it killed both the straights
premise and the 540 ceiling. `docs/07_FINDINGS_LOG.md` must be corrected (it still says "accel
solved / navigation-bound" AND implies a geometry ceiling — both wrong). Next: build mode 15 as a
coupled circle-strafe with synchronized flips; the control-law numbers (turn-rate ~150°/s, flip
cadence ~ every 3–7 s / at wall, side ±400) come straight from this demo.

Apparatus added: `scripts/segment_phases.py` (phase segmentation; revealed the per-hop vs macro
structure and the (side,turn) coupling).

---

## CORRECTION (after live mode-15 runs) — the accel is S-strafe at ~80°, not a constant-side circle-strafe

Three live mode-15 runs forced a correction to the *mechanism* (the headline — 540 ceiling is
false — stands; mode-15 v1 built to **657** in open space, well past 540).

- **mode-15 v1** (continuous constant-side view-turn + reactive wall-flip): built to 657 in
  sawtooth bursts, but the wall-flip **chattered** (flipped every 0.25 s near a wall) and
  collapsed the strafe pocket → periodic crash to ~50.
- **mode-15 v2** (center-anchored, flip every 2.5 s): flipping too often **killed the build**
  (avg 54) — building needs ~8 s of sustained strafing.
- **mode-15 v3** (no flips, pure constant-side continuous turn at 150°/s): **stuck at ~150** in a
  217-qu box — a constant-side continuous view-turn does **NOT** accelerate.

Re-measuring the human at the **low/mid-speed building ramp** (not the near-terminal t15 window)
shows the real accel mechanism, and it is **consistent with QW air physics**:
- the human **S-strafes** — `side` alternates +400/−400 each hop, `forwardmove ≈ 0`;
- the **wishdir sits ~80° off the velocity heading** (|offset| 67–87°, nearly perpendicular =
  the accel-optimal: `v·wishdir` small → `addspeed` large → strong accel);
- `dspd/dt` is strongly positive (70–115 qu/s²) through the ramp;
- the velocity heading advances slowly, giving the confined curve.

This is **exactly mode 13** (carve to `acos(26/v) ≈ 80°` off velocity, sign alternating per hop),
which already reached **656**. **Mode 15's open-loop constant-side view integration was a wrong
turn** — it abandoned the proven S-strafe and the velocity-closed-loop, so it stalled. The earlier
"constant side held for seconds, coupled to turn" reading was a 1-second-block majority-vote
artifact over the near-terminal high-speed segment, where alternation is slower.

**Corrected path to 880 (grounded, no longer guessing the physics):** start from the proven
mode-13 S-strafe accel; add (a) a slow net-heading bias so the straight S-strafe **curves** into a
confined loop, and (b) periodic synchronized flips for the figure-8. This is the plan's **Step 1**
(the mode-13 straight-line accel test) that I leapfrogged — it must be run first to establish the
real confined accel ceiling of the proven mechanism before adding the curve/flip layer.

