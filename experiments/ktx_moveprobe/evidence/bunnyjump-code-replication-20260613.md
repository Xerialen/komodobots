# Bunnyjump Code Replication Guide - 2026-06-13

Purpose: give a cold subagent enough information to reproduce the accepted
ztricks bunnyjump baseline without reading the whole chat history.

This is a practical baseline, not a strict "beats the human demo" claim. The
accepted run looks good live and preserves the important mouse shape, but the
strict scorer still reports `FAIL` because the human reference sustains
`>900 qu/s` longer.

## The Code

The code we cracked is not one speed parameter. It is the synchronization rule:

```text
preserve the human QWD mouse timeline
+ preserve human jump timing
+ preserve human side-switch timing
+ add speed only through phase-gated side-command strength
+ never let replay restarts or mixed attempts pollute the evidence
```

The controller that currently expresses this rule is moveprobe mode `25`.
Mode `25` replays the recorded QWD view angles and clock from
`getandmaintainspeed.qwd`. Its best accepted profile uses the human side input
sign after replay cursor `1500`, but replaces the side magnitude with `950`.
That keeps the smooth left/right mouse and strafe rhythm while giving the bot
enough command strength to maintain a believable high-speed run.

Use these tracked reference artifacts:

- QWD segmentation/interpolation procedure:
  `experiments/ktx_moveprobe/evidence/qwd-segmentation-interpolation-procedure-20260613.md`
- Human command file:
  `experiments/ktx_moveprobe/evidence/getandmaintainspeed-reference/getandmaintainspeed.cmds`
- Human mouse/speed analysis:
  `experiments/ktx_moveprobe/evidence/getandmaintainspeed-reference/mouse-analysis.json`
- Human analysis notes:
  `experiments/ktx_moveprobe/evidence/getandmaintainspeed-reference/mouse-analysis.md`
- Accepted baseline snapshot:
  `experiments/ktx_moveprobe/evidence/getandmaintainspeed-accepted-baseline-20260613.md`
- Accepted run artifacts:
  `artifacts/lab-runs/gm25_clocktol1500m950_0420/`

The raw local analysis artifacts still live under ignored `artifacts/`, but the
three files required for reproduction are committed in the tracked reference
directory above. A clean checkout should use the tracked paths.

Human reference metrics from `getandmaintainspeed.qwd`:

| metric | value |
|---|---:|
| paired command/state frames | `2541` |
| analyzed duration | `32.987s` |
| avg speed | `666.1 qu/s` |
| p50 / p95 / max speed | `720.8 / 924.4 / 948.5 qu/s` |
| time above `700` | `18.507s` |
| time above `900` | `6.377s` |
| yaw p50 / p95 rate | `132.7 / 244.8 deg/s` |
| yaw reversals | `43` (`1.3/s`) |
| side-only input | `84.8%` |
| jump button | `74.0%` |
| side plus mouse coupling | `95.1%` opposite-sign |

These numbers explain why raw speed is not enough. The bot must keep a smooth
human mouse pattern, not produce high speed through spammy yaw snapping.

## Cold-Start Reproduction

Run from the repo root on Windows PowerShell.

Use a unique run id if repeating the experiment. Do not overwrite
`gm25_clocktol1500m950_0420`; it is the frozen accepted baseline.

```powershell
$run = "gm25_repro_$(Get-Date -Format yyyyMMddTHHmmss)"
$reference = 'experiments\ktx_moveprobe\evidence\getandmaintainspeed-reference'
$cvars = 'k_fb_moveprobe_replay_stale_gap 120;k_fb_moveprobe_replay_one_shot 1;k_fb_moveprobe_s25_min_speed 700;k_fb_moveprobe_s25_gap 20;k_fb_moveprobe_s25_numerator 8;k_fb_moveprobe_s25_move 400;k_fb_moveprobe_s25_phase_start 1500;k_fb_moveprobe_s25_phase_target 850;k_fb_moveprobe_s25_phase_min_speed 320;k_fb_moveprobe_s25_phase_move 950;k_fb_moveprobe_s25_phase_human_cmd 1'

python scripts\run_frobodm2_lab.py `
  --map ztricks `
  --run-id $run `
  --duration 45 `
  --bot-count 1 `
  --bot-spacing 0 `
  --moveprobe-mode 25 `
  --replay-cmds "$reference\getandmaintainspeed.cmds" `
  --moveprobe-log-commands `
  --moveprobe-log-interval 0 `
  --ktx-extra-cvars $cvars

python scripts\score_getandmaintainspeed.py `
  --run-id $run `
  --reference "$reference\mouse-analysis.json"
```

Active deployed KTX binary for the accepted baseline:

```text
~/nquakesv/ktx/qwprogs.so -> /home/xerial/nquakesv/ktx/qwprogs-s25clocktol-20260612T2207Z.so
sha256 83b0b75297cd81a5b0c29d1e747eec434a703ca00dd430152689eca3176463fe
```

If the active server binary differs, either restore that build or explicitly
record the new binary path and SHA before comparing results.

## Cvar Contract

| cvar | value | why it matters |
|---|---:|---|
| `k_fb_moveprobe_replay_stale_gap` | `120` | Prevents ordinary command gaps from silently restarting replay cursor `0`. |
| `k_fb_moveprobe_replay_one_shot` | `1` | Keeps a completed/dead benchmark from falling back into stock Frogbot movement. |
| `k_fb_moveprobe_s25_min_speed` | `700` | Global catch-up only engages once live speed is already meaningful. |
| `k_fb_moveprobe_s25_gap` | `20` | Human frame must lead live speed before catch-up changes movement. |
| `k_fb_moveprobe_s25_numerator` | `8` | Velocity-relative air-strafe numerator for the global catch-up branch. |
| `k_fb_moveprobe_s25_move` | `400` | Base catch-up command magnitude before phase recovery. |
| `k_fb_moveprobe_s25_phase_start` | `1500` | Do not take over too early; cursor `1450` was worse and `1600` was too late. |
| `k_fb_moveprobe_s25_phase_target` | `850` | Phase recovery only matters when the human frame is in the high-speed region. |
| `k_fb_moveprobe_s25_phase_min_speed` | `320` | Lets phase recovery help after speed drops, but avoids zero-speed nonsense. |
| `k_fb_moveprobe_s25_phase_move` | `950` | The best accepted side-command strength. `960+` was on the physics cliff. |
| `k_fb_moveprobe_s25_phase_human_cmd` | `1` | Keep human side sign and mouse timing; replace only side magnitude. |

Leave these cvars off unless deliberately running a new probe:

- `k_fb_moveprobe_s25_path_div`
- `k_fb_moveprobe_s25_path_blend`
- `k_fb_moveprobe_s25_velsign`
- `k_fb_moveprobe_s25_phase2_start`
- `k_fb_moveprobe_s25_phase2_move`
- `k_fb_moveprobe_s25_phase_jump`
- `k_fb_moveprobe_s25_phase_gap_gain`
- `k_fb_moveprobe_s25_phase_move_max`
- `k_fb_moveprobe_s25_phase_yaw_offset`
- `k_fb_moveprobe_s25_phase_human_scale`
- `k_fb_moveprobe_s25_phase_lane_nudge`

Rejected probes matter. They prevent the next agent from repeating mistakes:

- Holding jump during the phase broke the recorded rhythm.
- Yaw offsets `+5` and `-5` were worse than the unshifted human mouse.
- Scaling exact human commands by `2.375` preserved too many low/zero frames.
- Adaptive phase gap boost was worse than fixed `950`.
- Late `phase2` movement after cursor `2044` did not improve sustain.
- Path blend and velocity-sign selection hurt this ztricks reference.

## Expected Evidence

A successful reproduction produces a clean one-shot replay, not a perfect
strict-score pass.

Hard replay checks:

- `moveprobe-replay-events.md` shows exactly one `activate` and one `complete`.
- `frameCount` is `2541`.
- `maxCursor` and `finalCursor` are `2540`.
- Final horizontal divergence is near the accepted baseline; `<=100 qu` is a
  practical sanity limit.
- `run-summary.md` shows one bot on `ztricks`, moveprobe mode `25`, command
  logging enabled, and the lab session stopped cleanly.

Accepted baseline numbers from `gm25_clocktol1500m950_0420`:

| metric | value |
|---|---:|
| movement avg | `466.6 qu/s` |
| movement p95 | `873.6 qu/s` |
| movement max | `917.6 qu/s` |
| air proxy | `65.6%` |
| cadence | `59.9/min` |
| event time `>900` | `0.240s` |
| command yaw p95 | `280.0 deg/s` |
| command yaw reversals/s | `1.10` |

Strict scorer expectation:

- `event_p95_beats_human`: likely `FAIL`
- `event_max_beats_human`: likely `FAIL`
- `event_high_time_beats_human`: likely `FAIL`
- `command_high_time_beats_human`: likely `FAIL`
- `mouse_yaw_p95_within_20pct`: should `PASS`
- `mouse_reversal_rate_within_50pct`: should `PASS`

That is intentional. This profile is the accepted visual/operational baseline.
Future strict improvement work must beat `scripts/score_getandmaintainspeed.py`
without overwriting the baseline.

## Troubleshooting

If the bot only jumps in place or barely moves:

- Confirm `--moveprobe-mode 25` is present.
- Confirm `--replay-cmds experiments\ktx_moveprobe\evidence\getandmaintainspeed-reference\getandmaintainspeed.cmds`
  exists and is uploaded by the runner.
- Open the run's `lab.cfg` and verify all cvars from the contract appear.
- Check `moveprobe-commands.json` for `s25_state`; no `s25_state` means mode 25
  did not run.

If replay activates more than once:

- `k_fb_moveprobe_replay_stale_gap` is missing or too low.
- `k_fb_moveprobe_replay_one_shot` is missing.
- The run is mixed evidence; do not compare it to the accepted baseline.

If the strict scorer fails:

- Do not immediately tune. A strict `FAIL` is expected for this baseline.
- First verify the two mouse-shape checks pass.
- Then compare p95/max/event-time to the accepted baseline, not directly to the
  human target.

If yaw looks spammy:

- Do not switch to path steering or controller-generated yaw.
- The reference finding is that human mouse movement is the primary signal.
  Losing the QWD yaw/pitch timeline invalidates this baseline.

## Validation Commands

These commands validate the static contracts and the frozen accepted run without
starting a new live server:

```powershell
python -m unittest tests.test_score_getandmaintainspeed tests.test_perslot_moveprobe_patch -v

python -c "import sys; from pathlib import Path; sys.path.insert(0, 'scripts'); from score_getandmaintainspeed import score_run; r = score_run(Path('artifacts/lab-runs/gm25_clocktol1500m950_0420'), reference_path=Path('experiments/ktx_moveprobe/evidence/getandmaintainspeed-reference/mouse-analysis.json')); print(r['run_id'], r['verdict'], r['checks'])"
```

Use the live reproduction command only when you need a new MVD.

## Transfer Rule

For future route work, copy the principle before copying the numbers:

1. Extract exact QWD commands and paired trajectory using the segmentation and
   interpolation procedure documented beside this guide.
2. Preserve the QWD mouse timeline unless there is hard evidence it is wrong.
3. Preserve human jump timing before trying any autojump or jump-hold probe.
4. Add controller strength only inside a phase gate tied to replay cursor or
   route state.
5. Score both movement output and mouse shape.
6. Record the accepted profile as evidence, then branch future tuning away from
   it.

This is the reusable bunnyjump code.
