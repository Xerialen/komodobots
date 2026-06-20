"""dm3_leg_traffic.py — all-player landmark->landmark leg-traffic counts (#315 demo).

END-CRITERION DEMO for #315: prove the rebuilt catalog's all-player world-state layer
(`actor_ticks`, the agent_observation layer populated by PR #296) is actually USABLE for
all-player analysis. Given a populated catalog + the dm3 landmark set, it counts how often
EVERY observed actor (self ego + in-PVS observed others) travels from one named landmark to
the next.

This is a deliberately LIGHTWEIGHT AGGREGATE, NOT the Phase-1 route segmenter (#319):

  * landmark assignment is a plain nearest-landmark snap (3D Euclidean to the
    `lab/dashboard/public/data/map_entities/dm3.json` entity `loc` points), optionally
    gated by a max snap radius. It is NOT BSP/PVS-aware, does not model teleporters,
    height layers, jump arcs, item pickups, or dwell time, and does not segment a
    trajectory into canonical routes.
  * a "leg" is simply a transition between two DISTINCT consecutive landmark visits
    within one (episode, actor) timeline (consecutive identical snaps are collapsed to
    a single visit). Direction is kept (A->B != B->A).

It exists to show the data flows end to end and the all-player traffic is measurable.
Treat the numbers as a coarse traffic proxy, not a validated route census.

Honest coverage caveat (carried from #315): `actor_ticks` holds OBSERVED-OTHERS (in-PVS,
with occlusion gaps; per-demo other-coverage is partial), NOT a true omniscient 8-player
view. It is enough to make all-player landmark traffic measurable; a perfectly clean
8-player view needs the Go mvd_analyzer or multi-POV .qwd fusion (docs/13) later.

Pure stdlib (sqlite3 + json + math). Usage:

    python3 scripts/dm3_leg_traffic.py --db <catalog>.sqlite [--top 25] \
        [--landmarks lab/dashboard/public/data/map_entities/dm3.json] \
        [--max-snap-qu 600] [--map dm3] [--self-only] [--json]
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DEFAULT_LANDMARKS = (REPO_ROOT / "lab" / "dashboard" / "public" / "data"
                     / "map_entities" / "dm3.json")


def load_landmarks(path: Path) -> list[tuple[str, float, float, float]]:
    """Return [(name, x, y, z)] for every map entity carrying a `loc` label + xyz.

    Several entities can share a `loc` (e.g. the SNG.low health pair); each is kept as a
    candidate snap point, all mapping to the same landmark NAME, so a position snaps to
    the named area whichever of its co-located entities is closest.
    """
    doc = json.loads(path.read_text(encoding="utf-8"))
    out: list[tuple[str, float, float, float]] = []
    for e in doc.get("entities", []):
        name = e.get("loc") or e.get("name")
        if name is None:
            continue
        if not all(k in e for k in ("x", "y", "z")):
            continue
        out.append((str(name), float(e["x"]), float(e["y"]), float(e["z"])))
    return out


def resolve_max_snap(max_snap_qu: float | None) -> float | None:
    """Resolve the --max-snap-qu CLI value to the `nearest_landmark` cutoff.

    `0` (or any non-positive value) is the DOCUMENTED "disable the cutoff" sentinel and
    must map to None. The check is EXPLICIT (`is not None and <= 0`) because `0.0` is
    falsey: a plain `if max_snap_qu` would let 0.0 fall through as a 0-radius cutoff,
    which silently rejects every position not sitting exactly on a landmark.
    """
    if max_snap_qu is not None and max_snap_qu <= 0:
        return None
    return max_snap_qu


def nearest_landmark(ox: float, oy: float, oz: float,
                     landmarks: list[tuple[str, float, float, float]],
                     max_snap_qu: float | None) -> str | None:
    """Nearest landmark NAME by 3D Euclidean distance, or None if the closest is farther
    than `max_snap_qu` (so mid-corridor positions far from any landmark are not forced
    onto one). Linear scan — the landmark set is tiny (tens of points)."""
    best_name = None
    best_d2 = math.inf
    for name, lx, ly, lz in landmarks:
        d2 = (ox - lx) ** 2 + (oy - ly) ** 2 + (oz - lz) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_name = name
    if best_name is None:
        return None
    if max_snap_qu is not None and best_d2 > max_snap_qu * max_snap_qu:
        return None
    return best_name


def leg_counts(con: sqlite3.Connection,
               landmarks: list[tuple[str, float, float, float]],
               map_name: str = "dm3",
               max_snap_qu: float | None = 600.0,
               self_only: bool = False) -> dict:
    """Compute directed landmark->landmark leg counts across ALL actors in `actor_ticks`.

    For each (episode_id, actor_id) timeline ordered by tick: snap each row to its nearest
    landmark, collapse consecutive identical snaps into a single visit, and emit each
    transition between two DISTINCT consecutive visits as one directed leg.
    """
    (map_id,) = con.execute("SELECT map_id FROM maps WHERE name=?", (map_name,)).fetchone()

    # restrict to actors on this map; optionally to the self ego only (actor == episode owner).
    where_self = "AND a.actor_id = e.player_id" if self_only else ""
    rows = con.execute(
        f"""SELECT a.episode_id, a.actor_id, a.tick, a.ox, a.oy, a.oz
            FROM actor_ticks a
            JOIN episodes e ON e.episode_id = a.episode_id
            WHERE e.map_id = ? {where_self}
            ORDER BY a.episode_id, a.actor_id, a.tick""",
        (map_id,),
    ).fetchall()

    legs: Counter = Counter()
    visits: Counter = Counter()
    cur_key = None
    last_lm = None
    n_actor_timelines = 0
    n_snapped = 0
    n_total = 0
    for ep_id, actor_id, _tick, ox, oy, oz in rows:
        key = (ep_id, actor_id)
        if key != cur_key:
            cur_key = key
            last_lm = None
            n_actor_timelines += 1
        n_total += 1
        lm = nearest_landmark(ox, oy, oz, landmarks, max_snap_qu)
        if lm is None:
            continue  # out of snap range -> not at a named landmark this tick
        n_snapped += 1
        if lm != last_lm:
            visits[lm] += 1
            if last_lm is not None:
                legs[(last_lm, lm)] += 1
            last_lm = lm

    return {
        "map": map_name,
        "self_only": self_only,
        "max_snap_qu": max_snap_qu,
        "actor_timelines": n_actor_timelines,
        "actor_ticks_total": n_total,
        "actor_ticks_snapped": n_snapped,
        "snap_fraction": round(n_snapped / n_total, 4) if n_total else 0.0,
        "distinct_landmarks_visited": len(visits),
        "distinct_legs": len(legs),
        "total_legs": int(sum(legs.values())),
        "legs": legs,          # Counter[(from, to)] -> count
        "visits": visits,      # Counter[landmark] -> visit count
    }


def format_table(result: dict, top: int) -> str:
    legs: Counter = result["legs"]
    lines = []
    lines.append(
        "dm3 all-player leg traffic  (map=%s, self_only=%s, snap<=%s qu)"
        % (result["map"], result["self_only"], result["max_snap_qu"]))
    lines.append(
        "  actor timelines=%d  actor_ticks=%d  snapped=%d (%.1f%%)  "
        "landmarks=%d  distinct legs=%d  total legs=%d"
        % (result["actor_timelines"], result["actor_ticks_total"],
           result["actor_ticks_snapped"], 100.0 * result["snap_fraction"],
           result["distinct_landmarks_visited"], result["distinct_legs"],
           result["total_legs"]))
    lines.append("")
    lines.append("  %-5s  %-28s  %s" % ("count", "leg (from -> to)", ""))
    lines.append("  %s" % ("-" * 45))
    for (frm, to), n in legs.most_common(top):
        lines.append("  %5d  %-12s -> %-12s" % (n, frm, to))
    if not legs:
        lines.append("  (no legs — is actor_ticks populated? a STALE pre-#296 catalog is empty)")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="populated catalog .sqlite (gitignored/regenerable)")
    ap.add_argument("--landmarks", type=Path, default=DEFAULT_LANDMARKS,
                    help="map_entities dm3.json (default: committed dashboard copy)")
    ap.add_argument("--map", default="dm3")
    ap.add_argument("--top", type=int, default=25, help="how many top legs to print")
    ap.add_argument("--max-snap-qu", type=float, default=600.0,
                    help="max snap radius in quake units; None-like 0 disables the cutoff")
    ap.add_argument("--self-only", action="store_true",
                    help="count only the self-POV ego actor (sanity baseline)")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args(argv)

    max_snap = resolve_max_snap(args.max_snap_qu)
    landmarks = load_landmarks(args.landmarks)
    if not landmarks:
        print("ERROR: no landmarks loaded from %s" % args.landmarks)
        return 2

    con = sqlite3.connect(args.db)
    try:
        result = leg_counts(con, landmarks, map_name=args.map,
                            max_snap_qu=max_snap, self_only=args.self_only)
    finally:
        con.close()

    if args.json:
        # Counters aren't JSON-native with tuple keys -> serialize as lists.
        payload = dict(result)
        payload["legs"] = [{"from": f, "to": t, "count": n}
                           for (f, t), n in result["legs"].most_common()]
        payload["visits"] = [{"landmark": k, "visits": v}
                             for k, v in result["visits"].most_common()]
        print(json.dumps(payload, indent=2))
    else:
        print(format_table(result, args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
