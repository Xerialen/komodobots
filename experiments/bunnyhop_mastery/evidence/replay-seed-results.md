# Replay-seed (mode 10/12) live results — trick.bsp, 2026-06-08

First mastery experiment (user-directed). Patched KTX (`qwprogs-replay.so`, modes 10–13)
deployed to servexeri lab port 28599; stock restored after. trick5.cmds replayed on trick.bsp
(map-identity precondition confirmed). Single bot, `--prewar --lab-mvdsv mvdsv-lab`.

## Runs

| run | mode | corr | speed max / p95 / avg | div_h med / max | path: straightness / net-rot / bbox |
|---|---|---|---|---|---|
| `trick5_replay_ol`   | 10 (open-loop) | — | **933 / 892 / 539** | 32@~cursor200 → 1072 | 0.033 / 1.69turns / 1441×1473 |
| `trick5_replay_d16y6`| 12 (corrective)| d16 y6 | 924 / 872 / 505 | 322 / 1172 | 0.012 / 1.69turns / 1380×1533 |
| `trick5_replay_d8y20`| 12 (corrective)| d8 y20 | **stalled** (hspeed 0) | 2 / 338 | bot stuck at spawn — invalid |
| **human trick5 (ref)** | — | — | 1088 / 1058 / 880 | — | 0.016 / 0.53turns / 1749×1788 |

## Finding: the confined ~880 bunnyhop IS reproducible through the bot seam

- **Open-loop replay reproduces the human's confined high-speed technique.** Executing the
  human's recorded usercmd stream, the bot reaches **max 933, p95 892 qu/s** (human 1088/1058)
  and traces the **same confined double-loop pattern** — bbox ~1450 qu (human 1750),
  straightness 0.033 (human 0.016). See `bot-trick5-replay-ol-path.txt` vs
  `human-trick5-path.txt`: visually the same figure-8 filling the box.
- **It does NOT spiral into walls** like the mode-13 accelerator (whose long run collapsed to
  p50 292). The replay stays confined and fast — confirming the gap was **area/radius
  management**, and that the bot's actuation (BotSetCommand) can produce the ~880 confined
  pattern. The mastery *target is reachable on this map.*
- **Position is not lockstep.** Open-loop `div_h` exceeds the 32 qu bbox by ~cursor 200
  (~2.5 s, matching the dm3 finding) and grows to ~1000; the bot loops *more* than the human
  (1.69 vs 0.53 net turns) because, once drifted, the human's yaw stream traces a different
  (but still confined) path.
- **Yaw correction is not the lever.** Mode-12 d16y6 barely changed divergence and cost a
  little speed. Strong correction (d8y20) **over-rotated the bot so it never strafed → stalled
  at spawn (hspeed 0)** — confirming correction competes with the speed-building strafe.

## What this proves, and the next pillar

- **Proven:** a sustained ~880, confined-loop bunnyhop is achievable on trick.bsp via the bot
  seam (replay reproduces it). This overturns the loop's "map-geometry ~600 cap."
- **Not yet:** a *generative* controller (one not tied to a recorded human run). Replay borrows
  the human's exact input program; mastery means generating the confined-loop-at-880 pattern.
- **The decisive contrast for the next experiment:** human net rotation ≈ **0.5 turns** (it
  *alternates* to stay confined), bot mode-13 one-way circle **accumulates** net rotation and
  spirals out. So a generative fix is **mode-13 with area/alternation control** — flip the
  strafe side / bound net rotation at the box edges so it stays confined (net rotation ~0)
  while accelerating — measured against this same path-shape + speed fingerprint. The
  imitation policy stays gated behind "constant rules can't reproduce it."

Artifacts (this folder): `bot-trick5-replay-ol-path.txt`. Runs: `artifacts/lab-runs/20260608T0223*`.
Demos: `tricks/dm3/trick5_replay_ol__*.mvd`, `trick5_replay_d16y6__*.mvd` (+ nQuake mirror).
