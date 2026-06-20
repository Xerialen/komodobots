"""validate_catalog.py — stdlib validators for the komodobots catalog (C4).

Replaces pandera (a third-party dep) for the IN-TREE, CI-gated checks. Pure stdlib:
sqlite3 + json. Collects every violation and raises CatalogError listing all of them,
so a bad catalog fails loudly with a complete report rather than at the first error.

The richer dataframe-schema validation (pandera) lives out-of-tree in ml/; this module
is the floor that the merge gate enforces.

Repo destination: scripts/validate_catalog.py
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

# canonical item_type vocabulary (catalog.sql items.item_type comment)
ITEM_TYPES = {
    "rl", "ra", "ya", "ga", "mh", "quad", "pent", "ring", "ssg", "ng", "sng",
    "gl", "lg", "cells", "rockets", "nails", "shells", "health25", "health15",
}
CATEGORIES = {"weapon", "armor", "health", "powerup", "ammo"}
NORM_METHODS = {"zscore", "minmax", "robust", "log1p_zscore", "sincos",
                "divide_period", "identity"}


class CatalogError(ValueError):
    """Raised with the full list of validation failures."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("catalog validation failed:\n  - " + "\n  - ".join(errors))


def validate_maps(con: sqlite3.Connection) -> list[str]:
    errs: list[str] = []
    rows = con.execute(
        "SELECT name, x_min, x_max, y_min, y_max, z_min, z_max, diagonal, server_fps FROM maps"
    ).fetchall()
    if not rows:
        return ["maps: no rows"]
    for name, xmn, xmx, ymn, ymx, zmn, zmx, diag, fps in rows:
        if not (xmn < xmx and ymn < ymx and zmn < zmx):
            errs.append(f"maps[{name}]: AABB min must be < max on every axis")
        if not (diag and diag > 0):
            errs.append(f"maps[{name}]: diagonal must be > 0")
        if not (fps and fps > 0):
            errs.append(f"maps[{name}]: server_fps must be > 0")
    return errs


def validate_items(con: sqlite3.Connection, expect_count: int | None = None) -> list[str]:
    errs: list[str] = []
    rows = con.execute(
        "SELECT item_type, category, static_value, coords_verified, respawn_seconds FROM items"
    ).fetchall()
    if expect_count is not None and len(rows) != expect_count:
        errs.append(f"items: expected {expect_count} rows, got {len(rows)}")
    for it, cat, sv, cv, rs in rows:
        if it not in ITEM_TYPES:
            errs.append(f"items: unknown item_type {it!r}")
        if cat not in CATEGORIES:
            errs.append(f"items: unknown category {cat!r} (item_type {it})")
        if sv is None or not (0.0 <= sv <= 1.0):
            errs.append(f"items[{it}]: static_value {sv} out of [0,1]")
        if rs is not None and rs < 0:
            errs.append(f"items[{it}]: negative respawn_seconds {rs}")
    return errs


def validate_markers(con: sqlite3.Connection) -> list[str]:
    errs: list[str] = []
    (total,) = con.execute("SELECT COUNT(*) FROM markers").fetchone()
    if total == 0:
        errs.append("markers: no rows")
    # a marker with a partial origin (some axes NULL, some not) is malformed
    bad = con.execute(
        """SELECT marker_id FROM markers
           WHERE (origin_x IS NULL) + (origin_y IS NULL) + (origin_z IS NULL) NOT IN (0,3)"""
    ).fetchall()
    for (mid,) in bad:
        errs.append(f"markers[{mid}]: partial origin (mix of NULL and non-NULL axes)")
    return errs


def validate_nav_edges(con: sqlite3.Connection) -> list[str]:
    errs: list[str] = []
    # every edge endpoint must reference an existing marker (same map)
    orphans = con.execute(
        """SELECT e.from_marker, e.to_marker FROM nav_edges e
           WHERE NOT EXISTS (SELECT 1 FROM markers m
                             WHERE m.map_id=e.map_id AND m.marker_id=e.from_marker)
              OR NOT EXISTS (SELECT 1 FROM markers m
                             WHERE m.map_id=e.map_id AND m.marker_id=e.to_marker)"""
    ).fetchall()
    for fr, to in orphans:
        errs.append(f"nav_edges: edge {fr}->{to} references a missing marker")
    # negative distances are impossible
    (neg,) = con.execute(
        "SELECT COUNT(*) FROM nav_edges WHERE distance_qu IS NOT NULL AND distance_qu < 0"
    ).fetchone()
    if neg:
        errs.append(f"nav_edges: {neg} edges with negative distance_qu")
    return errs


def validate_frag_events(con: sqlite3.Connection) -> list[str]:
    errs: list[str] = []
    # killer/victim, when set, must reference real players
    bad = con.execute(
        """SELECT event_id FROM frag_events f
           WHERE (f.killer_id IS NOT NULL AND NOT EXISTS
                    (SELECT 1 FROM players p WHERE p.player_id=f.killer_id))
              OR (f.victim_id IS NOT NULL AND NOT EXISTS
                    (SELECT 1 FROM players p WHERE p.player_id=f.victim_id))"""
    ).fetchall()
    for (eid,) in bad:
        errs.append(f"frag_events[{eid}]: killer/victim references a missing player")
    (negt,) = con.execute("SELECT COUNT(*) FROM frag_events WHERE t_s < 0").fetchone()
    if negt:
        errs.append(f"frag_events: {negt} rows with negative t_s")
    return errs


def validate_actor_ticks(con: sqlite3.Connection) -> list[str]:
    """Validate the OMNISCIENT-from-POV world-state layer (actor_ticks, P2).

    Checks that are cheap and catch a mis-decode or a broken join:
      - every actor_id references a real players row;
      - every (episode_id, tick) actor row has a matching player_ticks self row
        (the self ego is always present, so observed-others are anchored to a real tick);
      - origins lie within the episode's map AABB (a decode/offset bug shows up as
        out-of-map coordinates) — checked with a small pad for transient edge states.
    Skips silently if the table is absent (older catalogs) or empty.
    """
    errs: list[str] = []
    try:
        (total,) = con.execute("SELECT COUNT(*) FROM actor_ticks").fetchone()
    except sqlite3.OperationalError:
        return errs  # table not present in this schema
    if total == 0:
        return errs  # nothing populated (e.g. self-only / non-proto-28 corpus) — not an error

    (orphan_actor,) = con.execute(
        """SELECT COUNT(*) FROM actor_ticks a
           WHERE NOT EXISTS (SELECT 1 FROM players p WHERE p.player_id=a.actor_id)"""
    ).fetchone()
    if orphan_actor:
        errs.append(f"actor_ticks: {orphan_actor} rows reference a missing actor_id (player)")

    (orphan_tick,) = con.execute(
        """SELECT COUNT(*) FROM actor_ticks a
           WHERE NOT EXISTS (SELECT 1 FROM player_ticks t
                             WHERE t.episode_id=a.episode_id AND t.tick=a.tick)"""
    ).fetchone()
    if orphan_tick:
        errs.append(f"actor_ticks: {orphan_tick} rows have no matching player_ticks (episode,tick)")

    # AABB containment (join each actor row to its episode's map). A generous pad allows
    # the brief out-of-bounds excursions real play produces (e.g. mid-teleport, edge clip).
    pad = 256.0
    bad_aabb = con.execute(
        """SELECT COUNT(*) FROM actor_ticks a
           JOIN episodes e ON e.episode_id=a.episode_id
           JOIN maps    m ON m.map_id=e.map_id
           WHERE a.ox < m.x_min-? OR a.ox > m.x_max+?
              OR a.oy < m.y_min-? OR a.oy > m.y_max+?
              OR a.oz < m.z_min-? OR a.oz > m.z_max+?""",
        (pad, pad, pad, pad, pad, pad),
    ).fetchone()[0]
    if bad_aabb:
        frac = bad_aabb / total
        # A handful of edge rows is fine; a large fraction means a decode/offset bug.
        if frac > 0.01:
            errs.append(
                f"actor_ticks: {bad_aabb}/{total} ({frac:.1%}) rows are outside the map "
                f"AABB (+/-{pad:.0f} qu) — likely an entity-stream decode/offset error")
    return errs


def validate_freshness(con: sqlite3.Connection) -> list[str]:
    """Anti-recurrence guard: flag a STALE regenerable catalog (pre-#296 build).

    The relational catalog (`data/catalog/*.sqlite`) is gitignored and regenerable.
    A stale on-disk copy — one built BEFORE the actor_ticks-population code landed
    (commit 4756c0d / PR #296) — silently shipped and broke the all-player
    (agent_observation) analysis: `actor_ticks` was empty even though `player_ticks`
    was full. The code was correct; the ARTIFACT was stale. This check makes that
    state fail loudly so the only fix is to regenerate.

    Signal: the ETL inserts the SELF ego row into `actor_ticks` for EVERY
    `player_ticks` row (catalog_etl_qwd.insert_demo), so any FRESH build with
    player_ticks>0 necessarily has actor_ticks>=player_ticks>0. The ONLY way to
    observe player_ticks>0 AND actor_ticks==0 is a pre-#296 stale build. We do NOT
    flag the legitimately-empty case (player_ticks==0, a static-only/spine catalog)
    nor a missing `actor_ticks` table (older schema): those are not staleness.
    """
    errs: list[str] = []
    try:
        (n_actor,) = con.execute("SELECT COUNT(*) FROM actor_ticks").fetchone()
    except sqlite3.OperationalError:
        return errs  # table not present in this schema — not a freshness signal
    try:
        (n_pt,) = con.execute("SELECT COUNT(*) FROM player_ticks").fetchone()
    except sqlite3.OperationalError:
        return errs  # no per-tick layer at all — static-only catalog
    if n_pt > 0 and n_actor == 0:
        errs.append(
            f"freshness: actor_ticks is EMPTY but player_ticks={n_pt} (>0) — this catalog "
            f"was built BEFORE the actor_ticks-population code (PR #296) and is STALE. "
            f"The all-player/agent_observation layer is missing. Regenerate it: "
            f"python3 scripts/catalog_etl_qwd.py --catalog-dir data/catalog "
            f"--demo-list experiments/stage2/move-bc-dataset/p1_catalog_slice.tsv "
            f"--db <out>.sqlite --workers 4")
    return errs


def validate_normalization_stats(path: Path) -> list[str]:
    """Validate the frozen normalization artifact's method specs."""
    errs: list[str] = []
    doc = json.loads(path.read_text(encoding="utf-8"))

    def check_spec(key: str, spec: dict):
        m = spec.get("method")
        if m not in NORM_METHODS:
            errs.append(f"norm[{key}]: unknown method {m!r}")
            return
        need = {"zscore": ("mean", "std"), "minmax": ("min", "max"),
                "robust": ("median", "iqr"), "log1p_zscore": ("mean", "std")}.get(m, ())
        for f in need:
            if f not in spec:
                errs.append(f"norm[{key}]: method {m} missing {f!r}")
        if m == "minmax" and "min" in spec and "max" in spec and not (spec["min"] < spec["max"]):
            errs.append(f"norm[{key}]: minmax min must be < max")
        clip = spec.get("clip")
        if clip is not None and (not isinstance(clip, list) or len(clip) != 2):
            errs.append(f"norm[{key}]: clip must be a 2-element list or null")

    for k, spec in doc.get("global", {}).items():
        if isinstance(spec, dict) and "method" in spec:
            check_spec(f"global.{k}", spec)
    for mapname, feats in doc.get("per_map", {}).items():
        for k, spec in feats.items():
            if isinstance(spec, dict) and "method" in spec:
                check_spec(f"per_map.{mapname}.{k}", spec)
    return errs


def validate(con: sqlite3.Connection, stats_path: Path | None = None,
             expect_items: int | None = None, raise_on_error: bool = True) -> list[str]:
    """Run all DB validators (+ normalization stats if given). Returns the error list;
    raises CatalogError if raise_on_error and any errors were found."""
    errs: list[str] = []
    errs += validate_maps(con)
    errs += validate_items(con, expect_items)
    errs += validate_markers(con)
    errs += validate_nav_edges(con)
    errs += validate_frag_events(con)
    errs += validate_actor_ticks(con)
    errs += validate_freshness(con)
    if stats_path is not None:
        errs += validate_normalization_stats(stats_path)
    if errs and raise_on_error:
        raise CatalogError(errs)
    return errs


def main(argv: list[str] | None = None) -> int:
    import catalog_load  # local import: only main() needs it
    ap = argparse.ArgumentParser(description="Validate a komodobots catalog build")
    ap.add_argument("--catalog-dir", type=Path, required=True)
    ap.add_argument("--fixture-dir", type=Path, default=None)
    ap.add_argument("--stats", type=Path, default=None, help="normalization_stats json")
    ap.add_argument("--expect-items", type=int, default=None)
    args = ap.parse_args(argv)
    con, _ = catalog_load.build(args.catalog_dir, args.fixture_dir)
    errs = validate(con, args.stats, args.expect_items, raise_on_error=False)
    if errs:
        print("FAIL:\n  - " + "\n  - ".join(errs))
        return 1
    print("OK: catalog valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
