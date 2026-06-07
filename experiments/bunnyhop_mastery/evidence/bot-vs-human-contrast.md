# Bot vs human bunnyhop contrast — the mastery gap (2026-06-07)

Input to the `bunnyhop-mastery-panel`. Reframes the loop's "acceleration is solved,
ceiling is map geometry" conclusion using the **validated** human fingerprint.

## Human fingerprint (trick5.cmds, fine-grained 77 fps, VALIDATED)

Extractor `scripts/extract_bunnyhop_fingerprint.py` reproduces the known benchmark
(peak **1087.6** ≈ 1088, p50 **880.2** ≈ 880 — validation gate passes at ±5%).

- Horizontal speed: peak **1088**, p95 1058, **p50 880** qu/s
- Jump cadence: **84.7/min** (52 hops over 36.8 s)
- View-yaw vs velocity offset: p50 **45°** (textbook strafe)
- **Turn technique (the crux):** median turn rate **145°/s** while moving, median
  moving speed **895 qu/s**, implied **carve radius ≈ 354 qu**.
- 45% of all frames are at 120–180°/s turn rate sustaining **855 qu/s**; even
  180–240°/s holds 815. The human is **continuously carving a bounded-radius arc**,
  not running straight and turning at the ends.

## Bot current behaviour (mode-13, best runs)

- 60 s run: p50 535, max 656. **Long (180 s) run: p50 collapses to 292, max 598.**
- The collapse is the tell: the bot's "speed-optimal angle" `acos(K/speed)` turns
  *less* as speed grows → **radius grows as v²** → it slams a wall, drops −324 qu/s
  in one frame, resets, re-accelerates. It **cannot sustain** speed.

## The reframe (overturns the loop's straight-runway premise)

- **Both** human and bot circle. The difference is **radius control**: the human
  holds a *bounded* ~354 qu radius (constant ~145°/s turn rate) that fits trick.bsp's
  open area and sustains ~880; the bot lets radius blow up and hits walls at ~600.
- So the ceiling is **not** raw acceleration and **not** "the map is too small" — the
  human proves the map fits a high-speed carve. The bot's controller **maximises
  instantaneous acceleration at the cost of an unbounded radius.**
- **The decisive experiment is therefore NOT a straight line.** It is a **bounded-radius
  carve at the human's turn rate**: make the bot hold ~145°/s (or bound its radius to
  ~354 qu) and measure whether it reaches the human's ~880 speed band while sustaining
  it (no wall-hit resets). That resolves:
  - **H1** — a bounded carve reaches ~880 → mastery is a *radius-control* fix (small, cvar-level).
  - **H2** — even a bounded carve plateaus well below 880 → there is a real accel/technique
    deficit (jump timing, ground-contact handling, strafe angle), to fix first.

## Bot↔human comparison (headline numbers)

| metric | human trick5 | bot 60 s | bot 180 s |
|---|---:|---:|---:|
| p50 hspeed (qu/s) | 880 | 535 | 292 |
| peak/max (qu/s) | 1088 | 656 | 598 |
| carve radius | bounded ≈354 qu | grows as v² | grows as v² |
| sustained? | yes (36 s) | until 1st wall | no — repeated resets |

Artifacts: `fingerprint-human-trick5.{json,md}` (this folder).
