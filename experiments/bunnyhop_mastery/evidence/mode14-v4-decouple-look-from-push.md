# Mode 14 v4 — decouple LOOK from PUSH (face the travel direction) — trick.bsp, 2026-06-08

## The correction (user, with `tricks-direction.jpg`)

The user watched the v3 demo: *"clearly the bot is watching the center of the map, which is
not at all what I meant."* The drawing is a **big CCW loop hugging the round wall**, arrows
pointing **along the direction of travel** — the bot should **look ahead, around the contour of
the wall** (where it goes next). The scribble in the middle is the center it must **ignore**,
not stare at.

## Why v3 watched the center (root cause)

v3 set the **view = the carve wishdir**, which air-strafe holds **~85° off velocity**, and then
pushed **pure forwardmove** along that view. On a tight orbit (radius 624) about the centroid,
"85° off velocity" points **straight at the center** → the bot literally faces the infield.
The loop was also too tight (circling the centroid, not hugging the wall).

This conflated two things that humans keep separate: **where you look** (ahead, along the path)
vs **where you push** (the carve, sideways). The dance insight names it exactly — *face your
partner, footwork underneath.*

## The fix (two changes, physics unchanged)

1. **Decouple look from push.** The **view** is now `base_yaw` — the loop tangent, the travel
   direction (look ahead around the round wall). The carve wishdir (`proposed_dir`, **identical
   to v3**) is emitted as **forward/side strafe** by projecting it onto the view's own basis
   (`DotProduct(v_forward/v_right, proposed_dir)*maxspeed` — the established idiom at
   bot_movement.c ~line 2109). `wishvel == proposed_dir*maxspeed` **exactly**, so the air-accel
   is bit-for-bit v3 — only the rendered facing changes. The bot now looks ahead and **mostly
   strafes** (tiny forwardmove), like a human, instead of forward-staring at the center.
2. **Hug the wall.** Default orbit radius **624 → 850** (and radius_gain 0.5 → 0.6) so the loop
   fills the room to the round wall (human trick5 loop half-extent ~875), matching the drawing —
   not a tight infield circle.

## What this does and does NOT change

- **Look:** fixed — the bot faces its travel direction around the wall (the drawing). This is the
  whole point of the correction and the realization of the direction/dance model.
- **Speed:** the wishdir is unchanged, so per-frame accel is the same as v3. Speed moves only
  through the larger radius (a bigger circle's turn-rate ceiling, `v≤√(300·R)`). v4 is the
  *correct facing*, not a new accel mechanism. Breaking past the single-circle band toward 880
  still needs the **figure-8** (straight runs + end turns) — unchanged conclusion.

## Live result (run 20260608T045003Z, single bot, trick.bsp, 45 s)

| signal | v3 | **v4** | human trick5 | verdict |
|---|---:|---:|---:|---|
| **facing**: \|view − travel heading\| | ~85° (at center) | **14° median** (p90 19°) | slight lead | **fixed — looks ahead along the wall** |
| **path** | tight circle about centroid | **big CCW loop hugging the wall, center empty** | confined loop | **matches `tricks-direction.jpg`** |
| sustained hspeed (P95) | ~482 | **482** | ~880 | unchanged (as predicted) |
| max hspeed | 596 | 515 | 1088 | same band |
| jump cadence /min | ~84 | 96 | 84.7 | human-like |

The **facing correction landed**: the bot's view sits **14° off its velocity heading** (looking
ahead, slightly leading into the turn — exactly how a human carves), versus v3's ~85° sideways
stare at the infield. The path is a **large smooth loop along the perimeter wall with the centre
empty** — the user's drawing — not v3's tight centroid circle. Speed is the **same band as v3**
(max 515 / P95 482), confirming the predicted invariant: identical wishdir ⇒ identical accel; v4
changes the *look*, not the *push*.

Demo for ocular review: `tricks/dm3/trick14v4__20260608T045003Z.mvd` (+ nQuake watch mirror).

## Status
Built clean on servexeri; live run done; **stock restored** (symlink → `qwprogs-1.48-dev-08807d.so`).
The direction/dance model is now correctly realized. Reaching the 880 band from here remains the
**figure-8** (straight high-speed runs + end turns) — v4 is the correct *facing* foundation it
builds on. Patch: `experiments/ktx_moveprobe/frogbot-moveprobe.patch` (regenerated).
