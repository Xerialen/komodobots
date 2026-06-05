# Findings Log

Status: living document.

Purpose:

Capture discoveries, observations, measurements, and failed experiments.

Format:

## YYYY-MM-DD

### Experiment

What was attempted?

### Result

What happened?

### Evidence

Links, files, reports, commits, screenshots, MVDs, or metrics.

### Interpretation

What do we think this means?

### Confidence

Low / Medium / High

### Follow-up

What should be tested next?

---

## Initial Entry

Project created.

Current working hypothesis:

KTX/Frogbots may be usable as a server-native shell while replacing or enhancing the movement brain.

No laboratory evidence yet.

---

## 2026-06-05

### Experiment

Inspected the existing headless QuakeWorld environment and adjacent assets to determine whether they can become the first Komodobots movement lab.

### Result

The available foundation is stronger than the original placeholder assumed:

- `ezquake-test` / `~/hud-runner` is a proven headless ezQuake render harness, but it is a client-side demo playback and screenshot tester.
- `servexeri:~/nquakesv/` is the better lab substrate because it has MVDSV, KTX, stock `dm2.bsp`, `frobodm2.bsp`, Frogbot route files, and MVD recording config.
- KTX bot support appears to be present in both source and deployed artifacts.
- MVD parsing is available through the WSL `~/mvd-mcp-bundle/` binaries, with `dm2.bsp` present for map-aware analysis.

### Evidence

- Updated `docs/05_HEADLESS_TEST_ENV.md` with the environment inventory and proposed automation entry point.
- Updated `docs/02_SOURCE_MAP.md` with MVDSV, deployed KTX, `mvd_analyzer`, and `ezquake-test` source notes.
- Updated `docs/06_DATA_AND_MVD_PIPELINE.md` with current parser entry points.
- SSH checks showed live `turkishbathhouse` MVDSV ports `28501`, `28502`, and `28503` running on `servexeri`.
- Server config inspection showed `demo_tmp_record 1`, `sv_demotxt 2`, `sv_demofps 77`, and `sv_demodir demos`.
- User clarified after the initial inspection that no one plays on this server, so lab use of any port is acceptable.

### Interpretation

Komodobots should start from the existing `servexeri` MVDSV/KTX install. Any port can be used for experiments; a separate temporary lab process/port remains useful for repeatability and cleanup, not because of player-traffic risk.

The main unproven control point is unattended bot spawning. `botcmd` support exists, but the first smoke test must prove that automation can issue `botcmd enable` and `botcmd addbot`, start a run, and collect an MVD without a human player sitting in the server.

### Confidence

Medium.

The inventory is direct evidence from local files, vault notes, and SSH inspection. Bot spawn and demo production remain untested.

### Follow-up

Run a 30-60 second `frobodm2` lab smoke test on any convenient port, collect the generated MVD/JSON sidecar, and parse it with the WSL `mvd-api` bundle.

---

## 2026-06-05 - `frobodm2` Smoke Test

### Experiment

Started a separate MVDSV/KTX lab process on `servexeri` port `28599`, loaded `frobodm2`, connected a minimal scripted QuakeWorld client, issued `botcmd addbot`, recorded a short MVD, copied the demo to a temp local artifact directory, and parsed it with `qw-analyze-v20`.

### Result

The first lab smoke test succeeded.

- The lab loaded `frobodm2`.
- The scripted client connected.
- Two Frogbots entered: `/ bro` and `/ goldenboy`.
- The bots moved/fought long enough to produce two RL frags.
- KTX saved an MVD.
- `qw-analyze-v20` parsed the MVD summary successfully.

### Evidence

- Run ID: `20260605T180521Z`.
- Remote run directory: `servexeri:/home/xerial/komodobots-lab/runs/20260605T180521Z`.
- Remote demo: `servexeri:/home/xerial/nquakesv/ktx/demos/ffa_2[frobodm2]20260605-1825.mvd`.
- Demo size: `112289` bytes.
- Transferred demo SHA-256: `00CFFC080105966C14DA0FA6736BF66D2C31F0989DAFA7DC82EB9072956A4FBA`.
- Parser JSON summary: duration `39307` ms, map `Frogbotrophobopolis`, total frags `2`.
- Frag at `28354` ms: `/ bro` killed `/ goldenboy` with `rl`.
- Frag at `34828` ms: `/ goldenboy` killed `/ bro` with `rl`.
- Parser mode checks:

```text
json exit=0 bytes=24395 stderr=
md exit=0 bytes=96 stderr=
events exit=1 bytes=813009 stderr=qw-analyze: end of demo
```

### Interpretation

The Komodobots lab substrate is real enough to build on. The important correction is that `botcmd` is not an MVDSV server-console command; it must be issued from a connected KTX client context. KTX Frogbot auto-add also does not solve zero-human smoke tests because it depends on `human_count`.

The rough scripted client is therefore the current proven control path. It is captured as `experiments/qw_min_client.py` for follow-up automation. ezQuake under Xvfb remains useful for playback/visual verification, but it was not reliable enough here for unattended bot spawning.

### Confidence

High for the narrow claim that `servexeri` can produce and parse a bot-generated `frobodm2` MVD.

Medium for repeatability until the client shim is exercised through a lab launcher and re-run from a clean command.

### Follow-up

Build a lab startup/teardown launcher around `experiments/qw_min_client.py`. Completed by `scripts/run_frobodm2_lab.py`; the next step is to run the same loop on stock `dm2`.

---

## 2026-06-05 - One-command `frobodm2` Lab Runner

### Experiment

Implemented `scripts/run_frobodm2_lab.py` and ran it twice from the repo root:

```bash
python scripts/run_frobodm2_lab.py --duration 40 --bot-count 2
```

The runner starts a temporary MVDSV/KTX screen session on `servexeri`, loads `frobodm2`, uploads/runs `experiments/qw_min_client.py`, records an MVD, copies artifacts to `artifacts/lab-runs/<run-id>/`, parses the demo with WSL `qw-analyze-v20`, writes `run-summary.md`, and stops its own screen session.

### Result

The repeatable `frobodm2` lab runner works.

- Run `20260605T190849Z` produced a `108554` byte local `demo.mvd`, parsed JSON/Markdown successfully, observed `/ bro` and `/ goldenboy`, and recorded two frags.
- Run `20260605T191116Z` produced a `98919` byte local `demo.mvd`, parsed JSON/Markdown successfully, observed `/ bro` and `/ goldenboy`, and recorded no frags.
- Both runs wrote complete artifact directories under `artifacts/lab-runs/`.
- Both runs left `localhost:28599` down after cleanup.

### Evidence

Parser exit summaries:

```text
20260605T190849Z: json=0 md=0 events=1
20260605T191116Z: json=0 md=0 events=1
```

Run summaries:

- `artifacts/lab-runs/20260605T190849Z/run-summary.md`
- `artifacts/lab-runs/20260605T191116Z/run-summary.md`

Remote demos:

- `/home/xerial/nquakesv/ktx/demos/ffa_2[frobodm2]20260605-1908.mvd`
- `/home/xerial/nquakesv/ktx/demos/ffa_2[frobodm2]20260605-1911.mvd`

### Interpretation

Komodobots now has repeatable evidence production for `frobodm2`: one command can start the stack, spawn bots, produce an MVD, parse it, summarize it, and clean up. Frags are not guaranteed on every short run, so combat events should remain evidence when present, not a required success condition for the runner.

This completes the hygiene step between "manual smoke worked once" and "we can run controlled lab iterations."

### Confidence

High for repeatable `frobodm2` MVD production and parser summary generation.

Medium for future movement comparisons until stock `dm2` is added and movement metrics are derived from parser output.

### Follow-up

Do not try to force stock `dm2` Frogbot routing. Use another routed map such as `dm3`, then add the first movement metrics over generated MVDs.

---

## 2026-06-05 - Stock `dm2` Check and `dm3` Pivot

### Experiment

Made the lab runner map-capable and tried stock `dm2` because `qw-sim` was built around `dm2`. After user clarification that Frogbots have never worked on stock `dm2` and that route-building for it is not useful, checked `dm3` as an alternative routed map.

### Result

Stock `dm2` is not a useful Frogbot lab map in the current environment.

- `dm2.bsp` and `dm2.loc` exist.
- `ktx/bots/maps/dm2.bot` does not exist.
- Run `20260605T195452Z` loaded stock `dm2`, recorded a `72183` byte MVD, and parsed JSON/Markdown successfully, but no Frogbots entered.
- A temporary experiment that copied `frobodm2.bot` to `dm2.bot` proved why this is the wrong path: one run spawned bots, but the next run destabilized the server and left a zero-byte demo. That route-copy escape hatch was removed from the runner.

`dm3` is a better next routed map.

- `dm3.bsp`, `dm3.loc`, and `ktx/bots/maps/dm3.bot` exist.
- Run `20260605T200124Z` loaded `dm3`, spawned `/ bro` and `/ goldenboy`, recorded a `102929` byte MVD, parsed JSON/Markdown successfully, and recorded one frag.
- The lab port was down afterward and no temporary `dm2.bot` remained.

### Evidence

`dm3` summary:

```text
Run ID: 20260605T200124Z
Map title: The Abandoned Base
Duration: 40801 ms
Demo size: 102929 bytes
SHA-256: 744346553fb7a224b6159ad6d17b0e7180dacee9358b030fa3ffb3315dfb8700
Parser exits: json=0 md=0 events=1
Frag: 17173 ms, / bro killed / goldenboy with sg
```

User map rationale:

- `dm2` matters because it is the map chosen for `qw-sim`.
- `dm2` is not necessarily ideal for measuring bunnyhopping.
- Frogbots have not worked on stock `dm2`; `frobodm2` exists for that reason.

### Interpretation

The map-capable runner should target maps with real Frogbot route files for bot movement evidence. Stock `dm2` can remain important for `qw-sim` data continuity, but it should not absorb lab time as a Frogbot route problem.

### Confidence

High that `dm3` is a valid routed bot lab map.

High that stock `dm2` should not be pursued as a Frogbot route-building task right now.

### Follow-up

Use `frobodm2` and `dm3` as the first routed bot movement sources, then add derived movement metrics over their generated MVDs.

---

## 2026-06-05 - First MVD-derived Movement Metrics

### Experiment

Implemented `scripts/extract_movement_metrics.py` and wired it into `scripts/run_bot_lab.py` through `scripts/run_frobodm2_lab.py`. The extractor reads `events.txt` from `qw-analyze-v20 -format events`, collects named-player `kind:5` origin samples, and derives first-pass horizontal movement metrics.

Ran fresh 40 second lab runs:

```bash
python scripts/run_bot_lab.py --map frobodm2 --duration 40 --bot-count 2
python scripts/run_bot_lab.py --map dm3 --duration 40 --bot-count 2
```

### Result

The runner now produces movement artifacts automatically:

- `movement-metrics.json`
- `movement-metrics.md`

Fresh run `20260605T201217Z` on `frobodm2`:

- `/ bro`: avg `329.2` qu/s, max `995.6` qu/s, p95 `463.6` qu/s, over 320 qu/s `62.9%`, over 400 qu/s `51.5%`.
- `/ goldenboy`: avg `276.4` qu/s, max `910.8` qu/s, p95 `456.6` qu/s, over 320 qu/s `44.6%`, over 400 qu/s `30.5%`.

Fresh run `20260605T201313Z` on `dm3`:

- `/ bro`: avg `287.4` qu/s, max `581.4` qu/s, p95 `462.7` qu/s, over 320 qu/s `53.0%`, over 400 qu/s `37.0%`.
- `/ goldenboy`: avg `324.6` qu/s, max `535.6` qu/s, p95 `449.0` qu/s, over 320 qu/s `63.1%`, over 400 qu/s `53.6%`.

Both runs parsed JSON/Markdown successfully, accepted the known events-mode exit `1`, observed two named bots, and left `servexeri:28599` down after cleanup. The temporary stock `dm2.bot` route remained absent.

### Evidence

Artifacts:

- `artifacts/lab-runs/20260605T201217Z/run-summary.md`
- `artifacts/lab-runs/20260605T201217Z/movement-metrics.md`
- `artifacts/lab-runs/20260605T201313Z/run-summary.md`
- `artifacts/lab-runs/20260605T201313Z/movement-metrics.md`

Remote demos:

- `/home/xerial/nquakesv/ktx/demos/ffa_2[frobodm2]20260605-2012.mvd`
- `/home/xerial/nquakesv/ktx/demos/ffa_2[dm3]20260605-2013.mvd`

### Interpretation

Komodobots now has the first measurable movement layer: each lab run can tell us whether bots are moving, how fast, how often they exceed ordinary maxspeed, and how much time they spend nearly stationary. This does not prove bunnyhopping intelligence yet, but it gives us a scoreboard for movement changes.

The current metrics are intentionally position-derived. They should be treated as first-pass behavioral evidence, not as proof of legal input timing or actual jump-command skill.

### Confidence

High that generated MVDs can produce repeatable per-bot horizontal speed metrics.

Medium that these metrics are enough for bunnyhopping evaluation until airborne/jump rhythm and human reference distributions are added.

### Follow-up

Compare these bot metrics against human/reference MVDs and add the next movement layer: airborne segmentation, jump cadence, and speed gain/loss around ground contacts.

---

## 2026-06-05 - Baseline Movement Report v2

### Experiment

Extended `scripts/extract_movement_metrics.py` from horizontal-speed reporting to baseline movement v2. The report now adds vertical-motion and airborne-proxy metrics derived from MVD player origin samples:

- vertical-motion time ratio
- airborne-proxy time ratio
- airborne-proxy run count
- jump cadence per minute
- average airborne-proxy duration
- post-landing speed delta/loss over a 250 ms window

Ran fresh 40 second lab baselines:

```bash
python scripts/run_bot_lab.py --map frobodm2 --duration 40 --bot-count 2
python scripts/run_bot_lab.py --map dm3 --duration 40 --bot-count 2
```

### Result

Run `20260605T205256Z` on `frobodm2`:

- `/ bro`: avg `311.8` qu/s, p95 `456.5` qu/s, over 320 qu/s `58.2%`, air proxy `18.1%`, cadence `32.6/min`, post-landing delta `+11.9` qu/s.
- `/ goldenboy`: avg `346.4` qu/s, p95 `464.0` qu/s, over 320 qu/s `68.6%`, air proxy `16.7%`, cadence `29.5/min`, post-landing delta `+9.7` qu/s.

Run `20260605T205353Z` on `dm3`:

- `/ bro`: avg `279.4` qu/s, p95 `450.2` qu/s, over 320 qu/s `47.2%`, air proxy `25.0%`, cadence `22.2/min`, post-landing delta `+36.6` qu/s.
- `/ goldenboy`: avg `92.8` qu/s, p95 `365.3` qu/s, over 320 qu/s `7.5%`, air proxy `36.7%`, cadence `14.7/min`, post-landing delta `+28.8` qu/s.

Both runs parsed JSON/Markdown successfully, accepted the known events-mode exit `1`, observed two named bots, and left `servexeri:28599` down after cleanup. The temporary stock `dm2.bot` route remained absent.

### Evidence

Artifacts:

- `artifacts/lab-runs/20260605T205256Z/run-summary.md`
- `artifacts/lab-runs/20260605T205256Z/movement-metrics.md`
- `artifacts/lab-runs/20260605T205353Z/run-summary.md`
- `artifacts/lab-runs/20260605T205353Z/movement-metrics.md`

Remote demos:

- `/home/xerial/nquakesv/ktx/demos/ffa_2[frobodm2]20260605-2053.mvd`
- `/home/xerial/nquakesv/ktx/demos/ffa_2[dm3]20260605-2054.mvd`

Validation:

- `python -m py_compile scripts\extract_movement_metrics.py scripts\run_frobodm2_lab.py scripts\run_bot_lab.py experiments\qw_min_client.py tests\test_extract_movement_metrics.py`
- `python -m unittest discover -s tests -v`

### Interpretation

S1 baseline is now good enough to serve the next stage. The lab has a repeatable movement report that captures speed, vertical motion, and an explicit airborne proxy. It still does not prove true jump input timing, but it gives S2 movement-override experiments a baseline scoreboard.

The `dm3` run shows why multiple baselines matter: one bot had low average horizontal speed while still showing large air-proxy time, likely because route/map behavior can create vertical movement without strong horizontal bunnyhopping. Future comparisons should use several runs per map or aggregate distributions.

### Confidence

High that baseline Frogbot movement can now be measured automatically from generated MVDs.

Medium that the airborne proxy tracks bunnyhopping itself. It is a useful approximation until grounded flags, collision context, or usercmd reconstruction exist.

### Follow-up

Start S2: prove that movement can be isolated and replaced without breaking KTX/Frogbot spawning, combat participation, MVD recording, and parser/metric generation.

---

## 2026-06-05 - S2 KTX Final-Command Moveprobe

### Experiment

Added the first S2 movement override probe:

- `experiments/ktx_moveprobe/frogbot-moveprobe.patch` applies to KTX commit `08807da`.
- The patch hooks `src/bot_movement.c::BotSetCommand()` after the prewar-freeze guard and immediately before button assembly and `trap_SetBotCMD(...)`.
- `scripts/run_bot_lab.py` / `scripts/run_frobodm2_lab.py` can now write `k_fb_moveprobe_*` cvars into generated lab configs and summaries.

Temporarily deployed the patched KTX build to `servexeri`, with deployed `qwprogs.so` backups before each run, then restored the stock deployed library and reversed the KTX source patch after the runs.

Ran two `frobodm2` experiments:

```bash
python scripts/run_bot_lab.py --map frobodm2 --duration 40 --bot-count 2 --moveprobe-mode 2 --moveprobe-yaw 90 --moveprobe-forwardmove 800
python scripts/run_bot_lab.py --map frobodm2 --duration 40 --bot-count 2 --moveprobe-mode 1
```

### Result

Moveprobe mode `2` replaced the final movement command with a fixed command plus forced jump:

- Run `20260605T213010Z`.
- Bots spawned and the lab produced MVD/parser/metrics artifacts.
- Parser exits: `json=0`, `md=0`, `events=1`.
- The run recorded one telefrag.
- Movement collapsed to near-stationary behavior: `/ bro` avg `1.8` qu/s, `/ goldenboy` avg `1.0` qu/s, both with `0.0%` air proxy.

Moveprobe mode `1` forced jump while preserving Frogbot direction/combat:

- Run `20260605T213149Z`.
- Bots spawned, fought, recorded three frags, and the lab produced MVD/parser/metrics artifacts.
- Parser exits: `json=0`, `md=0`, `events=1`.
- `/ bro`: avg `330.7` qu/s, p95 `464.8` qu/s, over maxspeed `66.4%`, air proxy `17.0%`, cadence `29.7/min`.
- `/ goldenboy`: avg `383.4` qu/s, p95 `464.0` qu/s, over maxspeed `80.9%`, air proxy `19.1%`, cadence `37.0/min`.

After both runs, `servexeri:28599` was down and `~/nquakesv/build/ktx` was clean on `master...origin/master`.

### Evidence

Artifacts:

- `artifacts/lab-runs/20260605T213010Z/run-summary.md`
- `artifacts/lab-runs/20260605T213010Z/movement-metrics.md`
- `artifacts/lab-runs/20260605T213149Z/run-summary.md`
- `artifacts/lab-runs/20260605T213149Z/movement-metrics.md`

Patch and docs:

- `experiments/ktx_moveprobe/frogbot-moveprobe.patch`
- `experiments/ktx_moveprobe/README.md`

Remote restore checks:

```text
servexeri ~/nquakesv/build/ktx: clean master...origin/master
quakestat localhost:28599: DOWN
```

### Interpretation

S2 has its first positive evidence: Frogbot commands can be perturbed near the final command-emission point while preserving the existing KTX/Frogbot shell, MVD recording, parser output, and metric generation.

Mode `2` is also useful negative evidence. Blind fixed-command replacement, even with forced jump, is not a movement brain; it can satisfy the plumbing proof while producing unusable behavior.

At this point, the next S2 step was to instrument the exact values handed to `trap_SetBotCMD(...)` for stock, mode `1`, and mode `2`. That follow-up is recorded in the v2a entries below.

### Confidence

High that `BotSetCommand()` is a real control point for command perturbation.

Medium that this is the right long-term integration point for replacing movement vectors. It is source-grounded and measured, but the probe is still a patch outside upstream KTX.

### Follow-up

Build moveprobe v2a instrumentation: keep the `BotSetCommand()` hook, log the final `msec`, angles, movement values, buttons, and impulse handed to `trap_SetBotCMD(...)`, and compare stock/mode `1`/mode `2`. This follow-up is now complete in the v2a comparison entry below.

## 2026-06-05 - S2 Moveprobe v2a Instrumentation Scaffold

### Experiment

Extended the S2 moveprobe scaffold so patched KTX can emit sampled final-command rows immediately before `trap_SetBotCMD(...)`.

Code changes:

- `experiments/ktx_moveprobe/frogbot-moveprobe.patch` now adds `k_fb_moveprobe_log_commands` and `k_fb_moveprobe_log_interval`.
- When command logging is enabled, KTX prints `FBMOVEPROBE_CMD` rows with final `msec`, angles, movement command values, buttons, and impulse.
- `scripts/run_bot_lab.py` / `scripts/run_frobodm2_lab.py` now accept `--moveprobe-log-commands` and `--moveprobe-log-interval`.
- The runner parses command rows from `screen.log` into `moveprobe-commands.json` and `moveprobe-commands.md`.

### Result

Implementation scaffold only at the time of this entry. The patched remote comparison run was performed afterward and is recorded in the next entry.

### Interpretation

This addresses the main uncertainty left by the first S2 probe: MVD movement metrics show behavioral consequences, but not the exact final command emitted by KTX. The next evidence-producing step is a three-run comparison with command logging enabled.

### Follow-up

Run three short `frobodm2` labs against patched KTX with `--moveprobe-log-commands`: stock mode `0`, forced-jump mode `1`, and fixed-command mode `2`. This follow-up is now complete in the v2a comparison entry below.

## 2026-06-05 - S2 Moveprobe v2a Emitted-Command Comparison

### Experiment

Temporarily deployed the v2a patched KTX build on `servexeri`, then ran three short `frobodm2` labs with command logging enabled:

```bash
python scripts/run_bot_lab.py --map frobodm2 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 0 --moveprobe-log-commands --moveprobe-log-interval 0.25
python scripts/run_bot_lab.py --map frobodm2 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 1 --moveprobe-log-commands --moveprobe-log-interval 0.25
python scripts/run_bot_lab.py --map frobodm2 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 2 --moveprobe-yaw 90 --moveprobe-forwardmove 800 --moveprobe-log-commands --moveprobe-log-interval 0.25
```

The deployed `qwprogs` target was backed up before patch deployment and restored afterward.

### Result

Stock mode `0`:

- Run `20260605T222006Z`.
- Parser exits: `json=0`, `md=0`, `events=1`.
- `196` final command rows parsed.
- Command rows showed variable yaw, forward, side, and normal firing button combinations (`0`, `1`, `3` for `/ bro`; `0`, `1` for `/ goldenboy`).
- Movement stayed plausible for a short Frogbot run: `/ bro` avg `363.5` qu/s, `/ goldenboy` avg `410.4` qu/s.

Forced-jump mode `1`:

- Run `20260605T222047Z`.
- Parser exits: `json=0`, `md=0`, `events=1`.
- `196` final command rows parsed.
- Command rows kept variable yaw/movement values while final buttons were jump-bearing (`2` or `3`), proving the forced-jump perturbation reaches `trap_SetBotCMD(...)`.
- Movement did not collapse overall, though `/ bro` had much more stationary time in this short run.

Fixed-command mode `2`:

- Run `20260605T222129Z`.
- Parser exits: `json=0`, `md=0`, `events=1`.
- `197` final command rows parsed.
- Both bots emitted constant `yaw=90`, `forward=800`, `side=0`, `up=0`, `buttons=2`, `impulse=0`.
- Movement collapsed: `/ bro` avg `1.9` qu/s, `/ goldenboy` avg `1.6` qu/s, both with `0.0%` air proxy and p95 speed `0.0` qu/s.

After all runs:

```text
servexeri ~/nquakesv/build/ktx: clean master...origin/master
deployed qwprogs hash matched backup
quakestat localhost:28599: DOWN
```

### Evidence

Artifacts:

- `artifacts/lab-runs/20260605T222006Z/run-summary.md`
- `artifacts/lab-runs/20260605T222006Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260605T222006Z/movement-metrics.md`
- `artifacts/lab-runs/20260605T222047Z/run-summary.md`
- `artifacts/lab-runs/20260605T222047Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260605T222047Z/movement-metrics.md`
- `artifacts/lab-runs/20260605T222129Z/run-summary.md`
- `artifacts/lab-runs/20260605T222129Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260605T222129Z/movement-metrics.md`

### Interpretation

The final command-emission seam is now directly observed. Mode `1` proves button perturbation reaches the final bot command while preserving Frogbot's variable movement shell. Mode `2` proves movement/yaw replacement reaches the final command, but also proves a blind fixed command is not useful movement.

S2 should continue with a tiny useful controller probe. The controller should be deliberately bounded, such as steering along a short direction/corridor while preserving combat and the existing route shell. It should be judged on command evidence plus behavior plausibility, not speed alone.

### Follow-up

Build moveprobe v2b: replace fixed mode `2` with, or add mode `3` for, a minimal controlled movement policy that uses a plausible yaw/direction source instead of a constant world yaw. Run it on a routed map and require both emitted-command evidence and movement plausibility checks before calling S2 complete.

## 2026-06-05 - S2 Moveprobe v2b Route-Yaw Probe

### Experiment

Added moveprobe mode `3` to the KTX experiment patch. Mode `3` uses Frogbot's current horizontal route movement direction (`self->fb.dir_move_`) as the desired yaw, emits a simple `forwardmove` command, allows optional `sidemove`/`upmove`, and forces jump. If the route direction is empty for a frame, the mode leaves the already-computed stock command intact for that frame.

Temporarily deployed the patched `qwprogs.so` to `servexeri`, ran one short `frobodm2` lab with command logging, then restored the deployed `qwprogs.so` from backup.

```bash
python scripts/run_bot_lab.py --map frobodm2 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 3 --moveprobe-log-commands --moveprobe-log-interval 0.25
```

### Result

Run `20260605T224811Z` completed the full lab loop:

- Parser exits: `json=0`, `md=0`, `events=1`.
- Command rows parsed: `197`.
- `/ bro`: `108/110` sampled commands emitted `forward=800`, `107/110` emitted buttons `2`, and yaw had `44` distinct sampled values. Movement was mixed: avg `137.4` qu/s, p95 `442.4` qu/s, air proxy `8.9%`, but stationary time was `59.7%`.
- `/ goldenboy`: `81/87` sampled commands emitted `forward=800`, `81/87` emitted buttons `2`, and yaw had `87` distinct sampled values. Movement was plausible: avg `330.8` qu/s, p95 `464.6` qu/s, over maxspeed `62.6%`, air proxy `27.6%`, stationary time `1.3%`.

After the run:

```text
deployed qwprogs hash matched backup
servexeri ~/nquakesv/build/ktx: clean master...origin/master
quakestat localhost:28599: DOWN
```

### Evidence

Artifacts:

- `artifacts/lab-runs/20260605T224811Z/run-summary.md`
- `artifacts/lab-runs/20260605T224811Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260605T224811Z/movement-metrics.md`

Validation:

- `python -m unittest discover -s tests -v`
- `python -m py_compile scripts\extract_movement_metrics.py scripts\run_frobodm2_lab.py scripts\run_bot_lab.py experiments\qw_min_client.py tests\test_extract_movement_metrics.py`
- `git diff --check -- . ':(exclude)experiments/ktx_moveprobe/frogbot-moveprobe.patch'`
- `git diff --check -- experiments/ktx_moveprobe/frogbot-moveprobe.patch`
- Local KTX `git apply --check` from a clean checkout.
- Remote KTX apply/build/deploy/reverse/rebuild completed cleanly.

### Interpretation

Mode `3` is meaningful partial progress. The emitted-command evidence shows the seam can drive route-derived yaw and forward movement, not only a constant fixed command. The behavior evidence is not strong enough to close S2: one bot moved plausibly, while the other still spent most of the run stationary.

The likely lesson is that "route-derived yaw plus always-forward/jump" is closer to useful movement than fixed world yaw, but it still conflicts with route state, aim, local geometry, or recovery in enough cases that a single successful-looking bot cannot be treated as a general movement replacement.

### Confidence

Medium.

The command evidence is direct and strong. The behavior evidence is mixed and comes from one short run, so the conclusion should remain cautious.

### Follow-up

Run moveprobe v2c before advancing to S3: make the plausibility gate explicit, repeat mode `3` across at least `frobodm2` and `dm3` or multiple short runs, and summarize stationary/low-speed ratios plus route-yaw command coverage. If the route-yaw probe is still split, refine fallback/recovery rather than declaring S2 complete.

## 2026-06-05 - S2 Moveprobe v2c Repeatability and Plausibility Gate

### Experiment

Added `scripts/summarize_moveprobe_plausibility.py`, a small artifact summarizer that combines per-run `movement-metrics.json` and `moveprobe-commands.json` into an explicit gate:

- expected forward command coverage >= `80%`
- jump-button command coverage >= `80%`
- distinct sampled yaw values >= `10`
- stationary time <= `25%`
- low-speed time <= `40%`

The goal was to make the "not speed alone" rule executable before deciding whether route-yaw mode `3` is enough S2 evidence.

Then temporarily deployed the patched KTX build again and ran fresh route-yaw mode `3` repeats:

```bash
python scripts/run_bot_lab.py --map frobodm2 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 3 --moveprobe-log-commands --moveprobe-log-interval 0.25
python scripts/run_bot_lab.py --map dm3 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 3 --moveprobe-log-commands --moveprobe-log-interval 0.25
```

### Result

Fresh `frobodm2` repeat `20260605T225720Z`:

- Parser exits: `json=0`, `md=0`, `events=1`.
- Command rows parsed: `197`.
- `/ bro`: PASS, `110` commands, forward coverage `82.7%`, jump coverage `82.7%`, `107` distinct sampled yaws, avg `278.1` qu/s, p95 `462.6` qu/s, stationary `6.5%`, low-speed `22.1%`, air proxy `28.7%`.
- `/ goldenboy`: PASS, `87` commands, forward coverage `95.4%`, jump coverage `95.4%`, `87` distinct sampled yaws, avg `370.3` qu/s, p95 `466.7` qu/s, stationary `0.2%`, low-speed `5.1%`, air proxy `26.2%`.
- No frags recorded in the short run, though command logs included firing-button combinations (`1` and `3`).

Fresh `dm3` repeat `20260605T225802Z`:

- Parser exits: `json=0`, `md=0`, `events=1`.
- Command rows parsed: `196`.
- `/ bro`: PASS, `110` commands, forward coverage `99.1%`, jump coverage `99.1%`, `110` distinct sampled yaws, avg `299.8` qu/s, p95 `450.4` qu/s, stationary `1.1%`, low-speed `1.4%`, air proxy `58.5%`.
- `/ goldenboy`: PASS, `86` commands, forward coverage `95.3%`, jump coverage `95.3%`, `84` distinct sampled yaws, avg `393.6` qu/s, p95 `462.7` qu/s, stationary `0.0%`, low-speed `1.7%`, air proxy `7.9%`.
- No frags recorded in the short run.

After the runs:

```text
deployed qwprogs hash matched backup
servexeri ~/nquakesv/build/ktx: clean master...origin/master
quakestat localhost:28599: DOWN
```

### Evidence

Artifacts:

- `artifacts/lab-runs/20260605T225720Z/run-summary.md`
- `artifacts/lab-runs/20260605T225720Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260605T225720Z/movement-metrics.md`
- `artifacts/lab-runs/20260605T225802Z/run-summary.md`
- `artifacts/lab-runs/20260605T225802Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260605T225802Z/movement-metrics.md`
- `artifacts/lab-runs/moveprobe-v2c-fresh-summary.md`

Validation:

- `python -m unittest discover -s tests -v`
- `python -m py_compile scripts\extract_movement_metrics.py scripts\run_frobodm2_lab.py scripts\run_bot_lab.py scripts\summarize_moveprobe_plausibility.py experiments\qw_min_client.py tests\test_extract_movement_metrics.py tests\test_moveprobe_plausibility.py`
- `git diff --check -- . ':(exclude)experiments/ktx_moveprobe/frogbot-moveprobe.patch'`
- Local KTX `git apply --check` from a clean checkout.
- Remote KTX apply/build/deploy/reverse/rebuild completed cleanly.

### Interpretation

S2 movement override feasibility is provisionally satisfied pending review. The final command seam can be observed and replaced, fixed-command replacement failed as expected, and route-yaw mode `3` produced repeatable movement that passes an explicit non-speed-only gate on two routed maps.

This does not mean Komodobots has a realistic movement brain. Mode `3` still commandeers view yaw, so aim/movement separation and combat realism remain unresolved. The short v2c runs did not record frags. The result should be treated as permission to propose S3, not as a final controller.

### Confidence

Medium-high for S2 movement-feasibility.

Medium-low for player-believability implications, because aim/combat separation is still open and the runs are short.

### Follow-up

Ask Claude to review S2 exit. If accepted, start S3a: a bounded bunnyjump-primitive probe that compares a minimal yaw/strafe/jump policy against mode `3` and baseline metrics, uses the v2c plausibility gate, and keeps combat/aim limitations explicit.

## 2026-06-05 - S3a Bounded Alternating-Strafe Probe

### Experiment

Added moveprobe mode `4` to the KTX experiment patch. Mode `4` uses the same route-derived yaw as mode `3`, emits `forwardmove`, alternates sidemove sign roughly five times per second with a bot-slot offset, and forces jump. If `k_fb_moveprobe_sidemove` is `0`, mode `4` uses a default `400` sidemove magnitude.

Updated the runner to accept `--moveprobe-mode 4` and extended `scripts/summarize_moveprobe_plausibility.py` with `--min-side-ratio`, so S3a can require nonzero side command coverage.

Temporarily deployed the patched KTX build again and ran:

```bash
python scripts/run_bot_lab.py --map frobodm2 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 4 --moveprobe-log-commands --moveprobe-log-interval 0.25
python scripts/run_bot_lab.py --map dm3 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 4 --moveprobe-log-commands --moveprobe-log-interval 0.25
python scripts/summarize_moveprobe_plausibility.py 20260605T231033Z 20260605T231115Z --min-side-ratio 0.8 --output-md artifacts/lab-runs/moveprobe-s3a-summary.md
```

### Result

Fresh `frobodm2` S3a run `20260605T231033Z`:

- Parser exits: `json=0`, `md=0`, `events=1`.
- Command rows parsed: `197`.
- Command logs showed side values `[-400, 0, 400]` for both bots.
- `/ bro`: PASS, forward/side/jump coverage `94.5%`, `109` distinct sampled yaws, avg `281.4` qu/s, p95 `358.9` qu/s, stationary `1.3%`, low-speed `12.3%`, air proxy `20.1%`.
- `/ goldenboy`: PASS, forward/side/jump coverage `96.6%`, `82` distinct sampled yaws, avg `294.4` qu/s, p95 `364.5` qu/s, stationary `0.6%`, low-speed `9.3%`, air proxy `9.8%`.
- One RL frag: `/ bro` killed `/ goldenboy` at `12866` ms.

Fresh `dm3` S3a run `20260605T231115Z`:

- Parser exits: `json=0`, `md=0`, `events=1`.
- Command rows parsed: `196`.
- Command logs showed side values `[-400, 0, 400]` for both bots.
- `/ bro`: FAIL, forward/side/jump coverage `95.5%`, `108` distinct sampled yaws, avg `142.4` qu/s, p95 `349.2` qu/s, stationary `0.1%`, low-speed `63.0%`, air proxy `54.9%`.
- `/ goldenboy`: PASS, forward/side/jump coverage `93.0%`, `85` distinct sampled yaws, avg `151.6` qu/s, p95 `334.1` qu/s, stationary `1.6%`, low-speed `39.0%`, air proxy `58.0%`.

After the runs:

```text
deployed qwprogs hash matched backup
servexeri ~/nquakesv/build/ktx: clean master...origin/master
quakestat localhost:28599: DOWN
```

### Evidence

Artifacts:

- `artifacts/lab-runs/20260605T231033Z/run-summary.md`
- `artifacts/lab-runs/20260605T231033Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260605T231033Z/movement-metrics.md`
- `artifacts/lab-runs/20260605T231115Z/run-summary.md`
- `artifacts/lab-runs/20260605T231115Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260605T231115Z/movement-metrics.md`
- `artifacts/lab-runs/moveprobe-s3a-summary.md`

### Interpretation

S3a proves that a bounded strafe signal can be emitted and measured through the same final-command seam. It does not prove a useful bunnyjump primitive yet. Compared with route-yaw mode `3`, mode `4` reduced p95 speed on `frobodm2` and produced poor low-speed behavior on `dm3`, especially for `/ bro`.

The most likely conclusion is that hard alternating `+/-400` sidemove at this cadence is too crude and map-sensitive. The next useful step should be parameter diagnosis, not a larger controller.

### Confidence

Medium for the command-emission claim.

Medium-high that this exact mode `4` is not yet a better movement primitive than mode `3`.

### Follow-up

Ask Claude to review the mixed S3a result. Proposed S3b: run a tiny parameter sweep on `dm3`, starting with smaller `--moveprobe-sidemove` magnitudes such as `200` and `300`, or add a cvar for slower alternation cadence if needed. Keep `--min-side-ratio 0.8` and the low-speed gate.

## 2026-06-05 - S3b Sidemove Magnitude Diagnosis on `dm3`

### Experiment

Reused moveprobe mode `4` and ran a minimal `dm3` sidemove sweep:

```bash
python scripts/run_bot_lab.py --map dm3 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 4 --moveprobe-sidemove 200 --moveprobe-log-commands --moveprobe-log-interval 0.25
python scripts/run_bot_lab.py --map dm3 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 4 --moveprobe-sidemove 300 --moveprobe-log-commands --moveprobe-log-interval 0.25
python scripts/summarize_moveprobe_plausibility.py 20260605T231737Z 20260605T231819Z --min-side-ratio 0.8 --output-md artifacts/lab-runs/moveprobe-s3b-summary.md
```

### Result

`sidemove=200`, run `20260605T231737Z`:

- Parser exits: `json=0`, `md=0`, `events=1`.
- Command rows parsed: `196`.
- Command logs showed side values `[-200, 0, 200]`.
- `/ bro`: PASS, forward/side/jump coverage `88.2%`, `100` distinct sampled yaws, avg `228.5` qu/s, p95 `387.6` qu/s, stationary `7.4%`, low-speed `26.9%`, air proxy `17.4%`.
- `/ goldenboy`: PASS, forward/side/jump coverage `98.8%`, `86` distinct sampled yaws, avg `197.3` qu/s, p95 `377.7` qu/s, stationary `0.0%`, low-speed `28.3%`, air proxy `49.8%`.

`sidemove=300`, run `20260605T231819Z`:

- Parser exits: `json=0`, `md=0`, `events=1`.
- Command rows parsed: `196`.
- Command logs showed side values `[-300, 0, 300]`.
- `/ bro`: FAIL, forward/side/jump coverage `93.6%`, `108` distinct sampled yaws, avg `174.0` qu/s, p95 `357.6` qu/s, stationary `0.7%`, low-speed `51.1%`, air proxy `48.9%`.
- `/ goldenboy`: PASS, forward/side/jump coverage `91.9%`, `83` distinct sampled yaws, avg `291.9` qu/s, p95 `374.7` qu/s, stationary `0.0%`, low-speed `5.6%`, air proxy `12.4%`.

After the runs:

```text
deployed qwprogs hash matched backup
servexeri ~/nquakesv/build/ktx: clean master...origin/master
quakestat localhost:28599: DOWN
```

### Evidence

Artifacts:

- `artifacts/lab-runs/20260605T231737Z/run-summary.md`
- `artifacts/lab-runs/20260605T231737Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260605T231737Z/movement-metrics.md`
- `artifacts/lab-runs/20260605T231819Z/run-summary.md`
- `artifacts/lab-runs/20260605T231819Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260605T231819Z/movement-metrics.md`
- `artifacts/lab-runs/moveprobe-s3b-summary.md`

### Interpretation

S3b narrowed the failure. On `dm3`, sidemove `200` passes the side/plausibility gate for both bots, while `300` and the previous default `400` are too disruptive for at least `/ bro`.

This is still not a stronger controller than route-yaw mode `3`: average speeds are lower than the v2c `dm3` route-yaw run, and neither S3b run recorded frags. But it gives a safer strafe magnitude for the next bounded movement-literacy probe.

### Confidence

Medium.

The command coverage evidence is direct. The behavioral conclusion is based on one run per magnitude, so it needs repeat/cross-map validation.

### Follow-up

Ask Claude to review S3b. Proposed S3c: validate `sidemove=200` across `frobodm2` and a repeat `dm3` run, then compare against mode `3` and mode `4` default `400`. Do not add cadence or state until `200` is repeatable.

## 2026-06-05 - S3c Cross-Map Validation for `sidemove=200`

### Experiment

Temporarily deployed the current patched KTX build and ran mode `4` with `--moveprobe-sidemove 200` on the two routed maps:

```bash
python scripts/run_bot_lab.py --map frobodm2 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 4 --moveprobe-sidemove 200 --moveprobe-log-commands --moveprobe-log-interval 0.25
python scripts/run_bot_lab.py --map dm3 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 4 --moveprobe-sidemove 200 --moveprobe-log-commands --moveprobe-log-interval 0.25
python scripts/summarize_moveprobe_plausibility.py 20260605T233120Z 20260605T233202Z --min-side-ratio 0.8 --output-md artifacts/lab-runs/moveprobe-s3c-summary.md
```

### Result

`frobodm2`, run `20260605T233120Z`:

- Parser exits: `json=0`, `md=0`, `events=1`.
- Command rows parsed: `197`.
- `/ bro`: PASS, forward/side/jump coverage `93.6%`, `109` distinct sampled yaws, avg `279.6` qu/s, p95 `387.6` qu/s, stationary `0.8%`, low-speed `7.4%`, air proxy `19.8%`.
- `/ goldenboy`: PASS, forward/side/jump coverage `95.4%`, `84` distinct sampled yaws, avg `306.7` qu/s, p95 `386.5` qu/s, stationary `0.9%`, low-speed `4.6%`, air proxy `10.2%`.
- One RL frag: `/ bro` killed `/ goldenboy` at `9642` ms.

`dm3`, run `20260605T233202Z`:

- Parser exits: `json=0`, `md=0`, `events=1`.
- Command rows parsed: `196`.
- `/ bro`: PASS, forward/side/jump coverage `97.3%`, `109` distinct sampled yaws, avg `248.8` qu/s, p95 `383.1` qu/s, stationary `0.1%`, low-speed `16.7%`, air proxy `32.0%`.
- `/ goldenboy`: PASS, forward/side/jump coverage `93.0%`, `86` distinct sampled yaws, avg `293.3` qu/s, p95 `386.5` qu/s, stationary `0.0%`, low-speed `10.9%`, air proxy `14.7%`.

After the runs:

```text
deployed qwprogs hash matched backup
servexeri ~/nquakesv/build/ktx: clean master...origin/master
quakestat localhost:28599: DOWN
```

### Evidence

Artifacts:

- `artifacts/lab-runs/20260605T233120Z/run-summary.md`
- `artifacts/lab-runs/20260605T233120Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260605T233120Z/movement-metrics.md`
- `artifacts/lab-runs/20260605T233202Z/run-summary.md`
- `artifacts/lab-runs/20260605T233202Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260605T233202Z/movement-metrics.md`
- `artifacts/lab-runs/moveprobe-s3c-summary.md`

### Interpretation

S3c validates `sidemove=200` as the first repeatable mode `4` route-yaw strafe candidate. It passed the side/plausibility gate on both routed maps and avoided the `dm3` low-speed failure seen with `300` and `400`.

This is still not a final bunnyjump or player-realism controller. Compared with mode `3`, mode `4` with `sidemove=200` lowers high-speed spikes and remains view-yaw-commandeering. It is useful movement-literacy evidence, not a believable combat movement solution.

### Confidence

Medium-high for the narrow claim that `sidemove=200` generalizes across the two current routed maps.

Medium-low for any claim beyond that, because both runs still rely on route-yaw aim commandeering.

### Follow-up

Ask Claude to review S3c. Proposed S3d: add the smallest aim-independent movement-vector probe. Preserve the bot's real combat view angle, compute `forwardmove`/`sidemove` from desired route direction relative to that view, and compare against mode `4 --moveprobe-sidemove 200` with the same command/plausibility gates.
