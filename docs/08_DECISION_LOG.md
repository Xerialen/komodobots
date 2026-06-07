# Decision Log

Status: living document.

Purpose:

Record major project decisions and the evidence that motivated them.

Format:

## Decision

Short title.

### Date

YYYY-MM-DD

### Decision

What was chosen?

### Alternatives Considered

What other options existed?

### Evidence

What findings, measurements, documents, or experiments informed the decision?

### Expected Consequences

What do we expect to happen because of this choice?

### Revisit Conditions

What evidence would justify revisiting the decision?

---

## Initial Decision

### Date

2026-06-05

### Decision

Start from KTX/Frogbots rather than building a new bot framework.

### Alternatives Considered

- New bot architecture.
- Continue directly toward custom simulation stack.

### Evidence

Current evidence is incomplete.

KTX/Frogbots already appear to provide server-native integration, physics participation, combat participation, and MVD recording.

### Expected Consequences

Lower initial implementation cost.

### Revisit Conditions

If movement cannot be isolated and replaced cleanly, or if Frogbot architecture proves excessively restrictive.

---

## Decision

Use `servexeri` MVDSV/KTX as the first lab substrate; any port is acceptable.

### Date

2026-06-05

### Decision

Build the first Komodobots movement lab around the existing `servexeri:~/nquakesv/` MVDSV/KTX install. User clarified on 2026-06-05 that no one plays on this server, so the lab may use any port, including the existing `turkishbathhouse` ports `28501`, `28502`, and `28503`.

### Alternatives Considered

- Use `ezquake-test` / `~/hud-runner` as the lab foundation.
- Run experiments directly on one of the existing MVDSV ports.
- Build a fresh local MVDSV/KTX install before doing any smoke test.

### Evidence

`servexeri:~/nquakesv/` already has MVDSV, KTX, `dm2.bsp`, `frobodm2.bsp`, Frogbot route files, and MVD recording config. `ezquake-test` is valuable but only replays existing demos in a headless client. Player-traffic risk is low because the user confirmed no one plays on this server.

See `docs/05_HEADLESS_TEST_ENV.md` and `docs/07_FINDINGS_LOG.md` entry `2026-06-05`.

### Expected Consequences

The first smoke test should be small and fast: start or reuse one MVDSV/KTX process, spawn a Frogbot, produce a short MVD, parse it, then clean up only what the lab run owns. A separate generated lab process is still cleaner, but no longer required for traffic isolation.

### Revisit Conditions

Revisit if unattended bot spawning cannot be controlled through console/rcon/scripted client, if lab runs cannot produce MVDs without a real match flow, or if using the existing install creates confusing state that hurts repeatability.

---

## Decision

Use a minimal QuakeWorld client shim for unattended lab control.

### Date

2026-06-05

### Decision

For near-term lab automation, control KTX Frogbots by connecting a minimal scripted QuakeWorld client and sending reliable string commands such as `botcmd addbot` after sign-on. The current experiment artifact is `experiments/qw_min_client.py`.

### Alternatives Considered

- Issue `botcmd` directly from the MVDSV server console.
- Rely on KTX Frogbot auto-add cvars.
- Drive a full ezQuake client under Xvfb.

### Evidence

The `frobodm2` smoke test proved that server-console `botcmd` fails with `Unknown command "botcmd"`, while a connected scripted client can send `botcmd addbot` and cause Frogbots to enter the match. KTX auto-add does not add bots with zero human players because its path depends on `human_count`. ezQuake under Xvfb reached the server at the UDP level but did not reliably become a connected slot during this pass.

The successful run produced `ffa_2[frobodm2]20260605-1825.mvd`, which `qw-analyze-v20` parsed as a 39.3 second `Frogbotrophobopolis` recording with two RL frags between `/ bro` and `/ goldenboy`.

### Expected Consequences

The next lab runner can stay small: start a named MVDSV/KTX screen session, connect `experiments/qw_min_client.py`, issue KTX client commands, stop recording, parse the MVD, and shut down only the owned session. A full graphical client is not required for the first automation loop.

### Revisit Conditions

Revisit if the shim cannot be made reliable across repeated clean runs, if KTX exposes a cleaner remote command path, or if future experiments need actual ezQuake client behavior rather than server-side bot control.

---

## Decision

Use a local Python runner for lab orchestration.

### Date

2026-06-05

### Decision

Use `scripts/run_frobodm2_lab.py` as the current one-command lab entry point. It runs locally on Windows, orchestrates remote `servexeri` work through `ssh`/`scp`, and runs MVD parsing through WSL `qw-analyze-v20`.

### Alternatives Considered

- Keep running the smoke test as a manual sequence of SSH/screen commands.
- Write the orchestration as PowerShell only.
- Move all orchestration to a remote shell script on `servexeri`.

### Evidence

The runner completed two clean `frobodm2` runs:

- `20260605T190849Z`
- `20260605T191116Z`

Both produced local artifact directories, copied non-empty `demo.mvd` files, parsed JSON/Markdown with exit `0`, tolerated the known events-mode `qw-analyze: end of demo` exit `1`, wrote `run-summary.md`, and left port `28599` down after cleanup.

### Expected Consequences

Lab runs become easy to repeat and inspect from the repository. Raw artifacts stay out of Git under `artifacts/lab-runs/<run-id>/`, while project-relevant findings are promoted into docs.

### Revisit Conditions

Revisit if the launcher needs to run from non-Windows hosts, if WSL is removed from the parser path, or if orchestration grows large enough to deserve a dedicated package/module layout.

---

## Decision

Do not build stock `dm2` Frogbot routes for the lab.

### Date

2026-06-05

### Decision

Keep stock `dm2` as important `qw-sim` context, but do not treat it as a Frogbot movement-lab target. Use maps with real existing Frogbot route files, currently `frobodm2` and `dm3`, for bot-generated MVD experiments.

### Alternatives Considered

- Force stock `dm2` by copying `frobodm2.bot` to `dm2.bot`.
- Build new stock `dm2` Frogbot routes.
- Continue only on `frobodm2`.
- Try another routed map such as `dm3`.

### Evidence

User clarified that Frogbots have never worked on stock `dm2`; this is why `frobodm2` exists. User also clarified that `dm2` was chosen for `qw-sim` continuity, not because it is ideal for bunnyhopping measurement.

Environment checks showed `dm2.bsp` and `dm2.loc` exist, but `ktx/bots/maps/dm2.bot` does not. A no-route `dm2` run produced a parsable MVD but no bots. A temporary route-copy experiment could spawn bots once, but the next run destabilized and left a zero-byte demo. `dm3` has `dm3.bsp`, `dm3.loc`, and `dm3.bot`; run `20260605T200124Z` spawned two bots, produced a parsable `102929` byte MVD, and recorded one frag.

### Expected Consequences

The lab should spend effort on measurement and movement evidence, not route authoring for a map known to be unsuitable for Frogbots. `dm3` becomes the next clean routed-map complement to `frobodm2`.

### Revisit Conditions

Revisit only if a real maintained stock `dm2.bot` route appears, or if the project explicitly decides route authoring itself is the experiment.

---

## Decision

Derive first movement metrics from MVD event position samples.

### Date

2026-06-05

### Decision

Use `events.txt` from `qw-analyze-v20 -format events` as the first canonical movement-metric source. Derive per-player horizontal speed, distance, stationary time, and speed-threshold ratios from `kind:5` origin samples. Generate `movement-metrics.json` and `movement-metrics.md` for each lab run.

### Alternatives Considered

- Wait for `qw-sim` integration before producing any movement metrics.
- Use KTX demo sidecars as the primary movement evidence.
- Measure only frags/combat outcomes until movement overrides exist.
- Parse MVDs visually through ezQuake playback.

### Evidence

The WSL parser reliably writes event streams for generated MVDs, even though events mode currently exits `1` with `qw-analyze: end of demo` on short recordings. The event stream includes named player updates (`kind:1`) and dense player origin samples (`kind:5`) with timestamps.

Fresh runs proved the path:

- `20260605T201217Z` on `frobodm2` produced two named-player movement rows.
- `20260605T201313Z` on `dm3` produced two named-player movement rows.

KTX `.txt` sidecars may be empty, and frags are not guaranteed on short runs, so neither is sufficient as the movement evidence layer.

### Expected Consequences

Every bot lab run now produces an immediate movement scoreboard. This makes future movement changes testable against a stable artifact before deeper input reconstruction or `qw-sim` integration exists.

The metrics remain position-derived and should not be overclaimed as legal usercmd, jump timing, or airborne-state analysis.

### Revisit Conditions

Revisit once `qw-sim` can compute equivalent metrics directly, once parser versioning is pinned for regression use, or once airborne/jump-state reconstruction changes the canonical metric source.

---

## Decision

Label vertical movement as an airborne proxy, not ground truth.

### Date

2026-06-05

### Decision

For baseline movement report v2, derive air/jump-like metrics from vertical movement runs in MVD position samples, and label them explicitly as `airborne_proxy` metrics. A qualifying run is currently a vertical-motion sequence lasting at least 120 ms with at least 4 qu of Z range.

### Alternatives Considered

- Call the metric true airborne time.
- Wait for engine-side grounded flags before adding any vertical/jump metric.
- Use only horizontal speed until movement overrides exist.

### Evidence

MVD event position samples expose origin over time, but not normal player usercmds or an explicit grounded flag. Fresh v2 baseline runs on `frobodm2` and `dm3` produced useful vertical-motion summaries, but `dm3` also showed that high air-proxy time can coexist with weak horizontal speed. This means the metric is useful, but should not be overclaimed as bunnyhopping proof by itself.

### Expected Consequences

The lab can now track speed plus a jump-like proxy across baseline and future movement-controller experiments. Reports should continue to show the threshold method so comparisons remain reproducible.

### Revisit Conditions

Revisit if `qw-analyze-v20`, `qw-sim`, KTX instrumentation, or a movement override path exposes real grounded state, jump commands, or collision-plane context.

---

## Decision

Use `BotSetCommand()` as the first S2 movement override control point.

### Date

2026-06-05

### Decision

For the first movement override feasibility probe, hook KTX/Frogbots at `src/bot_movement.c::BotSetCommand()` after the prewar-freeze guard and immediately before button assembly and `trap_SetBotCMD(...)`.

Keep this as an experiment patch in Komodobots (`experiments/ktx_moveprobe/frogbot-moveprobe.patch`) until the project has enough evidence to justify an upstreamable KTX extension.

### Alternatives Considered

- Rewrite Frogbot path/routing logic first.
- Drive movement from an external client instead of server-native Frogbots.
- Add route-file hacks to force specific movement.
- Wait for `qw-sim` or human-demo comparison before attempting overrides.

### Evidence

KTX source inspection showed `BotSetCommand()` is the final command-emission point for bot `msec`, angles, movement values, buttons, and impulses.

Run `20260605T213010Z` proved fixed-command replacement plus forced jump can produce MVD/parser/metrics artifacts, though the movement collapsed.

Run `20260605T213149Z` proved a forced-jump perturbation can preserve bot spawning, combat, MVD recording, parser output, and movement metrics.

The v2a emitted-command comparison (`20260605T222006Z`, `20260605T222047Z`, `20260605T222129Z`) showed stock variable commands, forced-jump commands with jump-bearing final buttons, and fixed mode `2` commands with constant `yaw=90 forward=800 side=0 up=0 buttons=2`. Mode `2` still collapsed behavior to near-stationary movement.

The v2b route-yaw run (`20260605T224811Z`) showed that mode `3` can emit route-derived yaw with mostly `forward=800` and jump-bearing buttons. `/ goldenboy` moved plausibly, but `/ bro` spent `59.7%` of active time stationary.

The v2c repeatability check added an explicit command/plausibility gate and fresh route-yaw mode `3` repeats. `20260605T225720Z` on `frobodm2` and `20260605T225802Z` on `dm3` passed the gate for all four bot rows.

### Expected Consequences

S2 can proceed with instrumentation and small controller probes inside the server-native KTX/Frogbot loop instead of rewriting the bot stack. The project can treat movement override feasibility as provisionally satisfied pending review.

The next controller/probe should move toward a bounded S3 bunnyjump primitive while keeping combat/aim separation explicit. Mode `3` proves movement feasibility, not a final player-realism controller.

---

## Decision

Treat S3a mode `4` as a measured negative/partial result, not a better controller.

### Date

2026-06-05

### Decision

Do not promote the first alternating-strafe mode `4` into a larger controller yet. Keep it as a disposable S3a probe and diagnose parameters before adding more logic.

### Alternatives Considered

- Declare mode `4` the first bunnyjump primitive because it emits sidemove and passes `frobodm2`.
- Skip parameter diagnosis and add more controller state immediately.
- Revert to mode `3` and postpone strafe experiments.

### Evidence

Run `20260605T231033Z` on `frobodm2` passed the side/plausibility gate and recorded one RL frag, proving the alternating side command can be emitted and still keep the lab alive.

Run `20260605T231115Z` on `dm3` emitted side commands with over `93%` coverage, but `/ bro` failed low-speed at `63.0%` and `/ goldenboy` barely passed at `39.0%`.

### Expected Consequences

S3 should proceed as a sequence of small movement-literacy probes. The next step should vary sidemove magnitude or cadence and compare against mode `3`, rather than adding a larger bunnyjump controller.

### Revisit Conditions

Revisit if a small parameter sweep produces consistent gains over mode `3` while passing the v2c/S3 side gate on both routed maps.

---

## Decision

Use `sidemove=200` as the next S3 strafe probe candidate.

### Date

2026-06-05

### Decision

For the next bounded S3 experiment, test mode `4` with `--moveprobe-sidemove 200` across maps/repeats before adding cadence cvars or stateful movement logic.

### Alternatives Considered

- Keep default `400` because it passed `frobodm2`.
- Use `300` because it helped `/ goldenboy` on `dm3`.
- Add a new cvar for alternation cadence immediately.

### Evidence

The S3b `dm3` sweep showed:

- `20260605T231737Z`, `sidemove=200`: both bots passed the side/plausibility gate.
- `20260605T231819Z`, `sidemove=300`: `/ bro` failed low-speed at `51.1%`.
- Prior `20260605T231115Z`, default `400`: `/ bro` failed low-speed at `63.0%`.

### Expected Consequences

The next experiment can stay parameter-only and avoid adding controller complexity. If `200` repeats across maps, it becomes the first candidate S3 strafe magnitude.

### Revisit Conditions

Revisit if repeat runs show `200` is unstable, or if a slower alternation cadence becomes necessary to reduce low-speed behavior without dropping side coverage.

Stop expanding route-yaw mode `4` if `sidemove=200` does not generalize beyond mode `3` across `frobodm2` and `dm3`. The next branch should then be aim-independent movement: compute `forwardmove` and `sidemove` from a desired route velocity relative to the bot's actual combat view angle, rather than continuing to tune a view-yaw-commandeering scaffold.

### Revisit Conditions

Revisit if the command hook cannot express useful movement without fighting aim/combat logic, if KTX maintainability becomes poor, or if a cleaner movement-brain boundary appears elsewhere in Frogbot source.

---

## Decision

Pivot the next S3 probe toward aim-independent movement.

### Date

2026-06-05

### Decision

Treat mode `4 --moveprobe-sidemove 200` as the first repeatable route-yaw strafe candidate, but do not add more route-yaw cadence or state before testing aim-independent movement math.

The next experiment should preserve the bot's actual combat view angle and compute `forwardmove`/`sidemove` from the desired route direction relative to that view. This is the smallest step that connects Movement Realism to Player Realism.

### Alternatives Considered

- Keep tuning route-yaw sidemove magnitude/cadence after S3c passed.
- Promote mode `4` into a larger bunnyjump controller.
- Stop S3 because the side/plausibility gate is green.

### Evidence

S3c validated `sidemove=200` across the two routed maps:

- `20260605T233120Z`, `frobodm2`: both bots passed the side/plausibility gate and one RL frag was recorded.
- `20260605T233202Z`, `dm3`: both bots passed the side/plausibility gate.

The same evidence still inherits the route-yaw limitation: the probe gets route-relative movement by pointing view yaw at the route. Believable players can aim at enemies while moving route-relative, so the next proof must decouple movement command calculation from aim commandeering.

### Expected Consequences

S3 continues, but the next useful code should be a small mode or diagnostic that tests relative forward/side command mixing. If that fails, the project learns where the aim/move boundary actually is before investing in a final bunnyjump controller.

### Revisit Conditions

Revisit if preserving combat view makes command coverage or movement plausibility collapse, or if source inspection shows a cleaner existing Frogbot field than `desired_angle` for separating movement intent from aim.

---

## Decision

Diagnose the aim-independent movement split before adding a corrective policy.

### Date

2026-06-05

### Decision

Treat S3d mode `5` as a mechanical success but behavioral split. It proved that KTX can emit route/strafe commands projected relative to preserved combat yaw, but it did not pass the movement plausibility gate for both bots.

The next S3 experiment should add route-vs-view diagnostics instead of changing the movement policy again. Specifically, capture or summarize route yaw, preserved view yaw, yaw delta, and backward-command ratio so the project can tell whether `/ bro` fails because it is often trying to run backward/sideways relative to its aim.

### Alternatives Considered

- Tune mode `5` sidemove or cadence immediately.
- Add a no-backpedal clamp immediately.
- Revert to route-yaw mode `4` because it passed S3c.

### Evidence

S3d runs with mode `5 --moveprobe-sidemove 200`:

- `20260605T234620Z`, `frobodm2`: command coverage passed for both bots. `/ goldenboy` passed the behavior gate and recorded one SSG frag, but `/ bro` failed stationary `74.7%` and low-speed `79.2%`.
- `20260605T234701Z`, `dm3`: command coverage passed for both bots. `/ goldenboy` passed, but `/ bro` failed stationary `40.5%` and low-speed `53.8%`.

### Expected Consequences

S3 remains focused on aim/movement separation. The next code should improve observability first, then decide whether a no-backpedal clamp, route-side preference, or another policy is justified.

### Revisit Conditions

Revisit if diagnostics show the split is unrelated to yaw delta/backward commands, or if command logging cannot capture enough route context without a more durable controller boundary.

---

## Decision

Run one tiny no-backpedal correction probe before expanding the controller.

### Date

2026-06-06

### Decision

Use S3e diagnostics to justify exactly one small S3f policy probe: keep mode `5` aim-independent movement, but prevent negative local `forwardmove` from becoming a sustained backpedal. Start on `dm3`, because S3e made both `dm3` bot rows fail low-speed while `frobodm2` passed.

This is not a final bunnyjump controller. It is a falsifiable correction test for the aim/move boundary.

### Alternatives Considered

- Treat yaw delta/backward ratio as the full root cause and build a larger aim-independent controller.
- Revert to route-yaw mode `4` because it passes the current gate.
- Tune sidemove/cadence again without addressing preserved combat yaw.
- Stop S3 and move to human comparison.

### Evidence

S3e runs with mode `5 --moveprobe-sidemove 200`:

- `20260606T000331Z`, `frobodm2`: both bots passed. `/ bro` had `22.7%` backward commands and yaw-delta p90 `110.9`; `/ goldenboy` had `14.0%` backward commands and yaw-delta p90 `91.8`.
- `20260606T000414Z`, `dm3`: both bots failed low-speed. `/ bro` had the strongest conflict signal with `41.3%` backward commands, yaw-delta p90 `154.7`, and `43.1%` yaw deltas above 90 degrees. `/ goldenboy` still failed low-speed despite only `14.0%` backward commands.

### Expected Consequences

If the no-backpedal probe improves `dm3` without breaking command coverage, the project learns that negative local forward commands are a real part of the aim-independent movement failure. If it does not improve, the project should stop tuning command values and inspect route state, obstruction, or a cleaner Frogbot movement-intent boundary.

### Revisit Conditions

Revisit if S3f fails the low-speed gate on `dm3`, if it harms combat/view behavior, or if diagnostics show most low-speed time occurs without backward commands.

---

## Decision

Bound no-backpedal command magnitudes before expanding movement policy.

### Date

2026-06-06

### Decision

Treat S3f mode `6` as a positive corrective probe, not as a final controller. The next S3 experiment should keep the forward-hemisphere/no-backpedal property but cap or normalize the resulting local command magnitudes before running more policy work.

### Alternatives Considered

- Promote mode `6` because it passed the current gate on both routed maps.
- Tune the sidemove magnitude again.
- Add cadence/stateful bunnyjump logic on top of mode `6`.
- Revert to route-yaw mode `4` because it has smaller command values.

### Evidence

S3f runs with mode `6 --moveprobe-sidemove 200`:

- `20260606T001705Z`, `dm3`: both bots passed the gate. `/ bro` low-speed improved from S3e `43.1%` to `38.3%`; `/ goldenboy` improved from `52.8%` to `24.4%`; both had `0.0%` backward commands.
- `20260606T001825Z`, `frobodm2`: both bots passed with `0.0%` backward commands.
- Command logs showed local side values around `1100` after folding backpedal into strafe.

### Expected Consequences

The next experiment can test whether the no-backpedal idea survives a more realistic command bound. If it does, S3 has a better candidate for aim-independent movement literacy. If it does not, the project should inspect route state, obstruction, or a cleaner movement-intent boundary instead of adding more controller state.

S3g is the last planned command-magnitude probe before a branch point. Continuing to ladder small command heuristics without route/obstruction evidence or an S4 human comparison set would risk optimizing the lab's own gates rather than player believability.

### Revisit Conditions

Revisit if a bounded no-backpedal variant fails both maps, if side-command caps reintroduce low-speed behavior, if command values are already being clamped downstream in a way that makes local magnitude tuning misleading, or if S3 produces another green gate without a clearer path to human-anchored plausibility.

---

## Decision

Branch from S3 command probes to S4 human comparison scaffolding.

### Date

2026-06-06

### Decision

Treat S3g mode `7` as the best current S3 movement-literacy candidate and stop adding command-magnitude heuristics until the lab has a human-demo comparison anchor.

The next goal is S4a: inventory human MVD candidates, parse at least one defensible human demo through the movement-metrics pipeline, and record whether a true DM2 comparison set is available or missing.

### Alternatives Considered

- Promote mode `7` as a believable movement controller.
- Add more mode `7` tuning, such as cadence, cap, or route-state variants.
- Inspect Frogbot route/obstruction state before human comparison.
- Jump directly to Milton or a learned movement controller.

### Evidence

S3g runs with mode `7 --moveprobe-sidemove 200`:

- `20260606T003718Z`, `dm3`: both bots passed. `/ bro` low-speed improved from S3f `38.3%` to `26.1%`; `/ goldenboy` improved from `24.4%` to `18.9%`. Both had `0.0%` backward commands and max horizontal command `824.5`.
- `20260606T003808Z`, `frobodm2`: both bots passed. `/ bro` low-speed improved from S3f `13.8%` to `5.5%`; `/ goldenboy` improved from `26.8%` to `2.7%`. Max horizontal command stayed near `824.6`.
- Local human/demo candidates exist under `C:\Users\benya\projects\quakeworld\data\quake-development\clients\xerialqw-bench\qw\matchinfo\demos`, but the visible filenames are `aerowalk`, `e1m2`, and trick demos rather than a clear DM2 comparison set.

### Expected Consequences

The lab should move from self-defined movement gates toward a human-anchored comparison. If no DM2 human set is present locally, S4a should record that gap explicitly and either use a smaller non-DM2 parser proof or prepare the acquisition criteria for a real DM2 set.

### Revisit Conditions

Revisit S3 command work only after human comparison shows a specific mismatch that mode `7` cannot explain, or if S4a cannot parse human MVDs with the current pipeline.

---

## Decision

Treat S4a as a parser proof, not as a human movement baseline.

### Date

2026-06-06

### Decision

Use `scripts/analyze_human_mvd.py` as the first S4 human-demo scaffold and keep its conclusion narrow. The local `xerialqw-bench` demo folder can be inventoried and parsed, but the first successful human run is an `aerowalk` duel, not a DM2 comparison set and not map-matched to S3g.

The next goal is S4b: select or acquire a real DM2 human comparison set, then run the same scaffold before making any S3g-vs-human plausibility claim.

### Alternatives Considered

- Compare S3g `dm3`/`frobodm2` metrics directly against the `aerowalk` duel.
- Treat the local `e1m2` 4on4 demo as enough human evidence.
- Resume S3 command tuning because S4a did not find DM2 locally.
- Download demos ad hoc from `hub.quakeworld.nu`.

### Evidence

S4a inventory:

- Five local demos found under `C:\Users\benya\projects\quakeworld\data\quake-development\clients\xerialqw-bench\qw\matchinfo\demos`.
- Inferred maps: `aerowalk`, `e1m2`, `ztricks`, and `ztricks2`.
- Filename-inferred `dm2` candidates: `0`; this is a filename-token heuristic, not a content parse of every local demo.

S4a parser proof:

- `1on1_reppie_vs_locust_aerowalk.mvd` parsed with `json=0`, `md=0`, `events=1`.
- Movement metrics produced active rows for `reppie` and `locust`, clamped to the parsed match duration.
- Compact evidence is committed under `experiments/human_comparison/evidence/`.

thevault data note:

- `thevault/quakeworld/mvds.md` says not to mass-download from `hub.quakeworld.nu`.
- It records existing larger corpora on `servexeri`, including `/mnt/usb-ssd/4on4-corpus/demos/` and `/mnt/usb-ssd/4on4-corpus/manifest.tsv`, which should be preferred for S4b inventory/selection.

### Expected Consequences

S4 can proceed without overclaiming. The project now has a repeatable human-demo parser path, but a missing DM2 set is the blocking data gap for a useful human anchor.

### Revisit Conditions

Revisit if a local or corpus DM2 candidate cannot be parsed by the scaffold, if the parser cannot identify enough active players in real 4on4 demos, or if a map-matched non-DM2 comparison becomes a better short-term anchor than DM2.

---

## Decision

Resolve map mismatch before judging S3g against human movement.

### Date

2026-06-06

### Decision

Treat S4b as successful true-DM2 human data selection, but not as a direct S3g comparison. The selected DM2 MVD gives S4 a real human DM2 anchor. However, S3g bot evidence is currently on `dm3` and `frobodm2`, so a S3g-vs-S4b realism claim would still be map-mismatched.

The next goal is S4c: produce the first map-matched human comparison for S3g, most likely by selecting and parsing one human `dm3` 4on4 demo from the same existing corpus.

### Alternatives Considered

- Compare S3g `dm3`/`frobodm2` directly against the new human `dm2` summary.
- Stop S4 after finding one DM2 human reference.
- Try to generate S3g DM2 bot evidence immediately despite no known Frogbot `dm2.bot` route file.
- Return to movement-command tuning before any map-matched human anchor exists.

### Evidence

S4b selected `4on4_blue_vs_red[dm2]20260228-0512.mvd` from the existing `servexeri` 4on4 corpus:

- Manifest rows: `6409`.
- DM2 rows: `1598`.
- `4on4_` DM2 rows: `1450`.
- Cleanish 4on4 DM2 rows after excluding `tmp` and missing files: `1171`.
- Selected file hash/size: `f8269d8139b129426b569eaf6b2be278964d740bd0365647f4410db74da76585`, `8624854` bytes.
- Parsed as `dm2` / `Claustrophobopolis`, duration `747424` ms, with eight active 4on4 movement rows clamped to the parsed match duration.

S3g evidence remains:

- `20260606T003718Z`, `dm3`.
- `20260606T003808Z`, `frobodm2`.

### Expected Consequences

The lab now has a true DM2 human reference and a reasoned next step. S4c should make the first direct map-matched human-vs-bot comparison possible before any claim that mode `7` is human-like.

### Revisit Conditions

Revisit if a DM2 Frogbot route appears, if a better server-native bot path can generate DM2 bot evidence quickly, or if a human `dm3` corpus sample fails to parse through the current scaffold.

---

## Decision

Treat S4c as the first same-map anchor, not as proof that S3g is human-like.

### Date

2026-06-06

### Decision

S4c resolves the immediate map mismatch by comparing S3g `dm3` against a human `dm3` 4on4 sample from the existing `servexeri` corpus.

The result should move the project forward to S5a Milton/elite reference-set inventory, not back into movement-command tuning. S3g remains the best current S3 movement-literacy candidate, but the human comparison shows it is not yet a believable movement model.

### Alternatives Considered

- Treat S3g as human-like because it passed the project-defined S3 gate.
- Tune mode `7` immediately against the S4c p95/average-speed gap.
- Collect more random human `dm3` demos before changing stages.
- Return to the DM2 path by adding/finding a Frogbot `dm2` route first.

### Evidence

S4c selected `4on4_blue_vs_red[dm3]20260426-0307.mvd` from the existing `servexeri` 4on4 corpus:

- Manifest rows: `6409`.
- Exact `[dm3]` rows: `1663`.
- `4on4_` exact `[dm3]` rows: `1629`.
- Cleanish 4on4 DM3 rows after excluding `tmp` and missing files: `1247`.
- Moderate-size 2026 cleanish 4on4 DM3 rows: `444`.
- Selected file hash/size: `6897a00a4c185751ac82c579c091437cc5b82701df14cc2178da4792924ad4fe`, `7632722` bytes.
- Parsed as `dm3` / `The Abandoned Base`, duration `729226` ms, with eight active 4on4 movement rows.

Same-map S3g comparison:

- Human average speed range: `235.4` to `333.5` qu/s; S3g bot range: `190.1` to `248.2`.
- Human p95 speed range: `390.5` to `515.2` qu/s; S3g bot range: `361.0` to `375.3`.
- `/ bro` is below the human average and p95 speed ranges and above the human airborne-proxy range.
- `/ goldenboy` is inside the human average-speed range but below the human p95 speed range.

### Expected Consequences

The lab now has enough S4 evidence to stop using self-defined movement gates as the only plausibility anchor. S5a should identify an elite or Milton-specific reference set, starting from existing local/corpus metadata and the no-hub-mass-download constraint.

S3 command/controller work should resume only when the human/elite reference set points to a concrete missing behavior, not simply because one bot metric is below a single human sample.

### Revisit Conditions

Revisit if S5a cannot identify any defensible elite or Milton reference candidates, if the current corpus lacks metadata sufficient for player-specific selection, or if Claude recommends expanding S4 with a small multi-demo `dm3` human range before moving to S5.

---

## Decision

Treat exact-player reference selection as feasible, but require a tiny aggregate before S6/S7.

### Date

2026-06-06

### Decision

S5a proves the project can select Milton and elite-player reference demos by metadata: Turso `player_games` / `games` rows can be cross-referenced against the existing `servexeri` 4on4 corpus manifest without mass-downloading from hub or parsing the full corpus.

The next goal is S5b: build a tiny Milton/elite reference aggregate on `dm3`. Do not tune S3g or begin S7 player-specific movement from a single Milton match.

### Alternatives Considered

- Start S6 route primitives immediately from the single S5a Milton parse.
- Start S7 player-specific movement because a Milton row is now available.
- Tune mode `7` directly against Milton's p95 speed.
- Use only generic S4c human ranges and skip elite/player-specific references.

### Evidence

S5a metadata inventory, latest 500 rows per target:

- `Milton`: `1240` total 4on4 rows; `96` latest-500 manifest hits; `23` `dm3` hits; `19` `dm2` hits.
- `carapace`: `712` total 4on4 rows; `68` latest-500 manifest hits; `14` `dm3` hits; `13` `dm2` hits.
- `_ ParadokS`: `1729` total 4on4 rows; `55` latest-500 manifest hits; `11` `dm3` hits; `10` `dm2` hits.
- `yeti`: `1518` total 4on4 rows; `60` latest-500 manifest hits; `17` `dm3` hits; `17` `dm2` hits.
- `ok98`: `1326` total 4on4 rows; `59` latest-500 manifest hits; `13` `dm3` hits; `19` `dm2` hits.

Selected Milton sample:

- `4on4_blue_vs_anza[dm3]20260602-2022.mvd`
- SHA-256: `9ca8f72b3afa95ba87830a83478c51bb9b3dd626b733190a4ca2d84b4d66490e`
- Turso row: `Milton`, team `anza`, `118/18`, `dm3`, `2026-06-02 20:42:16 +0000`.
- Parsed as `dm3` / `The Abandoned Base`, duration `1200013` ms.
- Milton movement row: avg `314.2`, p95 `535.0`, stationary `5.9%`, low-speed `12.4%`, airborne proxy `35.1%`, cadence `44.9`/min.

S3g comparison against the Milton-containing sample:

- Both S3g `dm3` bot rows are below the sample's human p95 range.
- `/ bro` is below the sample's average-speed range and above the low-speed and airborne-proxy ranges.
- `/ goldenboy` is below the sample's average-speed and p95 ranges, but inside low-speed range.

### Expected Consequences

S5b should create a small but less brittle reference range before S6 route primitives. A tiny aggregate can distinguish one-match noise from stable elite movement signals, and it can turn "S3g is too slow/low-p95" into a better-scoped route or movement-state diagnosis.

### Revisit Conditions

Revisit if a multi-demo aggregate cannot be produced quickly from the existing corpus, if exact player aliases make target selection unreliable, or if Claude recommends moving to S6 route-state instrumentation before expanding the reference set.

---

## Decision

Move from S5 reference anchoring to S6 route primitive/state diagnosis.

### Date

2026-06-06

### Decision

Treat S5b as sufficient for the first elite movement anchor: the lab now has a tiny exact-player `dm3` aggregate for Milton, carapace, and yeti. It is not a style model, but it is enough to show S3g's current movement gap is sustained high-speed behavior rather than only a command-emission problem.

The next goal is S6a: inspect route primitive/state behavior around the S3g `dm3` low-speed and low-p95 result before adding more movement command heuristics.

### Alternatives Considered

- Expand S5 into a larger elite reference corpus immediately.
- Start S7 player-specific movement from the Milton sample.
- Tune mode `7` forward/side/cadence values against the aggregate.
- Return to DM2 route acquisition before diagnosing the existing `dm3` gap.

### Evidence

S5b aggregate:

- Reference targets: `Milton`, `carapace`, `yeti`.
- Reference avg speed range: `282.8` to `314.2`; S3g bot range: `190.1` to `248.2`.
- Reference p95 speed range: `505.8` to `535.0`; S3g bot range: `361.0` to `375.3`.
- Reference low-speed range: `12.4%` to `19.6%`; S3g bot range: `18.9%` to `26.1%`.
- Reference airborne-proxy range: `34.2%` to `35.9%`; S3g bot range: `24.8%` to `44.2%`.

S3g interpretation:

- `/ bro` is below reference avg/p95/stationary ranges and above low-speed/air ranges.
- `/ goldenboy` is below reference avg/p95/stationary/air ranges and only within low-speed range.

### Expected Consequences

S6a should inspect route/segment state and movement traces around sustained low-speed periods. If the bot is losing speed because route primitives are too coarse, turning into geometry, or failing to carry velocity between route intents, the next controller work should target that route-state boundary rather than blindly increasing command magnitude.

### Revisit Conditions

Revisit if S6a cannot access route/segment state from the current artifacts or KTX patch point, if Claude recommends expanding the aggregate before route diagnosis, or if a simple trace analysis shows the gap is a measurement artifact rather than route behavior.

---

## Decision

Add route-state logging before changing the movement controller again.

### Date

2026-06-06

### Decision

S6a shows the current S3g `dm3` artifacts can locate low-speed windows and join sampled final command context, but they cannot attribute those windows to route node choice, next waypoint, target entity, obstruction, or route primitive state.

The next goal is S6b: add minimal KTX/Frogbot route-state logging around the same command boundary. Do not add mode `8`, increase command magnitude, or tune mode `7` until low-speed windows can be tagged with route context.

### Alternatives Considered

- Tune mode `7` against the S5b p95 gap.
- Add another movement command heuristic without route attribution.
- Expand the human/elite reference set again before inspecting route state.
- Treat `route_yaw` as sufficient route-state evidence.

### Evidence

S6a route-state diagnosis over run `20260606T003718Z`:

- `/ bro`: `7` low-speed windows of at least `250` ms; longest low contribution `1198` ms; all `5` analyzed top windows had strong sampled command context.
- `/ goldenboy`: `4` low-speed windows; longest low contribution `1078` ms; `3` of `4` analyzed windows had strong sampled command context.
- Overall: `8` of `9` analyzed top low-speed windows had average sampled horizontal command at or above `400`.
- Current artifacts expose route direction (`route_yaw`) but not route node, next waypoint, target entity, obstruction state, or route primitive identity.

### Expected Consequences

S6b should keep the patch small and diagnostic. It should log route state near `BotSetCommand()` or the adjacent Frogbot route-selection boundary, then rerun a short S3g-style `dm3` experiment and feed the result through `scripts/diagnose_route_state.py`.

The expected deliverable is attribution-ready evidence, not improved movement yet.

### Revisit Conditions

Revisit if Claude identifies an existing Frogbot route-state artifact already available in the MVD/parser output, if KTX route state cannot be logged safely at the current patch point, or if a rerun shows the sampled strong-command/low-speed relationship was an artifact of the short S3g run.

---

## Decision

Use route-state-tagged low-speed windows before controller tuning.

### Date

2026-06-06

### Decision

S6b successfully adds minimal route-state logging to sampled moveprobe command rows. The lab can now tag low-speed windows with linked marker, touch marker, goal entity, goal marker, path-state flags, bot-state flags, blocked state, and route `dir_speed`.

The next goal is S6c: decode and attribute repeated route-state patterns in the S6b low-speed windows before changing mode `7` or adding another movement-command heuristic.

### Alternatives Considered

- Treat S6b as enough evidence to start mode `8`.
- Increase mode `7` command magnitude to chase the S5b p95 gap.
- Add more route-state fields immediately before analyzing the fields already captured.
- Expand the human reference aggregate before understanding the S6b route-state windows.

### Evidence

S6b route-state diagnosis over run `20260606T031102Z`:

- Route-state capability is now available with keys `blocked`, `bot_state`, `dir_speed`, `goal_ed`, `goal_marker`, `linked_marker`, `path_state`, and `touch_marker`.
- The diagnosis reports command/sample clock overlap as `ok`, so the low-speed command joins are not currently explained by a timestamp-epoch mismatch.
- `/ bro`: avg `136.3`, p95 `359.6`, low-speed `52.1%`, `17` low-speed windows, and all `5` analyzed top windows had strong sampled command context.
- `/ goldenboy`: avg `285.5`, p95 `381.3`, low-speed `7.0%`, and no low-speed windows meeting the S6 threshold.
- Repeated `/ bro` `water.LG` windows were tagged with linked/goal marker `59`, path state `32768`, and `blocked=0`.

### Expected Consequences

S6c should convert route-state tags into an actionable explanation or next probe. If marker `59` / path state `32768` corresponds to a known route flag or water/air primitive, the next experiment should target that route primitive. If repeated windows do not explain the movement gap, S6c should decide what additional route context is missing rather than hiding uncertainty behind another command mode.

### Revisit Conditions

Revisit if Claude finds a bug in the S6b logging fields, if path state `32768` cannot be decoded from KTX flags, if a repeated S6b run does not reproduce any route-state pattern, or if the route-state tags show that current low-speed windows are measurement artifacts rather than movement/route behavior.

---

## Decision

Inspect water-path/swim intent before controller tuning.

### Date

2026-06-06

### Decision

S6c decodes the repeated `/ bro` `water.LG` low-speed pattern as `WATER_PATH` route behavior on linked/goal marker `59`, especially the repeated `.bot` edge `276->59 idx=[0]`. The samples do not show `STUCK_PATH` or blocked obstruction state, and the final sampled mode `7` command remains strong.

The next goal is S6d: inspect water-path/swim movement intent around `water.LG` before changing mode `7`. The missing context is waterlevel/watertype, swim arrow/upmove intent, velocity, and raw route `dir_move` behavior around the low native `dir_speed` samples.

### Alternatives Considered

- Add mode `8` to push through the water path with a new command heuristic.
- Increase mode `7` command magnitude or force nonzero upmove immediately.
- Treat `WATER_PATH` attribution as enough to skip to S7 player-specific movement.
- Repeat the same S6b run before decoding the missing water/swim fields.

### Evidence

S6c route-state attribution over run `20260606T031102Z`:

- `path_state=32768` decodes to `WATER_PATH`; `STUCK_PATH` is `524288`.
- KTX route calculation sets `WATER_PATH` when either endpoint marker is in water and uses `sv_maxwaterspeed` for route time.
- `dir_speed` is captured by `SetDirectionMove()` before `dir_move_` is normalized.
- The repeated `water.LG` group has `3` windows, linked/goal marker `59`, `blocked=0`, no `STUCK_PATH`, avg sampled command near `824`, and avg native `dir_speed=0.338`.
- The worst repeated windows use `276->59 idx=[0]` with native `dir_speed` averages `0.059` and `0.196`.

### Expected Consequences

S6d should either derive the missing water/swim context from existing artifacts or add a tiny diagnostic suffix to the command log. If water/swim intent explains the low-speed windows, the next controller work should target swimming/water-path handling rather than generic land movement or command magnitude.

### Revisit Conditions

Revisit if Claude finds a bug in the S6c flag decoding or `.bot` edge attribution, if another S6b-style run fails to reproduce the water-path pattern, or if waterlevel/swim/upmove evidence shows that the low native `dir_speed` samples are not actually water-path movement intent.

---

## Decision

Try a tiny water-edge upmove preservation probe before route-edge rewrites.

### Date

2026-06-06

### Decision

S6d reproduced the `/ bro` `water.LG` low-speed pattern on a fresh `dm3` mode `7` run and added water/swim context. The repeated water-path windows were shallow edge-water samples (`waterlevel` `[1]` or `[1, 2]`), not active deep swim: `swim_arrow=0`, no sampled `waterlevel > 2`, and emitted `upmove=0`.

The next goal is S6e: preserve native Frogbot vertical command intent only for water-edge samples where stock KTX would have allowed vertical movement (`waterlevel > 1`), while keeping mode `7`'s horizontal no-backpedal bounded behavior unchanged. This is a targeted diagnostic/controller probe, not a new general movement heuristic.

### Alternatives Considered

- Treat S6d as enough evidence to rewrite the `276->59` route edge.
- Add a generic mode `8` speed or command-magnitude change.
- Force a fixed nonzero upmove everywhere in mode `7`.
- Keep adding water fields before testing the most direct hypothesis.

### Evidence

S6d water-state attribution over run `20260606T041805Z`:

- `/ bro` had `12` low-speed windows; all `5` analyzed top windows were near `water.LG`.
- The analyzed `/ bro` windows had strong sampled horizontal commands near `824`, `WATER_PATH`, and `blocked=0`.
- Repeated water-path groups had no sampled deep-water state, no swim-arrow intent, and `0.0%` emitted upmove.
- Raw route `dir_move_z` was sometimes nonzero in the same windows; the current mode `7` code overwrites `direction[2]` from `k_fb_moveprobe_upmove`, defaulting to `0`.

### Expected Consequences

If S6e reduces or removes the repeated `water.LG` low-speed windows without hurting normal movement, water-edge vertical command preservation becomes the first targeted route-primitive fix candidate. If it does not, the next step should inspect `.bot` edge geometry around `276->59` and marker `59`, not tune upmove values.

### Revisit Conditions

Revisit if Claude finds that S6d's water-state fields are logged after a point that makes the inference invalid, if `waterlevel > 1` does not correspond to stock vertical command emission in KTX source, or if S6e changes movement outside the water-edge windows in a way that makes the comparison non-local.

---

## Decision

Stop upmove tuning after S6e and inspect route-edge geometry.

### Date

2026-06-06

### Decision

S6e tested the most direct water-edge hypothesis by preserving native pre-probe `direction[2]` only when `waterlevel > 1` in mode `7`. The run did emit nonzero upmove in some water-edge samples, but it did not remove the repeated `water.LG` / `276->59` WATER_PATH low-speed pattern; the pattern appeared on `/ goldenboy`, and both bots had worse low-speed ratios in the short sample.

The next goal is S6f: inspect the `dm3.bot` route-edge geometry around `276->59` and marker `59` without adding another controller change. This is a route-data/diagnosis audit, not another movement-command heuristic.

### Alternatives Considered

- Force a fixed nonzero upmove in water-edge windows.
- Preserve native upmove for all waterlevels, including shallow `waterlevel == 1`.
- Increase mode `7` horizontal command magnitude to push through the water edge.
- Abandon S6 immediately and jump to S7 player-specific movement.

### Evidence

S6e run `20260606T044000Z`:

- `/ bro`: avg `153.0`, p95 `377.7`, low-speed `46.3%`.
- `/ goldenboy`: avg `152.7`, p95 `346.7`, low-speed `39.3%`.
- Repeated `/ goldenboy` `water.LG` group: `2` windows, linked/goal marker `59`, `.bot` edge `276->59 idx=[0]`, waterlevels `[1, 2]`, `blocked=0`, avg command `823.9`, and low native dir ratio `80.0%`.
- S6e emitted nonzero upmove in `13.3%` of that grouped sample, but the low-speed WATER_PATH pattern remained.

### Expected Consequences

S6f should determine whether marker positions, edge direction, or explicit path commands around `276->59` explain the low native route-vector magnitude. If no tiny route-data explanation appears, stop spending S6 effort on the water edge and return to the larger movement-realism gap: land-speed/bunnyhop behavior and stronger human reference evidence.

### Revisit Conditions

Revisit if Claude finds an implementation bug in the S6e native-upmove preservation, if a repeat run contradicts the negative result, or if route-edge geometry shows that upmove preservation should have been applied at a different point in the stock command pipeline.

---

## Decision

Close the S6 water-edge branch and move to S7 measurement scaffolding.

### Date

2026-06-06

### Decision

S6f inspected `dm3.bot` edge `276->59` and marker `59` with static route-file geometry plus S6d/S6e attribution samples. The edge exists, the reciprocal edge exists, and there is no explicit route-file flag to remove. Marker `59` has a static origin, but marker `276` does not, so the route file cannot provide a precise edge vector or coordinate-level correction.

The next goal is S7a: seed player-specific movement signatures from the existing exact-player `dm3` references (`Milton`, `carapace`, `yeti`) before any player-specific movement controller work. This advances toward S7 without pretending that the headline land-speed/bunnyhop gap is solved.

### Alternatives Considered

- Edit `dm3.bot` around `276->59` despite missing static source geometry.
- Add another mode `7` water-upmove or command-magnitude tweak.
- Continue S6 route-neighborhood archaeology around marker `59`.
- Jump directly to a player-specific controller.

### Evidence

S6f route-edge geometry evidence:

- `276->59` is defined as path index `0` at line `1837`.
- `59->276` is defined as path index `0` at line `549`.
- Marker `59` has static origin `[1329.0, -378.0, -24.0]`, zone `17`, goal `5`.
- Marker `276` has zone `17` but no `CreateMarker` origin.
- The focus edge has no explicit `SetMarkerPathFlags`; `WATER_PATH` is runtime route-state classification.
- S6d/S6e attribution includes `30` unique focus-edge samples with `WATER_PATH`, `blocked=0`, and `86.7%` low native `dir_speed`.

### Expected Consequences

S7a should produce an auditable, small player-specific movement-signature artifact from existing exact-player data. It should not implement a player-specific movement controller yet. Its job is to determine which movement features are player-specific enough to be useful and which are still dominated by the generic bot-vs-human land-speed gap.

### Revisit Conditions

Revisit if Claude identifies a route-file parsing error, if KTX source shows a reliable way to recover runtime marker `276` geometry from static artifacts, or if S7a reveals that player-specific signatures are too thin without broadening the human reference corpus first.

---

## Decision

Broaden exact-player references before player-specific controller work.

### Date

2026-06-06

### Decision

S7a built the first exact-player movement-signature scaffold from the existing S5b `Milton`/`carapace`/`yeti` `dm3` aggregate. The scaffold successfully separates broad human-vs-bot movement gaps from candidate style axes, but it also triggers the stop condition: the current set is one demo per player.

The next goal is S7b: broaden exact-player movement references before any player-specific movement controller work. Start with repeated `dm3` samples for the same targets where available, then rerun the S7a signature scaffold to check which axes are stable player signals and which are one-match noise or generic S3g land-speed deficit.

### Alternatives Considered

- Start tuning mode `7` against Milton's avg/p95 movement row.
- Build a Milton-specific controller or parameter profile from one Milton match.
- Treat low-speed ratio or cadence as stable player-style labels now.
- Drop S7 and return immediately to generic land-speed/bunnyhop controller work.

### Evidence

S7a signature scaffold:

- Avg speed: exact-player range `282.8` to `314.2`; S3g bot range `190.1` to `248.2`; best-bot gap to reference minimum `34.6` qu/s.
- P95 speed: exact-player range `505.8` to `535.0`; S3g bot range `361.0` to `375.3`; best-bot gap to reference minimum `130.5` qu/s.
- Low-speed ratio: exact-player range `12.4%` to `19.6%`; mixed S3g relation, so it is only a thin candidate player-style axis.
- Jump cadence: exact-player range `44.0` to `48.6`/min; no committed S3g comparison metric, so it is reference-only for now.
- Stop condition: only three single-demo exact-player rows.

### Expected Consequences

S7b should turn the current "candidate axes" into a stability check. If repeated samples preserve per-player differences, S7 can start designing player-style targets. If the axes move around heavily, the project should broaden the human reference corpus or return to generic movement-realism work before attempting player-specific control.

### Revisit Conditions

Revisit if Claude finds that the S7a axis classification hides an important metric, if existing artifacts already contain enough repeated exact-player rows to avoid a new selection step, or if S7b cannot find repeated same-map samples for the target players.

---

## Decision

Make repeated candidate axes bot-comparable before player-specific control.

### Date

2026-06-06

### Decision

S7b broadened the exact-player `dm3` reference set from one demo per target to two demos per target for `Milton`, `carapace`, and `yeti`. This is enough to start checking repeated-player stability, but not enough to build player-specific movement control.

The next goal is S7c: make the surviving repeated axes bot-comparable and controller-relevant. In practice, that means adding bot-side cadence/tempo metrics to the S3g summaries before treating cadence or low-speed behavior as player-style targets.

### Alternatives Considered

- Start a Milton/carapace/yeti-specific controller profile from the six-row aggregate.
- Treat low-speed or airborne proxy as stable enough because they still show cross-player spread.
- Ignore cadence because it is not currently in the S3g summary.
- Abandon S7 and immediately return to generic land-speed/bunnyhop controller work.

### Evidence

S7b repeated reference evidence:

- New selected demos: `Milton` `4on4_blue_vs_red[dm3]20260601-1914.mvd`, `carapace` `4on4_-s-_vs_]sr[[dm3]20260520-2032.mvd`, and `yeti` `4on4_red_vs_blue[dm3]20260528-2109.mvd`.
- Exact-player avg range: `282.8` to `314.2`; S3g bot avg range: `190.1` to `248.2`.
- Exact-player p95 range: `505.8` to `535.0`; S3g bot p95 range: `361.0` to `375.3`.
- Low-speed repeated stability: between-player mean spread `4.3%`, max within-player spread `3.2%`, separation ratio `1.34`, classified as mixed/overlapping.
- Airborne repeated stability: between-player mean spread `4.7%`, max within-player spread `6.0%`, separation ratio `0.78`, classified as mixed/overlapping.
- Cadence repeated stability: between-player mean spread `7.6`/min, max within-player spread `3.7`/min, separation ratio `2.06`, classified as a repeated reference-only candidate axis.

### Expected Consequences

The intended S7c branch was to either turn cadence/tempo into a comparable bot-vs-human signal or prove that the current S3g summaries were too incomplete for player-style decisions. S7c later fulfilled the comparable-signal path from existing artifacts; player-specific movement control remains blocked until S7d decides the smallest evidence-producing use of that signal.

### Revisit Conditions

Revisit if Claude finds a bug in S7b stability classification, if bot-side cadence already exists in committed evidence and was missed, or if broader reference rows contradict cadence as the strongest repeated axis.

---

## Decision

Treat bot-comparable cadence as an S7d design input, not a controller authorization.

### Date

2026-06-06

### Decision

S7c proved that the repeated cadence axis can be compared against S3g bots using existing committed artifacts. It should be carried forward as a diagnostic/player-style candidate, but it is not enough by itself to start broad player-specific movement control.

The next goal is S7d: decide the smallest evidence-producing action for bot-comparable repeated axes. Candidate paths are to keep cadence as a diagnostic target, broaden exact-player and bot samples first, or design a tiny controller probe that tests cadence without hiding the unresolved land-speed gap.

### Alternatives Considered

- Start a Milton/carapace/yeti-specific movement controller now that cadence is bot-comparable.
- Treat `/ goldenboy` being inside the human cadence range as evidence that cadence is solved.
- Treat `/ bro` being far above the human cadence range as proof that cadence alone explains the movement gap.
- Drop cadence and return immediately to generic avg/p95 land-speed optimization.

### Evidence

S7c bot-comparable cadence evidence:

- Exact-player `dm3` cadence range: `40.4` to `51.0`/min.
- S3g `/ bro` cadence: `91.7`/min, above the repeated human range.
- S3g `/ goldenboy` cadence: `43.3`/min, within the repeated human range.
- Repeated-player cadence stability: between-player mean spread `7.6`/min, max within-player spread `3.7`/min, separation ratio `2.06`.
- Cadence classification changed from `repeated_reference_only_candidate_axis` to `repeated_candidate_style_axis`.
- Avg and p95 still remain generic land-speed gaps: reference avg `282.8` to `314.2` versus S3g `190.1` to `248.2`; reference p95 `505.8` to `535.0` versus S3g `361.0` to `375.3`.

### Expected Consequences

S7d should make a product/experiment decision before adding controller code. A cadence-specific probe is acceptable only if it is tiny, separately measured, and cannot obscure the broader high-speed movement deficit. If S7d cannot justify such a probe, broaden samples or return to generic movement-realism work.

### Revisit Conditions

Revisit if Claude finds a cadence propagation or classification bug, if additional bot rows show the current two-bot relation is misleading, or if richer movement metrics reveal a better repeated player-style axis than cadence.

---

## Decision

Keep cadence diagnostic after S7d normalization; do not start cadence control yet.

### Date

2026-06-06

### Decision

S7d re-normalized bot-comparable cadence by non-stationary time, non-low-speed time, and airborne-proxy time using the committed S7c aggregate. The result does not justify a cadence controller yet.

Cadence remains useful as a diagnostic/player-style candidate, but it should not become a controller target until the project broadens bot evidence or separates cadence from airborne-proxy segmentation and the unresolved land-speed gap.

The next goal is S7e: broaden or dissect cadence evidence before controller work. The smallest useful path is to add more bot rows and/or inspect airborne-proxy segmentation from existing artifacts before changing KTX/Frogbot movement behavior.

### Alternatives Considered

- Start a tiny cadence controller because `/ goldenboy` is within the raw S7c cadence range.
- Treat `/ bro` as a simple over-cadence bug and lower jump frequency directly.
- Drop cadence and return immediately to generic land-speed optimization.
- Broaden exact-player references again before understanding the bot-side airborne-proxy relation.

### Evidence

S7d cadence-normalization evidence:

- Existing `jump_cadence_per_min` is already active-row normalized (`airborne_proxy_count / active_time_s * 60`).
- Non-stationary cadence: exact-player `44.2` to `55.6`/min; S3g `/ bro` `92.1`/min; S3g `/ goldenboy` `44.4`/min.
- Non-low-speed cadence: exact-player `48.7` to `61.3`/min; S3g `/ bro` `124.1`/min; S3g `/ goldenboy` `53.3`/min.
- Airborne-proxy cadence: exact-player `128.0` to `143.1`/min; S3g `/ bro` `207.6`/min; S3g `/ goldenboy` `174.4`/min.
- Airborne-proxy normalization puts both S3g bots above the exact-player range, while avg/p95 remain generic land-speed gaps.

### Expected Consequences

S7 should remain evidence-first. If S7e shows cadence is stable across more bot rows and separable from airborne-proxy segmentation, a tiny cadence probe may become defensible. If not, cadence should remain a diagnostic axis while movement-realism work returns to the broader land-speed/air-rhythm deficit.

### Revisit Conditions

Revisit if Code Sentinel finds a normalization bug, if broader bot samples show the current S3g bot relation is misleading, or if a better grounded jump/airborne metric replaces the current position-derived airborne proxy.

---

## Decision

Keep cadence diagnostic after S7e broadening; do not start cadence control yet.

### Date

2026-06-06

### Decision

S7e broadened the bot cadence evidence from two S3g `dm3` rows to six existing unchanged mode-7 `dm3` rows. The broader evidence still does not justify a cadence controller.

Cadence remains a useful diagnostic axis, but controller work should wait until raw airborne-proxy segment distributions are inspected or the project intentionally pivots back to the larger land-speed gap.

The next goal is S7f: inspect raw airborne-proxy segment distributions, or pivot back to the larger land-speed gap, before any cadence controller probe.

### Alternatives Considered

- Treat the broadened `/ bro` high cadence rows as authorization to lower cadence directly.
- Treat the low `/ goldenboy` raw cadence rows as evidence that cadence is not relevant.
- Include S6e `20260606T044000Z` as another mode-7 bot row despite its water-edge behavior change.
- Start a tiny cadence controller before inspecting the airborne-proxy segmentation.

### Evidence

S7e broadened cadence evidence:

- Included unchanged mode-7 bot runs: `20260606T003718Z`, `20260606T031102Z`, and `20260606T041805Z`.
- Excluded S6e `20260606T044000Z` because it changed water-edge vertical command behavior.
- Active cadence: exact-player `40.4` to `51.0`/min; broadened bot `18.5` to `138.7`/min; relation mixed.
- Non-stationary cadence: exact-player `44.2` to `55.6`/min; broadened bot `18.6` to `146.6`/min; relation mixed.
- Non-low-speed cadence: exact-player `48.7` to `61.3`/min; broadened bot `20.2` to `289.5`/min; relation mixed.
- Airborne-proxy cadence: exact-player `128.0` to `143.1`/min; broadened bot `164.1` to `274.1`/min; all bot rows above range.
- Bot p95 speed remains below exact-player p95 ranges, preserving the larger land-speed gap.

### Expected Consequences

S7 should not spend a branch tuning cadence until the position-derived airborne-proxy signal is understood. If S7f shows the proxy is over-segmenting bot air rhythm, fix the metric or segment interpretation before controller work. If S7f shows cadence is only a symptom, pivot back to land-speed/bunnyhop realism.

### Revisit Conditions

Revisit if Code Sentinel finds the broadened bot-run selection is unsafe, if raw segment inspection shows airborne-proxy cadence is a reliable grounded jump-rhythm proxy, or if new bot rows contradict the all-above airborne-proxy relation.

---

## Decision

Pivot from cadence control to air-rhythm and land-speed evidence after S7f.

### Date

2026-06-06

### Decision

S7f inspected raw airborne-proxy segment distributions from existing exact-player and unchanged mode-7 bot artifacts. The result does not justify a cadence controller.

Cadence remains diagnostic. The next stage should characterize the land-speed gap around route and air segments before another controller probe.

### Alternatives Considered

- Start a cadence controller because all broadened bot rows are above the airborne-proxy cadence range.
- Treat the airborne-proxy cadence gap as a metric bug and drop cadence entirely.
- Rerun KTX immediately with another controller tweak.
- Keep broadening cadence rows without inspecting the underlying air segment shape.

### Evidence

S7f raw airborne-proxy segment evidence:

- Player-median air duration: exact-player `325.0` ms, bot `217.2` ms, bot/reference p50 ratio `0.668`.
- Player-median air Z range: exact-player `43.8` qu, bot `11.5` qu, ratio `0.264`.
- Player-median air speed: exact-player `431.8` qu/s, bot `114.4` qu/s, ratio `0.265`.
- Raw active average speed ratio is `0.735`, preserving the broader land-speed deficit.

### Expected Consequences

The next PR should not tune jump cadence directly. It should use the existing evidence to characterize where the bot speed deficit appears around route and air segments, then decide whether a controller probe should target speed production, air rhythm, or another route/movement primitive.

### Revisit Conditions

Revisit if Code Sentinel finds a raw segment extraction bug, if a grounded-state or usercmd-aware metric replaces the current position-derived airborne proxy, or if broader bot rows produce human-scale airborne segments while still showing cadence problems.

---

## Decision

Target air-transition speed production or a narrow route primitive before another cadence/controller probe.

### Date

2026-06-06

### Decision

S7g characterized the S7f land-speed gap by segment context. The result says the next controller decision should not treat speed as a generic scalar and should not return to cadence tuning.

The next stage should choose between two concrete movement-realism targets:

- air-transition horizontal speed production, because bot pre-air, airborne, and post-air p50 speeds are far below exact-player reference;
- a narrow route primitive such as `WATER_PATH` low-dir-speed recovery, because sampled bot route `WATER_PATH` contexts are extremely slow.

### Alternatives Considered

- Start a generic speed controller because all accepted bot segments are slower on aggregate.
- Tune cadence directly despite S7d/S7e/S7f evidence that cadence is diagnostic.
- Treat route `WATER_PATH` as the only target and ignore the broader air-transition speed gap.
- Rerun the lab before extracting context from existing artifacts.

### Evidence

S7g land-speed context:

- All accepted segment p50: exact-player `334.0` qu/s, bot `222.0` qu/s, bot/reference ratio `0.665`.
- Airborne-proxy segment p50: exact-player `433.8` qu/s, bot `122.6` qu/s, ratio `0.283`.
- Non-airborne segment p50: exact-player `320.0` qu/s, bot `312.1` qu/s, ratio `0.975`.
- Pre-air window p50: exact-player `418.0` qu/s, bot `207.1` qu/s, ratio `0.495`.
- Post-air window p50: exact-player `365.7` qu/s, bot `184.5` qu/s, ratio `0.505`.
- Route `WATER_PATH` bot p50 speed: `95.3` qu/s.

### Expected Consequences

The next PR should decide the first probe target before changing movement commands. A controller probe that only increases cadence or all-segment speed risks improving the wrong proxy. A better next step is to choose a targetable context: air-transition acceleration/speed preservation or a narrow route primitive recovery.

### Revisit Conditions

Revisit if Code Sentinel finds a segment-bucketing bug, if route-state command sampling is too sparse to trust, or if broader bot rows show non-airborne speed is not actually human-scale.

---

## Decision

Choose air-transition horizontal speed production as the first controller probe target.

### Date

2026-06-06

### Decision

S7h chooses `air_transition_horizontal_speed` as the first controller-probe target and defers `water_path_low_dir_speed_recovery` to a guardrail/later narrow route target.

The reason is evidence priority: air-transition speed is human-comparable across the exact-player and bot row set and is clearly context-specific, while `WATER_PATH` is very slow but bot-only and route-diagnostic.

### Alternatives Considered

- Start a generic all-segment speed probe.
- Start a cadence controller despite S7d/S7e/S7f evidence that cadence is diagnostic.
- Start with a narrow `WATER_PATH` recovery probe.
- Rerun the lab before making a target decision from committed S7g context.

### Evidence

S7h controller-target evidence:

- Air-transition candidate: pre-air ratio `0.495`, airborne ratio `0.283`, post-air ratio `0.505`, non-airborne ratio `0.975`.
- Each air-transition bucket has six reference player p50s and six bot player p50s.
- `WATER_PATH` candidate: bot p50 speed `95.3` qu/s, low-dir-speed p50 `141.0` qu/s, and `3,674` route-state matched bot segments.
- `WATER_PATH` has no exact-player reference bucket and only `2` bot rows contributing `WATER_PATH` player p50s.

### Expected Consequences

S7i should design a tiny air-transition horizontal-speed probe. The probe must keep cadence diagnostic, retain route diagnostics, and reject all-segment speed gains if pre-air/airborne/post-air buckets or `WATER_PATH` context get worse.

### Revisit Conditions

Revisit if Code Sentinel finds the S7h target scoring unsafe, if the S7g route-state caveat becomes blocking, or if an S7i probe cannot be designed without hiding combat/route regressions.

---

## Decision

Design a tiny air-transition horizontal-speed probe before changing controller behavior.

### Date

2026-06-06

### Decision

S7i defines `s7i-mode8-air-transition-horizontal-speed` as a design-only probe contract. It does not implement the controller change. The next branch may implement a temporary mode-8 or mode-7-variant probe only if it preserves the contract:

- start from mode `7`,
- change horizontal command budget only during takeoff/air-transition windows,
- preserve combat view yaw, route projection, no-backpedal folding, command bounding outside the transition window, jump-button policy, route logging, water logging, and cadence reporting,
- keep `WATER_PATH` as a guardrail.

### Alternatives Considered

- Implement mode `8` immediately without a machine-readable contract.
- Chase all-segment speed directly.
- Add cadence or jump timing logic.
- Start with a route-only `WATER_PATH` primitive.

### Evidence

S7i consumes committed S7g/S7h/S7e evidence:

- Air-transition target selected by S7h.
- Pre-air ratio `0.495`, airborne ratio `0.283`, post-air ratio `0.505`.
- Non-airborne ratio `0.975`, so generic non-airborne speed is already near reference.
- `WATER_PATH` bot p50 `95.279` qu/s across `2` bot rows.
- Airborne-proxy cadence still diagnostic: every broadened bot row is above reference range.

### Expected Consequences

S7j should implement and run only the tiny air-transition probe. It must reject all-segment speed gains if air-transition buckets do not improve, if non-airborne or `WATER_PATH` context regresses, or if cadence/route reporting disappears.

### Revisit Conditions

Revisit if Code Sentinel finds the S7i contract too broad, if a mode-8 implementation cannot preserve mode-7 behavior outside transition windows, or if post-probe diagnostics cannot report the required buckets.

---

## Decision

Reject the corrected mode-8 air-transition probe under S7i stop conditions.

### Date

2026-06-06

### Decision

S7j implements and runs the S7i-constrained mode-8 probe. Claude review caught that the first implementation passed a hardcoded `true` into the transition gate, making every grounded frame transition-active. After fixing the gate to use pre-probe jump intent, the probe was rerun as `20260606T163907Z` and `20260606T164610Z`.

The combined corrected evidence rejects mode `8` under the S7i contract. All accepted segment speed improved only slightly and `WATER_PATH` stayed barely above baseline where present, but the intended pre-air and airborne-proxy buckets regressed and non-airborne speed fell below tolerance. Keep the air-transition target alive, but move the roadmap to S7k diagnosis of failed bucket and command/probe activation context before another command-policy change.

### Alternatives Considered

- Promote mode `8` because one corrected run improved multiple speed buckets.
- Increase transition scale or window and rerun immediately.
- Switch directly to a `WATER_PATH` route primitive probe.
- Treat the small all-segment and `WATER_PATH` gains as success despite target-bucket regressions.

### Evidence

S7j comparison against S7g/S7i baselines:

- Probe activation rows: `546` sampled rows, `110` transition-active, active ratio `0.201`.
- Pre-air p50: `207.1 -> 149.7` qu/s.
- Airborne-proxy p50: `122.6 -> 100.4` qu/s.
- Post-air p50: `184.5 -> 179.6` qu/s.
- All accepted segment p50: `222.0 -> 230.0` qu/s.
- Non-airborne p50: `312.1 -> 286.3` qu/s, failing the S7i `0.95` tolerance.
- Route low-dir-speed p50: `141.0 -> 201.2` qu/s.
- Route `WATER_PATH` p50: `95.3 -> 96.2` qu/s from one S7j bot row.

### Expected Consequences

S7k should not add another movement mode. It should inspect the failed air-transition and non-airborne buckets, correlate them with command/probe activation context, then decide whether another probe is justified.

### Revisit Conditions

Revisit if Code Sentinel finds the S7j comparison flawed, if S7k shows the bucket regressions are caused by a measurement artifact, or if a later probe improves air-transition buckets while preserving non-airborne and route context.

---

## Decision

Keep KTX/Frogbots for one narrower context-gated probe before considering a from-scratch stack.

### Date

2026-06-06

### Decision

S7k diagnoses the corrected S7j failed buckets and keeps the Frogbots-vs-from-scratch decision open. The project should continue with KTX/Frogbots for the next bounded stage, but the next probe must be narrower and context-gated.

Decision gates:

- Continue with KTX/Frogbots while the server-native shell still supports spawning, combat participation, command overrides, command diagnostics, and MVD evidence without rebuilding physics/collision/combat.
- Continue with KTX/Frogbots if a tiny movement primitive can improve a target human-comparable bucket while preserving non-target guardrails and route/cadence diagnostics.
- Consider abandoning or rebuilding if multiple bounded primitives cannot improve target buckets without unattributable regressions, or if Frogbot route/map state is too opaque or too static to separate controller failures from map-understanding failures.

### Alternatives Considered

- Abandon Frogbots now because S7j rejected mode `8`.
- Treat S7j as a pure water problem and pivot directly to `WATER_PATH`.
- Treat S7j as a pure controller problem and immediately increase transition scale/window.
- Build from scratch before proving whether KTX/Frogbots can expose and gate the needed movement contexts.

### Evidence

S7k diagnosis:

- Pre-air p50: `207.1 -> 149.7` qu/s, classified as `mixed_controller_and_route_context`.
- Airborne-proxy p50: `122.6 -> 100.4` qu/s, classified as `mixed_controller_and_route_context`.
- Non-airborne p50: `312.1 -> 286.3` qu/s, classified as `route_or_map_context_guardrail_contamination`.
- `/ goldenboy` run `20260606T164610Z` was the clearest route-context contaminator: non-airborne p50 `100.8` qu/s, low-dir ratio `0.626`, and `WATER_PATH` ratio `0.614`.
- First corrected-run rows still show air-transition weakness without `WATER_PATH`, so water does not explain the whole failure.

### Expected Consequences

S7l should design a context-gated air-transition probe before another lab rerun. It should either exclude low-dir-speed/`WATER_PATH` contexts from the treatment window or treat those contexts as hard stop-condition slices, while preserving cadence and route diagnostics.

### Revisit Conditions

Revisit the Frogbots-vs-from-scratch choice if S7l/S7m show that context-gated controller probes still cannot improve air-transition buckets without broad regressions, or if the route/map state needed to gate those probes cannot be observed or controlled inside KTX/Frogbots.

---

## Decision

Proceed to one context-gated air-transition probe before abandoning Frogbots.

### Date

2026-06-06

### Decision

S7l turns the S7k failed-bucket diagnosis into a stricter probe contract. It finds enough clean air-transition evidence to justify one more bounded KTX/Frogbots controller probe, but route-dirty contexts must remain guardrails and cannot count as success evidence.

Clean target slices:

- Pre-air: `2` player rows, `326` segments, p50 `229.0` qu/s.
- Airborne-proxy: `3` player rows, `844` segments, p50 `101.8` qu/s.

Route-dirty guardrail slices:

- Pre-air: `1` player row, `1,445` segments.
- Airborne-proxy: `1` player row, `1,179` segments.
- Non-airborne: `1` player row, `766` segments.

The next runtime probe must gate on live Frogbot route/water state, not offline labels. It may change horizontal command budget only in clean transition context and must preserve route, water, probe-activation, and cadence diagnostics.

### Alternatives Considered

- Abandon Frogbots after S7j because the first air-transition probe failed.
- Treat the S7j failure as a water-only or route-only problem.
- Increase the mode-8 transition scale/window without separating clean and dirty contexts.
- Start a route-primitive fix before proving whether clean air-transition slices can improve.

### Evidence

S7l design artifact:

- `experiments/human_comparison/evidence/context-gated-probe-design-s7l-dm3.json`
- `experiments/human_comparison/evidence/context-gated-probe-design-s7l-dm3.md`

The artifact records context-gate rules, allowed/forbidden follow-up changes, stop conditions, and the Frogbots-vs-from-scratch gates.

### Expected Consequences

S7m should implement and run a temporary context-gated air-transition probe. It should compare clean pre-air/airborne slices separately from route-dirty slices. All-segment speed gains remain insufficient. Missing route/cadence/probe diagnostics make the result inconclusive.

### Revisit Conditions

Revisit a from-scratch stack if the S7m clean-context probe still cannot improve target air-transition buckets under strong command coverage, or if KTX/Frogbots cannot expose the live state needed to gate the probe without corrupting server-native behavior.

---

## Decision

Use first-person QWD POV demos as the supervised action-label source.

### Date

2026-06-06

### Decision

Use `.qwd` POV demos for exact human action labels when such demos are available. Keep normal MVDs as the movement-state/evaluation source rather than treating them as usercmd data.

The Phase 1 extractor emits `komodobots.qwd_usercmd.v1` rows containing `time_s`, `msec`, `view_angles`, `forwardmove`, `sidemove`, `upmove`, `buttons`, and `impulse`. Phase 2 state/action pairing is deferred until the QWD `dem_read` client-state path is source-checked and parsed safely.

### Alternatives Considered

- Continue treating all human demo learning as inverse control only.
- Try to recover exact player input from server-side MVDs.
- Jump directly to a QWD state/action dataset before validating the raw action stream.
- Train on POV actions before checking client/build layout compatibility.

### Evidence

Source checks:

- ezQuake `src/cl_demo.c::CL_WriteDemoCmd()` writes a raw `usercmd_t` plus viewangles for `dem_cmd`.
- ezQuake `src/sv_ents.c` confirms normal server broadcasts/MVD paths do not preserve movement intent as exact usercmd labels.
- `src/qwprot/src/protocol.h::usercmd_t` validates the current `24` byte layout used by the extractor.

Validation:

- `python -m unittest tests.test_qwd_usercmd -v` passed `6` focused tests.
- `dm2_big_to_gl.qwd` parsed cleanly: `50112/50112` bytes read, `375` commands, no warnings.
- `dm2_bunny_to_gl.qwd` parsed cleanly with `--strict-plausibility`: `162582/162582` bytes read, `1537` commands, no warnings, plausible movement/action ranges.

### Expected Consequences

Komodobots now has a path to supervised movement actions for player POV data without rebuilding the engine or pretending MVDs contain key presses. This can eventually support behavioral cloning or policy imitation experiments, but only after Phase 2 safely pairs actions with observed state.

The current Frogbots decision path still uses KTX/Frogbots as the engine-native substrate. QWD usercmd extraction is a data-pipeline addition, not proof that a learned controller should replace the current bounded Frogbot probes immediately.

### Revisit Conditions

Revisit if additional POV QWDs from older/client-diverse builds fail clean EOF or plausibility checks, if the `usercmd_t` raw-struct layout differs by build, or if QWD `dem_read` state parsing cannot be made reliable enough to align observations with actions.

---

## Decision

Use QWD state/action pairing as a Frogbots-vs-from-scratch decision input, not as proof of Frogbot replay.

### Date

2026-06-06

### Decision

Treat the QWD trajectory route applicability probe as a successful data bridge: for matching POV demos, Komodobots can pair exact human commands with same-frame self-player trajectory and downsample that trajectory into route-like waypoints.

Do not treat this as a completed Frogbot route importer or controller. The next decision gate is whether one clean extracted route can be mapped against `dm3.bot` or executed in a controlled KTX/Frogbot server-loop probe without losing route, water, combat, or air-transition guardrails.

### Alternatives Considered

- Abandon Frogbots despite QWDs now providing human action/state data.
- Treat waypoint extraction as enough to claim Frogbot applicability.
- Jump directly to supervised movement training without checking route semantics or server-loop execution.
- Keep QWDs only as offline analysis and continue controller probes without using exact human actions.

### Evidence

QWD route applicability probe on local `dm3_*.qwd` trick demos:

- `29` of `29` demos produced exact command/state frame matches.
- Total paired frames: `22,749`.
- Paired coverage min/p50: `1.000` / `1.000`.
- `29` route candidates produced at `64` qu waypoint spacing.
- `26` of `29` demos had no real continuity split after duplicate-tick handling.
- Water-heavy demos stayed usable once the parser accepted only anchored self-player `svc_playerinfo` instead of naive byte-scan candidates.

### Expected Consequences

Before abandoning KTX/Frogbots, run one more bounded evidence step: pick a clean route candidate such as `dm3_sng_shortcut.qwd`, compare extracted waypoints against the current `dm3.bot` marker graph, and decide whether route-following, command-imitation, or a hybrid waypoint/controller probe is the smallest server-loop test.

### Revisit Conditions

Revisit the from-scratch option if the extracted QWD trajectory cannot be mapped to Frogbot route context, if KTX/Frogbots cannot expose or control the needed route execution state, or if a server-loop replay/controller probe cannot preserve non-target guardrails.

---

## Decision

Use a hybrid waypoint/controller probe for the first QWD-derived SNG shortcut test.

### Date

2026-06-06

### Decision

Do not start by mutating `dm3.bot` or asking Frogbots to follow the nearest-marker sequence as a normal route. The first QWD-derived SNG shortcut test should be a temporary hybrid waypoint/controller probe: use the existing Frogbot/KTX server shell and diagnostics, use the QWD trajectory as a waypoint target, and preserve the QWD local command profile instead of reducing the move to forward-only marker chasing.

### Alternatives Considered

- Pure route-following probe using the nearest Frogbot marker sequence.
- Add or edit direct `.bot` route edges for the human shortcut.
- Command-imitation only, ignoring the existing marker graph.
- Defer all QWD application until a full learned movement controller exists.

### Evidence

`dm3_sng_shortcut.qwd` mapped against current `dm3.bot`:

- `33` QWD waypoints collapsed to `14` nearest static Frogbot markers.
- Nearest-marker p50/p95/max: `70.112` / `120.324` / `142.597` qu.
- `0.939` of waypoints are within `128` qu of a static marker.
- Direct `.bot` edge ratio across collapsed marker transitions: `0.0`.
- Graph reachable ratio: `1.0`, but p50/p95/max shortest path is `5.0` / `15.8` / `17.0` edges.
- QWD commands are side-move dominant: nonzero forward `0.089`, nonzero side `0.718`, jump `0.284`.

### Expected Consequences

The next probe should test whether KTX/Frogbots can execute a temporary human-derived waypoint/command target under real server physics. Success requires movement evidence, not only arriving near markers. Preserve route, water, command, cadence, and movement-bucket diagnostics so failures can still be attributed.

### Revisit Conditions

Revisit pure route editing if the hybrid probe can execute the shortcut but only by following waypoint geometry that `dm3.bot` lacks. Revisit command-imitation-only if marker proximity proves irrelevant or harmful inside the server-loop probe.

---

## Decision

Implement one bounded QWD-derived SNG hybrid server-loop probe before expanding to other DM3 moves.

### Date

2026-06-06

### Decision

Use the committed `dm3_sng_shortcut.qwd` mapping to define one temporary KTX/Frogbot moveprobe mode, likely mode `9`, that consumes a bounded QWD waypoint string and the QWD side-dominant command profile.

Do not mutate `dm3.bot`, do not expand to all QWD moves, and do not claim that the bot learned the SNG move until a generated server-loop MVD proves execution under guardrails.

### Alternatives Considered

- Edit `dm3.bot` to add a direct SNG shortcut route.
- Try a pure nearest-marker route-following probe.
- Try command imitation without waypoint context.
- Skip the runtime probe and continue offline QWD analysis.
- Abandon Frogbots before testing whether QWD-derived route/controller inputs work in the engine-native shell.

### Evidence

The design artifact `experiments/qwd_route_probe/evidence/qwd-sng-hybrid-probe-design-dm3.*` preserves:

- `14` QWD control points from the SNG shortcut mapping.
- Recommended temporary mode `9`.
- Start/control-point radii of `192` / `96` qu.
- Recommended forward/side command profile of `320` / `508`.
- Required route, water, command, probe-activation, cadence, and movement-bucket diagnostics.
- Stop conditions requiring at least `4` advanced control points or inconclusive status, diagnostic preservation, and rejection of waypoint-only slow/stuck success.

Validation:

```powershell
python -m py_compile scripts/design_qwd_sng_hybrid_probe.py
python -m unittest tests.test_design_qwd_sng_hybrid_probe -v
python scripts/design_qwd_sng_hybrid_probe.py --output-json experiments/qwd_route_probe/evidence/qwd-sng-hybrid-probe-design-dm3.json --output-md experiments/qwd_route_probe/evidence/qwd-sng-hybrid-probe-design-dm3.md
```

### Expected Consequences

The next PR should implement the smallest runtime proof: a temporary mode `9`, runner/config plumbing only as needed, command/probe logging, and a comparison helper that scores control-point advancement beside existing movement/route/water/cadence guardrails.

If the SNG runtime probe is positive, extend the QWD method to the remaining DM3 QWD moves. If the probe cannot activate, cannot advance points, or only succeeds by slow/stuck motion, the result is inconclusive or rejected rather than a reason to optimize speed blindly.

### Revisit Conditions

Revisit the from-scratch option if the bounded mode `9` probe cannot be implemented without invasive Frogbot route rewrites, if diagnostics cannot be preserved, or if QWD-derived waypoint/controller control repeatedly fails under KTX physics despite valid input evidence.

---

## Decision

Treat the first QWD-derived SNG runtime probe as inconclusive and repair activation before expanding.

### Date

2026-06-06

### Decision

The first temporary mode-9 SNG hybrid server-loop run should not be promoted as proof that Frogbots learned the SNG move. Continue the QWD/Frogbots path for one smaller repair step, but do not apply the method to all DM3 QWD moves until the SNG probe reaches the minimum control-point advancement gate.

### Alternatives Considered

- Declare success because mode `9` activated and preserved diagnostics.
- Reject the QWD-to-Frogbot path because the first run advanced only `2` control points.
- Expand immediately to every DM3 QWD route candidate.
- Edit `dm3.bot` route topology before proving the temporary waypoint/controller path can execute.

### Evidence

Mode-9 run `20260606T221429Z`:

- Command/QWD samples: `866`.
- QWD active samples: `11`.
- Max active seconds: `1.12`, passing the activation gate.
- Max advanced control points: `2`, below the required `4`.
- Diagnostics preserved: route, water, probe-state, cadence, and movement metrics.
- Active QWD command profile passed where active: active side ratio `1.0`, active jump ratio `1.0`.
- Slow/stuck success and route-dirty success guardrails did not reject the run.

The committed scorer verdict is `qwd_sng_hybrid_probe_inconclusive` because `control_point_advancement` remained inconclusive.

### Expected Consequences

The next work should repair activation, spawn/context setup, waypoint targeting, or controller projection for the same SNG probe. It should keep the same stop conditions and avoid route-file mutation or broad QWD expansion.

### Revisit Conditions

Revisit expansion to the remaining DM3 QWD moves if a follow-up SNG probe advances at least `4` control points while preserving diagnostics and avoiding slow/route-dirty success. Revisit the from-scratch option if repeated bounded QWD probes cannot advance under KTX/Frogbot physics despite valid QWD input/trajectory evidence.

---

## Decision

Tighten QWD SNG evidence around MVD overlap before another controller change.

### Date

2026-06-06

### Decision

Do not treat the first mode-9 SNG run's two advanced control points as movement evidence until QWD activation overlaps the parsed MVD movement window. Continue the QWD/Frogbots path, but the next live repair must first fix timing/start context: the bot needs to activate near the first QWD control point while the MVD parser is still producing movement samples.

### Alternatives Considered

- Rerun the same mode-9 controller immediately with wider radii.
- Increase QWD command strength or change the projection policy.
- Expand to other DM3 QWD moves because the command log advanced two points.
- Reject the QWD-to-Frogbot path because the first run did not advance four points.

### Evidence

`qwd-sng-repair-diagnosis-dm3` aligned command-log server time to MVD-relative event time:

- Demo start `ServerTime`: `4.267595` s.
- Parsed match duration: `45816` ms.
- `/ goldenboy` active QWD rows aligned to `47044-48082` ms, outside the parsed movement window.
- `/ bro` had no active QWD rows and closest MVD approach to control point `0` was `281.954` qu, outside the `192` qu start radius.
- `/ goldenboy` closest in-window MVD approach to control point `0` was `282.774` qu, also outside the start radius.

The QWD SNG scorer now has an explicit `qwd_activation_mvd_overlap` stop condition and reports it as inconclusive for run `20260606T221429Z`. The companion `control_point_advancement` gate now requires in-window advancement rather than raw command-log advancement.

### Expected Consequences

The next stage should be a setup repair, not a broader controller attempt. It may adjust recording/activation timing, controlled spawn context, or activation instrumentation, but it should not mutate `dm3.bot` or claim movement success from command-log advancement outside the MVD evidence window.

### Revisit Conditions

Revisit controller projection or expansion to other QWD moves only after a follow-up SNG run activates inside the MVD movement window and advances at least `4` control points while preserving route, water, cadence, and slow/dirty guardrails.

---

## Decision

Treat QWD SNG setup as repaired, but reject learned-SNG claims until slow-success is diagnosed.

### Date

2026-06-06

### Decision

Continue the QWD-to-Frogbot path for one narrower diagnosis step, but do not expand to the remaining DM3 QWD moves yet. Run `20260606T231007Z` proves the mode-9 SNG setup can activate and advance `4` control points inside the parsed MVD window, but the run is rejected because the advancing bot crossed the slow/stationary guardrails.

The next stage should diagnose slow-success attribution before another controller change. Specifically, inspect whether `/ bro`'s control-point advancement is limited by controller projection, route/map context, or the widened `320` qu start radius.

### Alternatives Considered

- Declare success because the run reached `4` control points inside the MVD window.
- Expand immediately to all other DM3 QWD moves.
- Revert to timing/start-context repair despite the fixed overlap.
- Change controller projection or command strength before explaining the slow/stationary guardrail failure.
- Abandon KTX/Frogbots despite the setup repair milestone.

### Evidence

Setup-repair run `20260606T231007Z`:

- QWD active samples: `627`.
- Max active seconds: `16.591`.
- Max advanced control points: `4`.
- Max advanced control points inside MVD: `4`.
- `qwd_activation_mvd_overlap`: pass.
- Diagnostic preservation: pass.
- QWD command profile: pass.
- Route-dirty success guardrail: pass.
- `waypoint_only_slow_success`: reject.
- `/ bro` low-speed ratio: `0.429`; stationary ratio: `0.253`.

Artifacts:

- `experiments/qwd_route_probe/evidence/qwd-sng-setup-repair-result-dm3.*`
- `experiments/qwd_route_probe/evidence/qwd-sng-setup-repair-diagnosis-dm3.*`

### Expected Consequences

The next PR should not claim movement realism or route learning. It should produce attribution evidence for the slow-success rejection, ideally from existing artifacts first. If that diagnosis shows the widened start radius or route context is responsible, tighten setup before controller changes. If it shows command projection is the issue under clean context, design the smallest projection repair.

### Revisit Conditions

Revisit expansion to the remaining DM3 QWD moves only after SNG advancement passes both in-window control-point advancement and slow/stationary guardrails. Revisit abandoning Frogbots if repeated QWD-derived probes can only reach points through slow/stuck behavior or require invasive route/map rewrites that undermine the KTX/Frogbots substrate hypothesis.

---

## Decision

Treat QWD SNG slow-success as a setup/phase-gating failure, not learned movement.

### Date

2026-06-06

### Decision

Do not expand the QWD-derived method to the remaining DM3 QWD moves yet. The setup-repaired SNG run advanced enough control points inside the MVD window, but the slow-success attribution shows that the positive geometry came through a loose start-radius window and then stalled before the next target radius.

The next stage should tighten activation around the real CP0 approach and add phase-level success gates before changing projection policy.

### Alternatives Considered

- Declare SNG learned because `/ bro` advanced `4` control points inside the MVD window.
- Treat the failure as water or low-dir-speed route context and pivot to route repair.
- Increase command strength or change projection policy immediately.
- Expand to all other DM3 QWD moves now that mode `9` can advance geometry.

### Evidence

Slow-success diagnosis artifact:

- `experiments/qwd_route_probe/evidence/qwd-sng-slow-success-diagnosis-dm3.*`

Key measurements:

- `/ bro` activated at `t=0` under the widened `320` qu start radius while `281.954` qu from CP0.
- With the original `192` qu design radius, `/ bro` first crossed the start gate at `31652` ms and `83.332` qu from CP0.
- The CP0 active phase had p50 speed `84.385` qu/s, low-speed ratio `0.526`, stationary ratio `0.383`, and blocked ratio `0.371`.
- `/ bro` emitted strong QWD-style commands during active phases: side ratio `1.0`, jump ratio `1.0`, median horizontal command `600.0`.
- CP4 remained outside the point radius: closest distance `181.154` qu against the `96` qu point radius.
- Water and low-dir-speed route context were not primary for the slow-success candidate phases.

### Expected Consequences

The next PR should be a tight setup/phase gate or design for such a gate, not a broad controller policy change. A future positive SNG claim must show phase-level movement quality, not just aggregate control-point advancement.

### Revisit Conditions

Revisit expanding to remaining DM3 QWD moves only after a follow-up SNG run passes in-window advancement, slow/stationary guardrails, and phase-level target-radius gates under tightened activation. Revisit from-scratch if SNG remains achievable only through loose, slow, or route-stalled behavior.

---

## Decision

Require tight-start and phase-target gates for QWD SNG positives.

### Date

2026-06-07

### Decision

Continue the QWD-to-Frogbot SNG track, but make positive bounded evidence stricter. A future SNG run cannot pass merely by advancing four control points. It must also show pre-advance CP0 activation evidence inside the design start radius and avoid long unresolved post-advance target phases. If the first active row has already advanced to a later target, the start gate remains inconclusive instead of rejected.

The next live stage should rerun mode `9` with the original `192` qu start radius and unchanged projection before any command-policy or route-topology change.

### Alternatives Considered

- Treat the setup-repair run as positive enough because it advanced four points inside the MVD window.
- Change projection policy immediately to chase CP4.
- Keep using the widened `320` qu activation radius because it produced more QWD active samples.
- Expand to the remaining DM3 QWD moves before SNG has a clean phase-level pass.

### Evidence

The rescored artifact `experiments/qwd_route_probe/evidence/qwd-sng-phase-gate-tightening-dm3.*` consumes run `20260606T231007Z` with the strengthened scorer:

- `tight_start_activation`: reject. `/ bro` first activated inside the MVD at `281.954` qu from CP0, outside the design `192` qu start radius.
- `phase_target_progression`: reject. After reaching the advancement gate, `/ bro` stayed active on CP4 for `9.908` seconds and never got closer than `183.876` qu to the target against a `96` qu point radius.
- `waypoint_only_slow_success`: still reject.

### Expected Consequences

The next PR should be a tight-start live rerun, not a projection-policy change. If tight activation produces too little active evidence, the setup/spawn route context is still the blocker. If tight activation produces active evidence but still stalls at CP4, projection or route/map context becomes the next likely issue.

### Revisit Conditions

Revisit projection changes only after a tight-start rerun proves where the bot stalls under the stricter gates. Revisit expansion to other DM3 QWD moves only after SNG passes tight-start, phase-target, movement-quality, route, and diagnostic-preservation guardrails.

---

## Decision

Treat the tight-start SNG rerun as strong substrate evidence, not learned movement.

### Date

2026-06-07

### Decision

Continue the QWD-to-Frogbot path, but keep it diagnostic. The tight-start mode `9` rerun with the original `192` qu activation radius proves that QWD-derived control can advance much farther inside the real KTX/Frogbots server loop than the widened setup repair did. It does not prove human-like SNG movement, and it does not authorize expansion to the remaining DM3 QWD moves yet.

The next stage should improve evidence quality around QWD advancement/start events and active-window movement scoring before changing projection policy.

### Alternatives Considered

- Declare SNG learned because both bots advanced deep into the QWD path.
- Expand immediately to all other DM3 QWD moves.
- Change command projection to chase the unresolved target phases.
- Abandon Frogbots despite the tight-radius control-point advancement.
- Keep rerunning with the same sparse `0.1` second sampled command log and hope the phase gates pass.

### Evidence

Tight-start run `20260607T003837Z`:

- Start radius restored to the design `192` qu.
- QWD active samples: `274`.
- Max active seconds: `16.383`.
- Max advanced control points inside MVD: `12`.
- `/ bro` advanced `11` points inside MVD; `/ goldenboy` advanced `12`.
- `qwd_probe_activation`, `control_point_advancement`, `qwd_activation_mvd_overlap`, diagnostic preservation, QWD command profile, and route-dirty guardrails passed.
- `phase_target_progression` rejected on unresolved sampled target phases.
- `waypoint_only_slow_success` rejected because `/ bro` stayed above the low-speed guardrail.
- `tight_start_activation` was inconclusive because the first active in-MVD sampled rows were already at CP2, so the current sampled log cannot prove pre-advance CP0 state.
- The companion diagnosis now preserves that scorer uncertainty as `qwd_sng_start_evidence_inconclusive`, so setup is not considered fully repaired for start-proof purposes.

Artifacts:

- `experiments/qwd_route_probe/evidence/qwd-sng-tight-start-rerun-dm3.*`
- `experiments/qwd_route_probe/evidence/qwd-sng-tight-start-rerun-diagnosis-dm3.*`
- `experiments/qwd_route_probe/evidence/qwd-sng-tight-start-rerun-slow-success-diagnosis-dm3.*`

### Expected Consequences

The Frogbots substrate hypothesis remains alive and stronger: KTX/Frogbots can accept QWD-derived route/control evidence and execute deep SNG progress under server physics. The immediate blocker is now proof quality and movement quality, not basic control injection.

The next PR should add denser or event-level QWD advancement/start evidence, then adjust active-window movement quality scoring using already-preserved diagnostics if the start proof is clean. It should not mutate `dm3.bot`, broaden to every QWD, or claim movement realism from control-point count alone.

### Revisit Conditions

Revisit expanding to the other DM3 QWD moves only after SNG passes phase-entry proof plus active-window slow/stationary guardrails. Revisit from-scratch if the QWD path repeatedly advances geometry only through sparse unverifiable events, slow traversal, or route/map intervention that no longer looks like a small movement-controller enhancement.

---

## Decision

Add event-level QWD activation/advance instrumentation before projection changes or DM3 expansion.

### Date

2026-06-07

### Decision

Continue the QWD-to-Frogbot path, but keep the next step diagnostic. The tight-start MVD crossing diagnosis proves physical SNG route traversal through most of the human-derived control-point sequence, but the first sampled QWD command rows are already after internal advancement and cannot prove the pre-advance CP0 activation event.

The next PR should add event-level mode-9 activation/advance logging or unsampled advancement rows, then rescore active-window movement quality. It should not change projection policy, mutate `dm3.bot`, or expand to the remaining DM3 QWD moves yet.

### Alternatives Considered

- Treat MVD control-point traversal as enough and expand to all DM3 QWD moves.
- Change projection strength or phase targeting immediately.
- Rerun with the same sampled `0.1` second command log.
- Abandon Frogbots despite physical SNG traversal under KTX physics.

### Evidence

The MVD crossing artifact `experiments/qwd_route_probe/evidence/qwd-sng-tight-start-mvd-crossings-dm3.*` consumes run `20260607T003837Z`:

- `/ bro` first enters CP0's `192` qu start radius at `1761` ms (`83.482` qu) and reaches `11` sequential `96` qu point-radius control points.
- `/ goldenboy` first enters CP0's `192` qu start radius at `7432` ms (`85.522` qu) and reaches `12` sequential `96` qu point-radius control points.
- Both bots' first sampled QWD command rows are already at CP2 with `advanced_control_points=2`.
- The nearest MVD samples at those first sampled QWD rows are far from CP0 and CP2, so sampled command rows still cannot prove the internal start event.
- Movement quality still has slow transitions, especially `/ bro` CP7->CP8 and CP8->CP9, and `/ goldenboy` CP5->CP6.

### Expected Consequences

This should separate proof-quality failure from controller failure. If event-level logs show clean CP0 activation and true phase entries, the next decision can focus on active-window movement quality. If event-level logs still disagree with MVD crossing evidence, the mode-9 timing/identity instrumentation itself is suspect and should be fixed before further movement work.

### Revisit Conditions

Revisit projection changes or expansion to other DM3 QWD moves only after event-level activation/advance evidence resolves the start-proof gap and active-window movement-quality scoring can be evaluated without relying on sparse sampled command rows.

---

## Decision

Keep QWD event instrumentation separate from the next live SNG rerun.

### Date

2026-06-07

### Decision

Add unsampled mode-9 QWD activation/advance/complete event logging and parser support as its own bounded PR before another live KTX rerun. Do not change projection policy, mutate `dm3.bot`, broaden to other DM3 QWD routes, or claim learned SNG movement in the instrumentation step.

### Alternatives Considered

- Rerun the same sparse sampled-command setup and hope a sampled row catches CP0.
- Change QWD projection or command strength before fixing event visibility.
- Treat MVD control-point crossings as sufficient proof of internal mode-9 activation.
- Expand immediately to all DM3 QWD moves because the tight-start run physically traversed most SNG control points.

### Evidence

The MVD crossing artifact proves physical traversal but not internal timing: `/ bro` and `/ goldenboy` entered CP0's `192` qu radius and reached `11`/`12` sequential point-radius control points, while both first sampled QWD command rows were already at CP2. The new instrumentation adds `FBMOVEPROBE_QWD_EVENT` rows for QWD `activate`, `advance`, and `complete` edges and runner artifacts `moveprobe-qwd-events.json` / `moveprobe-qwd-events.md`.

Validation for the instrumentation step:

```powershell
git -C C:\Users\benya\projects\quakeworld\engine\ktx apply --check C:\Users\benya\projects\quakeworld\komodobots\experiments\ktx_moveprobe\frogbot-moveprobe.patch
python -m py_compile scripts\run_frobodm2_lab.py
python -m unittest tests.test_extract_movement_metrics -v
```

### Expected Consequences

The next live SNG rerun can answer a narrower question: do internal mode-9 activation and advancement events align with the MVD crossing evidence under the same projection policy? If yes, future work can focus on active-window movement quality. If no, instrumentation/timing identity is still suspect and must be repaired before movement-controller changes.

### Revisit Conditions

Revisit projection changes or broader DM3 QWD transfer only after a reviewed live rerun produces QWD event artifacts that resolve start/advance timing and allow active-window movement-quality scoring without relying on sampled command rows.

---

## Decision

Use QWD event rows as scoring evidence, but not as movement-quality proof.

### Date

2026-06-07

### Decision

Teach the SNG scorer to consume optional `moveprobe-qwd-events.json` rows as the preferred proof source for internal mode-9 activation and advancement timing. Keep event rows separate from movement-quality claims: they can resolve start/advance proof, but they cannot by themselves prove human-like SNG movement.

### Alternatives Considered

- Wait for the live rerun before making the scorer event-aware.
- Keep relying only on sampled `FBMOVEPROBE_CMD` rows.
- Treat physical MVD crossings as sufficient start proof without internal event rows.
- Treat event rows as a success condition by themselves.

### Evidence

The tight-start run's sampled command rows were too sparse to prove CP0 activation, while PR #34 added unsampled event rows for the exact transition edges. The new scorer test proves that an inside-MVD CP0 `activate` event can resolve the `tight_start_activation` gate when sampled commands start after advancement.

Validation for the scoring prep:

```powershell
python -m py_compile scripts\compare_qwd_sng_hybrid_probe.py
python -m unittest tests.test_compare_qwd_sng_hybrid_probe -v
```

### Expected Consequences

The next live rerun can answer whether mode-9 internal activation/advance timing matches the physical MVD crossing evidence. If it does, the next decision can focus on active-window movement quality rather than proof density.

### Revisit Conditions

Revisit if event-bearing live runs still disagree with MVD physical crossings, or if event rows appear without corresponding MVD movement evidence. In that case the scorer should treat identity/timing instrumentation as suspect before any projection-policy change or DM3-wide expansion.

---

## Decision

Restructure the autonomous loop to Coder (Claude) / adversarial Reviewer + merge authority (Codex) / on-demand second opinion (Gemini), executed by a deterministic no-token merge Action.

### Date

2026-06-07

### Decision

The themed roles (Phasekeeper / Code Sentinel / Merge Warden) are renamed to plain Coder and Reviewer plus a deterministic merge executor, pinned to agents:

- Coder = Claude (external/cloud agent): implements stage work and opens PRs.
- Reviewer = Codex, via Codex Cloud code review on a ChatGPT subscription (no extra API tokens, runs in OpenAI's cloud). Codex adversarially reviews and ends each review with `MERGER: READY | READY_WITH_NON_BLOCKING_CAVEATS | BLOCKED <head-sha>`, but does not merge (Codex cannot merge PRs).
- Merge executor = `.github/workflows/codex-merge.yml`: a deterministic `gh` + bash Action with no LLM and no API tokens. It merges only on a current-head-SHA Reviewer `READY` verdict with every `AGENTS.md` merge-gate condition satisfied, and fails closed otherwise.
- Gemini = on-demand second opinion via the Gemini Code Assist app (`/gemini review`); `.gemini/config.yaml` disables auto-review on PR open. Gemini never merges.

### Alternatives Considered

- Keep Gemini as the merger via the `run-gemini-cli` GitHub Action. Rejected: it needs a Gemini API key, and the consumer Gemini AI Pro subscription grants no API/CI access, against the no-extra-tokens goal.
- Let Codex merge directly. Rejected: Codex cannot merge PRs; it only reviews, fixes, and opens.
- GitHub native auto-merge gated on an approving review. Rejected: Codex posts a comment/review, not an `APPROVE`, so native auto-merge cannot key on it.
- Scheduled polling for the merge. Rejected: private-repo GitHub Actions minutes are metered, so polling is not free; event-driven triggers are.

### Evidence

- OpenAI docs: Codex code review is included in ChatGPT Plus/Pro/Business/Edu/Enterprise plans, runs in the cloud, and cannot merge PRs; it posts as the `chatgpt-codex-connector` bot.
- Live test on PR #37: Codex reviewed the PR in the cloud on the subscription.
- The executor enforces the gate with `gh pr view ... --json state,isDraft,baseRefName,mergeable,headRefOid,statusCheckRollup` and refuses unless the verdict cites the current head SHA.

### Expected Consequences

Reviews cost no extra tokens and run in the cloud; merges are deterministic and free except minimal Actions minutes, gated on Codex's verdict. The open question is whether Codex reliably emits the `MERGER:` verdict token; if not, the executor fails closed and the OWNER fallback can supply the verdict.

### Revisit Conditions

Revisit if Codex does not reliably emit the `MERGER: READY <head-sha>` line, if the `chatgpt-codex-connector` identity changes, or if a future need requires a smarter (LLM-based) merge decision than the deterministic gate provides.

---

## Decision

Replace the `MERGER:` verdict-token merge gate with a neutral PR-label gate (`gate: ready`) applied by a no-LLM labeler from Codex's native review.

### Date

2026-06-07

### Decision

The verdict-token mechanism is retired. The merge gate is now a neutral PR label, and `.github/workflows/codex-merge.yml` is deleted. Three deterministic, no-LLM, no-API-token Actions replace it:

- `review-gate-labeler.yml` — reads Codex's native review result (it cannot apply labels or emit custom tokens itself) and stamps `gate: ready` on a clean review ("no major issues") or `gate: blocked` on any posted finding. Fails closed; a repo OWNER can override with `/gate ready` or `/gate blocked`.
- `review-gate-merge.yml` — merges only when `gate: ready` is present, `gate: blocked` / `cycle: needs-human` are absent, the PR is open/non-draft/mergeable on `main`, and all non-gate checks pass.
- `review-gate-reset.yml` — on every `synchronize`, clears `gate: ready`/`gate: blocked` and sets `gate: reviewing`, so a stale review can never merge newer code.

### Alternatives Considered

- Keep the `MERGER: READY <head-sha>` token. Rejected: the prior decision's revisit condition fired — Codex's code-review feature posts its own fixed format and does not reliably emit custom tokens, so the token gate never triggered.
- Have Codex apply the `gate: ready` label itself. Rejected: verified against OpenAI's docs that the code-review feature cannot apply labels; only a manually-mentioned `@codex` cloud task could, which is non-deterministic and permission-dependent — the fuzziness the label gate is meant to remove.
- Owner applies the label by hand every PR. Kept as the override path, but not the default: it is a manual step per PR.

### Evidence

- Live tests on PR #37 and #38: Codex posted "Codex Review: Didn't find any major issues." as `chatgpt-codex-connector` with no `MERGER:` token — the token gate could never fire.
- OpenAI Codex GitHub docs: the code-review feature "posts a standard GitHub code review" (comments only); cloud `@codex` tasks act under least-privilege GitHub App tokens, read-only by default.
- The labeler's clean/blocked classification and the merger's self-check-exclusion jq filter were unit-checked locally (n_checks/n_bad over a simulated `statusCheckRollup` correctly excludes the gate workflows' own in-progress runs — the P1 self-deadlock Codex flagged on the first label-gate attempt).

### Expected Consequences

The merge is now fully deterministic on a label; the only non-deterministic atom is recognizing Codex's standard clean phrasing, isolated in the labeler and failing closed. From the operator's seat the loop is hands-off: Codex reviews → label appears → PR auto-merges. New commits reset the gate automatically.

### Revisit Conditions

Revisit if Codex's clean-review phrasing changes (the labeler's match strings would need updating), if the `chatgpt-codex-connector` identity changes, or if false-positive `gate: ready` stamps occur — in which case tighten the labeler to require an explicit clean signal or fall back to the OWNER `/gate` override.

---

## Decision

Add a deterministic CI floor (`pr-tests`) as the real merge gate; keep the custom executor on the free private plan instead of going public.

### Date

2026-06-07

### Decision

Per best practice (AI review is a filter, not the merge authority), the merge gate is layered: a deterministic machine check is the real authority, Codex's label is an advisory filter on top.

- Added `.github/workflows/pr-tests.yml`: runs the repo's 149 stdlib-only unit tests on a hosted `ubuntu-latest` runner for every PR (≈0.8s locally, no third-party deps). This is the hard gate.
- `review-gate-merge.yml` already counts the PR status rollup, so `pr-tests` is enforced automatically — it now also triggers on `check_suite: completed`, so a PR merges as soon as the last of {tests green, `gate: ready`} arrives, and "not ready yet" is silent (no comment spam).
- `lab-ci.yml` stays `workflow_dispatch`-only (self-hosted servexeri lab, currently fails per-PR); it is NOT the gate. `pr-tests` is the hosted floor.

### Alternatives Considered

- Make the repo public / upgrade to GitHub Pro to get branch protection + native auto-merge. Rejected: required-status-check enforcement (classic branch protection AND rulesets) returns 403 on a free private repo. But `pr-tests` runs on PRs on the free private plan anyway, and the custom executor enforces it — so the full best-practice gate (deterministic CI + AI filter + label-gated auto-merge) is achievable free and private. Going public only swaps the custom executor for GitHub-native enforcement (bypass-resistance — negligible for a solo repo) at the cost of permanently publishing 149 commits. Bad trade.
- Re-enable `lab-ci` on PRs as the floor. Rejected: it runs on the self-hosted runner and currently fails on every PR while the native parser work is open.

### Evidence

- `python -m unittest discover -s tests`: 149 tests pass in ~0.8s; sampled tests import only stdlib + repo modules; no `requirements.txt`/`pyproject`.
- Branch-protection and ruleset APIs both 403 with "Upgrade to GitHub Pro or make this repository public."
- Secret scan across all 149 commits before considering public: clean (only `${{ secrets.GEMINI_API_KEY }}` references, no secret values; no key/credential files in tree or history).
- Merge workflow bash passes `bash -n`; all workflow YAML parses.

### Expected Consequences

Fully automated merging on the free private plan with no human clicks (given Codex Automatic reviews is on): tests green + Codex clean → `gate: ready` → auto-squash-merge. A deterministic test floor sits under the AI filter, so a false-positive `gate: ready` still cannot merge failing code.

### Revisit Conditions

Revisit if the test suite grows to need third-party deps (add a cached install step), if `pr-tests` becomes flaky (quarantine, don't disable the floor), or if multi-committer collaboration starts (then GitHub-native branch protection becomes worth the public/Pro cost).

---

## Decision

Ship the review-gate flow: require the `PR Tests` CI floor at merge, accept one narrow webhook race as documented, and stop iterating with Codex.

### Date

2026-06-07

### Decision

After three Codex review rounds on the gate workflows (findings 4 → 2 → 2, narrowing in scope), fix the one safety-critical issue and go live rather than chase zero findings on a solo experimental repo.

- Fixed (Codex P1): the merge executor now requires a `PR Tests` status to be **present and all-SUCCESS** in the rollup; an empty/absent rollup is no longer treated as passable. This stops untested code merging if `PR Tests` is ever disabled/renamed/fails to trigger. Fail-closed.
- Accepted as documented (Codex P1, narrow): the labeler's P2-only ready path can, in a webhook-ordering race (a P2 inline comment ingested before a sibling P1), briefly ready a PR before the P1 flips it to blocked. Mitigations already in place: `review-gate-reset.yml` clears the gate on every new commit, the `PR Tests` floor must still pass, and a fresh review re-evaluates. For a solo repo the residual exposure is acceptable; revisit if it ever bites.
- Verified false positive (Codex P1): "statusCheckRollup has no workflowName" — live `gh pr view --json statusCheckRollup` exposes `workflowName`; filter unchanged.

### Alternatives Considered

- Keep iterating until Codex returns zero findings. Rejected: diminishing returns — Actions concurrency always admits another theoretical race, and the reset-on-commit + CI floor backstop the narrow ones.

### Evidence

- Live `statusCheckRollup` on PR #40 shows `{"workflowName":"PR Tests","conclusion":"SUCCESS"}` etc.
- Labeler verdict on #40 live data computed correctly (BLOCKED on fresh P1s; connect-notices filtered).
- All workflow YAML parses; merge/labeler bash pass `bash -n`.

### Expected Consequences

Hands-off merging on the free private plan: a PR merges only when `gate: ready` is set (from Codex's review via the no-LLM labeler) AND `PR Tests` is present and green. The CI floor can no longer be silently bypassed.

### Revisit Conditions

Revisit if the P2-only webhook race is ever observed merging an unreviewed change, if Codex's review identity/format changes, or when multi-committer collaboration justifies GitHub-native branch protection.

## Status

The autonomous review-gate loop (Coder = Claude, Reviewer = Codex, deterministic label-gated auto-merge with a `pr-tests` CI floor) is **live** as of 2026-06-07.
