# Data and MVD Pipeline

Status: living document.

## Purpose

This document explains what data Komodobots expects to get from QuakeWorld demos, what it cannot get, and how bot-generated MVDs should be compared against human MVDs.

## Core principle

Use MVD-derived evidence to measure movement realism.

Do not rely on visual vibes alone.

## Important limitation

MVDs are server-side recordings of game state and events.

They generally do not provide normal player input/usercmd streams such as exact key presses, mouse deltas, `forwardmove`, `sidemove`, or jump timing commands.

Therefore, learning from Milton or other elite players is not simple supervised learning from button labels.

The likely problem is inverse control:

Observed movement trace -> infer or optimize a legal command policy that produces similar movement inside the real server loop.

## Available or expected signals

From `mvd_analyzer`, `qw-sim`, and related parsers, Komodobots expects to work with:

- player positions over time
- derived velocity
- view angles / aim where available
- health / armor / weapon state
- powerup state
- item pickups
- weapon pickups
- damage events
- frag events
- location trails
- loc graph transitions
- region control summaries
- map entities
- KTX scoreboard/demo info

## First movement metrics

For DM2 big-room bunnyjump lab work and routed-map bot movement evidence, start with:

- horizontal speed average
- horizontal speed max
- speed gain over time
- airborne time ratio
- inferred jump rhythm
- direction/yaw change rhythm if available
- stuck or near-stationary time
- time spent in target area
- route or area exits

Current implemented first pass:

- Script: `scripts/extract_movement_metrics.py`
- Input: `events.txt` from `qw-analyze-v20 -format events`
- Position source: line-delimited JSON events with `kind:5`, `PlayerNum`, `Origin`, and `TimeMs`
- Player naming source: `kind:1` player info events
- Default excluded slots: unnamed players, which filters out the control-client shim
- Outputs: `movement-metrics.json` and `movement-metrics.md`
- Schema: `komodobots.movement_metrics.v2`

Current metric fields per named player:

- sample count and active time
- horizontal distance and net horizontal displacement
- average horizontal speed
- max horizontal speed and time of max
- p50/p90/p95 horizontal speed
- time ratio below 10 qu/s as stationary proxy
- time ratio below 100 qu/s as low-speed proxy
- time ratio above server `MaxSpeed`, usually 320 qu/s
- time ratio above 400 qu/s
- path efficiency
- vertical-motion time ratio
- airborne-proxy time ratio
- airborne-proxy run count and cadence per minute
- average airborne-proxy duration
- post-landing speed delta/loss over a fixed window
- dropped teleport/respawn-like segments above 2500 qu/s

Current limitation: these are position-derived metrics. The airborne fields are proxies derived from Z-motion runs, not ground-truth jump button, grounded flag, friction-window, or legal usercmd intent.

S2 moveprobe note:

The first KTX command-emission probe can perturb the final bot command before `trap_SetBotCMD(...)`, but the current MVD-derived metrics still observe only resulting movement. They cannot directly prove that the jump button was pressed or that a specific movement vector reached `trap_SetBotCMD(...)`; they show the behavioral consequence.

## Human comparison sets

Preferred order:

1. Clean human DM2 MVDs.
2. Elite DM2 MVDs.
3. Milton DM2 MVDs.
4. Bot-generated MVDs.

Milton is the long-term player-specific reference, but the first lab may use any clean DM2 movement data to validate the analysis pipeline.

## Bot-generated MVD loop

Target loop:

1. Run KTX/MVDSV headlessly.
2. Load a map appropriate to the experiment. Use stock `dm2` for `qw-sim` continuity and routed maps such as `frobodm2`/`dm3` for Frogbot movement evidence.
3. Spawn Frogbot or test bot.
4. Run fixed-duration movement experiment.
5. Record MVD.
6. Parse MVD with `mvd_analyzer` and/or `qw-sim`.
7. Generate metrics and report.
8. Append findings to `docs/07_FINDINGS_LOG.md`.

For S2 moveprobe runs, the runner also records the active moveprobe cvars in `lab.cfg`, `run.env`, and `run-summary.md`.

## Current parser entry points

As of the 2026-06-05 environment inspection, the practical parser path is:

- WSL `Ubuntu-24.04`: `~/mvd-mcp-bundle/mvd-api`
- WSL `Ubuntu-24.04`: `~/mvd-mcp-bundle/mvd-mcp`
- WSL BSP geometry: `~/mvd-mcp-bundle/bsps/dm2.bsp`
- Source checkout: `C:\Users\benya\projects\quakeworld\tools\mvd_analyzer`
- Offline CLI in source: `mvd-analytics/cmd/qw-analyze`

Prefer the prebuilt WSL bundle for the first lab smoke test because `go` was not on PATH in WSL during inspection. Before using parser output as regression evidence, pin the exact analyzer commit or binary version because the WSL bundle and local source checkout currently differ.

For the first successful smoke run, the actual parser binary used was:

```text
WSL Ubuntu-24.04: ~/qw-sim/bin/qw-analyze-v20
```

The demo was copied outside Git to a temp artifact directory before parsing:

```text
C:\Users\benya\AppData\Local\Temp\komodobots-lab\20260605T180521Z\ffa_2[frobodm2]20260605-1825.mvd
```

Useful parser commands:

```bash
~/qw-sim/bin/qw-analyze-v20 -format json <demo.mvd> > analysis.json
~/qw-sim/bin/qw-analyze-v20 -format md <demo.mvd> > analysis.md
~/qw-sim/bin/qw-analyze-v20 -format events <demo.mvd> > events.txt
```

Observed parser behavior on `ffa_2[frobodm2]20260605-1825.mvd`:

```text
json exit=0 bytes=24395 stderr=
md exit=0 bytes=96 stderr=
events exit=1 bytes=813009 stderr=qw-analyze: end of demo
```

The JSON summary was enough to prove the smoke test:

- Duration: `39307` ms.
- Map title: `Frogbotrophobopolis`.
- Total frags: `2`.
- `28354` ms: `/ bro` killed `/ goldenboy` with `rl`.
- `34828` ms: `/ goldenboy` killed `/ bro` with `rl`.

The KTX-generated `.txt` sidecar for this run was zero bytes, so the `.mvd` parser output is the canonical evidence for the smoke result.

## Current lab artifact contract

`scripts/run_frobodm2_lab.py` writes each run under:

```text
artifacts/lab-runs/<run-id>/
```

The runner intentionally stores raw artifacts outside Git. `.gitignore` excludes `artifacts/`.

Current generated files:

| File | Purpose |
|---|---|
| `demo.mvd` | Safe local copy of the generated server demo. |
| `demo.remote-path.txt` | Original remote KTX demo path. |
| `demo.sha256` | SHA-256 of `demo.mvd`. |
| `demo.size` | Byte size of `demo.mvd`. |
| `demo.txt` | KTX sidecar if present; may be zero bytes. |
| `analysis.json` | `qw-analyze-v20 -format json` output. |
| `analysis.md` | `qw-analyze-v20 -format md` output. |
| `events.txt` | `qw-analyze-v20 -format events` output. |
| `*.stderr` | Parser stderr by mode. |
| `run-summary.md` | Small human-readable smoke-run summary. |
| `movement-metrics.json` | Derived first-pass movement metrics from player origin event samples. |
| `movement-metrics.md` | Human-readable movement metrics table. |
| `screen.log` | MVDSV/KTX console log for the lab screen session. |
| `hardcopy.*.txt` | Screen hardcopies around client/run/cleanup checkpoints. |
| `pyclient.stdout` / `pyclient.stderr` | Minimal QW client shim logs. |
| `remote.stdout` / `remote.stderr` | Remote orchestration logs. |
| `lab.cfg` | Generated KTX config used for the run. |
| `run.env` | Run identity, port, remote paths, and timing. |

Verified one-command parser behavior:

```text
20260605T190849Z: json=0 md=0 events=1 demo=108554 bytes totalFrags=2
20260605T191116Z: json=0 md=0 events=1 demo=98919 bytes totalFrags=0
20260605T195452Z: json=0 md=0 events=1 demo=72183 bytes map=dm2 bots=0
20260605T200124Z: json=0 md=0 events=1 demo=102929 bytes map=dm3 totalFrags=1
20260605T201217Z: json=0 md=0 events=1 demo=110679 bytes map=frobodm2 movementPlayers=2
20260605T201313Z: json=0 md=0 events=1 demo=106867 bytes map=dm3 movementPlayers=2
20260605T205256Z: json=0 md=0 events=1 demo=105711 bytes map=frobodm2 movementPlayers=2 schema=v2
20260605T205353Z: json=0 md=0 events=1 demo=109061 bytes map=dm3 movementPlayers=2 schema=v2
20260605T213010Z: json=0 md=0 events=1 demo=73890 bytes map=frobodm2 moveprobe=2 movementPlayers=2
20260605T213149Z: json=0 md=0 events=1 demo=109520 bytes map=frobodm2 moveprobe=1 movementPlayers=2
```

For now, `events=1` with stderr `qw-analyze: end of demo` is accepted if `events.txt` is written and JSON/Markdown exits are zero. JSON is the canonical smoke-run parser artifact.

Map note: stock `dm2` is valid for parser continuity with `qw-sim`, but it is not a Frogbot movement source in this lab because there is no real `dm2.bot` route. Use routed bot maps such as `frobodm2` and `dm3` for bot-generated movement MVDs.

The first report generator now implements a narrow movement slice:

- parse generated MVD
- extract player position streams
- derive horizontal speed per sample/window
- report max speed, average speed, speed-threshold ratios, stationary proxy, and path-efficiency proxy
- store the raw parser JSON and derived report outside Git under `artifacts/lab-runs/<timestamp>/`

Fresh first-pass movement evidence:

```text
20260605T201217Z frobodm2:
  / bro       avg=329.2 max=995.6 p95=463.6 over320=62.9% over400=51.5%
  / goldenboy avg=276.4 max=910.8 p95=456.6 over320=44.6% over400=30.5%

20260605T201313Z dm3:
  / bro       avg=287.4 max=581.4 p95=462.7 over320=53.0% over400=37.0%
  / goldenboy avg=324.6 max=535.6 p95=449.0 over320=63.1% over400=53.6%
```

Fresh v2 baseline movement evidence:

```text
20260605T205256Z frobodm2:
  / bro       avg=311.8 p95=456.5 over320=58.2% airProxy=18.1% cadence=32.6/min postLandingDelta=+11.9
  / goldenboy avg=346.4 p95=464.0 over320=68.6% airProxy=16.7% cadence=29.5/min postLandingDelta=+9.7

20260605T205353Z dm3:
  / bro       avg=279.4 p95=450.2 over320=47.2% airProxy=25.0% cadence=22.2/min postLandingDelta=+36.6
  / goldenboy avg=92.8  p95=365.3 over320=7.5%  airProxy=36.7% cadence=14.7/min postLandingDelta=+28.8
```

Fresh S2 movement override evidence:

```text
20260605T213010Z frobodm2 moveprobe mode 2, fixed command:
  / bro       avg=1.8   p95=0.0   over320=0.1%  airProxy=0.0% cadence=0.0/min
  / goldenboy avg=1.0   p95=0.0   over320=0.1%  airProxy=0.0% cadence=0.0/min

20260605T213149Z frobodm2 moveprobe mode 1, forced jump:
  / bro       avg=330.7 p95=464.8 over320=66.4% airProxy=17.0% cadence=29.7/min
  / goldenboy avg=383.4 p95=464.0 over320=80.9% airProxy=19.1% cadence=37.0/min
```

## Open questions

- Can/should the current `events.txt` kind `5` position stream remain canonical for first-pass movement metrics?
- Can `qw-sim` already compute all required movement metrics?
- Where will human reference MVDs live?
- How should generated MVD artifacts be stored without bloating Git?
- Can bot experiments be made deterministic enough for regression testing?
