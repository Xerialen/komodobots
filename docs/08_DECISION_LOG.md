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
