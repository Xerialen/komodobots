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

import argparse
import json
import sys
from pathlib import Path

# --- locate the in-tree stdlib code (shared math + loader) -------------------
# repo layout: <repo>/scripts/...  and  <repo>/ml/pipeline/this_file
# staging layout: <deliverable>/integration/scripts and <deliverable>/integration/ml/pipeline
REPO_ROOT = Path(__file__).resolve().parents[2]   # integration/  (or repo root)
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import catalog_load                       # noqa: E402  (in-tree, stdlib)
from features import transforms as T      # noqa: E402  (SHARED math)
from features import egocentric as E      # noqa: E402
from features import agent_observation as AO   # noqa: E402  (SHARED POMDP obs transform, P3)

import duckdb                             # noqa: E402  (ml dep)
import pyarrow as pa                      # noqa: E402
import pyarrow.parquet as pq              # noqa: E402


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

def _load_episode_ticks(sqlite_path: Path, split: str = "train"):
    """Return {episode_id: [tick_obs, ...]} for the `split`, tick-ascending.

    Each tick_obs = {"self": <self_state dict>, "others": [<other_state dict>, ...]}.
    The ego self row in actor_ticks (actor_id == episodes.player_id) is split out as
    `self`; the remaining same-tick actor rows are the observed-others. self resource
    (health/armor) comes from player_ticks. DuckDB reads the SQLite directly."""
    d = duckdb.connect()
    d.execute("INSTALL sqlite; LOAD sqlite;")
    d.execute(f"ATTACH '{sqlite_path}' AS cat (TYPE sqlite);")
    # ego self per (episode,tick): joins player_ticks for resource cols + the episode's
    # player_id (to tag which actor_ticks row is self).
    self_rows = d.execute(
        """
        SELECT e.episode_id, pt.tick, e.player_id,
               pt.ox, pt.oy, pt.oz, pt.vx, pt.vy, pt.vz,
               pt.yaw, pt.pitch, pt.hspeed, pt.onground, pt.health, pt.armor
          FROM cat.player_ticks pt
          JOIN cat.episodes e USING(episode_id)
         WHERE e.split = ?
         ORDER BY e.episode_id, pt.tick
        """,
        [split],
    ).fetchall()
    # ALL actor rows (self + others) per (episode,tick), restricted to the split.
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
    d.close()

    # index observed-OTHERS by (episode,tick): every actor row whose actor_id != self
    others: dict[tuple, list] = {}
    for (eid, tick, actor_id, self_pid, ox, oy, oz, vx, vy, vz, yaw, alive, team_id) in actor_rows:
        if actor_id == self_pid:
            continue   # the ego's own row is the `self` block, not an entity
        others.setdefault((eid, tick), []).append({
            "actor_id": actor_id, "ox": ox, "oy": oy, "oz": oz,
            "vx": vx, "vy": vy, "vz": vz, "yaw": yaw,
            "alive": bool(alive) if alive is not None else True,
            "team_id": team_id,
        })

    episodes: dict[int, list] = {}
    for (eid, tick, self_pid, ox, oy, oz, vx, vy, vz, yaw, pitch, hspeed, onground, health, armor) in self_rows:
        self_state = {
            "ox": ox, "oy": oy, "oz": oz, "vx": vx, "vy": vy, "vz": vz,
            "yaw": yaw, "pitch": pitch, "hspeed": hspeed,
            "onground": bool(onground) if onground is not None else False,
            "health": health, "armor": armor, "team_id": None,
        }
        episodes.setdefault(eid, []).append(
            {"tick": tick, "self": self_state, "others": others.get((eid, tick), [])}
        )
    return episodes


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
) -> dict:
    """Build a windowed agent_observation Parquet shard from the catalog.

    Each row = one window: obs [K, SELF_DIM], entities [K, N_max, ENTITY_DIM],
    ent_mask [K, N_max], mask [K] (1=real step, 0=pad). Stored as flattened
    fixed-width list<float32> columns (parquet-friendly; the trainer reshapes via the
    documented schema). Returns a summary (shapes + observed-other coverage)."""
    import numpy as np

    episodes = _load_episode_ticks(sqlite_path, split=split)
    K, S, ENT = lookback_k, AO.SELF_DIM, AO.ENTITY_DIM

    obs_col, ent_col, entmask_col, mask_col = [], [], [], []
    meta_eid, meta_start = [], []
    n_windows = 0
    n_real_steps = 0
    n_steps_with_other = 0
    entity_abs_sum = 0.0
    entity_real_cells = 0

    for eid in sorted(episodes):
        ticks = episodes[eid]                       # already tick-ascending
        n = len(ticks)
        if n == 0:
            continue
        # window starts every `stride`; pad the trailing window to K (pad_short_windows)
        start = 0
        while start < n:
            window = ticks[start:start + K]
            real = len(window)
            obs_w = np.zeros((K, S), dtype=np.float32)
            ent_w = np.zeros((K, n_max, ENT), dtype=np.float32)
            entmask_w = np.zeros((K, n_max), dtype=np.float32)
            mask_w = np.zeros((K,), dtype=np.float32)
            for j, t in enumerate(window):
                enc = AO.encode_observation(t["self"], t["others"], norm, map_name, n_max)
                obs_w[j] = np.asarray(enc["self"], dtype=np.float32)
                ent_w[j] = np.asarray(enc["ents"], dtype=np.float32)
                entmask_w[j] = np.asarray(enc["mask"], dtype=np.float32)
                mask_w[j] = 1.0
                n_real_steps += 1
                if enc["n_obs"] > 0:
                    n_steps_with_other += 1
                # accumulate |entity feature| over REAL entity cells for non-triviality proof
                em = entmask_w[j].astype(bool)
                if em.any():
                    entity_abs_sum += float(np.abs(ent_w[j][em]).sum())
                    entity_real_cells += int(em.sum()) * ENT

            obs_col.append(obs_w.reshape(-1).tolist())
            ent_col.append(ent_w.reshape(-1).tolist())
            entmask_col.append(entmask_w.reshape(-1).tolist())
            mask_col.append(mask_w.tolist())
            meta_eid.append(int(eid))
            meta_start.append(int(window[0]["tick"]))
            n_windows += 1
            if max_windows is not None and n_windows >= max_windows:
                start = n   # stop this episode
                break
            start += stride
        if max_windows is not None and n_windows >= max_windows:
            break

    table = pa.table({
        "episode_id": pa.array(meta_eid, type=pa.int64()),
        "start_tick": pa.array(meta_start, type=pa.int64()),
        "obs": pa.array(obs_col, type=pa.list_(pa.float32())),          # [K*S]
        "entities": pa.array(ent_col, type=pa.list_(pa.float32())),     # [K*N_max*ENT]
        "ent_mask": pa.array(entmask_col, type=pa.list_(pa.float32())), # [K*N_max]
        "mask": pa.array(mask_col, type=pa.list_(pa.float32())),        # [K]
    })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out_path, compression="zstd")

    mean_entity_abs = (entity_abs_sum / entity_real_cells) if entity_real_cells else 0.0
    return {
        "out": str(out_path),
        "split": split,
        "n_windows": n_windows,
        "window_shape": {"obs": [K, S], "entities": [K, n_max, ENT], "ent_mask": [K, n_max], "mask": [K]},
        "K": K, "stride": stride, "N_max": n_max,
        "self_dim": S, "entity_dim": ENT,
        "real_steps": n_real_steps,
        "steps_with_observed_other": n_steps_with_other,
        "observed_other_step_frac": round(n_steps_with_other / n_real_steps, 4) if n_real_steps else 0.0,
        "mean_abs_entity_feature": round(mean_entity_abs, 6),
        "bytes": out_path.stat().st_size,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build a Parquet feature shard")
    sub = ap.add_subparsers(dest="cmd")

    # legacy fixture demo (kept)
    apf = sub.add_parser("fixture", help="legacy: per-actor snapshot shard from the fixture")
    apf.add_argument("--catalog-dir", type=Path, required=True)
    apf.add_argument("--fixture-dir", type=Path, required=True)
    apf.add_argument("--stats", type=Path, required=True)
    apf.add_argument("--out", type=Path, default=Path("gold/features/dm3_milton_211436.parquet"))

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

    args = ap.parse_args(argv)

    if args.cmd == "shard":
        norm = load_norm(args.stats)
        summ = build_observation_shard(
            args.db, norm, args.out, split=args.split, map_name=args.map,
            lookback_k=args.lookback_k, stride=args.stride, n_max=args.n_max,
            max_windows=args.max_windows,
        )
        print(json.dumps(summ, indent=2))
        return 0

    # default / "fixture": the original demo path
    con, summary = catalog_load.build(args.catalog_dir, args.fixture_dir)
    print("catalog:", json.dumps(summary.get("fixture", {}).get("team_frags", {})))
    norm = load_norm(args.stats)
    rows = build_actor_features(args.fixture_dir, norm)
    out = emit_parquet(rows, args.out)
    pit = pit_join_demo(con, args.fixture_dir)
    print(f"wrote {out} ({len(rows)} actor rows); PIT join produced {len(pit)} frag rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
