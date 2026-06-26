# Data Contract

Status: living document. This is the single anchor for **what training data Komodobots
extracts, where it comes from, why, how it is transformed, what format it must have, and
where the output goes.** It exists because that truth previously lived only inside one
script (`scripts/build_training_dataset.py`) and one module (`scripts/move_world_view.py`),
with no version-controlled contract tying them together — exactly the drift risk raised in
issue #374.

This document is the prose layer. The binding, machine-readable layer is:

| Artifact | Role |
|---|---|
| `configs/extraction_spec.yaml` | exact field → source → transform mapping (mirrors code, line-anchored) |
| `schemas/training_example.schema.json` | JSON Schema for one raw NDJSON shard row |
| `examples/expected_training_frame.jsonl` | golden example rows that validate against the schema |
| `tests/test_data_contract.py` | proves the example validates **and** that the builder's emitted keys still match this contract |

> **Rule (read before changing any extraction/transform/format code):**
> Do not infer new fields. Do not rename fields or change the output format unless
> `configs/extraction_spec.yaml`, `schemas/training_example.schema.json`,
> `examples/expected_training_frame.jsonl`, **and** the tests are updated in the **same PR**.
> `tests/test_data_contract.py` fails the build if the code and the contract disagree.

---

## 1. WHY — what the data is for

**Program of record: `docs/28_MEGALODON_MILTON_MLOPS_PROGRAM.md`** (owner re-plan, 2026-06-26). This
contract's **row/schema mechanics (sections 2–6 below) are unchanged** — it is still the version-controlled
truth for what is extracted, from where, and in what format. What changed is the **purpose**: the goal is no
longer human-like-by-imitation judged on a 4v4 bench, but the **information-honest superhuman bot
(Megalodon Milton), trained by RL and validated route-first** (MSE/RMSE vs elite-human ground truth on a
Route Canon "Highway"); 4v4 is demoted to a Phase-4 drift signal.

The original consumer described here is now **legacy**: the move-only `6 -> 128 -> 128 -> {3,3,2}` ReLU MLP
MoveMLP (`experiments/stage2/move-bc-train/train.py`, view/aim replayed from the human;
`docs/19_ARCHITECTURE_AND_GOTCHAS.md`) with success on the 4v4 dm3 leap-vs-frog frag margin is the **old
serving model that the docs/28 P1–P3 movement brain replaces**. The **evolution of the feature vector /
training target** to the docs/28 feature store and RL observation space is owned by tickets **T1.1 (#418,
Feature-Registry→JSON — LANDED, see §1.1)**, **T1.2 (#419, unified catalog writer)**, and **T4.1 (#425,
Parquet offline store)** — each of which, per the binding rule above, must move this contract together with
whatever data-contract surface it actually touches in the **same PR**. Note the **docs/28 feature-store
surface** (the `feature_registry` / `dataset_spec` / `normalization_stats` family — §1.1) is **distinct**
from the **Layer-A raw-row contract** that sections 2–6 below pin (`build_training_dataset.py`'s 11-field
NDJSON + `move_world_view` 6-dim vector + its schema/golden/extraction-spec/tests): **T1.1 migrated the
former (YAML→JSON) and left the latter byte-unchanged** (no Layer-A field added, renamed, or reordered).
Until the remaining tickets land, the extracted rows below remain valid as the data line that feeds the pivot.

### 1.1 Feature registry — the docs/28 feature-store surface (generate-first, T1.1 #418)

The docs/28 movement-brain observation space is declared in **`data/catalog/feature_registry.json`**
(migrated from YAML in T1.1; `registry_version` 5). It is the **single source** for the obs-vector layout:
its `observation` block — the explicit, load-bearing SELF / entity / action channel order plus the v5
history dims — is the authority the live + offline encoder (`scripts/features/agent_observation.py`) and the
shard contract (`ml/broad_bc/shard_contract.py`) both **import** (no hand-copied dims; the `onground` SELF
channel, previously in the encoder but unregistered, is now a registered feature).

`scripts/generate_from_registry.py` (pure stdlib) **derives** two committed artifacts from the registry —
`scripts/features/registry_constants_generated.py` and `data/catalog/obs_spec.generated.json` (each carries
an `AUTO-GENERATED — DO NOT HAND-EDIT` header) — and **validates** (never overwrites) the curated artifacts
that legitimately hold config the registry does not: every feature `source:` must exist in
`scripts/catalog_schema.sql`; every fitted feature must have a matching key + method in
`data/catalog/normalization_stats.template.json` (which keeps the *verified* map AABB bounds); and
`data/catalog/dataset_spec.yaml`'s `registry_version` / `N_max` must match; and every emitted
observation-layout channel (`self_layout` / `entity_layout` / `action_layout`) must resolve to a registered
feature or a documented `<base>_sincos` flattening, so a model input can never be emitted without a
declaration (fail-closed). The gating check
`tests/test_registry_generate.py` fails the build if regenerating the generated files produces any diff
(definition drift) or if a linkage breaks. **Edit the registry, then regenerate — never hand-edit a
generated file.** Changing this surface (adding / renaming / reordering an obs channel) moves
`feature_registry.json` + the regenerated artifacts + `tests/test_registry_generate.py` in the same PR.

## 2. WHERE — data sources

| Source | Location | Format | Used for | Notes |
|---|---|---|---|---|
| POV `.qwd` trick/match corpus | `~/ctv_decomp` (canonical, ~478 QWDs) | first-person QuakeWorld demo | **action labels + state** | The only source carrying exact `usercmd` intent (forwardmove/sidemove/jump). Passed to the builder via `--demo-dir`. |
| Server MVD corpus | `servexeri:~/...` (see `docs/06_DATA_AND_MVD_PIPELINE.md`) | server-side demo | movement-realism *comparison* | MVDs generally **do not** carry usercmd intent, so they cannot supply button labels (`docs/06`). |
| QW stats DB | Turso + local SQLite `fantasyquake/backups/qw-stats.db` | relational | economy / aim priors | read-only. |
| MVD parser | `~/qw-sim/bin/qw-analyze-v20` | binary | metric extraction | **Pin the exact commit before treating output as regression evidence** (`docs/02`, `docs/06`). Currently unpinned — see audit. |

Demo-count headline (state once, reference everywhere): **raw 478 / indexed 465 / kept 433**
(the 472 figure elsewhere is `demolist` rows, not distinct demos).

For the upstream MVD/QWD pipeline detail see `docs/06_DATA_AND_MVD_PIPELINE.md`; for software
sources (KTX, MVDSV, Frogbots) see `docs/02_SOURCE_MAP.md`. This contract owns the
**training-data** view those two docs did not consolidate.

## 3. WHAT + HOW — the two layers

The pipeline has **two** layers, and the model does **not** train on layer A directly.

### Layer A — raw per-frame shard (the NDJSON row)

`scripts/build_training_dataset.py` runs `build_replay_frames()`
(`scripts/build_replay_command_file.py`) over each demo and emits **one NDJSON row per
command index**. Eleven fields:

| Field | Type | Meaning |
|---|---|---|
| `demo` | string | source demo file name |
| `map` | string\|null | server map level |
| `frame` | int | **command index** (one row per `usercmd`), *not* a time frame |
| `msec` | int | command duration |
| `o` | float[3] | origin `[x,y,z]` (lerp-interpolated float) |
| `v` | int[3] | velocity `[x,y,z]` (lerp then `round()` → int) |
| `a` | float[3] | view angles `[pitch,yaw,roll]` |
| `m` | int[3] | move `[forwardmove,sidemove,upmove]` — **the action label source** |
| `buttons` | int | button bitfield; bit `2` = jump |
| `onground` | bool | **degenerate offline**: POV `.qwd` carries no server ground flag → effectively always `false` |
| `pm_code` | int | pmove code; **degenerate offline** → effectively `0` |

`solid`, `reference_source`, and `reference_interpolated` are built by `build_replay_frames`
but intentionally **not** emitted into the row.

### Layer B — derived model feature vector (what the net actually sees)

`scripts/move_world_view.py::state_features` derives the **6-dim** input vector from the raw
`v`/`a` fields. Order is load-bearing (it is the trained column order — do not reorder
without retraining):

```
FEATURE_NAMES = [hspeed/320, vz/320, lvm_sin, lvm_cos, moving, pitch/90]
MAXSPEED = 320.0   MOVING_EPS = 1.0   PITCH_NORM = 90.0
```

This is the single function both the offline builder and the live sidecar call, so it is the
real train/serve parity contract. Its bit-exactness is already guarded by
`tests/test_golden_vector_parity.py` against `tests/fixtures/golden_vector_parity.tsv`
(`komodobots.golden_vector.v1`) — that test guards **layer B only**, never the layer-A row.
This contract documents the edge `layer A raw shard → move_world_view → layer B vector` that
was previously unwritten.

### Selection / quality filter

The per-demo `manifest.json` carries movement-quality stats (`peak_hspeed`, `p50/p90_hspeed`,
`air_frac`, `jumps`, `paired_coverage`) so high-retention sustained-high-speed bunnyhop runs
can be selected before fitting. **The builder does not enforce any threshold** — it writes a
shard for every demo with ≥1 frame and only *prints* the count of demos with
`peak_hspeed > 700`. Selection happens downstream by consuming the manifest.

## 4. FORMAT + DESTINATION

- **Shards:** NDJSON, one compact object per line, at `{out_dir}/{demo_stem}.ndjson`.
- **Manifest:** single JSON array at `{out_dir}/manifest.json`.
- **Model-facing:** the layer-B vectors pack to an `(N,6)` float32 `X` + `(N,3)` label matrix
  in `.npz` (e.g. `~/move_bc_dataset.npz`), trained on the 4090 workstation; offline gate
  metrics land under `experiments/stage2/move-bc-train/`.
- **Bench:** the 4v4 leap-minus-frog frag margin lands in a validation ledger consumed by the
  dashboard at `/botlab/?evidence=1`.
- **Live serving:** the KTX `trap_SetBotCMD` moveprobe seam via the python policy sidecar
  (`scripts/move_policy_sidecar.py`, `/dev/shm`).

## 5. Change control

Any change to extracted fields, transforms, or output format **must** update, in the same PR:

- this document,
- `configs/extraction_spec.yaml`,
- `schemas/training_example.schema.json`,
- `examples/expected_training_frame.jsonl`,
- `tests/test_data_contract.py` if the field set or types change.

Decisions go to `docs/08_DECISION_LOG.md`; newly discovered source-data behaviour goes to
`docs/07_FINDINGS_LOG.md`. (Issue #374's best-practice names these `05_`/`06_`; in this repo
they already exist at `08_`/`07_` — use those, do not renumber.)
