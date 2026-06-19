# ml/ — out-of-tree feature build & training (WSL2)

This subtree holds the **deps-heavy** half of the data architecture: the Parquet
feature build, the normalization fit, and model training. It is deliberately
**outside the stdlib-only merge gate**.

## Why it's separate

The repo's hard merge gate (`.github/workflows/pr-tests.yml`) runs
`python -m unittest` on **bare Python 3.12 with no `pip install`**. Anything that
imports `duckdb`, `pyarrow`, `pandera`, `numpy`, or `torch` would break it. So:

| | in-tree (`scripts/`, `tests/`) | out-of-tree (`ml/`) |
|---|---|---|
| deps | **stdlib only** | `requirements.txt` (DuckDB/Arrow/torch/…) |
| CI | `pr-tests.yml` — **the merge gate** | `ml-tests.yml` — **separate, non-gating** |
| runs on | every PR, bare Python | on demand / nightly, in a venv |
| imports `scripts/features` | — | **yes** (shared math, see Parity) |

The unit suite never imports anything in `ml/`, so `ml/` can use the full
scientific-Python stack without ever threatening the gate.

## Setup (WSL2, RTX 4090 box)

Per the host policy, model/data work runs in **WSL2 Ubuntu 24.04**, never Windows-native
(so `wsl --shutdown` frees all VRAM/RAM instantly for gaming):

```bash
cd ml
python3 -m venv .venv-ml
source .venv-ml/bin/activate
pip install -r requirements.txt
```

> Installing these deps is a system change — get the owner's OK first (per CLAUDE.md).

## Stages

1. **`pipeline/build_features.py`** — load the SQLite catalog (via the in-tree
   `catalog_load`), join the fixture's `actor_ticks` to the static item/region
   catalogs with a **DuckDB ASOF point-in-time join** (`t <= tick`, no future
   leakage), apply the **shared** `scripts/features` transforms, and emit a Parquet
   feature shard to `gold/features/`.
2. **`pipeline/normalize_fit.py`** — stream the TRAIN split with Welford/Chan to
   produce a frozen `normalization_stats.json` (the artifact `scripts/features`
   reads at train *and* inference).
3. **training — `train_broad_bc.py`** (+ the `broad_bc/` package): the **BROAD**,
   enemy/team-aware behavioral-cloning trainer. Its input is the full POMDP
   `agent_observation` (self `obs` + per-observed-other `entities` + `team`/`audio`,
   `00-DATA-ARCHITECTURE.md` §2.8), pooled with a masked DeepSets head, cloning the
   broad usercmd (move + jump + attack) — **not** movement-only. See **`BROAD_BC.md`**
   for the SHARD CONTRACT it consumes, the deps-free CPU smoke (`smoke_broad_bc.py`),
   and the `pinnacle` GPU run command.

## Shard schema contract (P3 — `build_observation_shard`)

`pipeline/build_features.py shard` consumes the relational catalog
(`player_ticks` self + `actor_ticks` self+observed-others) and emits a **windowed
`agent_observation` Parquet shard** via the SHARED
`scripts/features.agent_observation` transform (train/serve parity). This is the
contract the **TRAINER** consumes — frozen per `registry_version=2`.

**Build:**
```bash
python ml/pipeline/normalize_fit.py  --db data/catalog/dm3_4on4.sqlite \
    --out data/catalog/norm/normalization_stats.dm3_4on4.json --split train --map dm3
python ml/pipeline/build_features.py shard --db data/catalog/dm3_4on4.sqlite \
    --stats data/catalog/norm/normalization_stats.dm3_4on4.json \
    --out data/catalog/shards/dm3_4on4_train_p3.parquet \
    --split train --lookback-k 64 --stride 16 --n-max 7
```

**One Parquet row = one window** (`dataset_spec.yaml`: `lookback_K=64`, `stride=16`,
`N_max=7`; windows never cross an episode; trailing window padded + attention-masked).
Array columns are stored **flattened row-major** as `list<float32>` and the trainer
reshapes by the shapes below (constants: `S = SELF_DIM = 16`, `ENT = ENTITY_DIM = 13`,
`A = ACT_DIM = 5`, `K = lookback_k`, `Nm = n_max`). The per-window shape constants are
also stamped in the Parquet **table-level metadata** (`komodobots.shard.*`) so the
trainer's `_read_parquet_shard` reshape is unambiguous and width-agnostic:

| column | dtype | flat len | reshape to | meaning |
|---|---|---|---|---|
| `episode_id` | int64 | — | scalar | source episode (window never spans two) |
| `demo_id` | int64 | — | scalar | **group-by-demo split key** (one Parquet file packs many demos) |
| `start_tick` | int64 | — | scalar | tick index of the window's first step |
| `obs` | list\<float32\> | `K*S` | `[K, S]` | normalized **SELF** feature vector / step |
| `entities` | list\<float32\> | `K*Nm*ENT` | `[K, Nm, ENT]` | per-observed-other **egocentric** vectors |
| `ent_mask` | list\<float32\> | `K*Nm` | `[K, Nm]` | 1.0 = real entity slot, 0.0 = pad/absent |
| `act` | list\<float32\> | `K*A` | `[K, A]` | broad usercmd **TARGET** (fwd/side/up move + jump + attack) |
| `mask` | list\<float32\> | `K` | `[K]` | 1.0 = real step, 0.0 = pad (mask in loss+attn) |
| `weight` | list\<float32\> | `K` | `[K]` | action confidence; 0.0 on pad / interpolated frame |

**`act` channel order** (`agent_observation.ACT_FIELDS`, len 5 — the cloned heads;
`feature_registry` `action` group): `forwardmove, sidemove, upmove` (each `usercmd/400`
→ ~`[-1,1]`) · `jump_button` (`1.0 if buttons&2`) · `attack_button` (`1.0 if buttons&1`).
The reserved continuous turn columns (`cmd_delta_yaw_sin/cos`) are **not** cloned yet
(future AIM head), so the shard omits them; the trainer indexes `act` by name, so width 5
binds the 5 heads. `audio`/`team` columns are **absent** (`.qwd` has no audio; team is
folded into the entity `is_teammate` flag) — the trainer treats them as optional.

**`obs` channel order** (`agent_observation.SELF_FIELDS`, len 16):
`pos_x_norm, pos_y_norm, pos_z_norm` (per-map minmax) · `vel_x_z, vel_y_z, vel_z_z`
(per-map zscore, world frame) · `hspeed_norm` (per-map robust) · `vel_heading_sin,
vel_heading_cos` (sincos; 0,0 when hspeed<80) · `yaw_sin, yaw_cos, pitch_sin,
pitch_cos` (sincos) · `onground` (0/1) · `health_norm, armor_norm` (/250, /200).

**`entities` channel order** (`agent_observation.ENTITY_FIELDS`, len 13, innermost dim):
`entity_rel_dist_norm` (/diagonal) · `entity_rel_bearing_sin, entity_rel_bearing_cos`
(sincos) · `entity_rel_pitch_sin, entity_rel_pitch_cos` (sincos) · `entity_rel_vel_x,
entity_rel_vel_y, entity_rel_vel_z` (egocentric-rotated, per-map vel zscore — reuses the
SELF vel keys) · `entity_health_est_norm, entity_armor_est_norm` (/250, /200, **ZEROED**
when not observed) · `entity_alive` (0/1) · `entity_is_teammate` (0/1, **relative** —
never an absolute team id; 0 when team unknown) · `entity_is_visible` (0/1 observed gate).

**Invariants the trainer can rely on** (all asserted in `ml/tests/test_pipeline.py`):
- Kept entities are the **N nearest** by egocentric distance, **nearest-first**, tie-broken
  by `actor_id` → byte-identical layout regardless of input row order. Pool with a
  DeepSets/transformer head using `ent_mask` (permutation-/side-invariant).
- **No future leakage:** a step reads only `actor_ticks`/`player_ticks` rows AT that tick;
  the `act`/`weight` label is the `actions` row joined on the SAME `(episode,tick)` PK
  (equal-tick, never tick+1); windows never span episodes. Padded steps zero `obs` AND
  `entities`; pad entity slots (`ent_mask==0`) are all-zero.
- **Train-only normalization:** the stats artifact is fit on `episodes.split='train'`
  rows only (`computed_from="train"`, `registry_version=2`); identical refit hashes
  byte-for-byte; the shard rebuild is byte-identical (deterministic). The `act` labels are
  raw usercmd (`forwardmove/sidemove/upmove ÷ 400`, `jump=buttons&2`, `attack=buttons&1`)
  — NOT fitted, so they do not enter the norm artifact.

> .qwd provenance note: the self-POV `.qwd` catalog (P1/P2) carries kinematics + alive
> for observed-others but NOT their health/armor/weapon or team — so
> `entity_health_est_norm`/`entity_armor_est_norm` are 0 and `entity_is_teammate` is 0
> (team unknown) in a `.qwd`-only shard. The columns are present at full width; they
> populate once the `.mvd`/`actor_visibility` omniscient path lands. `entity_is_visible`
> is 1.0 for every present row (a received in-PVS sample IS an observation).

## Parity guarantee

`ml/` imports the **same** `scripts/features` transforms the live bot uses. The
offline Parquet build and the in-tree path therefore produce **byte-identical**
normalized vectors on a given tick — verified by `ml/tests/test_parity.py`. The
heavy `pandera` dataframe-schema check is the out-of-tree counterpart to the
in-tree stdlib `scripts/validate_catalog.py`.

## Repo destination

`ml/` at the repo root; `ml-tests.yml` under `.github/workflows/`.
