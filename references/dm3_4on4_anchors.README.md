# DM3 4on4 elite-anchor reference — methodology

`dm3_4on4_anchors.json` is the Stage-0 Spike 4 deliverable of the DM3 4on4
stand-in program (`docs/12_DM3_4ON4_STANDIN_PROGRAM.md` §7 spike 4, §6 gates).
It replaces the provisional point-value bands (derived from ~3 players, single
demos) with **per-player distributions plus pool min/max**, each tied to an
explicitly stated **measurement plane**, with full provenance (demo SHA256s,
analyzer schema version, rating artifact).

It is built by `scripts/extract_dm3_4on4_anchors.py`. Re-run with:

```
python scripts/extract_dm3_4on4_anchors.py
```

## Status: DIAGNOSTIC-ONLY

`"diagnostic_only": true`. The pool is **3 players × 2 dm3 demos each (n=6)**.
The trustworthy-band floor for letting a gate pass/fail a bot is **≥ 5 players
AND ≥ 5 demos per player**. This pool is far below that, so **every band here is
diagnostic-only**: the bands are the empirical per-player min/max, and no M/E/A/P
gate may hard-pass or hard-fail a bot against them until the pool widens. This is
the program §6 discipline ("measure the real objective; surface unreachable
targets as findings, don't tune around them"). The anchor JSON exists today only
to retire "no anchor file exists / single-replay anchor"; it is not yet a
census-grade gate reference.

The carapace `book_vs_-s-` demo is a deliberately visible example of why this
matters: that game has `ddr_ratio` 0.64 and `kill_efficiency` 0.35 (a losing
game), pulling the carapace floor far below his other demo. Single-point
thresholds would have hidden this; per-player spread surfaces it.

## Anchor player set (clone-selection axis)

`Milton`, `carapace`, `yeti` — selected on the **carry-corrected individual**
rating, NOT the team-W/L rating (`rate_4on4.py`), per the program's corrected
clone-selection axis (a carried passenger must not rank as "best").

- `fantasyquake/scripts/rate_individual.py` over `backups/qw-stats.db`
  (artifact `data/individual_ratings.json`, git `4f5fa39`, all-time window):
  - **Milton** — #1 / 108 pool, blended 3334.93, 1224 games
  - **carapace** — #2 / 108 pool, blended 3046.47, 710 games
  - **yeti** — not in the tb4_s2 reporting pool but **1510 4on4 games** in
    `qw-stats.db`; a recognised elite, carried in the S5b/S7b movement reference.

`rate_individual.py` blends a within-lobby z-composite (quality damage-diff with
EWep up-weight, efficiency axis, enemy-RL denial, survivability) with the team
OpenSkill rating, strength-of-schedule adjusted — so it ranks individual skill
de-confounded from team carry.

## Measurement planes (same-plane discipline)

Every metric names its `plane`. The two planes are **never mixed** in one number.

### `mvd_event_rate_finite_difference` — movement
`qw-analyze -format events` kind:5 player-origin samples, at the **native MVD
position event rate (~13 ms)**. Horizontal speed = `hypot(dx,dy)/dt` between
consecutive samples; percentiles are unweighted per accepted segment; a teleport
guard drops segments > 2500 qu/s. Produced by
`scripts/extract_movement_metrics.py` (`komodobots.movement_metrics.v2`) and read
here verbatim from the committed S7c signature JSON
(`player-signatures-s7c-dm3.json`).

This is the **same plane the bot is scored on** — bot lab runs emit the same
`events.txt`. It is **NOT a 100 Hz pmove trace**. The schema's `vx/vy/vz`
velocity columns (RESULT_SCHEMA v32) are a *central*-difference of the same
position stream; the lab script uses a *forward* difference of the same stream —
conceptually the same MVD-event-rate plane, so M3/P bands stay self-consistent.
When scoring a bot, score it on this plane (or reconstruct human 100 Hz
trace-equivalents via `pmove_sim`) — never cross-plane (program G-ALIGN /
M3-plane rule).

### `ktx_demoinfo_stream` — economy, aim/combat, positioning
`qw-analyze analysis.json`:
- **Economy** — KTX item took/respawn timeline (`items.items[].phases[].takenBy`).
  `*_control_share` = target's pickups / all-player pickups of that single-spawn
  dm3 item (mega `mh`, red armor `ra`, yellow armor `ya`, `quad`, `rl`).
- **Aim/combat** — KTX `mvdhidden_dmgdone` damage stream (`damage.byPlayer`):
  - `ddr_ratio = given / max(taken_all,1)` — the deepfrag `rate.py` DDR form.
  - `ddr_diff = given − taken_all` — the `rate_individual` per-game differential.
  - `ewep_pct = ewep / given` — share of damage dealt to RL/LG-armed enemies
    (EWep victim-weapon buckets `enemyVsLg/Rl/Both`).
  - `kill_efficiency = kills / (kills+deaths)` from **v19-corrected**
    `match.players[]` kills/deaths/suicides (suicides reported so fall-feeding is
    visible, per G-A2).
- **Positioning** — `locGraph` node/edge coverage only (match-level). **Per-player
  loc presence (G-P1) is NOT yet populated** — it needs a `streams.li` /
  PVS-aware pass; flagged PARTIAL. G-P1 is diagnostic-only in the program anyway.

#### Analyzer schema caveat
The on-disk anchor `analysis.json` were produced at **schemaVersion 21**; the
analyzer source is now **v32**. The damage / items / v19-frag fields used here
are stable across that range (v19 corrected kills/deaths/suicides predates v21).
A clean re-analysis at v32 is the right path **before** any of these bands is
promoted off diagnostic-only — at which point `regionControl` (program-demoted to
diagnostic cross-check) and the `streams`-based per-player loc presence can also
be added.

## Provenance

`provenance.demos[]` carries, per anchor demo: `target_player`, `run_id`, demo
filename, **sha256** (cross-checked against the S7c aggregate and re-verified on
the source `.mvd`), the on-disk `analysis.json` path, its `analysis_schema_version`,
map, and duration. The raw demos and `analysis.json` live under the main
`komodobots` checkout's `artifacts/human-demos/` (gitignored large binaries), not
in this Git tree.

## What to widen next (to leave diagnostic-only)

1. Decompress + provenance-filter more elite dm3 4on4 demos (program §7 spike 3)
   to reach ≥ 5 players × ≥ 5 demos.
2. Re-analyze all anchor demos at analyzer schema v32 (single qw-analyze pass).
3. Add the `streams.li` per-player loc-presence pass for G-P1.
4. Only then promote bands from per-player min/max envelopes to census thresholds.
