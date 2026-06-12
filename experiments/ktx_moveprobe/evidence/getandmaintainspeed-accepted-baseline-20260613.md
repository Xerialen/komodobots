# getandmaintainspeed accepted baseline - 2026-06-13 CEST

User verdict: the live bot behavior in `gm25_clocktol1500m950_0420` is more
than good enough as the current practical baseline.

This is deliberately not recorded as a strict numeric win. The strict scorer
still reports `FAIL` because the human reference sustains speed above `900`
qu/s much longer. The value of this run is that it looked operationally good in
the live lab and the replay harness finally produced one clean activation and
one clean completion without silently mixing multiple attempts into the same
MVD.

## Reproduction

```powershell
$cvars = 'k_fb_moveprobe_replay_stale_gap 120;k_fb_moveprobe_replay_one_shot 1;k_fb_moveprobe_s25_min_speed 700;k_fb_moveprobe_s25_gap 20;k_fb_moveprobe_s25_numerator 8;k_fb_moveprobe_s25_move 400;k_fb_moveprobe_s25_phase_start 1500;k_fb_moveprobe_s25_phase_target 850;k_fb_moveprobe_s25_phase_min_speed 320;k_fb_moveprobe_s25_phase_move 950;k_fb_moveprobe_s25_phase_human_cmd 1'
python scripts\run_frobodm2_lab.py --map ztricks --run-id gm25_clocktol1500m950_0420 --duration 45 --bot-count 1 --bot-spacing 0 --moveprobe-mode 25 --replay-cmds artifacts\qwd-getandmaintainspeed\getandmaintainspeed.cmds --moveprobe-log-commands --moveprobe-log-interval 0 --ktx-extra-cvars $cvars
python scripts\score_getandmaintainspeed.py --run-id gm25_clocktol1500m950_0420
```

Active deployed KTX binary:

- `~/nquakesv/ktx/qwprogs.so -> /home/xerial/nquakesv/ktx/qwprogs-s25clocktol-20260612T2207Z.so`
- SHA-256 `83b0b75297cd81a5b0c29d1e747eec434a703ca00dd430152689eca3176463fe`

## Clean Replay Evidence

| event | time | cursor | note |
|---|---:|---:|---|
| activate | `7.565s` | `0` | single replay activation |
| complete | `40.559s` | `2540` | single replay completion, final horizontal divergence `71.837` |

Attempt row:

```text
FBMOVEPROBE_ATTEMPT n=1 end=complete break_cursor=231 furthest_cursor=2540 frame_count=2541 maxH=808.5 final_maxH=808.5
```

## Strict Score

| metric | human | accepted run event | accepted run command |
|---|---:|---:|---:|
| p95 speed | `924.4` | `873.6` | `869.9` |
| max speed | `948.5` | `917.6` | `886.6` |
| time >900 | `6.377s` | `0.240s` | `0.000s` |
| yaw p95 | `244.8` |  | `280.0` |
| yaw reversals/s | `1.30` |  | `1.10` |

The mouse-shape checks are close enough to keep using this as a baseline, but
future strict claims must still beat the scorer rather than only looking good.

## Harness Fixes Captured

- `k_fb_moveprobe_replay_stale_gap` prevents ordinary replay command gaps from
  silently restarting from cursor `0`.
- `k_fb_moveprobe_replay_one_shot` keeps a completed/dead benchmark attempt
  complete instead of falling back into normal Frogbot movement.
- Replay clock reset now tolerates tiny backward jitter up to `0.25s`; larger
  backward jumps still reset the replay session.

## Next Smallest Useful Experiment

Leave this baseline intact. Future tuning should copy it to a new run/profile
and improve against `scripts/score_getandmaintainspeed.py`; do not overwrite the
accepted operational baseline just because a strict scorer probe is being
attempted.
