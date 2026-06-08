# Mode 14 v3 (smooth center-orbit) + the circle-radius ceiling — trick.bsp, 2026-06-08

v3 replaced v2's jerky reactive wall-follow with a **smooth-by-construction center orbit**:
the base heading is the tangent to a circle of radius R about a center C (seeded from the human
trick5 centroid (2523,−2554)), gently biased to hold R. The carve (around velocity, sign steers
toward the base) is unchanged from v2.

## Progression (the smoothness lever, confirmed)

| controller | sustained hspeed | peak | note |
|---|---:|---:|---|
| v1 (carve around base, wall-follow) | ~350 | 666 | perimeter-hug |
| v2 (carve around velocity, wall-follow, gentle) | ~440 | 469 | jerky direction |
| **v3 (carve around velocity, smooth center-orbit)** | **~540** | 596 | **smooth, stable orbit** |
| human trick5 | ~880 | 1088 | figure-8 |

Each smoothness improvement raised the sustained speed. v3 holds a clean, stable ~540.

## The ceiling is now exact: a single circle caps at ~548 here

QW air-strafe turn rate is capped: `ω_max ≈ 300/v` rad/s (the air-accel adds ~`sv_accel·30·dt`
perpendicular per frame). To hold a circle of radius R at speed v you need `ω = v/R ≤ ω_max`, i.e.

  **R ≥ v² / 300.**

The trick.bsp room gives a usable radius ~1000 qu, so the **maximum speed of any single circular
orbit is `v = √(300·1000) ≈ 548 qu/s`.** v3 hit **540** — essentially the physical limit. Reaching
880 would need `R ≥ 880²/300 = 2581 qu`, far larger than the room → **impossible as one circle.**

This unifies the whole arc:
- mode 13's one-way circle let R grow as v² and **spiralled into walls at ~600**.
- v3's bounded circle **caps at the room's circle limit (~540)**.
- the human's net rotation is only ~0.5 turns — a **figure-8**, not a circle: near-straight
  high-speed runs (R→∞, no turn-rate limit) joined by turns, so speed peaks at 1088 on the
  straights and only the turns pay the curvature cost.
- replay reached 880 because it replays that figure-8.

## Conclusion / next form

**No orbit reaches 880 in this room; the human's figure-8 (straight runs + end turns) is
required.** v3 is the best *circle* possible and sits at its physical limit. The final
direction-layer form is a **straight-run / back-and-forth (figure-8)**: hold a near-straight
heading to build speed, turn ~180° (or cross into the other lobe) when approaching the box edge,
repeat. That keeps the high-speed segments straight (no turn-rate cap) while staying confined —
the only path from ~540 to the ~880 band, and it matches the validated human path shape.

Demos: `tricks/dm3/trick14v3_*__*.mvd`.
