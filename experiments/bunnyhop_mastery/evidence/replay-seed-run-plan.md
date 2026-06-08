# Replay-seed (mode 12) first live run — recipe (2026-06-08)

First mastery experiment, per user direction. **Goal:** prove a sustained ~880, confined
multi-loop bunnyhop is reproducible on trick.bsp by replaying the human trick5 stream with
bounded per-frame correction — i.e. borrow the human's varying-curvature technique wholesale
rather than derive an (impossible-by-air-physics) constant-angle controller.

No new KTX code: **mode 12 (corrective replay) already exists** (`bot_movement.c:1575`,
`BotApplyMoveProbeReplay(..., 2)`); the controller is the existing moveprobe patch.

## Precondition — SATISFIED
trick5 was recorded on **trick.bsp** (docs/07_FINDINGS_LOG.md:3447; `trick.bot` was generated
from trick5's trajectory). Same map we test on; mode-10/11/12 snap the bot to the human frame0
origin `[2560,-3136,-488]`, so spawn alignment is handled. (`replay-build-trick5.json` has an
empty `map_level`, but the demo + docs confirm the map — worth re-stamping the build later.)

## Deploy (serial, user-gated — shared server)
1. On servexeri: apply `experiments/ktx_moveprobe/frogbot-moveprobe.patch` to the KTX checkout,
   `cmake --build` → `qwprogs.so` (the patched build with modes 10–13).
2. Back up the live `qwprogs.so`, repoint the symlink to the patched build.
3. Run the batch below (lab port 28599; production 28501–3 untouched).
4. **Restore stock** (`qwprogs.so → qwprogs-1.48-dev-08807d.so`), verify clean.

## Batch (single bot, --map trick, --prewar --lab-mvdsv mvdsv-lab)

Baseline (establishes the open-loop divergence point on trick5):
```
python scripts/run_bot_lab.py --map trick --bot-count 1 --duration 42 \
  --moveprobe-mode 10 --replay-cmds artifacts/replay/trick5.cmds \
  --moveprobe-log-commands --prewar --lab-mvdsv mvdsv-lab \
  --record-trick-name trick5_replay_ol
```

Corrective replay sweep (mode 12) — sweep deadband × yaw_max:
```
# deadband ∈ {8,16,32} qu, yaw_max ∈ {3,6,10} deg ; 9 cells, e.g.:
python scripts/run_bot_lab.py --map trick --bot-count 1 --duration 42 \
  --moveprobe-mode 12 --replay-cmds artifacts/replay/trick5.cmds \
  --moveprobe-corr-deadband 16 --moveprobe-corr-yaw-max 6 \
  --moveprobe-log-commands --prewar --lab-mvdsv mvdsv-lab \
  --record-trick-name trick5_replay_d16y6
```

## Scoring (per run)
1. **Replay fidelity:** `moveprobe-replay-events.json` + the `replay=` fields in the
   FBMOVEPROBE log → the cursor/divergence at which `div_h` first exceeds the player bbox
   (~32 qu). Headline: how many seconds past the open-loop baseline (~2.7 s on dm3; measure
   trick5's) mode 12 holds the carve.
2. **Speed + path shape:** build a `.cmds` from the bot's recorded MVD (or use the velocity
   log) and run `scripts/extract_bunnyhop_fingerprint.py` + `scripts/plot_path_ascii.py`.
   Compare to the human: p50 toward 880, peak toward 1088, **net rotation ≈ 0**, bbox ≈ 1750,
   straightness ≈ 0.02 (confined loops), cadence ≈ 85/min.

## Success / readout
- **PASS (mastery reproducible):** mode 12 sustains the confined ~880 loops for ≫ the
  open-loop baseline (target: most of the 36.8 s replay) with the bot's path-shape matching
  the human (net rotation ~0, bbox ~1750) — proving the technique is reproducible on this map.
- **PARTIAL:** correction extends the lockstep window materially but still diverges before the
  end → tune deadband/yaw_max, or escalate to a stronger closed-loop term.
- **Informs next pillar:** once replay proves the target is reachable, the open question
  becomes whether a *generative* controller (not tied to one recorded run) can produce the
  same confined-loop pattern — the point at which the imitation-policy option re-enters.
