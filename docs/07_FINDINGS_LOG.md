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
