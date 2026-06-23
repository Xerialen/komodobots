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

## 2026-06-16 -- T0.2 live-transport latency spike (shm chosen)

### Experiment

Bot-program Phase-0 wall #1 ("live brain pipe", ticket #207). Evaluate the
cheapest per-tick action transports for the moveprobe seam and pick one. The
per-tick action is exactly the `trap_SetBotCMD` payload at
`artifacts/ktx-live/bot_movement.c:~6191` (move `direction[3]`, aim
`desired_angle[3]`, `buttons` = fire/jump, `impulse` = weapon, `cmd_msec`).
Built a stdlib-only host-local microbenchmark
(`experiments/ktx_moveprobe/latency_spike.py`) of three candidates: (a) per-tick
action-file re-read, (b) POSIX shared memory (`mmap` over `/dev/shm` with a
per-slot seqlock = the `shm_open`+`mmap` mechanism), (c) a unix-domain datagram
socket = the short, newest-wins action-queue. Load model = a single-threaded
consumer (the KTX bot frame loop) fetching the freshest action for all slots
once per tick at the tick rate, with a separate producer process (the brain
sidecar) writing each slot asynchronously. Identical 32-byte action record for
all three. Target: p99 < ~0.5 ms/tick for up to 4 slots @ ~77 Hz.

### Result

All three clear the 0.5 ms/tick budget. **shm wins decisively** on latency,
jitter, and scaling.

4 slots @ 77 Hz, ~539 ticks measured (per-tick p99):

| candidate     | p50 (ms) | p99 (ms) | max (ms) | verdict |
|---------------|---------:|---------:|---------:|:-------:|
| action-file   |   0.0627 |   0.1058 |   0.1942 | PASS    |
| **shm**       |   0.0068 | **0.0124** | 0.0581 | **PASS** |
| socket        |   0.0193 |   0.0712 |   0.1455 | PASS    |

Stable across 3 repeats (shm per-tick p99 = 0.012 / 0.017 / 0.029 ms; ordering
shm < socket < action-file holds every run). At 8 slots (2x load) shm holds at
0.0155 ms p99. shm is ~40x under budget at the required 4-slot load.

### Evidence

- Benchmark: `experiments/ktx_moveprobe/latency_spike.py` (stdlib only;
  `python3 experiments/ktx_moveprobe/latency_spike.py [--json] [--slots N]`).
- Report: `experiments/ktx_moveprobe/T0.2_LATENCY_SPIKE.md` (full tables,
  candidate analysis, suggested T0.3 wiring, env caveat).
- Machine-readable run: `experiments/ktx_moveprobe/evidence/t0.2-latency-spike-20260616.json`.

### Interpretation

The transport is nowhere near the bottleneck at Phase-0 scale; even the worst
candidate clears budget. shm has the largest tail-latency margin and no per-tick
syscall (after a one-time mmap, a read is two struct unpacks against mapped
memory), so it is the recommended pipe to wire. The socket is a clean fallback
(simplest native wiring, still under budget); the file path is a low-effort
debug tap. Decision is recorded against the program's "Live transport: spike
decides" open fork.

### Confidence

Medium. The transport mechanism itself is proven far inside budget in a faithful
host-local producer/consumer model. This is a HOST-LOCAL microbenchmark only --
it does NOT run the real KTX server (no server build/SSH in this sandbox), so it
does not prove the end-to-end on-server cost (QVM/trap overhead, real frame
scheduler, real box load). No on-server numbers are fabricated.

### Follow-up

T0.3: wire shm live-mode into
`experiments/ktx_moveprobe/frogbot-moveprobe-perslot.patch` with the per-slot
seqlock reader + safe fallback (do not freeze; fall through to stock frogbot when
the helper stalls), run 1 bot live 5 min, and record the **on-KTX** p99 there to
close the loop this spike opened. The report's "Suggested wiring for T0.3"
section gives the record layout and reader/fallback contract.

---

## 2026-06-16 -- T0.1 bench emits leap-frog frag margin + R-T damage.matrix gate

### Experiment

docs/18 Phase 0 T0.1 (#206): turn the fixed-roster 4v4 ledger into a bench that
scores a frog-vs-leap match and writes the leap-minus-frog frag margin over
best-of-N, with the R-T `damage.matrix` gate. Win = total frags; combat guard =
damage done (never accuracy).

### Result

The 4v4 validation ledger builder now attaches, per valid game, a `bench` block
(leap team, frog team, leap/frog frags, `frag_margin`, `leap_won`) and a
`damage_matrix` gate (enemy damage > 0, intra-team damage within tolerance),
plus a ledger-level `bench` aggregate (`leap_frag_margin_total`/`mean`,
`leap_wins`, per-game series, overall gate verdict). The roster builder gained a
`leap_team` mode (four `leap` bots vs four skill-20 frogbot controls); the
single-komodobot roster still validates and its komodobot team is treated as the
leap team. All additions are backward compatible (old ledger consumers unchanged).

### Evidence

- `python -m unittest discover -s tests -p "test_*.py"`: 1181 tests passed
  (+9 new bench/gate/roster tests).
- End-to-end CLI on a two-game frog-vs-leap fixture
  (`fourvfour_validation_build.main --summary`):
  - per-game margins `34-28=+6` and `36-25=+11`, both `damage.matrix gate=green`
    (enemy=11600, intra-team=0);
  - `bench(best-of-2): leap-frog margin total=17 mean=8.5 leap_wins=2/2
    damage.matrix gate=green`;
  - margin identical across two consecutive builds (repeatable).
- Canonical scoring source = Alfhan's mvdanalyzer / ktxstats `dmg.given`
  (enemy) and `dmg.team` (intra-team); KTX writes its stats JSON to a `.txt`
  (`k_demotxt_format json`) and the 4v4 runner already derives `ktxstats.json`
  from the demo `.json` sidecar.

### Interpretation

The bench number ("leap frags minus frog frags over best-of-N") and the R-T
combat-honesty gate are now first-class ledger fields, so any future brain swap
is judged by frags with a damage-done guard, exactly as docs/18 requires.

### Confidence

High (offline/unit + CLI evidence). The full live 4v4 server run was not
executed in this environment (no SSH to servexeri / no WSL analyzer here); the
scoring path is proven against canonical-shaped fixtures.

### Follow-up

T0.2 (live-transport latency spike) and T0.3 (KTX live mode), then T0.7 drives
the first real live frog-vs-leap verdict through this same bench path.

---

## 2026-06-16 -- Bench fix: reject split-leap rosters before scoring (post-#227)

### Experiment

Close a Codex P2 found on PR #227 (T0.1) after it merged to `main`. The
four-leap roster shape check in `lab/server/fourvfour_validation_build.py`
validated a roster only by counting roles (`leap_count==4`,
`control_count==4`), so a roster with the four `leap` bots split 2+2 across
both teams of four (two leap + two control per team) passed as valid. The bench
then could not resolve a single leap team, scored zero games, and still emitted
a green `damage.matrix` gate -- a malformed run that looks valid while emitting
no frag margin (the bench silently lies).

### Result

Two-part defense-in-depth fix:

1. `_validate_roster` now tracks the team(s) carrying any leap/komodobot role
   and adds `roster_leap_roles_split_across_teams` when those roles span more
   than one team. The two legitimate shapes (one komodobot + seven controls;
   four leap on one team vs four skill-20 frogbots) still validate.
2. `validate_match` now fails closed: it calls `_leap_frog_teams` on the
   enriched players and adds `bench_could_not_resolve_leap_vs_frog_teams` when a
   single leap team cannot be resolved, so an unresolved game is recorded as
   invalid (never counted in `valid_games`, never scored, never gated green) even
   if roster fields are missing/inconsistent.

### Evidence

- `python -m unittest discover -s tests -p "test_*.py"`: 1182 tests passed
  (+1 new regression test).
- Pre-fix repro on a split-leap fixture: `valid_games=1`, `games_scored=0`,
  `leap_frag_margin_total=None`, `damage_matrix_gate_pass=True` (green gate, no
  margin). Post-fix on the same fixture: `valid_games=0`, one invalid game with
  reasons `['roster_leap_roles_split_across_teams',
  'bench_could_not_resolve_leap_vs_frog_teams']`, `games_scored=0`,
  `damage_matrix_gate_pass=False`.
- Existing positive case `test_full_leap_roster_resolves_team_and_margin`
  extended to assert the legitimate four-leap-on-one-team shape still scores a
  +3 margin with a green gate.

### Interpretation

The bench's leap-minus-frog margin can no longer read "valid + green" while
emitting no margin. A malformed frog-vs-leap roster is now caught at validation
and at scoring, so the bench verdict stays trustworthy (docs/18 binding rule).

### Confidence

High (unit + targeted repro before/after).

### Follow-up

Unchanged from T0.1: T0.2/T0.3 then T0.7 for the first live verdict.

---

## 2026-06-15 -- QWD qizmo decompression works from Windows via WSL

### Experiment

Fix and re-test the #188 post-merge defect where
`tools/qwd_content_manifest.py` resolved the local `qizmo_bundle.tgz` on
Windows but tried to execute the bundled Linux `ld-linux.so.2` / `qizmo`
directly from PowerShell, producing `WinError 193`.

### Result

The parser now runs the bundled Linux qizmo through `wsl.exe --cd /mnt/...`
when invoked from Windows. Linux/WSL-native sessions keep the direct qizmo
invocation.

### Evidence

- `python -m unittest tests.test_qwd_content_manifest -v`: 26 tests passed,
  5 corpus fixtures skipped.
- `python -m py_compile tools\qwd_content_manifest.py tests\test_qwd_content_manifest.py`: passed.
- Real qizmo-disguised `.qwd` smoke:
  `...\\smackdown\\neu\\group_c\\adt_jod_1_dm2_camper.qwd` -> `true_map=dm2`,
  `mode=4on4`, `player_count=8`, `frame_count=93281`, `errors=[]`,
  `decompressor="qizmo via WSL (bundle qizmo_bundle.tgz)"`.
- Real `.qwz` smoke:
  `...\\cottelan\\2on22dm6.qwz` -> `true_map=dm6`, `mode=2on2`,
  `player_count=4`, `frame_count=48636`, `errors=[]`,
  `decompressor="qizmo via WSL (bundle qizmo_bundle.tgz)"`.

### Interpretation

Compressed Challenge-TV demos can now enter the content-manifest gate from the
default Windows/PowerShell checkout instead of requiring manual WSL-side
decompression first. This repairs the concrete post-merge defect found after
#188 merged.

### Confidence

High for the local Windows + WSL + bundled-qizmo path, because it was proven on
both a qizmo-disguised `.qwd` and a `.qwz` corpus file. Medium for other Windows
machines until WSL presence and the qizmo bundle path are checked.

### Follow-up

Run the manifest over the first intentionally selected elite dm2/dm3 corpus
batch and record skipped/ambiguous demos separately from self-POV-eligible
movement-training candidates.

---

## 2026-06-11

### Experiment

LD-G2 (#108): golden-path validation harness for Lab Dashboard v1.  Ran the
offline harness (`scripts/ld_g2_golden_path.py`) against the committed
`lab/dashboard/public/` artifacts for the first time.

### Result

Contract gap found: `maps.json` recorded `"glb_bytes": 611980` for dm2 but
the committed `dm2.glb` is 613256 bytes (the GLB header's own declared length
also says 613256 — consistent internally).  The GLB itself is valid; only the
maps.json provenance field was stale.  Corrected in this PR.

All other contracts pass: routes-manifest (index + per-map JSON, 11 dm3 routes,
field completeness), GLB magic/version/SHA round-trip for dm3/frobodm2/trick,
verdicts.seed.json schema, deploy file-set (panes, top-level assets).

### Evidence

`tests/test_ld_g2_golden_path.py` (42 tests, including the broken-fixture
negative control).  `python -m unittest discover -s tests -p "test_*.py" -v`
→ 934 tests, all pass.

### Interpretation

The stale `glb_bytes` value in maps.json was inert for the dashboard (three.js
loads by path, not by length check), but it would have caused silent mismatch
in any future provenance auditor or integrity check.  Now corrected and
regression-locked.

### Confidence

High — the check directly compares file size vs declared size; no inference.

### Follow-up

Live-path evidence (telemetry WebSocket frame, deployed records.json schema)
deferred to a declared lab slot; see LD-G2 PR and the `--live` flag in the
harness.

---

## 2026-06-10

### Experiment

Nav-base mode 23 (frogbot navigation + bunnyhop weave actuation): movement doctrine
(never hop up stairs), goal pinning, look-through carrot, corner governor A/B, offline
pmove simulator. Approved phased plan executed overnight; full ledger in
experiments/nav_doctrine/evidence/run-ledger.md.

### Result

Stairs walked grounded (0 jump inputs pre-crest, 0.9-1.1s, 3/3 deterministic test);
directed reach on sng_shortcut2 4/10 -> 6-8/10 with the carrot (pooled 19/30 vs 4/10);
corner-precision governor REGRESSED reach to 4/10 in both trigger variants (removed);
pmove sim validated (human replay 692/692 frames <=0.20qu, edge 529.1 vs 528.2);
11-route difficulty ladder built (sng_shortcut2 easiest, sng_to_rl 9/11); prewar found
to corrupt the dm3 marker graph (different item set) and rejected for directed labs.
No trick jump attempted yet (Phase 4: graph trick links).

### Evidence

experiments/nav_doctrine/ (README + evidence/). Run IDs per claim in the ledger.
Key runs: stairs 20260610T010034-010144Z, carrot block 20260610T0048-0057Z,
baseline 20260609T2254-2303Z, sim validation artifacts/pmove-validation/.

### Interpretation

Navigation reliability (not speed) is the binding gap, and it is physics at precision
gates, not frogbot path stochasticity. Speed-preserving corner conversion belongs in
the offline sweep, not live heuristics.

### Confidence

High for stairs doctrine, sim validity, prewar rejection (each directly measured).
Medium for the carrot's exact effect size (n=10 blocks; 6-8/10 band).

### Follow-up

P3b offline sweep over mode-23 constants for corner conversion + edge speed;
walkable-route human reference demo for the 80% speed gate; Phase 4 trick link
(routing-layer speed prerequisite) once >=437 edge speed demonstrated on rung 1.

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

## 2026-06-06 - S6f Review-Fix Follow-Up

### Experiment

Addressed the new automated review finding on route-state attribution command joins before starting S7a.

### Result

- `scripts/attribute_route_state_windows.py` now uses diagnosis `user_id` to match sampled command rows by command `ed` when that id is present.
- Name matching remains only as a fallback for older artifacts without ids.
- If a player has a `user_id` but no command rows with matching `ed`, attribution now returns no command rows instead of falling back to a duplicate netname.
- Added regression tests for duplicate-name command rows and the no-id-match/no-name-fallback case.
- Regenerated S6c and S6d attribution evidence under the current attribution schema; S6e and S6f evidence did not change.

### Evidence

The existing S6 runs use distinct bot names and matching `user_id`/`ed` values, so the substantive S6 water-edge conclusions are unchanged. The fix prevents future or busier sessions with duplicate Frogbot names from silently mixing another player's route or water-state samples into the current window.

### Follow-up

Update the PR for Claude/reviewer context, then continue to S7a if there is no further blocking feedback.

## 2026-06-06 - S7a Exact-Player Movement Signature Scaffold

### Experiment

Added `scripts/summarize_player_movement_signatures.py` to build a compact player-signature scaffold from the existing S5b exact-player `dm3` aggregate. No KTX patch, route file, controller mode, remote lab run, or new human-demo parse changed.

Generated committed evidence:

- `experiments/human_comparison/evidence/player-signatures-s7a-dm3.json`
- `experiments/human_comparison/evidence/player-signatures-s7a-dm3.md`

### Result

- Avg speed and p95 speed remain generic S3g-vs-human land-speed gaps. The best S3g `dm3` bot is still `34.6` qu/s below the exact-player avg-speed minimum and `130.5` qu/s below the p95-speed minimum.
- Low-speed ratio is a thin candidate player-style axis: `Milton` `12.4%`, `carapace` `19.6%`, `yeti` `15.4%`; S3g has one bot inside the range and one above it.
- Jump cadence is a thin reference-only candidate axis: `44.0` to `48.6`/min, but the committed S3g bot summary does not carry the same metric.
- Airborne proxy is not useful as a player-style axis here because the exact-player reference spread is too small while the two S3g bot rows split above and below the range.
- The S7a stop condition triggered: three single-demo exact-player rows can seed axes, but cannot support stable player-specific style claims.

### Evidence

The S7a helper records per-player signature rows, feature-axis interpretations, bot relation classifications, and headline land-speed gaps in auditable JSON/Markdown. Tests cover generic land-speed gap classification, thin mixed candidate axes, missing-metric exclusion, and reference-only cadence handling.

### Interpretation

S7a moves the project into player-specific measurement, but not player-specific control. The current exact-player set is useful enough to say "do not hide the land-speed gap behind style," and useful enough to identify low-speed/cadence as candidate axes. It is not enough to build a Milton movement brain.

### Confidence

High that the S7a artifact correctly reflects the existing S5b aggregate and S3g bot rows.

Medium that low-speed and cadence will remain player-style axes after broader sampling, because the current reference set is one match per player.

### Follow-up

Ask Claude to review S7a. Proposed S7b: broaden exact-player movement references before controller work. Add repeated `dm3` samples for Milton/carapace/yeti where available, then rerun the signature scaffold to separate stable player style from one-match noise and the generic S3g land-speed gap.

## 2026-06-06 - S7a Review-Fix Follow-Up

### Experiment

Addressed Claude's S7a review finding before starting S7b reference broadening.

### Result

- Hardened the shared `load_json_if_present` helper so malformed JSON raises a clear `ValueError` instead of a raw `JSONDecodeError`.
- Hardened the same helper so valid-but-non-object JSON raises a clear `ValueError` instead of flowing into later `.get(...)` calls.
- Added regression coverage for missing, malformed, and non-object JSON.
- Tightened the S7a single-demo stop-condition flag so an empty reference set is not mislabeled as "one demo per player".

### Evidence

This is a review-hardening change only. It does not alter the committed S7a movement-signature evidence for the existing three exact-player rows.

### Follow-up

Update the PR for Claude/reviewer context, then continue with S7b if there is no further blocking feedback.

## 2026-06-06 - S7b Repeated Exact-Player Movement References

### Experiment

Broadened the S7 exact-player `dm3` reference set before controller work. Queried Turso `player_games` / `games` metadata, cross-referenced the existing `servexeri` 4on4 corpus manifest, selected one additional `dm3` demo for each S7a target, copied from the existing corpus, verified SHA-256, parsed through the human MVD pipeline, and regenerated the aggregate/signature evidence.

Selected repeats:

- `Milton`: `4on4_blue_vs_red[dm3]20260601-1914.mvd`, SHA `9acddc0807f997cbf59b0873907666f1a16af6624f2691389c22583781d85193`.
- `carapace`: `4on4_-s-_vs_]sr[[dm3]20260520-2032.mvd`, SHA `2eed3c5acf9cc0b22f391d08ac5eba7c2198b2ba12afb4c27992676fbf00894d`.
- `yeti`: `4on4_red_vs_blue[dm3]20260528-2109.mvd`, SHA `fa3792df611f650db9c47627812e63f277c9cb2bbb2f06dda4c291ad04e33246`.

### Result

- The selection path found repeated references for all three targets: Milton had `265` metadata rows, `30` manifest-eligible rows, and `28` additional available rows after excluding S5b demos; carapace had `172` / `22` / `21`; yeti had `439` / `17` / `16`.
- The six-row repeated aggregate keeps the same headline gap: reference avg range `282.8` to `314.2`, S3g `190.1` to `248.2`; reference p95 range `505.8` to `535.0`, S3g `361.0` to `375.3`.
- The repeated-player stability scaffold marks avg and p95 as stable but generic land-speed gaps.
- Low-speed ratio remains mixed/overlapping: between-player mean spread `4.3%`, max within-player spread `3.2%`, separation ratio `1.34`.
- Airborne proxy remains mixed/overlapping: between-player mean spread `4.7%`, max within-player spread `6.0%`, separation ratio `0.78`.
- Jump cadence is the only repeated candidate axis: between-player mean spread `7.6`/min, max within-player spread `3.7`/min, separation ratio `2.06`. It is still reference-only because committed S3g bot summaries do not carry cadence.

### Evidence

Committed artifacts:

- `experiments/human_comparison/evidence/human-reference-s7b-selection.json`
- `experiments/human_comparison/evidence/human-reference-s7b-selection.md`
- `experiments/human_comparison/evidence/human-reference-s7b-repeated-dm3-aggregate.json`
- `experiments/human_comparison/evidence/human-reference-s7b-repeated-dm3-aggregate.md`
- `experiments/human_comparison/evidence/player-signatures-s7b-dm3.json`
- `experiments/human_comparison/evidence/player-signatures-s7b-dm3.md`

S7b also found and fixed a practical parser bottleneck: three parallel full-match human parses produced `events.txt` files around `110 MB` each and timed out while computing movement metrics. `scripts/extract_movement_metrics.py` now uses an indexed landing-window speed lookup instead of scanning every segment for every airborne proxy landing. Focused regression tests confirm the indexed lookup matches the previous slow scan.

### Interpretation

S7b removes the S7a single-demo stop condition, but it does not authorize player-specific movement control. The strongest repeated signal is cadence, and it is not yet bot-comparable in the committed S3g summaries. Low-speed and airborne proxy are still too overlapping to become style targets. The generic avg/p95 gap remains the larger movement-realism problem.

### Confidence

High that repeated `dm3` references exist and were selected from the existing metadata/corpus path without hub download.

High that the six-row aggregate and stability scaffold reflect the parsed summaries.

Medium that cadence is a durable style axis, because S7b has only two demos per player and no bot-side cadence comparison yet.

### Follow-up

Ask Claude to review S7b. Proposed S7c: make the surviving repeated axes bot-comparable and controller-relevant by adding bot-side cadence/tempo metrics to the S3g summaries, then decide whether low-speed/cadence warrant player-style targets or whether more exact-player references are needed.

## 2026-06-06 - S7c Bot-Comparable Cadence

### Experiment

Made the S7b surviving repeated axis bot-comparable without rerunning the lab. The raw S3g movement artifacts already contained `jump_cadence_per_min`, so S7c carried that field through `scripts/summarize_moveprobe_plausibility.py`, `scripts/summarize_reference_aggregate.py`, and `scripts/summarize_player_movement_signatures.py`.

### Result

- Regenerated `experiments/ktx_moveprobe/evidence/moveprobe-s3g-summary.*` from existing S3g runs `20260606T003718Z` and `20260606T003808Z`.
- Generated a fresh S7c repeated aggregate and signature report:
  - `experiments/human_comparison/evidence/human-reference-s7c-bot-comparable-cadence-dm3-aggregate.*`
  - `experiments/human_comparison/evidence/player-signatures-s7c-dm3.*`
- Exact-player `dm3` cadence range is `40.4` to `51.0`/min, mean `45.2`/min.
- S3g `/ bro` cadence is `91.7`/min, above the repeated human range.
- S3g `/ goldenboy` cadence is `43.3`/min, within the repeated human range.
- Cadence is now classified as a bot-comparable repeated candidate style axis with mixed bot relation, rather than a reference-only axis.
- Avg and p95 remain generic land-speed gaps: reference avg `282.8` to `314.2` versus S3g `190.1` to `248.2`; reference p95 `505.8` to `535.0` versus S3g `361.0` to `375.3`.
- Claude review follow-up added explicit `bot_source_run_ids` to the S7c aggregate/signature evidence so the carried S3g cadence source is auditable from the committed files.

### Evidence

Committed artifacts:

- `experiments/ktx_moveprobe/evidence/moveprobe-s3g-summary.json`
- `experiments/ktx_moveprobe/evidence/moveprobe-s3g-summary.md`
- `experiments/human_comparison/evidence/human-reference-s7c-bot-comparable-cadence-dm3-aggregate.json`
- `experiments/human_comparison/evidence/human-reference-s7c-bot-comparable-cadence-dm3-aggregate.md`
- `experiments/human_comparison/evidence/player-signatures-s7c-dm3.json`
- `experiments/human_comparison/evidence/player-signatures-s7c-dm3.md`

Focused validation covered cadence propagation in the moveprobe plausibility summary, bot cadence classification in the reference aggregate, and bot-comparable repeated cadence handling in the player-signature scaffold.

### Interpretation

S7c completes the narrow handoff from repeated reference-only cadence to bot-comparable cadence. It does not authorize a broad player-specific controller. `/ goldenboy` already sits inside the human cadence range while still below human avg/p95 speed, so cadence alone is not a realism score. `/ bro` is far above the cadence range, making cadence useful as a diagnostic target for repeated-jump behavior.

### Confidence

High that the committed S3g artifacts already contained the bot cadence values and that S7c only changed summarization/evidence handling.

Medium that cadence should become a controller target, because the evidence has only two bot rows and two demos per exact player.

### Follow-up

Ask Claude to review S7c. Proposed S7d: decide what to do with bot-comparable repeated axes: keep cadence as a diagnostic target, broaden exact-player/bot samples, or design a tiny controller probe, while keeping the generic land-speed gap visible.

## 2026-06-06 - S7d Cadence Normalization Decision

### Experiment

Decided the S7c bot-comparable cadence path before controller work, using only existing committed artifacts. Added a small normalization helper that consumes the S7c aggregate and derives cadence per non-stationary minute, non-low-speed minute, and airborne-proxy minute.

### Result

- Generated `experiments/human_comparison/evidence/cadence-normalization-s7d-dm3.*`.
- Confirmed that `jump_cadence_per_min` is already active-row normalized (`airborne_proxy_count / active_time_s * 60`), so S7d tests stricter denominators rather than calling S7c raw match-wall-clock cadence.
- Non-stationary cadence range: exact-player `44.2` to `55.6`/min; S3g `/ bro` `92.1`/min above range; `/ goldenboy` `44.4`/min within range.
- Non-low-speed cadence range: exact-player `48.7` to `61.3`/min; S3g `/ bro` `124.1`/min above range; `/ goldenboy` `53.3`/min within range.
- Airborne-proxy cadence range: exact-player `128.0` to `143.1`/min; S3g `/ bro` `207.6`/min and `/ goldenboy` `174.4`/min both above range.

### Evidence

Committed artifacts:

- `scripts/decide_cadence_normalization.py`
- `experiments/human_comparison/evidence/cadence-normalization-s7d-dm3.json`
- `experiments/human_comparison/evidence/cadence-normalization-s7d-dm3.md`
- `tests/test_cadence_normalization_decision.py`

### Interpretation

S7d keeps cadence as a diagnostic signal, not a controller target. Movement-time normalization does not overturn the S7c mixed relation: `/ goldenboy` remains human-range and `/ bro` remains high. Airborne-proxy normalization is stricter and puts both bots above the exact-player range, which suggests the current cadence signal is entangled with air-rhythm/proxy segmentation and the unresolved land-speed gap.

### Confidence

High that the arithmetic is source-grounded in the committed S7c aggregate and the existing movement-metrics cadence definition.

Medium that airborne-proxy-normalized cadence reflects true jump rhythm, because airborne proxy is still position-derived rather than a grounded/usercmd label.

### Follow-up

Ask Code Sentinel to review S7d. Proposed S7e: broaden or dissect cadence evidence before controller work. The smallest next action is to add more bot rows and/or inspect airborne-proxy segmentation so cadence can be separated from the unresolved land-speed and air-rhythm gaps.

## 2026-06-06 - S7e Broadened Cadence Evidence

### Experiment

Broadened the bot side of S7 cadence evidence without rerunning the lab or changing KTX/Frogbot movement behavior. Added `scripts/broaden_cadence_evidence.py`, consumed the S7c exact-player aggregate, and read existing `dm3` mode-7 movement metrics from:

- S3g `20260606T003718Z`
- S6b `20260606T031102Z`
- S6d `20260606T041805Z`

S6e `20260606T044000Z` is explicitly excluded because it changed water-edge vertical command behavior, so it is a mode-7 variant rather than an unchanged diagnostic rerun.

### Result

- Generated `experiments/human_comparison/evidence/cadence-evidence-s7e-dm3.*`.
- Bot rows broadened from `2` to `6` while staying on existing `dm3` mode-7 artifacts.
- Active cadence remains mixed: exact-player `40.4` to `51.0`/min, broadened bots `18.5` to `138.7`/min.
- Non-stationary cadence remains mixed: exact-player `44.2` to `55.6`/min, broadened bots `18.6` to `146.6`/min.
- Non-low-speed cadence remains mixed: exact-player `48.7` to `61.3`/min, broadened bots `20.2` to `289.5`/min.
- Airborne-proxy cadence stays uniformly high: exact-player `128.0` to `143.1`/min, broadened bots `164.1` to `274.1`/min.
- The broadened rows also keep the generic land-speed issue visible: bot p95 range is `359.6` to `386.3` qu/s, still far below the exact-player p95 range from S7b/S7c.

### Evidence

Committed artifacts:

- `scripts/broaden_cadence_evidence.py`
- `tests/test_broaden_cadence_evidence.py`
- `experiments/human_comparison/evidence/cadence-evidence-s7e-dm3.json`
- `experiments/human_comparison/evidence/cadence-evidence-s7e-dm3.md`

### Interpretation

S7e strengthens S7d rather than overturning it. Cadence remains diagnostic and is still not controller-authorizing. The broadened bot set shows raw and movement-time cadence are unstable/mixed, while all unchanged mode-7 bot rows are above the exact-player airborne-proxy cadence range. That points toward an air-rhythm/proxy-segmentation issue, or toward the larger land-speed gap, rather than a simple cadence knob.

### Confidence

High that the included bot rows come from existing `dm3` mode-7 artifacts and that S6e is properly excluded as a behavior variant.

Medium that airborne-proxy cadence represents true jump rhythm, because the proxy is still position-derived and needs raw segment inspection before controller use.

### Follow-up

Ask Code Sentinel to review S7e. Proposed S7f: inspect raw airborne-proxy segment distributions, or deliberately pivot back to the larger land-speed gap, before any cadence controller probe.

## 2026-06-06 - S7f Raw Airborne-Proxy Segment Inspection

### Experiment

Inspected raw airborne-proxy segment distributions without rerunning the lab or changing KTX/Frogbot movement behavior. Added `scripts/inspect_airborne_proxy_segments.py`, replayed the movement-metrics airborne proxy over raw `events.txt` kind `5` samples, and compared:

- Six exact-player `dm3` reference rows from the S7c aggregate.
- Six unchanged mode-7 bot rows from the S7e evidence.

### Result

- Generated `experiments/human_comparison/evidence/airborne-segments-s7f-dm3.*`.
- Player-median airborne-proxy duration: exact-player `325.0` ms, bot `217.2` ms, bot/reference p50 ratio `0.668`.
- Player-median airborne-proxy Z range: exact-player `43.8` qu, bot `11.5` qu, ratio `0.264`.
- Player-median airborne-proxy horizontal speed: exact-player `431.8` qu/s, bot `114.4` qu/s, ratio `0.265`.
- Raw active average speed ratio is `0.735`, so the broader land-speed gap remains visible even outside the airborne-proxy subset.

### Evidence

Committed artifacts:

- `scripts/inspect_airborne_proxy_segments.py`
- `tests/test_inspect_airborne_proxy_segments.py`
- `experiments/human_comparison/evidence/airborne-segments-s7f-dm3.json`
- `experiments/human_comparison/evidence/airborne-segments-s7f-dm3.md`

### Interpretation

S7f explains why cadence should stay diagnostic. The bot airborne-proxy segments are not human-scale jumps; they are shorter, lower-Z, and much slower vertical-motion runs. The all-above airborne-proxy cadence relation from S7d/S7e is therefore a symptom of broken air/land rhythm and horizontal-speed production, not authorization for a cadence controller.

### Confidence

High that the segment distributions are source-grounded in the same `events.txt` samples and thresholds as `movement-metrics.json`.

Medium that the current airborne proxy fully captures real grounded/airborne state, because it is still position-derived rather than an engine grounded flag or usercmd label.

### Follow-up

Ask Code Sentinel to review S7f. Proposed S7g: characterize the land-speed gap around route and air segments before another controller probe. Cadence should remain diagnostic until bots produce human-scale airborne segments and horizontal speed.

## 2026-06-06 - S7g Land-Speed Gap Characterization

### Experiment

Characterized the land-speed gap without rerunning the lab or changing KTX/Frogbot movement behavior. Added `scripts/characterize_land_speed_gap.py`, consumed `experiments/human_comparison/evidence/airborne-segments-s7f-dm3.json`, and bucketed accepted movement segments by:

- airborne-proxy overlap,
- `400` ms pre-air and post-air transition windows,
- sampled strong/weak moveprobe command context,
- route low-dir-speed and `WATER_PATH` context when command artifacts exposed route state.

### Result

- Generated `experiments/human_comparison/evidence/land-speed-gap-s7g-dm3.*`.
- All accepted segment p50: exact-player `334.0` qu/s, bot `222.0` qu/s, bot/reference ratio `0.665`.
- Airborne-proxy segment p50: exact-player `433.8` qu/s, bot `122.6` qu/s, ratio `0.283`.
- Non-airborne segment p50: exact-player `320.0` qu/s, bot `312.1` qu/s, ratio `0.975`.
- Pre-air window p50: exact-player `418.0` qu/s, bot `207.1` qu/s, ratio `0.495`.
- Post-air window p50: exact-player `365.7` qu/s, bot `184.5` qu/s, ratio `0.505`.
- Sampled bot route `WATER_PATH` p50 speed is `95.3` qu/s.

### Evidence

Committed artifacts:

- `scripts/characterize_land_speed_gap.py`
- `tests/test_characterize_land_speed_gap.py`
- `experiments/human_comparison/evidence/land-speed-gap-s7g-dm3.json`
- `experiments/human_comparison/evidence/land-speed-gap-s7g-dm3.md`

### Interpretation

S7g narrows the land-speed problem. The bots are not simply slow everywhere: generic non-airborne p50 speed is close to the exact-player p50 in this row set. The gap concentrates around air-transition and airborne segments, with an additional route primitive warning from very slow sampled `WATER_PATH`/low-dir-speed contexts.

### Confidence

High that the segment buckets are derived from the same accepted movement segments and S7f row set used for cadence/airborne evidence.

Medium that route-state context fully explains the low-speed samples, because only bot rows have sampled command/route diagnostics and some route-state samples are diagnostic reruns rather than true human-comparable labels.

### Follow-up

Ask Code Sentinel to review S7g. Proposed S7h: decide whether the first controller probe targets air-transition horizontal speed production or a narrow route primitive such as `WATER_PATH` low-dir-speed recovery.

## 2026-06-06 - S7h Controller Probe Target Decision

### Experiment

Chose the first controller-probe target without rerunning the lab or changing KTX/Frogbot movement behavior. Added `scripts/choose_controller_probe_target.py`, consumed `experiments/human_comparison/evidence/land-speed-gap-s7g-dm3.json`, and compared:

- air-transition horizontal speed production,
- route `WATER_PATH` low-dir-speed recovery.

### Result

- Generated `experiments/human_comparison/evidence/controller-probe-target-s7h-dm3.*`.
- Selected target: `air_transition_horizontal_speed`.
- Deferred target: `water_path_low_dir_speed_recovery`.
- Air-transition evidence is human-comparable across all six exact-player reference rows and six bot rows: pre-air ratio `0.495`, airborne ratio `0.283`, post-air ratio `0.505`, and non-airborne ratio `0.975`.
- Route `WATER_PATH` remains important but secondary: p50 speed is `95.3` qu/s, route-state matched bot segments total `3,674`, and only `2` bot rows contribute `WATER_PATH` player p50s with no exact-player reference bucket.

### Evidence

Committed artifacts:

- `scripts/choose_controller_probe_target.py`
- `tests/test_choose_controller_probe_target.py`
- `experiments/human_comparison/evidence/controller-probe-target-s7h-dm3.json`
- `experiments/human_comparison/evidence/controller-probe-target-s7h-dm3.md`

### Interpretation

S7h chooses air-transition horizontal speed production as the first controller-probe target because it is broader and human-comparable. `WATER_PATH` is too slow to ignore, but it is a narrow bot-only route diagnostic, so it should be a guardrail and deferred route primitive rather than the first probe.

### Confidence

High that the target choice follows S7g evidence and does not use PR-body claims or markdown scraping.

Medium that the first air-transition probe will isolate the right controller mechanism, because S7h is a target-selection step and does not yet test a new command policy.

### Follow-up

Ask Code Sentinel to review S7h. Proposed S7i: design a tiny air-transition horizontal-speed probe with unchanged cadence reporting, unchanged route diagnostics, and stop conditions that reject all-segment speed gains if air-transition buckets or `WATER_PATH` context get worse.

## 2026-06-06 - S7i Air-Transition Probe Design

### Experiment

Designed the next tiny controller probe before changing controller behavior. Added `scripts/design_air_transition_probe.py`, consumed:

- `experiments/human_comparison/evidence/land-speed-gap-s7g-dm3.json`,
- `experiments/human_comparison/evidence/controller-probe-target-s7h-dm3.json`,
- `experiments/human_comparison/evidence/cadence-evidence-s7e-dm3.json`.

No KTX patch behavior, Frogbot behavior, lab runner behavior, parser behavior, route file, or cadence policy changed in S7i.

### Result

- Generated `experiments/human_comparison/evidence/air-transition-probe-design-s7i-dm3.*`.
- Probe id: `s7i-mode8-air-transition-horizontal-speed`.
- Verdict: `ready_to_design_tiny_air_transition_probe`.
- The follow-up probe must start from mode `7` and change horizontal command budget only during takeoff/air-transition windows.
- Required post-probe reporting includes pre-air, airborne, post-air, non-airborne, route low-dir-speed, `WATER_PATH`, active cadence, non-low-speed cadence, and airborne-proxy cadence.

### Evidence

Baseline values copied into the design artifact:

- Pre-air bot/reference p50 ratio `0.495`.
- Airborne-proxy bot/reference p50 ratio `0.283`.
- Post-air bot/reference p50 ratio `0.505`.
- Non-airborne bot/reference p50 ratio `0.975`.
- `WATER_PATH` bot p50 speed `95.279` qu/s from `2` bot rows.
- Airborne-proxy cadence remains diagnostic: bot range `164.1` to `274.1`/min versus reference `128.0` to `143.1`/min.

Stop conditions:

- Reject all-segment speed gains if no air-transition bucket improves.
- Reject required air-transition or non-airborne p50 regressions beyond `5%`.
- Reject or mark inconclusive if `WATER_PATH` gets worse or route/WATER_PATH diagnostics disappear.
- Do not claim success from cadence changes.

### Interpretation

S7i keeps the project from jumping straight into a controller tweak. The next patch must be small enough to answer one question: can a tightly scoped air-transition horizontal-command probe improve the human-comparable pre-air/airborne/post-air gap without hiding route or cadence regressions?

### Confidence

High that the design is source-grounded in committed S7g/S7h/S7e evidence.

Medium that a mode-8 implementation can isolate air-transition speed without changing unrelated route behavior, because that still needs a real probe.

### Follow-up

Ask Code Sentinel to review S7i. Proposed S7j: implement and run the tiny air-transition probe only if it preserves the S7i contract, then compare against the S7g/S7h/S7e baselines.

## 2026-06-06 - S7j Air-Transition Probe Result

### Experiment

Implemented and ran the S7i-constrained tiny controller probe. The KTX moveprobe patch now includes mode `8`, which starts from mode `7` and scales the desired horizontal command budget only while the bot is in a takeoff/recent-air/recent-landing transition window. Claude review caught that the first version passed a hardcoded `true` jump gate, making every grounded frame transition-active; the committed patch now uses the pre-probe `*jumping` state. The runner now accepts:

```bash
python scripts/run_bot_lab.py --map dm3 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 8 --moveprobe-sidemove 200 --moveprobe-transition-scale 1.25 --moveprobe-transition-window 0.4 --moveprobe-log-commands --moveprobe-log-interval 0.25 --run-id 20260606T163907Z
python scripts/run_bot_lab.py --map dm3 --duration 45 --bot-count 2 --bot-spacing 6 --moveprobe-mode 8 --moveprobe-sidemove 200 --moveprobe-transition-scale 1.25 --moveprobe-transition-window 0.4 --moveprobe-log-commands --moveprobe-log-interval 0.25 --run-id 20260606T164610Z
```

The temporary patched KTX build was deployed to `servexeri`, the lab was run twice, the live `qwprogs` module was restored to its original SHA-256 hash after each run, and the remote KTX checkout was returned clean.

### Result

- Generated `experiments/human_comparison/evidence/air-transition-probe-s7j-dm3.*`.
- Probe activation reporting worked: `546` sampled command rows had `probe_state`, and `110` were transition-active (`20.1%`).
- Pre-air p50 fell from `207.1` to `149.7` qu/s.
- Airborne-proxy p50 fell from `122.6` to `100.4` qu/s.
- Post-air p50 fell from `184.5` to `179.6` qu/s.
- All accepted segment p50 improved only slightly from `222.0` to `230.0` qu/s.
- Non-airborne p50 fell from `312.1` to `286.3` qu/s, failing the S7i guardrail.
- Route low-dir-speed p50 improved from `141.0` to `201.2` qu/s.
- Route `WATER_PATH` p50 stayed barely above baseline where present: `95.3 -> 96.2` qu/s.

### Evidence

Committed artifacts:

- `experiments/ktx_moveprobe/frogbot-moveprobe.patch`
- `scripts/run_frobodm2_lab.py`
- `scripts/compare_air_transition_probe.py`
- `tests/test_extract_movement_metrics.py`
- `tests/test_compare_air_transition_probe.py`
- `experiments/human_comparison/evidence/air-transition-probe-s7j-dm3.json`
- `experiments/human_comparison/evidence/air-transition-probe-s7j-dm3.md`

### Interpretation

S7j is rejected evidence, not accepted controller behavior. Claude's gate fix was necessary, and the second corrected run restored enough `WATER_PATH` guardrail coverage to make the verdict stricter than "inconclusive." The combined fixed runs show that the mode-8 lever can shift aggregate speed, but it worsens the intended air-transition buckets and fails the non-airborne guardrail. Do not promote mode `8` or claim movement realism improved.

### Confidence

High that the result follows the S7i stop-condition contract and uses local validation plus two real lab runs.

Medium that two short two-bot `dm3` runs fully characterize the mode, because the current evidence is enough to reject this exact probe but not enough to choose the next controller policy.

### Follow-up

Ask Code Sentinel to review S7j. Proposed S7k: inspect the failed bucket and command/probe activation context before trying another controller probe.

## 2026-06-06 - S7k Failed-Bucket Diagnosis

### Experiment

Diagnosed the corrected S7j failure without adding another movement mode or rerunning the lab. Added `scripts/diagnose_s7j_failed_buckets.py`, consumed:

- `experiments/human_comparison/evidence/air-transition-probe-s7j-dm3.json`,
- `experiments/human_comparison/evidence/land-speed-gap-s7g-dm3.json`,
- local corrected S7j run artifacts `20260606T163907Z` and `20260606T164610Z`.

The script recomputes per-segment command/probe/route context for the failed pre-air, airborne-proxy, and non-airborne buckets.

### Result

- Generated `experiments/human_comparison/evidence/failed-bucket-diagnosis-s7k-dm3.*`.
- Pre-air stayed failed: S7g/S7j p50 `207.1 -> 149.7` qu/s, with strong command ratio `0.936`, probe-active ratio `0.091`, low-dir ratio `0.565`, and `WATER_PATH` ratio `0.469`.
- Airborne-proxy stayed failed: `122.6 -> 100.4` qu/s, with strong command ratio `0.925`, probe-active ratio `0.140`, low-dir ratio `0.535`, and `WATER_PATH` ratio `0.404`.
- Non-airborne guardrail failure was route/context contaminated: `312.1 -> 286.3` qu/s overall, but `/ goldenboy` in `20260606T164610Z` had non-airborne p50 `100.8` qu/s, low-dir ratio `0.626`, and `WATER_PATH` ratio `0.614`.
- The clean first run rows still show air-transition weakness without `WATER_PATH`: `/ bro` airborne p50 `101.8` qu/s and `/ goldenboy` airborne p50 `181.2` qu/s while `WATER_PATH` ratio was `0.000`.

### Evidence

Committed artifacts:

- `scripts/diagnose_s7j_failed_buckets.py`
- `tests/test_diagnose_s7j_failed_buckets.py`
- `experiments/human_comparison/evidence/failed-bucket-diagnosis-s7k-dm3.json`
- `experiments/human_comparison/evidence/failed-bucket-diagnosis-s7k-dm3.md`

Review hardening keeps the default evidence regeneration clean-checkout reproducible from the committed compact context source, creates both custom output directories, skips segments with missing/non-numeric speeds, and ignores nullable route `path_state` values instead of treating them as `WATER_PATH`.

### Interpretation

Water is not the whole problem. `WATER_PATH` and low-dir-speed context explain the non-airborne guardrail contamination and part of the air-bucket mix, but the intended air-transition buckets still fail under strong command/probe coverage even in rows without `WATER_PATH`.

This is also not yet evidence that Frogbots lack high-level intelligence or full 3D map understanding. The current failure split is lower-level: command-policy/physics timing around air transitions plus route/map-context guardrails around low-dir-speed and `WATER_PATH`.

### Confidence

High that S7k identifies the dominant bucket-context split in the corrected S7j artifacts.

Medium that the exact next probe should be air-transition again, because S7k supports a narrower context-gated probe but does not design it yet.

### Follow-up

Ask Claude/Code Sentinel to review S7k. Proposed S7l: design a smaller context-gated air-transition probe that either excludes low-dir-speed/`WATER_PATH` contexts or treats them as hard stop-condition slices before another lab rerun.

## 2026-06-06 - S7l Context-Gated Probe Design

### Experiment

Designed the narrower air-transition probe requested by S7k without changing controller behavior or rerunning the lab. Added `scripts/design_context_gated_probe.py`, consuming:

- `experiments/human_comparison/evidence/failed-bucket-diagnosis-s7k-dm3.json`.

The helper splits S7k player/bucket rows into `clean_air_transition_candidate`, `route_guardrail_slice`, and `measurement_risk` slices so the next probe cannot pass on all-segment or route-dirty gains alone.

### Result

- Generated `experiments/human_comparison/evidence/context-gated-probe-design-s7l-dm3.*`.
- Clean pre-air evidence is sufficient for a bounded claim path: `2` player rows, `326` segments, p50 `229.0` qu/s.
- Clean airborne-proxy evidence is sufficient for a bounded claim path: `3` player rows, `844` segments, p50 `101.8` qu/s.
- Route-dirty evidence remains substantial and must be scored as a guardrail: pre-air `1` row / `1,445` segments, airborne-proxy `1` row / `1,179` segments, non-airborne `1` row / `766` segments.
- The next probe must activate only in live clean route context: no `WATER_PATH`, no low-dir-speed route primitive, command/probe diagnostics present, and inside the intended transition window.

### Evidence

Committed artifacts:

- `scripts/design_context_gated_probe.py`
- `tests/test_design_context_gated_probe.py`
- `experiments/human_comparison/evidence/context-gated-probe-design-s7l-dm3.json`
- `experiments/human_comparison/evidence/context-gated-probe-design-s7l-dm3.md`

Review hardening after Claude/Gemini feedback wraps missing/corrupt JSON and invalid segment counts in the typed `ContextGatedProbeInputError` path, and documents the intentional low-dir/WATER_PATH dirty-threshold asymmetry. The design artifact semantics remain unchanged.

### Interpretation

S7l does not prove movement realism improved. It proves the next Frogbots test can be made sharper: clean air-transition slices exist, but route-dirty slices are large enough that they must be excluded from success claims and preserved as hard guardrails. This keeps the KTX/Frogbots hypothesis alive for one more bounded probe without treating water or all-segment speed as the whole problem.

### Confidence

High that S7l accurately encodes the S7k split into a stricter probe contract.

Medium that the next implementation will be easy inside KTX, because S7l requires the future patch to gate on live Frogbot route/water state rather than offline labels.

### Follow-up

Ask Claude/Code Sentinel to review S7l. Proposed S7m: implement and run the context-gated air-transition probe, then compare clean and route-dirty slices separately against S7k/S7g baselines.

## 2026-06-06 - QWD POV Usercmd Extractor Phase 1

### Experiment

Added a standalone QWD POV-demo usercmd extractor for Phase 1 action labels. The parser walks flat `.qwd` records, decodes `dem_cmd` as the ezQuake raw `usercmd_t` dump plus following viewangle payload, skips length-prefixed `dem_read` payloads, and emits `komodobots.qwd_usercmd.v1` line-delimited JSON.

The source-grounded layout is the ezQuake/qwprot `usercmd_t`: `byte msec`, three bytes padding, `float angles[3]`, `short forwardmove/sidemove/upmove`, `byte buttons`, `byte impulse`, for a validated size of `24` bytes.

### Result

- Synthetic unit tests lock the byte layout and round-trip known `dem_cmd` values.
- A truncated `dem_cmd` fails explicitly instead of silently desyncing.
- Real QWD files walked to exact EOF with no warnings.
- Phase 2 state/action pairing is deliberately not implemented in this step.

### Evidence

Validation commands:

```powershell
python -m unittest tests.test_qwd_usercmd -v
python tools/qwd_usercmd/qwd_usercmd.py "C:\Users\benya\projects\quakeworld\data\quake-development\clients\xerialqw-bench\qw\matchinfo\demos\tricks\dm2_big_to_gl.qwd" --output artifacts/qwd-usercmd/dm2_big_to_gl.ndjson --include-cmd-angles
python tools/qwd_usercmd/qwd_usercmd.py "C:\Users\benya\projects\quakeworld\data\quake-development\clients\xerialqw-bench\qw\matchinfo\demos\tricks\dm2_bunny_to_gl.qwd" --output artifacts/qwd-usercmd/dm2_bunny_to_gl.ndjson --include-cmd-angles --strict-plausibility
```

Focused tests: `6` tests passed.

Real-demo parse summaries:

- `dm2_big_to_gl.qwd`: SHA-256 `44456a0a1cf2e386bc3230907c40975c433ff0654ea727974474cf8a9e33f6f7`, `50112` bytes read of `50112`, `eof_clean=true`, `375` command frames, `388` `dem_read` records, `1` `dem_set`, duration `4.858` s, command rate `77.192` fps, warnings `[]`.
- `dm2_bunny_to_gl.qwd`: `162582` bytes read of `162582`, `eof_clean=true`, `1537` command frames, `1389` `dem_read` records, `1` `dem_set`, duration `20.736` s, command rate `74.122` fps, warnings `[]`.

Plausibility evidence from `dm2_bunny_to_gl.qwd`: `msec` range `12..53`, `forwardmove` range `-400..380`, `sidemove` range `-380..380`, `upmove=0`, buttons `[0, 1, 2, 3]`, impulses `[2, 7]`, and `1086` distinct rounded yaw samples.

Committed artifacts:

- `tools/qwd_usercmd/qwd_usercmd.py`
- `tools/qwd_usercmd/README.md`
- `tests/test_qwd_usercmd.py`

Raw NDJSON outputs remain ignored under `artifacts/qwd-usercmd/`.

### Interpretation

POV QWDs can supply exact human input/action labels for movement research, while MVDs remain the state/evaluation source. This weakens the earlier assumption that human learning must be purely inverse control when a matching POV QWD exists, but it does not change the MVD limitation for ordinary server-side demos.

### Confidence

High for Phase 1 action-stream extraction on current ezQuake-style QWDs, because the parser is source-grounded, layout-tested, and walked two real files to clean EOF.

Medium for broad QWD compatibility until more POV demos from different client builds are checked, because `dem_cmd` stores a raw in-memory struct and old/non-ezQuake builds could differ.

### Follow-up

Ask Claude/Code Sentinel to review the QWD layout and record walking. The next smallest useful experiment is Phase 2 design: parse enough QWD `dem_read` client state to pair each command with observed movement state without assuming MVD `DF_` playerinfo flags apply to QWD.

## 2026-06-06 - QWD Trajectory Route Applicability Probe

### Experiment

Tested whether first-person QWD trick demos can provide not only exact human actions, but also same-frame movement state and route-like trajectory geometry that could eventually inform a Frogbot movement controller.

Added `scripts/probe_qwd_route_applicability.py`. The probe:

- decodes exact outgoing commands through `tools/qwd_usercmd/qwd_usercmd.py`;
- source-checks QWD `svc_playerinfo` against ezQuake `cl_ents.c`, `sv_ents.c`, and `MSG_ReadCoord()`;
- accepts self-player state only at QWD network-body offset `8`, avoiding false-positive `svc_playerinfo` bytes later in payloads;
- pairs command/state rows by frame order;
- measures pair coverage, time deltas, speed distributions, continuity splits, command ratios, and waypoint-downsampled route candidates.

### Result

All `29` local `dm3_*.qwd` trick demos produced exact command/state frame matches:

- Total command frames: `22,749`.
- Total paired frames: `22,749`.
- Paired coverage min/p50: `1.000` / `1.000`.
- Route candidates after `64` qu waypoint downsampling: `29` of `29`.
- No real continuity split after duplicate-tick handling: `26` of `29`.

The earlier naive byte-scan prototype produced impossible speed spikes in water-heavy demos because unrelated payload bytes could look like `svc_playerinfo`. Anchoring state recovery to the QWD network-body offset fixed that failure mode and kept water-heavy demos usable as measured trajectories.

### Evidence

Validation commands:

```powershell
python -m unittest tests.test_qwd_usercmd tests.test_probe_qwd_route_applicability -v
python scripts/probe_qwd_route_applicability.py --demo-root "C:\Users\benya\projects\quakeworld\data\quake-development\clients\xerialqw-bench\qw\matchinfo\demos\tricks" --pattern "dm3_*.qwd" --output-json experiments/qwd_route_probe/evidence/qwd-trajectory-route-probe-dm3.json --output-md experiments/qwd_route_probe/evidence/qwd-trajectory-route-probe-dm3.md --raw-output-dir artifacts/qwd-route-probe --waypoint-spacing 64
```

Focused tests: `8` tests passed across the existing QWD usercmd extractor and new route-applicability probe.

Committed artifacts:

- `scripts/probe_qwd_route_applicability.py`
- `tests/test_probe_qwd_route_applicability.py`
- `experiments/qwd_route_probe/evidence/qwd-trajectory-route-probe-dm3.json`
- `experiments/qwd_route_probe/evidence/qwd-trajectory-route-probe-dm3.md`

Raw paired rows and waypoint exports remain ignored under `artifacts/qwd-route-probe/`.

### Interpretation

This is a real bridge from human POV demos to movement-controller evidence. For matching QWDs, Komodobots can now pair exact human commands with plausible self trajectory and reduce that trajectory into route-like waypoints.

It is not yet evidence that a Frogbot can execute those waypoints or replay those commands. Frogbot application still needs semantic route mapping to `.bot` route concepts, a server-loop controller probe, and stop conditions that reject combat, route, water, or air-transition regressions.

### Confidence

High for this local DM3 QWD corpus: frame coverage is exact and the parser is source-grounded with false-positive guards.

Medium for broader QWD/client compatibility until demos from more clients and maps are checked.

Medium-low for direct Frogbot applicability until one route candidate is mapped against `dm3.bot` and tried in a controlled KTX/Frogbot experiment.

### Follow-up

Next smallest useful experiment: choose one clean route candidate such as `dm3_sng_shortcut.qwd`, compare its extracted waypoints against the current `dm3.bot` marker graph, and decide whether the first Frogbot-facing probe should be route-following, command-imitation, or a hybrid waypoint/controller test.

## 2026-06-06 - QWD SNG Shortcut to Frogbot Route Mapping

### Experiment

Mapped one clean QWD route candidate, `dm3_sng_shortcut.qwd`, onto the current KTX Frogbot `dm3.bot` marker graph. Added `scripts/map_qwd_route_to_frogbot.py` to regenerate the QWD waypoints, find nearest static Frogbot markers, collapse the marker sequence, measure direct edge and shortest-path graph alignment, and choose the smallest Frogbot-facing probe type.

### Result

The SNG shortcut is spatially close to existing Frogbot markers, but it is not a direct match to the existing `.bot` route topology:

- QWD command/state coverage: `1.000`.
- QWD waypoints at `64` qu spacing: `33`.
- Collapsed nearest-marker sequence: `14` markers.
- Nearest-marker p50/p95/max: `70.112` / `120.324` / `142.597` qu.
- Waypoints within `128` qu of a static marker: `0.939`.
- Direct `.bot` edge ratio across collapsed transitions: `0.0`.
- Graph reachable ratio: `1.0`, but shortest-path p50/p95/max is `5.0` / `15.8` / `17.0` edges.
- QWD command profile is side-move dominant: nonzero forward `0.089`, nonzero side `0.718`, jump `0.284`.

### Evidence

Validation commands:

```powershell
python scripts/map_qwd_route_to_frogbot.py --demo "C:\Users\benya\projects\quakeworld\data\quake-development\clients\xerialqw-bench\qw\matchinfo\demos\tricks\dm3_sng_shortcut.qwd" --bot-map "C:\Users\benya\projects\quakeworld\engine\ktx\resources\example-configs\ktx\bots\maps\dm3.bot" --waypoint-spacing 64 --output-json experiments/qwd_route_probe/evidence/qwd-frogbot-route-map-dm3-sng-shortcut.json --output-md experiments/qwd_route_probe/evidence/qwd-frogbot-route-map-dm3-sng-shortcut.md
python -m unittest tests.test_map_qwd_route_to_frogbot -v
```

Focused tests: `3` mapping tests passed.

Committed artifacts:

- `scripts/map_qwd_route_to_frogbot.py`
- `tests/test_map_qwd_route_to_frogbot.py`
- `experiments/qwd_route_probe/evidence/qwd-frogbot-route-map-dm3-sng-shortcut.json`
- `experiments/qwd_route_probe/evidence/qwd-frogbot-route-map-dm3-sng-shortcut.md`

### Interpretation

The first QWD-to-Frogbot server-loop probe should be a `hybrid_waypoint_controller_probe`, not pure route following. Existing `dm3.bot` markers are close enough to provide spatial context, but the direct edges do not encode the human shortcut path. The human command labels are mostly sidemove rather than forwardmove, so reducing the move to a simple forward marker chase would discard the useful QWD signal.

### Confidence

High that pure `.bot` route-following is the wrong first SNG shortcut probe.

Medium that a hybrid waypoint/controller probe is the best next step, because this mapping still has not executed inside KTX.

### Follow-up

Ask Claude/Code Sentinel to review the mapping logic and the recommendation. Next smallest useful experiment: design a tiny server-loop SNG shortcut probe that feeds a temporary waypoint target plus QWD-local command profile into the existing moveprobe path while preserving route, water, command, cadence, and movement-bucket diagnostics.

## 2026-06-06 - QWD SNG Hybrid Probe Design

### Experiment

Designed the first Frogbot-facing runtime probe from the committed `dm3_sng_shortcut.qwd` mapping without changing KTX, Frogbot behavior, route files, lab runners, parsers, or metrics.

Added `scripts/design_qwd_sng_hybrid_probe.py`. The helper consumes `experiments/qwd_route_probe/evidence/qwd-frogbot-route-map-dm3-sng-shortcut.json` and writes a bounded contract for a temporary hybrid waypoint/controller moveprobe mode.

### Result

Generated `experiments/qwd_route_probe/evidence/qwd-sng-hybrid-probe-design-dm3.*`.

The design keeps the QWD evidence narrow and executable:

- `14` control points from the collapsed SNG shortcut mapping.
- Recommended temporary moveprobe mode: `9`.
- Suggested activation: only on `dm3`, near the first QWD control point.
- Suggested control-point radius: `96` qu; start radius: `192` qu.
- Recommended command profile: waypoint attraction `forwardmove=320`, QWD-style `sidemove=508`, forced jump only while the probe is active and reported.
- No `dm3.bot` mutation.
- Required diagnostics: route, water, command, probe activation, cadence, and movement buckets.

### Evidence

Validation commands:

```powershell
python -m py_compile scripts/design_qwd_sng_hybrid_probe.py
python -m unittest tests.test_design_qwd_sng_hybrid_probe -v
python scripts/design_qwd_sng_hybrid_probe.py --output-json experiments/qwd_route_probe/evidence/qwd-sng-hybrid-probe-design-dm3.json --output-md experiments/qwd_route_probe/evidence/qwd-sng-hybrid-probe-design-dm3.md
```

Focused tests: `6` design tests passed.

Committed artifacts:

- `scripts/design_qwd_sng_hybrid_probe.py`
- `tests/test_design_qwd_sng_hybrid_probe.py`
- `experiments/qwd_route_probe/evidence/qwd-sng-hybrid-probe-design-dm3.json`
- `experiments/qwd_route_probe/evidence/qwd-sng-hybrid-probe-design-dm3.md`

### Interpretation

The SNG QWD trajectory is close enough to Frogbot marker space for context, but direct route topology still does not match the shortcut and the human action profile is side-move dominant. The next evidence must therefore be a temporary server-loop hybrid waypoint/controller probe, not route editing or a pure marker chase.

This still does not prove movement realism improved. It only says the next KTX/Frogbot experiment is sufficiently bounded to try before abandoning the Frogbots substrate.

### Confidence

High that the design faithfully consumes the committed SNG mapping artifact and preserves the QWD side-move signal.

Medium that mode `9` will be easy to implement cleanly inside KTX, because the runtime patch still needs to pass waypoint strings, report QWD probe state, and preserve existing diagnostics.

### Follow-up

Ask Claude/Code Sentinel to review the design gate. Next smallest useful experiment: implement the temporary mode `9` SNG hybrid probe plus a comparison helper, run it on `dm3`, and decide whether positive server-loop evidence justifies applying the same QWD route/controller method to the remaining DM3 QWD moves.

## 2026-06-06 - QWD SNG Hybrid Server-Loop Probe

### Experiment

Implemented the bounded QWD-derived SNG shortcut runtime probe described by the QWD SNG design artifact. The patch adds temporary mode `9` to the KTX moveprobe scaffold, with bounded QWD waypoint parsing, start/control-point radius handling, preserved combat-view projection, and a `qwd=` command-log suffix.

Updated the lab runner to pass QWD waypoint/radius cvars through base64-safe remote shell transport and parse nested QWD command state. Added `scripts/compare_qwd_sng_hybrid_probe.py` to score generated KTX/Frogbot runs against the SNG design guardrails.

### Result

The first real `dm3` mode-9 run is inconclusive, not positive.

Run `20260606T221429Z` produced real server-loop evidence:

- `866` sampled command/QWD rows.
- QWD active samples: `11`.
- Max active seconds: `1.12`, passing the minimum activation gate.
- Max advanced control points: `2`, below the required `4`.
- Diagnostics were preserved: route, water, probe-state, cadence, and movement metrics were available.
- The active QWD command profile passed where active: side ratio `1.0`, jump ratio `1.0`.
- Slow/stuck success and route-dirty success guardrails did not reject the run.

### Evidence

Committed artifacts:

- `scripts/compare_qwd_sng_hybrid_probe.py`
- `tests/test_compare_qwd_sng_hybrid_probe.py`
- `experiments/qwd_route_probe/evidence/qwd-sng-hybrid-probe-result-dm3.json`
- `experiments/qwd_route_probe/evidence/qwd-sng-hybrid-probe-result-dm3.md`
- Updated `experiments/ktx_moveprobe/frogbot-moveprobe.patch`
- Updated `scripts/run_frobodm2_lab.py`

Validation:

```powershell
git apply --check experiments/ktx_moveprobe/frogbot-moveprobe.patch
ssh servexeri "set -e; cd ~/nquakesv/build/ktx; git apply --check ~/komodobots-lab/qwd-sng-mode9.patch; git apply ~/komodobots-lab/qwd-sng-mode9.patch; cmake --build build -- -j2"
python scripts/run_bot_lab.py --map dm3 --duration 45 --bot-count 2 --bot-spacing 6 --moveprobe-mode 9 --moveprobe-forwardmove 320 --moveprobe-sidemove 508 --moveprobe-qwd-waypoints "<14 QWD control points>" --moveprobe-qwd-point-radius 96 --moveprobe-qwd-start-radius 192 --moveprobe-log-commands --moveprobe-log-interval 0.1
python scripts/compare_qwd_sng_hybrid_probe.py --bot-run-id 20260606T221429Z --output-json experiments\qwd_route_probe\evidence\qwd-sng-hybrid-probe-result-dm3.json --output-md experiments\qwd_route_probe\evidence\qwd-sng-hybrid-probe-result-dm3.md
python -m unittest tests.test_compare_qwd_sng_hybrid_probe tests.test_extract_movement_metrics -v
```

The remote KTX source and deployed `qwprogs.so` were restored to the stock build after the lab run.

### Interpretation

The QWD-to-Frogbot path is now executable inside the engine-native shell, but it has not yet shown that Frogbots can learn or perform the SNG shortcut. This result keeps KTX/Frogbots viable for one narrower repair step because the probe activated and preserved diagnostics, but it blocks expansion to the remaining DM3 QWD moves until activation/control-point advancement improves.

### Confidence

High that mode `9` can be injected, logged, scored, and rolled back safely in the current lab.

Medium that the next repair is only activation/spawn/context setup. The first run advanced two points, so controller policy may also be part of the limitation.

### Follow-up

Repair the mode-9 SNG probe setup before expanding. The next smallest useful experiment is to make QWD activation and control-point advancement robust enough to reach at least `4` control points while preserving the same route/water/cadence/slow-success guardrails.

## 2026-06-06 - QWD SNG Timing and Start-Context Diagnosis

### Experiment

Diagnosed the first mode-9 SNG probe result without another live KTX run. Added `scripts/diagnose_qwd_sng_probe.py` and tightened `scripts/compare_qwd_sng_hybrid_probe.py` so QWD activation/advancement must overlap the parsed MVD movement window before movement guardrails can support a positive claim.

The diagnosis aligns command-log server time to MVD-relative event time by subtracting the demo start `ServerTime` from events kind `0`, then checks closest MVD approaches to the QWD control points.

### Result

The first SNG run remains inconclusive, but the failure is now more precisely attributed:

- `/ bro` never activated and never entered the configured `192` qu start radius during the MVD window; closest MVD approach to control point `0` was `281.954` qu.
- `/ goldenboy` activated for `11` sampled command rows and advanced `2` control points, but the aligned active window was `47044-48082` ms while the parsed match duration was `45816` ms.
- The scorer now reports `qwd_activation_mvd_overlap` as inconclusive for `/ goldenboy`, and `control_point_advancement` now requires in-window advancement rather than raw command-log advancement, so the result no longer implies that movement guardrails observed the active advancement window.
- The helper also hardens nullable command fields before integer casts in the QWD SNG scorer.

### Evidence

Committed artifacts:

- `scripts/diagnose_qwd_sng_probe.py`
- `tests/test_diagnose_qwd_sng_probe.py`
- `experiments/qwd_route_probe/evidence/qwd-sng-hybrid-probe-diagnosis-dm3.json`
- `experiments/qwd_route_probe/evidence/qwd-sng-hybrid-probe-diagnosis-dm3.md`
- Updated `experiments/qwd_route_probe/evidence/qwd-sng-hybrid-probe-result-dm3.*`

Validation:

```powershell
python -m py_compile scripts\compare_qwd_sng_hybrid_probe.py scripts\diagnose_qwd_sng_probe.py
python -m unittest tests.test_compare_qwd_sng_hybrid_probe tests.test_diagnose_qwd_sng_probe -v
python scripts\compare_qwd_sng_hybrid_probe.py --bot-run-id 20260606T221429Z
python scripts\diagnose_qwd_sng_probe.py --bot-run-id 20260606T221429Z
```

### Interpretation

This does not prove Frogbots learned SNG, and it does not disprove the QWD-to-Frogbot path. It says the next live experiment must first make QWD activation overlap recorded MVD movement evidence. Changing the controller projection or expanding to other DM3 QWD moves would be premature until the timing/start-context gate is clean.

### Confidence

High for the timing-window diagnosis because it uses the same run's command log, events kind `0` server start time, parser match duration, and MVD position samples.

Medium for the start-context attribution because the first run used ordinary bot spawning/route context; a controlled spawn or earlier recording window could change the closest-approach result.

### Follow-up

Repair mode-9 setup so activation happens inside the recorded MVD window and at least one bot enters the start radius under measured conditions. Only then rerun the SNG probe and re-evaluate control-point advancement.

## 2026-06-06 - QWD SNG Setup Repair Rerun

### Experiment

Temporarily redeployed the existing mode-9 KTX moveprobe patch, reran the `dm3_sng_shortcut.qwd` hybrid probe, and changed only setup/radius timing inputs: same QWD control points, same `96` qu point radius, same `forwardmove=320` / `sidemove=508` profile, but widened the start radius from `192` to `320` qu. The live KTX module was restored to stock after the run.

The first attempted `65` second rerun produced useful command logs but no committed evidence because the minimal client timed out, the match ended, and KTX canceled/deleted the MVD. The accepted rerun used the original `45` second duration to avoid that timeout.

### Result

Run `20260606T231007Z` repaired the timing/start-context evidence blocker but still did not prove the SNG move was learned.

- The run produced a non-empty MVD, parser output, movement metrics, and `867` sampled command rows.
- QWD active samples: `627`.
- Max active seconds: `16.591`.
- Max advanced control points inside the parsed MVD window: `4`.
- `qwd_activation_mvd_overlap`, `control_point_advancement`, diagnostic preservation, QWD command profile, and route-dirty guardrails all passed.
- The run was rejected by `waypoint_only_slow_success`: `/ bro` advanced `4` points but had low-speed ratio `0.429` and stationary ratio `0.253`, above the `0.40` / `0.25` guardrails.
- `/ goldenboy` activated for `181` rows but advanced `0` points.

### Evidence

Committed artifacts:

- `experiments/qwd_route_probe/evidence/qwd-sng-setup-repair-result-dm3.json`
- `experiments/qwd_route_probe/evidence/qwd-sng-setup-repair-result-dm3.md`
- `experiments/qwd_route_probe/evidence/qwd-sng-setup-repair-diagnosis-dm3.json`
- `experiments/qwd_route_probe/evidence/qwd-sng-setup-repair-diagnosis-dm3.md`

Validation commands:

```powershell
git apply --check C:\Users\benya\projects\quakeworld\komodobots\experiments\ktx_moveprobe\frogbot-moveprobe.patch
ssh servexeri 'set -e; cd ~/nquakesv/build/ktx; git apply --check ~/komodobots-lab/qwd-sng-setup-repair.patch; git apply ~/komodobots-lab/qwd-sng-setup-repair.patch; cmake --build build -- -j2'
python scripts\run_bot_lab.py --map dm3 --duration 45 --bot-count 2 --bot-spacing 6 --moveprobe-mode 9 --moveprobe-forwardmove 320 --moveprobe-sidemove 508 --moveprobe-qwd-waypoints "<14 QWD control points>" --moveprobe-qwd-point-radius 96 --moveprobe-qwd-start-radius 320 --moveprobe-log-commands --moveprobe-log-interval 0.1
python scripts\compare_qwd_sng_hybrid_probe.py --bot-run-id 20260606T231007Z --stage qwd-sng-setup-repair-dm3 --output-json experiments\qwd_route_probe\evidence\qwd-sng-setup-repair-result-dm3.json --output-md experiments\qwd_route_probe\evidence\qwd-sng-setup-repair-result-dm3.md
python scripts\diagnose_qwd_sng_probe.py --bot-run-id 20260606T231007Z --stage qwd-sng-setup-repair-dm3 --result-json experiments\qwd_route_probe\evidence\qwd-sng-setup-repair-result-dm3.json --output-json experiments\qwd_route_probe\evidence\qwd-sng-setup-repair-diagnosis-dm3.json --output-md experiments\qwd_route_probe\evidence\qwd-sng-setup-repair-diagnosis-dm3.md
python -m py_compile scripts\diagnose_qwd_sng_probe.py
python -m unittest tests.test_diagnose_qwd_sng_probe -v
```

Remote rollback checks:

```text
live symlink -> qwprogs-1.48-dev-08807d.so
~/nquakesv/build/ktx: clean master...origin/master
localhost:28599 DOWN
```

### Interpretation

The QWD-to-Frogbot path crossed a real milestone: a human-derived SNG control sequence can now activate and advance the required four points inside a recorded MVD window. That keeps KTX/Frogbots viable for a narrower follow-up.

It is still not learned movement. The guardrails correctly block the claim because the bot reached those points with too much slow/stationary time. The remaining issue is now controller-vs-route-vs-radius/context attribution, not MVD timing.

### Confidence

High that timing/start-context setup was repaired for this run.

Medium that the slow-success rejection is a controller-policy problem; the widened `320` qu start radius may also be introducing a loose setup context that needs diagnosis before widening control further.

### Follow-up

Diagnose the accepted setup-repair run's slow-success windows before another live controller change. The next smallest useful experiment is to inspect `/ bro`'s active QWD segments around control points `0..4`, sampled route/blocked/dir-speed context, and emitted command profile to decide whether to tighten start radius/context, adjust projection, or abandon the SNG probe path.

## 2026-06-06 - QWD SNG Slow-Success Attribution

### Experiment

Diagnosed the setup-repaired SNG run `20260606T231007Z` without another KTX rerun. Added `scripts/diagnose_qwd_sng_slow_success.py` to split active mode-9 QWD commands by current control-point target, join those phases to MVD movement segments, and check whether the slow-success rejection came from controller projection, route/map context, or loose setup radius.

### Result

The slow-success failure is best attributed to loose setup activation plus a post-CP3 progression gap, not water and not missing QWD-style commands.

- `/ bro` was the slow-success candidate.
- The widened `320` qu start radius activated `/ bro` immediately at `t=0` from `281.954` qu away; the original `192` qu design radius would first have triggered at `31652` ms, when `/ bro` was `83.332` qu from CP0.
- `/ bro`'s CP0 active phase lasted `0-29677` ms with p50 speed `84.385` qu/s, low-speed ratio `0.526`, stationary ratio `0.383`, and blocked ratio `0.371`.
- `/ bro` still had strong command profile during those phases: side ratio `1.0`, jump ratio `1.0`, median horizontal command `600.0`.
- `/ bro` advanced to target index `4`, but during the CP4 phase the closest MVD approach to CP4 was `181.154` qu, outside the `96` qu point radius.
- Water and low route direction speed were not primary in the slow-success candidate phases: `water_path_ratio=0.0` and low-dir ratios near `0.0`.

### Evidence

Committed artifacts:

- `scripts/diagnose_qwd_sng_slow_success.py`
- `tests/test_diagnose_qwd_sng_slow_success.py`
- `experiments/qwd_route_probe/evidence/qwd-sng-slow-success-diagnosis-dm3.json`
- `experiments/qwd_route_probe/evidence/qwd-sng-slow-success-diagnosis-dm3.md`

Validation:

```powershell
python -m unittest tests.test_diagnose_qwd_sng_slow_success -v
python scripts\diagnose_qwd_sng_slow_success.py --bot-run-id 20260606T231007Z --stage qwd-sng-slow-success-diagnosis-dm3 --output-json experiments\qwd_route_probe\evidence\qwd-sng-slow-success-diagnosis-dm3.json --output-md experiments\qwd_route_probe\evidence\qwd-sng-slow-success-diagnosis-dm3.md
```

### Interpretation

This strengthens the evidence that KTX/Frogbots can accept QWD-derived control inside the real server loop, but it blocks the stronger claim that Frogbots learned SNG. The widened start radius made the probe active through a long slow/blocked setup window, and the bot still failed to enter the next target radius after CP3. The next useful step is setup/phase gating, not broader projection changes or expanding to all DM3 QWD moves.

### Confidence

High for the attribution from existing artifacts: it uses the same committed result, sampled QWD command state, route/water diagnostics, and MVD position samples.

Medium for the next repair shape because a tighter setup gate may need a live rerun to prove whether SNG traversal can pass movement guardrails.

### Follow-up

Tighten SNG activation around the real CP0 approach and add phase-level success gates before changing projection policy or trying other DM3 QWD moves.

## 2026-06-07 - QWD SNG Phase-Gate Tightening

### Experiment

Tightened `scripts/compare_qwd_sng_hybrid_probe.py` without rerunning KTX or changing movement behavior. The scorer now reports first active in-MVD QWD target distance plus active control-point phase summaries, then applies two stricter stop conditions before positive bounded evidence is possible:

- `tight_start_activation`
- `phase_target_progression`

### Result

Rescoring setup-repair run `20260606T231007Z` as `qwd-sng-phase-gate-tightening-dm3` rejects the run on the known setup/phase failures:

- `/ bro` first activated inside the MVD at `281.954` qu from CP0, outside the `192` qu design start radius.
- `/ bro` spent `9.908` seconds in the CP4 phase and never got closer than `183.876` qu to CP4 against the `96` qu point radius.
- The existing `waypoint_only_slow_success` rejection still applies.

### Evidence

Committed artifacts:

- `experiments/qwd_route_probe/evidence/qwd-sng-phase-gate-tightening-dm3.json`
- `experiments/qwd_route_probe/evidence/qwd-sng-phase-gate-tightening-dm3.md`

Validation:

```powershell
python -m py_compile scripts\compare_qwd_sng_hybrid_probe.py
python -m unittest tests.test_compare_qwd_sng_hybrid_probe -v
python scripts\compare_qwd_sng_hybrid_probe.py --bot-run-id 20260606T231007Z --stage qwd-sng-phase-gate-tightening-dm3 --output-json experiments\qwd_route_probe\evidence\qwd-sng-phase-gate-tightening-dm3.json --output-md experiments\qwd_route_probe\evidence\qwd-sng-phase-gate-tightening-dm3.md
```

### Interpretation

The stricter scorer closes the loophole where loose-radius geometry could look like progress. This keeps the Frogbots substrate hypothesis alive but blocks expansion to other DM3 QWD moves until a tight-start SNG rerun passes movement-quality and phase-level gates.

### Confidence

High for the new rejection evidence because it reuses the existing sampled QWD state and MVD-aligned command rows from the accepted setup-repair run.

### Follow-up

Rerun mode `9` with the original `192` qu start radius, unchanged projection, unchanged diagnostics, and the new phase-level gates. Only consider projection changes if the tight-start active phases still stall before the next target.

## 2026-06-07 - QWD SNG Tight-Start Rerun

### Experiment

Temporarily redeployed the existing mode-9 KTX moveprobe patch, ran one `dm3` SNG probe as `20260607T003837Z`, and restored the live KTX module afterward. The run restored the original `192` qu start radius while keeping the same `dm3_sng_shortcut.qwd` control points, `96` qu point radius, `forwardmove=320`, `sidemove=508`, command logging, route/water diagnostics, and cadence reporting.

### Result

This is major substrate progress, but it is still rejected movement evidence.

- The run produced a non-empty MVD, parser output, movement metrics, and `865` sampled command rows.
- QWD active samples: `274`.
- Max active seconds: `16.383`.
- Max advanced control points inside the parsed MVD window: `12`.
- `/ bro` advanced `11` control points inside MVD; `/ goldenboy` advanced `12`.
- Passing gates: QWD activation, in-window control-point advancement, MVD-overlap, diagnostic preservation, active side/jump command profile, and route-dirty success guardrail.
- Rejected gates: `phase_target_progression` and `waypoint_only_slow_success`.
- Inconclusive gate: `tight_start_activation`, because both bots' first active in-MVD sampled rows were already at CP2. The scorer correctly refuses to infer pre-advance CP0 start evidence from that sampled state.
- The regenerated diagnosis verdict is `qwd_sng_start_evidence_inconclusive`, preserving the unresolved pre-advance CP0 start-proof gate while still recording the rejected movement guardrails.
- `/ bro` remains the slow-success candidate with whole-run low-speed ratio `0.55`; the active-phase diagnosis shows many early phases with strong side/jump commands and no water/low-dir-speed route contamination, but later CP8/CP9 phases slow down.

### Evidence

Committed artifacts:

- `experiments/qwd_route_probe/evidence/qwd-sng-tight-start-rerun-dm3.json`
- `experiments/qwd_route_probe/evidence/qwd-sng-tight-start-rerun-dm3.md`
- `experiments/qwd_route_probe/evidence/qwd-sng-tight-start-rerun-diagnosis-dm3.json`
- `experiments/qwd_route_probe/evidence/qwd-sng-tight-start-rerun-diagnosis-dm3.md`
- `experiments/qwd_route_probe/evidence/qwd-sng-tight-start-rerun-slow-success-diagnosis-dm3.json`
- `experiments/qwd_route_probe/evidence/qwd-sng-tight-start-rerun-slow-success-diagnosis-dm3.md`

Validation:

```powershell
git apply --check C:\Users\benya\projects\quakeworld\komodobots\experiments\ktx_moveprobe\frogbot-moveprobe.patch
ssh servexeri 'set -euo pipefail; cd ~/nquakesv/build/ktx; git apply --check ~/komodobots-lab/qwd-sng-tight-start-rerun.patch; git apply ~/komodobots-lab/qwd-sng-tight-start-rerun.patch; cmake --build build -- -j2'
python scripts\run_bot_lab.py --map dm3 --duration 45 --bot-count 2 --bot-spacing 6 --moveprobe-mode 9 --moveprobe-forwardmove 320 --moveprobe-sidemove 508 --moveprobe-qwd-waypoints "<14 QWD control points>" --moveprobe-qwd-point-radius 96 --moveprobe-qwd-start-radius 192 --moveprobe-log-commands --moveprobe-log-interval 0.1
python scripts\compare_qwd_sng_hybrid_probe.py --bot-run-id 20260607T003837Z --stage qwd-sng-tight-start-rerun-dm3 --output-json experiments\qwd_route_probe\evidence\qwd-sng-tight-start-rerun-dm3.json --output-md experiments\qwd_route_probe\evidence\qwd-sng-tight-start-rerun-dm3.md
python scripts\diagnose_qwd_sng_probe.py --bot-run-id 20260607T003837Z --stage qwd-sng-tight-start-rerun-dm3 --result-json experiments\qwd_route_probe\evidence\qwd-sng-tight-start-rerun-dm3.json --output-json experiments\qwd_route_probe\evidence\qwd-sng-tight-start-rerun-diagnosis-dm3.json --output-md experiments\qwd_route_probe\evidence\qwd-sng-tight-start-rerun-diagnosis-dm3.md
python scripts\diagnose_qwd_sng_slow_success.py --bot-run-id 20260607T003837Z --stage qwd-sng-tight-start-rerun-dm3 --result-json experiments\qwd_route_probe\evidence\qwd-sng-tight-start-rerun-dm3.json --output-json experiments\qwd_route_probe\evidence\qwd-sng-tight-start-rerun-slow-success-diagnosis-dm3.json --output-md experiments\qwd_route_probe\evidence\qwd-sng-tight-start-rerun-slow-success-diagnosis-dm3.md
```

Follow-up diagnosis-hygiene validation:

```powershell
python -m py_compile scripts\diagnose_qwd_sng_probe.py
python -m unittest tests.test_diagnose_qwd_sng_probe -v
python scripts\diagnose_qwd_sng_probe.py --bot-run-id 20260607T003837Z --stage qwd-sng-tight-start-rerun-dm3 --result-json experiments\qwd_route_probe\evidence\qwd-sng-tight-start-rerun-dm3.json --output-json experiments\qwd_route_probe\evidence\qwd-sng-tight-start-rerun-diagnosis-dm3.json --output-md experiments\qwd_route_probe\evidence\qwd-sng-tight-start-rerun-diagnosis-dm3.md
```

Remote rollback checks:

```text
live symlink -> qwprogs-1.48-dev-08807d.so
live qwprogs hash -> 23d45401251ee802549c924f3179cf0cd76e0132dd7727778994c0464b8143e0
~/nquakesv/build/ktx: clean master...origin/master
localhost:28599 DOWN
```

### Interpretation

The KTX/Frogbots shell is still viable enough to keep probing: exact QWD-derived SNG control can now push bots through most of the SNG path under tight activation in the real server loop. But the result is not accepted learned movement. Sparse sampled command rows cannot prove pre-advance CP0 activation, phase target entries are still not proven, and `/ bro` remains too slow over the run. The corrected diagnosis keeps the next step focused on denser or event-level QWD start/advancement evidence before projection changes.

### Confidence

High that the live run, MVD parsing, command logging, and remote rollback succeeded.

Medium that the remaining failure is controller policy rather than instrumentation/scoring, because phase entry may be missed by `0.1` second command sampling and the current slow-success guardrail is still whole-run rather than active-window only.

### Follow-up

Keep the next step diagnostic. Capture denser or event-level QWD advancement/start evidence and score active-window movement quality before changing projection policy or expanding the method to other DM3 QWD moves.

## 2026-06-07 - QWD SNG MVD Crossing Diagnosis

### Experiment

Added `scripts/inspect_qwd_sng_mvd_crossings.py` and inspected the tight-start SNG run `20260607T003837Z` from MVD position samples only. The helper derives first CP0 start-radius entry, sequential point-radius control-point entries, and movement-window speed summaries between entries, then compares those physical crossings against the first sampled QWD command row.

No KTX rerun, route mutation, or controller-policy change was made.

### Result

The MVD proves physical route traversal through most of the SNG path, but it does not yet prove internal mode-9 activation timing.

- `/ bro` first entered CP0's `192` qu start radius at `1761` ms (`83.482` qu), then reached `11` sequential `96` qu point-radius control points.
- `/ goldenboy` first entered CP0's `192` qu start radius at `7432` ms (`85.522` qu), then reached `12` sequential `96` qu point-radius control points.
- Both bots' first sampled QWD command rows were already at CP2 with `advanced_control_points=2`.
- The nearest MVD samples at those first sampled QWD rows were far from CP0 and CP2, so the sampled command log still cannot prove pre-advance internal CP0 activation.
- Movement quality remains mixed: `/ bro` has slow transitions across CP7->CP8 and CP8->CP9; `/ goldenboy` has a slow transition across CP5->CP6.

### Evidence

Committed artifacts:

- `scripts/inspect_qwd_sng_mvd_crossings.py`
- `tests/test_inspect_qwd_sng_mvd_crossings.py`
- `experiments/qwd_route_probe/evidence/qwd-sng-tight-start-mvd-crossings-dm3.json`
- `experiments/qwd_route_probe/evidence/qwd-sng-tight-start-mvd-crossings-dm3.md`

Validation:

```powershell
python -m py_compile scripts\diagnose_qwd_sng_probe.py scripts\inspect_qwd_sng_mvd_crossings.py
python -m unittest tests.test_diagnose_qwd_sng_probe tests.test_inspect_qwd_sng_mvd_crossings -v
python scripts\diagnose_qwd_sng_probe.py --bot-run-id 20260607T003837Z --stage qwd-sng-tight-start-rerun-dm3 --result-json experiments\qwd_route_probe\evidence\qwd-sng-tight-start-rerun-dm3.json --output-json experiments\qwd_route_probe\evidence\qwd-sng-tight-start-rerun-diagnosis-dm3.json --output-md experiments\qwd_route_probe\evidence\qwd-sng-tight-start-rerun-diagnosis-dm3.md
python scripts\inspect_qwd_sng_mvd_crossings.py --bot-run-id 20260607T003837Z --stage qwd-sng-tight-start-mvd-crossings-dm3 --result-json experiments\qwd_route_probe\evidence\qwd-sng-tight-start-rerun-dm3.json --output-json experiments\qwd_route_probe\evidence\qwd-sng-tight-start-mvd-crossings-dm3.json --output-md experiments\qwd_route_probe\evidence\qwd-sng-tight-start-mvd-crossings-dm3.md
```

### Interpretation

This strengthens the Frogbots substrate hypothesis: under real KTX physics, the bots physically traversed the human-derived SNG control-point geometry with tight CP0 starts. It still blocks learned-SNG claims because internal activation/advance timing is not proven at event level and movement quality still fails the scorer guardrails.

The next smallest useful experiment is not a projection change. It is event-level QWD activation/advance logging or unsampled advancement rows, followed by active-window movement-quality scoring.

### Confidence

High for physical MVD control-point traversal because it uses dense `events.txt` position samples and the committed QWD control-point geometry.

Medium for internal mode-9 timing interpretation because sampled command rows and MVD positions currently disagree at the first active sampled row; that disagreement is exactly why event-level logging is the next target.

### Follow-up

Add event-level QWD activation/advance instrumentation to mode `9`, rerun the same SNG probe without changing projection policy, and rescore start proof plus active-window movement quality before trying other DM3 QWD moves.

## 2026-06-07 - QWD SNG Event Logging Instrumentation

### Experiment

Added event-level mode-9 QWD instrumentation before another live SNG rerun. The KTX moveprobe patch now emits unsampled `FBMOVEPROBE_QWD_EVENT` rows on QWD activation, control-point advancement, and completion edges when command logging is enabled. The lab runner parses those rows into separate `moveprobe-qwd-events.json` and `moveprobe-qwd-events.md` artifacts.

No live KTX server rerun, route mutation, projection-policy change, or learned-movement claim was made in this step.

### Result

The instrumentation is locally valid and ready for review:

- `activate` events record the first internal mode-9 CP0 activation edge with current distance/origin.
- `advance` events record the reached target index and the next target index without waiting for sampled `FBMOVEPROBE_CMD` rows.
- `complete` events record final target completion.
- Run summaries now expose both sampled command count and QWD event count.
- Parser tests cover the new event row format and summary schema.

### Evidence

Changed files:

- `experiments/ktx_moveprobe/frogbot-moveprobe.patch`
- `scripts/run_frobodm2_lab.py`
- `tests/test_extract_movement_metrics.py`
- `docs/02_SOURCE_MAP.md`
- `docs/06_DATA_AND_MVD_PIPELINE.md`
- `docs/07_FINDINGS_LOG.md`
- `docs/08_DECISION_LOG.md`
- `docs/09_ROADMAP.md`

Validation:

```powershell
git -C C:\Users\benya\projects\quakeworld\engine\ktx apply --check C:\Users\benya\projects\quakeworld\komodobots\experiments\ktx_moveprobe\frogbot-moveprobe.patch
python -m py_compile scripts\run_frobodm2_lab.py
python -m unittest tests.test_extract_movement_metrics -v
git diff --check
```

### Interpretation

This closes a measurement blind spot rather than a movement gap. The prior MVD crossing evidence proves physical tight-start SNG traversal, but sparse sampled command rows could not prove internal activation timing. Event rows should let the next live rerun distinguish "mode 9 internally activated/advanced cleanly" from "the MVD geometry and sampled command rows are still misaligned."

### Confidence

Medium-high for instrumentation correctness: the local KTX patch applies cleanly and parser/unit tests pass. Confidence remains medium for the live evidence outcome until the patched server is rebuilt and a reviewed rerun produces real `moveprobe-qwd-events.*` artifacts.

### Follow-up

After review, rerun the same `dm3_sng_shortcut.qwd` mode-9 probe with unchanged QWD waypoints, `192` qu start radius, `96` qu point radius, and unchanged projection/command profile. Then rescore start proof and active-window movement quality before changing projection policy or expanding to other DM3 QWD moves.

## 2026-06-07 - QWD SNG Event-Aware Scoring Prep

### Experiment

Updated `scripts/compare_qwd_sng_hybrid_probe.py` to consume optional `moveprobe-qwd-events.json` artifacts produced by the mode-9 event instrumentation. This was an offline scoring change only: no live KTX rerun, route mutation, projection-policy change, or learned-movement claim was made.

### Result

The scorer can now use event rows as the preferred proof source for first CP0 activation and inside-MVD advancement when sparse sampled command rows begin after internal advancement.

- Event rows contribute to `qwd_event_count`, `qwd_event_inside_mvd_count`, max advancement, active seconds, and first active start proof.
- A CP0 `activate` event inside the parsed MVD window can make `tight_start_activation` pass even if the first sampled active command row is already at CP2 or later.
- Runs without `moveprobe-qwd-events.json` retain the previous sampled-command behavior and still stay inconclusive if the start proof is unverifiable.
- The markdown report now displays event counts and the start-proof source per player.

### Evidence

Changed files:

- `scripts/compare_qwd_sng_hybrid_probe.py`
- `tests/test_compare_qwd_sng_hybrid_probe.py`
- `docs/02_SOURCE_MAP.md`
- `docs/06_DATA_AND_MVD_PIPELINE.md`
- `docs/07_FINDINGS_LOG.md`
- `docs/08_DECISION_LOG.md`
- `docs/09_ROADMAP.md`

Validation:

```powershell
python -m py_compile scripts\compare_qwd_sng_hybrid_probe.py
python -m unittest tests.test_compare_qwd_sng_hybrid_probe -v
python -m unittest discover -s tests -v
```

### Interpretation

This turns the event instrumentation into usable evidence for the next reviewed live rerun, but it does not itself improve Frogbot movement. Event rows prove internal mode-9 state transitions; movement quality still needs active-window speed/slow/stationary guardrails before expanding to other DM3 QWD moves.

### Confidence

Medium-high for the offline scorer behavior because the targeted regression test covers the exact sparse-sampling failure mode from the tight-start run.

### Follow-up

After review and human confirmation for the live server step, rerun the unchanged `dm3_sng_shortcut.qwd` mode-9 probe with event logging enabled and score it with the event-aware scorer before changing projection policy or trying other DM3 QWD moves.

---

## 2026-06-07

### Experiment

Closed-loop movement on `dm3_sng_to_rl`: can a Frogbot reproduce more of the human trick than open-loop replay, and does feedback help? Three KTX moveprobe variants, each snapped to the human frame-0 state and scored on the identical divergence trace (bot origin vs human origin at the same replay time index):

- **Mode 10 (open-loop replay):** emit the exact human usercmd each frame (no feedback). Baseline / control arm.
- **Mode 11 (closed-loop steering):** discard the usercmd; each frame re-aim from the bot's ACTUAL origin toward the human origin `lookahead` frames ahead, move forward + strafe (sign from the human's recorded sidemove), jump. `lookahead=4`.
- **Mode 12 (corrective replay):** emit the exact human usercmd, but once horizontal divergence exceeds a deadband, rotate view yaw toward the human origin by a clamped per-frame budget. `deadband=16 qu`, `yaw_max=3 deg/frame`.

Headline metric: the cursor at which horizontal divergence (divH) first exceeds 32 qu (the believable-corridor length), plus max divergence and whether the full 691-frame stream replayed. 1 bot, dm3, same `dm3_sng_to_rl.cmds` for all three.

### Result

| Arm | run_id | divH crosses 32 at | maxH (qu) | full stream |
|---|---|---|---|---|
| open-loop (m10) | 20260607T151125Z | cursor 255 | 1065.9 | 691/691 |
| steering (m11) | 20260607T164852Z | cursor 24 | 1348.5 | 600/691 (bot left route) |
| corrective (m12) | 20260607T170056Z | cursor 381 | 196.1 | 691/691 |

Mode 12 correction budget: per-frame yaw nudge held at the 3.0 deg clamp (`corr_max=3.00`), cumulative `corr_accum=1154` deg over the run (logged via `FBMOVEPROBE_REPLAY_CORR`).

### Evidence

- Artifacts: `artifacts/lab-runs/{20260607T151125Z,20260607T164852Z,20260607T170056Z}/` (moveprobe-commands.json, moveprobe-replay-events.json, replay-score.json, screen.log).
- Recorded demos (git + nQuake mirror): `tricks/dm3/dm3_sng_to_rl__{20260607T151125Z,164852Z,170056Z}.mvd`.
- KTX modes 10/11/12 in `src/bot_movement.c` (`BotApplyMoveProbeReplay` `replay_variant` 0/1/2), captured in `experiments/ktx_moveprobe/frogbot-moveprobe.patch`.
- Approach chosen by the `movement-approach-panel` judge panel (6 candidates, 2 judges each); hybrid/corrective ranked top, from-scratch scoped later.

### Interpretation

Open-loop reproduces a real lockstep prefix (a ring->YA trick jump, Frogbot brain off) to cursor 255, then diverges catastrophically at the strafe-jump because it has no feedback. Pure steering (m11) is dramatically WORSE — it collapses the corridor to cursor 24 — which proves the human's exact per-frame input is load-bearing in the prefix; a steering heuristic with generic strafe magnitudes cannot replace it. Corrective replay (m12) keeps that exact input AND adds a small clamped yaw correction: it extends the corridor through the strafe-jump (255->381, +50%) and bounds worst-case divergence 5.4x (1066->196 qu) while replaying the full stream. Because the correction is a yaw nudge (it never writes origin/velocity), the 196 qu is a genuine trajectory improvement, not metric masking. Net: closed-loop CORRECTION (not steering, not from-scratch) is the validated path to more-believable bunnyjump; the from-scratch movement brain stays shelved.

### Confidence

Medium-high. The three-arm A/B shares one snapped start, one demo, one scorer; the divH-cross ordering (24 << 255 < 381) and the 5.4x maxH reduction are large, consistent signals with a clean monotonic divergence ramp from a verified frame-0 snap. Single parameter setting per arm (not yet swept), single trick demo — robustness across (deadband, yaw_max) and a second dm3 trick is the open question.

### Follow-up

Sweep mode 12 (deadband {8,16,32} x yaw_max {2,3,5}) and replicate on a second dm3 trick to confirm the corridor extension generalizes; consider whether a higher yaw_max tracks further at acceptable believability (corr_max was saturated at the 3 deg clamp). Ocular-review the m12 demo for visible twitch.

---

## 2026-06-07 (bunnyhop acceleration on trick.bsp)

### Experiment

Attack acceleration directly (the foundational bunnyhop skill, and the bottleneck in the dm3 corrective run) on trick.bsp, a pure-acceleration map (open, no walls/water). New KTX moveprobe **mode 13**: a velocity-aware air-strafe accelerator (no replay) that rotates the wish-direction to the speed-optimal angle vs current velocity and jumps continuously. Metric: horizontal speed vs the human `trick5` benchmark (median 880, peak 1088 qu/s). 1 bot, dm3->trick.

### Result

| Arm | run_id | jumps/min | airborne | max hspeed |
|---|---|---|---|---|
| normal frogbot (mode 0) | 20260607T184752Z | 15 | 8% | 457 |
| mode 13, held jump | 20260607T185607Z | 0 | 0% | 158 (spins on ground) |
| mode 13, toggle + air-strafe | 20260607T190104Z | 80 | 96% | 476 |

Plus: a bot now spawns on trick.bsp at all, via a programmatically generated `trick.bot` (180 markers from trick5's trajectory) -- no in-game waypoint editor.

### Evidence

`experiments/ktx_moveprobe/evidence/bunnyhop-accel-trick-20260607.{json,md}`, `trick.bot`; demos `tricks/dm3/trick_accel__*.mvd`; KTX in `frogbot-moveprobe.patch`; `scripts/generate_bot_route.py`.

### Interpretation

Two findings. (1) Spawn: frogbots need `map_supported` (a loadable `bots/maps/<map>.bot`); it can be generated offline from a demo trajectory since moveprobe drives the bot, not the route graph. (2) The load-bearing mechanic: holding +jump every frame jumps once then holds, so the bot never bunnyhops (0 jumps/min, spins at 138). Toggling jump on ground contact + gating the air-strafe to airborne -> 80 jumps/min, 96% airborne, max 476. This held-jump defect is shared by the unconditional-jump modes 5-9/11 and likely explains the chronic weak bot air-speed (S7: 122 vs 433).

### Confidence

High for the mechanic (before/after is stark: 0% -> 96% airborne from the jump-toggle alone). The acceleration itself is partial -- max 476 but median 75 (not sustained), still far from human 880/1088.

### Follow-up

Numerator sweep via the retry/auto-tune harness + air-strafe refinement (the ~90 deg/frame circle bleeds speed; the true optimal angle is smaller, and alternating strafe likely sustains better). Re-test the unconditional-jump modes with the toggle.

---

## 2026-06-07 -- Optimal strafe angle: acceleration solved, ceiling is map geometry (trick.bsp)

### Finding

The mode-13 air-strafe used `acos((K/speed)^2)` -- a ~89.96 deg wish-angle where
`velocity . wishdir ~= 0`, so air accel added speed almost purely perpendicular and
barely grew |v| (crawled to max 476). Corrected to the **speed-optimal angle**
`acos(K/speed)`, K~=26 (hold `velocity . wishdir` just under the ~30 air cap). Result
(single bot, trick.bsp): p50 75->285 at 30s, **535 at 60s (96% airborne, 1% landing
loss), still climbing.**

**Verified the bot mouses correctly:** emitted view-yaw sweeps ~6 deg/frame, held ~85
deg ahead of velocity (textbook strafe); ground frames run straight. So it is real
air-strafe, not a static aim.

With the lab's 60s cap removed (patched `mvdsv-lab`, see decision log), a 200s run shows
the bot accelerating at the **exact optimal rate** (+3 qu/s per 0.1s frame) up to
~360-600, then a **single-frame -324 qu/s drop (wall hit)**, then re-accelerating --
every ~8s, no fly-off (vz > -290). So the ~600 ceiling is **trick.bsp geometry**: a
map-blind circle's radius grows as v^2 and slams into walls. Alternating S-strafe is
worse (max 412).

### Interpretation

Acceleration is **solved and physics-optimal**; the human 880/1088 is **navigation-bound**,
not acceleration-bound. A map-blind strafe caps at ~600 on trick.bsp regardless of tuning.
Reaching human speed needs map-aware navigation (use the open runway, turn at the ends) --
the routes/objectives pillar.

### Confidence

High. Acceleration rate matches theory frame-for-frame; the ceiling is unambiguously
single-frame wall hits, not strafe inefficiency or fly-off.

### Follow-up

Map-aware navigation on trick.bsp (runway back-and-forth) to convert optimal acceleration
into human-level absolute speed. Re-test legacy unconditional-jump modes with the toggle.
See `experiments/ktx_moveprobe/evidence/accel-optimal-angle-trick-20260607.md`.

## 2026-06-10 -- Terminal carve: FIRST LANDINGS; release fixed; speed-at-arm is the new wall (A5 round 2)

### Finding

The terminal-carve release (A5 #118 round 2, pre-registered in
`experiments/a5_distance_standstill/a5-distance-standstill.md` section 9) produced the
**first far-platform landings in the project's history** on the ztricks Distance gap:
9/81 configs landed 1/30 in the scored sweep (round 1: 0/4860), and the pre-registered
top-3 x 100-seed extension reached **9/100 best** -- one seed under the pre-committed
>=10/100 live bar, so **the off-ramp fires; no live phase this round**.

### Evidence

`carve-sweep-results.json.gz` (2430 attempts), `carve-extension-results.json`,
`carve-offramp-decomposition.json`. Funnel vs round 1: releases 1917/2430 (was 361/4860),
0 by timeout (was 85), 82% within 45 qu of the lip (was 125 total), release heading bent
to p50 -7.1 deg (wall-slide family was 0.0), jump bit ON the lip row (the silent walk-off
release is mechanically gone). Every landed attempt released at **453.0-459.7 qu/s**;
release vh p50 overall is 433.5. The 9 landing configs are exactly the
carve_deg 52 x carve_vh 450 cells; carve_d and tol changed nothing (the arm decides).

### Interpretation

The carve fixed the RELEASE sub-skill (bend + on-lip jump) but not release SPEED: the
herr rule fires after ~2 carve ticks, long before ground-build lifts 433 toward the
~453+ the ballistic arc needs. Landing is currently a speed-at-arm lottery: the orbit
passes the arm window at >=450 in ~34% of attempts, and ~26% of those land. The human's
475 lip speed sits comfortably above the same threshold.

### Confidence

High on the funnel numbers (full per-attempt records committed); the ballistic
WOULD-LAND estimator is now measured ~8x optimistic at the band edge -- trust LANDED.

### Follow-up

Round-3 candidate (pre-register before any scored run): a release SPEED FLOOR -- while
armed keep carving until vh >= release_vh AND the aim rule (grid sketch in ledger
section 10). Live-phase standing requirement (user directive 2026-06-10): **the moment
any of this runs on the server, every run must be visible in the bot lab**
(dashboard at 192.168.86.33:8095/botlab/; B5 #64 already auto-archives every lab MVD to
the servexeri SSD).


## 2026-06-11 -- LD-C3 Mockup pane wired (offline map/route browser, #97)

### Finding

The Mockup view pane (`lab/dashboard/src/MockupPane.tsx`) is implemented and
wired into the App shell.  All dependencies were already merged (LD-B1 view
shell, LD-C1 routes manifest, LD-C2 map meshes, LD-B3 map-scene module).

The pane provides:
- Map selector (dm3 / dm2 / frobodm2 / trick) using the committed maps.json
  AABB centers for per-map overview camera positioning.
- Route browser listing all 11 dm3 routes with human stats (mean speed, peak
  speed) from the komodobots.routes.v1 manifest; dm2/frobodm2/trick show
  "no censused routes yet" rather than hiding the list (honest empty state).
- Human reference polyline + gap markers (edge in route color, land in grey)
  + teleport entry markers (teal), built from census xyz coords via
  setFromQuake() to match the Live 3D pane's Quake coordinate convention.
- Multiple simultaneous route selections (distinct palette colors); deselect
  by clicking again; map switch resets selection.
- MockupSelection { map, route } context event emitted via onSelect callback on
  every map or selection change, consumed by App shell state; ready for LD-E1
  (#100) to wire to the KPI dock context store.

### Evidence

- `tsc --noEmit`: 0 errors (with MockupPane.tsx and App.tsx changes).
- `vite build`: succeeds, 2.66 s, 705 KB bundle (Three.js is the bulk; no
  change from pre-LD-C3 baseline -- three was already a dependency).
- `test_mockup_context.py`: 22 tests pass, covering schema contract,
  per-route field contract, critical census values (sng_to_rl final gap
  req=525.3, peak=534.7), and the MockupSelection context event shape.
- Full suite `python -m unittest discover -s tests -p "test_*.py"`: 476 OK.

### Deferred (deployment screenshots require servexeri)

The issue DoD calls for Playwright MCP screenshots from the deployed
:8095/botlab/ server.  That requires SSH access to servexeri which is out of
reach for this agent.  The deploy is a `deploy_dashboard.py --staged` +
`--cutover --confirm-live` two-step identical to all prior LD- PRs.  Deployment
screenshots are marked as deferred in the PR; the Coder or user should run them
after merge.

### Confidence

High on the TypeScript type-safety and data contract (tsc clean + 22 Python
tests).  Deployment validation pending.


## 2026-06-11 -- Dashboard ztricks try path is live, controller still fails quickly

### Finding

The Lab Dashboard control panel can start a dashboard-owned `ztricks` session and run
the Distance standstill preset from the visible browser. Final live pass:
`dash_20260611T221516Z` on port `28599`.

### Evidence

Clicking **try** returned `game ztricks_distance_standstill` in the panel and produced
one roster row (`s3 / bro`). The server log contained 18 nonzero `FBMOVEPROBE_CMD`
rows beginning at `origin=-3516.125,3712.000,-453.759` with `move=320,0,0`, after the
quoted spawn cvar had been applied. Earlier browser passes also verified `prewar`,
`axe only`, and the single-bot respawn control path.

### Interpretation

The dashboard command path is working; the bot is not refusing to try. The visible
"stands still" symptom after the initial burst is the current ztricks controller
failing the jump and settling, not a UI command failure. `removeall` also proved
unreliable with a 2 s short-lived shim, so botcmd shims now stay connected for 5 s.

### Follow-up

The next movement experiment should improve or instrument mode 23's post-launch failure
on ztricks Distance, using the dashboard **try/pause** loop as the required live
observation surface.


## 2026-06-12 -- KomodoLab user-story test pass after side-rail merge

### Finding

KomodoLab is usable for the core control/telemetry operator loop, but three
user-story blockers remain outside a small local fix: Live Game/QTV does not
render, records/KPI data is unavailable in the dashboard, and the bot roster can
retain stale rows after repeated ztricks resets.

### Evidence

Full evidence is recorded in
`lab/evidence/komodolab-user-story-test-run-2026-06-12.md`.

Baseline checks:

- `npm run build` in `lab/dashboard`: passed.
- `python -m unittest discover -s tests`: 957 tests passed.
- GitHub issue-template YAML parse: passed.
- `python scripts/ld_g2_golden_path.py --live`: all 6 checks passed.

Browser/live pass:

- Opened
  `http://127.0.0.1:5173/botlab/?views=live3d%2Cgame&ws=ws%3A%2F%2F127.0.0.1%3A8771`.
- Live 3D rendered the bot (`/ bro` / `ed 4`) and showed telemetry fields,
  including `hops: 1` and increasing air time after **try**.
- Control rail buttons succeeded for game mode, DMM, powerups, start/stop,
  prewar, weapon lock/unlock, and ztricks Distance standstill. The control audit
  logged the successful commands from `2026-06-12T07:21:36Z` through
  `2026-06-12T07:25:46Z`.
- Cvar console accepted `set samelevel 1` and rejected `quit`.
- Server screen hardcopy showed fresh mode-23 `FBMOVEPROBE_CMD` rows after
  **try**.

### Bugs Registered

- #157: Bot roster keeps stale rows after repeated ztricks tries.
- #158: Live Game pane stays retrying while telemetry and Live 3D work.
- #159: KPI records surface reports records.json 404 in BotLab.

### Interpretation

The user stories for controlling the game, starting/repeating a ztricks attempt,
and seeing telemetry are doable today. The story "watch the live in-game view"
is not complete until #158 is fixed. The story "review records/progress from the
KPI dock" is not complete until #159 is fixed. The story "know exactly which bot
exists" is only partially complete until #157 is fixed.

### Follow-up

Fix #157 first because stale roster rows can cause operator mistakes during the
otherwise-working ztricks loop. Then fix #158 so the primary watch-live story is
visually complete. Retest with the same test run artifact as the checklist.


## 2026-06-12 -- ztricks Distance route reaches mode 23 but emits zero movement

### Finding

The BotLab GUI and control bridge can route the `distance_standstill` try action
to live KTX, but the current ztricks mode-23 controller does not produce a real
movement attempt. The apparent KPI speed bump is not sufficient evidence of a
try; raw command rows show `move=0,0,0`.

### Evidence

Live session `dash_20260612T113124Z` on `ztricks`/port `28599`:

- Browser panel showed `route distance_standstill selected - bot is standing still until try`.
- Pressing **try** showed `trying distance_standstill`.
- Raw `screen.log`/telemetry rows showed mode 23 active for ed `3` and `5`, but final commands stayed zero:

```text
FBMOVEPROBE_CMD ... ed=5 name=/ bro mode=23 ... move=0,0,0 buttons=0 ... route=65,65,44,8,0,128,0,0.000 ... origin=-3429.873,3692.024,-487.969
FBMOVEPROBE_CMD ... ed=3 name= mode=23 ... move=0,0,0 buttons=0 ... route=1,1,0,-1,1048576,0,0,0.000 ... origin=-1168.000,1632.000,-574.969
```

Bridge/UI fixes made during the investigation:

- ztricks Distance remains a normal dashboard route, but its try action can use the bridge-backed `ztricks_distance_standstill` compatibility action.
- The bridge action now stamps route state onto per-slot moveprobe cvars before setting mode 23, so stale practice-idle suffixes no longer keep reused ed slots in mode 24.
- The live `kbot-telemetry` sidecar was redeployed/restarted with the updated bridge.

Verification:

- `npm run build` in `lab/dashboard`: passed.
- `python -m pytest tests\test_control_bridge.py tests\test_f3_control_drawer.py tests\test_build_routes_manifest.py`: 130 passed.

### Bug Registered

- #166: ztricks distance route enters mode 23 but emits zero movement.

### Interpretation

The "nothing happens" symptom is no longer a GUI button or bridge delivery bug.
It is a route/controller capability gap: mode 23 is active on ztricks Distance
but emits no final movement command in the live build. The A5 report already
warns that the deployed mode-23 law did not solve this jump in sim (`0/4860`
landings), so the next fix should either wire this route to a proven replay path
or implement the missing terminal-carve/release controller work.


## 2026-06-12 -- Browser validation of session, map, route, and add-bot flows

### Finding

The BotLab control drawer can now survive the operator flow of stopping a
session, starting a different map, selecting and changing routes, and adding
bots without leaving stale `s??` placeholder cards in the roster.

### Evidence

Browser target:
`http://127.0.0.1:5173/botlab/?views=game&ws=ws%3A%2F%2F127.0.0.1%3A8771`.

Validated in the Codex browser:

- Stopped active `ztricks` session `dash_20260612T113124Z`; control returned to
  `SESSION FREE` with no bot rows.
- Started `dm3` session `dash_20260612T114209Z`; selecting `sng_to_rl` for bot
  `s7` enabled per-bot route controls, then changing the same bot to `hilljump`
  preserved the same bot card and showed
  `route hilljump selected - bot is standing still until try`.
- Pressed **+ add** on `dm3`; roster changed from `s7`, `s5`, `s3` to `s7`,
  `s5`, `s3`, `s4` with no `??` placeholder.
- Stopped `dm3`, selected `ztricks` from the map dropdown, and started
  `ztricks` session `dash_20260612T114804Z`.
- Pressed **+ add** on `ztricks`; roster showed real bot cards `s5`, `s3`,
  `s7` with no `??` placeholder.
- Selected `distance_standstill` on the first ztricks bot; its **try** and
  **loop** buttons became enabled while unassigned bots stayed disabled.

Code fix:

- `session_start`/`session_stop` now clear stale frame-suppression state instead
  of suppressing newly reused ed slots.
- Live-frame and ASSIGN upserts prune unlabeled provisional rows once real bot
  rows exist, while preserving route-labeled placeholders such as the ztricks
  bridge route.

Verification:

- `npm run build` in `lab/dashboard`: passed.
- `python -m pytest tests\test_f3_control_drawer.py tests\test_build_routes_manifest.py tests\test_control_bridge.py`: 133 passed.

### Interpretation

The control-drawer operator story is now usable for session start/stop, map
change, route selection, route change, and add-bot roster reconciliation. The
known remaining issue is still #166: pressing **try** for `distance_standstill`
reaches mode 23 but the controller emits zero movement.


## 2026-06-12 -- ztricks Distance per-bot try emits movement again

### Finding

The zero-command symptom from `dash_20260612T113124Z` was a control-path problem,
not proof that mode 23 could no longer emit movement. ztricks Distance still had
a legacy route `game_command` override, so the per-bot **try** button was secretly
using the old global remove-all/add-one preset instead of configuring the
selected bot like every other route. The bridge also stuffed space-separated
`spawn_origin` cvar values without quotes on the generic per-bot `set_cvar`
path.

### Fix

- Removed `control.game_command` from the generated ztricks Distance route
  manifest; per-bot **try** now uses the route cvar sequence in
  `ControlDrawer.configureBotRoute`.
- Removed the UI-side `control?.game_command` shortcut so routes cannot bypass
  the selected-bot path.
- Added `format_set_cvar_command()` in the control bridge so validated values
  containing spaces are quoted before being stuffed into the Quake console.
- Redeployed `lab/server/control_bridge.py` to
  `servexeri:~/komodobots-lab/sidecar/control_bridge.py` and restarted the
  `kbot-telemetry` sidecar.

### Evidence

Browser retry against
`http://127.0.0.1:5173/botlab/?views=game&ws=ws%3A%2F%2F127.0.0.1%3A8771`:

- Confirmed stale takeover after sidecar restart.
- Started clean ztricks session `dash_20260612T120449Z` on port `28600`.
- Selected `distance_standstill` on bot `s5`; panel showed
  `route distance_standstill selected - bot is standing still until try`.
- Pressed the same row's **try**; panel showed `trying distance_standstill` and
  roster stayed `s5`, `s3` rather than removing/readding bots.
- Server log showed per-slot assignment and nonzero mode-23 commands:

```text
FBMOVEPROBE_ASSIGN ... ed=5 ... mode=23 mode_src=slot ... fixed_goal=8 goal_src=slot spawn_origin=-3516.125,3712,-453.125 spawn_src=slot
FBMOVEPROBE_CMD ... ed=5 ... mode=23 ... move=320,0,0 buttons=1 ... origin=-3516.125,3712.000,-453.125
```

Verification:

- `npm run build` in `lab/dashboard`: passed.
- `python -m pytest tests\test_control_bridge.py tests\test_build_routes_manifest.py tests\test_f3_control_drawer.py`: 134 passed.

### Interpretation

The specific "selected route + try does nothing" GUI/bridge failure is fixed and
retested. The controller still needs movement-quality work: mode 23 now launches
again from the A5 start, but this does not mean the ztricks Distance jump is
solved or landed.


## 2026-06-12 -- mvd_analyzer map entities imported for BotLab

### Finding

Upstream `mvd_analyzer` already has static map-entity JSON for the requested
maps and for `ztricks`; no local ztricks entity generation was needed. The
source ref used for this import is
`galfthan/mvd_analyzer` `upstream/main`
`dbfee83f457946c93e941c4a0b76efd25183d25e`.

Imported entity counts:

- `dm2`: 70
- `dm3`: 61
- `e1m2`: 117
- `phantombase`: 61
- `schloss`: 57
- `ztricks`: 35

### Change

- Added `lab/tools/import_map_entities.py` to copy the upstream
  `mvd-analytics/mapents/data/<map>.json` files into BotLab public data and
  write `komodobots.map_entities.v1` provenance/counts.
- Committed `lab/dashboard/public/data/map_entities/{dm2,dm3,e1m2,phantombase,schloss,ztricks,index}.json`.
- Extended `scripts/ld_g2_golden_path.py` so the offline dashboard harness
  validates the map-entity corpus, including required presence of `ztricks`.
- Added importer and harness tests.

### Evidence

- `python lab\tools\import_map_entities.py --source-repo C:\Users\benya\projects\quakeworld\tools\mvd_analyzer --ref upstream/main`: wrote six map files plus `index.json`.
- `python -m pytest tests\test_import_map_entities.py tests\test_ld_g2_golden_path.py`: 55 passed.

### Interpretation

BotLab now has a reusable static map context layer separate from routes and
meshes. `e1m2`, `phantombase`, and `schloss` have entity data available even
though they do not yet have committed BotLab meshes or censused routes.


## 2026-06-12 -- Mockup consumes ztricks map entities

### Finding

The imported map-entity corpus can already give useful route-authoring context
for ztricks Distance. The route starts within 32 qu of upstream
`tele-dst-1`, and the successful human landing point is nearest to upstream
`tele-src-3` within 200 qu. That is enough to display the route's surrounding
teleporter context directly in BotLab without inventing a separate ztricks
schema.

### Change

- Added `ztricks` to the Mockup map selector.
- Mockup now fetches `public/data/map_entities/<map>.json`, overlays static
  entities in the Three.js scene, and shows per-map entity counts.
- Selected-route detail now shows nearest static entities for route start,
  final edge, and landing.
- Null route metrics render as `n/a`; LiveMetricsPanel skips null human-speed
  anchors and null required-speed gaps instead of coercing them to zero.

### Evidence

- `python -m pytest tests\test_mockup_context.py tests\test_live_metrics_panel.py tests\test_import_map_entities.py tests\test_ld_g2_golden_path.py`: 142 passed.
- `npm run build` in `lab/dashboard`: passed, with the existing Vite chunk-size warning.
- Codex browser validation on
  `http://127.0.0.1:5173/botlab/?views=mockup`: selected `ztricks` and
  `distance_standstill`; route detail rendered `dur 2.12 s`, `mean 388 qu/s`,
  `peak 496 qu/s`, `req n/a hu 475`, `start tele-dst-1 teleportDst 27q`,
  `edge tele-dst-1 teleportDst 172q`, and `land tele-src-3 teleportSrc 180q`;
  entity summary rendered `35 total`, `spawn 1`, `teleportDst 8`,
  `teleportSrc 26`.
- Canvas screenshot crop pixel check passed: 480x500 canvas crop, 12,000
  sampled pixels, 860 unique sampled colors, 1,791 bright samples, nonblank =
  true.

### Interpretation

ztricks Distance is now inspectable in Mockup as a normal route with static
teleporter/landing context. This does not yet add a scoring zone or new
controller behavior; it makes the static context visible and contract-tested so
the next scoring step can consume the same data.


## 2026-06-12 -- ztricks route manifest promoted the successful getspeed.qwd attempt

### Finding

The human reference for ztricks Distance is present locally and already analyzed
by A5. It is `C:\nQuake\qw\matchinfo\demos\getspeed.qwd`, sha256
`dfb893a32d24b0aec5a5a94a94b16cee9cd42dcdd6602c6a093c5f21e9988307`: ten failed
Distance attempts followed by a successful 11th attempt.

A5's validated replay data identifies the successful route segment as rows
`1807..1969`, with lip row `1918`, landing row `1969`, lip speed `475.2`,
landing speed `495.5`, and launch heading `-11.7`. Both recorded and simulated
replays land the far platform.

### Change

- `lab/tools/build_routes_manifest.py` now derives `ztricks.json`
  `distance_standstill` from A5's committed `human-replay.json`,
  `alignment-meta.json`, and `getspeed-aligned.cmds`.
- The route manifest now carries the start-to-landing human polyline, duration
  `2.116`, active mean speed `388.4`, peak speed `495.5`, human edge speed
  `475.2`, and a `reference` block with attempt/row/heading/sha evidence.
- `required_speed` intentionally remains null because A5 showed speed alone is
  not a sufficient success gate for this jump; release heading/geometry is the
  decisive dimension.

### Evidence

- `python lab\tools\build_routes_manifest.py`: regenerated `ztricks.json` with
  one route and 28 polyline points.
- `python -m pytest tests\test_build_routes_manifest.py tests\test_mockup_context.py tests\test_live_metrics_panel.py tests\test_import_map_entities.py tests\test_ld_g2_golden_path.py`: 166 passed.
- Codex browser validation on
  `http://127.0.0.1:5173/botlab/?views=mockup`: selected `ztricks` and
  `distance_standstill`; the detail panel showed the successful-reference
  metrics (`dur 2.12 s`, `mean 388 qu/s`, `peak 496 qu/s`, `req n/a hu 475`)
  and current static context (`start tele-dst-1`, `edge tele-dst-1`,
  `land tele-src-3`). Canvas crop was nonblank.

### Interpretation

BotLab now has the perfect human ztricks Distance reference in the same route
manifest layer as the other routes. The next scoring/controller step should
compare bot attempts to the successful QWD segment's lip row, landing row,
speed, and launch heading rather than treating the jump as an abstract
standstill distance preset.


## 2026-06-12 -- live ztricks route attempts re-arm, but controller misses the landing

### Finding

The browser-to-bridge route flow can now assign and repeat the ztricks
`distance_standstill` route as a normal per-bot route, but the deployed mode-23
controller still does not complete the jump.

### Change

- `ControlDrawer.tsx` clears per-slot `spawn_origin`, waits one sampled frame,
  then restores the route spawn before flipping the bot into route mode. This
  gives KTX a real assignment edge for repeated tries of the same route.
- `control_bridge.py` now formats empty cvar values as `set name ""` and reports
  the exact stuffed command in control responses/audit details.

### Evidence

- `python -m pytest tests\test_control_bridge.py tests\test_f3_control_drawer.py`:
  113 passed.
- `npm run build` in `lab/dashboard`: passed, with the existing Vite chunk-size
  warning.
- Bridge redeployed to `servexeri` sidecar `kbot-telemetry`; fresh session
  `dash_20260612T135158Z` started on port `28599`.
- Browser selected `distance_standstill` for `s3` and pressed **try**. Server
  emitted slot-sourced `FBMOVEPROBE_ASSIGN` rows, then `113` mode-23 rows with
  `21` nonzero command rows. Closest configured spawn distance was about
  `10.5q`, closest lip distance about `94.3q`, and closest landing distance
  about `137.9q`; max x reached `-3156.651` versus human landing x `-3044.1`.
- Pressing **try** again on the same selected route emitted fresh clear/restore
  ASSIGN rows and nonzero movement again, proving the repeated-try standstill
  failure is no longer the active UI/bridge failure. The repeat still missed:
  closest landing distance was about `172.5q`.
- Created GitHub issue #167 for the remaining controller/route-reproduction
  failure.

### Interpretation

The next bottleneck is no longer "did the GUI make the bot try?" It is that
mode 23 is not reproducing the human ztricks release geometry/heading well
enough to land. The next useful experiment should compare the mode-23 command
and origin trace against A5's successful `getspeed.qwd` rows around the lip and
landing, not add more dashboard controls.


## 2026-06-12 -- live ztricks attempt reaches the lip with speed but wrong heading

### Finding

The live one-attempt loop is useful, but the deployed mode-23 controller is
missing the control primitive needed for the ztricks Distance jump. In a fresh
dashboard-owned `ztricks` session (`dash_20260612T142054Z`, port `28600`), the
bot reached the successful human lip neighborhood with enough speed, but its
travel heading was almost perpendicular to the required release line and the
jump bit did not fire there.

### Evidence

Baseline live retry on `/ bro` (`ed=3`) used the current dashboard route
settings: spawn snap `-3516.125 3712 -453.125`, mode `23`, fixed goal `8`,
`k_fb_moveprobe_s23_launch_vh 430`, `k_fb_moveprobe_s23_launch_angle 50`, and
`k_fb_moveprobe_s21_swing 8`.

- The server emitted `482` ed-3 mode-23 command rows from time `70.725` to
  `76.825`; `443` rows had nonzero command output and `3` rows carried the
  jump bit.
- Closest pass to the successful human release point was only `6.0q` away:
  `t=71.752`, origin `(-3354.980, 3775.733, -487.969)`, horizontal speed
  `457.1`, velocity heading `84.6 deg`, yaw `134.6`, buttons `1`.
- Human reference for the same release: origin about
  `(-3360.8, 3777.2, -487.969)`, speed `475.2`, launch heading `-11.7 deg`,
  jump bit on at the lip row.
- The first actual jump bit in the live retry happened later and in the wrong
  state: `t=74.684`, origin `(-3362.6, 3718.1, -487.969)`, speed `153.0`,
  heading `133.8 deg`.
- The closest observed approach to the human landing point remained `191.6q`
  away (`t=72.639`, origin `(-3225.2, 3698.1, -539.3)`).

One manual follow-up tried `k_fb_moveprobe_fixed_goal_s3 44`, the far marker on
the successful y-band in the generated `ztricks.bot`. That run emitted `548`
mode-23 rows from time `459.882` to `466.988`, but stayed at spawn with zero
movement and zero jump rows (`dir_speed=0.000`), so changing only the fixed
goal is not enough with the current generated graph/controller.

### Interpretation

This is not a raw-speed problem and not a "try button did nothing" problem. The
live controller can move, and it can even arrive near the lip with about the
right speed. It cannot synchronize the final mouse/yaw direction, strafe
wishdir, and jump timing into the human terminal carve. A5 round 2 already
showed the required missing idea in sim: terminal carve plus a release-speed
floor. The live side now confirms that the next useful change is a default-off
KTX control primitive for that terminal carve/release rule, exposed through the
route settings, followed by the same one-attempt live loop.


## 2026-06-12 -- ztricks speedjump formula v0 extracted

### Finding

The successful ztricks Distance attempt can be expressed as a concrete release
formula rather than a vague "go faster" instruction. The important window is a
15-command-row / `195 ms` terminal sweep ending at the lip.

### Evidence

`experiments/a5_distance_standstill/speedjump-formula.md` extracts attempt 11
from `getspeed-aligned.cmds` into a controller contract:

- terminal sweep starts around row `1904`: speed `441.4`, velocity heading
  `41.4 deg`, view yaw `39.1 deg`, `d_lip 91.4`.
- speed floor crosses around row `1908`: speed `450.8`, velocity heading
  `27.5 deg`, view yaw `23.8 deg`, `d_lip 71.9`.
- release happens at row `1918`: speed `475.2`, velocity heading `-11.3 deg`,
  view yaw `-19.0 deg`, yaw lead `-7.7 deg`, `d_lip 12.8`, jump bit on.
- landing happens at row `1969`: origin `(-3044.1, 3760.5, -488.0)`, speed
  `495.5`.

### Interpretation

The next KTX primitive should score release state first, not landing first:
`vh`, `d_lip`, velocity heading, target error, yaw lead, and jump bit must match
the formula before any landing claim is meaningful. The live attempt failure is
now explained precisely: it had location and exploratory speed, but not the
terminal heading/yaw/jump synchronization.


## 2026-06-12 -- ztricks terminal-carve primitive added to mode 23

### Finding

The ztricks Distance route can now ask mode 23 for the missing terminal
speedjump primitive without making trickjump a separate GUI concept. The
primitive is default-off: unset `k_fb_moveprobe_s23_launch_target_{x,y,z}` keeps
the existing mode-23 Frogbot route weave, while the ztricks route metadata sets
the target/lip/release cvars needed for the terminal right-carve.

### Evidence

- `experiments/ktx_moveprobe/frogbot-moveprobe-perslot.patch` now adds
  `zjump=` command telemetry:
  `phase,d_lip,vh,vel_yaw,target_yaw,target_err,yaw_lead,armed,release_rule`.
- `lab/tools/build_routes_manifest.py` regenerates `ztricks.json` with the
  terminal-carve cvars: landing target `(-3044.1, 3760.5, -488)`, `lip_x
  -3348`, release speed floors `470/453`, `carve_d 80`, `carve_angle 52`,
  `carve_side 1`, yaw-lead `-12..-4`, and target-error `-2..10`.
- `scripts/moveprobe_parse.py` and `scripts/run_frobodm2_lab.py` parse and
  summarize nested `zjump_state`, so the next live run can be judged on release
  state before landing.

Validation:

- `python -m unittest tests.test_extract_movement_metrics tests.test_build_routes_manifest tests.test_control_bridge tests.test_perslot_moveprobe_patch`
  -> `116` tests OK.
- `python -m unittest discover -s tests` -> `993` tests OK.
- `npm run build` in `lab/dashboard` -> passed; Vite still reports the existing
  large chunk warning.
- Temporary clean KTX worktree at base `08807da`: `git apply --check
  frogbot-moveprobe-perslot.patch` passed.
- Temporary patched KTX worktree at base `08807da`: `./build_cmake.sh
  linux-amd64` built `qwprogs.so` successfully.

### Interpretation

This does not prove the bot can land the ztricks jump. It gives the live loop a
proper attempt primitive and enough telemetry to tune attempt by attempt:
first make `zjump_state` match the human release formula, then score landing.


## 2026-06-12 -- live zjump primitive test exposes approach-speed blocker

### Finding

Two live `ztricks` harness runs proved the new `zjump=` telemetry works and
bounded the next blocker. The first build let the terminal-carve primitive own
the command too early; the corrected build waits for the speed floor before
taking over. After that fix, the bot still did not arm or release because the
mode-23 approach reached the human lip neighborhood far too slowly.

### Evidence

Deployment safety:

- Built from a temporary clean local KTX worktree at base `08807da`, applied
  `frogbot-moveprobe-perslot.patch`, compiled `linux-amd64`, and uploaded named
  modules to `servexeri:~/nquakesv/ktx/`.
- The active lab symlink was restored after each run to
  `qwprogs-mode24-20260612T101218Z.so`.
- Restore hash verified:
  `49a41cd17e5eec3aadf4b0bd1042a87214b7f8f50f65c8d7a617001ef5926418`.

Run `zjump_20260612T152517Z` used the first zjump build
`qwprogs-zjump-20260612T152431Z.so`:

- `1005` command rows parsed; demo archived with SHA-256
  `9dbca706e48570c551ecc19fae7fcf52b53982d5fe61046a2fcd67ce5e8cd17f`.
- `zjump.phase` spent `904` rows at `1`, but `armed_rows=0` and
  `release_rows=0`.
- The primitive took over at low speed and starved the approach: max logged
  zjump speed was only `272.7 qu/s`; closest pass to the human release point was
  `74.5q` away at `190.0 qu/s`.

Fix applied:

- Changed mode 23 so `phase=1` still logs the configured terminal zone, but the
  command override only returns early when `armed=1` (`vh >=
  k_fb_moveprobe_s23_release_vh_min`).
- Re-generated patch headers and compile-verified the corrected patch in a
  temporary KTX worktree.

Run `zjump_fixed_20260612T152858Z` used corrected build
`qwprogs-zjump-fixed-20260612T152818Z.so`:

- `1007` command rows parsed; demo archived with SHA-256
  `1022b66b7e4153813c9dae1c170e85370bb3fc3752ed94aba7f5d34902657131`.
- Movement improved versus the first run: average `85.5 qu/s`, max MVD segment
  speed `423.3 qu/s`, p95 `300.3 qu/s`.
- `zjump.phase` was `1` for only `14` rows, confirming the primitive no longer
  monopolized the approach; still `armed_rows=0` and `release_rows=0`.
- Closest pass to the human release point was `26.4q` away at only `228.0
  qu/s`, with velocity yaw `335.3 deg` (equivalent to `-24.7 deg`) and target
  error `26.0 deg`.
- Closest pass to the human landing point was still `141.8q` away.

### Interpretation

The code path and telemetry are usable, but the ztricks route/controller is not
entering the terminal runway with enough speed to use the release primitive. Do
not lower the accepted release formula and call that success. The next smallest
experiment is an approach-speed probe: preserve the speed-floor-gated zjump
release, then tune the approach before the lip (start/launch route state,
`launch_vh`, launch angle, and/or a pre-terminal acceleration segment) until
`zjump` can reach `armed=1`.


## 2026-06-12 -- ztricks batch harness replaces one-attempt manual loop

### Finding

The live ztricks tuning loop can now run multiple clean attempts inside one
temporary server/MVD session. This is materially faster than restarting and
documenting one jump at a time, and it produces one scored row per attempt.

### Change

- Added `scripts/run_ztricks_batch.py`: starts one temporary `ztricks` lab
  server, keeps a passive client connected, cycles `removeall` / cvar setup /
  spawn-snap / one-bot attempt rows, then runs the standard artifact pipeline.
- Added `scripts/score_ztricks_batch.py`: segments `moveprobe-commands.json`
  into named-bot attempts and scores each against the successful `getspeed.qwd`
  release formula (`vh`, lip distance, velocity yaw, target error, yaw lead,
  release rule, landing distance).
- Documented the harness in `docs/05_HEADLESS_TEST_ENV.md`,
  `docs/02_SOURCE_MAP.md`, and `experiments/ktx_moveprobe/README.md`.

### Evidence

Validation:

```text
python -m py_compile scripts\score_ztricks_batch.py scripts\run_ztricks_batch.py scripts\run_frobodm2_lab.py
python -m unittest tests.test_score_ztricks_batch tests.test_extract_movement_metrics -v
```

Result: `21` tests passed. The new scorer tests cover time-gap splitting,
spawn-snap splitting, nameless-row exclusion, release-formula scoring, and
Markdown output.

Live batch:

- Temporarily switched `servexeri:~/nquakesv/ktx/qwprogs.so` to
  `qwprogs-zjump-fixed-20260612T152818Z.so` for a new lab process only.
- Ran:

```text
python scripts\run_ztricks_batch.py --attempts 3 --attempt-seconds 6 --port 28599 --strict-port
```

- Run ID: `zbatch_20260612T160053Z`.
- Artifacts:
  `artifacts/lab-runs/zbatch_20260612T160053Z/`.
- Demo archived to
  `/mnt/usb-ssd/non-games/lab/Komodobots/ztricks/zbatch_20260612T160053Z.mvd`,
  SHA-256 `5de82275e8e0b6ca43ad5349bb9d5160359b1ddc78a51ee0d0f7d04bc383a631`.
- Parser exits: JSON `0`, Markdown `0`, events `1` with the known
  `qw-analyze: end of demo`.
- `moveprobe-commands.json`: `4595` commands parsed.
- Rescored after excluding unnamed empty-slot rows:
  `3` real named-bot attempts.

Best attempt was attempt `2` (`launch_vh=430`, `launch_angle=50`,
`swing=14`):

- max zjump speed `183.5 qu/s`.
- closest release point `79.7q` away at `133.3 qu/s`.
- closest landing point `332.0q` away.
- `armed_rows=0`, `release_rows=0`.
- classification: `approach_speed_below_release_floor`.

After the run, restored the production symlink:

```text
/home/xerial/nquakesv/ktx/qwprogs-mode24-20260612T101218Z.so
49a41cd17e5eec3aadf4b0bd1042a87214b7f8f50f65c8d7a617001ef5926418
localhost:28599 DOWN
```

### Interpretation

The efficient batch mechanism works, and the scorer now produces the row shape
needed for attempt-to-attempt tuning. The controller did not improve: all three
attempts stayed far below the `453 qu/s` release floor, so the next useful work
is still approach-speed generation before the lip, not release-threshold
relaxation or GUI changes.


## 2026-06-12 -- ztricks scoring now interpolates between datapoints

### Finding

Nexus pointed out that discrete timestep data should be interpolated between
datapoints. Applying that to ztricks changes both how we score live attempts and
how the controller should eventually consume the human reference. Nearest-row
scoring is too coarse for a 13 ms command stream when the decisive terminal
window is about 195 ms.

### Change

- Added `scripts/ztricks_reference_trace.py` and
  `scripts/build_ztricks_reference_trace.py`.
- Generated
  `experiments/a5_distance_standstill/ztricks-reference-trace.json/md` from
  the successful `getspeed.qwd` attempt.
- Updated `scripts/score_ztricks_batch.py`:
  - release and landing estimates now project onto adjacent bot-sample
    segments instead of choosing only the nearest sampled row.
  - the physical lip event now uses a piecewise-linear crossing at `x=-3348`.
  - reports include interpolation metadata and can take an explicit
    `--reference-trace`.
- Added tests for angle unwrapping, local quadratic interpolation, interpolated
  physical-lip detection, and bot-side release/lip projection.

### Evidence

Reference trace generation:

```text
python scripts\build_ztricks_reference_trace.py
```

Key generated reference events:

- `release_jump`: row `1918`, `t=1.441`, origin
  `(-3360.8, 3777.2, -488.0)`, `vh=475.2`, velocity yaw `-11.3`,
  view yaw `-19.0`, yaw lead `-7.7`, buttons `2`.
- `physical_lip_x_crossing`: interpolated between rows `1920..1921`,
  `t=1.468`, `x=-3348.0`, `vh=475.2`.
- `landing`: row `1969`, `t=2.103`, origin
  `(-3044.1, 3760.5, -488.0)`, `vh=495.5`.
- Controller guidance curve: local quadratic Lagrange samples every `0.01s`
  from terminal sweep start to physical lip crossing, with angles unwrapped
  before interpolation.

Validation:

```text
python -m unittest tests.test_ztricks_reference_trace tests.test_score_ztricks_batch tests.test_extract_movement_metrics -v
python -m py_compile scripts\ztricks_reference_trace.py scripts\build_ztricks_reference_trace.py scripts\score_ztricks_batch.py scripts\run_ztricks_batch.py
```

Result: `26` focused/adjacent interpolation, scorer, and moveprobe parsing
tests passed.

Rescoring live batch `zbatch_20260612T160053Z` still yields the same controller
verdict, now with interpolated event semantics:

- `3` attempts scored.
- best attempt still attempt `2`.
- release projection: `79.7q` away at `133.3 qu/s`.
- physical lip crossing estimate: `t=29.804s` at `120.4 qu/s`.
- closest landing projection: `332.0q` away at `70.8 qu/s`.
- `armed_rows=0`, `release_rows=0`, classification
  `approach_speed_below_release_floor`.

### Interpretation

Nexus's interpolation point is now part of the toolchain. Evidence events stay
conservative and non-overshooting (linear/projection), while the reference
trace also exposes a smooth local-quadratic controller curve for the mouse/yaw
sweep. The result does not make the current controller better; it makes the
diagnosis sharper. The next controller experiment should chase the
interpolated/quadratic terminal yaw and velocity-heading curve, while still
using release-state gates before claiming a jump attempt is meaningful.


## 2026-06-12 -- ztricks reference-curve live retry fixes no-movement, not release

### Finding

The live "bots just jump in their spot" failure was real, and is now separated
from the harder ztricks problem. Mode 23 can move the bot again from the A5
practice state, but the current controller still does not create a valid
Distance release: the bot crosses the lip under the `453 qu/s` arm floor and
often on the wrong ground/air cadence.

### Change

- Added optional `k_fb_moveprobe_spawn_velocity` so ztricks attempts can start
  from the first grounded human reference state with its teleport-exit momentum
  (`-3434.375 3686.875 -488`, velocity `259 -172 0`) instead of a zero-velocity
  teleport deposit.
- Added a default-off mode-23 ztricks human-reference terminal curve using the
  successful attempt's local quadratic yaw samples. The route/dashboard/batch
  presets enable it for ztricks Distance with a terminal-lane entry target
  `(-3439.375, 3758.125)` and a tighter y corridor centered on `3768.5` with
  tolerance `24`.
- Fixed the silent-marker case: if Frogbot navigation gives no horizontal route
  vector for ztricks, mode 23 now falls back to the terminal-lane entry before
  chasing the far landing target.
- Fixed the scorer speed helper so phase-0 `zjump` rows with zero zjump speed
  fall back to actual water/velocity speed instead of hiding movement as `0`.
- Tightened the unarmed reference-curve jump: it may only press the "try
  anyway" jump inside the release-lip window, not at the start of the terminal
  lane.

### Evidence

Validation:

```text
python -m unittest tests.test_perslot_moveprobe_patch tests.test_build_routes_manifest tests.test_control_bridge tests.test_score_ztricks_batch -v
python -m py_compile scripts\run_ztricks_batch.py scripts\score_ztricks_batch.py scripts\build_ztricks_reference_trace.py lab\tools\build_routes_manifest.py lab\server\control_bridge.py
```

Result: `108` focused tests passed; Python compile passed.

Remote KTX build/deploy safety:

- Built temporary modules from clean KTX commit `08807da` in disposable
  worktrees, without touching the dirty `~/nquakesv/build/ktx` checkout.
- After each live run, restored
  `/home/xerial/nquakesv/ktx/qwprogs-mode24-20260612T101218Z.so`, SHA-256
  `49a41cd17e5eec3aadf4b0bd1042a87214b7f8f50f65c8d7a617001ef5926418`, and
  verified `localhost:28599 DOWN`.

Live sequence:

- `qwprogs-zcurve-20260612T184820Z.so`
  (`a1b2466529b7b5a210f48238d1b845ac79ae12c241648a8fb912883fc12c50b5`) /
  `zbatch_20260612T164913Z`: reference curve engaged too late/wrong-lane;
  best max zjump speed about `134.5 qu/s`, no arm/release. This matched the
  user's live observation that the bot mostly jumped in place.
- `qwprogs-zcurve2-20260612T185630Z.so`
  (`5a76b1c5e466f681a09ba51b8fdd9ed769f2bb03ae56bea2a128d158e98e59ba`) /
  `zbatch_20260612T165711Z`: spawn velocity was applied, but the Frogbot marker
  route was silent at the practice point; raw rows showed `move=0,0,0`.
- `qwprogs-zcurve3-20260612T185950Z.so`
  (`a60b7fb7989380ece38801c4ee7222f7133181f00654f9d085e8b20d8162c69b`) /
  `zbatch_20260612T170030Z`: real movement returned. Movement metrics reported
  max speeds `483.2` and `508.1 qu/s`, but terminal rows were in the wrong lane
  and no arm/release happened.
- `qwprogs-zcurve4-20260612T190756Z.so`
  (`0afc421095a8c964f986fe6e336d8b1c10586749e49a028018ee24bee8a258d8`) /
  `zbatch_20260612T170840Z`: terminal-lane fallback worked, but the unarmed
  reference curve spent a jump too early around `60-70q` before the lip. Best
  scored segment maxed at `406.6 qu/s`; `armed/release = 0/0`.
- `qwprogs-zcurve5-20260612T171142Z.so`
  (`bc95454f69dc38d730ecba7efa9b7f226bd88682e79d27f2d1460f40a495763b`) /
  `zbatch_20260612T171211Z`: early terminal-curve jump was removed. Best scored
  segment maxed at `401.3 qu/s`; movement metrics saw player max speeds
  `424.9` and `423.4 qu/s`; `armed/release = 0/0`.

Raw `zbatch_20260612T171211Z` command rows show the current failure mode:

- ordinary approach bunnyhop rows still occur around `d_lip ~= 80q`;
- terminal rows reach the human y corridor, but at about `322-324 qu/s`;
- the bot crosses the lip under the arm floor and not on a valid grounded
  release cadence.

### Interpretation

This fixes the "no real movement" bug, but not the ztricks jump. The missing
dimension is now approach-hop timing/starting geometry, not only the terminal
mouse curve: the controller must arrive at the ledge on a useful ground frame
with at least `453 qu/s`, then spend the jump in the release window. The next
smallest experiment should tune start position and/or approach-hop cadence
before changing the terminal formula again.


## 2026-06-12 -- ztricks spawn-floor speedjump route added

### Finding

The live Distance loop is too hard as the first calibration target. The same
speedjump controller now has a safe ztricks route that removes ledge/trap
success from the equation: start at the real deathmatch spawn, turn 90 degrees
left from the BSP spawn angle, run the terminal speedjump/reference-curve law on
flat ground, and judge the attempt by horizontal speed gain.

### Change

- Added `spawn_left_speedjump` to `lab/dashboard/public/data/routes/ztricks.json`
  via `lab/tools/build_routes_manifest.py`.
- The route uses spawn origin `-1168 1632 -496`, zero spawn velocity, yaw `45`,
  synthetic lip `[-920.5, 1879.5, -496.0]`, and target
  `[-796.1, 2003.9, -496.0]`.
- Added default-off KTX patch support for
  `k_fb_moveprobe_s23_refcurve_yaw_offset`, so the human reference curve can be
  rotated onto the spawn-floor lane without changing Distance behavior.
- Updated the dashboard control drawer so route assignment clears and reapplies
  per-slot `spawn_velocity`; this prevents the A5 Distance route's seeded
  velocity from leaking into standstill routes.

### Evidence

Validation in this change: route manifest rebuild and focused unit tests for
the manifest, mockup data contract, drawer route-cvar assignment, and KTX patch
static contract.

### Interpretation

This does not claim the bot can execute the full multi-hop stop/turn-back drill
yet. It creates the smallest live calibration step that answers the user's
actual question: does the same speedjump/mouse-curve law increase speed on safe
ground when ledges and traps are removed?


## 2026-06-12 -- spawn-floor ztricks route reaches human-level speed

### Finding

The safe-floor `spawn_left_speedjump` route can now reach human-level horizontal
speed. This is the first positive live result for the reduced ztricks problem:
remove ledge/trap completion, keep the same speedjump/Nexus reference-curve
primitive, and score actual speed gain.

### Change

- Added optional KTX cvar `k_fb_moveprobe_s23_lip_y`.
- When `lip_y` is non-zero, mode 23 computes `d_lip` as projected progress
  along the configured lip-to-target lane, instead of raw `lip_x - origin.x`.
  This lets the local-quadratic human reference curve keep its timing on the
  diagonal `spawn_left_speedjump` lane.
- The Distance route and legacy bridge preset now explicitly set `lip_y=0` and
  `k_fb_moveprobe_s23_refcurve_yaw_offset=0` so route switching cannot leak
  the safe-floor lane settings into Distance.
- `scripts/run_ztricks_batch.py` now takes `--route` and reads route control
  metadata from `lab/dashboard/public/data/routes/ztricks.json`.
- `scripts/score_ztricks_batch.py` now scores by route profile:
  `distance_standstill` keeps release/landing formula scoring, while
  `spawn_left_speedjump` reports start-to-peak horizontal speed gain against
  the `495.5 qu/s` human target.

### Evidence

Local validation:

```text
python lab\tools\build_routes_manifest.py
python -m py_compile scripts\score_ztricks_batch.py scripts\run_ztricks_batch.py lab\tools\build_routes_manifest.py lab\server\control_bridge.py
python -m unittest tests.test_score_ztricks_batch tests.test_build_routes_manifest tests.test_perslot_moveprobe_patch tests.test_control_bridge tests.test_f3_control_drawer -v
git apply --check experiments/ktx_moveprobe/frogbot-moveprobe-perslot.patch against clean KTX 08807da
```

Result: `163` focused tests passed; KTX patch apply check passed.

Remote KTX build:

- Built clean remote worktree at `08807da` with the updated
  `frogbot-moveprobe-perslot.patch`.
- Deployed as
  `~/nquakesv/ktx/qwprogs-zspawn-20260612T180834Z.so`, SHA-256
  `778f3dcfb549ce271d76d950534d8f598c971696ff0a7bcd965ecea1f8427672`.

Live batch:

```text
python scripts\run_ztricks_batch.py --route spawn_left_speedjump --attempts 6 --attempt-seconds 6 --launch-vh 430,380,340 --launch-angle 50,45 --swing 8,14 --port 28599
```

Run `zbatch_20260612T180901Z`, archived MVD SHA-256
`c4ba8ab8aa47ecdbca1359b360cf664b763da18a070fd3ca4d1080fdfc8d9dff`.

Speed-gain score:

| attempt | max vh | pct human | class |
|---:|---:|---:|---|
| 1 | 498.6 | 100.6% | `human_level_or_better` |
| 2 | 503.0 | 101.5% | `human_level_or_better` |
| 3 | 477.8 | 96.4% | `speed_gain_below_human` |
| 4 | 506.2 | 102.2% | `human_level_or_better` |
| 5 | 495.7 | 100.0% | `human_level_or_better` |
| 6 | 500.4 | 101.0% | `human_level_or_better` |

### Interpretation

This proves the reduced speedjump problem can now reach human-level speed on
flat ground. It does not prove the original Distance jump is solved, because
Distance still adds the hard release-cadence and landing geometry gates. The
next smallest experiment is to use the fastest safe-floor attempts to tune
approach timing and then move the synthetic lip/route start closer to the real
Distance release problem while preserving this speed-gain evidence.

### Reproduction check

Two follow-up batches tested whether the result repeats.

Same six-attempt sweep:

```text
python scripts\run_ztricks_batch.py --route spawn_left_speedjump --attempts 6 --attempt-seconds 6 --launch-vh 430,380,340 --launch-angle 50,45 --swing 8,14 --port 28599
```

Run `zbatch_20260612T182309Z`, archived MVD SHA-256
`de711aab8b744f0f5bcfc46e4cbe414b92b60ecd4bfa3c945ca32d5202de6697`:
`6/6` attempts reached human-level speed, best `515.6 qu/s`.

Fixed default route params:

```text
python scripts\run_ztricks_batch.py --route spawn_left_speedjump --attempts 8 --attempt-seconds 6 --launch-vh 430 --launch-angle 50 --swing 8 --port 28599
```

Run `zbatch_20260612T182505Z`, archived MVD SHA-256
`dfb49f230e706665b4e7268ab7b4f128af5769e8e136a18c78ff475f84070ca8`:
`7/8` attempts reached human-level speed, best `530.3 qu/s`; the only strict
miss was `494.9 qu/s`, `0.6 qu/s` below the `495.5 qu/s` target.

Across the three live safe-floor batches so far, the strict hit rate is
`18/20`. Treat this as reproducible for the reduced speed-gain route, with a
small stochastic threshold-margin failure rate still present.


## 2026-06-12 -- getspeedstill QWD room/POV visualization

### Experiment

Rendered `C:\nQuake\qw\matchinfo\demos\getspeedstill.qwd` with the same
QWD extraction and simple room/first-person POV visualization used for
`mousemovement.qwd`.

### Result

The QWD bridge recovered a usable exact-command plus anchored self-trajectory
stream: `2106` command frames, `2069` paired command/state frames, `0.982`
coverage, and `112` downsampled waypoints.  The generated MP4 shows the path,
extracted first-person view direction, yaw/pitch trace, command pulses, and
speed pulses.

The standalone `qw-analyze-v20` events mode still does not produce useful rows
for this QWD (`qw-analyze: unexpected EOF`), so the controller evidence should
continue to come from `tools/qwd_usercmd/qwd_usercmd.py` plus
`scripts/probe_qwd_route_applicability.py`.

### Evidence

Artifacts:

- `artifacts/qwd-getspeedstill/getspeedstill_room_pov.mp4`
- `artifacts/qwd-getspeedstill/getspeedstill_room_pov_frame.png`
- `artifacts/qwd-getspeedstill/getspeedstill_view.html`
- `artifacts/qwd-getspeedstill/getspeedstill_visual_summary.json`
- `artifacts/qwd-getspeedstill/trajectory-probe.md`
- `artifacts/qwd-getspeedstill/replay-build.json`

Key visualization summary values:

- duration `26.857s`, frames `2069`, rendered frames `1004`
- speed avg `237.4 qu/s`, p50 `319.8`, p95 `452.3`, max `458.4`
- forward nonzero `49.3%`, side nonzero `48.8%`, jump button `8.2%`
- yaw total absolute travel `2952.6 deg`, yaw reversals `64`,
  p95 absolute yaw rate `364.6 deg/s`

### Interpretation

`getspeedstill.qwd` is usable as human-input/trajectory evidence for
speedjump-style controller work, and it looks more oscillatory than
`mousemovement.qwd` in yaw reversal count.  It is still a visual and data
reference, not proof that a Frogbot can replay the movement without live-server
controller validation.


## 2026-06-12 -- live safe-floor speedjump beats getspeedstill speed

### Experiment

Opened BotLab live game/telemetry against lab port `28599` and ran a short
live `ztricks` batch on the `spawn_left_speedjump` route while the browser was
visible.  The controller used the reduced safe-floor speedjump pattern:
real ztricks spawn, turn left onto the flat lane, mode-23 reference yaw curve,
and forward+side movement (`move=320,320`) with the proven fixed parameters
`launch_vh=430`, `launch_angle=50`, `swing=8`.

This was not a frame-for-frame replay of `getspeedstill.qwd`; it was the same
movement family/control law applied live, with the speed target set above the
`getspeedstill.qwd` visualized max of `458.4 qu/s`.

### Result

All four live attempts exceeded both the `getspeedstill.qwd` visualized max
speed and the existing safe-floor human target of `495.5 qu/s`.

| attempt | command-score max vh | movement-metrics max vh | classification |
|---:|---:|---:|---|
| 1 | `496.0` | `518.8` | `human_level_or_better` |
| 2 | `503.4` | `528.3` | `human_level_or_better` |
| 3 | `498.7` | `514.4` | `human_level_or_better` |
| 4 | `496.9` | `521.0` | `human_level_or_better` |

### Evidence

- Run ID: `zlive_20260612T211350Z`
- Local artifacts:
  `artifacts/lab-runs/zlive_20260612T211350Z/`
- Local demo:
  `artifacts/lab-runs/zlive_20260612T211350Z/demo.mvd`
- Remote demo:
  `/home/xerial/nquakesv/ktx/demos/komodobots_ztricks_zlive_20260612t211350z.mvd`
- Archive:
  `/mnt/usb-ssd/non-games/lab/Komodobots/ztricks/zlive_20260612T211350Z.mvd`
- Demo SHA-256:
  `762242a91506e2b4152db93356ec0516b53984a7a7aebca4b9604ebbce3c5792`
- Command rows parsed: `9846`
- Parser exits: JSON `0`, Markdown `0`, events `1` with known
  `qw-analyze: end of demo`
- Cleanup: lab port `28599` verified down after the run.

### Interpretation

The reduced safe-floor speedjump is live-server reproducible at speeds above
the `getspeedstill.qwd` reference visualization.  The remaining gap is not raw
speed generation on flat ground; it is turning this into a controller that
uses `getspeedstill.qwd`'s exact yaw/strafe timing as data and then transfers
that timing back to harder geometry without losing direction, release cadence,
or landing control.


## 2026-06-12 -- getspeedstill vs live zspawn mouse comparison

### Experiment

Built a side-by-side simple-room visualization comparing
`getspeedstill.qwd` against the fastest live safe-floor attempt from
`zlive_20260612T211350Z` (attempt 2, ed `6`, `30.689s..39.047s`).
The visualization normalizes playback progress so the full human demo and the
shorter live attempt can be inspected together.

### Result

The live attempt is faster, but the mouse/control shape is not human-like.

| metric | getspeedstill.qwd | live attempt 2 |
|---|---:|---:|
| max speed | `458.4 qu/s` | `503.4 qu/s` |
| p95 speed | `452.3 qu/s` | `483.0 qu/s` |
| yaw travel / second | `109.9 deg/s` | `1396.3 deg/s` |
| yaw p95 rate | `365.0 deg/s` | `14807.0 deg/s` |
| yaw reversals | `57` | `75` |
| pitch range | `-5.5..41.3 deg` | `-3.5..0.0 deg` |
| forward nonzero | `49.3%` | `98.9%` |
| side nonzero | `48.8%` | `2.6%` |
| jump button | `8.2%` | `1.5%` |

### Evidence

- Viewer: `artifacts/comparison-getspeedstill-zlive/comparison_view.html`
- Video: `artifacts/comparison-getspeedstill-zlive/getspeedstill_vs_zlive_room.mp4`
- Summary: `artifacts/comparison-getspeedstill-zlive/comparison_summary.json`
- Analysis: `artifacts/comparison-getspeedstill-zlive/comparison_analysis.md`
- Thumbnail: `artifacts/comparison-getspeedstill-zlive/comparison_frame.png`

### Interpretation

The safe-floor controller can create speed, but it does so through a much more
mechanical pattern than the human demo: snap-like view-yaw changes, almost no
pitch, mostly forward-only movement, and only brief terminal side input.  The
next controller step should not chase more speed first.  It should use the QWD
as a timing reference for smoother yaw/pitch/strafe synchronization, then
retest whether that human-shaped controller can preserve the speed already
shown on the safe-floor route.


## 2026-06-12 -- getandmaintainspeed QWD mouse-first analysis

### Experiment

Analyzed `C:\nQuake\qw\matchinfo\demos\getandmaintainspeed.qwd` with mouse
movement treated as the primary signal, not a secondary decoration.  Extracted
exact QWD user commands, paired them with recovered self-player trajectory,
rendered a simple room/POV video, and computed yaw/pitch/input/speed metrics.

### Result

This demo is a stronger human reference than the earlier short speed-gain
clips because it sustains high speed with a controlled mouse/input rhythm.

| metric | value |
|---|---:|
| exact command frames | `2615` |
| paired command/state frames | `2541` |
| paired coverage | `0.972` |
| duration analyzed | `32.987s` |
| average speed | `666.1 qu/s` |
| p50 / p95 / max speed | `720.8 / 924.4 / 948.5 qu/s` |
| time above 700 qu/s | `18.507s` (`56.1%`) |
| time above 900 qu/s | `6.377s` (`19.3%`) |
| yaw p50 / p95 / p99 rate | `132.7 / 244.8 / 618.2 deg/s` |
| yaw reversals | `43` (`1.3/s`) |
| pitch range | `0.0..40.7 deg` |
| side-only input | `84.8%` |
| jump button | `74.0%` |
| side+mouse coupling | `1918` frames, `95.1%` opposite-sign |

`qw-analyze-v20` JSON/Markdown produced an empty match summary for this QWD
and events mode failed with `unexpected dem_cmd in MVD file`; the useful
evidence is therefore the exact QWD command extraction plus
`probe_qwd_route_applicability.py`, not the generic MVD event parser.

### Evidence

- Viewer: `artifacts/qwd-getandmaintainspeed/getandmaintainspeed_view.html`
- Video: `artifacts/qwd-getandmaintainspeed/getandmaintainspeed_room_pov.mp4`
- Thumbnail: `artifacts/qwd-getandmaintainspeed/getandmaintainspeed_room_pov_frame.png`
- Mouse analysis: `artifacts/qwd-getandmaintainspeed/mouse-analysis.json`
- Mouse analysis notes: `artifacts/qwd-getandmaintainspeed/mouse-analysis.md`
- Paired trajectory: `artifacts/qwd-getandmaintainspeed/raw/getandmaintainspeed.paired.ndjson`
- Replay command file: `artifacts/qwd-getandmaintainspeed/getandmaintainspeed.cmds`
- Source SHA-256:
  `28ab7b7748bc0b6b3be0720d62d700ce177cae977ac97d8d5b7b8300ba8901a8`

### Interpretation

Do not reduce this demo to "speed is high."  The important discovery is that
high speed is maintained while side input, jump cadence, pitch, yaw lead, and
velocity heading stay coordinated.  Compared with the live bot controller, this
is exactly the missing quality: controlled mouse movement instead of spammy
view-yaw snapping.  The next controller experiment should use this QWD as a
mouse/input timing target and only then evaluate whether speed remains high.


## 2026-06-12 -- ztricks getandmaintainspeed live replay/catch-up attempts

### Experiment

Ran live `ztricks` attempts against
`artifacts/qwd-getandmaintainspeed/getandmaintainspeed.cmds` with the deployed
lab KTX build.  The target is not only peak speed: the bot must preserve the
human mouse/input timing and sustain the high-speed window from the QWD
reference.

Added experimental moveprobe mode `25`: it keeps the recorded replay view
angles and clock, but when live horizontal speed trails the human frame by a
configured gap above a configured speed floor, it projects a velocity-relative
air-strafe wishdir into the recorded view basis.  This keeps the mouse trace
human-derived while testing whether movement can catch up.

### Result

The goal is **not met yet**.  Open-loop replay remains the most human-shaped
baseline; mode `25` can improve the top end, but current settings do not
maintain the human speed window.

Per-command velocity comparison over the first replay attempt:

| run | mode / key cvars | avg | p50 | p95 | max | time >700 | time >900 |
|---|---|---:|---:|---:|---:|---:|---:|
| human `getandmaintainspeed.qwd` | reference | `666.1` | `720.8` | `924.4` | `948.5` | `18.507s` | `6.377s` |
| `getmaintain_mode10_20260612T2140Z` | exact replay | `623.0` | `680.3` | `816.6` | `827.3` | `15.497s` | `0.000s` |
| `getmaintain_mode25_hi700g80_20260612T2225Z` | min `700`, gap `80`, num `8` | `639.9` | `700.9` | `848.3` | `855.9` | `16.525s` | `0.000s` |
| `getmaintain_mode25_hi700g20_20260612T2229Z` | min `700`, gap `20`, num `8` | `559.7` | `578.5` | `891.5` | `910.8` | `10.638s` | `1.062s` |
| `getmaintain_mode25_hi700g0_20260612T2233Z` | min `700`, gap `0.1`, num `8` | `458.1` | `490.0` | `862.2` | `903.6` | `7.547s` | `0.103s` |

Other probes rejected:

- Mode `22` default smooth held-strafe route actuation did not bootstrap in this
  room (`p95 389.8`, max `461.0` by movement metrics).
- Mode `20` raw speed steering did not transfer to `ztricks`; it produced many
  teleports and maxed at `701.1` by movement metrics.
- Mode `11` path steering discarded the human mouse and was slow (`p95 391.3`,
  max `458.5`).
- Mode `25` with `s25_flip 1` was worse, confirming the original catch-up sign
  convention is the better of the two.
- Mode `25` with `s25_numerator 15` and with an `800` speed floor both failed
  to complete the full replay stream.

### Evidence

- Patched/deployed KTX build:
  `~/nquakesv/ktx/qwprogs-s25c-20260612T2243Z.so`, SHA-256
  `7450eec6d3cd6ed958c9b309aef28cf5c01f6a31a3ac84f6c3fff642c72ed6fc`
- Main live run artifacts:
  `artifacts/lab-runs/getmaintain_mode10_20260612T2140Z`
- Best mode-25 top-end run:
  `artifacts/lab-runs/getmaintain_mode25_hi700g20_20260612T2229Z`
- Rejected mode-25 runs:
  `artifacts/lab-runs/getmaintain_mode25_default_fix_20260612T2221Z`,
  `artifacts/lab-runs/getmaintain_mode25_hi700g80_20260612T2225Z`,
  `artifacts/lab-runs/getmaintain_mode25_hi700g0_20260612T2233Z`,
  `artifacts/lab-runs/getmaintain_mode25_hi700g20n15_20260612T2238Z`,
  `artifacts/lab-runs/getmaintain_mode25_hi700g20flip_20260612T2244Z`,
  `artifacts/lab-runs/getmaintain_mode25_hi800g20_20260612T2249Z`

### Interpretation

The useful signal is that the recorded mouse trace can survive mode `25` while
top-end speed rises above exact replay, but the intervention is not yet the
right shape.  More catch-up increases peak speed but steals sustained
medium-high speed and route stability.  The next smallest useful experiment is
not another broad cvar sweep; it is to make mode `25` log when the catch-up
branch engages and compare those frames to the human yaw/velocity lead.  Then
gate the boost by the human phase (for example, only inside stable side-only
arcs), not just by speed gap.

### 2026-06-12 continuation: full rebuild and direction probes

Reconstructed the KTX source from the last full per-slot/ztricks patch plus
mode `25` after a regenerated source tree had dropped the older
`spawn_velocity` and mode-23 zjump pieces.  The restored patch again passes the
structural guard and the deployed source includes mode `25`.

Added three default-off mode-25 diagnostics:

- `k_fb_moveprobe_s25_path_div` / `k_fb_moveprobe_s25_path_blend`: optional
  divergence-triggered wishdir blend toward the human frame origin.
- `k_fb_moveprobe_s25_velsign`: optional strafe-side choice by whichever
  velocity-relative wishdir points closer to the human velocity vector.

These diagnostics did **not** solve the target.  They are preserved only as
controlled probes; leave them off for the current best mode-25 baseline.

Human gate remains:

| reference | avg | p50 | p95 | max | time >700 | time >900 |
|---|---:|---:|---:|---:|---:|---:|
| human `getandmaintainspeed.qwd` | `666.1` | `720.8` | `924.4` | `948.5` | `18.507s` | `6.377s` |

Segmented first-attempt command scores from the rebuilt/live probes:

| run | key cvars | avg | p50 | p95 | max | time >700 | time >900 | note |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `getmaintain_mode25full_hi700g20_20260612T2317Z` | min `700`, gap `20`, num `8`, move `400` | `597.1` | `606.4` | `895.2` | `914.9` | `12.762s` | `1.307s` | fastest rebuilt segment, but fell/teleported out before completing |
| `gm25_g20_rerun_2325` | same | `536.7` | `559.2` | `879.5` | `904.8` | `8.933s` | `0.865s` | completed replay, still below human |
| `gm25_m800_2320` | move `800` | `459.1` | `491.4` | `854.6` | `883.9` | `8.703s` | `0.000s` | rejected; too much command magnitude |
| `gm25_n30_2322` | numerator `30` | `287.5` | `186.6` | `693.7` | `722.3` | `1.379s` | `0.000s` | rejected |
| `gm25_m508_2327` | move `508` | `461.9` | `491.9` | `856.5` | `888.0` | `9.116s` | `0.000s` | rejected |
| `gm25_path025_2330` | path div `400`, blend `0.25` | `385.6` | `326.5` | `730.8` | `767.6` | `3.466s` | `0.000s` | rejected; leash threw the bot out vertically |
| `gm25_path005_2332` | path div `500`, blend `0.05` | `520.7` | `526.8` | `753.1` | `790.0` | `2.401s` | `0.000s` | rejected; leash killed high-speed phase |
| `gm25_velsign_2335` | `velsign 1` | `435.6` | `472.2` | `796.4` | `841.9` | `4.663s` | `0.000s` | rejected; velocity sign choice worsened direction |

Phase comparison of `getmaintain_mode25full_hi700g20_20260612T2317Z` showed the
bot briefly overlaps the human's main high-speed phase: around cursors
`1760..1859`, bot average speed was `906.9` with max `914.9`.  The failure is
after that: human stays above `900` through later cursor ranges (`2044..2087`,
`2097..2104`, `2106..2230`), while the bot either falls/teleports or drops into
the `220..300` speed range.  This confirms the user's observation: speed alone
is not enough; the missing piece is synchronized direction/phase control after
the first successful high-speed burst.

Deploy evidence:

- `~/nquakesv/ktx/qwprogs-s25full-20260612T2315Z.so`, SHA-256
  `b21d65184d99caf27e1efdc57810e2324210bbd9916b00cd484672253f90b12b`
- `~/nquakesv/ktx/qwprogs-s25path-20260612T2330Z.so`, SHA-256
  `6755a2df956af5343af7b0747e7d051f82d2b7de7ca68e18792c8ca173a209b9`
- `~/nquakesv/ktx/qwprogs-s25vel-20260612T2335Z.so`, SHA-256
  `52035227301bf81464fbe9b2e788eec7a916ec666d7adf9bfd588209c45e80c1`

Verification:

```powershell
python -m unittest tests.test_perslot_moveprobe_patch tests.test_moveprobe_assign_parse -v
```

Result: `23` tests passed.

Next smallest useful experiment: add explicit mode-25 branch telemetry
(`engaged`, speed gap, chosen sign, rotation, projected forward/side, velocity
lead to human) and score it against the cursor ranges above.  The next
controller change should be phase-aware around the post-1900 cursor collapse,
not another global movement-magnitude sweep.

### 2026-06-13 continuation: phase human-command probe

Added mode-25 branch telemetry plus default-off phase probes:

- `s25=` command suffix: active/engaged/reason, live speed, target speed,
  speed gap, sign, rotation, wish yaw, live/target velocity yaw, target-velocity
  error, and emitted forward/side command.
- `k_fb_moveprobe_s25_phase_start`, `phase_target`, `phase_min_speed`,
  `phase_move`, and `phase_numerator` for phase-aware recovery after the
  first high-speed burst.
- `k_fb_moveprobe_s25_phase_human_cmd`: preserve the recorded mouse and human
  side-input sign, but use `phase_move` as the side magnitude instead of
  projecting the velocity-relative wishdir into the human view basis.
- `k_fb_moveprobe_s25_phase2_start` / `phase2_move`: default-off late-window
  boost probe.
- `k_fb_moveprobe_s25_phase_jump`: default-off jump-hold probe.

The goal is still **not met**.  The best current live result is the
phase-human-command profile:

```text
k_fb_moveprobe_s25_min_speed 700
k_fb_moveprobe_s25_gap 20
k_fb_moveprobe_s25_numerator 8
k_fb_moveprobe_s25_move 400
k_fb_moveprobe_s25_phase_start 1500
k_fb_moveprobe_s25_phase_target 850
k_fb_moveprobe_s25_phase_min_speed 320
k_fb_moveprobe_s25_phase_move 950
k_fb_moveprobe_s25_phase_human_cmd 1
```

Scoreboard against `getandmaintainspeed.qwd`:

| run | key difference | movement p95 | movement max | command p95 | command max | event time >900 | result |
|---|---|---:|---:|---:|---:|---:|---|
| human `getandmaintainspeed.qwd` | reference | `924.4` | `948.5` | `924.4` | `948.5` | `6.377s` | target |
| `gm25_phasehuman1500m900_0018` | phase human cmd, move `900` | `903.3` | `959.9` | `893.8` | `910.2` | `2.656s` | stable but too slow |
| `gm25_phasehuman1500m950_0024` | phase human cmd, move `950` | `922.9` | `963.5` | `896.5` | `915.7` | `3.840s` | best so far, still short |
| `gm25_phasehuman1500m1100_0021` | phase human cmd, move `1100` | `818.9` | `856.6` | `819.2` | `830.7` | `0.000s` | rejected, overshot rhythm |
| `gm25_phasehuman1500t900m950_0033` | target `900` | `913.6` | `967.1` | `902.9` | `919.5` | `3.733s` | more command >900, worse overall |
| `gm25_phasehuman1500t875m950_0046` | target `875` | `881.9` | `958.8` | `871.9` | `898.6` | `1.314s` | rejected |
| `gm25_phasehuman1500m950p2_2044m980_0050` | late phase2 move `980` | `889.6` | `935.3` | `884.0` | `899.3` | `0.986s` | rejected |
| `gm25_phasehuman1500m950jump_0100` | phase jump-hold | `751.7` | `823.7` | `787.5` | `847.4` | `0.041s` | rejected |

Interpretation:

- Preserving the human mouse and using boosted human side-only command is much
  better than the earlier projected catch-up vector for this reference.  It
  removes the forward/back command noise and stays on the floor.
- The useful side-move magnitude is narrow.  `950` is near the live physics
  cliff; `960`, `980`, and `1100` variants either fell or became slower.
- Holding jump continuously is not a shortcut.  It breaks the recorded rhythm
  and destroys the high-speed window.
- The bot now beats the human peak speed (`963.5` vs `948.5`) and nearly
  matches p95 (`922.9` vs `924.4`), but it does **not** maintain `>900` as long
  as the human (`3.840s` vs `6.377s`).

Deploy evidence:

- `~/nquakesv/ktx/qwprogs-s25telemetry-20260612T2345Z.so`, SHA-256
  `ddd73045cfcb35bafe225e60eb408ca4e115bba74f5a84bea53d3c629df8a1b9`
- `~/nquakesv/ktx/qwprogs-s25phase-20260612T2350Z.so`, SHA-256
  `2aed23fa9dbd5ede4f0a89998f2f63a03e91d0a1f62335a7577a7d96b2a1dfaf`
- `~/nquakesv/ktx/qwprogs-s25phasemove-20260613T0000Z.so`, SHA-256
  `9045c33d61c9d3571769f94759cde178a98a41882943228d0caad75f7e33ce67`
- `~/nquakesv/ktx/qwprogs-s25humancmd-20260613T0015Z.so`, SHA-256
  `42844ef7aff1a709766bcb449730409340d05f209319d16021e4044d7b91872c`
- `~/nquakesv/ktx/qwprogs-s25phase2-20260613T0050Z.so`, SHA-256
  `82643586e914b4dfa43c5e7c3d9a8bec7dcaa111ba6c8c5c411be3548ae21bdd`
- `~/nquakesv/ktx/qwprogs-s25phasejump-20260613T0100Z.so`, SHA-256
  `acc6aaf786055961519b120b93d351b2eb7c4b95576805bc36b15194d3d48fca`

Next smallest useful experiment: do not add more scalar magnitude sweeps.
Extract the human cursor windows where speed remains above `900` and fit a
smooth per-window side-magnitude/yaw-offset curve from the existing telemetry.
Then test one curve-shaped phase-human-command controller against the current
best profile, with success gated on event time above `900`, not peak speed.

### 2026-06-13 continuation: adaptive, yaw, and scaled-input probes

Tested four follow-up hypotheses against the current best profile
(`phase_start 1500`, `phase_target 850`, fixed phase side magnitude `950`):

1. Adaptive gap boost: add a tiny speed-deficit-based increase to phase move
   magnitude.
2. Phase yaw offset: keep mouse timing but apply a small constant phase yaw
   bias to test whether the movement basis was slightly misaligned.
3. Exact human command scaling: scale recorded forward/side commands instead
   of replacing side with a fixed magnitude, preserving human zero/transition
   frames.
4. Phase-start timing: delay phase human-command takeover from cursor `1500`
   to `1600`.

All four were worse than the current best.  The best-known run remains
`gm25_phasehuman1500m950_0024`.

| run | probe | movement p95 | movement max | command p95 | command max | event time >900 | result |
|---|---|---:|---:|---:|---:|---:|---|
| `gm25_phasehuman1500m950_0024` | current best | `922.9` | `963.5` | `896.5` | `915.7` | `3.799s` | best so far |
| `gm25_phasehuman1500m950gap025cap960_0125` | gap gain `0.25`, cap `960` | `764.8` | `842.8` | `764.3` | `802.9` | `0.000s` | rejected |
| `gm25_phasehuman1500m950yawp5_0135` | yaw offset `+5` | `884.4` | `946.3` | `879.7` | `898.5` | `1.309s` | rejected |
| `gm25_phasehuman1500m950yawn5_0138` | yaw offset `-5` | `878.1` | `1988.8` | `875.1` | `891.1` | `0.563s` | rejected; teleport spike in movement max |
| `gm25_phasehumanscale2375_0145` | exact human cmd scale `2.375` | `818.6` | `867.2` | `811.2` | `825.9` | `0.000s` | rejected |
| `gm25_phasehuman1600m950_0150` | phase start `1600` | `861.7` | `906.3` | `860.1` | `877.5` | `0.080s` | rejected |

Interpretation:

- The fixed phase side magnitude is still better than preserving exact zero
  frames.  For this bot, the human's timing alone is not enough once the body
  has diverged from the human trajectory; the controller still needs stronger
  continuous side actuation.
- Small constant yaw offsets hurt both signs, so the remaining alignment
  problem is not a simple fixed angular bias.
- A tiny adaptive magnitude increase already crosses a bad rhythm/physics
  boundary.  The current `950` side magnitude is close to the usable ceiling.
- Delaying phase takeover to cursor `1600` loses the first high-speed window.

Deploy evidence:

- `~/nquakesv/ktx/qwprogs-s25phasegap-20260613T0125Z.so`, SHA-256
  `66eb7023c62146ba0b886cc0c76cfca9f2d667e1c26d51257d2d5717420e4d6e`
- `~/nquakesv/ktx/qwprogs-s25phaseyaw-20260613T0135Z.so`, SHA-256
  `aaaaa71d9917f589c37884c2435b1895c8c0175c0d832fe689cdad523e0448f8`
- `~/nquakesv/ktx/qwprogs-s25humanscale-20260613T0145Z.so`, SHA-256
  `964f168b617a87aea1c56db6b9f7e06a5c8089d4c9f763a60935ff2dabe7cd6b`

Next smallest useful experiment: stop using a single global phase actuation
model. Split the reference into human cursor arcs and learn one small table of
phase controls per arc: fixed side magnitude, whether zero frames should be
overridden, and optional sign handling.  The table should be derived from the
successful frames in `gm25_phasehuman1500m950_0024` and must be validated on
event time above `900`, not only p95 or peak speed.

### 2026-06-13 continuation: repeatability and simple per-arc checks

Closed several missing checks around the best-known profile
(`phase_start 1500`, `phase_target 850`, fixed phase side magnitude `950`):

- Fixed `phase_move 960` with the same target/start as the best run.
- Two-arc profile: `950` until cursor `2044`, then `900`.
- Explicitly zeroed all newer default-off cvars.
- Reran the same `950` profile on both the latest all-probe binary and the
  older `qwprogs-s25humancmd-20260613T0015Z.so` binary that originally produced
  the best run.
- Tested phase start `1450` on the older binary.

None beat the human target, and the original best did not reproduce.

| run | probe | movement p95 | movement max | command p95 | command max | event time >900 | result |
|---|---|---:|---:|---:|---:|---:|---|
| human `getandmaintainspeed.qwd` | reference | `924.4` | `948.5` | `924.4` | `948.5` | `6.377s` | target |
| `gm25_phasehuman1500m950_0024` | previous best | `922.9` | `963.5` | `896.5` | `915.7` | `3.799s` | best single run, not repeated |
| `gm25_phasehuman1500m960_0200` | fixed move `960` | `840.6` | `891.5` | `837.4` | `855.1` | `0.000s` | rejected |
| `gm25_phasehuman1500m950p2_2044m900_0205` | `950 -> 900` at cursor `2044` | `898.6` | `963.5` | `892.1` | `908.4` | `2.174s` | rejected |
| `gm25_phasehuman1500m950_rerun_0210` | latest binary, same best cvars | `791.8` | `850.8` | `809.2` | `823.0` | `0.000s` | not reproduced |
| `gm25_phasehuman1500m950_zeroed_0215` | latest binary, all newer cvars explicitly `0` | `859.2` | `1988.8` | `851.3` | `867.6` | `0.281s` | not reproduced; teleport spike in movement max |
| `gm25_phasehuman1500m950_oldbin_0220` | old `s25humancmd` binary, same best cvars | `899.8` | `956.6` | `894.5` | `910.3` | `2.197s` | closer, still not reproduced |
| `gm25_phasehuman1450m950_oldbin_0225` | old binary, phase start `1450` | `862.0` | `894.1` | `835.9` | `852.6` | `0.000s` | rejected |

Interpretation:

- The fixed `950` phase-human-command profile can produce near-human p95 and
  bot-higher peak speed, but the result is not repeatable enough to claim the
  goal.
- The poorer reruns do not show leaked newer reason bits; explicitly zeroing
  the new cvars did not recover the old best.  The repeatability problem is
  therefore either live physics/setup variance or sensitivity to early route
  state, not a simple hidden-cvar leak.
- Lowering late move to `900` improved some late-window averages in earlier
  isolated evidence but did not improve full-run `>900` duration when combined
  as a two-arc controller.
- Starting phase takeover at `1450` is too early and `1600` is too late.  Cursor
  `1500` remains the best tested takeover point, but it is not robust.

Next smallest useful experiment: make repeatability first-class. Run a small
batch harness for the exact best profile, collect at least 5 attempts, and
compare early-window state before cursor `1500` between high and low outcomes.
Only then should the controller table be expanded; otherwise a per-arc table is
likely to overfit a single lucky run.

### 2026-06-13 continuation: accepted getandmaintainspeed baseline

After the repeatability investigation, the replay harness itself was tightened
before freezing a practical baseline:

- Added `k_fb_moveprobe_replay_stale_gap` so a normal command gap does not
  silently restart a replay from cursor `0`.
- Added `k_fb_moveprobe_replay_one_shot` so one-shot benchmarks can complete or
  die without falling back into stock Frogbot movement and mixing attempts.
- Relaxed replay clock-back reset to tolerate tiny backward jitter up to
  `0.25s`; the live server produced a small `11.980 -> 11.971` backward tick
  that previously caused duplicate activation.
- Added `scripts/score_getandmaintainspeed.py` so strict scoring is repeatable
  and does not depend on hand-reading one MVD.
- Fixed the generated ztricks route manifest provenance for
  `spawn_left_speedjump`: it now carries the required `source.census`,
  `source.cmds`, and `source.cmds_sha256` fields, with a note that the route is
  a synthetic spawn-floor drill rather than a separate human census.

The accepted live run is `gm25_clocktol1500m950_0420`. Benjamin watched it live
and judged the behavior more than good enough for the current baseline. This is
now frozen as an accepted operational/visual baseline, with an explicit caveat:
it still does not beat the human `getandmaintainspeed.qwd` benchmark under the
strict scorer.

Reproduction command:

```powershell
$cvars = 'k_fb_moveprobe_replay_stale_gap 120;k_fb_moveprobe_replay_one_shot 1;k_fb_moveprobe_s25_min_speed 700;k_fb_moveprobe_s25_gap 20;k_fb_moveprobe_s25_numerator 8;k_fb_moveprobe_s25_move 400;k_fb_moveprobe_s25_phase_start 1500;k_fb_moveprobe_s25_phase_target 850;k_fb_moveprobe_s25_phase_min_speed 320;k_fb_moveprobe_s25_phase_move 950;k_fb_moveprobe_s25_phase_human_cmd 1'
python scripts\run_frobodm2_lab.py --map ztricks --run-id gm25_clocktol1500m950_0420 --duration 45 --bot-count 1 --bot-spacing 0 --moveprobe-mode 25 --replay-cmds artifacts\qwd-getandmaintainspeed\getandmaintainspeed.cmds --moveprobe-log-commands --moveprobe-log-interval 0 --ktx-extra-cvars $cvars
python scripts\score_getandmaintainspeed.py --run-id gm25_clocktol1500m950_0420
```

Deploy evidence:

- `~/nquakesv/ktx/qwprogs.so` points to
  `/home/xerial/nquakesv/ktx/qwprogs-s25clocktol-20260612T2207Z.so`.
- SHA-256:
  `83b0b75297cd81a5b0c29d1e747eec434a703ca00dd430152689eca3176463fe`.

Clean replay evidence:

| event | time | cursor | note |
|---|---:|---:|---|
| activate | `7.565s` | `0` | single activation |
| complete | `40.559s` | `2540` | single completion, final horizontal divergence `71.837` |

Strict score:

| metric | human | accepted run event | accepted run command |
|---|---:|---:|---:|
| p95 speed | `924.4` | `873.6` | `869.9` |
| max speed | `948.5` | `917.6` | `886.6` |
| time >900 | `6.377s` | `0.240s` | `0.000s` |
| yaw p95 | `244.8` |  | `280.0` |
| yaw reversals/s | `1.30` |  | `1.10` |

Committed evidence snapshot:

- `experiments/ktx_moveprobe/evidence/getandmaintainspeed-accepted-baseline-20260613.json`
- `experiments/ktx_moveprobe/evidence/getandmaintainspeed-accepted-baseline-20260613.md`

Interpretation:

- The bot behavior is good enough to stop this tuning pass and preserve the
  baseline.
- The strict scorer remains valuable because it prevents us from confusing a
  visually good baseline with a numeric beat-human claim.
- Future attempts should copy this profile and compare against
  `scripts/score_getandmaintainspeed.py`; do not overwrite the accepted
  baseline while exploring stricter improvements.

Next smallest useful experiment: branch from this accepted profile, run one
strict-score improvement at a time, and keep the accepted baseline as the
rollback/reference profile.

### 2026-06-13 continuation: DM3 rocket-route replay state

The DM3 `mega_to_rl.qwd` reference is not pure movement.  Its serverinfo says
`hostname=eQuakesv KTPro Server`, `deathmatch=3`, `status=Standby`,
`pm_ktjump=0.5`; the QWD has attack+jump windows with `impulse 7`, and the
first rocket window raises horizontal speed from about `321` to `635 qu/s`.
Follow-up inspection found no literal `prewar` string in the QWD; `Standby` is
the recorded server state.  The first attack window is at frame `119`, about
`t=1.533`, near the mega-area marker (`item_health` marker 11 at roughly
`1840 624 -203`): player origin is about `1859.6 645.5 -176.5`, `buttons=3`,
`impulse=7`, and the paired state shows the rocket-style velocity change.

The first live replay implementation preserved attack bits but failed to fire:
`dm3_mega_to_rl_m25_attack_preselect_005` emitted `buttons=3` and `impulse=7`
but the MVD event log reported repeated `no weapon`.  The blocker was lab
inventory state, not mouse/strafe timing.

Implemented two default-off KTX replay controls in
`experiments/ktx_moveprobe/frogbot-moveprobe-perslot.patch`:

- `k_fb_moveprobe_replay_attack_grant`: when combined with
  `k_fb_moveprobe_replay_attack`, grants RL/rockets at replay activation.
- `k_fb_moveprobe_corr_autojump`: mode-12 corrective replay presses jump on
  unexpected ground contact when the QWD frame itself is not already jumping.

Validation:

- Patch contract: `python -m unittest tests.test_perslot_moveprobe_patch -v`
  passes 16 tests.
- Pristine KTX `08807da` apply check passes.
- Deployed replay-grant binary:
  `/home/xerial/nquakesv/ktx/qwprogs-replayattack-grant-20260612T231458Z.so`,
  SHA-256
  `2642695bab3d3f216cadc332cc9de2f52d33a24aeb2c9b57d4e64a420fc32b47`.
- Deployed replay-autojump binary:
  `/home/xerial/nquakesv/ktx/qwprogs-replayautojump-20260612T232658Z.so`,
  SHA-256
  `bfa1c33b554f9a4cb016900e80418de392bafa300385e82a8fffd590913e8d27`.

Route evidence:

| route | run | mode/cvars | result |
|---|---|---|---|
| `sng_to_rl` | `dm3_sng_m25_default_001` | mode 25, no attack | `REACHED_RL`, route `100%`, speed `101%`, closest `14 qu`, PASS |
| `mega_to_rl` | `dm3_mega_to_rl_m12_attack_grant_008` | mode 12 + attack replay + RL grant | `REACHED_RL`, route `100%`, speed `93%`, closest `23 qu`, PASS |
| `rl_to_bridge` | `dm3_rl_to_bridge_m12_attack_grant_001` | mode 12 + attack replay + RL grant | best before autojump: route `84.1%`, edge `398/467 qu/s`, fell short |
| `rl_to_bridge` | `dm3_rl_to_bridge_m12_autojump_grant_006` | mode 12 + attack replay + RL grant + autojump | edge improved to `433/467 qu/s`, still fell short |
| `rl_to_ya` | `dm3_rl_to_ya_m12_attack_grant_001` | mode 12 + attack replay + RL grant | route `94.1%`, speed `113%`, left route; best crossing speed high but goal not reached |

Interpretation:

- `mega_to_rl` is solved once the bot receives the same RL/rocket state as the
  KTPro Standby QWD.
- `rl_to_bridge` is now an actual live rocket-route attempt, not a no-weapon
  fake.  The binding failure is a small path/ground-contact divergence: around
  replay cursor `340`, the bot is only about `16 qu` off the human line but
  touches the `z=-24` floor, drops from the human's `~546 qu/s` airborne state
  to a grounded `~425 qu/s`, and cannot recover the `467 qu/s` final-edge
  requirement.  Autojump helps but does not solve the route.
- `rl_to_ya` has enough raw speed but still needs final-route/landing
  correction; speed alone is again not sufficient.

Next smallest useful experiment: for `rl_to_bridge`, add a route-local
air-preservation correction rather than more global replay cvar nudging.  The
controller should detect "human airborne but live bot grounded near the QWD
line" and bias away from the floor/ledge contact before friction drains speed;
the pass criterion remains `REACHED_RL`/bridge-goal with route `>=80%` and speed
`>=80%`.

### 2026-06-13 continuation: DM3 rocket-route completion

The route-local realign experiment succeeded after adding a replay-cursor phase
gate.  The important guard is `k_fb_moveprobe_corr_ground_realign_after`: it
keeps the idle-frame walk-to-QWD-origin correction inactive during earlier
rocket/landing phases, where a few units of pre-launch shift can miss the floor.

Validation:

- Patch contract: `python -m unittest tests.test_perslot_moveprobe_patch -v`
  passes 17 tests.
- Pristine KTX `08807da` apply check passes.
- Deployed binary:
  `/home/xerial/nquakesv/ktx/qwprogs-replaygroundalign-after-20260612T234438Z.so`,
  SHA-256
  `15d8bcda84f7f447278c0aaee4f5ce4f8506c6ce45e261df0de938b9beea5611`.

Winning runs:

| route | run | mode/cvars | result |
|---|---|---|---|
| `rl_to_bridge` | `dm3_rl_to_bridge_m12_groundalign_after340_grant_014` | mode 12 + attack replay + RL grant + ground realign after cursor `340` | `REACHED_RL`, route `100%`, speed `153%`, closest `9 qu`, PASS |
| `rl_to_ya` | `dm3_rl_to_ya_m12_groundalign_after250_grant_003` | mode 12 + attack replay + RL grant + ground realign after cursor `250` | `REACHED_RL`, route `100%`, speed `129%`, closest `1 qu`, PASS |

Interpretation:

- The exact DM3 route set requested in the current goal is now solved in live
  lab evidence: `sng_to_rl`, `mega_to_rl`, `rl_to_bridge`, and `rl_to_ya`.
- The reusable principle is not "more correction everywhere."  The ungated
  ground realign changed the first `rl_to_bridge` rocket approach by only a few
  units and caused a miss.  Phase gating matters as much as the correction.
- Speed alone is still not a sufficient success metric.  `rl_to_ya` had enough
  speed before this change but needed final route/goal correction; `rl_to_bridge`
  needed both rocket state and phase-specific path repair.

Next smallest useful experiment: run a small repeatability batch for the two new
rocket-route passes using the exact winning cvars, then promote the cvar recipes
into route metadata only if they reproduce.

### 2026-06-13 continuation: `dm3_ring_to_mega` is passable but not repeatable

`dm3_ring_to_mega` is a tighter binding case than the solved rocket routes.  The
human route needs about `536.5 qu/s` at the ring-room launch edge and the human
reference only has about `536.8 qu/s`, so a few units of path/cadence drift are
enough to turn a good-looking replay into a wall/slot clip.

Validation and deploy evidence:

- Patch contract: `python -m unittest tests.test_perslot_moveprobe_patch -v`
  passes 20 tests.
- Pristine KTX `08807da` apply check passes.
- Deployed command-blend/interpolation binary:
  `/home/xerial/nquakesv/ktx/qwprogs-replay-cmdblend-interp-20260613T080057Z.so`,
  SHA-256
  `1f0e3712642e1edb71c0d2a9f48f65bddb62bde12ebe4852a6e69e18c248daca`.

Live route evidence:

| run | cvars | result |
|---|---|---|
| `dm3_ring_to_mega_m12_baseline_002` | mode 12, yaw correction | Fell short: route `67.8%`, speed `77%`, edge `532/536`; trace shows a slot clip near `x=1232`, `y=684`. |
| `dm3_ring_to_mega_m12_cmdblend005_noyaw_019` | command blend `0.05` after cursor `245`, yaw disabled | PASS: route `100%`, speed `99%`, closest `3 qu`. |
| `dm3_ring_to_mega_m12_cmdblend005_noyaw_020` | same as above | Fell short: route `68.1%`, edge `514/536`; already `~27 qu` behind the human line at cursor `220`. |
| `dm3_ring_to_mega_m12_cmdblend005_noyaw_021` | same as above | Fell short: route `68.1%`, edge `534/536`; clipped/stalled near `x=1232`. |
| `dm3_ring_to_mega_m12_cmdblend005_noyaw_022` | same as above | PASS: route `100%`, speed `99%`, closest `0 qu`. |
| `dm3_r2m_msec_only_027` | recorded `msec` override, no path blend | Worse: route `65.8%`, edge `468/536`; cadence override alone is rejected for this route. |
| `dm3_r2m_interp_only_028` | QWD reference/view interpolation, no path blend | PASS: route `99.9%`, speed `99%`, closest `2 qu`. |
| `dm3_r2m_interp_only_029` | same as above | Bad failure: no scoreable segment; interpolation can send the bot into an early wrong/teleporting line. |

Interpretation:

- The route is not unsolved because the bot cannot generate enough speed; the bot
  can complete it in live KTX.  The failure is repeatability.
- The stable principle from Nexus still looks right: the controller needs proper
  interpolation/resampling between QWD datapoints, but the first live
  implementation is too naive.  Smoothing the reference view/path without a
  phase guard can make an early line much worse.
- More path blend is not the answer.  Starting blend earlier or increasing
  command magnitude stole speed or knocked the route off-line.
- Recorded `msec` override is also not the answer by itself; it reduced edge
  speed on this route.

Next smallest useful experiment: add replay resampling diagnostics before more
controller changes.  Log selected cursor, previous cursor, interpolation
fraction, raw-frame yaw, interpolated yaw, and whether the live bot is on a
teleporter/route marker during the first `120` replay cursors.  Then compare one
pass (`028`) against the bad interpolation failure (`029`) to decide whether the
fix is angle wrapping, start-phase gating, or not interpolating view yaw until
after the first stable bunnyhop cycle.

### 2026-06-13 continuation: later `dm3_ring_to_mega` repeatability sweep

Live deploy evidence:

- Local patch contract: `python -m pytest tests/test_perslot_moveprobe_patch.py`
  passes `21` tests after adding step-cursor, start-resnap, and phase lane-nudge
  guards.
- Deployed start-resnap binary:
  `/home/xerial/nquakesv/ktx/qwprogs-replay-startresnap-20260613T102652Z.so`,
  SHA-256
  `fdc61193a0b13ec03ac8be884d677c327209c9b89ce0dd358c4aca4de3063e1b`.
- Deployed lane-nudge binary:
  `/home/xerial/nquakesv/ktx/qwprogs-replay-lanenudge-20260613T113516Z.so`,
  SHA-256
  `6b04b69e0e95d6af2a2866e3d6496b7f498e042cb96d7dc0a9063d758df26b90`.

Best live repeatability results:

| profile | result | notes |
|---|---:|---|
| `jump268`, mode `25`, interpolation, phase `200/500`, move `650` | `2/6` | Too weak; failures include no ledge impulse and low-speed fall-short. |
| same, move `700` | `3/6` | Still clips/stalls around `x=1232,y=688` in failed runs. |
| same, move `800` | `6/8` | Best late-strength profile before phase-start tuning, but still has two short/clip misses. |
| phase `170/440`, min speed `420`, move `800`, `jump268` | `3/3` in sweep, then `6/8` repeat | Best overall open-loop family so far; misses are one no-score start/vertical warp and one no-ledge contact miss. |
| successful-bot-pass replay rebuilt from `dm3_r2m_m25_jump268_start170m800_repeat_001` and replayed in mode `12` | `3/6` | Replaying the bot's own successful live trajectory did not remove the contact variance. |

Rejected or non-winning levers:

- `k_fb_moveprobe_replay_step_cursor 1` with the `m800` profile was stable but
  consistently short: `0/4`.
- Recorded command `msec` with the `start170/m800` profile was consistently
  worse: `0/4`, route only about `47%`.
- `k_fb_moveprobe_s25_phase_jump 1` from cursor `170` was worse: `0/6`; it
  changes earlier hops and leaves the route before the launch edge.
- One-frame-earlier jump profiles (`jump266`, `jump267`) did not solve the
  contact problem; `jump267` reached `2/3` in one sweep but still had a
  no-ledge miss.
- Final-window forward-bias profiles (`+100/+200`, cursors `250/260..285`) were
  worse and often produced no ledge approach.
- Small shifted-origin replay profiles (`shift4_7`, `shift8_14`, `shift0_8`)
  were worse; `shift6_0` only reached `1/2`.
- Phase lane-nudge was mixed/worse in its first sweep. It remains default-off.

Current interpretation:

- `dm3_ring_to_mega` is passable in live KTX but still not solved
  reproducibly. The best profile completes multiple live attempts, but not
  enough to promote it as a standard route.
- The remaining scored miss is usually not raw speed; it is final contact. In
  the clearest miss, the bot is only about `6 qu` short of the contact point at
  cursor `270`, so it never receives the launch impulse and falls through the
  void despite holding the correct jump button.
- The no-score class can include vertical start corruption: one run went from
  replay frame `0` at `(204.5,-151.6,56)` to `(192,-208,-175)` by cursor `1`.
  The current start-resnap guard only checks horizontal divergence; a future
  repair should consider total or vertical divergence too.

Next smallest useful experiment: add final-contact diagnostics around cursors
`250..285`: flags decoded by name, on-ground transition edges, collision/plane
state if available, and the exact frame where vertical velocity flips positive
in pass runs. Then add a route-local contact-aware jump/contact assist only if
the diagnostics prove that the bot reaches the correct surface late rather than
missing the surface entirely.
---

## 2026-06-10 -- QWD mouse/command replay seam audit

### Finding

Claude's A5 handoff was mostly honest and mostly right on the live/sim gap: the generic replay seam really did need the A5 time-aligned command/state repair, and ztricks live retries need per-attempt re-arm/re-snap because the catcher teleport injects a 300 qu/s throw. The important tightening is that frame-order `zip(cmds, states)` is not generally safe once `svc_playerinfo` rows drop.

QWD "mouse movement" is the per-frame absolute view-angle result plus movement commands/buttons, not raw device mouse deltas. That is still the right KTX replay label because `trap_SetBotCMD` consumes absolute command angles. Real-demo validation kept `cmd_angles` vs trailing `view_angles` differences at thousandths of a degree on the sampled demos.

### Evidence

- `scripts/build_replay_command_file.py` now time-matches commands and anchored player states by QWD time by default, writes a JSON sidecar with alignment/msec/angle-channel metadata, interpolates missing reference rows, and refuses unsafe legacy zip builds unless `--allow-unsafe-zip` is explicit.
- `scripts/qwd_seam_validator.py` audited the two locally present requested demos:
  - `DM3_trick5.qwd`: 479 commands, 473 state rows, zip unsafe, six interpolated time-aligned reference rows, yaw p95 channel delta `0.002411` deg.
  - `dm3_sng_to_rl.qwd`: 692 commands, 692 state rows, zip safe by count/drift, one generic-builder unmatched/interpolated row, yaw p95 channel delta `0.0` deg.
- `getspeed.qwd` was not present locally at `C:\n\Quake\qw\matchinfo\demos\getspeed.qwd`, so the raw QWD seam validator could not be rerun on that source file. The committed A5 physics validation still reproduced the expected PASS from `getspeed-aligned.cmds`: anchored p95 `0.147` qu, 11 attempts, winning attempt landed in sim.
- `scripts/audit_replay_timing.py` now compares source `.cmds` cadence/cursor time against live `moveprobe-commands.json(.gz)` or `screen.log`, including first-active-frame angle deltas. No local active mode-10 live command artifact was available to run a meaningful timing audit today.
- A5 live port artifacts were added as `experiments/a5_distance_standstill/a5-live-port-spec.md` and `a5-live-port-servexeri-overlay.md`. They are not deployed; they document the `servexeri:~/nquakesv/build/ktx` seam for replay `fixangle`, replay timing diagnostics, S23 transition logs, catcher re-arm/re-snap, fixed target navigation, and terminal carve release. The overlay is a draft, not an apply-ready KTX patch.
- The lab runner now parses `FBMOVEPROBE_S23` rows into `moveprobe-s23-events.json` and `.md`.

### Follow-up

Restore or locate `getspeed.qwd` if raw-QWD seam validation needs to be repeated. Before scored A5 live runs, apply/review the servexeri overlay, run an inertness gate, run a short ztricks S23 smoke proving snap/re-arm/arm/release/timeout events, and run the replay timing audit on the next active replay artifact before changing live replay to source-row `msec`.

---

## 2026-06-12 -- Issue #157 roster convergence fixed for ztricks resets

### Finding

The BotLab control-panel roster now converges after ztricks practice resets and
single-bot respawn flows instead of re-appending late frame rows from previous
attempts.

### Evidence

Code validation:

- `python -m unittest tests.test_f3_control_drawer -v`: 57 tests passed.
- `npm run build` in `lab/dashboard`: passed.
- `python -m unittest discover tests`: 1032 tests passed after rebasing onto
  `Harden QWD replay seam alignment (#128)`.

Browser/live validation:

- Reloaded the patched local dashboard at
  `http://127.0.0.1:5173/botlab/?views=game&ws=ws%3A%2F%2F127.0.0.1%3A8771`.
- Used the control panel force-takeover flow to replace the stale dashboard lock
  with a fresh dashboard-owned `ztricks` session on port `28599`.
- Ran **try** twice. After the second try and a 14 s wait, beyond the old
  10 s suppression window, the rendered bot roster contained exactly one row:
  `s7 / bro`.
- Existing Live Game/FTE console error was still present and remains covered by
  #158; the roster fix did not depend on the Live Game pane rendering.

### Interpretation

The old timer-only suppression was too weak: once its 10 s window expired, late
telemetry frames from removed edicts could be treated as new frame-discovered
bots. The drawer now tracks frame fallback mode explicitly. Normal add-bot
flows stay in append mode, pause/remove-all use an empty mode, and single-bot
respawn uses a single-bot mode that locks onto the first accepted live ed and
ignores later frames from other edicts. Ztricks Distance remains a normal route,
not a hardcoded GUI trick preset.

### Follow-up

Close #157 after this PR lands. The next smallest useful experiment is #158:
fix the Live Game/QTV rendering path so the primary watch-live story no longer
depends on Live 3D alone.

---

## 2026-06-22 -- RL-on-speed cracks closed-loop over-press (movement-v5); cadence the residual

> Caveat (PR #356, 2026-06-22): the magnitudes below predate three Codex-found fixes — a PPO joint-ratio head mismatch (`old_logp` included the attack head, `new_logp` didn't -> unchanged-policy ratio `1/p_attack`), a closed-loop policy-self-yaw `yaw_rate==0`-after-tick-0 bug, and an uninitialized `_prev_goal_dist` on reset — so they are INDICATIVE pending a clean re-train+re-eval; the DIRECTIONAL result (RL moves over-press where the supervised family could not) is unlikely a pure artifact but the exact numbers warrant re-validation. See `docs/notes/rl-onspeed-results.md`.

### Experiment

Solve the closed-loop bunnyhop-SPEED skill the supervised family could not make.
`ml/train_broad_bc.py`-trained cs10 (and every supervised successor: reweight,
GRU-sequence, DAgger D-1/D-1.5/D-2 — exhausted per #353) over-presses forward
~0.83-0.96 in closed loop (human air band 0.07-0.50), so air-strafe accel dies and
the G-MV4 speed band (avg 252.279-315.632; p95 461.538-560.008) fails. Ran `ml/rl_onspeed.py`
(PPO-on-speed, movement-v5): the BC trunk + a self-yaw action head (policy owns its
movement yaw = the speed mechanism), warm-started from the BC-pretrained believable-aim
ckpt and KL-anchored to a frozen copy of it for believability, reset from catalog val
segments, evaluated by the SAME goal-conditioned gate harness
(`ml/eval_broad_closedloop.py` + `ml/eval_broad_dryroute.py`, post-#355 goal-injection
fix). 8 rounds, each raw-validated.

### Result

**The over-press is SOLVED, and it was a REWARD ARTIFACT — not fundamental.** Round 4
proved over-press and speed were ANTI-CORRELATED under a "speed-however-achieved" reward
(every in-band-speed snapshot bulldozed at press >= 0.80; the only low-press snapshot was
too slow at M1 163.5). Round 5 changed the reward to credit speed ONLY via the air-strafe
mechanism (`perp_frac = 1 - (v_hat . wishdir)^2`) plus a hard air press-barrier — the
anti-correlation BROKE (M1 257 in-band at press 0.0). Round 6 softened the barrier to land
in the human band: best ckpt **`rl_round6_r4init.pt`** is fast (M1 273.22, in the 252-316
band) by air-strafing at human-level forward-press (0.243, in the human 0.07-0.50 band — NOT
bulldozing), launching (ra_jumps PASS, launch 1/3), and believable (G-MV1). One residual:
**M6 G-MV3 strafe cadence** (the L<->R flip rhythm, in-band margin band 8-360) co-occurring
with launch + speed in a single snapshot — best ckpt is at -8 (out of band).

### Evidence

- `python -m unittest discover -s tests`: floor PASS (count reported in PR), incl. the
  logging-coverage guard for the new `ml/rl_onspeed.py` (#351).
- Per-round metric vectors (raw-validated, source `/home/ubuntu/.claude/overnight-rl-state.json`
  `runs[]`), all from the goal-conditioned gate harness:
  - R1 basin-escape: over-press 0.906 -> 0.571 while G-MV1 held (the supervised family never
    moved it off ~0.83-1.0); M5 hard-route speed% 22 -> 71; launch 0 -> 1/3.
  - R2 regression + launch-guard break (tuning misstep; eval is deterministic-argmax, so
    behavior rewards must move the ARGMAX, not just sampling) — discarded.
  - R3 first M1 in-band (267.576 >= 252) + M6 cadence fixed; over-press regressed to 0.799
    (eval-vs-rollout press selection bug).
  - R4 net-best on aggregate (M1 280.088) + the decisive press<->speed anti-correlation
    diagnostic = a reward problem, not selection.
  - R5 REWARD BREAKTHROUGH: M1 257.066 in-band at press 0.0 (relief maxed 0.5); over-flipped
    to press 0 + cadence/launch broke (not promoted).
  - R6 OVER-PRESS SOLVED IN-BAND: `rl_round6_r4init.pt` M1 273.22 / press 0.243074 / M5 80.845
    / launch 1/3 / G-MV1 (best); companion `rl_round6.pt` (r5init) M6 in-band +26.97 but press
    just-under 0.026.
  - R7 broke the press<->cadence tension (first unified candidate @it12) but over-flipped
    (281 fpm) -> M1 1.16 under floor + launch broke (not promoted).
  - R8 (final) 4/5 guard-safe (M1 255.826, press 0.485 in-band, launch 1/3, G-MV1) with M6
    cadence -8 the residual; an 8-candidate launch-aware screen + a seed sweep reproduced
    the tension.
- Checkpoints live on pinnacle `/home/xerial/rl-onspeed/ckpts/rl_round{1..8}*.pt` (NOT in
  git); best = `rl_round6_r4init.pt`.

### Interpretation

RL is the matched lever for the closed-loop bunnyhop-speed skill: it cracked the central
failure (over-press / bulldozing) that defeated the entire supervised family, and the
round-5 mechanism-gated reward proved that failure was an artifact of crediting
speed-however-achieved, not an intrinsic property of the manifold. The bot can be fast by
air-strafing at human press, launch, and stay believable. The unsolved M6 cadence is a REAL
tension, not under-tuning: the argmax side-flip that creates cadence steals the sustained
perpendicular air-strafe that launch and the speed floor depend on (they compete for the
same yaw control), reproduced across 8 candidates + a seed sweep.

What this does NOT prove: the cadence rhythm is NOT solved in-band with launch+speed; the
checkpoints are not productionized (no live-server validation, no deployment); and the
result is the offline goal-conditioned gate harness, not live play.

### Confidence

High (8 raw-validated rounds from the same gate harness; the anti-correlation and its break
were each demonstrated; the residual was reproduced across candidates + a seed sweep).

### Follow-up

The cadence residual needs a DIFFERENT mechanism than a per-tick flip reward: a
trajectory/multi-tick cadence credit (reward the L<->R rhythm without shortening the
strafe-hold that feeds launch) OR AMP (adversarial believability discriminator on the real
human yaw-rhythm distribution). Owner-gated. See `docs/notes/rl-onspeed-results.md` and
`docs/08_DECISION_LOG.md`.
