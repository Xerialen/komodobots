"""shard_contract.py — the SHARD CONTRACT the broad-BC loader binds to.

DEPS-FREE (stdlib only) on purpose: both the torch trainer and the offline
stdlib smoke import this so they agree on exactly one schema.

=============================================================================
THE CONTRACT (what FEAT emits / what this trainer consumes)
=============================================================================
Authoritative source: `data/catalog/dataset_spec.yaml` (komodobots.dataset_spec.v1,
registry_version 2) + `data/catalog/feature_registry.yaml`. One *sample* = one
window of K ticks. FEAT (the parallel feature coder) materializes the windowed
gold tensors; this trainer reads them. Per dataset_spec `record_layout` a sample
is a group of NumPy arrays sharing a basename (WebDataset tar member or an .npz):

  key        ext            shape            dtype     meaning
  ---------  -------------  ---------------  --------  ------------------------------
  obs        obs.npy        [K, F_obs]       float32   normalized SELF features
                                                       (position+velocity+orientation+
                                                        player_resource+item+timing+
                                                        player_style + self team scalars)
  entities   entities.npy   [K, N_max, F_ent] float32  per OBSERVED-OTHER actor egocentric
                                                       vector (enemies + teammates) — the
                                                       enemy/team-aware channel
  ent_mask   ent_mask.npy   [K, N_max]       float32   1 = real other-actor slot, 0 = pad/absent
  audio      audio.npy      [K, F_audio]     float32   decayed spatial audio cues (optional)
  team       team.npy       [K, F_team]      float32   team-aggregate context (optional)
  act        act.npy        [K, F_act]       float32   ACTION TARGETS (the human usercmd)
  mask       mask.npy       [K]              float32   1 = real step, 0 = pad (loss-masked)
  weight     w.npy          [K]              float32   per-step loss weight = action confidence
  meta       json           -                -         {episode_id, demo_id, player_id, map_id,
                                                        start_tick, label_source, registry_version,
                                                        norm_artifact_version}

N_max = 7 (4on4 => 7 other actors; 1v1 is the SAME path, more masking).
The model INPUT is the concatenation [obs | pooled(entities, ent_mask) | audio | team]
=> the policy sees self + enemy + teammate context (BROAD), not movement-only.

This trainer is BC-only: it consumes single-step windows (bc_window=1 in
dataset_spec) by default — K can be >1 and we read the LAST real tick per window —
so it works whether FEAT emits K=1 BC rows or K=64 sequence windows.

=============================================================================
ACTION HEADS (broad usercmd, discretized) — OUTPUT
=============================================================================
The `act` row is the recovered usercmd (catalog `actions` table / feature_registry
`action` group): forwardmove, sidemove, upmove in [-1,1] (raw /400 in {-400..400}),
buttons-derived jump_button & attack_button in {0,1}, and the commanded view turn.
We clone it as a set of DISCRETE classification heads (MLMove-style, generalized
from the move-only 3 heads to the broad action):

  head      classes  source act column            encoding
  --------  -------  ---------------------------  ----------------------------------
  fwd       3        forwardmove  (sign)           {-:0, 0:1, +:2}  (back/none/fwd)
  side      3        sidemove     (sign)           {-:0, 0:1, +:2}  (left/none/right)
  up        3        upmove       (sign)           {-:0, 0:1, +:2}  (down/none/up=jump-as-up)
  jump      2        jump_button  (buttons & 2)    {0,1}
  attack    2        attack_button(buttons & 1)    {0,1}

(Turn / cmd_delta_yaw is left as a continuous AIM head TODO — see ACTION_HEADS;
 the broad button/attack heads are what make this NOT move-only.)

=============================================================================
TOLERANCE / REBIND
=============================================================================
FEAT's *exact* per-feature column ORDER inside obs/entities is frozen by
feature_registry.yaml at review-time. Until then this module ships:
  * the EXPECTED widths/keys (so synthetic shards match the layout), and
  * `ShardSchema`, a small config object the loader/trainer accept so at
    review-time we bind to FEAT's real `obs_dim` / `ent_dim` / `N_max` / action
    column indices by reading the shard's own `meta` (and the registry) — no code
    change, just a schema object.
The loader NEVER assumes a fixed obs/ent width: it reads it from the shard.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


# --- contract version (bump if the key set / head set changes) --------------
SHARD_CONTRACT_VERSION = "broad_bc.shard_contract.v1"
EXPECTS_REGISTRY_VERSION = 2          # must match feature_registry.yaml / dataset_spec.yaml

# --- array keys (dataset_spec record_layout) --------------------------------
KEY_OBS = "obs"
KEY_ENTITIES = "entities"
KEY_ENT_MASK = "ent_mask"
KEY_AUDIO = "audio"
KEY_TEAM = "team"
KEY_ACT = "act"
KEY_MASK = "mask"
KEY_WEIGHT = "weight"
KEY_META = "meta"

# Optional channels: a shard MAY omit these (1v1 / ablation); the loader zero-fills.
OPTIONAL_KEYS = (KEY_AUDIO, KEY_TEAM, KEY_WEIGHT)

# --- default geometry (from dataset_spec.yaml) ------------------------------
DEFAULT_N_MAX = 7                     # entity_max.N_max (4on4 = 7 other actors)

# Reference action-column order inside `act` (feature_registry `action` group,
# leakage_safe:false targets). Used to build synthetic shards and as the DEFAULT
# binding; override via ShardSchema.act_cols when FEAT pins a different order.
ACT_COLS = (
    "forwardmove",        # [-1,1]  (= raw/400)
    "sidemove",           # [-1,1]
    "upmove",             # [-1,1]
    "jump_button",        # {0,1}   (buttons & 2)
    "attack_button",      # {0,1}   (buttons & 1)
    "cmd_delta_yaw_sin",  # [-1,1]  (continuous; reserved for AIM head, not cloned yet)
    "cmd_delta_yaw_cos",  # [-1,1]
)

# --- the discrete action heads we clone (broad) -----------------------------
# name -> (n_classes, source act column, kind)
#   kind "sign3" : 3-way back/none/fwd over a [-1,1] column (deadzone -> none)
#   kind "bin"   : 2-way {0,1} over a {0,1} column
ACTION_HEADS = (
    ("fwd",    3, "forwardmove",   "sign3"),
    ("side",   3, "sidemove",      "sign3"),
    ("up",     3, "upmove",        "sign3"),
    ("jump",   2, "jump_button",   "bin"),
    ("attack", 2, "attack_button", "bin"),
)

# Deadzone (in the [-1,1] normalized move space) under which a sign3 head is "none".
SIGN3_DEADZONE = 1e-3


@dataclass
class ShardSchema:
    """Configurable binding between FEAT's emitted shard and this trainer.

    The loader reads obs_dim / ent_dim / n_max FROM THE SHARD ARRAYS (never
    hard-coded), so the only thing that ever needs pinning at review-time is the
    `act` column order, if FEAT diverges from ACT_COLS. Everything else is
    discovered, which is what makes the loader tolerant.
    """
    n_max: int = DEFAULT_N_MAX
    act_cols: tuple = ACT_COLS
    # feature column NAMES (purely documentary / for the model card); the loader
    # does not need them to read arrays, but recording them pins the binding.
    obs_cols: tuple = field(default_factory=tuple)
    ent_cols: tuple = field(default_factory=tuple)
    expects_registry_version: int = EXPECTS_REGISTRY_VERSION
    # which `act` column index feeds each head (resolved from act_cols)
    def act_index(self, col: str) -> int:
        return self.act_cols.index(col)

    def heads(self):
        """(name, n_classes, act_col_index, kind) for every cloned head."""
        out = []
        for name, k, col, kind in ACTION_HEADS:
            out.append((name, k, self.act_index(col), kind))
        return out

    def to_dict(self) -> dict:
        d = asdict(self)
        d["contract_version"] = SHARD_CONTRACT_VERSION
        d["heads"] = [
            {"name": n, "classes": k, "act_col": col, "kind": kind}
            for (n, k, col, kind) in ACTION_HEADS
        ]
        return d


def load_registry_version(registry_yaml: Path) -> int | None:
    """Cheap stdlib read of `registry_version:` from feature_registry.yaml
    (no yaml dep — we only need the one integer)."""
    try:
        for ln in Path(registry_yaml).read_text(encoding="utf-8").splitlines():
            s = ln.strip()
            if s.startswith("registry_version:"):
                return int(s.split(":", 1)[1].strip().split()[0])
    except OSError:
        return None
    return None


def encode_sign3(value: float, deadzone: float = SIGN3_DEADZONE) -> int:
    """[-1,1] move component -> {0:back/left/down, 1:none, 2:fwd/right/up}."""
    if value > deadzone:
        return 2
    if value < -deadzone:
        return 0
    return 1


def encode_bin(value: float) -> int:
    """{0,1} button column -> class id (threshold at 0.5 so floats round-trip)."""
    return 1 if value >= 0.5 else 0


def encode_action_row(act_row, schema: ShardSchema) -> list:
    """One `act` vector -> the per-head integer class labels, in ACTION_HEADS order.

    `act_row` is anything indexable (list / tuple / 1-D numpy view). This is the
    SINGLE label-encoding used by BOTH the torch trainer and the stdlib smoke, so
    they cannot drift.
    """
    labels = []
    for (_name, _k, col_idx, kind) in schema.heads():
        v = float(act_row[col_idx])
        if kind == "sign3":
            labels.append(encode_sign3(v))
        elif kind == "bin":
            labels.append(encode_bin(v))
        else:  # pragma: no cover - guarded by ACTION_HEADS
            raise ValueError(f"unknown head kind {kind!r}")
    return labels


def head_names() -> list:
    return [h[0] for h in ACTION_HEADS]


def write_contract_doc(out_path: Path, schema: ShardSchema | None = None) -> Path:
    """Emit a machine-readable copy of the resolved contract (handy in run dirs)."""
    schema = schema or ShardSchema()
    doc = {
        "contract_version": SHARD_CONTRACT_VERSION,
        "authoritative_source": "data/catalog/dataset_spec.yaml + data/catalog/feature_registry.yaml",
        "expects_registry_version": EXPECTS_REGISTRY_VERSION,
        "array_keys": {
            "obs": "[K, F_obs] float32 — normalized SELF features",
            "entities": "[K, N_max, F_ent] float32 — per observed-other egocentric vector (enemy+teammate)",
            "ent_mask": "[K, N_max] float32 — 1=real other-actor, 0=pad",
            "audio": "[K, F_audio] float32 — optional decayed audio cues",
            "team": "[K, F_team] float32 — optional team-aggregate context",
            "act": "[K, F_act] float32 — usercmd action targets",
            "mask": "[K] float32 — 1=real step, 0=pad",
            "weight": "[K] float32 — per-step loss weight (action confidence)",
            "meta": "json — episode_id, demo_id, player_id, map_id, start_tick, "
                    "label_source, registry_version, norm_artifact_version",
        },
        "n_max_default": DEFAULT_N_MAX,
        "act_cols": list(schema.act_cols),
        "action_heads": [
            {"name": n, "classes": k, "act_col": col, "kind": kind}
            for (n, k, col, kind) in ACTION_HEADS
        ],
        "model_input": "[obs | pooled(entities, ent_mask) | audio | team] "
                       "=> BROAD (self + enemy + teammate), NOT move-only",
        "schema": schema.to_dict(),
    }
    Path(out_path).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return Path(out_path)
