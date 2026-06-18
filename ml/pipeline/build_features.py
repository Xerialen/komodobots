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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build a Parquet feature shard from a fixture")
    ap.add_argument("--catalog-dir", type=Path, required=True)
    ap.add_argument("--fixture-dir", type=Path, required=True)
    ap.add_argument("--stats", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("gold/features/dm3_milton_211436.parquet"))
    args = ap.parse_args(argv)

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
