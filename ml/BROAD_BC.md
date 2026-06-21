# Broad behavioral-cloning trainer (`train_broad_bc.py`)

The **BROAD**, enemy/team-aware BC trainer for the dm3 4on4 stand-in bot — the P4
trainer scaffold. It is *not* movement-only: its input is the full POMDP
`agent_observation` (self + observed-other players + team context), and it clones the
broad human usercmd (movement **and** jump/attack buttons).

Contrast with the move-only Stage-2 template (`experiments/stage2/move-bc-train/`):

| | move-only template (`main` line) | `ml/train_broad_bc.py` (this, `dev`/broad line) |
|---|---|---|
| input | 6-dim self movement vector | **full agent_observation** `[obs \| entities(+mask) \| audio \| team]` |
| sees enemies/teammates | no | **yes** (per-observed-other egocentric channel, masked DeepSets pool) |
| action heads | fwd / side / jump (3) | fwd / side / up / **jump** / **attack** (5) |
| model | flat MLP | per-entity encoder + masked mean-pool + trunk + multi-head |
| host | WSL 4090 | `pinnacle` (offline RTX 4090, WSL2) |

## Files

```
ml/train_broad_bc.py          production trainer (torch + numpy) — runs on pinnacle
ml/smoke_broad_bc.py          OFFLINE, deps-free CPU smoke (no torch/numpy)
ml/broad_bc/
  shard_contract.py           THE SHARD CONTRACT (schema + tolerant rebind)
  synth_shard.py              synthetic-shard generator for the smoke
  core.py                     deps-free loader / split / labels / metrics / model-card
                              + a pure-python reference MLP+SGD (the smoke engine)
ml/tests/test_broad_bc.py     contract + reproducibility tests (torch parts skip if absent)
```

The torch trainer and the offline smoke share `ml/broad_bc/` for **everything except
the matmul backend** (split-by-demo, label encoding, metrics, model-card, the contract),
so the deps-free smoke exercises the *real* contract.

---

## SHARD CONTRACT (what FEAT emits / what the loader consumes)

Authoritative source: `data/catalog/dataset_spec.yaml` (`komodobots.dataset_spec.v1`,
`registry_version: 5`) + `data/catalog/feature_registry.yaml`. One **sample = one window
of K ticks**. (v5 is **sequence-aware**: the policy SELF input is the FLAT last-`SELF_HISTORY=16`-tick
goal-conditioned SELF history, the `self_history` field — see below.) FEAT's REAL build (`ml/pipeline/build_features.py shard`) emits **one
Parquet file** holding MANY windows (and many demos) with the per-window arrays stored
row-major-**flattened** as `list<float32>`; the loader (`core._read_parquet_shard`)
reshapes them via the table-level shape metadata FEAT stamps. (`.npz` / `.json.gz` — one
demo per file, pre-shaped — are also read; the smoke uses them.) The loader reads
`obs_dim` / `ent_dim` / `act_dim` / `n_max` **from the shard** — never hard-coded — so it
is tolerant to FEAT's final widths.

| key | shape | dtype | meaning |
|---|---|---|---|
| `obs` | `[K, F_obs]` | float32 | normalized single-tick **self** features (position+velocity+orientation+player_resource + the two appended turn-direction features `yaw_rate_z` + `face_vel_angle_norm` + the route-conditioning goal features `goal_heading_sincos` + `goal_dist_norm`; `F_obs=21` = `SELF_DIM` / `EXPECTS_SELF_DIM`). v5: carried for provenance / the reject guard; `self_history[...][-F_obs:]` equals this. |
| `self_history` | `[SELF_HISTORY*F_obs]` | float32 | **v5 SEQUENCE input**: ONE FLAT last-`SELF_HISTORY=16`-tick goal-conditioned SELF history **per window** — for the window's **last real tick** (oldest→newest, EPISODE-continuous, left-pad-repeat-first only at the **episode** start). `SELF_HISTORY*F_obs = 336` = `EXPECTS_SELF_HISTORY_DIM`. Stored as **one** `[SELF_HISTORY*F_obs]` vector per window (NOT a per-tick `[K, SELF_HISTORY*F_obs]`) — the OOM fix: the trainer/loader only ever read the last-real-tick history, so the stored vector is byte-identical to the old `[K, HD][last_real_tick]`. **This** is the SELF input the v5 policy (a GRU over the 16-step sequence) consumes (jump cadence is a temporal pattern). |
| `entities` | `[K, N_max, F_ent]` | float32 | per **observed-other** actor egocentric vector (enemies + teammates; `F_ent=13`). Team is **folded in** as the per-entity `is_teammate` flag. |
| `ent_mask` | `[K, N_max]` | float32 | `1`=real other-actor slot, `0`=pad/absent |
| `act` | `[K, F_act]` | float32 | **action targets** (human usercmd); `F_act=5` = fwd/side/up move + jump + attack (the cloned heads) |
| `mask` | `[K]` | float32 | `1`=real step, `0`=pad (loss-masked) |
| `weight` | `[K]` | float32 | per-step loss weight = action confidence (`0` on pad / interpolated frames) |
| `demo_id` | per-window int | — | **group-by-demo split key** (Parquet packs many demos per file → split keys off this, not one id/file) |
| `episode_id` / `start_tick` | per-window int | — | provenance (window never spans two episodes) |
| _`audio`_ | _`[K, F_audio]`_ | float32 | **ABSENT** in a `.qwd` shard — `.qwd` carries no audio cues (deferred). Optional; loader zero-fills. |
| _`team`_ | _`[K, F_team]`_ | float32 | **ABSENT** — team is folded into entity `is_teammate`. Optional; loader zero-fills. |

- `N_max = 7` (4on4 ⇒ 7 other actors; 1v1 is the **same** path with more masking).
- **Model input** = `[obs | masked_pool(entities, ent_mask) | audio | team]`; `audio`/`team`
  are width 0 in a `.qwd` shard, so the input is `[obs | masked_pool(entities)]` ⇒ self +
  enemy + teammate context ⇒ **BROAD, not move-only**.
- BC-only: by default the loader takes the **last real tick** of each window, so it works
  whether FEAT emits single-step BC rows (`bc_window=1`) or `K=64` sequence windows.
- Pad entity slots are **zeroed** (contract); invisible-but-known actors carry the belief
  block in their live fields per `feature_registry.yaml` `entity_observation`.
- **`.qwd` provenance:** the self-POV `.qwd` corpus carries observed-others' kinematics +
  alive but NOT their health/armor/team, so `entity_health_est/armor_est` are 0 and
  `entity_is_teammate` is 0 (team unknown) in a `.qwd`-only shard; those populate once the
  `.mvd`/omniscient path lands. The columns are present at full width regardless.

### Action heads (broad usercmd, discretized)

The `act` row is the recovered usercmd (catalog `actions` table / `feature_registry`
`action` group). It is cloned as discrete classification heads (MLMove-style, generalized
from the move-only 3 heads):

| head | classes | source `act` column | encoding |
|---|---|---|---|
| `fwd` | 3 | `forwardmove` (sign) | `{-:0, 0:1, +:2}` back/none/fwd |
| `side` | 3 | `sidemove` (sign) | `{-:0, 0:1, +:2}` left/none/right |
| `up` | 3 | `upmove` (sign) | `{-:0, 0:1, +:2}` down/none/up |
| `jump` | 2 | `jump_button` (`buttons & 2`) | `{0,1}` |
| `attack` | 2 | `attack_button` (`buttons & 1`) | `{0,1}` |

The commanded view turn (`cmd_delta_yaw`) is carried in `act` but **not cloned yet** — it
is reserved for a continuous AIM head (next wave). The `jump`+`attack` heads are what make
this trainer broad rather than move-only.

### Binding to FEAT's actual schema (reconciled)

FEAT's real schema is now bound directly: `act_cols = (forwardmove, sidemove, upmove,
jump_button, attack_button)` (the shard emits exactly these 5; the loader indexes by name
so the width-5 `act` resolves the 5 cloned heads with no rebind). `obs` (16), `entities`
(13), `act_dim` (5) and `N_max` (7) are discovered from the shard arrays / its table
metadata; `audio` and `team` are **absent** (`.qwd` has no audio; team is folded into the
entity `is_teammate` flag) and the loader zero-fills them, so `F_aux = 0`.

`shard_contract.SHARD_CONTRACT_VERSION = "broad_bc.shard_contract.v1"` and
`EXPECTS_REGISTRY_VERSION = 5` (`EXPECTS_SELF_DIM = 21`, `EXPECTS_SELF_HISTORY = 16`,
`EXPECTS_SELF_HISTORY_DIM = 336`, `REQUIRED_NORM_KEYS = ("yaw_rate",)`). The loader REJECTS
a stale/mislabelled shard before training via `SC.check_shard_meta`: if
`meta.registry_version` differs from 5 (a pre-v5 single-tick-SELF shard) **or** `meta.obs_dim`
differs from 21 **or** `meta.self_history_dim` differs from 336 (a v5-labelled shard whose
flat history width is wrong — e.g. a wrong history length, or the old per-tick K×HD storage)
**or** a v5+ shard **omits** `self_history_dim` entirely (the v5 self_history contract is
mandatory — without it the loader would silently degrade to the 21-wide single-tick `obs`),
it raises. At row-build time `SC.require_self_history_present` (called by BOTH the deps-free
loader and the torch trainer) additionally rejects a v5+ shard that lacks the actual
`self_history` **array** — a v5-labelled shard must never train at `x_len = 21`. The normalization artifact is likewise checked (`SC.check_norm_artifact`): a pre-v5
stats artifact missing the `per_map.<map>.yaw_rate` key (or stamped at a pre-v5
`registry_version`) is rejected (not zero-filled), since `yaw_rate_z` z-scores against it.
(Should FEAT ever reorder `act`, pass a
`ShardSchema(act_cols=...)` — a one-object change; see
`test_rebind_schema_with_reordered_act_cols`.)

---

## Offline CPU smoke (deps-free — runs anywhere, no torch)

Proves the contract + scaffold end-to-end with **no torch/numpy**: generates a tiny
synthetic BROAD corpus whose action depends on **both** self obs **and** the observed-other
entity channel (so a move-only model could not fit it), reads it through the *same*
loader/split/labels the torch trainer uses, trains the pure-python reference MLP to
completion, runs it **twice** and asserts identical loss, and emits checkpoint +
`metrics.json` + model-card stub.

```bash
# from repo root, bare python3 (no venv needed)
python3 ml/smoke_broad_bc.py --out /tmp/broad_bc_smoke
```

Outputs in `--out`: `broad_bc_smoke.ckpt.json`, `metrics.json` (per-head val
action-accuracy + reproducibility flag + loss curve), `model_card.json`,
`shard_contract.resolved.json`. Exit 0 iff reproducible **and** loss dropped **and** every
head beats its majority baseline.

Also run by the unit tests:
```bash
python3 -m unittest ml.tests.test_broad_bc
```

---

## PINNACLE GPU RUN (the real training run — offline, NOT executed by the scaffold)

Owner policy: GPU/training on `pinnacle` (offline RTX 4090, WSL2) is autonomous, but this
scaffold unit is **build + CPU-smoke only** — the real run is the next wave. Run it on
`pinnacle` inside the ml venv, **offline** (no production game-server):

```bash
# on pinnacle, WSL2 Ubuntu (per host policy: WSL2 only, so `wsl --shutdown` frees VRAM):
cd <repo>/ml
python3 -m venv .venv-ml && source .venv-ml/bin/activate
pip install -r requirements.txt          # duckdb + pyarrow + numpy + torch (owner OK)

# 0. Build the catalog slice (or reuse data/catalog/dm3_4on4.sqlite). Then fit the
#    train-only norm and build the real (obs,act) Parquet shards (the SHARD CONTRACT):
DB=data/catalog/dm3_4on4.sqlite
python3 pipeline/normalize_fit.py --db "$DB" --out gold/norm/normalization_stats.json \
    --split train --map dm3
python3 pipeline/build_features.py shard --db "$DB" \
    --stats gold/norm/normalization_stats.json \
    --out gold/shards/dm3_4on4_train.parquet --split train --lookback-k 64 --stride 16 --n-max 7
# (repeat for --split val if you want a held-out demo metric)

SHARDS="gold/shards/dm3_4on4_train.parquet"   # .parquet (real) — globs to many also OK
NORM="gold/norm/normalization_stats.json"

# 1+2. Train (CUDA auto-detected; fixed seed; checkpoint + metrics + model card emitted).
#      The loader discovers obs/ent/act dims from the shard; split is by demo_id.
python3 train_broad_bc.py \
    --shards $SHARDS \
    --norm-artifact "$NORM" \
    --out      "$HOME/broad_bc_policy.pt" \
    --epochs 20 --batch 4096 --lr 1e-3 --hidden 256 --ent-out 64 \
    --val-frac 0.1 --seed 0
```

Emits next to `--out`: `broad_bc_policy.metrics.json` (per-head val action-accuracy,
`best_mean_val_acc`, `input_includes_observed_others`) and `broad_bc_policy.model_card.json`
(pins `git_sha` / `registry_version` / `norm_artifact_version` / `seed`).

Notes:
- `--shards` is shell-globbed; pass the real FEAT shard paths.
- `--cpu` forces CPU (tiny debug only; the real run is CUDA).
- Determinism: python/numpy/torch seeds set + `use_deterministic_algorithms(warn_only)`.
- The checkpoint stores `dims` + `head_names` + `contract_version` so the live sidecar can
  bind the policy to the same world-view.
- **Live game-server runs stay human-gated** — this trainer never touches the server; it
  only reads shards and writes a checkpoint.
```
