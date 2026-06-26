"""shard_contract.py — the SHARD CONTRACT the broad-BC loader binds to.

DEPS-FREE (stdlib only) on purpose: both the torch trainer and the offline
stdlib smoke import this so they agree on exactly one schema.

=============================================================================
THE CONTRACT (what FEAT emits / what this trainer consumes)
=============================================================================
Authoritative source: `data/catalog/dataset_spec.yaml` (komodobots.dataset_spec.v1,
registry_version 5) + `data/catalog/feature_registry.json`. One *sample* = one
window of K ticks. FEAT (the parallel feature coder) materializes the windowed
gold tensors; this trainer reads them.

FEAT's REAL build (`ml/pipeline/build_features.py shard`) emits ONE **Parquet**
file holding MANY windows (and many demos), array columns stored row-major-
FLATTENED as `list<float32>`; `core._read_parquet_shard` reshapes them back via
the table-level shape metadata FEAT stamps (so the loader still never hard-codes a
width). The `.npz` / `.json.gz` layouts (one demo per file, arrays pre-shaped) are
also supported — the smoke uses them. Per dataset_spec `record_layout` a sample is
this set of arrays:

  key          shape              dtype    meaning
  -----------  -----------------  -------  ----------------------------------------
  obs          [K, F_obs]         float32  normalized single-tick SELF features (position+
                                          velocity+orientation+player_resource + the appended
                                          turn-direction (v3) + route-conditioning goal (v4)
                                          features; F_obs=21 — EXPECTS_SELF_DIM. Carried per-
                                          tick for provenance / the reject guard;
                                          self_history[...][-F_obs:] equals this tick's obs.)
  self_history [H*F_obs]          float32  v5 SEQUENCE input: ONE FLAT last-H-tick SELF
                                          history PER WINDOW — for the window's LAST REAL tick
                                          (H=SELF_HISTORY=16, oldest->newest, left-pad-repeat-
                                          first at window start). H*F_obs=336 =
                                          EXPECTS_SELF_HISTORY_DIM. THIS is what the v5 policy
                                          (GRU) consumes in place of the single-tick SELF. The
                                          trainer/loader only ever read the last-real-tick
                                          history, so the build stores JUST it (not a per-tick
                                          [K, H*F_obs]) — 64x less memory, identical training
                                          data; the loader reshapes the column to [n, H*F_obs].
  entities   [K, N_max, F_ent] float32  per OBSERVED-OTHER actor egocentric vector
                                        (enemies + teammates; F_ent=13). The
                                        enemy/team-aware channel; team is FOLDED IN
                                        as the per-entity `is_teammate` flag.
  ent_mask   [K, N_max]       float32   1 = real other-actor slot, 0 = pad/absent
  act        [K, F_act]       float32   ACTION TARGETS (human usercmd); F_act=5 =
                                        fwd/side/up move + jump + attack (the cloned
                                        heads). Indexed BY NAME, so width 5 binds.
  mask       [K]              float32   1 = real step, 0 = pad (loss-masked)
  weight     [K]              float32   per-step loss weight = action confidence
                                        (0 on pad / interpolated frames)
  demo_ids   [n_windows]      (str)     per-WINDOW demo id — group-by-demo split key
                                        (Parquet packs many demos per file)
  meta       dict             -         {demo_id, n_windows, K, n_max, obs_dim,
                                        ent_dim, act_dim, registry_version,
                                        norm_artifact_version, map_id, has_audio,
                                        has_team}

OPTIONAL / ABSENT in a .qwd FEAT shard:
  audio  [K, F_audio]  — .qwd carries NO audio cues -> DEFERRED (shard omits it).
  team   [K, F_team]   — team is folded into entity `is_teammate` -> shard omits it.
The loader treats audio/team as optional and zero-fills (F_aux = 0 for a .qwd shard).

N_max = 7 (4on4 => 7 other actors; 1v1 is the SAME path, more masking).
The model INPUT is [self_history | pooled(entities, ent_mask) | audio | team] (audio/team
width 0 when absent) => the policy sees a SHORT SELF HISTORY (sequence-aware, so it can
express temporal patterns like the bunnyhop jump-on-landing cadence) + enemy + teammate
context (BROAD), not movement-only and not single-tick. self_history[...][-SELF_DIM:] is
the current single-tick (goal-conditioned) SELF, so the broad/enemy-aware + goal signal
is preserved.

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
feature_registry.json at review-time. Until then this module ships:
  * the EXPECTED widths/keys (so synthetic shards match the layout), and
  * `ShardSchema`, a small config object the loader/trainer accept so at
    review-time we bind to FEAT's real `obs_dim` / `ent_dim` / `N_max` / action
    column indices by reading the shard's own `meta` (and the registry) — no code
    change, just a schema object.
The loader NEVER assumes a fixed obs/ent width: it reads it from the shard.
"""
from __future__ import annotations

import logging
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# The obs-vector layout dims (SELF_DIM, the v5 history dims, REQUIRED_NORM_KEYS, the registry
# version, N_max) are the GENERATED single source of truth — data/catalog/feature_registry.json
# `observation`, emitted to scripts/features/registry_constants_generated.py by
# scripts/generate_from_registry.py. This contract IMPORTS them (aliased to the EXPECTS_* names)
# instead of hand-copying, so a shard, the live encoder and this trainer can never disagree with
# the registry. Self-bootstrap the repo root onto sys.path so the import resolves regardless of
# cwd; still deps-free stdlib (the generated module is pure constants).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from scripts.features.registry_constants_generated import (  # noqa: E402
    REGISTRY_VERSION as EXPECTS_REGISTRY_VERSION,
    SELF_DIM as EXPECTS_SELF_DIM,
    SELF_HISTORY as EXPECTS_SELF_HISTORY,
    SELF_HISTORY_DIM as EXPECTS_SELF_HISTORY_DIM,
    REQUIRED_NORM_KEYS,
    N_MAX_DEFAULT as DEFAULT_N_MAX,
)



LOGGER = logging.getLogger(__name__)
# --- contract version (bump if the key set / head set changes) --------------
SHARD_CONTRACT_VERSION = "broad_bc.shard_contract.v1"
# registry_version 5 (GRU over a goal-conditioned short history): the SELF channels stay
# the 21-wide v4 goal-conditioned vector (the frozen-16 + the v3 turn-direction pair
# yaw_rate_z + face_vel_angle_norm + the v4 route-conditioning goal triple
# goal_heading_sincos[2] + goal_dist_norm), but a NEW per-tick `self_history` field carries
# the FLAT [SELF_HISTORY * SELF_DIM] short history (the last SELF_HISTORY SELF ticks,
# oldest->newest) the policy now consumes in place of the single-tick SELF (jump cadence is
# a TEMPORAL pattern the single tick could not express). v5 unifies dev's #335
# goal-conditioning (SELF_DIM 21) with the self-aim sequence/GRU line (the history). A
# pre-v5 shard (no self_history field, a wrong flat-dim, or the 18-wide no-goal SELF) MUST
# be rejected loudly — the registry-version equality guard + the explicit self-history
# flat-dim guard + the obs_dim channel-count guard below do that. The v4 goal features are
# sincos + /diagonal identity, so they add NO new required norm key.
# EXPECTS_REGISTRY_VERSION is IMPORTED above (= registry observation REGISTRY_VERSION); must
# match feature_registry.json / dataset_spec.yaml (the linkage is validated by generate_from_registry.py).
# expected SELF (obs) channel count — agent_observation.SELF_DIM. 21-wide goal-conditioned
# v4 layout (frozen-16 + turn-direction pair + route-conditioning goal triple); the per-tick
# `obs` column carries it and each of the SELF_HISTORY history rows is one such 21-wide SELF
# vector. IMPORTED above (deps-free, single source = registry observation SELF_DIM) so the loader
# can reject a shard whose declared obs_dim does not match the SELF layout even if its
# registry_version label was hand-edited to 5.
# the short-history length the v5 sequence-aware policy consumes (== agent_observation.
# SELF_HISTORY). The model input replaces the single-tick SELF with the FLAT history of
# these many ticks; the flattened width is EXPECTS_SELF_HISTORY * EXPECTS_SELF_DIM.
# EXPECTS_SELF_HISTORY is IMPORTED above (= registry observation SELF_HISTORY).
# expected FLAT self-history width PER ROW = EXPECTS_SELF_HISTORY * EXPECTS_SELF_DIM (336).
# self_history is stored as ONE [HD] history per window (the last-real-tick history), so a
# row's self_history length must be EXACTLY this HD. IMPORTED above (deps-free, single source =
# registry observation SELF_HISTORY * SELF_DIM = 336) so the loader can reject a shard whose
# `self_history` width does not match the v5 layout — both a too-narrow (wrong history length, or
# a 16-wide-SELF history) AND a too-wide (the OLD per-tick [K*HD] storage, or a hand-edited
# registry_version=5 on a single-tick shard) — even if its registry_version label says 5.
# normalization keys the SELF path REQUIRES under per_map[<map>]. yaw_rate_z (v3) z-scores
# against `yaw_rate`; a stats artifact missing it would silently de-normalize the appended
# turn-rate feature, so its absence is a hard reject (not a zero-fill). The v4 goal features
# need NO fitted key (sincos + identity), and v5 adds no channel, so REQUIRED_NORM_KEYS is
# unchanged (each history row z-scores yaw_rate_z against the SAME `yaw_rate` key).
# REQUIRED_NORM_KEYS is IMPORTED above (= registry observation.required_norm_keys).

# --- array keys (dataset_spec record_layout) --------------------------------
KEY_OBS = "obs"
# v5: the FLAT self-history field [SELF_HISTORY*SELF_DIM] = ONE history per window (the
# last-real-tick history, oldest->newest). This is what the v5 policy consumes as its SELF
# input (the single-tick `obs` stays per-tick for provenance / the reject guard;
# self_history[-SELF_DIM:] == the last-real-tick obs).
KEY_SELF_HISTORY = "self_history"
KEY_ENTITIES = "entities"
KEY_ENT_MASK = "ent_mask"
KEY_AUDIO = "audio"
KEY_TEAM = "team"
KEY_ACT = "act"
KEY_MASK = "mask"
KEY_WEIGHT = "weight"
KEY_META = "meta"
# Per-WINDOW demo id (Parquet shards pack many demos in one file, unlike the .npz
# one-demo-per-file layout). When present, the loader groups the split by THIS
# (so no demo straddles train/val) instead of the single meta.demo_id.
KEY_DEMO_IDS = "demo_ids"
# Per-window episode id (provenance; not required by the loader).
KEY_EPISODE_IDS = "episode_ids"

# Optional channels: a shard MAY omit these and the loader zero-fills / falls back.
#   audio, team  — .qwd has no audio cues and folds team into entity is_teammate
#                  (FEAT's ACTUAL schema), so a real .qwd shard omits BOTH.
#   weight       — defaults to 1.0 per step if absent.
OPTIONAL_KEYS = (KEY_AUDIO, KEY_TEAM, KEY_WEIGHT)

# --- default geometry (from dataset_spec.yaml) ------------------------------
# DEFAULT_N_MAX is IMPORTED above (= registry observation.n_max; entity_max.N_max, 4on4 = 7).

# Reference action-column order inside `act` (feature_registry `action` group,
# leakage_safe:false targets). Used to build synthetic shards and as the DEFAULT
# binding; override via ShardSchema.act_cols when FEAT pins a different order.
# NB: FEAT's REAL .qwd shard emits ONLY the first 5 (the cloned heads) — the two
# reserved continuous turn columns (indices 5,6) are NOT cloned yet, and since the
# loader indexes act columns BY NAME via ShardSchema.act_index, a width-5 `act`
# binds the fwd/side/up/jump/attack heads correctly with no rebind. ACT_COLS keeps
# all 7 so the synthetic smoke can also exercise the (future) turn columns.
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


def check_shard_meta(meta: dict, *, where: str = "shard") -> None:
    """Reject a stale / mislabelled FEAT shard BEFORE it binds to the v5 layout.

    Raises ValueError if, for the registry_version this contract EXPECTS:
      * meta.registry_version is present and != EXPECTS_REGISTRY_VERSION (the stale-shard
        guard — a pre-v5 shard, e.g. a v4 single-tick-SELF shard with no self_history
        field, can no longer pass as the v5 sequence-aware layout), OR
      * meta.obs_dim is present and != EXPECTS_SELF_DIM (catches an artifact whose SELF
        channel count is not the 21-wide goal-conditioned layout — e.g. an 18-wide no-goal
        SELF, or a 16-channel pre-turn-direction one), OR
      * meta.self_history_dim is present and != EXPECTS_SELF_HISTORY_DIM (catches a
        v5-LABELLED shard whose PER-ROW flat self-history width is not SELF_HISTORY*SELF_DIM
        — a wrong history length, a hand-edited registry_version=5 on a single-tick shard,
        OR the OLD per-tick [K*SELF_HISTORY*SELF_DIM] storage). This is the #313-style
        explicit reject for the v5 sequence field, OR
      * meta.registry_version >= EXPECTS_REGISTRY_VERSION (a v5+ shard) but self_history_dim
        is OMITTED. For pre-v5 fields the "omit == match" leniency below holds, but a shard
        LABELLED v5 MUST carry the self_history contract — without self_history_dim the loader
        would silently fall back to the 21-wide single-tick `obs` (x_len=21) and a v5-labelled
        shard would masquerade as the pre-v5 width. So v5 makes self_history_dim REQUIRED, not
        optional. (The matching `self_history` ARRAY presence is enforced at row-build time by
        require_self_history_present, which both the trainer and the deps-free loader call.)

    A pre-v5 (registry_version < 5 or absent) shard that OMITS a field is treated as matching
    (legacy / minimal smoke shards): there we only reject on a PRESENT, MISMATCHED value. Pure
    stdlib (no torch); the trainer and any eval call the SAME function so the reject rule cannot
    drift. `where` is woven into the message for provenance (the shard path / demo id)."""
    rv = meta.get("registry_version")
    if rv is not None and int(rv) != EXPECTS_REGISTRY_VERSION:
        raise ValueError(
            f"shard registry_version {rv} != expected {EXPECTS_REGISTRY_VERSION} "
            f"({where}); refusing to train on a mismatched FEAT shard "
            f"(a pre-v5 single-tick-SELF shard must not bind to the v5 sequence-aware "
            f"self_history layout)")
    od = meta.get("obs_dim")
    if od is not None and int(od) != EXPECTS_SELF_DIM:
        raise ValueError(
            f"shard obs_dim {od} != expected SELF channel count {EXPECTS_SELF_DIM} "
            f"({where}); the registry_version {EXPECTS_REGISTRY_VERSION} SELF vector is "
            f"21-wide (v3 turn-direction yaw_rate_z + face_vel_angle_norm, then the v4 "
            f"route-conditioning goal_heading_sincos + goal_dist_norm) — refusing a "
            f"{od}-channel SELF artifact")
    shd = meta.get("self_history_dim")
    if shd is not None and int(shd) != EXPECTS_SELF_HISTORY_DIM:
        raise ValueError(
            f"shard self_history_dim {shd} != expected {EXPECTS_SELF_HISTORY_DIM} "
            f"(= SELF_HISTORY {EXPECTS_SELF_HISTORY} * SELF_DIM {EXPECTS_SELF_DIM}) "
            f"({where}); the registry_version {EXPECTS_REGISTRY_VERSION} policy consumes "
            f"the FLAT last-{EXPECTS_SELF_HISTORY}-tick SELF history (ONE {EXPECTS_SELF_HISTORY_DIM}"
            f"-wide vector per window) — refusing a {shd}-wide self_history artifact "
            f"(a wrong history length, or the old per-tick K*HD storage)")
    # v5 makes the self_history CONTRACT mandatory: a shard whose registry_version says v5+
    # MUST declare self_history_dim (== HD), else the loader would silently degrade to the
    # 21-wide single-tick obs. Pre-v5 shards keep the omit==match leniency above.
    if rv is not None and int(rv) >= EXPECTS_REGISTRY_VERSION and shd is None:
        raise ValueError(
            f"shard registry_version {rv} (v{EXPECTS_REGISTRY_VERSION}+) is MISSING "
            f"self_history_dim ({where}); a v{EXPECTS_REGISTRY_VERSION} shard MUST declare the "
            f"FLAT self-history width {EXPECTS_SELF_HISTORY_DIM} (= SELF_HISTORY "
            f"{EXPECTS_SELF_HISTORY} * SELF_DIM {EXPECTS_SELF_DIM}) — refusing to fall back to "
            f"the {EXPECTS_SELF_DIM}-wide single-tick obs (a v{EXPECTS_REGISTRY_VERSION}-labelled "
            f"shard must not masquerade as the pre-v{EXPECTS_REGISTRY_VERSION} width)")


def require_self_history_present(meta: dict, has_self_history: bool, *,
                                 where: str = "shard") -> None:
    """Enforce, at ROW-BUILD time, that a v5+ shard actually carries the `self_history`
    ARRAY (not just the meta width). For registry_version >= EXPECTS_REGISTRY_VERSION the
    policy SELF input IS the flat self_history; if the array is absent the row builders would
    silently fall back to the single-tick `obs` (x_len == EXPECTS_SELF_DIM == 21) instead of
    the required EXPECTS_SELF_HISTORY_DIM (336). So a v5-labelled shard lacking the array is a
    hard contract error, NOT a fallback. Pre-v5 (or unlabelled) shards keep the single-tick
    fallback. Pure stdlib; BOTH the deps-free loader (core.shard_to_rows) and the torch trainer
    (train_broad_bc.rows_to_tensors) call this so the rule cannot drift."""
    rv = meta.get("registry_version")
    if rv is not None and int(rv) >= EXPECTS_REGISTRY_VERSION and not has_self_history:
        raise ValueError(
            f"shard registry_version {rv} (v{EXPECTS_REGISTRY_VERSION}+) is MISSING the "
            f"`{KEY_SELF_HISTORY}` array ({where}); the v{EXPECTS_REGISTRY_VERSION} policy "
            f"SELF input is the FLAT last-{EXPECTS_SELF_HISTORY}-tick history "
            f"({EXPECTS_SELF_HISTORY_DIM}-wide) — refusing to fall back to the "
            f"{EXPECTS_SELF_DIM}-wide single-tick obs (a v{EXPECTS_REGISTRY_VERSION}-labelled "
            f"shard must never train at x_len={EXPECTS_SELF_DIM})")


def check_norm_artifact(stats: dict, map_name: str = "dm3", *, where: str = "norm") -> None:
    """Reject a normalization artifact that is MISSING a key the v3 SELF path needs
    (REQUIRED_NORM_KEYS, e.g. `yaw_rate`) under per_map[<map>]. A stats dict without
    `yaw_rate` would silently de-normalize the appended yaw_rate_z feature, so its
    absence is a hard, loud reject (NOT a zero-fill). Also rejects a stats artifact
    whose own registry_version is present and != EXPECTS_REGISTRY_VERSION (a stale v2
    template). Pure stdlib; the SAME check the trainer + eval reuse."""
    rv = stats.get("registry_version")
    if rv is not None and int(rv) != EXPECTS_REGISTRY_VERSION:
        raise ValueError(
            f"normalization artifact registry_version {rv} != expected "
            f"{EXPECTS_REGISTRY_VERSION} ({where}); refusing a mismatched stats artifact")
    pm = (stats.get("per_map") or {}).get(map_name, {})
    missing = [k for k in REQUIRED_NORM_KEYS if k not in pm]
    if missing:
        raise ValueError(
            f"normalization artifact missing required per_map[{map_name!r}] key(s) "
            f"{missing} ({where}); the registry_version {EXPECTS_REGISTRY_VERSION} SELF "
            f"path z-scores yaw_rate_z against `yaw_rate` — refusing to de-normalize it")


def load_registry_version(registry_json: Path) -> int | None:
    """Cheap stdlib read of `registry_version` from feature_registry.json (stdlib `json` only;
    T1.1 #418 migrated the registry yaml -> json)."""
    try:
        return int(json.loads(Path(registry_json).read_text(encoding="utf-8"))["registry_version"])
    except (OSError, ValueError, KeyError, TypeError):
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
        "authoritative_source": "data/catalog/dataset_spec.yaml + data/catalog/feature_registry.json",
        "expects_registry_version": EXPECTS_REGISTRY_VERSION,
        "expects_self_dim": EXPECTS_SELF_DIM,
        "expects_self_history": EXPECTS_SELF_HISTORY,
        "expects_self_history_dim": EXPECTS_SELF_HISTORY_DIM,
        "required_norm_keys": list(REQUIRED_NORM_KEYS),
        "array_keys": {
            "obs": "[K, F_obs] float32 — normalized single-tick SELF features (provenance)",
            "self_history": "[SELF_HISTORY*F_obs] float32 — v5 flat last-H-tick SELF history for the window's last real tick (one per window; the policy SELF input)",
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
        "model_input": "[self_history | pooled(entities, ent_mask) | audio | team] "
                       "=> SEQUENCE-AWARE BROAD (short self-history + enemy + teammate), "
                       "NOT move-only and NOT single-tick",
        "schema": schema.to_dict(),
    }
    Path(out_path).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return Path(out_path)
