"""build_features.py — offline Parquet feature build (D2). WSL2 / ml venv only.

Demonstrates the full pattern on the real Milton fixture:
  1. build the SQLite catalog with the IN-TREE stdlib loader (catalog_load),
  2. read the fixture's actor_ticks snapshot (8 actors at t=130),
  3. DuckDB ASOF point-in-time join: attach each actor's LATEST item_event at-or-before
     the tick (no future leakage),
  4. apply the SHARED scripts/features transforms (parity with the live bot),
  5. emit a Parquet feature shard.

Deps: duckdb, pyarrow (ml/requirements.txt). Imports scripts/features from the repo's
in-tree package — that shared import is the parity guarantee.
"""
from __future__ import annotations

import logging
import argparse
import json
import sys
from pathlib import Path


LOGGER = logging.getLogger(__name__)
# --- locate the in-tree stdlib code (shared math + loader) -------------------
# repo layout: <repo>/scripts/...  and  <repo>/ml/pipeline/this_file
# staging layout: <deliverable>/integration/scripts and <deliverable>/integration/ml/pipeline
REPO_ROOT = Path(__file__).resolve().parents[2]   # integration/  (or repo root)
SCRIPTS = REPO_ROOT / "scripts"
HERE = Path(__file__).resolve().parent            # ml/pipeline (sibling in-tree modules)
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

import catalog_load                       # noqa: E402  (in-tree, stdlib)
import route_goals as RG                  # noqa: E402  (in-tree, stdlib; v4 goal labelling)
from features import transforms as T      # noqa: E402  (SHARED math)
from features import egocentric as E      # noqa: E402
from features import agent_observation as AO   # noqa: E402  (SHARED POMDP obs transform, P3)

import duckdb                             # noqa: E402  (ml dep)
import pyarrow as pa                      # noqa: E402
import pyarrow.parquet as pq              # noqa: E402

# fallback per-tick frame time (ms) for yaw_rate when a player_ticks row carries no
# msec (~13ms = the recorded QW tick cadence the closed-loop/dry-route evals also use).
FRAME_DT_MS = 13.0

# --- route-conditioning v4: hindsight GOAL labelling (offline) ----------------------
# The v4 SELF feature needs a per-tick GOAL = where the player is heading. OFFLINE that is
# the HINDSIGHT next-resource the player reached (GCSL), labelled by route_goals (stdlib,
# position-based + flicker-immune); at INFERENCE the tactical/spawn layer supplies it. The
# goal MATH is the SHARED AO.goal_vector (parity). dm3 coords default to the committed
# data/catalog/resource_coords.dm3.json (the catalog-side mirror of the SAME route nodes
# experiments/route_observatory/route_legs.resource_coords reads from a parsed demo).
_DEFAULT_RESOURCE_COORDS = REPO_ROOT / "data" / "catalog" / "resource_coords.dm3.json"


def _last_real_tick(window_mask) -> int:
    """Index of the last real (mask>=0.5) tick in a window; 0 if all pad.

    MIRRORS broad_bc.core._last_real_tick byte-for-byte (kept local so build_features —
    in ml/pipeline/, which only puts scripts/ on sys.path — needs no cross-package import).
    The trainer/loader extract the SELF history at EXACTLY this index, so the build stores
    EXACTLY this tick's history (no drift between the producer and the two consumers)."""
    idx = 0
    for i, m in enumerate(window_mask):
        if float(m) >= 0.5:
            idx = i
    return idx


def load_norm(stats_path: Path) -> dict:
    return json.loads(stats_path.read_text(encoding="utf-8"))


def build_actor_features(fixture_dir: Path, norm: dict, map_name: str = "dm3") -> list[dict]:
    """Compute per-actor egocentric + normalized features for the snapshot tick.
    Pure stdlib math (the SHARED transforms) — DuckDB is used below only for the
    PIT join over the event tables."""
    ticks = json.loads((fixture_dir / "actor_ticks.sample.json").read_text(encoding="utf-8"))
    world = ticks["world_state_t130"]
    pm = norm["per_map"][map_name]

    rows = []
    for name, st in world.items():
        x, y, z = st["pos"]
        # self position via per-map minmax (the AABB-bounded normalization)
        row = {
            "actor": name,
            "team": st["team"],
            "pos_x_n": T.normalize(x, pm["pos_x"]),
            "pos_y_n": T.normalize(y, pm["pos_y"]),
            "pos_z_n": T.normalize(z, pm["pos_z"]),
            "health_n": T.normalize(st["h"], {"method": "divide_period", "period": norm["divide_period"]["health"]}),
            "armor_n": T.normalize(st["a"], {"method": "divide_period", "period": norm["divide_period"]["armor"]}),
            "has_quad": 1 if st.get("q") else 0,
        }
        # nearest enemy: egocentric bearing/distance (yaw unknown in MVD -> use 0 as
        # placeholder; real builds recover yaw via the qwd_usercmd dense path)
        enemies = [(n2, s2["pos"]) for n2, s2 in world.items() if s2["team"] != st["team"]]
        if enemies:
            nearest = min(enemies, key=lambda e: E.rel_distance(e[1], st["pos"]))
            dist = E.rel_distance(nearest[1], st["pos"])
            bearing = E.rel_bearing_deg(nearest[1], st["pos"], 0.0)
            sin_b, cos_b = T.normalize(bearing, {"method": "sincos"})
            row["nearest_enemy"] = nearest[0]
            row["nearest_enemy_dist_n"] = dist / 3797.1   # identity-after-/diagonal
            row["nearest_enemy_bearing_sin"] = sin_b
            row["nearest_enemy_bearing_cos"] = cos_b
        rows.append(row)
    return rows


def emit_parquet(rows: list[dict], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, out_path)
    return out_path


def pit_join_demo(con_sqlite, fixture_dir: Path) -> list[tuple]:
    """DuckDB ASOF point-in-time join: for each frag in the sample window, attach the
    most recent item pickup at-or-before that frag's time. Demonstrates the no-future-
    leakage join the gold feature build relies on."""
    frags = json.loads((fixture_dir / "frag_events.sample.json").read_text(encoding="utf-8"))
    items = json.loads((fixture_dir / "item_events.sample.json").read_text(encoding="utf-8"))
    frag_rows = [(f["time"] / 1000.0, f["killer"], f["victim"])
                 for f in frags["sample_window_milton_quad"]["frags"]]
    pick_rows = [(p["time"] / 1000.0, p["weapon"], p["source"])
                 for p in items["milton_weapon_pickups"]]
    d = duckdb.connect()
    d.execute("CREATE TABLE frags(t DOUBLE, killer VARCHAR, victim VARCHAR)")
    d.executemany("INSERT INTO frags VALUES (?,?,?)", frag_rows)
    d.execute("CREATE TABLE picks(t DOUBLE, weapon VARCHAR, source VARCHAR)")
    d.executemany("INSERT INTO picks VALUES (?,?,?)", pick_rows)
    return d.execute(
        """SELECT f.t, f.killer, f.victim, p.weapon AS last_weapon_picked, p.t AS picked_at
           FROM frags f
           ASOF LEFT JOIN picks p ON f.t >= p.t
           ORDER BY f.t"""
    ).fetchall()


# =============================================================================
# P3: real windowed agent_observation shard from the relational catalog.
# Consumes player_ticks (ego self) + actor_ticks (self + observed-others), applies
# the SHARED scripts/features.agent_observation transform (train/serve parity), and
# emits a windowed Parquet shard. dataset_spec.yaml: K=64, stride=16, N_max=7, windows
# never cross an episode, trailing window padded + attention-masked.
# =============================================================================

# WHY no future leakage: every (episode_id, tick) observation reads ONLY actor_ticks
# rows AT THAT tick (the equal-tick self-join below) and player_ticks at that tick — it
# never references tick+1..end. Windows are built by slicing a per-episode tick-ordered
# list, and a window NEVER spans two episodes, so no cross-trajectory leakage either.

def _load_episode_ticks(sqlite_path: Path, split: str = "train",
                        resource_coords: dict | None = None, goal_rho: float = RG.GOAL_RHO):
    """Return ({episode_id: [tick_obs, ...]}, {episode_id: demo_id}) for the `split`,
    tick-ascending.

    Each tick_obs = {"tick", "self": <self_state dict>, "others": [<other_state>...],
    "act": <action_state dict | None>}. The ego self row in actor_ticks
    (actor_id == episodes.player_id) is split out as `self`; the remaining same-tick
    actor rows are the observed-others; self resource (health/armor) comes from
    player_ticks; the broad usercmd label comes from the `actions` table (PK
    (episode,tick), so an exact equal-tick join — no future leakage). The
    episode->demo_id map drives the trainer's group-by-demo split. DuckDB reads the
    SQLite directly.

    SOURCE LIMITATION (QWD observed-only catalogs): this builder treats EVERY non-self
    actor_ticks row at a tick as an observed/visible entity (entity_is_visible=1). That
    is CORRECT for the self-POV `.qwd` ETL — it only writes an actor_ticks row for a
    player the recording client was actually RECEIVING (in PVS within the staleness
    window), so a present row already IS a PVS-observed sample. There is no omniscient
    leakage to gate here. The `actor_visibility` table (PVS/FOV/LOS + carried-forward
    belief) is the DEFERRED `.mvd` omniscient-path concern: an `.mvd` catalog records
    ALL players every tick, so that path MUST join actor_visibility to gate which actors
    the ego may observe. That join is intentionally NOT implemented here (out of scope
    for the QWD path); see ml/README.md ".qwd provenance note"."""
    d = duckdb.connect()
    d.execute("INSTALL sqlite; LOAD sqlite;")
    d.execute(f"ATTACH '{sqlite_path}' AS cat (TYPE sqlite);")
    # ego self per (episode,tick): joins player_ticks for resource cols + the episode's
    # player_id (to tag which actor_ticks row is self).
    self_rows = d.execute(
        """
        SELECT e.episode_id, pt.tick, e.player_id,
               pt.ox, pt.oy, pt.oz, pt.vx, pt.vy, pt.vz,
               pt.yaw, pt.pitch, pt.hspeed, pt.onground, pt.health, pt.armor,
               pt.msec
          FROM cat.player_ticks pt
          JOIN cat.episodes e USING(episode_id)
         WHERE e.split = ?
         ORDER BY e.episode_id, pt.tick
        """,
        [split],
    ).fetchall()
    # ALL actor rows (self + others) per (episode,tick), restricted to the split.
    # actor_ticks.team_id is the ONLY place the ego's absolute team lives (player_ticks
    # has no team column) — so the ego self row here is what carries team into self_state.
    actor_rows = d.execute(
        """
        SELECT a.episode_id, a.tick, a.actor_id, e.player_id,
               a.ox, a.oy, a.oz, a.vx, a.vy, a.vz, a.yaw, a.alive, a.team_id
          FROM cat.actor_ticks a
          JOIN cat.episodes e USING(episode_id)
         WHERE e.split = ?
         ORDER BY a.episode_id, a.tick
        """,
        [split],
    ).fetchall()
    # recovered broad-usercmd LABELS per (episode,tick) — equal-tick PK join (PIT-safe).
    action_rows = d.execute(
        """
        SELECT a.episode_id, a.tick,
               a.forwardmove, a.sidemove, a.upmove, a.buttons,
               a.confidence, a.is_interp
          FROM cat.actions a
          JOIN cat.episodes e USING(episode_id)
         WHERE e.split = ?
        """,
        [split],
    ).fetchall()
    # episode -> demo_id (group-by-demo split key carried per window into the shard)
    ep_demo = dict(d.execute(
        "SELECT episode_id, demo_id FROM cat.episodes WHERE split = ?", [split],
    ).fetchall())
    d.close()

    # index the action label by (episode,tick)
    actions: dict[tuple, dict] = {}
    for (eid, tick, fwd, side, up, buttons, conf, is_interp) in action_rows:
        actions[(eid, tick)] = {
            "forwardmove": fwd, "sidemove": side, "upmove": up,
            "buttons": buttons,
            "confidence": 1.0 if conf is None else float(conf),
            "is_interp": bool(is_interp) if is_interp is not None else False,
        }

    # index observed-OTHERS by (episode,tick): every actor row whose actor_id != self.
    # The ego's OWN actor row is split off here too — not as an entity, but to recover
    # the ego's absolute team_id (the relative is_teammate flag in entity_features needs
    # the ego team present; otherwise every teammate channel trains as all-zero).
    others: dict[tuple, list] = {}
    self_team_by_kt: dict[tuple, int] = {}
    for (eid, tick, actor_id, self_pid, ox, oy, oz, vx, vy, vz, yaw, alive, team_id) in actor_rows:
        if actor_id == self_pid:
            # the ego's own row is the `self` block, not an entity — but carry its team
            self_team_by_kt[(eid, tick)] = team_id
            continue
        others.setdefault((eid, tick), []).append({
            "actor_id": actor_id, "ox": ox, "oy": oy, "oz": oz,
            "vx": vx, "vy": vy, "vz": vz, "yaw": yaw,
            "alive": bool(alive) if alive is not None else True,
            "team_id": team_id,
        })

    episodes: dict[int, list] = {}
    # yaw_rate (the turn-direction signal) is computed from the PREVIOUS tick's view yaw
    # IN THE SAME EPISODE: yaw_rate[t] = wrap180(yaw[t]-yaw[t-1]) / (msec[t]/1000), via the
    # SHARED AO.yaw_rate_degps so it is byte-identical to the inference call-sites. self_rows
    # is ordered by (episode_id, tick), so we track prev_yaw per episode and reset at each
    # new episode (first tick -> prev None -> rate 0.0, the helper's convention). msec is the
    # per-tick frame time (qwd dense path); fall back to the fixed FRAME_DT_MS when null.
    prev_yaw_by_ep: dict[int, float] = {}
    for (eid, tick, self_pid, ox, oy, oz, vx, vy, vz, yaw, pitch, hspeed, onground, health, armor, msec) in self_rows:
        prev_yaw = prev_yaw_by_ep.get(eid)   # None on the episode's first tick
        dt_s = (float(msec) if msec else FRAME_DT_MS) / 1000.0
        yaw_rate = AO.yaw_rate_degps(yaw, prev_yaw, dt_s) if yaw is not None else 0.0
        if yaw is not None:
            prev_yaw_by_ep[eid] = float(yaw)
        self_state = {
            "ox": ox, "oy": oy, "oz": oz, "vx": vx, "vy": vy, "vz": vz,
            "yaw": yaw, "pitch": pitch, "hspeed": hspeed,
            "onground": bool(onground) if onground is not None else False,
            "health": health, "armor": armor,
            # turn-direction signal (RAW deg/s); self_features z-scores it per-map. The
            # SAME AO.yaw_rate_degps runs at inference, so train/serve are parity-identical.
            "yaw_rate": yaw_rate,
            # ego absolute team from the ego's actor_ticks row (NOT player_ticks, which
            # has no team col). Stays None for a .qwd-only catalog with no team data —
            # then entity_features keeps is_teammate=0; when team IS populated, teammates
            # correctly encode is_teammate=1.0 instead of silently training all-zero.
            "team_id": self_team_by_kt.get((eid, tick)),
        }
        episodes.setdefault(eid, []).append(
            {"tick": tick, "self": self_state,
             "others": others.get((eid, tick), []),
             "act": actions.get((eid, tick))}
        )

    # route-conditioning v4: stamp each tick's hindsight GOAL (the next resource reached on
    # its leg) into self_state["goal"]; AO.self_features turns it into the 3 goal channels
    # (free-roam [0,0,1] when None). PER-EPISODE so a leg never crosses an episode boundary.
    # No coords (non-dm3 / artifact absent) -> no "goal" key -> every tick is free-roam.
    if resource_coords:
        for _eid, eticks in episodes.items():
            positions = [(t["self"].get("ox"), t["self"].get("oy")) for t in eticks]
            goals = RG.label_episode_goals(positions, resource_coords, goal_rho)
            for t, g in zip(eticks, goals):
                t["self"]["goal"] = g
    return episodes, ep_demo


def build_observation_shard(
    sqlite_path: Path,
    norm: dict,
    out_path: Path,
    split: str = "train",
    map_name: str = "dm3",
    lookback_k: int = 64,
    stride: int = 16,
    n_max: int = AO.N_MAX_DEFAULT,
    max_windows: int | None = None,
    resource_coords_path: Path | None = None,
    goal_rho: float = RG.GOAL_RHO,
) -> dict:
    """Build a windowed agent_observation Parquet shard from the catalog.

    Route-conditioning v4: each tick is stamped with a hindsight GOAL (the next resource
    the player reaches on its leg) from resource_coords.<map>.json — dm3 defaults to the
    committed data/catalog/resource_coords.dm3.json; AO.self_features turns it into the
    3 appended goal channels (free-roam when a tick has no leg / no coords are configured).

    Each row = one window: obs [K, SELF_DIM], self_history [SELF_HISTORY*SELF_DIM]
    (the v5 sequence input — a SINGLE FLAT last-SELF_HISTORY-tick SELF history for the
    window's LAST REAL tick, oldest->newest, left-pad-repeat-first at the window start;
    each SELF row is the 21-wide goal-conditioned vector), entities [K, N_max, ENTITY_DIM],
    ent_mask [K, N_max], act [K, ACT_DIM] (broad usercmd label), mask [K] (1=real
    step, 0=pad), weight [K] (action confidence; 0 on pad/interp). Stored as
    flattened fixed-width list<float32> columns (parquet-friendly; the trainer
    reshapes via the documented schema + table-level metadata). A per-window
    `demo_id` column carries the group-by-demo split key. Returns a summary
    (shapes + observed-other coverage + per-head action-label counts).

    self_history MEMORY NOTE: the trainer/loader consume the SELF history of ONLY the
    window's LAST REAL tick (core.shard_to_rows / train_broad_bc.rows_to_tensors both read
    self_in[wi] at that one tick). Storing a [K, HD] per-tick history was therefore 64x
    redundant (and OOM-killed pa.table() on a ~72GB box: K=64 * HD=336 = 21,504 floats/row).
    So we store the SINGLE [HD] last-real-tick history per row. This is BYTE-IDENTICAL
    training data — the stored vector == what the old [K, HD][last_real_tick] extraction
    yielded — only the storage shrank. The history is assembled by the SHARED
    AO.assemble_self_history helper over the window's own per-tick SELF vectors up to AND
    INCLUDING the last real tick (oldest->newest), with the SAME left-pad-repeat-first rule
    the inference rolling-deque path uses — so the flat history is byte-identical between
    this offline build and the closed-loop / dry-route rollouts (the v5 train/serve parity
    contract)."""
    import numpy as np

    # route-conditioning v4 goal coords: explicit --resource-coords wins; else dm3 defaults
    # to the committed artifact; any other map with no coords -> every tick free-roam.
    coords = {}
    if resource_coords_path is not None:
        coords = RG.load_resource_coords(resource_coords_path)
    elif map_name == "dm3":
        coords = RG.load_resource_coords(_DEFAULT_RESOURCE_COORDS)
    episodes, ep_demo = _load_episode_ticks(
        sqlite_path, split=split, resource_coords=coords, goal_rho=goal_rho)
    n_goal_ticks = sum(1 for et in episodes.values() for t in et if t["self"].get("goal") is not None)
    n_all_ticks = sum(len(et) for et in episodes.values())
    K, S, ENT, A = lookback_k, AO.SELF_DIM, AO.ENTITY_DIM, AO.ACT_DIM
    H = AO.SELF_HISTORY
    HD = AO.SELF_HISTORY_DIM                          # = H * S (flat history width)

    obs_col, selfhist_col, ent_col, entmask_col, mask_col = [], [], [], [], []
    act_col, weight_col, demo_col = [], [], []
    meta_eid, meta_start = [], []
    n_windows = 0
    n_real_steps = 0
    n_steps_with_other = 0
    n_steps_with_label = 0
    entity_abs_sum = 0.0
    entity_real_cells = 0
    # per-head label histogram over REAL (mask==1) steps, for the non-triviality proof.
    # heads: fwd(3) side(3) up(3) jump(2) attack(2) — sign3 buckets for moves, bin for buttons.
    head_counts = {
        "fwd": [0, 0, 0], "side": [0, 0, 0], "up": [0, 0, 0],
        "jump": [0, 0], "attack": [0, 0],
    }

    def _sign3(v: float) -> int:
        return 2 if v > 1e-3 else (0 if v < -1e-3 else 1)

    for eid in sorted(episodes):
        ticks = episodes[eid]                       # already tick-ascending
        n = len(ticks)
        if n == 0:
            continue
        demo_id = int(ep_demo.get(eid, -1))
        # EPISODE-continuous SELF sequence (oldest->newest over the WHOLE episode), encoded
        # once via the SHARED AO.self_features (byte-identical to the per-tick obs the window
        # loop builds below). The stored last-real-tick self_history is assembled from THIS
        # episode list sliced to the ABSOLUTE episode tick — NOT the window slice — so a window
        # that starts mid-episode left-pads from the true preceding episode ticks, exactly like
        # the inference rolling deque (which runs maxlen=H over the whole episode, never reset
        # per window). Slicing the window only would left-pad-repeat the window's FIRST tick,
        # breaking the v5 train/serve byte-parity for any window with < H real ticks before ti.
        episode_selves: list[list[float]] = [
            AO.self_features(t["self"], norm, map_name) for t in ticks
        ]
        # window starts every `stride`; pad the trailing window to K (pad_short_windows)
        start = 0
        while start < n:
            window = ticks[start:start + K]
            obs_w = np.zeros((K, S), dtype=np.float32)
            ent_w = np.zeros((K, n_max, ENT), dtype=np.float32)
            entmask_w = np.zeros((K, n_max), dtype=np.float32)
            act_w = np.zeros((K, A), dtype=np.float32)
            mask_w = np.zeros((K,), dtype=np.float32)
            weight_w = np.zeros((K,), dtype=np.float32)
            # Only the LAST REAL tick's SELF history is stored, and it is assembled from the
            # EPISODE-continuous episode_selves (built above), so the window loop no longer
            # accumulates its own per-window SELF list — obs_w still carries every tick's SELF
            # for provenance via the SAME AO.self_features values episode_selves holds.
            for j, t in enumerate(window):
                enc = AO.encode_observation(t["self"], t["others"], norm, map_name, n_max)
                obs_w[j] = np.asarray(enc["self"], dtype=np.float32)
                ent_w[j] = np.asarray(enc["ents"], dtype=np.float32)
                entmask_w[j] = np.asarray(enc["mask"], dtype=np.float32)
                act_vec = AO.encode_action(t.get("act"))
                act_w[j] = np.asarray(act_vec, dtype=np.float32)
                mask_w[j] = 1.0
                # weight = action confidence, but a NULL label or an interpolated/
                # anomalous frame (dataset_spec: exclude from training) -> weight 0 so
                # it is loss-down-weighted while keeping the window contiguous/masked.
                act_state = t.get("act")
                if act_state is None:
                    weight_w[j] = 0.0
                else:
                    conf = float(act_state.get("confidence", 1.0))
                    weight_w[j] = 0.0 if act_state.get("is_interp") else conf
                    n_steps_with_label += 1
                    head_counts["fwd"][_sign3(act_vec[0])] += 1
                    head_counts["side"][_sign3(act_vec[1])] += 1
                    head_counts["up"][_sign3(act_vec[2])] += 1
                    head_counts["jump"][1 if act_vec[3] >= 0.5 else 0] += 1
                    head_counts["attack"][1 if act_vec[4] >= 0.5 else 0] += 1
                n_real_steps += 1
                if enc["n_obs"] > 0:
                    n_steps_with_other += 1
                # accumulate |entity feature| over REAL entity cells for non-triviality proof
                em = entmask_w[j].astype(bool)
                if em.any():
                    entity_abs_sum += float(np.abs(ent_w[j][em]).sum())
                    entity_real_cells += int(em.sum()) * ENT

            obs_col.append(obs_w.reshape(-1).tolist())
            # v5 self_history: store ONLY the LAST REAL tick's flat [HD] history (the trainer
            # and loader consume the SELF history of just that tick — core.shard_to_rows /
            # train_broad_bc.rows_to_tensors read self_in[wi] at _last_real_tick). `ti` is that
            # tick index via the SAME _last_real_tick logic the consumer uses; the absolute
            # episode index of that tick is `start + ti`, so episode_selves[:start+ti+1] is the
            # EPISODE-continuous SELF sequence ending at it (oldest->newest). Feeding the helper
            # the EPISODE slice (not window_selves[:ti+1]) makes the left-pad-repeat-first use
            # the true preceding EPISODE ticks for a mid-episode window — byte-identical to the
            # inference deque (maxlen=H over the whole episode) and so to the v5 train/serve
            # parity contract.
            ti = _last_real_tick(mask_w)
            selfhist_col.append(
                AO.assemble_self_history(episode_selves[:start + ti + 1], H))
            ent_col.append(ent_w.reshape(-1).tolist())
            entmask_col.append(entmask_w.reshape(-1).tolist())
            act_col.append(act_w.reshape(-1).tolist())
            mask_col.append(mask_w.tolist())
            weight_col.append(weight_w.tolist())
            demo_col.append(demo_id)
            meta_eid.append(int(eid))
            meta_start.append(int(window[0]["tick"]))
            n_windows += 1
            if max_windows is not None and n_windows >= max_windows:
                start = n   # stop this episode
                break
            start += stride
        if max_windows is not None and n_windows >= max_windows:
            break

    # table-level metadata so the trainer can reshape the flattened columns + bind the
    # contract WITHOUT a sidecar (read via pq.read_table(...).schema.metadata).
    norm_ver = str(norm.get("artifact_version", "UNSET"))
    schema_meta = {
        b"komodobots.shard.contract": b"broad_bc.shard_contract.v1",
        # stamp the registry_version from the (v5) norm artifact; fall back to 5 — the
        # current EXPECTS_REGISTRY_VERSION — so a shard is never mislabelled as a stale
        # pre-v5 version (this build emits the v5 self_history field, and the SELF channels
        # are the 21-wide goal-conditioned layout: agent_observation.SELF_DIM).
        b"komodobots.shard.registry_version": str(norm.get("registry_version", 5)).encode(),
        b"komodobots.shard.K": str(K).encode(),
        b"komodobots.shard.n_max": str(n_max).encode(),
        b"komodobots.shard.obs_dim": str(S).encode(),
        # v5: the flat self-history width (= SELF_HISTORY * SELF_DIM). self_history is now
        # stored as ONE [HD] vector PER ROW (the last-real-tick history), so the loader
        # reshapes the column to [n_windows, HD]; the reject guard verifies a row's width
        # HD == EXPECTS_SELF_HISTORY_DIM.
        b"komodobots.shard.self_history": str(H).encode(),
        b"komodobots.shard.self_history_dim": str(HD).encode(),
        b"komodobots.shard.ent_dim": str(ENT).encode(),
        b"komodobots.shard.act_dim": str(A).encode(),
        b"komodobots.shard.act_cols": ",".join(AO.ACT_FIELDS).encode(),
        b"komodobots.shard.map": map_name.encode(),
        b"komodobots.shard.split": split.encode(),
        b"komodobots.shard.norm_artifact_version": norm_ver.encode(),
        b"komodobots.shard.has_audio": b"false",
        b"komodobots.shard.has_team": b"false",
    }
    table = pa.table(
        {
            "episode_id": pa.array(meta_eid, type=pa.int64()),
            "demo_id": pa.array(demo_col, type=pa.int64()),
            "start_tick": pa.array(meta_start, type=pa.int64()),
            "obs": pa.array(obs_col, type=pa.list_(pa.float32())),          # [K*S]
            "self_history": pa.array(selfhist_col, type=pa.list_(pa.float32())),  # [HD] (last real tick)
            "entities": pa.array(ent_col, type=pa.list_(pa.float32())),     # [K*N_max*ENT]
            "ent_mask": pa.array(entmask_col, type=pa.list_(pa.float32())), # [K*N_max]
            "act": pa.array(act_col, type=pa.list_(pa.float32())),          # [K*ACT_DIM]
            "mask": pa.array(mask_col, type=pa.list_(pa.float32())),        # [K]
            "weight": pa.array(weight_col, type=pa.list_(pa.float32())),    # [K]
        },
        metadata=schema_meta,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out_path, compression="zstd")

    mean_entity_abs = (entity_abs_sum / entity_real_cells) if entity_real_cells else 0.0
    return {
        "out": str(out_path),
        "split": split,
        "n_windows": n_windows,
        "n_demos": len({d for d in demo_col}),
        "window_shape": {"obs": [K, S], "self_history": [HD],
                         "entities": [K, n_max, ENT],
                         "ent_mask": [K, n_max], "act": [K, A],
                         "mask": [K], "weight": [K]},
        "K": K, "stride": stride, "N_max": n_max,
        "self_dim": S, "self_history": H, "self_history_dim": HD,
        "entity_dim": ENT, "act_dim": A,
        "act_cols": list(AO.ACT_FIELDS),
        "route_conditioning": {
            "n_resources": len(coords),
            "goal_labeled_ticks": n_goal_ticks,
            "goal_coverage": round(n_goal_ticks / n_all_ticks, 4) if n_all_ticks else 0.0,
        },
        "real_steps": n_real_steps,
        "steps_with_label": n_steps_with_label,
        "label_coverage": round(n_steps_with_label / n_real_steps, 4) if n_real_steps else 0.0,
        "steps_with_observed_other": n_steps_with_other,
        "observed_other_step_frac": round(n_steps_with_other / n_real_steps, 4) if n_real_steps else 0.0,
        "mean_abs_entity_feature": round(mean_entity_abs, 6),
        "action_head_counts": head_counts,
        "bytes": out_path.stat().st_size,
    }


def _add_fixture_args(p) -> None:
    """Legacy fixture-demo options. Registered on BOTH the `fixture` subparser AND the
    root parser so the documented `build_features.py --catalog-dir ...` invocation (no
    subcommand) still parses and dispatches to the fixture path (back-compat)."""
    p.add_argument("--catalog-dir", type=Path)
    p.add_argument("--fixture-dir", type=Path)
    p.add_argument("--stats", type=Path)
    p.add_argument("--out", type=Path, default=Path("gold/features/dm3_milton_211436.parquet"))


def _run_fixture(args) -> int:
    """The original per-actor snapshot demo path (fixture build + PIT-join demo)."""
    missing = [f for f in ("catalog_dir", "fixture_dir", "stats") if getattr(args, f) is None]
    if missing:
        flags = ", ".join("--" + m.replace("_", "-") for m in missing)
        print(f"fixture build requires: {flags}", file=sys.stderr)
        return 2
    con, summary = catalog_load.build(args.catalog_dir, args.fixture_dir)
    print("catalog:", json.dumps(summary.get("fixture", {}).get("team_frags", {})))
    norm = load_norm(args.stats)
    rows = build_actor_features(args.fixture_dir, norm)
    out = emit_parquet(rows, args.out)
    pit = pit_join_demo(con, args.fixture_dir)
    print(f"wrote {out} ({len(rows)} actor rows); PIT join produced {len(pit)} frag rows")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build a Parquet feature shard")
    # root-level back-compat: the documented `build_features.py --catalog-dir ...` form
    # (no subcommand) routes to the fixture path. Keep in sync with the `fixture` subparser.
    _add_fixture_args(ap)
    sub = ap.add_subparsers(dest="cmd")

    # legacy fixture demo (kept, explicit `fixture` subcommand)
    apf = sub.add_parser("fixture", help="legacy: per-actor snapshot shard from the fixture")
    _add_fixture_args(apf)

    # P3: windowed agent_observation shard from the catalog
    apw = sub.add_parser("shard", help="windowed agent_observation shard from a catalog .sqlite")
    apw.add_argument("--db", type=Path, required=True)
    apw.add_argument("--stats", type=Path, required=True)
    apw.add_argument("--out", type=Path, required=True)
    apw.add_argument("--split", default="train")
    apw.add_argument("--map", default="dm3")
    apw.add_argument("--lookback-k", type=int, default=64)
    apw.add_argument("--stride", type=int, default=16)
    apw.add_argument("--n-max", type=int, default=AO.N_MAX_DEFAULT)
    apw.add_argument("--max-windows", type=int, default=None)
    apw.add_argument("--resource-coords", type=Path, default=None,
                     help="route-conditioning v4 goal coords (resource_coords.<map>.json); "
                          "dm3 defaults to the committed data/catalog artifact")
    apw.add_argument("--goal-rho", type=float, default=RG.GOAL_RHO,
                     help="resource-visit radius (qu) for the hindsight goal label")

    args = ap.parse_args(argv)

    if args.cmd == "shard":
        norm = load_norm(args.stats)
        summ = build_observation_shard(
            args.db, norm, args.out, split=args.split, map_name=args.map,
            lookback_k=args.lookback_k, stride=args.stride, n_max=args.n_max,
            max_windows=args.max_windows,
            resource_coords_path=args.resource_coords, goal_rho=args.goal_rho,
        )
        print(json.dumps(summ, indent=2))
        return 0

    # default (no subcommand) or explicit `fixture`: the original demo path. The
    # root-level --catalog-dir/--fixture-dir/--stats make the legacy invocation work
    # without requiring the `fixture` keyword.
    return _run_fixture(args)


if __name__ == "__main__":
    raise SystemExit(main())
