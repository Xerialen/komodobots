"""core.py — deps-free core for the BROAD behavioral-cloning trainer.

Everything here is pure standard library so the OFFLINE CPU smoke can run with NO
torch / numpy (the host has neither when offline). The torch trainer
(`ml/train_broad_bc.py`) imports the SAME functions for split-by-demo, label
encoding, metrics and model-card assembly, so the offline smoke proves the real
contract — only the matmul backend differs (pure-Python here, torch on pinnacle).

Contents:
  * read_shard / iter_corpus  — read FEAT-format shards (.npz OR stdlib .json.gz),
                                flatten windows to BC rows, build the BROAD input
                                vector  [obs | pooled(entities, ent_mask) | audio | team].
  * split_by_demo             — held-out-DEMO split (never by frame; matches
                                dataset_spec split_policy.group_by_demo_id).
  * encode_labels             — per-head integer classes (via shard_contract).
  * head_accuracy / confusion — val metrics per head.
  * RefMLP + train_ref        — a tiny pure-Python MLP + SGD reference trainer used
                                ONLY by the offline smoke (seed-reproducible).
  * build_model_card          — git_sha / registry_version / norm artifact_version /
                                seed pinned model-card stub.
"""
from __future__ import annotations

import gzip
import json
import math
import random
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import shard_contract as SC


# =============================================================================
# Shard reading  (tolerant: .npz via numpy if present, else stdlib .json.gz)
# =============================================================================
def read_shard(path) -> dict:
    """Read one shard into a dict of nested python lists + meta. Works on:
      * `.parquet` — FEAT's REAL gold shard (one file = many windows from many
        episodes/demos; array columns stored FLATTENED, reshaped here via the
        table-level metadata FEAT stamps);
      * `.npz`     — the np.savez layout (one demo per file, arrays already shaped);
      * `.json.gz` / `.json` — the stdlib offline-smoke layout."""
    path = Path(path)
    name = path.name
    if name.endswith(".parquet"):
        return _read_parquet_shard(path)
    if name.endswith(".npz"):
        import numpy as np  # only when actually reading an npz
        z = np.load(path, allow_pickle=False)
        meta = json.loads(str(z["meta"])) if "meta" in z.files else {}
        out = {SC.KEY_META: meta}
        for k in (SC.KEY_OBS, SC.KEY_ENTITIES, SC.KEY_ENT_MASK, SC.KEY_AUDIO,
                  SC.KEY_TEAM, SC.KEY_ACT, SC.KEY_MASK, SC.KEY_WEIGHT):
            if k in z.files:
                out[k] = z[k].tolist()
        return out
    # stdlib path
    if name.endswith(".json.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    if name.endswith(".json"):
        return json.loads(path.read_text(encoding="utf-8"))
    raise ValueError(f"unrecognized shard extension: {path}")


def _read_parquet_shard(path) -> dict:
    """Read FEAT's REAL Parquet gold shard and reshape the FLATTENED list<float32>
    columns back to the nested [n_windows][K][...] arrays the loader consumes.

    FEAT packs MANY windows (and many demos) into one Parquet file and stores the
    per-window arrays row-major-flattened; the per-window shape (K, n_max, obs/ent/
    act dims) is stamped in the table-level metadata so the reshape is unambiguous
    and the loader still NEVER hard-codes a width. Per-window `demo_id` is returned
    as `demo_ids` so the group-by-demo split keys off the real demo (the .npz path
    carried a single demo_id per file; here many demos share a file)."""
    import pyarrow.parquet as pq  # ml dep; only imported when a .parquet is read

    t = pq.read_table(path)
    meta_kv = t.schema.metadata or {}

    def _m(key: str, default):
        v = meta_kv.get(("komodobots.shard." + key).encode())
        return v.decode() if v is not None else default

    K = int(_m("K", 1))
    n_max = int(_m("n_max", SC.DEFAULT_N_MAX))
    obs_dim = int(_m("obs_dim", 0))
    ent_dim = int(_m("ent_dim", 0))
    act_dim = int(_m("act_dim", 0))
    n_rows = t.num_rows
    names = set(t.schema.names)

    # Vectorized reshape: pull each FLATTENED list<float32> column straight into a
    # contiguous numpy array, then reshape to [n_windows, K, ...]. The original
    # pure-Python rebuild (`to_pylist()` + per-element `float(next(it))`) was
    # O(elements) and OOM'd / hung on a real shard (~0.9 B entity floats for a
    # 28-demo split); this is a couple of C-level passes. numpy is always present on
    # the .parquet path (the torch-trainer host); the deps-free smoke reads .json.gz.
    import numpy as np  # ml dep; parquet path only

    def _flat_f32(col_name):
        """Flattened float32 values of a FEAT list<float32> column — no Python-object
        intermediate (the killer was to_pylist on the ~0.9 B-float entity column)."""
        col = t.column(col_name)
        if col.null_count:
            raise ValueError(f"shard column {col_name!r} has nulls; contract is dense")
        parts = [ch.flatten().to_numpy(zero_copy_only=False) for ch in col.chunks]
        flat = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
        return np.ascontiguousarray(flat, dtype=np.float32)

    def _reshape(col_name, *inner):
        """FLATTENED list<float32> column -> ndarray [n_rows, *inner] (row-major)."""
        return _flat_f32(col_name).reshape((n_rows,) + tuple(inner))

    out: dict = {}
    if SC.KEY_OBS in names and obs_dim:
        out[SC.KEY_OBS] = _reshape(SC.KEY_OBS, K, obs_dim)               # [n][K][S]
    if SC.KEY_ENTITIES in names and ent_dim:
        out[SC.KEY_ENTITIES] = _reshape(SC.KEY_ENTITIES, K, n_max, ent_dim)
        out[SC.KEY_ENT_MASK] = _reshape(SC.KEY_ENT_MASK, K, n_max)       # [n][K][Nm]
    if SC.KEY_ACT in names and act_dim:
        out[SC.KEY_ACT] = _reshape(SC.KEY_ACT, K, act_dim)              # [n][K][A]
    if SC.KEY_MASK in names:
        out[SC.KEY_MASK] = _reshape(SC.KEY_MASK, K)                     # [n][K]
    if SC.KEY_WEIGHT in names:
        out[SC.KEY_WEIGHT] = _reshape(SC.KEY_WEIGHT, K)                 # [n][K]
    # audio/team are absent in a .qwd FEAT shard (folded/deferred) — leave them out;
    # the loader zero-fills.
    if "demo_id" in names:
        out[SC.KEY_DEMO_IDS] = [str(d) for d in t.column("demo_id").to_pylist()]
    if "episode_id" in names:
        out[SC.KEY_EPISODE_IDS] = [int(e) for e in t.column("episode_id").to_pylist()]

    out[SC.KEY_META] = {
        "demo_id": (out.get(SC.KEY_DEMO_IDS, ["?"])[0] if n_rows else "?"),
        "n_windows": n_rows,
        "K": K, "n_max": n_max,
        "obs_dim": obs_dim, "ent_dim": ent_dim, "act_dim": act_dim,
        "registry_version": int(_m("registry_version", SC.EXPECTS_REGISTRY_VERSION)),
        "norm_artifact_version": _m("norm_artifact_version", "UNSET"),
        "map_id": _m("map", "UNSET"),
        "contract_version": _m("contract", SC.SHARD_CONTRACT_VERSION),
        "has_audio": _m("has_audio", "false") == "true",
        "has_team": _m("has_team", "false") == "true",
    }
    return out


def _last_real_tick(window_mask) -> int:
    """Index of the last real (mask==1) tick in a window; 0 if all pad."""
    idx = 0
    for i, m in enumerate(window_mask):
        if float(m) >= 0.5:
            idx = i
    return idx


def _pool_entities(ent_window_tick, em_window_tick) -> tuple:
    """Mean-pool the VISIBLE other-actor vectors at one tick + a presence count.

    Returns (pooled_vector, n_visible). Mean over mask==1 rows (DeepSets-style
    permutation-invariant pooling, the contract's pooling op). When nothing is
    visible the pooled vector is zeros (belief/zeroed contract)."""
    # len()-based guard (not truthiness): ent_window_tick may be a numpy row now
    # that the parquet loader returns ndarrays — `if not ndarray` raises.
    if ent_window_tick is None or len(ent_window_tick) == 0:
        return [], 0
    ent_dim = len(ent_window_tick[0])
    pooled = [0.0] * ent_dim
    n_vis = 0
    for slot_vec, m in zip(ent_window_tick, em_window_tick):
        if float(m) >= 0.5:
            n_vis += 1
            for c in range(ent_dim):
                pooled[c] += float(slot_vec[c])
    if n_vis:
        for c in range(ent_dim):
            pooled[c] /= n_vis
    return pooled, n_vis


def shard_to_rows(shard: dict, schema: SC.ShardSchema):
    """Flatten a shard's windows into BC rows.

    Yields dicts: {x: broad_input_vector, y: [per-head class ids], demo_id,
    weight}. The BROAD input vector is
        [ self_obs | pooled_entities | n_vis_frac | audio | team ]
    i.e. it INCLUDES the observed-other / enemy-team channel (pooled_entities) —
    this is what makes the trainer broad, not move-only."""
    meta = shard.get(SC.KEY_META, {})
    default_demo = meta.get("demo_id", "?")
    n_max = meta.get("n_max", schema.n_max)

    obs = shard[SC.KEY_OBS]
    ents = shard.get(SC.KEY_ENTITIES)
    ems = shard.get(SC.KEY_ENT_MASK)
    audio = shard.get(SC.KEY_AUDIO)
    team = shard.get(SC.KEY_TEAM)
    act = shard[SC.KEY_ACT]
    mask = shard.get(SC.KEY_MASK)
    weight = shard.get(SC.KEY_WEIGHT)
    # Parquet shards carry a per-WINDOW demo id (many demos per file); the .npz path
    # has one demo per file, so fall back to meta.demo_id.
    demo_ids = shard.get(SC.KEY_DEMO_IDS)

    n_windows = len(obs)
    for wi in range(n_windows):
        wmask = mask[wi] if mask is not None else [1.0] * len(obs[wi])
        ti = _last_real_tick(wmask)
        if float(wmask[ti]) < 0.5:
            continue  # all-pad window
        demo_id = demo_ids[wi] if demo_ids is not None else default_demo
        x = list(map(float, obs[wi][ti]))             # self obs
        if ents is not None and ems is not None:
            pooled, n_vis = _pool_entities(ents[wi][ti], ems[wi][ti])
            x += pooled                                # observed-other channel
            x.append(n_vis / max(n_max, 1))           # presence fraction
        if audio is not None:
            x += list(map(float, audio[wi][ti]))
        if team is not None:
            x += list(map(float, team[wi][ti]))
        y = SC.encode_action_row(act[wi][ti], schema)
        w = float(weight[wi][ti]) if weight is not None else 1.0
        yield {"x": x, "y": y, "demo_id": demo_id, "weight": w}


def iter_corpus(shard_paths, schema: SC.ShardSchema):
    """Read every shard, return (rows, input_dim). Rows is a list of the dicts
    above. input_dim is asserted consistent across rows."""
    rows = []
    in_dim = None
    for p in shard_paths:
        shard = read_shard(p)
        for r in shard_to_rows(shard, schema):
            if in_dim is None:
                in_dim = len(r["x"])
            elif len(r["x"]) != in_dim:
                raise ValueError(
                    f"inconsistent input dim {len(r['x'])} != {in_dim} in {p}")
            rows.append(r)
    return rows, (in_dim or 0)


# =============================================================================
# Split by demo  (dataset_spec split_policy.group_by_demo_id)
# =============================================================================
def split_by_demo(rows, val_frac: float, seed: int):
    """Held-out-DEMO split. Returns (train_rows, val_rows, val_demos).

    Consecutive ticks of one demo are near-duplicates -> a frame-level split leaks.
    We split whole demos (deterministic under `seed`)."""
    demos = sorted({r["demo_id"] for r in rows})
    rng = random.Random(seed)
    rng.shuffle(demos)
    n_val = max(1, int(round(val_frac * len(demos)))) if len(demos) > 1 else 0
    val_demos = set(demos[:n_val])
    tr = [r for r in rows if r["demo_id"] not in val_demos]
    va = [r for r in rows if r["demo_id"] in val_demos]
    return tr, va, sorted(val_demos)


# =============================================================================
# Metrics (per head)
# =============================================================================
def head_accuracy(preds, rows, head_idx) -> float:
    if not rows:
        return 0.0
    correct = sum(1 for p, r in zip(preds, rows) if p[head_idx] == r["y"][head_idx])
    return correct / len(rows)


def majority_baseline(rows, head_idx, n_classes) -> float:
    """Accuracy of always predicting the most common class (sanity floor)."""
    if not rows:
        return 0.0
    counts = [0] * n_classes
    for r in rows:
        counts[r["y"][head_idx]] += 1
    return max(counts) / len(rows)


# =============================================================================
# Pure-python reference MLP + SGD  (OFFLINE SMOKE ENGINE — not used on pinnacle)
# =============================================================================
def _zeros(n):
    return [0.0] * n


def _matvec(W, x):
    # W: out x in (list of rows), x: in -> out
    return [sum(wij * xj for wij, xj in zip(row, x)) for row in W]


def _softmax(z):
    m = max(z)
    ex = [math.exp(v - m) for v in z]
    s = sum(ex)
    return [e / s for e in ex]


@dataclass
class RefMLP:
    """Minimal multi-head MLP (1 hidden ReLU layer) in pure python.

    Mirrors the torch BroadBCPolicy: a shared trunk + one linear head per action
    head. Trained by plain SGD with a fixed seed so two runs give identical loss.
    Small by construction (smoke only)."""
    in_dim: int
    hidden: int
    head_dims: list   # n_classes per head, in ACTION_HEADS order
    seed: int = 0

    def __post_init__(self):
        rng = random.Random(self.seed)
        def mat(o, i, scale):
            return [[rng.uniform(-scale, scale) for _ in range(i)] for _ in range(o)]
        s1 = 1.0 / math.sqrt(self.in_dim)
        sh = 1.0 / math.sqrt(self.hidden)
        self.W1 = mat(self.hidden, self.in_dim, s1)
        self.b1 = _zeros(self.hidden)
        self.Wh = [mat(k, self.hidden, sh) for k in self.head_dims]
        self.bh = [_zeros(k) for k in self.head_dims]

    # --- forward ----------------------------------------------------------
    def _trunk(self, x):
        z = _matvec(self.W1, x)
        h = [zi + bi for zi, bi in zip(z, self.b1)]
        a = [v if v > 0 else 0.0 for v in h]      # ReLU
        relu_mask = [1.0 if v > 0 else 0.0 for v in h]
        return a, relu_mask

    def forward(self, x):
        a, relu_mask = self._trunk(x)
        logits = []
        for Wk, bk in zip(self.Wh, self.bh):
            zk = _matvec(Wk, a)
            logits.append([zi + bi for zi, bi in zip(zk, bk)])
        return logits, a, relu_mask

    def predict(self, x):
        logits, _, _ = self.forward(x)
        return [max(range(len(lg)), key=lg.__getitem__) for lg in logits]


def _ce_loss_and_grad(logits, y):
    """Sum of per-head cross-entropy; returns (loss, [dlogits per head])."""
    loss = 0.0
    dlogits = []
    for lg, yc in zip(logits, y):
        p = _softmax(lg)
        loss += -math.log(max(p[yc], 1e-12))
        dl = list(p)
        dl[yc] -= 1.0
        dlogits.append(dl)
    return loss, dlogits


def train_ref(rows, in_dim, head_dims, *, hidden=24, epochs=8, lr=0.1, seed=0,
              batch=64, log=None):
    """Train the reference MLP by mini-batch SGD. Deterministic under `seed`
    (data shuffle + init both seeded). Returns (model, history)."""
    model = RefMLP(in_dim=in_dim, hidden=hidden, head_dims=list(head_dims), seed=seed)
    rng = random.Random(seed + 777)
    n = len(rows)
    history = []
    for ep in range(epochs):
        order = list(range(n))
        rng.shuffle(order)
        ep_loss = 0.0
        nb = 0
        for bstart in range(0, n, batch):
            idxs = order[bstart:bstart + batch]
            # accumulate grads over the batch
            gW1 = [[0.0] * in_dim for _ in range(model.hidden)]
            gb1 = _zeros(model.hidden)
            gWh = [[[0.0] * model.hidden for _ in range(k)] for k in head_dims]
            gbh = [_zeros(k) for k in head_dims]
            bloss = 0.0
            for i in idxs:
                x = rows[i]["x"]; y = rows[i]["y"]; w = rows[i].get("weight", 1.0)
                logits, a, relu_mask = model.forward(x)
                loss, dlogits = _ce_loss_and_grad(logits, y)
                bloss += w * loss
                # backprop heads -> hidden
                da = _zeros(model.hidden)
                for hidx, (dl, Wk) in enumerate(zip(dlogits, model.Wh)):
                    for c in range(head_dims[hidx]):
                        g = w * dl[c]
                        gbh[hidx][c] += g
                        row = gWh[hidx][c]
                        for j in range(model.hidden):
                            row[j] += g * a[j]
                            da[j] += g * Wk[c][j]
                # through ReLU -> input layer
                for j in range(model.hidden):
                    dz = da[j] * relu_mask[j]
                    gb1[j] += dz
                    rowW = gW1[j]
                    for k in range(in_dim):
                        rowW[k] += dz * x[k]
            m = max(len(idxs), 1)
            # SGD step (mean over batch)
            for j in range(model.hidden):
                model.b1[j] -= lr * gb1[j] / m
                rW = model.W1[j]; gW = gW1[j]
                for k in range(in_dim):
                    rW[k] -= lr * gW[k] / m
            for hidx in range(len(head_dims)):
                for c in range(head_dims[hidx]):
                    model.bh[hidx][c] -= lr * gbh[hidx][c] / m
                    rW = model.Wh[hidx][c]; gW = gWh[hidx][c]
                    for j in range(model.hidden):
                        rW[j] -= lr * gW[j] / m
            ep_loss += bloss / m
            nb += 1
        rec = {"epoch": ep, "train_loss": round(ep_loss / max(nb, 1), 6)}
        history.append(rec)
        if log:
            log(f"ep{ep:02d} train_loss={rec['train_loss']:.6f}")
    return model, history


def evaluate_heads(model, rows, head_specs):
    """Per-head val accuracy + majority baseline. head_specs = list of
    (name, n_classes)."""
    preds = [model.predict(r["x"]) for r in rows]
    out = {}
    for hidx, (name, k) in enumerate(head_specs):
        out[name] = {
            "val_acc": round(head_accuracy(preds, rows, hidx), 6),
            "majority_baseline": round(majority_baseline(rows, hidx, k), 6),
        }
    return out


# =============================================================================
# Model card
# =============================================================================
def git_sha(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:  # noqa: BLE001
        return "UNKNOWN"


def build_model_card(*, run_kind, schema: SC.ShardSchema, in_dim, hidden,
                     head_specs, metrics, history, seed, repo_root,
                     norm_artifact_version="UNSET", registry_version=None,
                     dataset_version="UNSET", torch_version=None, device=None,
                     extra=None) -> dict:
    """Assemble the model-card stub. Pins the reproducibility quadruple
    (git_sha, registry_version, norm artifact_version, seed) per the
    normalization_stats template's model-card requirement."""
    card = {
        # identifies the MODEL-CARD format itself (distinct from the data `schema`
        # object below); renamed from "schema" to avoid the two keys colliding.
        "card_schema": "komodobots.model_card.broad_bc.v1",
        "run_kind": run_kind,                      # "cpu_smoke" | "gpu_train"
        "task": "broad behavioral cloning (dm3 4on4 stand-in; enemy/team-aware)",
        "input_is_broad": True,
        "input_includes_observed_others": True,    # entities channel pooled into x
        "input_includes_team_context": True,
        "move_only": False,
        # --- reproducibility quadruple (model-card requirement) ---
        "git_sha": git_sha(Path(repo_root)),
        "registry_version": registry_version if registry_version is not None
                            else schema.expects_registry_version,
        "norm_artifact_version": norm_artifact_version,
        "seed": seed,
        "dataset_version": dataset_version,
        # --- shape / contract ---
        "shard_contract_version": SC.SHARD_CONTRACT_VERSION,
        "input_dim": in_dim,
        "hidden": hidden,
        "action_heads": [{"name": n, "classes": k} for (n, k) in head_specs],
        "model_input_composition": "[obs | pooled(entities, ent_mask) | n_vis_frac | audio | team]",
        "schema": schema.to_dict(),
        # --- results ---
        "metrics": metrics,
        "train_history": history,
    }
    if torch_version is not None:
        card["torch"] = torch_version
    if device is not None:
        card["device"] = device
    if extra:
        card.update(extra)
    return card
