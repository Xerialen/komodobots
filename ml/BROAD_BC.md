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
`registry_version: 2`) + `data/catalog/feature_registry.yaml`. One **sample = one window
of K ticks**, stored as arrays sharing a basename (a WebDataset tar group, or an `.npz`).
The loader reads `obs_dim` / `ent_dim` / `n_max` **from the arrays** — never hard-coded —
which is what makes it tolerant to FEAT's final widths.

| key | ext | shape | dtype | meaning |
|---|---|---|---|---|
| `obs` | `obs.npy` | `[K, F_obs]` | float32 | normalized **self** features (position+velocity+orientation+player_resource+item+timing+player_style + self team scalars) |
| `entities` | `entities.npy` | `[K, N_max, F_ent]` | float32 | per **observed-other** actor egocentric vector (enemies + teammates) — the enemy/team-aware channel |
| `ent_mask` | `ent_mask.npy` | `[K, N_max]` | float32 | `1`=real other-actor slot, `0`=pad/absent |
| `audio` | `audio.npy` | `[K, F_audio]` | float32 | optional decayed spatial audio cues |
| `team` | `team.npy` | `[K, F_team]` | float32 | optional team-aggregate context |
| `act` | `act.npy` | `[K, F_act]` | float32 | **action targets** (the human usercmd) |
| `mask` | `mask.npy` | `[K]` | float32 | `1`=real step, `0`=pad (loss-masked) |
| `weight` | `w.npy` | `[K]` | float32 | per-step loss weight = action confidence |
| `meta` | json | — | — | `episode_id, demo_id, player_id, map_id, start_tick, label_source, registry_version, norm_artifact_version, n_max, obs_dim, ent_dim` |

- `N_max = 7` (4on4 ⇒ 7 other actors; 1v1 is the **same** path with more masking).
- **Model input** = `[obs | masked_pool(entities, ent_mask) | audio | team]` ⇒ self +
  enemy + teammate context ⇒ **BROAD, not move-only**.
- BC-only: by default the loader takes the **last real tick** of each window, so it works
  whether FEAT emits single-step BC rows (`bc_window=1`) or `K=64` sequence windows.
- Pad entity slots are **zeroed** (contract); invisible-but-known actors carry the belief
  block in their live fields per `feature_registry.yaml` `entity_observation`.

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

### Rebinding to FEAT's actual schema at review-time

The only thing that can need pinning is the **`act` column order** if FEAT diverges from
`shard_contract.ACT_COLS`. That is a one-object change — pass a `ShardSchema(act_cols=...)`
(see `test_rebind_schema_with_reordered_act_cols`). `obs`/`entities`/`audio`/`team` widths
and `N_max` are discovered from the shard, so no code change is needed for them.

`shard_contract.SHARD_CONTRACT_VERSION = "broad_bc.shard_contract.v1"` and
`EXPECTS_REGISTRY_VERSION = 2`. If FEAT's `meta.registry_version` differs from 2, that is a
hard mismatch to resolve before training.

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
pip install -r requirements.txt          # torch + numpy (system change — owner OK per CLAUDE.md)

# 1. FEAT must have emitted gold shards (the SHARD CONTRACT above) and a frozen
#    normalization_stats.json. Point the trainer at them:
SHARDS="$HOME/komodobots-gold/broad/shard-*.npz"
NORM="$HOME/komodobots-gold/norm/normalization_stats.json"

# 2. Train (CUDA auto-detected; fixed seed; checkpoint + metrics + model card emitted):
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
