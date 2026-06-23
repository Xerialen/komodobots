# DM3 4on4 elite-anchor reference — methodology

`dm3_4on4_anchors.json` is the **hardened** Stage-0 Spike-4 deliverable of the
DM3 4on4 stand-in program (`references/12_DM3_4ON4_STANDIN_PROGRAM.md` §7 spike 4, §6
gates, §8 risk 6). It is the goal-true gate anchor: per-player distributions plus
pool min/max for every gate-relevant metric (M / E / A / P), each tied to an
explicitly stated **measurement plane**, with full provenance.

It is built by `scripts/extract_dm3_4on4_anchors.py` from a directory of
per-demo v32 `analysis.json` and a manifest. See "How this was built" below for
the exact reproduction commands (WSL2, per the machine hosting policy).

## Status: PROMOTED off diagnostic-only (all four families)

`"diagnostic_only": false`. The pool is **8 elite players × 8–14 dm3 4on4 demos
each (30 distinct demos, 84 per-player samples)**, re-analyzed at the **current
mvd_analyzer schema (v32)**. The trustworthy-band floor for letting a gate
pass/fail a bot is **≥ 5 players AND ≥ 5 demos per player**; this pool clears it
on every metric in every family, so:

| Family | Plane | Promotion | min demos/player |
|---|---|---|---:|
| **M** movement | `mvd_event_rate_finite_difference` | **promoted** | 8 |
| **E** economy | `ktx_demoinfo_stream` | **promoted** | 8 |
| **A** aim/combat | `ktx_demoinfo_stream` | **promoted** | 8 |
| **P** positioning | `ktx_demoinfo_stream` | **promoted** | 8 |

`promotion_status` in the JSON records this per family; the promotion rule is
checked **per metric** — a family is promoted only if *every* metric in it clears
the floor on *both* axes (distinct players AND distinct demos per player).

**Promoted still means an empirical per-player min/max envelope, not a
single-point cut.** A gate may now hard-pass/hard-fail a bot by requiring it
inside the elite per-player envelope (and may report distance-to-distribution),
but the band is the observed range across elite players' good *and* bad games —
it is not a tuned threshold. This is the program §6 discipline ("measure the real
objective; surface unreachable targets as findings, don't tune around them").

### What changed vs the v1 (diagnostic-only) anchor

The previous anchor (`komodobots.dm3_4on4_anchors.v1`) was diagnostic-only and
thin on every axis. This v2 fixes each gap the program §8 risk-6 named:

1. **Pool widened** from 3 players × 2 demos (n=6) to **8 players × 8–14 demos
   (n=30 distinct demos)** — clears the ≥5×≥5 floor.
2. **Re-analyzed at v32** (was schema v21). Every demo, local and hub, analyzed
   by the same v32 `qw-analyze` build.
3. **Positioning pass added.** v1 had only match-level `locGraph` node/edge counts
   and flagged G-P1 "PARTIAL / not yet populated". v2 adds the **per-player
   `streams` loc-presence pass** that was missing: each player's share of their
   own position samples spent in each dm3 region of interest.
4. **Measurement plane stated per metric** and never mixed (unchanged discipline,
   now applied across a real corpus).

## Anchor player set (clone-selection axis)

`Milton, carapace, reppie, yeti, andeh, XantoM, bps, realpit` — the top
**carry-corrected individual**-rated players (NOT team-W/L) who *also* have ≥5 dm3
4on4 demos in the assembled v32 corpus.

Selection ran `fantasyquake/scripts/rate_individual.py` over
`backups/qw-stats.db` (fantasyquake git `4f5fa39`, all-time window,
`openskill==6.0.0` PlackettLuce), rating **18,972 4v4 games / 2,234 players**. All
8 anchor players rank in the top ~15 of 2,234 by blended individual rating:

| Player | blended | individual | team | games |
|---|--:|--:|--:|--:|
| Milton | 3335.21 | 3258.20 | 3450.73 | 1224 |
| carapace | 3040.29 | 3138.61 | 2892.82 | 710 |
| reppie | 2931.69 | 2955.08 | 2896.61 | 352 |
| yeti | 2718.30 | 2607.16 | 2885.00 | 1486 |
| andeh | 2696.90 | 2753.29 | 2612.31 | 595 |
| XantoM | 2696.47 | 2664.85 | 2743.92 | 525 |
| bps | 2685.27 | 2705.82 | 2654.45 | 647 |
| realpit | 2684.85 | 2641.61 | 2749.71 | 946 |

`rate_individual.py` blends a within-lobby z-composite (quality damage-diff with
EWep up-weight, efficiency axis, enemy-RL denial, survivability) with the team
OpenSkill rating, strength-of-schedule adjusted — so it ranks individual skill
de-confounded from team carry, per the program's corrected clone-selection axis (a
carried passenger must not rank as "best").

## Corpus (how the ≥5×≥5 floor was reached)

A single per-demo v32 `analysis.json` carries every signal the anchor needs, and
because each MVD records **all** players, every demo a target appears in
contributes one per-player sample for that target. The corpus is:

- **7 modern-KTX dm3 4on4 MVDs on disk** under the main komodobots checkout
  (`artifacts/human-demos/source/`) — the v1 anchor's 6 demos plus one more.
- **23 additional recent dm3 4on4 MVDs from the public QuakeWorld Hub CDN**
  (`https://d.quake.world/<sha[:3]>/<sha>.mvd.gz`), selected by greedy set-cover
  over the 40 most-recent dm3 4on4 hub games per anchor player so each player
  reaches ≥8 distinct demos. (25 were downloaded; 2 turned out to be the same
  games already on disk and dedup left 30 distinct.)

The hub has **5,251 dm3 4on4 games** available, so the pool can be widened
further later. Every pulled demo was verified at v32 to carry the KTX
`mvdhidden_dmgdone` damage stream + item timeline (modern KTX), and all are on
`dm3` ("The Abandoned Base").

### Why the old Challenge-TV `.qwz` archive is NOT used for E/A/P

`data/challenge-tv-archive/` holds ~858 dm3 `.qwz`/`.qwd` **POV** demos (548
catalogued, SmackDown3-era). These are single-player POV `.qwd` (Qizmo-compressed)
demos: they are the **movement-BC** source (they carry exact per-frame usercmds;
program §7 spike 3), but they **predate the KTX `mvdhidden_dmgdone` stream** —
analyzing one at v32 yields `damage = false`, `items = false`. So they can support
only the movement plane, never the economy/aim/positioning families, and are not
part of this anchor. (The MVD server demos used here zero the movement-intent
usercmds but carry the full KTX damage/item signal — the complementary trade-off.)

## Measurement planes (same-plane discipline)

Every metric names its `plane`. The two planes are **never mixed** in one number.

### `mvd_event_rate_finite_difference` — movement
A **forward** finite difference of the v32 `streams.players[].pos` columns
(`t/x/y/z`), at the **native MVD position event rate (~13 ms)**. Horizontal speed
= `hypot(dx,dy)/dt` between consecutive samples; percentiles unweighted per
accepted segment; a teleport guard drops segments > 2500 qu/s; airborne proxy =
vertical-motion runs ≥ 120 ms with Z range ≥ 4 qu; jump cadence =
airborne-run count / active-s × 60.

This is **byte-for-byte the same method and thresholds** as
`scripts/extract_movement_metrics.py` (`komodobots.movement_metrics.v2`) — the
**same plane the bot is scored on** (bot lab runs emit the same kind:5 origin
stream). It is computed *in this script* from the v32 `pos` stream (rather than
read from the older S7c signature JSON) so the local-corpus and hub-corpus demos
sit on one identical estimator. It is **NOT a 100 Hz pmove trace**, and it is
**NOT** the v32 `vx/vy` *central*-difference velocity column (a different
estimator on the same stream). When scoring a bot, score it on this plane (or
reconstruct human 100 Hz trace-equivalents via `pmove_sim`) — never cross-plane
(program G-ALIGN / M3-plane rule).

Fields: `avg_horizontal_speed_qu_per_s`, `p95_horizontal_speed_qu_per_s`,
`stationary_time_ratio`, `low_speed_time_ratio`, `airborne_proxy_time_ratio`,
`jump_cadence_per_min`.

### `ktx_demoinfo_stream` — economy, aim/combat, positioning
qw-analyze v32 `analysis.json`, count/share-based (plane-agnostic w.r.t. speed):

- **Economy** — KTX item took/respawn timeline
  (`items.items[].phases[].takenBy`). `*_control_share` = target's pickups /
  all-player pickups of that single-spawn dm3 item (mega `mh`, red armor `ra`,
  yellow armor `ya`, `quad`, `rl`). In 4on4 the contested share is naturally low
  (8 players competing for one entity).
- **Aim/combat** — KTX `mvdhidden_dmgdone` damage stream (`damage.byPlayer`):
  - `ddr_ratio = given / max(taken_all,1)` — the deepfrag `rate.py` DDR form.
  - `ddr_diff = given − taken_all` — the `rate_individual` per-game differential.
  - `ewep_pct = ewep / given` — share of damage dealt to RL/LG-armed enemies
    (EWep victim-weapon buckets `enemyVsLg/Rl/Both`).
  - `kill_efficiency = kills / (kills+deaths)` from **v19-corrected**
    `match.players[]` kills/deaths/suicides (suicides reported so fall-feeding is
    visible, per G-A2).
- **Positioning** (the G-P1 pass v1 lacked) — for the target's *own* position
  stream, each sample's loc is resolved via `streams.players[].pos.li →
  timelineAnalysis.locTable`, and `<region>_presence_share` = the share of the
  target's samples whose loc falls in that dm3 region of interest (RA / YA / mega
  (SNG) / quad / pent-ring / RL-bridge / water), plus `distinct_locs_visited`.

All economy/aim/positioning metrics are at **analyzer schema v32** — there is no
longer a schema-version caveat (v1 was v21).

## Provenance

`provenance.demos[]` carries, per demo: `sha256`, `source` (`local_disk` vs
`qw_hub_cdn`), demo filename, CDN url + hub timestamp (hub demos),
`analysis_schema_version` (32), `map`, `duration_ms`, and
`pool_players_present`. `provenance.analyzer` records the qw-analyze build/schema
and invocation; `provenance.rate_individual` and `provenance.hub_corpus` record
the selection axis and the hub source. The raw MVDs and v32 `analysis.json` are
not committed to this Git tree (gitignored large binaries); they are reproducible
from the SHAs (local) and CDN urls (hub).

## How this was built (reproduction, WSL2)

Heavy compute (Go build, demo download, v32 analysis, ratings) runs in WSL2 per
the machine hosting policy. Outline:

1. **Build qw-analyze** (schema v32): in WSL2 Ubuntu-24.04 with go1.25.10,
   `cd tools/mvd_analyzer/mvd-analytics && go build -o qw-analyze ./cmd/qw-analyze`.
2. **Rank players**: `fantasyquake/scripts/rate_individual.py` over
   `backups/qw-stats.db` (openskill==6.0.0). Pick the top individual-rated players
   with ≥5 dm3 4on4 demos in the corpus.
3. **Assemble the corpus**: analyze the 7 on-disk dm3 4on4 MVDs at v32
   (`qw-analyze -format json -include positions,velocity`), and pull additional
   recent dm3 4on4 MVDs from the hub CDN (Supabase `v1_games` filtered to
   `map=dm3,mode=4on4`, downloaded from `d.quake.world/<sha[:3]>/<sha>.mvd.gz`),
   analyzing each at v32. Verify each carries the damage stream.
4. **Extract**: `python scripts/extract_dm3_4on4_anchors.py --analysis-dir <dir>
   --manifest <manifest.json> --output references/dm3_4on4_anchors.json`. The
   manifest lists the pool players, the per-demo SHAs/sources, and the
   rate_individual + hub provenance.

## What to widen / harden next

1. Pull more of the 5,251 hub dm3 4on4 games to push every player past ~15–20
   demos and tighten the per-player envelopes.
2. Add the EWep victim-weapon bucket *distribution* (G-A3/A4) and `weaponPickups`
   gating (does the bot hold the weapon it deals EWep with).
3. Add `backpacks` xferRL/xferLG (G-E) and respawn-timing approach (G-E2) once a
   bot-scoring harness consumes them.
4. Cross-check the positioning regions against `timelineAnalysis.regionControl`
   (program-demoted to diagnostic cross-check) for consistency.
