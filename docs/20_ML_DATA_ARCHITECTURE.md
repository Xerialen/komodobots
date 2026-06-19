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
passes. **What `.qwd` does NOT provide:** the omniscient all-actor world state (`actor_ticks`),
the POMDP `actor_visibility`/`audio_cues`, and the demo-wide item/region timelines come from
the server-side `.mvd` path (mvd_analyzer `getStateAt`/`getEvents`/`getRegionControl`) — those
tables stay empty under the `.qwd` loader (the broadening step, see §Status).

## Status

In-tree catalog/loader/features/validators + tests landed (stdlib, CI-gated). The
demos→catalog ETL for the self-POV / movement + action layer is landed
(`catalog_etl_qwd.py`, P1) and produces a real multi-demo populated catalog. `ml/`
pipeline scaffolded + smoke-tested. Pending: the `.mvd`/mvd_analyzer ETL for the
omniscient `actor_ticks` + team/item/region timelines (full-behavior broadening);
`bsp_geom.py` (PVS/LOS) to realize the `actor_visibility` masking; training stage.
Worked example: `WORKED-EXAMPLE.md`.
