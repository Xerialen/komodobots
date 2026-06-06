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

Use a three-agent autonomous pipeline for roadmap phase work.

### Date

2026-06-06

### Decision

Store Komodobots-specific autonomous agent cards under `agents/`, adapted from Benjamin's generic vault templates. Use three separated roles:

- Phasekeeper implements one top-level roadmap stage per PR.
- Code Sentinel reviews and hardens the stage PR for slop, validation gaps, and roadmap drift.
- Merge Steward performs the final merge gate and merges only when all gates pass.

The default rule is that future top-level stages start from updated `main` after the previous stage PR merges. Stacked PRs are explicit exceptions, not the normal unattended pattern.

### Alternatives Considered

- Continue with one autonomous agent that implements, reviews, and keeps adding work to the same PR.
- Let the developer agent merge when review appears clean.
- Keep the templates only in the vault and rely on each runtime prompt to remember Komodobots-specific branch and PR rules.

### Evidence

The earlier unattended S2-to-S7 loop created a legacy cross-stage PR plus a stacked S7 child PR. That proved the need for stricter role boundaries, one-stage PR containers, and a dedicated merge gate before the next stage begins.

The repo-specific cards point back to `AGENTS.md`, `docs/00_VISION_AND_NORTH_STAR.md`, and `docs/09_ROADMAP.md` so autonomous work stays aligned with the lab's evidence-producing goal.

### Expected Consequences

Developer automation can continue making progress without turning into a rolling mega-PR. Review and merge decisions become separate checkpoints. Future Claude or Codex runs can use the same role contracts while still following Komodobots-specific docs, branches, and PR state.

### Revisit Conditions

Revisit if the three-agent loop stalls unattended work, if GitHub automation cannot reliably detect Code Sentinel verdicts, if the project chooses a different branching policy, or if roadmap stages become too large or too small for one-PR boundaries.
