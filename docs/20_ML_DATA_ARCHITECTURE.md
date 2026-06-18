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

## Status

In-tree catalog/loader/features/validators + tests landed (stdlib, CI-gated). `ml/`
pipeline scaffolded + smoke-tested. Pending: `bsp_geom.py` (PVS/LOS) to realize the
`actor_visibility` masking; training stage. Worked example: `WORKED-EXAMPLE.md`.
