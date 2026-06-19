<!-- PROPOSED new canonical doc for the komodobots repo: docs/20_ML_DATA_ARCHITECTURE.md (E2).
     The repo's docs run 00-09; 10 is the next free number. AGENTS.md defines no routing
     rule for new top-level numbered docs — get the owner's OK before adding, or fold this
     summary into an existing numbered doc if preferred. -->

# 20 — ML Data Architecture

Canonical entry point for the machine-learnable data substrate. Full spec lives in the
research deliverable (`research/komodobots-ml-data-architecture/00-DATA-ARCHITECTURE.md`);
this is the in-repo summary + pointer.

## Layout

```
data/catalog/        catalog_schema.sql + JSON catalogs (maps/items/locs/regions/markers/nav)
                     + normalization_stats + feature_registry/dataset_spec (reference)
data/fixtures/       dm3_milton_211436/ — the canonical test fixture
scripts/catalog_*.py, scripts/features/, scripts/validate_catalog.py   # in-tree, stdlib, CI-gated
ml/                  Parquet feature build (DuckDB), normalization fit, training  # WSL2, non-gating
```

## The split (Strategy A — see ADR in 08_DECISION_LOG)

- **In-tree = stdlib only.** The catalog loads with `sqlite3`; the feature transforms
  (egocentric geometry + per-feature normalization) are pure stdlib and **shared with
  the live bot**, so train-time and inference-time math are identical. Validators replace
  pandera in-tree. The merge gate (`pr-tests.yml`) stays dependency-free.
- **Out-of-tree (`ml/`) = the heavy stack.** DuckDB ASOF point-in-time joins over Parquet
  (no future leakage), WebDataset/HDF5 emit, torch training. Own `requirements.txt`;
  `ml-tests.yml` runs it as a **separate, non-gating** job.

## Key invariants

- **State, not inputs.** MVD stores positions; velocity is finite-differenced, angles come
  from the dense `qwd_usercmd` path. Actions are recovered (inverse dynamics).
- **POMDP.** `world_state` (omniscient) is the critic/target; `agent_observation` is the
  masked policy input (`is_visible = pvs_visible AND in_fov AND los_clear`). Feeding
  world_state to a policy is a wallhack bot.
- **Train-only normalization.** Stats fit on `split='train'` (grouped by demo), frozen to
  a versioned JSON artifact, re-applied byte-identically at val/test/inference.
- **4on4-first.** Multi-actor + team + audio + region-control layers are the primary
  target; single-agent movement is a sub-skill.

## Populating the catalog from real demos (P1)

`catalog_load.py` builds the STATIC spine (maps/items/markers/nav) + one hand-extracted
fixture's identity/team/frag rows. To populate the per-tick trajectory tables from REAL
demos there is now a second loader:

- **`scripts/catalog_etl_qwd.py`** (stdlib, CI-gated) — runs the validated `.qwd`
  extractor (`build_replay_command_file.build_replay_frames`, the exact path the Stage-2
  MOVE-BC pool uses) over a list of self-POV dm3 4on4 `.qwd` demos and loads, per demo:
  `demos` (source=`qwd`), `players` (the POV slot), `episodes` (contiguous trajectory
  segments split at teleport/respawn discontinuities via `pmove_sim.detect_teleports`,
  capped at 2048 frames), `player_ticks` (the ego-self per-tick STATE spine: o/v/angles/
  hspeed/onground, velocity finite-differenced from the dense input path), and `actions`
  (recovered usercmd LABELS, `label_source='qwd_usercmd'`, confidence 1.0). A
  **group-by-demo** train/val/test split is written to `episodes.split` (no demo
  straddles). `--with-fixture` additionally folds the `dm3_milton_211436` team-layer rows
  (`teams`/`frag_events`/`item_events`/`region_control_timeline`, the last decoded from
  the sample's `bucketStates` char string) so the relational team tables are exercised.

```bash
python scripts/catalog_etl_qwd.py --catalog-dir data/catalog \
    --demo-list experiments/stage2/move-bc-dataset/p1_catalog_slice.tsv \
    --db data/catalog/dm3_4on4.sqlite \
    --with-fixture data/fixtures/dm3_milton_211436 --workers 2
```

The output `.sqlite` is a regenerable build artifact (gitignored: `data/catalog/*.sqlite`).
A bounded 8-demo slice (the smallest real match POVs in `/home/ubuntu/ctv_decomp/`, one per
player) yields ~350k `player_ticks` + ~350k `actions` across 368 episodes; `validate_catalog`
passes.

## Observed-other players → `actor_ticks` (P2, the agent_observation layer)

P1 stated `actor_ticks` could only come from a server-side `.mvd`. That is **only true for
the fully OMNISCIENT view** (players outside the recorder's PVS). A QuakeWorld CLIENT demo
(`.qwd`) records the full server→client message stream the client RECEIVED, which includes
an `svc_playerinfo` for **every player in the recording client's PVS** — see mvdsv
`SV_WritePlayersToClient` (`src/sv_ents.c`): the per-player loop runs over all
`SV_PlayerVisibleToClient` players and writes one playerinfo each (for the recorder's own
entity the server clears `PF_MSEC|PF_COMMAND`; every other player keeps them and carries a
delta-usercmd with its commanded view angles). That **observed-other set is exactly the
POMDP `agent_observation`** — the masked view the human actually acted on — and is the
correct input for behavioral-cloning a believable policy. P1 simply did not extract it
(its self-POV recovery anchors one playerinfo per message at playernum == self).

- **`scripts/qwd_observed_others.py`** (stdlib, CI-gated) does a FULL sequential `svc_*`
  walk of each QWD server-message body (skip table ported from the authoritative
  mvd_analyzer Go reader `parser.skipCommand` + mvdsv `sv_ents.c`) and decodes every
  `svc_playerinfo` in the **QWD/PF_ client form** (not the MVD/DF_ broadcast form) at its
  true offset: per other player, origin/velocity/commanded-view-angles/alive/onground/
  pm_code. Scoped to PROTOCOL 28 standard-coord QW (the CTV/SmackDown corpus); it refuses
  FTE/float-coord demos rather than risk a wrong skip table.
- **`catalog_etl_qwd.py`** now folds this into `actor_ticks`: for each self episode-tick
  (on the absolute QWD demo clock) it samples each other player's most-recently-RECEIVED
  state within a 0.5 s staleness window (a player that has left PVS / gone silent drops
  out — its carried-forward BELIEF/memory is the DEFERRED `actor_visibility` layer). The
  self ego is also written to `actor_ticks` (schema: EVERY player). `validate_catalog`
  gains an `actor_ticks` validator (actor/tick FK integrity + map-AABB containment — an
  entity-stream mis-decode shows up as out-of-map coordinates).

Verified on real dm3 4on4 POVs: e.g. `…aq_vs_dt_dm3_cougar.qwd` (proto 28, self slot 10)
decodes 8 distinct in-PVS other players, ~112k observed-other rows, **0.00 % outside the
dm3 AABB** with 100 % of message bodies walked cleanly. A 3-demo slice yields ~662k
`actor_ticks` rows; the observed-others-per-tick distribution is the expected PVS-limited
taper (most ticks 1–3 others, up to 7). The PVS/LOS mask refinement (`bsp_geom` raycast →
`actor_visibility`) and `audio_cues` stay deferred; demo-observed presence is already a
strong ground-truth visibility signal.

**Still `.mvd`-only:** the truly OMNISCIENT all-player world state (players the recorder
never saw), `actor_visibility`/`audio_cues`, and the demo-wide item/region timelines come
from the server-side `.mvd` path (mvd_analyzer `StateAt`/`getEvents`/`getRegionControl`).
The `.mvd` corpus present in this workspace (~30 unique, in `nquakesv/ktx*/demos` and lab
`runs/`) is **bot-generated dm3 lab output** (`4on4_red_vs_blue`, `4on4_frog_vs_leap`,
trick demos) — a world-state/critic/RL source for later, **not** human play. The human
dm3 4on4 corpus is the `.qwd` set exploited above.

## Status

In-tree catalog/loader/features/validators + tests landed (stdlib, CI-gated). The
demos→catalog ETL for the self-POV / movement + action layer is landed
(`catalog_etl_qwd.py`, P1) and produces a real multi-demo populated catalog. The
observed-OTHER players (in-PVS `agent_observation`) are now extracted from the same `.qwd`
corpus into `actor_ticks` (`qwd_observed_others.py` + the `catalog_etl_qwd.py` join, P2).
`ml/` pipeline scaffolded + smoke-tested. Pending: the `.mvd`/mvd_analyzer ETL for the
fully OMNISCIENT all-player state + team/item/region timelines (only needed for the
critic/RL omniscient view, and gated on a real human dm3 4on4 `.mvd` source — the present
`.mvd` corpus is bot lab output); `bsp_geom.py` (PVS/LOS) to realize the `actor_visibility`
masking; training stage. Worked example: `WORKED-EXAMPLE.md`.
