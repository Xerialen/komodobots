# Mode 16 (curling air-strafe + center-hold) — confined AND accelerating — trick.bsp, 2026-06-08

The synthesis of the confirmed physics (`PHYSICS-confirmed-air-accel.md`) + the user's expert
model. ACCEL = mode 13's proven one-way carve (wishdir at `acos(K/|v|)` off velocity, K=26).
CONFINEMENT (the missing layer): when the bot drifts past `max_radius` from the room center, or a
forward traceline sees a wall, flip the curl direction toward the center, with a **long cooldown**
(1.2 s) so it does long arcs — not the per-hop pump / wall-chatter that killed mode 15.

## Result (run 20260608T074435Z, single bot, 45 s)

| signal | mode 13 | mode 15 (best) | **mode 16** | human |
|---|---:|---:|---:|---:|
| confined? (bbox) | NO (spiralled to wall) | NO (2016, hit walls) | **YES — 1748×2016** | 1749×1788 |
| builds continuously? | yes → 656 then wall | bursts then crash to ~50 | **yes → 594, recovers** | yes → 1088 |
| P95 / max hspeed | — / 656 | 482 / 657 | **547 / 594** | 1058 / 1088 |
| >400 qu/s | — | 31% | **47%** | — |

**First controller that is both confined and accelerating.** Speed climbs steadily within each arc
(e.g. t24→33: 419→594), dips at each center-reaim flip, then **rebuilds higher** — recoveries, not
mode-15's catastrophic crashes. The path is **big confined loops filling the room**, the same
shape class as the human's tangled figure-8, inside a box (1748×2016) ≈ the human's (1749×1788).

## What's left (594 → 880)
The accel is solved and confinement works; the gap is now **flip cost**: each center-reaim is a
hard curl reversal that bleeds ~150–380 qu/s (the dips). Two levers, both cvar-only (no rebuild):
- **`numerator` 26 → 15.** The true speed-gain optimum is `K=15` (maximise `(30−K)·K/v`), not 26.
  Mode 13/16 used 26 → sub-optimal accel. K=15 is more perpendicular = faster build.
- **Fewer/gentler flips:** raise `max_radius` (640 → ~750) and `flip_cooldown` (1.2 → ~2 s) so arcs
  are longer and re-aims rarer; later, replace the hard reversal with a gentler continuous
  center-bias to bleed less speed (small rebuild).

Apparatus: `bot_movement.c` mode 16 (`k_fb_moveprobe_curl_*` cvars). Deployed `qwprogs-curl.so`,
server restored to stock after the run.
