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

## 2026-06-05 - S3d Aim-Independent Movement-Vector Probe

### Experiment

Added moveprobe mode `5`. Unlike mode `3`/`4`, mode `5` does not set route yaw into `self->fb.desired_angle`. It preserves the bot's current combat view yaw, builds a route-relative movement vector with optional alternating `sidemove`, then projects that world-space intent into local `forwardmove`/`sidemove` commands.

Because local `forwardmove` is expected to vary when the view yaw is preserved, the plausibility helper now supports `--min-horizontal-ratio`. The S3d summary disables exact-forward coverage and requires horizontal/side/jump command coverage instead.

Temporarily deployed the patched KTX build and ran:

```bash
python scripts/run_bot_lab.py --map frobodm2 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 5 --moveprobe-sidemove 200 --moveprobe-log-commands --moveprobe-log-interval 0.25
python scripts/run_bot_lab.py --map dm3 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 5 --moveprobe-sidemove 200 --moveprobe-log-commands --moveprobe-log-interval 0.25
python scripts/summarize_moveprobe_plausibility.py 20260605T234620Z 20260605T234701Z --min-forward-ratio 0 --min-horizontal-ratio 0.8 --min-side-ratio 0.8 --output-md artifacts/lab-runs/moveprobe-s3d-summary.md
```

### Result

`frobodm2`, run `20260605T234620Z`:

- Parser exits: `json=0`, `md=0`, `events=1`.
- Command rows parsed: `197`.
- `/ bro`: FAIL, forward/horizontal/side/jump coverage `0.0%`/`96.4%`/`96.4%`/`96.4%`, `45` distinct sampled yaws, avg `61.2` qu/s, p95 `348.6` qu/s, stationary `74.7%`, low-speed `79.2%`, air proxy `8.0%`.
- `/ goldenboy`: PASS, forward/horizontal/side/jump coverage `0.0%`/`85.1%`/`85.1%`/`85.1%`, `78` distinct sampled yaws, avg `256.0` qu/s, p95 `381.5` qu/s, stationary `2.8%`, low-speed `21.2%`, air proxy `26.9%`.
- One SSG frag: `/ goldenboy` killed `/ bro` at `22855` ms.

`dm3`, run `20260605T234701Z`:

- Parser exits: `json=0`, `md=0`, `events=1`.
- Command rows parsed: `195`.
- `/ bro`: FAIL, forward/horizontal/side/jump coverage `0.9%`/`93.6%`/`93.6%`/`93.6%`, `59` distinct sampled yaws, avg `144.4` qu/s, p95 `367.8` qu/s, stationary `40.5%`, low-speed `53.8%`, air proxy `14.8%`.
- `/ goldenboy`: PASS, forward/horizontal/side/jump coverage `0.0%`/`98.8%`/`98.8%`/`98.8%`, `84` distinct sampled yaws, avg `219.6` qu/s, p95 `381.4` qu/s, stationary `1.5%`, low-speed `24.7%`, air proxy `32.8%`.

After the runs:

```text
deployed qwprogs hash matched backup
servexeri ~/nquakesv/build/ktx: clean master...origin/master
quakestat localhost:28599: DOWN
```

### Evidence

Artifacts:

- `artifacts/lab-runs/20260605T234620Z/run-summary.md`
- `artifacts/lab-runs/20260605T234620Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260605T234620Z/movement-metrics.md`
- `artifacts/lab-runs/20260605T234701Z/run-summary.md`
- `artifacts/lab-runs/20260605T234701Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260605T234701Z/movement-metrics.md`
- `artifacts/lab-runs/moveprobe-s3d-summary.md`

### Interpretation

S3d proves the command seam can emit aim-independent route/strafe commands without taking over view yaw. The command gate passed for both bots on both maps.

Behavior did not generalize. `/ goldenboy` passed both maps, but `/ bro` failed stationary/low-speed gates on both maps. This suggests the next problem is not basic command emission; it is the aim/move conflict created when the bot tries to preserve combat view while following route intent.

The current command logs show many large negative local forward values in mode `5`. That is compatible with a bot trying to move route-relative while looking away from the route, but the current log does not include route yaw or yaw-delta context.

### Confidence

High for the command-emission claim.

Medium for the behavioral split, based on one run per map.

Low for root cause. The next run needs route-vs-view diagnostics before adding a corrective policy.

### Follow-up

Ask Claude to review S3d. Proposed S3e: add route-vs-view diagnostics to the command log and summarizer. Capture route yaw, preserved view yaw, yaw delta, negative-forward/backward-command ratio, and compare those against stationary/low-speed behavior for the mode `5` split before changing the controller policy.

## 2026-06-06 - S3e Aim/Move Diagnostic Logging

### Experiment

Added route-vs-view diagnostics to the moveprobe command log and plausibility summary:

- KTX command rows now append `diag=route_yaw,view_yaw,yaw_delta,backward`.
- `scripts/run_frobodm2_lab.py` parses the optional diagnostic fields into `moveprobe-commands.json` and `moveprobe-commands.md`.
- `scripts/summarize_moveprobe_plausibility.py` reports backward-command ratio plus absolute yaw-delta average, p90, and ratio above 90 degrees.

Temporarily deployed the patched KTX build and ran:

```bash
python scripts/run_bot_lab.py --map frobodm2 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 5 --moveprobe-sidemove 200 --moveprobe-log-commands --moveprobe-log-interval 0.25
python scripts/run_bot_lab.py --map dm3 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 5 --moveprobe-sidemove 200 --moveprobe-log-commands --moveprobe-log-interval 0.25
python scripts/summarize_moveprobe_plausibility.py 20260606T000331Z 20260606T000414Z --min-forward-ratio 0 --min-horizontal-ratio 0.8 --min-side-ratio 0.8 --output-md artifacts/lab-runs/moveprobe-s3e-summary.md
```

### Result

`frobodm2`, run `20260606T000331Z`:

- Parser exits: `json=0`, `md=0`, `events=1`.
- Command rows parsed: `196`.
- `/ bro`: PASS, horizontal/side/jump coverage `96.4%`, backward commands `22.7%`, absolute yaw-delta avg `53.1`, p90 `110.9`, above-90 ratio `19.1%`, avg `264.5` qu/s, p95 `382.4` qu/s, stationary `3.3%`, low-speed `14.3%`.
- `/ goldenboy`: PASS, horizontal/side/jump coverage `98.8%`, backward commands `14.0%`, absolute yaw-delta avg `44.2`, p90 `91.8`, above-90 ratio `10.5%`, avg `316.7` qu/s, p95 `389.1` qu/s, stationary `0.5%`, low-speed `4.0%`.
- One SSG frag: `/ goldenboy` killed `/ bro` at `24532` ms.

`dm3`, run `20260606T000414Z`:

- Parser exits: `json=0`, `md=0`, `events=1`.
- Command rows parsed: `195`.
- `/ bro`: FAIL, horizontal/side/jump coverage `99.1%`, backward commands `41.3%`, absolute yaw-delta avg `79.6`, p90 `154.7`, above-90 ratio `43.1%`, avg `149.8` qu/s, p95 `370.2` qu/s, stationary `0.1%`, low-speed `43.1%`.
- `/ goldenboy`: FAIL, horizontal/side/jump coverage `98.8%`, backward commands `14.0%`, absolute yaw-delta avg `44.7`, p90 `99.4`, above-90 ratio `16.3%`, avg `168.5` qu/s, p95 `382.1` qu/s, stationary `4.9%`, low-speed `52.8%`.

After the runs:

```text
deployed qwprogs hash matched backup
servexeri ~/nquakesv/build/ktx: clean master...origin/master
quakestat localhost:28599: DOWN
```

### Evidence

Artifacts:

- `artifacts/lab-runs/20260606T000331Z/run-summary.md`
- `artifacts/lab-runs/20260606T000331Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260606T000331Z/movement-metrics.md`
- `artifacts/lab-runs/20260606T000414Z/run-summary.md`
- `artifacts/lab-runs/20260606T000414Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260606T000414Z/movement-metrics.md`
- `artifacts/lab-runs/moveprobe-s3e-summary.md`
- `experiments/ktx_moveprobe/evidence/moveprobe-s3e-summary.md`
- `experiments/ktx_moveprobe/evidence/moveprobe-s3e-summary.json`

### Interpretation

S3e supports the yaw-conflict hypothesis only partially. `/ bro` on `dm3` has the clearest failure signature: high backward-command ratio, high yaw-delta p90, many samples above 90 degrees, and a failing low-speed gate.

The same explanation is not sufficient by itself. `/ goldenboy` on `dm3` also failed the low-speed gate while its backward-command ratio stayed at `14.0%`, close to its passing `frobodm2` row. The next corrective policy must therefore be small and judged as a falsifiable probe, not as a confirmed root-cause fix.

### Confidence

High for the diagnostic logging and summary fields.

Medium for the claim that yaw delta/backward commands contribute to the split.

Low for any single-cause explanation.

### Follow-up

Ask Claude to review S3e. Proposed S3f: add the smallest no-backpedal/forward-hemisphere correction to mode `5`. If projected local `forwardmove` is negative, clamp or remap it so the bot strafes instead of backpedaling, then run `dm3` first with the same horizontal/side/jump and low-speed gates. If that does not improve the `dm3` low-speed rows, stop policy tuning and inspect route state/obstruction rather than adding controller complexity.

## 2026-06-06 - S3f No-Backpedal Correction Probe

### Experiment

Added moveprobe mode `6`, a small corrective variant of mode `5`.

Mode `6` preserves combat view yaw and uses the same route/strafe projection as mode `5`. If the projected local `forwardmove` is negative, it folds that removed backpedal magnitude into local `sidemove` and clamps local forward to `0`.

Temporarily deployed the patched KTX build and ran `dm3` first. Because `dm3` improved and passed, repeated on `frobodm2`:

```bash
python scripts/run_bot_lab.py --map dm3 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 6 --moveprobe-sidemove 200 --moveprobe-log-commands --moveprobe-log-interval 0.25
python scripts/run_bot_lab.py --map frobodm2 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 6 --moveprobe-sidemove 200 --moveprobe-log-commands --moveprobe-log-interval 0.25
python scripts/summarize_moveprobe_plausibility.py 20260606T001705Z 20260606T001825Z --min-forward-ratio 0 --min-horizontal-ratio 0.8 --min-side-ratio 0.8 --output-md artifacts/lab-runs/moveprobe-s3f-summary.md
```

### Result

`dm3`, run `20260606T001705Z`:

- Parser exits: `json=0`, `md=0`, `events=1`.
- Command rows parsed: `196`.
- `/ bro`: PASS, horizontal/side/jump coverage `93.6%`, backward commands `0.0%`, absolute yaw-delta avg `82.2`, p90 `163.1`, above-90 ratio `43.6%`, avg `167.4` qu/s, p95 `362.9` qu/s, stationary `3.1%`, low-speed `38.3%`.
- `/ goldenboy`: PASS, horizontal coverage `88.4%`, side coverage `87.2%`, jump coverage `88.4%`, backward commands `0.0%`, absolute yaw-delta avg `66.3`, p90 `124.2`, above-90 ratio `40.7%`, avg `236.0` qu/s, p95 `382.4` qu/s, stationary `1.8%`, low-speed `24.4%`.
- One SG frag: `/ bro` killed `/ goldenboy` at `11126` ms.

`frobodm2`, run `20260606T001825Z`:

- Parser exits: `json=0`, `md=0`, `events=1`.
- Command rows parsed: `197`.
- `/ bro`: PASS, horizontal/side/jump coverage `94.5%`, backward commands `0.0%`, absolute yaw-delta avg `84.3`, p90 `167.1`, above-90 ratio `50.0%`, avg `246.3` qu/s, p95 `361.0` qu/s, stationary `1.7%`, low-speed `13.8%`.
- `/ goldenboy`: PASS, horizontal/side/jump coverage `85.1%`, backward commands `0.0%`, absolute yaw-delta avg `85.8`, p90 `163.2`, above-90 ratio `51.7%`, avg `217.3` qu/s, p95 `374.6` qu/s, stationary `3.6%`, low-speed `26.8%`.
- One GL frag: `/ goldenboy` killed `/ bro` at `13358` ms.

After both deployments:

```text
deployed qwprogs hash matched backup
servexeri ~/nquakesv/build/ktx: clean master...origin/master
quakestat localhost:28599: DOWN
```

### Evidence

Artifacts:

- `artifacts/lab-runs/20260606T001705Z/run-summary.md`
- `artifacts/lab-runs/20260606T001705Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260606T001705Z/movement-metrics.md`
- `artifacts/lab-runs/20260606T001825Z/run-summary.md`
- `artifacts/lab-runs/20260606T001825Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260606T001825Z/movement-metrics.md`
- `artifacts/lab-runs/moveprobe-s3f-summary.md`
- `experiments/ktx_moveprobe/evidence/moveprobe-s3f-summary.md`
- `experiments/ktx_moveprobe/evidence/moveprobe-s3f-summary.json`

### Interpretation

S3f is positive corrective evidence. Removing sustained backpedal commands flipped the `dm3` mode `5` low-speed failure into a pass for both bots, then repeated as a pass on `frobodm2`.

It is not a final movement policy. The command logs show very large folded side commands, often near or above `1100`, while yaw deltas remain large. That may pass this coarse plausibility gate but is unlikely to be the right durable command surface for believable player movement.

### Confidence

High for the claim that mode `6` removes sampled backward commands and passes the current gate on both routed maps.

Medium for the claim that no-backpedal behavior is a useful corrective direction.

Low for the realism of the current folded side magnitudes.

### Follow-up

Ask Claude to review S3f. Proposed S3g: keep the no-backpedal correction, but add a bounded-command variant that caps or normalizes local `forwardmove`/`sidemove` magnitudes after projection. Rerun `dm3` and `frobodm2` with the same gates and compare against mode `6`. Treat S3g as the final command-magnitude probe before branching to route/obstruction inspection or S4 human comparison; do not keep tuning tiny command heuristics only to satisfy the current gates.

## 2026-06-06 - S3g Bounded No-Backpedal Command Probe

### Experiment

Added moveprobe mode `7`, a bounded variant of mode `6`.

Mode `7` preserves combat view yaw, uses the same route/strafe projection as mode `5`, applies the same no-backpedal fold as mode `6`, then normalizes local horizontal command magnitude back down to the original route/strafe intent magnitude. With `forwardmove=800` and `sidemove=200`, the expected cap is about `824.6`.

Temporarily deployed the patched KTX build and ran `dm3` first. Because `dm3` passed and the magnitude cap held, repeated on `frobodm2`:

```bash
python scripts/run_bot_lab.py --map dm3 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 7 --moveprobe-sidemove 200 --moveprobe-log-commands --moveprobe-log-interval 0.25
python scripts/run_bot_lab.py --map frobodm2 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 7 --moveprobe-sidemove 200 --moveprobe-log-commands --moveprobe-log-interval 0.25
python scripts/summarize_moveprobe_plausibility.py 20260606T003718Z 20260606T003808Z --min-forward-ratio 0 --min-horizontal-ratio 0.8 --min-side-ratio 0.8 --output-md artifacts/lab-runs/moveprobe-s3g-summary.md
```

### Result

`dm3`, run `20260606T003718Z`:

- Parser exits: `json=0`, `md=0`, `events=1`.
- Command rows parsed: `195`.
- `/ bro`: PASS, horizontal/side/jump coverage `98.2%`, backward commands `0.0%`, max horizontal command `824.5`, absolute yaw-delta avg `85.8`, p90 `157.7`, avg `190.1` qu/s, p95 `361.0` qu/s, stationary `0.4%`, low-speed `26.1%`.
- `/ goldenboy`: PASS, horizontal/side/jump coverage `94.2%`, backward commands `0.0%`, max horizontal command `824.5`, absolute yaw-delta avg `77.8`, p90 `157.5`, avg `248.2` qu/s, p95 `375.3` qu/s, stationary `2.5%`, low-speed `18.9%`.
- One SG frag: `/ bro` killed `/ goldenboy` at `12846` ms.

`frobodm2`, run `20260606T003808Z`:

- Parser exits: `json=0`, `md=0`, `events=1`.
- Command rows parsed: `197`.
- `/ bro`: PASS, horizontal/side/jump coverage `99.1%`, backward commands `0.0%`, max horizontal command `824.5`, absolute yaw-delta avg `59.9`, p90 `135.5`, avg `322.0` qu/s, p95 `386.2` qu/s, stationary `0.1%`, low-speed `5.5%`.
- `/ goldenboy`: PASS, horizontal/side/jump coverage `98.9%`, backward commands `0.0%`, max horizontal command `824.6`, absolute yaw-delta avg `65.8`, p90 `149.3`, avg `312.1` qu/s, p95 `392.5` qu/s, stationary `0.0%`, low-speed `2.7%`.
- No frags recorded.

After both deployments:

```text
deployed qwprogs hash matched backup
servexeri ~/nquakesv/build/ktx: clean master...origin/master
quakestat localhost:28599: DOWN
```

### Evidence

Artifacts:

- `artifacts/lab-runs/20260606T003718Z/run-summary.md`
- `artifacts/lab-runs/20260606T003718Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260606T003718Z/movement-metrics.md`
- `artifacts/lab-runs/20260606T003808Z/run-summary.md`
- `artifacts/lab-runs/20260606T003808Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260606T003808Z/movement-metrics.md`
- `artifacts/lab-runs/moveprobe-s3g-summary.md`
- `experiments/ktx_moveprobe/evidence/moveprobe-s3g-summary.md`
- `experiments/ktx_moveprobe/evidence/moveprobe-s3g-summary.json`

### Interpretation

S3g is stronger than S3f as an S3 movement-literacy candidate. It preserves combat yaw, removes sampled backward commands, passes the current gate on both routed maps, and bounds sampled horizontal command magnitude near `824.6` instead of relying on folded side values around `1100`.

This is still not a realism verdict. The current gate is project-defined and lacks a human reference distribution. More command tuning would risk optimizing the gate rather than proving believability.

### Confidence

High for the claim that mode `7` passes the current S3 gate on `dm3` and `frobodm2` while bounding sampled command magnitude.

Medium for treating mode `7` as the best current S3 movement-literacy candidate.

Low for any claim that mode `7` is human-like before human-demo comparison.

### Follow-up

Ask Claude to review S3g. Proposed S4a: build the first human-demo comparison scaffold. Inventory candidate human MVDs, starting with local files under `C:\Users\benya\projects\quakeworld\data\quake-development\clients\xerialqw-bench\qw\matchinfo\demos`, parse one or more through the existing MVD movement pipeline, record whether a real DM2 human comparison set is present or missing, and compare S3g bot movement metrics against whatever human baseline is defensible. Do not add another movement-command heuristic until the gate has a human anchor.

## 2026-06-06 - S4a Human-Demo Comparison Scaffold

### Experiment

Added `scripts/analyze_human_mvd.py`, a local human-demo inventory and parser scaffold. It inventories `.mvd` files, copies a selected demo into `artifacts/human-demos/<run-id>/`, parses it with `qw-analyze-v20`, runs the existing movement metrics extractor, and writes compact JSON/Markdown summaries.

Ran:

```bash
python scripts/analyze_human_mvd.py --demo 1on1_reppie_vs_locust_aerowalk.mvd --run-id s4a-1on1-reppie-vs-locust-aerowalk
```

### Result

Local inventory root:

```text
C:\Users\benya\projects\quakeworld\data\quake-development\clients\xerialqw-bench\qw\matchinfo\demos
```

Inventory result:

- `5` demos inventoried.
- Inferred maps: `aerowalk`, `e1m2`, `ztricks`, `ztricks2`.
- Filename-inferred `dm2` candidates: `0`.
- Map inference method: filename-token heuristic, not content parsing.

Parsed demo `1on1_reppie_vs_locust_aerowalk.mvd`:

- Run id: `s4a-1on1-reppie-vs-locust-aerowalk`.
- Parser exits: `json=0`, `md=0`, `events=1`.
- Event count: `58,517`; position events: `35,447`.
- Match title/map: `Aerowalk` / `aerowalk`.
- Duration: `600057` ms.
- Active movement players: `reppie` and `locust`.
- Movement samples were clamped to the parsed `600057` ms match duration.
- `reppie`: active `597.646` s, avg `324.0` qu/s, p95 `537.4`, stationary `4.6%`, low-speed `11.0%`, airborne proxy `44.8%`, cadence `40.8`/min.
- `locust`: active `597.699` s, avg `318.5` qu/s, p95 `519.0`, stationary `5.2%`, low-speed `11.1%`, airborne proxy `39.6%`, cadence `34.8`/min.
- Six named slots with less than `1` second active time, fewer than `10` samples, or less than `100` qu horizontal distance were excluded from the compact active-player summary.

### Evidence

Artifacts:

- `artifacts/human-demos/human-demo-inventory.md`
- `artifacts/human-demos/human-demo-s4a-summary.md`
- `artifacts/human-demos/s4a-1on1-reppie-vs-locust-aerowalk/movement-metrics.md`
- `experiments/human_comparison/evidence/human-demo-inventory.md`
- `experiments/human_comparison/evidence/human-demo-inventory.json`
- `experiments/human_comparison/evidence/human-demo-s4a-summary.md`
- `experiments/human_comparison/evidence/human-demo-s4a-summary.json`

### Interpretation

S4a proves the existing parser and movement-metrics pipeline can process a human MVD and produce compact evidence alongside S3 bot summaries.

It does not prove S3g is human-like. The parsed human demo is an `aerowalk` duel, while S3g bot evidence is on `dm3` and `frobodm2`. The local inventory also has no filename-inferred `dm2` demo. Any direct S3g-vs-human judgement from this run would be map-mismatched and misleading.

### Confidence

High for the parser/scaffold proof and local inventory result.

High that no filename-inferred local DM2 candidate was present in the inspected folder.

Low for any movement-realism comparison until S4 has a DM2 or map-matched human set.

### Follow-up

Ask Claude to review S4a. Proposed S4b: select or acquire a real DM2 human comparison set and run it through the same scaffold. Prefer existing bulk corpora noted in thevault, especially the `servexeri` `/mnt/usb-ssd/4on4-corpus/demos/` manifest/corpus; do not mass-download from `hub.quakeworld.nu`.

## 2026-06-06 - S4b True-DM2 Human Demo Selection

### Experiment

Selected one true DM2 human 4on4 MVD from the existing `servexeri` corpus instead of downloading from hub.

Remote corpus:

```text
servexeri:/mnt/usb-ssd/4on4-corpus/manifest.tsv
servexeri:/mnt/usb-ssd/4on4-corpus/demos/
```

Selection filters:

- Existing corpus file; no hub download.
- Basename starts with `4on4_`.
- Basename contains `[dm2]`.
- Basename does not contain `tmp`.
- File exists under the corpus demo root.
- Single moderate-size 2026 demo for the first S4b parse.

Selected:

```text
4on4_blue_vs_red[dm2]20260228-0512.mvd
```

Ran:

```bash
python scripts/analyze_human_mvd.py --demo-root artifacts/human-demos/source --artifact-root artifacts/human-demos/s4b --stage s4b-dm2 --demo 4on4_blue_vs_red[dm2]20260228-0512.mvd --run-id s4b-dm2-blue-vs-red-20260228-0512
```

### Result

Corpus inventory:

- Manifest rows: `6409`.
- DM2 rows: `1598`.
- `4on4_` DM2 rows: `1450`.
- Cleanish 4on4 DM2 rows after excluding `tmp` and missing files: `1171`.

Selected demo verification:

- Manifest SHA-256: `f8269d8139b129426b569eaf6b2be278964d740bd0365647f4410db74da76585`.
- Manifest size: `8624854` bytes.
- Local transferred artifact matched the manifest hash and size.

Parsed demo:

- Run id: `s4b-dm2-blue-vs-red-20260228-0512`.
- Parser exits: `json=0`, `md=0`, `events=1`.
- Event count: `501300`; position events: `443408`.
- Match title/map: `Claustrophobopolis` / `dm2`.
- Duration: `747424` ms.
- Active movement rows: eight 4on4 players.
- Movement samples were clamped to the parsed `747424` ms match duration.
- The short post-match zero-distance named slot `blaze` was removed from the compact active-player summary by the match-duration clamp.
- Comparison verdict: `human_dm2_available_but_s3g_not_dm2`.

Active-player movement summary:

| Player | Avg | P95 | Stationary | Low | Air | Cadence/min |
|---|---:|---:|---:|---:|---:|---:|
| `BLooD_DoG(D_P)` | 295.1 | 491.9 | 9.3% | 16.1% | 29.8% | 45.7 |
| `Nico` | 296.8 | 487.9 | 10.9% | 17.9% | 38.3% | 58.8 |
| `Zord` | 275.3 | 429.5 | 7.0% | 15.3% | 21.2% | 35.9 |
| `Schotty` | 259.1 | 392.4 | 10.4% | 19.2% | 19.8% | 36.3 |
| `grl` | 256.9 | 464.1 | 16.3% | 23.4% | 20.4% | 33.6 |
| `foobar` | 228.1 | 481.6 | 26.0% | 33.6% | 20.9% | 33.4 |
| `SEX` | 253.0 | 466.4 | 19.6% | 27.4% | 25.5% | 41.3 |
| `vegeta` | 266.8 | 482.5 | 11.0% | 21.2% | 25.3% | 40.1 |

### Evidence

Artifacts:

- `artifacts/human-demos/s4b/human-demo-inventory.md`
- `artifacts/human-demos/s4b/human-demo-s4b-dm2-summary.md`
- `artifacts/human-demos/s4b/s4b-dm2-blue-vs-red-20260228-0512/movement-metrics.md`
- `experiments/human_comparison/evidence/human-dm2-s4b-selection.md`
- `experiments/human_comparison/evidence/human-dm2-s4b-selection.json`
- `experiments/human_comparison/evidence/human-dm2-s4b-inventory.md`
- `experiments/human_comparison/evidence/human-dm2-s4b-inventory.json`
- `experiments/human_comparison/evidence/human-dm2-s4b-summary.md`
- `experiments/human_comparison/evidence/human-dm2-s4b-summary.json`

### Interpretation

S4b fills the specific data gap discovered in S4a: a true DM2 human reference is available from the existing corpus and parses through the same movement pipeline.

It still does not make S3g human-like. S3g bot evidence is on `dm3` and `frobodm2`, while this human reference is `dm2`. The result is useful as a DM2 human anchor, but not as a direct S3g comparison.

### Confidence

High for the corpus selection counts and selected file provenance.

High that the selected MVD is a true DM2 human 4on4 demo and parses through the current pipeline.

Low for any S3g-vs-human comparison until maps are matched or bot evidence exists on DM2.

### Follow-up

Ask Claude to review S4b. Proposed S4c: resolve the map mismatch before making realism claims. Since stock `dm2` lacks a Frogbot route file, the smallest useful next comparison is likely to select and parse one human `dm3` 4on4 demo from the same corpus, then compare its movement summary against the existing S3g `dm3` bot run. If Claude prefers preserving the S4 DM2 path instead, the alternative is to generate DM2 bot evidence by adding/finding a real DM2 route or another server-native bot path.

## 2026-06-06 - S4c Map-Matched Human DM3 Comparison

### Experiment

Selected one human `dm3` 4on4 MVD from the existing `servexeri` corpus and compared it against the existing S3g `dm3` bot summary.

Remote corpus:

```text
servexeri:/mnt/usb-ssd/4on4-corpus/manifest.tsv
servexeri:/mnt/usb-ssd/4on4-corpus/demos/
```

Selection filters:

- Existing corpus file; no hub download.
- Basename starts with `4on4_`.
- Basename contains exact `[dm3]`.
- Basename does not contain `tmp`.
- File exists under the corpus demo root.
- Single moderate-size 2026 demo for the first same-map parse.

Selected:

```text
4on4_blue_vs_red[dm3]20260426-0307.mvd
```

Ran:

```bash
python scripts/analyze_human_mvd.py --demo-root artifacts/human-demos/source --artifact-root artifacts/human-demos/s4c --stage s4c-dm3 --demo 4on4_blue_vs_red[dm3]20260426-0307.mvd --run-id s4c-dm3-blue-vs-red-20260426-0307
```

### Result

Corpus inventory:

- Manifest rows: `6409`.
- Exact `[dm3]` rows: `1663`.
- `4on4_` exact `[dm3]` rows: `1629`.
- Cleanish 4on4 DM3 rows after excluding `tmp` and missing files: `1247`.
- Moderate-size 2026 cleanish 4on4 DM3 rows: `444`.

Selected demo verification:

- Manifest SHA-256: `6897a00a4c185751ac82c579c091437cc5b82701df14cc2178da4792924ad4fe`.
- Manifest size: `7632722` bytes.
- Local transferred artifact matched the manifest hash and size.

Parsed demo:

- Run id: `s4c-dm3-blue-vs-red-20260426-0307`.
- Parser exits: `json=0`, `md=0`, `events=1`.
- Event count: `477099`; position events: `432058`.
- Match title/map: `The Abandoned Base` / `dm3`.
- Duration: `729226` ms.
- Active movement rows: eight 4on4 players.
- Ignored named slots: `0`.
- Comparison verdict: `same_map_human_reference_available`.

Human movement range versus S3g `dm3` bot run `20260606T003718Z`:

| Metric | Human min | Human mean | Human max | Bot min | Bot mean | Bot max |
|---|---:|---:|---:|---:|---:|---:|
| Avg | 235.4 | 285.5 | 333.5 | 190.1 | 219.2 | 248.2 |
| P95 | 390.5 | 482.3 | 515.2 | 361.0 | 368.1 | 375.3 |
| Stationary | 3.5% | 9.8% | 21.1% | 0.4% | 1.5% | 2.5% |
| Low | 9.1% | 16.7% | 28.6% | 18.9% | 22.5% | 26.1% |
| Air | 21.9% | 29.4% | 39.6% | 24.8% | 34.5% | 44.2% |

Bot rows versus the human range:

| Bot | Avg range | P95 range | Stationary range | Low range | Air range |
|---|---|---|---|---|---|
| `/ bro` | `below_human_min` | `below_human_min` | `below_human_min` | `within_human_range` | `above_human_max` |
| `/ goldenboy` | `within_human_range` | `below_human_min` | `below_human_min` | `within_human_range` | `within_human_range` |

### Evidence

Artifacts:

- `artifacts/human-demos/s4c/human-demo-inventory.md`
- `artifacts/human-demos/s4c/human-demo-s4c-dm3-summary.md`
- `artifacts/human-demos/s4c/s4c-dm3-blue-vs-red-20260426-0307/movement-metrics.md`
- `experiments/human_comparison/evidence/human-dm3-s4c-selection.md`
- `experiments/human_comparison/evidence/human-dm3-s4c-selection.json`
- `experiments/human_comparison/evidence/human-dm3-s4c-inventory.md`
- `experiments/human_comparison/evidence/human-dm3-s4c-inventory.json`
- `experiments/human_comparison/evidence/human-dm3-s4c-summary.md`
- `experiments/human_comparison/evidence/human-dm3-s4c-summary.json`

### Interpretation

S4c resolves the immediate S3g map mismatch: there is now a same-map human `dm3` reference compared against the S3g `dm3` bot run.

It does not prove S3g is human-like. The descriptive comparison says the current gate was too weak: both S3g bots are below the human p95 speed range, `/ bro` is also below the human average-speed range, and `/ bro` is above the human airborne-proxy range. Mode `7` remains useful movement-literacy evidence, but not a believable movement model.

### Confidence

High for the selected file provenance, parser result, and same-map comparison mechanics.

Medium for the specific movement-range interpretation because this is one human 4on4 demo and one S3g bot run.

Low for any general player-realism claim until the lab has a broader elite or player-specific reference set.

### Follow-up

Ask Claude to review S4c. Proposed S5a: build a Milton/elite movement reference-set inventory. Use existing corpus and local metadata first, keep the no-hub-mass-download rule, identify whether the current data can find Milton or other elite reference demos without training or a costly full content scan, and parse one small defensible reference sample if available.

## 2026-06-06 - S5a Milton/Elite Reference Inventory

### Experiment

Used existing metadata instead of parsing the whole corpus:

- Turso `qw-stats-xerialen` `player_games` / `games` rows identify player-to-game membership.
- `servexeri:/mnt/usb-ssd/4on4-corpus/manifest.tsv` identifies which game SHA-256 values are present in the local 4on4 MVD corpus.
- thevault `quakeworld/mvds.md` no-hub-mass-download rule still applies.

For each target player, inspected exact `player_name` matches in `player_games` where `mode='4on4'`, then cross-referenced the latest `500` rows against the corpus manifest and map.

Target players:

- `Milton`
- `carapace`
- `_ ParadokS`
- `yeti`
- `ok98`

Selected one exact `Milton` `dm3` reference sample and parsed it through `scripts/analyze_human_mvd.py`:

```bash
python scripts/analyze_human_mvd.py --demo-root artifacts/human-demos/source --artifact-root artifacts/human-demos/s5a --stage s5a-milton-dm3 --demo 4on4_blue_vs_anza[dm3]20260602-2022.mvd --run-id s5a-milton-dm3-blue-vs-anza-20260602-2022
```

### Result

Metadata inventory:

| Player | Total 4on4 rows | Latest-500 manifest hits | DM3 hits | DM2 hits |
|---|---:|---:|---:|---:|
| `Milton` | 1240 | 96 | 23 | 19 |
| `carapace` | 712 | 68 | 14 | 13 |
| `_ ParadokS` | 1729 | 55 | 11 | 10 |
| `yeti` | 1518 | 60 | 17 | 17 |
| `ok98` | 1326 | 59 | 13 | 19 |

This proves exact-player elite/Milton reference selection is feasible from metadata without training, hub downloads, or a bulk content scan.

Selected demo:

- `4on4_blue_vs_anza[dm3]20260602-2022.mvd`
- SHA-256: `9ca8f72b3afa95ba87830a83478c51bb9b3dd626b733190a4ca2d84b4d66490e`
- Size: `14359909` bytes
- Turso row: `Milton`, team `anza`, date `2026-06-02 20:42:16 +0000`, frags/deaths `118/18`, match `blue` vs `anza`, score `133`-`261`, server `Berlin KTX Server antilag #4`

Parsed demo:

- Run id: `s5a-milton-dm3-blue-vs-anza-20260602-2022`.
- Parser exits: `json=0`, `md=0`, `events=1`.
- Event count: `799790`; position events: `694902`.
- Match title/map: `The Abandoned Base` / `dm3`.
- Duration: `1200013` ms.
- Active movement rows: eight 4on4 players.
- Milton row: active `1199.415` s, avg `314.2` qu/s, p95 `535.0`, stationary `5.9%`, low-speed `12.4%`, airborne proxy `35.1%`, cadence `44.9`/min.

Milton-containing sample versus S3g `dm3` bot run `20260606T003718Z`:

| Metric | Human min | Human mean | Human max | Bot min | Bot mean | Bot max |
|---|---:|---:|---:|---:|---:|---:|
| Avg | 248.5 | 277.0 | 314.2 | 190.1 | 219.2 | 248.2 |
| P95 | 447.4 | 490.3 | 535.0 | 361.0 | 368.1 | 375.3 |
| Stationary | 5.9% | 10.6% | 14.5% | 0.4% | 1.5% | 2.5% |
| Low | 12.4% | 17.8% | 21.6% | 18.9% | 22.5% | 26.1% |
| Air | 31.0% | 33.5% | 37.2% | 24.8% | 34.5% | 44.2% |

Bot rows versus this sample:

| Bot | Avg range | P95 range | Stationary range | Low range | Air range |
|---|---|---|---|---|---|
| `/ bro` | `below_human_min` | `below_human_min` | `below_human_min` | `above_human_max` | `above_human_max` |
| `/ goldenboy` | `below_human_min` | `below_human_min` | `below_human_min` | `within_human_range` | `below_human_min` |

### Evidence

Artifacts:

- `artifacts/reference-set/4on4-manifest.tsv`
- `artifacts/human-demos/s5a/human-demo-inventory.md`
- `artifacts/human-demos/s5a/human-demo-s5a-milton-dm3-summary.md`
- `artifacts/human-demos/s5a/s5a-milton-dm3-blue-vs-anza-20260602-2022/movement-metrics.md`
- `experiments/human_comparison/evidence/human-milton-s5a-selection.md`
- `experiments/human_comparison/evidence/human-milton-s5a-selection.json`
- `experiments/human_comparison/evidence/human-milton-s5a-inventory.md`
- `experiments/human_comparison/evidence/human-milton-s5a-inventory.json`
- `experiments/human_comparison/evidence/human-milton-s5a-summary.md`
- `experiments/human_comparison/evidence/human-milton-s5a-summary.json`

### Interpretation

S5a removes a major data uncertainty: the project can select player-specific reference demos by metadata, at least for Milton and several elite targets.

The first Milton sample sharpens the S4c result. The current S3g bot movement remains below elite p95 movement and, for `/ bro`, below average speed while also spending too much time in low-speed/airborne-proxy states. This points toward route primitive/state diagnosis before player-style modelling.

This is still one match. Do not tune mode `7` directly to this single Milton row.

### Confidence

High that exact-player metadata selection is feasible for the tested target names.

High for the selected Milton demo provenance and parser result.

Medium for the S3g-vs-Milton movement gap because it is one match and one bot run.

Low for any player-specific movement conclusion until S5 has a tiny aggregate.

### Follow-up

Ask Claude to review S5a. Proposed S5b: build a tiny Milton/elite reference aggregate. Select a small bounded set of exact-player `dm3` demos from the proven metadata path, parse compact summaries, and report multi-demo movement ranges before S6 route primitives or S7 player-specific movement.

## 2026-06-06 - S5b Tiny Milton/Elite Reference Aggregate

### Experiment

Added `scripts/summarize_reference_aggregate.py` and selected two more exact-player `dm3` references using the metadata path proven in S5a. Raw demos and event streams remain ignored under `artifacts/`.

Selected targets:

- `Milton`: `4on4_blue_vs_anza[dm3]20260602-2022.mvd`
- `carapace`: `4on4_book_vs_-s-[dm3]20260526-2011.mvd`
- `yeti`: `4on4_red_vs_blue[dm3]20260530-0322.mvd`

Ran:

```bash
python scripts/analyze_human_mvd.py --demo-root artifacts/human-demos/source --artifact-root artifacts/human-demos/s5b --stage s5b-carapace-dm3 --demo 4on4_book_vs_-s-[dm3]20260526-2011.mvd --run-id s5b-carapace-dm3-book-vs-s-20260526-2011
python scripts/analyze_human_mvd.py --demo-root artifacts/human-demos/source --artifact-root artifacts/human-demos/s5b --stage s5b-yeti-dm3 --demo 4on4_red_vs_blue[dm3]20260530-0322.mvd --run-id s5b-yeti-dm3-red-vs-blue-20260530-0322
python scripts/summarize_reference_aggregate.py --stage s5b-elite-dm3 --map dm3 --target Milton=experiments/human_comparison/evidence/human-milton-s5a-summary.json --target carapace=artifacts/human-demos/s5b/s5b-carapace-dm3-book-vs-s-20260526-2011/human-summary.json --target yeti=artifacts/human-demos/s5b/s5b-yeti-dm3-red-vs-blue-20260530-0322/human-summary.json --output-json artifacts/human-demos/s5b/reference-s5b-elite-dm3-aggregate.json --output-md artifacts/human-demos/s5b/reference-s5b-elite-dm3-aggregate.md
```

### Result

Reference rows:

| Target | Avg | P95 | Stationary | Low | Air | Cadence/min |
|---|---:|---:|---:|---:|---:|---:|
| `Milton` | 314.2 | 535.0 | 5.9% | 12.4% | 35.1% | 44.9 |
| `carapace` | 282.8 | 524.9 | 11.5% | 19.6% | 34.2% | 44.0 |
| `yeti` | 291.5 | 505.8 | 7.5% | 15.4% | 35.9% | 48.6 |

Aggregate range against S3g `dm3` bot run `20260606T003718Z`:

| Metric | Ref min | Ref mean | Ref max | Bot min | Bot mean | Bot max |
|---|---:|---:|---:|---:|---:|---:|
| Avg | 282.8 | 296.2 | 314.2 | 190.1 | 219.2 | 248.2 |
| P95 | 505.8 | 521.9 | 535.0 | 361.0 | 368.1 | 375.3 |
| Stationary | 5.9% | 8.3% | 11.5% | 0.4% | 1.5% | 2.5% |
| Low | 12.4% | 15.8% | 19.6% | 18.9% | 22.5% | 26.1% |
| Air | 34.2% | 35.1% | 35.9% | 24.8% | 34.5% | 44.2% |
| Cadence/min | 44.0 | 45.8 | 48.6 | | | |

Bot rows versus the aggregate:

| Bot | Avg range | P95 range | Stationary range | Low range | Air range |
|---|---|---|---|---|---|
| `/ bro` | `below_human_min` | `below_human_min` | `below_human_min` | `above_human_max` | `above_human_max` |
| `/ goldenboy` | `below_human_min` | `below_human_min` | `below_human_min` | `within_human_range` | `below_human_min` |

### Evidence

Artifacts:

- `artifacts/human-demos/s5b/s5b-carapace-dm3-book-vs-s-20260526-2011/human-summary.md`
- `artifacts/human-demos/s5b/s5b-yeti-dm3-red-vs-blue-20260530-0322/human-summary.md`
- `artifacts/human-demos/s5b/reference-s5b-elite-dm3-aggregate.md`
- `experiments/human_comparison/evidence/human-reference-s5b-selection.md`
- `experiments/human_comparison/evidence/human-reference-s5b-selection.json`
- `experiments/human_comparison/evidence/human-carapace-s5b-summary.md`
- `experiments/human_comparison/evidence/human-carapace-s5b-summary.json`
- `experiments/human_comparison/evidence/human-yeti-s5b-summary.md`
- `experiments/human_comparison/evidence/human-yeti-s5b-summary.json`
- `experiments/human_comparison/evidence/human-reference-s5b-aggregate.md`
- `experiments/human_comparison/evidence/human-reference-s5b-aggregate.json`

The committed aggregate records repo-local input paths as forward-slash repo-relative paths. This keeps regenerated evidence portable across developer workspaces.

### Interpretation

S5b is a stronger anchor than S5a because it avoids making one Milton match the whole target. It still remains deliberately tiny.

The aggregate shows a stable high-speed gap: S3g's p95 speed is far below all three exact-player references, and S3g's average speed is also below the reference range. The current bot gate did not require sustained high-speed movement, so more mode `7` command tuning would optimize the wrong surface.

The next useful experiment should inspect route primitive/state behavior around low-speed stretches, not add another movement-command heuristic.

### Confidence

High for the aggregate mechanics and target-row provenance.

Medium for the reference range because it is three exact-player rows, not a large distribution.

High that S3g is below this tiny aggregate on avg and p95 movement.

### Follow-up

Ask Claude to review S5b. Proposed S6a: route primitive/state diagnosis. Inspect S3g `dm3` movement traces around low-speed stretches and route/segment state if available, to decide whether the gap is route choice, obstruction/turn behavior, or missing route-level movement intent.

## 2026-06-06 - S6a Route-State Diagnosis

### Experiment

Added `scripts/diagnose_route_state.py` and applied it to the existing S3g `dm3` run `20260606T003718Z`.

The script uses only existing artifacts:

- `events.txt` kind `5` position samples
- `analysis.json` map entities and match duration
- `run.env`
- `moveprobe-commands.json`

It detects low-speed windows, joins sampled command rows around those windows, reports nearest map-entity locations, and records whether route node/goal/obstruction state is present in the current artifacts.

### Result

Artifact capability:

- Position trace: available.
- Command trace: available, `195` sampled command rows.
- Command diagnostics: `backward`, `route_yaw`, `view_yaw`, `yaw_delta`.
- Map-entity location context: available.
- Route node/goal/obstruction state: not available.

Player summary:

| Player | Avg | P95 | Max | Low | Low windows | Longest low | Top windows with strong-command low speed |
|---|---:|---:|---:|---:|---:|---:|---:|
| `/ bro` | 190.1 | 361.0 | 449.4 | 26.1% | 7 | 1198 ms | 5 / 5 |
| `/ goldenboy` | 248.2 | 375.3 | 415.0 | 18.9% | 4 | 1078 ms | 3 / 4 |

Top-window interpretation:

- `8` of `9` analyzed low-speed windows showed low speed despite average sampled horizontal command at or above `400`.
- `/ bro` had repeated low-speed windows near `water.LG` and `bridge.low` with sampled horizontal command around `824`.
- `/ goldenboy` had one low-speed window with no sampled command rows nearby, but the other analyzed windows had strong or mixed-strong command context.

### Evidence

Artifacts:

- `artifacts/lab-runs/20260606T003718Z/s6a-route-state-diagnosis.md`
- `artifacts/lab-runs/20260606T003718Z/s6a-route-state-diagnosis.json`
- `experiments/ktx_moveprobe/evidence/route-state-s6a-diagnosis.md`
- `experiments/ktx_moveprobe/evidence/route-state-s6a-diagnosis.json`

Validation:

- `python -m unittest tests.test_diagnose_route_state -v` -> 4 passed
- `python -m unittest discover -s tests -v` -> 26 passed
- `PYTHONPYCACHEPREFIX=<temp> python -m py_compile ...` for scripts/tests -> clean
- `git diff --check` -> clean, with only CRLF normalization warnings
- SHA-256 checks confirmed committed S6a JSON/Markdown evidence matches the generated run-artifact copies

### Interpretation

S6a suggests the S3g high-speed gap is not simply missing final-command emission: low-speed windows often happen while the sampled final command is still strong and jump-bearing.

However, the current artifacts cannot distinguish route choice, route-node transitions, obstruction/blocked behavior, or missing route-level movement intent. `route_yaw` is available, but route state itself is not.

### Confidence

High that current artifacts lack route node/goal/obstruction state.

High that the inspected low-speed windows often coincide with strong sampled commands.

Medium for cause attribution, because S6a deliberately proves that attribution is not possible from the current artifacts alone.

### Follow-up

Ask Claude to review S6a. Proposed S6b: add minimal route-state logging around the Frogbot command boundary so future low-speed windows can be tagged with route node/goal/obstruction context before changing mode `7` or adding a new command heuristic.

## 2026-06-06 - S6b Minimal Route-State Logging

### Experiment

Extended the temporary KTX moveprobe patch so each sampled `FBMOVEPROBE_CMD` row appends:

```text
route=<linked_marker>,<touch_marker>,<goal_ed>,<goal_marker>,<path_state>,<bot_state>,<blocked>,<dir_speed>
```

The Python runner now parses this into nested `route_state` rows, and `scripts/diagnose_route_state.py` summarizes those values inside low-speed windows.

Temporarily deployed the patched KTX build to `servexeri`, backed up the live `qwprogs.so`, ran one short S3g-style `dm3` probe, then restored the deployed module and reversed the remote source patch:

```bash
python scripts/run_bot_lab.py --map dm3 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 7 --moveprobe-sidemove 200 --moveprobe-log-commands --moveprobe-log-interval 0.25 --run-id 20260606T031102Z
python scripts/diagnose_route_state.py --stage s6b-route-state --run-id 20260606T031102Z --output-json artifacts/lab-runs/20260606T031102Z/s6b-route-state-diagnosis.json --output-md artifacts/lab-runs/20260606T031102Z/s6b-route-state-diagnosis.md
```

Remote restore checks:

```text
deployed qwprogs hash matched backup: 23d45401251ee802549c924f3179cf0cd76e0132dd7727778994c0464b8143e0
servexeri ~/nquakesv/build/ktx: clean master...origin/master
quakestat localhost:28599: DOWN
```

### Result

Run `20260606T031102Z`:

- Parser exits: `json=0`, `md=0`, `events=1`.
- Command rows parsed: `196`.
- Route-state capability: available.
- Route-state keys: `blocked`, `bot_state`, `dir_speed`, `goal_ed`, `goal_marker`, `linked_marker`, `path_state`, `touch_marker`.
- Command/sample clock sanity: `ok`, with `21666` ms overlap after the `150` ms command-window margin.

Player summary:

| Player | Avg | P95 | Max | Low | Low windows | Longest low | Top windows with strong-command low speed |
|---|---:|---:|---:|---:|---:|---:|---:|
| `/ bro` | 136.3 | 359.6 | 406.2 | 52.1% | 17 | 1646 ms | 5 / 5 |
| `/ goldenboy` | 285.5 | 381.3 | 427.8 | 7.0% | 0 | 0 ms | 0 / 0 |

Top route-state windows for `/ bro`:

| Rank | Window | Location | Avg cmd | Route state | Blocked |
|---:|---|---|---:|---|---:|
| 1 | `3181-5292` | `Quad` | 659.1 | `L[-1,91,119,170] T[43,119,168,170,172] G[-1,3] P[0]` | 0.0% |
| 2 | `13193-14307` | `water.LG` | 824.1 | `L[59] T[37,273] G[59] P[0,32768]` | 0.0% |
| 3 | `24441-25517` | `water.LG` | 823.8 | `L[59] T[276] G[59] P[32768]` | 0.0% |
| 4 | `21860-22918` | `water.LG` | 824.1 | `L[59] T[276] G[59] P[32768]` | 0.0% |
| 5 | `9008-9882` | `bridge.low` | 824.0 | `L[161] T[159] G[10] P[0]` | 0.0% |

### Evidence

Artifacts:

- `artifacts/lab-runs/20260606T031102Z/run-summary.md`
- `artifacts/lab-runs/20260606T031102Z/moveprobe-commands.md`
- `artifacts/lab-runs/20260606T031102Z/movement-metrics.md`
- `artifacts/lab-runs/20260606T031102Z/s6b-route-state-diagnosis.md`
- `artifacts/lab-runs/20260606T031102Z/s6b-route-state-diagnosis.json`
- `experiments/ktx_moveprobe/evidence/route-state-s6b-diagnosis.md`
- `experiments/ktx_moveprobe/evidence/route-state-s6b-diagnosis.json`

Validation:

- `git -C C:\Users\benya\projects\quakeworld\engine\ktx apply --check experiments\ktx_moveprobe\frogbot-moveprobe.patch` -> clean
- `python -m unittest tests.test_extract_movement_metrics tests.test_diagnose_route_state -v` -> passed
- `PYTHONPYCACHEPREFIX=<temp> python -m py_compile scripts\run_frobodm2_lab.py scripts\diagnose_route_state.py tests\test_extract_movement_metrics.py tests\test_diagnose_route_state.py` -> clean
- S6b lab command completed cleanly
- S6b diagnosis command completed cleanly
- Claude's S6a robustness feedback was addressed in the diagnosis script: sibling JSON artifacts are guarded, command/sample clock overlap is reported, non-dict command/map-entity rows are tolerated, and the explicit run-directory input is documented as read-only by design.

### Interpretation

S6b satisfies the logging goal. The artifact gap from S6a is closed: low-speed windows can now be tagged with Frogbot marker, goal, path-state, bot-state, blocked, and route `dir_speed` context.

This run does not show an obstruction flag explanation. The analyzed `/ bro` windows all had `blocked=0`, and repeated `water.LG` windows share linked/goal marker `59` with path state `32768`. That points the next investigation toward route-state/path-flag interpretation and repeated marker transitions, not another command magnitude change.

### Confidence

High that S6b route-state logging works and is parsed into the diagnosis artifact.

High that `/ bro` had repeated low-speed windows despite strong sampled commands in this run.

Medium for route-cause interpretation until the path-state values are decoded against KTX route flags and repeated on at least one more short run.

### Follow-up

Ask Claude to review S6b. Proposed S6c: use the route-state-tagged low-speed windows to decode repeated marker/path-state/blocked patterns, starting with `/ bro` at `water.LG` linked/goal marker `59` and path state `32768`, before changing mode `7` or adding another movement-command heuristic.

## 2026-06-06 - S6c Route-State Window Attribution

### Experiment

Added `scripts/attribute_route_state_windows.py` and applied it to the existing S6b `dm3` run `20260606T031102Z`.

The script uses:

- `experiments/ktx_moveprobe/evidence/route-state-s6b-diagnosis.json`
- `artifacts/lab-runs/20260606T031102Z/moveprobe-commands.json`
- KTX/Frogbot flag definitions from `include/fb_globals.h`
- KTX route/water behavior from `src/route_calc.c`
- KTX `dir_speed` meaning from `src/bot_movement.c`
- Frogbot map edges from `resources/example-configs/ktx/bots/maps/dm3.bot`

No KTX patch, remote deploy, or controller change was made for S6c.

### Result

Decoded source facts:

- `path_state=32768` is `WATER_PATH`.
- `STUCK_PATH` is `524288`.
- bot state `128` is `AWARE_SURROUNDINGS`.
- KTX route calculation sets `WATER_PATH` when either path endpoint marker is in water and computes the path time using `sv_maxwaterspeed`.
- `SetDirectionMove()` stores `dir_speed` as the pre-normalization magnitude, then normalizes `dir_move_`.

Repeated pattern summary:

| Player | Windows | Location | Linked | Goal | Water | Stuck | Blocked | Low native dir | Dir speed avg | Avg cmd | Classification |
|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|
| `/ bro` | 3 | `water.LG` | `[59]` | `[59]` | yes | no | 0.0% | 62.5% | 0.338 | 824.0 | `water_path_without_obstruction` |
| `/ bro` | 1 | `Quad` | `[91,119,170]` | `[3]` | no | no | 0.0% | 20.0% | 0.774 | 659.1 | `route_state_unresolved` |
| `/ bro` | 1 | `bridge.low` | `[161]` | `[10]` | no | no | 0.0% | 0.0% | 0.700 | 824.0 | `route_state_unresolved` |

Window details:

- Rank 2, `13193-14307`, `water.LG`: mixed edge samples `273->59 idx=[4]` and `37->59 idx=[2]`; path state includes both `0` and `WATER_PATH`; dir_speed avg `0.787`.
- Rank 3, `24441-25517`, `water.LG`: repeated edge `276->59 idx=[0]`; path state `WATER_PATH`; dir_speed avg `0.059`.
- Rank 4, `21860-22918`, `water.LG`: repeated edge `276->59 idx=[0]`; path state `WATER_PATH`; dir_speed avg `0.196`.

### Evidence

Artifacts:

- `experiments/ktx_moveprobe/evidence/route-state-s6c-attribution.json`
- `experiments/ktx_moveprobe/evidence/route-state-s6c-attribution.md`

Validation:

- `python -m unittest tests.test_attribute_route_state_windows -v` -> 3 passed
- `PYTHONPYCACHEPREFIX=<temp> python -m py_compile scripts\attribute_route_state_windows.py tests\test_attribute_route_state_windows.py` -> clean
- Claude's S6c review follow-up was addressed after initial attribution: the output now documents the marker-index invariant, malformed command rows without `time_s` are dropped instead of treated as time zero, JSON-derived default command paths require safe lab run ids, and the KTX patch now bounds `goalentity < MAX_EDICTS` before reading `g_edicts[goalentity]`.

### Interpretation

S6c attributes the strongest repeated S6b low-speed pattern to water-path route behavior, not stuck/blocked obstruction recovery and not missing final command magnitude.

The key signal is that native Frogbot `dir_speed` collapses on repeated `276->59` water-path windows while the mode `7` probe still emits strong sampled movement commands near `824`. This suggests the next missing evidence is water/swim intent context around the route primitive: `waterlevel`, `swim_arrow`, `upmove`, velocity, and/or raw `dir_move` behavior.

### Confidence

High that `32768` is `WATER_PATH` and not `STUCK_PATH`.

High that the repeated `water.LG` windows had `blocked=0` and strong sampled command context.

Medium that water-path/swim handling is the cause of low movement realism, because S6c attributes the repeated route state but does not yet expose waterlevel/upmove/swim intent.

### Follow-up

Ask Claude to review S6c. Proposed S6d: inspect water-path movement intent around `water.LG` by adding or deriving minimal `waterlevel`, `swim_arrow`, `upmove`, velocity, and route `dir_move` context before changing mode `7`.

## 2026-06-06 - S6d Water-Path Swim-Intent Diagnosis

### Experiment

Extended the sampled KTX `FBMOVEPROBE_CMD` rows with a `water=` suffix containing waterlevel, watertype, player flags, `swim_arrow`, emitted `upmove`, current velocity, and raw route `dir_move`. Reran a short `dm3` mode `7` probe as `20260606T041805Z`.

The live KTX library was backed up before deployment and restored afterward; the restored live hash matched the backup hash `23d45401251ee802549c924f3179cf0cd76e0132dd7727778994c0464b8143e0`.

### Result

- `/ bro`: avg `183.9`, p95 `365.5`, low-speed `33.7%`, and `12` low-speed windows.
- `/ goldenboy`: avg `286.5`, p95 `386.3`, low-speed `8.4%`, and `2` low-speed windows.
- All `5` analyzed `/ bro` top windows were near `water.LG`, had strong sampled commands near `824`, had `blocked=0`, and included `WATER_PATH`.
- The repeated `/ bro` water-path groups had waterlevel `[1]` or `[1, 2]`, no sampled `waterlevel > 2`, `swim_arrow=0`, and emitted `upmove=0`.
- The lowest native `dir_speed` windows remained on or near `.bot` edge `276->59 idx=[0]`, with dir_speed averages `0.050`, `0.051`, and `0.064` in the sharpest windows.

### Evidence

Artifacts:

- `experiments/ktx_moveprobe/evidence/route-state-s6d-water-attribution.json`
- `experiments/ktx_moveprobe/evidence/route-state-s6d-water-attribution.md`

Validation:

- `python -m unittest discover -s tests -v` -> 41 passed
- `py_compile` on changed scripts/tests -> clean
- external KTX `git apply --check` -> clean
- `git diff --check` -> clean, with only CRLF normalization warnings
- Remote KTX source checkout was clean after deployment; live `qwprogs.so` was restored to the backup hash.

### Interpretation

S6d does not support an active deep-swim explanation for the repeated `water.LG` windows. `BotWaterMove()` only sets `swim_arrow` once `waterlevel > 2`, and the analyzed window samples did not reach that depth.

The sharper hypothesis is a shallow water-edge transition: mode `7` overwrites emitted `direction[2]` from `k_fb_moveprobe_upmove`, defaulting to `0`, while some failing samples have `waterlevel=2` and nonzero raw `dir_move_z`. The next useful experiment should preserve native water-edge vertical command intent in a tiny, bounded way and stop if it does not reduce the `water.LG` low-speed windows.

### Confidence

High that S6d water-state logging works and is parsed into nested command artifacts.

High that the repeated `water.LG` failure reproduced on a fresh run with `WATER_PATH`, `blocked=0`, strong commands, no `swim_arrow`, and zero emitted upmove.

Medium that preserving native water-edge upmove will help, because S6d did not log pre-probe stock `direction[2]` directly; it inferred the likely missing vertical command from KTX source and raw `dir_move_z`.

### Follow-up

Ask Claude to review S6d. Proposed S6e: add the smallest mode `7` water-edge upmove preservation probe, rerun one short `dm3` sample, and compare only the repeated `water.LG` low-speed windows. If it does not improve those windows, stop upmove tuning and inspect `.bot` edge geometry around `276->59`.

## 2026-06-06 - S6d Review-Hardening Follow-Up

### Experiment

Addressed Claude's S6d review findings in the analysis scripts before continuing to S6e. The changes were evidence-hygiene fixes rather than a new bot run.

### Result

- Moveprobe plausibility summaries now bind by `user_id`/edict strictly when that id is present; if id-matched command rows are missing, the player gets zero command rows instead of falling back to a duplicate netname.
- Reference aggregates now preserve missing metrics as missing values, so absent human baseline fields are excluded from range calculations instead of silently becoming `0.0`.
- Reference aggregates now warn when the requested map filter excludes every reference row.
- Landing speed-loss ratio now reports the mean of per-landing loss ratios, matching the field name.
- Route-state diagnosis now skips untimestamped command rows during window joins, matching the newer attribution script behavior.
- `run_frobodm2_lab.py` now uses the guarded percent formatter for the air-proxy line in run summaries.
- The committed S5b reference aggregate was regenerated with the updated script; numeric values stayed unchanged and the artifact now records `warnings: []`.

### Evidence

Validation added targeted regression tests for duplicate-name/id-miss command attribution, missing reference metrics, all-excluded reference maps, per-landing loss-ratio semantics, and untimestamped command joins.

### Interpretation

These fixes reduce the chance that a future S6 or S7 result looks numerically valid while being joined to the wrong bot, anchored to a fake zero human baseline, or inflated by malformed timestamp rows.

### Follow-up

Continue with S6e only after this review-hardening commit is pushed and Claude has the updated PR context. Keep S6e timeboxed; after the water-edge probe, the next substantive branch should either attack the headline land-speed/bunnyhop gap or broaden the reference corpus, per Claude's north-star caution.

## 2026-06-06 - S6e Water-Edge Upmove Preservation Probe

### Experiment

Changed only mode `7` vertical command handling in the KTX moveprobe patch: for `waterlevel > 1`, mode `7` now preserves the native pre-probe `direction[2]`; for all other samples it still uses `k_fb_moveprobe_upmove`. Horizontal mode `7` behavior stayed unchanged: aim-independent projection, no-backpedal folding, and bounded command magnitude.

Reran one short `dm3` mode `7` sample as `20260606T044000Z`.

The live KTX library was backed up before deployment and restored afterward; the restored live `qwprogs.so` hash matched the backup hash `23d45401251ee802549c924f3179cf0cd76e0132dd7727778994c0464b8143e0`.

### Result

- `/ bro`: avg `153.0`, p95 `377.7`, low-speed `46.3%`, and `3` low-speed windows.
- `/ goldenboy`: avg `152.7`, p95 `346.7`, low-speed `39.3%`, and `7` low-speed windows.
- `/ bro` no longer had the same repeated top `water.LG` water-path group; instead it produced a very long `YA.box` low-speed window with `STUCK_PATH`/blocked context.
- `/ goldenboy` produced the repeated `water.LG` / `276->59` WATER_PATH pattern: `2` grouped windows, linked/goal marker `59`, waterlevels `[1, 2]`, `blocked=0`, avg command `823.9`, low native dir ratio `80.0%`, and dir speed avg `0.240`.
- S6e emitted nonzero upmove in some `/ goldenboy` water-edge samples (`13.3%` of grouped samples), but the repeated low-speed pattern persisted.

### Evidence

Artifacts:

- `experiments/ktx_moveprobe/evidence/route-state-s6e-water-upmove-attribution.json`
- `experiments/ktx_moveprobe/evidence/route-state-s6e-water-upmove-attribution.md`

Validation:

- S6e run `20260606T044000Z`: parser exits `json=0`, `md=0`, `events=1` with `qw-analyze: end of demo`, movement players `2`, parsed commands `195`.
- external KTX `git apply --check` -> clean
- Remote KTX source checkout was clean after deployment; live `qwprogs.so` was restored to the backup hash and port `28599` was down.

### Interpretation

S6e hit the stop condition. Native water-edge upmove preservation did not reduce or remove the repeated `water.LG` / `276->59` WATER_PATH low-speed pattern. It also worsened overall low-speed ratios in this one short run.

This means the next step should not be another upmove value or generic movement-command tweak. The most local remaining S6 question is whether the `.bot` route edge geometry around `276->59` / marker `59` is producing a bad desired route vector or edge transition.

### Confidence

High that the S6e patch was deployed, logged, and restored cleanly.

High that the repeated water-path pattern persisted despite some nonzero emitted upmove.

Medium that S6e is conclusively bad, because this is one short stochastic Frogbot run; however, the explicit stop condition was "stop upmove tuning if repeated water.LG windows do not improve," and that condition was met.

### Follow-up

Ask Claude to review S6e. Proposed S6f: inspect `dm3.bot` route-edge geometry around `276->59` and marker `59` without a new controller change. If that audit does not reveal a tiny route-data fix, pivot away from S6 water-edge tuning and back toward the headline land-speed/bunnyhop gap or broader human reference evidence.

## 2026-06-06 - S6f Route-Edge Geometry Audit

### Experiment

Added `scripts/inspect_route_edge_geometry.py` to inspect a focused Frogbot `.bot` edge and its S6 attribution samples. Ran it against `dm3.bot` edge `276->59`, marker `59`, and the committed S6d/S6e attribution artifacts. No KTX code, route file, or remote lab run changed.

### Result

- `276->59` is explicitly present as `SetMarkerPath 276 0 59` at `dm3.bot` line `1837`.
- The reciprocal `59->276` is also explicitly present as `SetMarkerPath 59 0 276` at line `549`.
- The focus edge has no explicit `SetMarkerPathFlags`; the observed `WATER_PATH` state is runtime route-state classification, not a literal route-file flag on the edge.
- Marker `59` has a static origin `[1329.0, -378.0, -24.0]`, zone `17`, and goal `5`.
- Marker `276` is zoned as `17` but has no static `CreateMarker` origin, so the static route file cannot compute a vector, slope, or coordinate-level correction for `276->59`.
- S6d/S6e attribution contributes `30` unique sampled `276->59` rows; all focus-edge path states are `WATER_PATH`, `blocked=0`, waterlevels include `[0, 1, 2]`, and `86.7%` of the focus-edge samples have native `dir_speed < 0.25`.

### Evidence

Artifacts:

- `experiments/ktx_moveprobe/evidence/route-edge-s6f-geometry.json`
- `experiments/ktx_moveprobe/evidence/route-edge-s6f-geometry.md`

Validation:

- Focused route-edge geometry tests cover edge parsing, missing static origins, computable vectors, and attribution rollup.

### Interpretation

S6f confirms the repeated `276->59` low-native-dir-speed pattern is not an invented attribution: the edge exists and the S6 samples repeatedly land on it. But it does not justify a tiny static route-data fix. The source marker lacks a static origin, the reciprocal edge already exists, and the water-path state is assigned at runtime rather than being an explicit `.bot` flag to remove or edit.

Stop the S6 water-edge branch here. The next goal should move toward S7 by building player-specific movement signatures from exact-player reference data before any player-specific controller work, while keeping the larger land-speed/bunnyhop gap visible.

### Confidence

High that `dm3.bot` edge `276->59` and reciprocal `59->276` are parsed correctly with line anchors.

High that static edge geometry is incomplete because marker `276` has no `CreateMarker` origin.

Medium that no route-data fix exists at all, because runtime/item marker placement could still be knowable from KTX internals or live state; however, the static route file alone does not provide enough evidence for a safe tiny edit.

### Follow-up

Ask Claude to review S6f. Proposed S7a: seed player-specific movement signatures from the existing exact-player `dm3` references (`Milton`, `carapace`, `yeti`) before any player-specific movement controller work.
