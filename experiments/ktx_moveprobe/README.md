# KTX Frogbot Movement Probe

Status: S2 experiment scaffold.

## Purpose

Prove that Frogbot movement commands can be overridden at the final command-emission point without replacing the KTX/MVDSV lab loop.

The patch in this directory is deliberately crude. It is not a bunnyjump controller and should not be promoted as movement AI.

## Patch

Apply `frogbot-moveprobe.patch` to a KTX checkout at commit `08807da` or an equivalent source tree:

```bash
cd ~/nquakesv/build/ktx
git apply /path/to/frogbot-moveprobe.patch
cmake --build build
```

The patch adds `k_fb_moveprobe_mode` handling inside `BotSetCommand()` after the prewar-freeze guard and immediately before button assembly and `trap_SetBotCMD(...)`.

It can also emit sampled command rows with the exact values about to be handed to `trap_SetBotCMD(...)`:

```text
FBMOVEPROBE_CMD time=12.250 ed=3 name=/ goldenboy mode=2 msec=13 angles=0.0,90.0,0.0 move=800,0,0 buttons=2 impulse=0
```

Those rows are deliberately console-oriented, temporary probe output. They exist to compare stock, forced-jump, and fixed-command runs before building a real movement controller.

Modes:

| Mode | Meaning |
|---:|---|
| `0` | Off. Stock Frogbot command emission. |
| `1` | Force the jump button while preserving existing Frogbot movement direction and combat. |
| `2` | Replace the final movement command with fixed yaw/forward/sidemove/upmove values and force jump while leaving firing and weapon selection intact. |

Mode `2` cvars:

| Cvar | Default in runner | Meaning |
|---|---:|---|
| `k_fb_moveprobe_yaw` | `0` | Bot view yaw used for the fixed command. |
| `k_fb_moveprobe_forwardmove` | `800` | Forward command sent to `trap_SetBotCMD`. |
| `k_fb_moveprobe_sidemove` | `0` | Side command sent to `trap_SetBotCMD`. |
| `k_fb_moveprobe_upmove` | `0` | Up command sent to `trap_SetBotCMD`. |
| `k_fb_moveprobe_log_commands` | `0` | When `1`, print sampled final command rows before `trap_SetBotCMD`. |
| `k_fb_moveprobe_log_interval` | `0.25` | Minimum seconds between command log samples per bot. Use `0` for every command. |

## Runner

The lab runner can now write the cvars into the generated KTX config:

```bash
python scripts/run_bot_lab.py --map frobodm2 --duration 40 --bot-count 2 --moveprobe-mode 1
python scripts/run_bot_lab.py --map frobodm2 --duration 40 --bot-count 2 --moveprobe-mode 2 --moveprobe-yaw 90
python scripts/run_bot_lab.py --map frobodm2 --duration 20 --bot-count 2 --moveprobe-mode 0 --moveprobe-log-commands
```

Each run records the mode and command values in `run.env`, `lab.cfg`, and `run-summary.md`.

When command logging is enabled, the runner parses `screen.log` and writes:

- `moveprobe-commands.json`
- `moveprobe-commands.md`

The S2 v2a comparison is three short runs with `--moveprobe-log-commands`: stock mode `0`, forced-jump mode `1`, and fixed-command mode `2`. The comparison verifies final `msec`, view angles, movement command values, buttons, and impulses before any controller work continues.

Known v2a comparison runs:

| Run ID | Mode | Result |
|---|---:|---|
| `20260605T222006Z` | `0` | Stock variable commands logged; movement remained plausible. |
| `20260605T222047Z` | `1` | Variable movement preserved; final buttons included jump. |
| `20260605T222129Z` | `2` | Constant `yaw=90 forward=800 side=0 up=0 buttons=2`; movement collapsed. |

## Rollback

This is an experiment patch. After running it against `servexeri`, restore the deployed `qwprogs.so` from the backup made before copying the patched build, and reset or reverse-apply the source checkout patch.
