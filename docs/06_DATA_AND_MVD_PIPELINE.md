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
- Plausibility summarizer: `scripts/summarize_moveprobe_plausibility.py`
- Route-state diagnosis helper: `scripts/diagnose_route_state.py`
- Input: `events.txt` from `qw-analyze-v20 -format events`
- Position source: line-delimited JSON events with `kind:5`, `PlayerNum`, `Origin`, and `TimeMs`
- Player naming source: `kind:1` player info events
- Default excluded slots: unnamed players, which filters out the control-client shim
- Sample window: named player samples are clamped to `analysis.json` `match.duration` when present, so post-match/intermission samples do not inflate active time in comparisons
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

Moveprobe plausibility gate:

- Schema: `komodobots.moveprobe_plausibility.v1`
- Inputs: per-run `movement-metrics.json` plus `moveprobe-commands.json`
- Default gate: expected forward command coverage >= `80%`, jump-button command coverage >= `80%`, at least `10` distinct sampled yaw values, stationary time <= `25%`, low-speed time <= `40%`
- S3a side gate: pass `--min-side-ratio 0.8` to require nonzero sidemove coverage for strafe probes
- S3d horizontal command gate: pass `--min-forward-ratio 0 --min-horizontal-ratio 0.8 --min-side-ratio 0.8` when exact local forward values vary because movement is projected relative to preserved combat yaw
- S3e diagnostics: command rows may include `route_yaw`, `view_yaw`, `yaw_delta`, and `backward`; the summary reports backward-command ratio plus absolute yaw-delta average, p90, and ratio above 90 degrees. `yaw_delta` is interpretable for aim-independent modes `5`/`6`/`7`; route-yaw modes `3`/`4` make the field structural rather than diagnostic.
- S3f no-backpedal gate: use the same horizontal/side/jump thresholds as S3e, then inspect command magnitudes because folding negative forward into side can create very large side values
- S3g bounded-command gate: use the same horizontal/side/jump thresholds as S3e/S3f, then inspect `max_abs_forward_command`, `max_abs_side_command`, and `max_horizontal_command` in the summary
- Expected-forward handling: by default the summarizer derives the expected forward command from each run's `MOVEPROBE_FORWARDMOVE` in `run.env`, then falls back to `800`; use `--expected-forward` for older/custom artifacts.
- Command matching: movement rows are matched to command rows by movement `user_id` and command `ed` when possible, then by netname as a fallback. Duplicate bot netnames are unsupported for artifacts that require the fallback.
- Purpose: prevent speed-only interpretation by requiring command coverage and low stuck/low-speed behavior

Route-state diagnosis:

- Schema: `komodobots.route_state_diagnosis.v1`
- Inputs: a lab run's `events.txt`, `analysis.json`, `run.env`, and `moveprobe-commands.json`
- Output: top low-speed windows per named bot, nearest map-entity location context, sampled command strength, jump ratio, yaw-delta summary, and artifact capability flags
- Current limitation: S3g artifacts expose route direction as `route_yaw`, but not route node, next waypoint, route goal, obstruction state, or route primitive identity
- Purpose: decide whether the next experiment needs route-state instrumentation before changing controller command values

S2 moveprobe note:

The first KTX command-emission probe can perturb the final bot command before `trap_SetBotCMD(...)`, but the current MVD-derived metrics still observe only resulting movement. They cannot directly prove that the jump button was pressed or that a specific movement vector reached `trap_SetBotCMD(...)`; they show the behavioral consequence.

The v2a instrumentation path fills that gap for patched KTX runs. With `--moveprobe-log-commands`, KTX emits sampled `FBMOVEPROBE_CMD` console rows immediately before `trap_SetBotCMD(...)`, and the runner writes parsed `moveprobe-commands.json` / `moveprobe-commands.md` artifacts. S3e diagnostic rows append `diag=route_yaw,view_yaw,yaw_delta,backward`. These command logs are not a replacement for MVD behavior metrics; they are the control-plane evidence that the intended command values reached the final bot syscall.

## Human comparison sets

Preferred order:

1. Clean human DM2 MVDs.
2. Elite DM2 MVDs.
3. Milton DM2 MVDs.
4. Bot-generated MVDs.

Milton is the long-term player-specific reference, but the first lab may use any clean DM2 movement data to validate the analysis pipeline.

Current S4a human-demo scaffold:

- Script: `scripts/analyze_human_mvd.py`
- Default inventory root: `C:\Users\benya\projects\quakeworld\data\quake-development\clients\xerialqw-bench\qw\matchinfo\demos`
- Artifact root: `artifacts/human-demos/`
- Specific `--demo` values must resolve under `--demo-root`; set `--demo-root` to the intended source directory rather than passing arbitrary absolute paths.
- Explicit `--run-id` values use the same safe run-id character set as the bot lab runner.
- Raw demo and parser outputs remain ignored.
- Small derived evidence can be promoted to `experiments/human_comparison/evidence/`.
- Output schemas: `komodobots.human_mvd_inventory.v1` and `komodobots.human_mvd_analysis.v1`

S4a result:

- Inventoried five local human/trick demos: two `aerowalk`, one `e1m2`, and two trick demos.
- Found zero filename-inferred `dm2` candidates locally. This inventory check is a filename-token heuristic, not content parsing.
- Parsed `1on1_reppie_vs_locust_aerowalk.mvd` successfully through `qw-analyze-v20` and `scripts/extract_movement_metrics.py`.
- Parser exits: `json=0`, `md=0`, `events=1` with `events=1` matching the known end-of-demo behavior.
- Active movement rows: `reppie` and `locust`; six named slots with less than `1` second, fewer than `10` samples, or less than `100` qu horizontal distance were kept out of the compact summary.
- Active times are clamped to the parsed match duration: `reppie` `597.646` s and `locust` `597.699` s against a `600.057` s match.
- Comparison verdict: parser proof only. The human demo is `aerowalk`; S3g bot evidence is `dm3` and `frobodm2`, so the current evidence is not map-comparable and not a DM2 realism baseline.

Next S4 data step:

Select or acquire a real DM2 human comparison set before using human metrics to judge S3g. Per thevault `quakeworld/mvds.md`, avoid mass-downloads from `hub.quakeworld.nu`; prefer existing bulk corpora such as the `servexeri` `/mnt/usb-ssd/4on4-corpus/demos/` set and its manifest, or other bulk sources that avoid hub egress.

S4b result:

- Inspected `servexeri:/mnt/usb-ssd/4on4-corpus/manifest.tsv`.
- Manifest rows: `6409`; DM2 rows: `1598`; `4on4_` DM2 rows: `1450`; cleanish 4on4 DM2 rows after excluding `tmp` and missing files: `1171`.
- Copied one selected existing corpus file, not from hub: `4on4_blue_vs_red[dm2]20260228-0512.mvd`.
- Manifest SHA-256/size matched the local artifact: `f8269d8139b129426b569eaf6b2be278964d740bd0365647f4410db74da76585`, `8624854` bytes.
- Parsed run `s4b-dm2-blue-vs-red-20260228-0512` as `dm2` / `Claustrophobopolis`.
- Parser exits: `json=0`, `md=0`, `events=1`; event count: `501300`; position events: `443408`.
- Active movement rows: eight 4on4 players. Match-duration clamping removes the short post-match zero-distance `blaze` row from the compact summary.
- Comparison verdict: `human_dm2_available_but_s3g_not_dm2`. S4 now has a true DM2 human reference file, but S3g is still not map-matched because the current bot evidence is `dm3` and `frobodm2`.

Next S4 comparison step:

Before making a S3g-vs-human realism claim, either produce S3g-style bot evidence on DM2 or parse map-matched human `dm3` data from the same corpus. Because stock `dm2` currently lacks a Frogbot route file, the smallest useful comparison is likely one human `dm3` 4on4 demo matched against the existing S3g `dm3` bot run.

S4c result:

- Selected `4on4_blue_vs_red[dm3]20260426-0307.mvd` from the same existing `servexeri` corpus; no hub download.
- Exact `[dm3]` inventory counts: `6409` manifest rows, `1663` `[dm3]` rows, `1629` `4on4_` `[dm3]` rows, `1247` cleanish existing 4on4 `[dm3]` rows, and `444` moderate-size cleanish 2026 rows.
- Manifest SHA-256/size matched the local artifact: `6897a00a4c185751ac82c579c091437cc5b82701df14cc2178da4792924ad4fe`, `7632722` bytes.
- Parsed run `s4c-dm3-blue-vs-red-20260426-0307` as `dm3` / `The Abandoned Base`.
- Parser exits: `json=0`, `md=0`, `events=1`; event count: `477099`; position events: `432058`.
- Active movement rows: eight 4on4 players with match-duration clamped active times around `728` s.
- Comparison verdict: `same_map_human_reference_available`.
- Against this single human `dm3` sample, S3g `dm3` bots are not yet a human-like movement match: `/ bro` is below the human range for average and p95 speed, `/ goldenboy` is only inside the human average-speed range, both bots are below the human p95 range, and `/ bro` exceeds the human airborne-proxy range.

Next S5 data step:

Build a Milton/elite reference-set inventory before training or controller changes. Use existing local/corpus metadata first, preserve the no-hub-mass-download rule, and decide whether the current corpus can identify player-specific reference demos without a costly content scan.

S5a result:

- Queried Turso `player_games` / `games` metadata and cross-referenced game SHA-256 values with the existing `servexeri` 4on4 corpus manifest.
- Exact `Milton` selection is feasible without training, hub download, or a full content scan: `1240` total 4on4 rows; latest-500 metadata window had `96` manifest hits, including `23` `dm3` and `19` `dm2` hits.
- Other elite targets are also feasible in the latest-500 metadata window: `carapace` `68` manifest hits, `_ ParadokS` `55`, `yeti` `60`, and `ok98` `59`.
- Selected the latest manifest-matched exact `Milton` `dm3` row: `4on4_blue_vs_anza[dm3]20260602-2022.mvd`, SHA-256 `9ca8f72b3afa95ba87830a83478c51bb9b3dd626b733190a4ca2d84b4d66490e`.
- Parsed run `s5a-milton-dm3-blue-vs-anza-20260602-2022` as `dm3` / `The Abandoned Base`, duration `1200013` ms, event count `799790`, position events `694902`.
- Milton movement row: active `1199.415` s, avg `314.2` qu/s, p95 `535.0`, stationary `5.9%`, low-speed `12.4%`, airborne proxy `35.1%`, cadence `44.9`/min.
- Against this Milton-containing sample, S3g `dm3` bots are below the human p95 range; `/ bro` is also below average speed and above both low-speed and airborne-proxy ranges.

Next S5 comparison step:

Promote S5b as a tiny reference aggregate before S6 route primitives: select a small, bounded set of exact-player `dm3` references from Milton and/or the elite targets already proven selectable, parse compact summaries, and report a multi-demo range so one Milton match does not become the sole target.

S5b result:

- Added `scripts/summarize_reference_aggregate.py` to combine exact-player human summaries into compact reference ranges and compare same-map S3g bot rows.
- Selected three exact-player `dm3` references by metadata, with no hub download and no bulk content scan:
  - `Milton`: `4on4_blue_vs_anza[dm3]20260602-2022.mvd`
  - `carapace`: `4on4_book_vs_-s-[dm3]20260526-2011.mvd`
  - `yeti`: `4on4_red_vs_blue[dm3]20260530-0322.mvd`
- Reference rows:
  - `Milton`: avg `314.2`, p95 `535.0`, stationary `5.9%`, low `12.4%`, air `35.1%`, cadence `44.9`/min.
  - `carapace`: avg `282.8`, p95 `524.9`, stationary `11.5%`, low `19.6%`, air `34.2%`, cadence `44.0`/min.
  - `yeti`: avg `291.5`, p95 `505.8`, stationary `7.5%`, low `15.4%`, air `35.9%`, cadence `48.6`/min.
- Aggregate p95 range: reference `505.8` to `535.0`; S3g `dm3` bots `361.0` to `375.3`.
- Aggregate average-speed range: reference `282.8` to `314.2`; S3g `dm3` bots `190.1` to `248.2`.
- S3g `/ bro` is below reference avg/p95/stationary ranges and above low-speed/air ranges.
- S3g `/ goldenboy` is below reference avg/p95/stationary/air ranges while staying inside the low-speed range.

S6a result:

- Added `scripts/diagnose_route_state.py`.
- Diagnosed S3g `dm3` run `20260606T003718Z`.
- `/ bro`: `7` low-speed windows of at least `250` ms; longest low contribution `1198` ms.
- `/ goldenboy`: `4` low-speed windows; longest low contribution `1078` ms.
- Top-window command context: `8` of `9` analyzed windows had average sampled horizontal command at or above `400`, many near the mode `7` cap around `824`.
- Artifact capability verdict: position/command/route-yaw evidence is available, but route node/goal/obstruction state is not.

Next S6 data step:

Add minimal route-state logging around the Frogbot command boundary so low-speed windows can be tagged with route node, next goal, obstruction/blocked state, or route primitive before changing the movement controller again.

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

For S2 moveprobe runs, the runner also records the active moveprobe cvars in `lab.cfg`, `run.env`, and `run-summary.md`. When command logging is enabled, the same run directory includes `moveprobe-commands.json` and `moveprobe-commands.md`.

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

The runner intentionally stores raw artifacts outside Git. `.gitignore` excludes `artifacts/`. Small derived summaries that support PR claims can be promoted into Git under `experiments/ktx_moveprobe/evidence/`.

Human-demo artifacts follow the same split: raw demos, `analysis.json`, and full `events.txt` stay in `artifacts/human-demos/`; compact inventory and S4 summaries can be committed under `experiments/human_comparison/evidence/`.

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
20260605T222006Z: json=0 md=0 events=1 demo=71105 bytes map=frobodm2 moveprobe=0 commands=196 movementPlayers=2
20260605T222047Z: json=0 md=0 events=1 demo=65648 bytes map=frobodm2 moveprobe=1 commands=196 movementPlayers=2
20260605T222129Z: json=0 md=0 events=1 demo=47234 bytes map=frobodm2 moveprobe=2 commands=197 movementPlayers=2
20260605T224811Z: json=0 md=0 events=1 demo=59812 bytes map=frobodm2 moveprobe=3 commands=197 movementPlayers=2
20260605T225720Z: json=0 md=0 events=1 demo=67335 bytes map=frobodm2 moveprobe=3 commands=197 movementPlayers=2
20260605T225802Z: json=0 md=0 events=1 demo=64591 bytes map=dm3 moveprobe=3 commands=196 movementPlayers=2
20260605T231033Z: json=0 md=0 events=1 demo=68834 bytes map=frobodm2 moveprobe=4 commands=197 movementPlayers=2
20260605T231115Z: json=0 md=0 events=1 demo=71271 bytes map=dm3 moveprobe=4 commands=196 movementPlayers=2
20260605T231737Z: json=0 md=0 events=1 demo=63831 bytes map=dm3 moveprobe=4 sidemove=200 commands=196 movementPlayers=2
20260605T231819Z: json=0 md=0 events=1 demo=66789 bytes map=dm3 moveprobe=4 sidemove=300 commands=196 movementPlayers=2
20260605T233120Z: json=0 md=0 events=1 demo=68715 bytes map=frobodm2 moveprobe=4 sidemove=200 commands=197 movementPlayers=2
20260605T233202Z: json=0 md=0 events=1 demo=63803 bytes map=dm3 moveprobe=4 sidemove=200 commands=196 movementPlayers=2
20260605T234620Z: json=0 md=0 events=1 demo=62771 bytes map=frobodm2 moveprobe=5 sidemove=200 commands=197 movementPlayers=2
20260605T234701Z: json=0 md=0 events=1 demo=62921 bytes map=dm3 moveprobe=5 sidemove=200 commands=195 movementPlayers=2
20260606T000331Z: json=0 md=0 events=1 demo=70414 bytes map=frobodm2 moveprobe=5 sidemove=200 diagnostics=1 commands=196 movementPlayers=2
20260606T000414Z: json=0 md=0 events=1 demo=74149 bytes map=dm3 moveprobe=5 sidemove=200 diagnostics=1 commands=195 movementPlayers=2
20260606T001705Z: json=0 md=0 events=1 demo=68881 bytes map=dm3 moveprobe=6 sidemove=200 diagnostics=1 commands=196 movementPlayers=2
20260606T001825Z: json=0 md=0 events=1 demo=70030 bytes map=frobodm2 moveprobe=6 sidemove=200 diagnostics=1 commands=197 movementPlayers=2
20260606T003718Z: json=0 md=0 events=1 demo=69549 bytes map=dm3 moveprobe=7 sidemove=200 diagnostics=1 commands=195 movementPlayers=2
20260606T003808Z: json=0 md=0 events=1 demo=66511 bytes map=frobodm2 moveprobe=7 sidemove=200 diagnostics=1 commands=197 movementPlayers=2
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
20260605T213010Z frobodm2 moveprobe mode 2, fixed command plus forced jump:
  / bro       avg=1.8   p95=0.0   over320=0.1%  airProxy=0.0% cadence=0.0/min
  / goldenboy avg=1.0   p95=0.0   over320=0.1%  airProxy=0.0% cadence=0.0/min

20260605T213149Z frobodm2 moveprobe mode 1, forced jump:
  / bro       avg=330.7 p95=464.8 over320=66.4% airProxy=17.0% cadence=29.7/min
  / goldenboy avg=383.4 p95=464.0 over320=80.9% airProxy=19.1% cadence=37.0/min
```

Fresh S2 emitted-command evidence:

```text
20260605T222006Z frobodm2 moveprobe mode 0, command logging:
  commands=196; stock commands had variable yaw, forward, side, and buttons [0,1,3] / [0,1]
  / bro avg=363.5 p95=464.1 airProxy=25.2%; / goldenboy avg=410.4 p95=633.8 airProxy=37.1%

20260605T222047Z frobodm2 moveprobe mode 1, command logging:
  commands=196; movement/yaw stayed variable, final buttons were [2,3], proving forced jump in emitted commands
  / bro avg=189.9 p95=463.9 airProxy=11.4%; / goldenboy avg=434.2 p95=595.2 airProxy=18.6%

20260605T222129Z frobodm2 moveprobe mode 2, command logging:
  commands=197; both bots emitted yaw=[90.0], forward=[800], side=[0], up=[0], buttons=[2]
  / bro avg=1.9 p95=0.0 airProxy=0.0%; / goldenboy avg=1.6 p95=0.0 airProxy=0.0%

20260605T224811Z frobodm2 moveprobe mode 3, route-yaw command logging:
  commands=197; sampled yaw varied by route direction, with forward=800 in 189/197 rows
  / bro avg=137.4 p95=442.4 airProxy=8.9% stationary=59.7%; / goldenboy avg=330.8 p95=464.6 airProxy=27.6% stationary=1.3%

20260605T225720Z frobodm2 moveprobe mode 3, v2c gate:
  both bots passed; / bro stationary=6.5% low=22.1%; / goldenboy stationary=0.2% low=5.1%

20260605T225802Z dm3 moveprobe mode 3, v2c gate:
  both bots passed; / bro stationary=1.1% low=1.4%; / goldenboy stationary=0.0% low=1.7%

20260605T231033Z frobodm2 moveprobe mode 4, S3a side gate:
  both bots passed with side coverage >94%; one RL frag; / bro avg=281.4 p95=358.9; / goldenboy avg=294.4 p95=364.5

20260605T231115Z dm3 moveprobe mode 4, S3a side gate:
  side coverage >93% for both bots, but / bro failed low-speed=63.0%; / goldenboy barely passed low-speed=39.0%

20260605T231737Z dm3 moveprobe mode 4, sidemove=200, S3b side gate:
  both bots passed; / bro avg=228.5 p95=387.6 low=26.9%; / goldenboy avg=197.3 p95=377.7 low=28.3%

20260605T231819Z dm3 moveprobe mode 4, sidemove=300, S3b side gate:
  / bro failed low=51.1%; / goldenboy passed low=5.6%; both bots had side coverage >91%

20260605T233120Z frobodm2 moveprobe mode 4, sidemove=200, S3c side gate:
  both bots passed; / bro avg=279.6 p95=387.6 low=7.4%; / goldenboy avg=306.7 p95=386.5 low=4.6%; one RL frag

20260605T233202Z dm3 moveprobe mode 4, sidemove=200, S3c side gate:
  both bots passed; / bro avg=248.8 p95=383.1 low=16.7%; / goldenboy avg=293.3 p95=386.5 low=10.9%

20260605T234620Z frobodm2 moveprobe mode 5, sidemove=200, S3d horizontal/side gate:
  command coverage passed for both; / bro failed stationary=74.7% low=79.2%; / goldenboy passed avg=256.0 p95=381.5 low=21.2%; one SSG frag

20260605T234701Z dm3 moveprobe mode 5, sidemove=200, S3d horizontal/side gate:
  command coverage passed for both; / bro failed stationary=40.5% low=53.8%; / goldenboy passed avg=219.6 p95=381.4 low=24.7%

20260606T000331Z frobodm2 moveprobe mode 5, sidemove=200, S3e diagnostics:
  both bots passed; / bro back=22.7% yawDeltaAvg=53.1 yawDeltaP90=110.9 low=14.3%; / goldenboy back=14.0% yawDeltaAvg=44.2 yawDeltaP90=91.8 low=4.0%; one SSG frag

20260606T000414Z dm3 moveprobe mode 5, sidemove=200, S3e diagnostics:
  command coverage passed for both, but both failed low-speed; / bro back=41.3% yawDeltaAvg=79.6 yawDeltaP90=154.7 low=43.1%; / goldenboy back=14.0% yawDeltaAvg=44.7 yawDeltaP90=99.4 low=52.8%

20260606T001705Z dm3 moveprobe mode 6, sidemove=200, S3f no-backpedal:
  both bots passed; / bro back=0.0% yawDeltaAvg=82.2 yawDeltaP90=163.1 low=38.3%; / goldenboy back=0.0% yawDeltaAvg=66.3 yawDeltaP90=124.2 low=24.4%; one SG frag

20260606T001825Z frobodm2 moveprobe mode 6, sidemove=200, S3f no-backpedal:
  both bots passed; / bro back=0.0% yawDeltaAvg=84.3 yawDeltaP90=167.1 low=13.8%; / goldenboy back=0.0% yawDeltaAvg=85.8 yawDeltaP90=163.2 low=26.8%; one GL frag

20260606T003718Z dm3 moveprobe mode 7, sidemove=200, S3g bounded no-backpedal:
  both bots passed; / bro maxMove=824.5 back=0.0% yawDeltaAvg=85.8 yawDeltaP90=157.7 low=26.1%; / goldenboy maxMove=824.5 back=0.0% yawDeltaAvg=77.8 yawDeltaP90=157.5 low=18.9%; one SG frag

20260606T003808Z frobodm2 moveprobe mode 7, sidemove=200, S3g bounded no-backpedal:
  both bots passed; / bro maxMove=824.5 back=0.0% yawDeltaAvg=59.9 yawDeltaP90=135.5 low=5.5%; / goldenboy maxMove=824.6 back=0.0% yawDeltaAvg=65.8 yawDeltaP90=149.3 low=2.7%
```

## Open questions

- Can/should the current `events.txt` kind `5` position stream remain canonical for first-pass movement metrics?
- Can `qw-sim` already compute all required movement metrics?
- Where will human reference MVDs live?
- How should generated MVD artifacts be stored without bloating Git?
- Can bot experiments be made deterministic enough for regression testing?
