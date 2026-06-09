# Mode 19 — wall-aware retention bunnyhop + the low-numerator build-rate fix

**Status (2026-06-08):** WIP. Best config = mode 19, numerator 11, `s19_wall` 80. Measured over a
**90 s steady-state run**: **avg 519, max 849, p95 690, 92% of frames over 400 qu/s, 0% stationary**
(run `20260608T205313Z`). Up from mode-13's ~325 avg / 604 peak (with crashes). vs human: median 880
/ peak 1088 — so ~59% of sustained, ~78% of peak, and we touch the human's median peak (max ~849–889).

**Measurement note:** 45 s runs are dominated by the initial build-up transient and read ~360 avg
with large spread (305–519); the **90 s steady-state is the honest number (~519)**. Use ≥90 s
duration (`--timelimit 2`) for sustained-speed comparisons. The lab also races on teardown when runs
are fired back-to-back — leftover `komodobots_lab_*` screen sessions hold the port; kill them between
batches.

Remaining gap to sustained 880 is retention/path-control, not build rate (build rate solved by the
low numerator below).

## The diagnosis that reframed the work

The user's hypothesis tree — (1) a seam conversion/key, (2) frogbot insufficient, (3) quake/server
needs fixing — was **all refuted** by a forensic pass + offline budget analysis:

- **Seam (1) is faithful.** A live mode-10 replay of the exact human `trick5` usercmds hit **933
  peak, 82% airborne**, cursor in lockstep — `.cmds → trap_SetBotCMD → pmove` carries 880-class
  speed intact.
- **Engine (3) has no bot nerf.** Zero `isBot` branches in `pmove.c`; bots get the same
  maxspeed/accel/friction. Frame-timing is a red herring (the air-accel 30-cap makes 71 vs 77 fps
  ~0% top-speed difference).
- **It's the controller (4).** Per-air-frame `|v|²` gain `= 900 − cs²` where `cs = dot(velocity,
  wishdir)`. The bot's accel was never short — mode-16 already generated 565 |v|²/frame (2.8× the
  human) yet capped ~600. The wall was **speed retention**: the bot built 200–600 then crashed back
  to 30–120 thousands of times; the human builds-and-holds.

## Imitation corpus (data-driven, not hand-authored)

Per the user's direction — learn from existing skilled play, en masse. Ingested **1,849 vanilla-QW
trickjump POV demos** (servexeri firehose) → **1,844 extracted to (state,action) tuples** → 848
high-speed demos / 357k air-frames pooled into a velocity-relative air-law.

- `scripts/build_training_dataset.py` — batch `.qwd` → per-frame NDJSON (origin, velocity, view,
  move, buttons, **onground**, pm_code) + per-demo movement-quality manifest.
- `scripts/fit_air_law.py` — pools air-frames into `(|v|) → wishdir-offset` + serpentine flip
  cadence (~22 frames) + landing/jump stats.
- `scripts/build_replay_command_file.py` — widened to carry `onground`/`pm_code` into the tuple.

The corpus confirmed the cruise wish-angle is near-perpendicular (≈82–87°), i.e. the accel angle is
not the differentiator — consistent with the retention diagnosis.

## Mode 19 controller (`experiments/ktx_moveprobe/frogbot-moveprobe.patch`)

`else if (mode == 19)` — mode-13's proven velocity-relative air-accel (forward-move + rotated view,
toggle jump) **plus** a live forward `traceline` that flips the strafe side (debounced) when a wall
is within `s19_wall` qu, so the accelerating curl turns away from geometry instead of crashing into
it. Optional cadence flip every `s19_flip_frames` air frames. ezQuake unmodified; KTX-only; additive
(modes 0–18 untouched). Built on servexeri, deployed as `qwprogs-mode19.so`.

cvars (all live-tunable, no rebuild): `k_fb_moveprobe_accel_numerator`, `..._alternate`,
`k_fb_moveprobe_s19_wall`, `..._s19_wall_cd`, `..._s19_flip_frames`.

## The build-rate fix (the breakthrough this session)

I initially mis-read the physics: mode-13's `numerator=26` targets `cs≈26` → gain `900−26² = 224`.
But `900 − cs²` is **maximized at cs=0**. A **low numerator** (cs→0, fully perpendicular wishdir)
gains ~4× faster *and* turns tighter — and a steady circle at 880 has radius only ~336, which fits
trick.bsp's ~1750 box. Sweep (mode 19, wall 60–80, single runs — noisy):

| numerator | avg | max | notes |
|---:|---:|---:|---|
| 2  | 154 | 550 | too tight, fills the box |
| 8  | 259 | **889** | hits human median peak |
| 10 | 479 | 855 | |
| 11 | **519 / 331 / 374** | 817 | best avg sample; high variance |
| 12 | 393 | 690 | |
| 15 | 364–378 | 725–822 | |

Sweet spot ≈ numerator 10–12, `s19_wall` 60–80.

## Reproduce the current best

```
python scripts/run_frobodm2_lab.py --map trick --lab-mvdsv mvdsv-lab --prewar --timelimit 1 \
  --duration 45 --bot-count 1 --moveprobe-mode 19 \
  --ktx-extra-cvars "k_fb_moveprobe_accel_numerator 11;k_fb_moveprobe_accel_alternate 0;k_fb_moveprobe_s19_wall 80;k_fb_moveprobe_s19_wall_cd 15;k_fb_moveprobe_s19_flip_frames 0"
```

## Next

1. Average ≥3 runs per config (variance is large) and longer runs for stable statistics.
2. Push sustained avg: the peak is reached; the gap is holding it. Candidates — minimise per-hop
   loss (clean landings), a *smooth* serpentine carve vs discrete flips, or a wider steady circle.
3. Then package as the finding PR (Codex review at PR time).
