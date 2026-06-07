# Closed-loop movement on dm3_sng_to_rl (2026-06-07)

Three KTX moveprobe variants on the `dm3_sng_to_rl` trick, each snapped to the human
frame-0 state and scored on the identical divergence trace (bot origin vs human origin
at the same replay time index). 1 bot, dm3, same `dm3_sng_to_rl.cmds` (692 frames,
coverage 1.0). Headline metric: cursor at which horizontal divergence (divH) first
exceeds 32 qu (the believable-corridor length).

Approach selected by the `movement-approach-panel` judge panel (6 candidate movement
brains, 2 judges each, all source-verified): hybrid/corrective controllers ranked top,
from-scratch brain mid (heaviest build, scoped later).

| Arm | mode | run_id | divH crosses 32 | maxH (qu) | maxV (qu) | max3D (qu) | full stream | corr budget |
|---|---|---|---|---|---|---|---|---|
| open-loop replay | 10 | 20260607T151125Z | cursor 255 | 1065.9 | 203.5 | 1071.7 | 691/691 ✓ | — |
| closed-loop steering | 11 | 20260607T164852Z | cursor 24 | 1348.5 | 143.9 | 1355.8 | 600/691 (left route) | — |
| **corrective replay** | 12 | 20260607T170056Z | **cursor 381** | **196.1** | 208.8 | 286.5 | 691/691 ✓ | yaw ≤3°/frame (max 3.00, Σ 1154°) |

Params: m11 `lookahead_frames=4`; m12 `corr_deadband=16 qu`, `corr_yaw_max=3 deg/frame`.

## Interpretation

- **Open-loop (m10)** reproduces a real lockstep prefix — a ring→YA trick jump with the
  Frogbot brain off — to cursor 255, then diverges catastrophically at the strafe-jump
  (runaway to 1066 qu) because it has no feedback.
- **Steering (m11)** is dramatically worse: it discards the human usercmd and re-aims from
  the bot's actual origin, collapsing the corridor to cursor 24. This proves the human's
  exact per-frame input is load-bearing in the prefix — a steering heuristic with generic
  strafe magnitudes cannot replace it.
- **Corrective replay (m12)** keeps the exact human usercmd and adds only a yaw nudge
  clamped to 3°/frame once divH exceeds a 16 qu deadband. It extends the corridor through
  the strafe-jump (255→381, +50%), bounds worst-case divergence 5.4× (1066→196 qu), and
  replays the full stream. Because the correction is a yaw nudge (it never writes
  origin/velocity), the 196 qu is a genuine trajectory, not metric masking.

**Conclusion:** closed-loop CORRECTION (not steering, not from-scratch) is the validated
direction for believable bunnyjump movement. The from-scratch movement brain stays shelved.

## Evidence

- Run artifacts (gitignored): `artifacts/lab-runs/{20260607T151125Z,20260607T164852Z,20260607T170056Z}/`.
- Recorded demos (committed + nQuake mirror): `tricks/dm3/dm3_sng_to_rl__{...}.mvd`.
- KTX modes 10/11/12: `experiments/ktx_moveprobe/frogbot-moveprobe.patch` (`BotApplyMoveProbeReplay`, `replay_variant` 0/1/2).
- Machine-readable: `closed-loop-dm3-sng-to-rl-20260607.json` (this directory).

## Follow-up

Sweep m12 (`deadband {8,16,32}` × `yaw_max {2,3,5}`) and replicate on a second dm3 trick
to confirm the corridor extension generalizes; `corr_max` saturated at the 3° clamp, so a
higher `yaw_max` may track further at some believability cost. Ocular-review the m12 demo.
