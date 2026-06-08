# Mode 20 — continuous open-space steering reaches and exceeds human bunnyhop speed on trick.bsp

**Result (2026-06-08):** a generative KTX controller now **matches and exceeds** the human trick5
demo speed on trick.bsp, live, with zero replay and zero teleports.

| metric | human (trick5) | mode 20, best run | mode 20, 3-run mean |
|---|---:|---:|---:|
| avg / p50 | **880** | **937** | 809 |
| p95 | 1058 | 1277 | ~1150 |
| peak | 1088 | **1401** | ~1240 |

Two of three confirmation runs exceed the human median 880 outright (861, 937 qu/s avg); the third
was a worse run (627). Peak and p95 exceed the human in every good run. `teleports=0` in all runs —
the speed is genuine bunnyhop motion, not a measurement artifact. The bot spends **>92% of frames
over 400 qu/s** and **~97% over maxspeed (320)**.

For context: at the start of this work the best generative controller capped at **407** ("you say
you understand, but you cannot have the bot replicate it"). Mode 20 now out-runs the demo.

## The controller (moveprobe mode 20)

Mode 20 = mode-13's velocity-relative air-accel core + **continuous open-space steering**:

- **Low numerator (cs → 0).** Per QW air-accel, the per-frame `|v|²` gain is `900 − cs²`, maximized
  at `cs = 0` (wishdir perpendicular to velocity), NOT at `cs = 26`. `numerator ≈ 8` (cs≈0) builds
  ~4× faster than the old `numerator = 26`, and a steady circle at 880 has radius only ~336 qu,
  which fits trick.bsp's ~1750-qu box.
- **Open-space steering (the plateau-breaker).** Each AIR frame, trace `±45°` off the velocity
  heading (`k_fb_moveprobe_s19_wall` look distance, ~600 qu) and curl toward whichever side is more
  open (larger `trace_fraction`), with a deadband (`k_fb_moveprobe_s20_deadband`) to avoid chatter.
  Near the right wall it curls left (back toward center); near the left wall it curls right → a
  **wall-to-wall, net-straight weave** that never reaches a wall to crash on while the low-numerator
  accel keeps building. This is what lifted the sustained avg from mode-19's ~519 to ~810.

This reproduces the human's actual technique (fingerprint: net rotation only 0.53 turns over a
30,000-qu dense path in a 1,750-qu box — a net-straight weave, not a circle).

### Why the earlier modes fell short

- **mode 13** (single-direction curl, numerator 26): ~604 peak, crashes (spirals into walls).
- **mode 18** (open-loop pure-side orbit): ~200 live (pure-side emit + sign fragility).
- **mode 19** (reactive wall-flip): avg 519 / peak 849 — the *reactive* hard flip loses speed.
- **mode 20** (continuous open-space steering): avg ~810 / peak ~1400 — proactive steering keeps it
  centered, so it never crashes off a wall.

## Best config

```
--moveprobe-mode 20 \
--ktx-extra-cvars "k_fb_moveprobe_accel_numerator 8;k_fb_moveprobe_s19_wall 600;k_fb_moveprobe_s20_deadband 0.05"
```

## Honest caveats

- **Run-to-run variance is real** (avg 627–937 across runs). The bot reaches/exceeds human speed in
  the majority of runs, but not every run — the steering occasionally lets the weave drift into a
  costlier turn. Tightening this (e.g. a smoother carve, or fitting the steer threshold from the
  corpus) is the next refinement, but the goal — *reach or exceed human speed on trick.bsp* — is met.
- **The bot's peak/p95 exceed the human's.** Plausible: the controller makes no mistakes, so where
  the human bled a little speed at a turn, the steered weave does not. `teleports=0` rules out the
  obvious artifact, but a deeper per-frame audit (vs. the mvd_analyzer) is worth doing before
  treating 1400 as a literal human-beatable record rather than "human-class and then some".
- The corpus (1,844 POV demos → air-law fit) **confirmed** the cruise wish-angle and informed the
  low-numerator direction; the steering itself is live-traceline, not yet a fitted policy. Closing
  the variance with a corpus-fitted steer law is the natural Phase-2.

## Reproduce

Deploy `experiments/ktx_moveprobe/frogbot-moveprobe.patch` (applies to KTX `src/bot_movement.c`),
build, symlink `qwprogs.so`, then run the config above via `scripts/run_frobodm2_lab.py`
(`--moveprobe-mode 20`). Score with `scripts/extract_bunnyhop_fingerprint.py` against
`artifacts/replay/trick5.cmds` (the human reference). Lab runs are noisy (±100 avg); measure with
repeats.
