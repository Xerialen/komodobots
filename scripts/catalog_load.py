"""catalog_load.py — stdlib sqlite3 loader for the komodobots catalog (C2).

Pure standard library only (sqlite3, json, pathlib, argparse). NO third-party imports
— this module is imported by the unit suite, which CI runs on bare Python 3.12.

Loads the static reference catalogs (B1-B4) plus a demo fixture's identity/team/frag
rows into a fresh SQLite database built from catalog_schema.sql (C1):

    maps        <- maps.seed.json
    items       <- item_catalog.dm3.json
    markers     <- markers.dm3.json
    nav_edges   <- nav_edges.dm3.json
    demos/teams/players/frag_events  <- fixture meta.json + frag_events.sample.json

loc_catalog.dm3.json / region_catalog.dm3.json are reference-only (no backing table;
the relational spine stores region_control_timeline keyed by region_name text), so the
loader validates they parse but does not insert them.

Repo destination: scripts/catalog_load.py
"""
from __future__ import annotations

import logging
import argparse
import json
import sqlite3
from pathlib import Path


LOGGER = logging.getLogger(__name__)
HERE = Path(__file__).resolve().parent
SCHEMA_SQL = HERE / "catalog_schema.sql"


def connect(schema_sql: Path = SCHEMA_SQL, db_path: str = ":memory:") -> sqlite3.Connection:
    """Open a connection and apply the DDL. FK enforcement on."""
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(schema_sql.read_text(encoding="utf-8"))
    return con


def load_maps(con: sqlite3.Connection, maps_seed: Path) -> dict[str, int]:
    """Insert map rows. Returns {map_name: map_id}."""
    doc = json.loads(maps_seed.read_text(encoding="utf-8"))
    ids: dict[str, int] = {}
    for m in doc["maps"]:
        cur = con.execute(
            """INSERT INTO maps
               (name, source_bsp, source_bsp_sha256,
                x_min, x_max, y_min, y_max, z_min, z_max,
                center_x, center_y, center_z, diagonal,
                maxspeed, jumpspeed, gravity, friction, stopspeed,
                accelerate, airaccel_cap, server_fps)
               VALUES (?,?,?, ?,?,?,?,?,?, ?,?,?,?, ?,?,?,?,?, ?,?,?)""",
            (m["name"], m.get("source_bsp"), m.get("source_bsp_sha256"),
             m["x_min"], m["x_max"], m["y_min"], m["y_max"], m["z_min"], m["z_max"],
             m.get("center_x"), m.get("center_y"), m.get("center_z"), m["diagonal"],
             m.get("maxspeed", 320.0), m.get("jumpspeed", 270.0), m.get("gravity", 800.0),
             m.get("friction", 4.0), m.get("stopspeed", 100.0), m.get("accelerate", 10.0),
             m.get("airaccel_cap", 30.0), m.get("server_fps", 77.0)),
        )
        ids[m["name"]] = cur.lastrowid
    return ids


def load_items(con: sqlite3.Connection, item_catalog: Path, map_id: int) -> int:
    """Insert item rows for one map. Returns count."""
    doc = json.loads(item_catalog.read_text(encoding="utf-8"))
    n = 0
    for it in doc["items"]:
        ox, oy, oz = it["origin"]
        con.execute(
            """INSERT INTO items
               (map_id, classname, item_type, category,
                origin_x, origin_y, origin_z,
                respawn_seconds, static_value, coords_verified)
               VALUES (?,?,?,?, ?,?,?, ?,?,?)""",
            (map_id, it["classname"], it["item_type"], it["category"],
             ox, oy, oz, it.get("respawn_seconds"), it["static_value"],
             1 if it.get("coords_verified") else 0),
        )
        n += 1
    return n


def load_markers(con: sqlite3.Connection, markers_json: Path, map_id: int) -> int:
    """Insert marker rows. Origins may be NULL for referenced-only markers."""
    doc = json.loads(markers_json.read_text(encoding="utf-8"))
    n = 0
    for m in doc["markers"]:
        o = m.get("origin")
        ox, oy, oz = (o[0], o[1], o[2]) if o else (None, None, None)
        con.execute(
            """INSERT INTO markers
               (map_id, marker_id, origin_x, origin_y, origin_z, zone, goal)
               VALUES (?,?,?,?,?,?,?)""",
            (map_id, m["marker_id"], ox, oy, oz, m.get("zone"), m.get("goal")),
        )
        n += 1
    return n


def load_nav_edges(con: sqlite3.Connection, nav_edges_json: Path, map_id: int) -> int:
    """Insert nav-edge rows. Uses edge_idx = first path index; skips edges whose
    endpoints lack a marker row (referenced-only ids with no CreateMarker)."""
    doc = json.loads(nav_edges_json.read_text(encoding="utf-8"))
    known = {r[0] for r in con.execute("SELECT marker_id FROM markers WHERE map_id=?", (map_id,))}
    n = skipped = 0
    for e in doc["edges"]:
        s, t = e["from_marker"], e["to_marker"]
        if s not in known or t not in known:
            skipped += 1
            continue
        idxs = e.get("path_indexes") or [0]
        flags = e.get("explicit_flags") or []
        con.execute(
            """INSERT OR IGNORE INTO nav_edges
               (map_id, from_marker, to_marker, edge_idx, distance_qu, is_jump, is_teleport)
               VALUES (?,?,?,?,?,?,?)""",
            (map_id, s, t, idxs[0], e.get("distance_qu"),
             1 if any("JUMP" in f.upper() for f in flags) else 0,
             1 if any("TELE" in f.upper() for f in flags) else 0),
        )
        n += 1
    return n


def load_fixture(con: sqlite3.Connection, fixture_dir: Path, map_id: int) -> dict:
    """Load one demo fixture's demo/teams/players/frag_events rows.
    Returns a small summary dict for round-trip assertions."""
    meta = json.loads((fixture_dir / "meta.json").read_text(encoding="utf-8"))
    prov, ov = meta["_provenance"], meta["overview"]

    cur = con.execute(
        """INSERT INTO demos
           (path, source, map_id, demo_kind, duration_s, server_fps, sha256, parser_commit)
           VALUES (?,?,?,?,?,?,?,?)""",
        (prov["serverdemo"], "mvd", map_id, "4on4",
         ov["duration_ms"] / 1000.0, meta["ruleset"]["maxfps"],
         prov["sha256"], "schemaVersion=%s" % prov["schemaVersion"]),
    )
    demo_id = cur.lastrowid

    # teams (side A = first team listed in overview = Book)
    team_ids: dict[str, int] = {}
    for i, t in enumerate(ov["teams"]):
        c = con.execute(
            "INSERT INTO teams (demo_id, name, side) VALUES (?,?,?)",
            (demo_id, t["name"], "A" if i == 0 else "B"),
        )
        team_ids[t["name"]] = c.lastrowid

    # players (handle is unique; lowercased)
    player_ids: dict[str, int] = {}
    for p in ov["players"]:
        c = con.execute(
            "INSERT OR IGNORE INTO players (handle, is_bot) VALUES (?,0)",
            (p["name"].lower(),),
        )
        row = con.execute("SELECT player_id FROM players WHERE handle=?", (p["name"].lower(),)).fetchone()
        player_ids[p["name"]] = row[0]

    # frag_events from the sample window (the build's reconciliation slice)
    frags = json.loads((fixture_dir / "frag_events.sample.json").read_text(encoding="utf-8"))
    n_frag = 0
    for f in frags["sample_window_milton_quad"]["frags"]:
        con.execute(
            """INSERT INTO frag_events (demo_id, t_s, killer_id, victim_id, weapon)
               VALUES (?,?,?,?,?)""",
            (demo_id, f["time"] / 1000.0,
             player_ids.get(f["killer"]), player_ids.get(f["victim"]), f["weapon"]),
        )
        n_frag += 1

    return {
        "demo_id": demo_id,
        "team_ids": team_ids,
        "player_ids": player_ids,
        "team_frags": {t["name"]: t["frags"] for t in ov["teams"]},
        "player_frags": {p["name"]: p["frags"] for p in ov["players"]},
        "n_frag_events": n_frag,
    }


def build(catalog_dir: Path, fixture_dir: Path | None = None,
          db_path: str = ":memory:", schema_sql: Path = SCHEMA_SQL) -> tuple[sqlite3.Connection, dict]:
    """Build a fresh catalog DB from the schema/ JSON catalogs (+ optional fixture).
    Returns (connection, summary)."""
    con = connect(schema_sql, db_path)
    map_ids = load_maps(con, catalog_dir / "maps.seed.json")
    dm3 = map_ids["dm3"]
    summary = {
        "maps": len(map_ids),
        "items": load_items(con, catalog_dir / "item_catalog.dm3.json", dm3),
        "markers": load_markers(con, catalog_dir / "markers.dm3.json", dm3),
    }
    summary["nav_edges"] = load_nav_edges(con, catalog_dir / "nav_edges.dm3.json", dm3)
    # reference-only catalogs: validate they parse (no table to load into)
    for ref in ("loc_catalog.dm3.json", "region_catalog.dm3.json"):
        p = catalog_dir / ref
        if p.exists():
            json.loads(p.read_text(encoding="utf-8"))
    if fixture_dir is not None:
        summary["fixture"] = load_fixture(con, fixture_dir, dm3)
    con.commit()
    return con, summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Load komodobots catalogs into a SQLite DB")
    ap.add_argument("--catalog-dir", type=Path, required=True, help="schema/ dir with the JSON catalogs")
    ap.add_argument("--fixture-dir", type=Path, default=None, help="optional demo fixture dir")
    ap.add_argument("--db", default=":memory:", help="output .sqlite path (default in-memory)")
    args = ap.parse_args(argv)
    _, summary = build(args.catalog_dir, args.fixture_dir, args.db)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
