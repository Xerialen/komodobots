#!/usr/bin/env python3
"""Stage-0 Spike-4 (HARDENED) — build the DM3 4on4 elite-anchor distributions.

This supersedes the diagnostic-only v1 anchor (3 players x 2 demos, schema v21,
positioning only partial). It widens the pool to >=5 elite players with >=5 dm3
4on4 demos each, re-analyzes every demo at the CURRENT mvd_analyzer schema (v32),
derives ALL four gate families (M / E / A / P) from a single per-demo v32
``analysis.json``, and adds the per-player positioning (G-P1) loc-presence pass
that v1 was missing.

CORPUS
------
A single per-demo v32 ``analysis.json`` (qw-analyze, schema v32, run with
``-include positions,velocity``) carries every signal the anchor needs:
``streams.players[].pos`` (movement), ``items`` (economy), ``damage.byPlayer`` +
``match.players[]`` (aim/combat), and ``streams.players[].pos.li`` (per-player loc
presence -> positioning). Because each MVD records ALL players, every demo a
target appears in contributes one per-player sample for that target. The corpus
is built from:

  * the 7 modern-KTX dm3 4on4 MVDs on disk under the main komodobots checkout
    (``artifacts/human-demos/source/``), and
  * additional recent dm3 4on4 MVDs pulled from the public QuakeWorld Hub CDN
    (``https://d.quake.world/<sha[:3]>/<sha>.mvd.gz``) for the elite anchor pool.

Both are downloaded/analyzed in WSL2 per the machine hosting policy (see
references/dm3_4on4_anchors.README.md "How this was built").

SAME-PLANE DISCIPLINE
---------------------
Two distinct measurement planes are used and are NEVER mixed in a single metric.
Each emitted metric names its ``plane``.

  * ``mvd_event_rate_finite_difference`` (movement) -- horizontal speed / air
    ratios. Computed HERE, in this script, by a FORWARD finite difference of the
    v32 ``streams.players[].pos`` columns (t/x/y/z), native MVD position event
    rate (~13 ms), speed = hypot(dx,dy)/dt between consecutive samples,
    percentiles unweighted per accepted segment, teleport guard drops segments
    > 2500 qu/s. This is byte-for-byte the same method (and thresholds) as
    ``scripts/extract_movement_metrics.py`` (``komodobots.movement_metrics.v2``),
    which is the SAME plane the bot is scored on (bot lab runs emit the same
    kind:5 origin stream). It is NOT a 100 Hz pmove trace, and it is NOT the v32
    ``vx/vy`` central-difference column (which would be a different estimator on
    the same stream). Computing it here keeps the local-corpus and hub-corpus
    demos on one identical estimator.
  * ``ktx_demoinfo_stream`` (economy / aim / positioning) -- count/share-based,
    plane-agnostic w.r.t. movement speed. From the KTX ``mvdhidden_dmgdone``
    damage stream, the KTX item took/respawn timeline, the v19-corrected frag log
    (``match.players[]``), and the per-sample loc index (``pos.li`` ->
    ``timelineAnalysis.locTable``).

PROMOTION RULE (program section 6)
----------------------------------
A band may be promoted OFF ``diagnostic_only`` only where BOTH axes clear the
trustworthy floor: >= 5 distinct anchor players AND >= 5 distinct demos for every
one of those players, on that metric. Movement (M) and economy/aim/positioning
(E/A/P) are evaluated independently because they come from the same demos but the
floor is checked per metric family. Any family that does not clear the floor stays
diagnostic-only and says so.
"""

from __future__ import annotations

import logging
import argparse
import hashlib
import json
import math
from bisect import bisect_right
from collections import Counter, defaultdict
from pathlib import Path


LOGGER = logging.getLogger(__name__)
# --------------------------------------------------------------------------- #
# Movement method constants -- IDENTICAL to scripts/extract_movement_metrics.py #
# (komodobots.movement_metrics.v2) so the anchor plane matches the bot-scoring  #
# plane exactly.                                                                #
# --------------------------------------------------------------------------- #
STATIONARY_SPEED = 10.0
LOW_SPEED = 100.0
HIGH_SPEED = 400.0
TELEPORT_SPEED = 2500.0
DEFAULT_MAXSPEED = 320.0
VERTICAL_EPSILON = 0.25
VERTICAL_SPEED = 40.0
AIRBORNE_MIN_DURATION_MS = 120
AIRBORNE_MIN_Z_DELTA = 4.0

ANCHOR_SCHEMA = "komodobots.dm3_4on4_anchors.v2"
ANALYZER_SCHEMA_VERSION = 32
TRUSTWORTHY_FLOOR_PLAYERS = 5
TRUSTWORTHY_FLOOR_DEMOS = 5

# Key dm3 economy items (single-spawn) -> KTX item-timeline ``kind`` codes.
ECON_ITEMS = {
    "mh": "mega_health",
    "ra": "red_armor",
    "ya": "yellow_armor",
    "quad": "quad",
    "rl": "rocket_launcher",
}

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# stats helpers                                                                 #
# --------------------------------------------------------------------------- #
def stats(values):
    nums = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not nums:
        return {"n": 0, "min": None, "mean": None, "max": None, "spread": None}
    lo, hi = min(nums), max(nums)
    return {
        "n": len(nums),
        "min": round(lo, 4),
        "mean": round(sum(nums) / len(nums), 4),
        "max": round(hi, 4),
        "spread": round(hi - lo, 4),
    }


def percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def per_player_block(rows_by_player, key, pool_players):
    """{per_player:{player:{values,stats}}, pool:{stats}, n_players, n_demos_min}."""
    per_player = {}
    pool_vals = []
    demo_counts = []
    for player in pool_players:
        rows = rows_by_player.get(player, [])
        vals = [r.get(key) for r in rows]
        present = [v for v in vals if v is not None]
        per_player[player] = {
            "values": [round(v, 4) if isinstance(v, (int, float)) else v for v in vals],
            "stats": stats(vals),
        }
        pool_vals.extend(vals)
        demo_counts.append(len(present))
    return {
        "per_player": per_player,
        "pool": stats(pool_vals),
        "n_players": sum(1 for c in demo_counts if c > 0),
        "min_demos_per_player": min(demo_counts) if demo_counts else 0,
        "n_demos": len([v for v in pool_vals if v is not None]),
    }


# --------------------------------------------------------------------------- #
# Movement axis -- forward finite-difference on v32 streams pos (same plane)    #
# --------------------------------------------------------------------------- #
def _airborne_runs(segments):
    runs = []
    current = None
    for seg in segments:
        if seg["vertical_motion"]:
            if current is None:
                current = {"start_ms": seg["start_ms"], "end_ms": seg["end_ms"],
                           "z_min": min(seg["start_z"], seg["end_z"]),
                           "z_max": max(seg["start_z"], seg["end_z"])}
            else:
                current["end_ms"] = seg["end_ms"]
                current["z_min"] = min(current["z_min"], seg["start_z"], seg["end_z"])
                current["z_max"] = max(current["z_max"], seg["start_z"], seg["end_z"])
        elif current is not None:
            dur = current["end_ms"] - current["start_ms"]
            zd = current["z_max"] - current["z_min"]
            if dur >= AIRBORNE_MIN_DURATION_MS and zd >= AIRBORNE_MIN_Z_DELTA:
                runs.append(current)
            current = None
    if current is not None:
        dur = current["end_ms"] - current["start_ms"]
        zd = current["z_max"] - current["z_min"]
        if dur >= AIRBORNE_MIN_DURATION_MS and zd >= AIRBORNE_MIN_Z_DELTA:
            runs.append(current)
    return runs


def movement_for_player(pos, maxspeed):
    """Replicate compute_slot_metrics on the (t,x,y,z) of one player's v32 pos.

    Returns the six movement fields the anchor reports, or None if no samples.
    """
    ts, xs, ys, zs = pos.get("t"), pos.get("x"), pos.get("y"), pos.get("z")
    if not ts or len(ts) < 2:
        return None
    samples = sorted(zip(ts, xs, ys, zs), key=lambda s: s[0])

    active_ms = 0
    horizontal_distance = 0.0
    stationary_ms = low_speed_ms = vertical_motion_ms = 0
    speeds = []
    accepted = []
    prev = samples[0]
    for cur in samples[1:]:
        dt_ms = cur[0] - prev[0]
        if dt_ms <= 0:
            prev = cur
            continue
        dx, dy, dz = cur[1] - prev[1], cur[2] - prev[2], cur[3] - prev[3]
        dist = math.hypot(dx, dy)
        speed = dist / (dt_ms / 1000.0)
        vspeed = dz / (dt_ms / 1000.0)
        if speed > TELEPORT_SPEED or abs(vspeed) > TELEPORT_SPEED:
            prev = cur
            continue
        vmotion = abs(dz) >= VERTICAL_EPSILON or abs(vspeed) >= VERTICAL_SPEED
        active_ms += dt_ms
        horizontal_distance += dist
        speeds.append(speed)
        accepted.append({"start_ms": prev[0], "end_ms": cur[0],
                         "start_z": prev[3], "end_z": cur[3],
                         "vertical_motion": vmotion})
        if speed < STATIONARY_SPEED:
            stationary_ms += dt_ms
        if speed < LOW_SPEED:
            low_speed_ms += dt_ms
        if vmotion:
            vertical_motion_ms += dt_ms
        prev = cur

    if active_ms <= 0:
        return None
    active_s = active_ms / 1000.0
    avg_speed = horizontal_distance / active_s
    runs = _airborne_runs(accepted)
    airborne_ms = sum(r["end_ms"] - r["start_ms"] for r in runs)
    return {
        "avg_horizontal_speed_qu_per_s": round(avg_speed, 3),
        "p95_horizontal_speed_qu_per_s": round(percentile(speeds, 95), 3),
        "stationary_time_ratio": round(stationary_ms / active_ms, 3),
        "low_speed_time_ratio": round(low_speed_ms / active_ms, 3),
        "airborne_proxy_time_ratio": round(airborne_ms / active_ms, 3),
        "jump_cadence_per_min": round(len(runs) / active_s * 60.0, 3),
    }


# --------------------------------------------------------------------------- #
# Economy / Aim / Positioning -- ktx_demoinfo_stream                            #
# --------------------------------------------------------------------------- #
def econ_for_demo(analysis, target):
    took = {code: Counter() for code in ECON_ITEMS}
    for it in analysis.get("items", {}).get("items", []):
        kind = it.get("kind")
        if kind not in ECON_ITEMS:
            continue
        for ph in it.get("phases", []):
            tb = ph.get("takenBy")
            if tb:
                took[kind][tb] += 1
    out = {}
    for code, label in ECON_ITEMS.items():
        total = sum(took[code].values())
        tgt = took[code].get(target, 0)
        out[f"{label}_control_share"] = round(tgt / total, 4) if total else None
    return out


def aim_for_demo(analysis, target):
    dmg = analysis.get("damage", {}).get("byPlayer", {}).get(target, {})
    given = dmg.get("given", 0)
    taken = dmg.get("taken", 0)
    ewep = dmg.get("ewep", 0)
    out = {
        "damage_given": given,
        "damage_taken_all": taken,
        "ewep": ewep,
        "ddr_ratio": round(given / max(taken, 1), 4),
        "ddr_diff": given - taken,
        "ewep_pct": round(ewep / given, 4) if given else None,
    }
    for p in analysis.get("match", {}).get("players", []):
        if p.get("name") == target:
            kills = p.get("kills", 0)
            deaths = p.get("deaths", 0)
            out["kills"] = kills
            out["deaths"] = deaths
            out["suicides"] = p.get("suicides", 0)
            out["kill_efficiency"] = round(kills / (kills + deaths), 4) if (kills + deaths) else None
            break
    return out


# Regions of interest for the per-player loc-presence pass (G-P1). Each maps to a
# set of dm3 loc names; presence = fraction of a player's accepted position
# samples whose resolved loc falls in that region. This is the streams.li pass
# v1 was missing. Loc-name spellings are taken verbatim from the v32 locTable.
DM3_REGIONS = {
    "ra_region": ["RA", "RA.entry", "RA.low", "RA.rox", "RA.tunnel"],
    "ya_region": ["YA", "YA.entry", "YA.box", "YA.up", "YA.Quad"],
    "mega_region": ["SNG.MH", "SNG", "SNG.low", "SNG.ledge", "SNG.tele", "SNG.lifts"],
    "quad_region": ["Quad", "YA.Quad", "window.Quad"],
    "pent_region": ["Pent", "Pent.hide", "Ring"],
    "rl_region": ["RL", "bridge.low", "bridge.stairs", "bridge.high"],
    "water_region": ["water", "water.LG", "water.tunnel", "water.GL", "water.rox"],
}


def positioning_for_demo(analysis, target):
    """Per-player loc presence -- the G-P1 streams.li pass missing from v1.

    Plane: ktx_demoinfo_stream. For the target's own position stream, resolve each
    sample's loc index against locTable and report the share of samples spent in
    each region of interest, plus loc-coverage breadth (distinct locs visited).
    """
    loc_table = analysis.get("timelineAnalysis", {}).get("locTable") or []
    # invert region defs -> loc-name set
    region_locs = {r: set(names) for r, names in DM3_REGIONS.items()}
    streams = analysis.get("streams", {}).get("players", [])
    tgt = next((s for s in streams if s.get("name") == target), None)
    if not tgt:
        return None
    pos = tgt.get("pos") or {}
    li = pos.get("li")
    if not li:
        return None
    counts = Counter(li)
    total = sum(counts.values())
    if total == 0:
        return None
    # name -> sample count
    name_counts = Counter()
    for idx, c in counts.items():
        if 0 <= idx < len(loc_table):
            nm = loc_table[idx]
            if nm:
                name_counts[nm] += c
    out = {}
    for region, locs in region_locs.items():
        s = sum(name_counts.get(n, 0) for n in locs)
        out[f"{region}_presence_share"] = round(s / total, 4)
    out["distinct_locs_visited"] = len([n for n, c in name_counts.items() if c > 0])
    return out


# --------------------------------------------------------------------------- #
# main                                                                          #
# --------------------------------------------------------------------------- #
def maxspeed_of(analysis):
    md = analysis.get("metadata", {}) or {}
    cv = md.get("serverInfo") or md.get("serverinfo") or {}
    if not isinstance(cv, dict):
        return DEFAULT_MAXSPEED
    try:
        return float(cv.get("maxspeed", DEFAULT_MAXSPEED))
    except (TypeError, ValueError):
        return DEFAULT_MAXSPEED


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--analysis-dir", type=Path, required=True,
                    help="dir of v32 analysis.json files, one per demo, named <sha>.json")
    ap.add_argument("--manifest", type=Path, required=True,
                    help="JSON: {pool_players:[...], demos:[{sha256,source,demo,origin}]}")
    ap.add_argument("--output", type=Path,
                    default=REPO_ROOT / "references" / "dm3_4on4_anchors.json")
    args = ap.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    pool_players = manifest["pool_players"]
    demo_manifest = {d["sha256"]: d for d in manifest["demos"]}

    move_rows = defaultdict(list)
    econ_rows = defaultdict(list)
    aim_rows = defaultdict(list)
    pos_rows = defaultdict(list)
    demo_provenance = []

    for sha, meta in demo_manifest.items():
        path = args.analysis_dir / f"{sha}.json"
        prov = {**meta, "analysis_path": str(path)}
        if not path.exists():
            prov["status"] = "MISSING_analysis_json"
            demo_provenance.append(prov)
            continue
        analysis = json.loads(path.read_text(encoding="utf-8"))
        prov["status"] = "ok"
        prov["analysis_schema_version"] = analysis.get("schemaVersion")
        prov["map"] = analysis.get("match", {}).get("map")
        prov["duration_ms"] = analysis.get("match", {}).get("duration")
        roster = set(p.get("name") for p in analysis.get("match", {}).get("players", []))
        roster |= set(analysis.get("damage", {}).get("byPlayer", {}).keys())
        prov["pool_players_present"] = sorted(p for p in pool_players if p in roster)
        demo_provenance.append(prov)

        ms = maxspeed_of(analysis)
        streams = {s.get("name"): s for s in analysis.get("streams", {}).get("players", [])}
        for player in pool_players:
            if player not in roster:
                continue
            st = streams.get(player)
            if st and st.get("pos"):
                mv = movement_for_player(st["pos"], ms)
                if mv:
                    move_rows[player].append(mv)
            econ_rows[player].append(econ_for_demo(analysis, player))
            aim_rows[player].append(aim_for_demo(analysis, player))
            p = positioning_for_demo(analysis, player)
            if p:
                pos_rows[player].append(p)

    n_ok = sum(1 for d in demo_provenance if d.get("status") == "ok")

    MOVE_KEYS = ["avg_horizontal_speed_qu_per_s", "p95_horizontal_speed_qu_per_s",
                 "stationary_time_ratio", "low_speed_time_ratio",
                 "airborne_proxy_time_ratio", "jump_cadence_per_min"]
    ECON_KEYS = [f"{lbl}_control_share" for lbl in ECON_ITEMS.values()]
    AIM_KEYS = ["ddr_ratio", "ddr_diff", "ewep_pct", "kill_efficiency",
                "damage_given", "damage_taken_all", "ewep", "kills", "deaths", "suicides"]
    POS_KEYS = [f"{r}_presence_share" for r in DM3_REGIONS] + ["distinct_locs_visited"]

    def block(rows_by_player, keys):
        return {k: per_player_block(rows_by_player, k, pool_players) for k in keys}

    move_block = block(move_rows, MOVE_KEYS)
    econ_block = block(econ_rows, ECON_KEYS)
    aim_block = block(aim_rows, AIM_KEYS)
    pos_block = block(pos_rows, POS_KEYS)

    def family_promotable(b):
        """A family is promotable iff EVERY metric clears the floor on BOTH axes."""
        for m in b.values():
            if m["n_players"] < TRUSTWORTHY_FLOOR_PLAYERS:
                return False
            if m["min_demos_per_player"] < TRUSTWORTHY_FLOOR_DEMOS:
                return False
        return True

    move_promotable = family_promotable(move_block)
    econ_promotable = family_promotable(econ_block)
    aim_promotable = family_promotable(aim_block)
    pos_promotable = family_promotable(pos_block)

    # demos-per-player tally (distinct demos a player appears in, on the E/A axis
    # which is present whenever the player is in the roster)
    demos_per_player = {p: len(aim_rows.get(p, [])) for p in pool_players}
    min_dpp = min(demos_per_player.values()) if demos_per_player else 0

    overall_diagnostic = not (move_promotable and econ_promotable and aim_promotable and pos_promotable)

    payload = {
        "schema": ANCHOR_SCHEMA,
        "stage": "stage0-spike4-anchor-build-HARDENED",
        "map": "dm3",
        "diagnostic_only": overall_diagnostic,
        "promotion_status": {
            "movement": "promoted" if move_promotable else "diagnostic_only",
            "economy": "promoted" if econ_promotable else "diagnostic_only",
            "aim_combat": "promoted" if aim_promotable else "diagnostic_only",
            "positioning": "promoted" if pos_promotable else "diagnostic_only",
            "rule": (
                f"A family is promoted off diagnostic_only iff every metric in it "
                f"clears the floor on BOTH axes: >= {TRUSTWORTHY_FLOOR_PLAYERS} "
                f"distinct anchor players AND >= {TRUSTWORTHY_FLOOR_DEMOS} distinct "
                f"demos for each of those players. Promoted bands are still the "
                f"empirical per-player min/max envelope, not a single-point cut."
            ),
        },
        "pool_size": {
            "n_demos": n_ok,
            "n_players": len(pool_players),
            "demos_per_player": demos_per_player,
            "min_demos_per_player": min_dpp,
            "trustworthy_band_floor": {
                "players": TRUSTWORTHY_FLOOR_PLAYERS,
                "demos_per_player": TRUSTWORTHY_FLOOR_DEMOS,
            },
        },
        "anchor_players": pool_players,
        "anchor_player_selection": manifest.get("anchor_player_selection", {}),
        "measurement_planes": {
            "movement": {
                "id": "mvd_event_rate_finite_difference",
                "description": (
                    "FORWARD finite difference of v32 streams.players[].pos (t/x/y/z), "
                    "native MVD position event rate ~13 ms; horizontal speed = "
                    "hypot(dx,dy)/dt between consecutive samples; percentiles unweighted "
                    "per accepted segment; teleport guard drops > 2500 qu/s segments. "
                    "IDENTICAL method + thresholds to scripts/extract_movement_metrics.py "
                    "(komodobots.movement_metrics.v2) -- the SAME plane the bot is scored "
                    "on. NOT a 100 Hz pmove trace; NOT the v32 vx/vy central-difference "
                    "column (a different estimator on the same stream)."
                ),
                "computed_by": "scripts/extract_dm3_4on4_anchors.py::movement_for_player",
            },
            "economy_aim_positioning": {
                "id": "ktx_demoinfo_stream",
                "description": (
                    "qw-analyze v32 analysis.json: KTX mvdhidden_dmgdone damage stream "
                    "(given/taken/EWep buckets), KTX item took/respawn timeline "
                    "(items.items[].phases[].takenBy), v19-corrected frag log "
                    "(match.players[] kills/deaths/suicides), and per-sample loc index "
                    "(streams.players[].pos.li -> timelineAnalysis.locTable) for the "
                    "per-player positioning presence pass. Count/share-based, "
                    "plane-agnostic w.r.t. movement speed."
                ),
                "analyzer_schema_version": ANALYZER_SCHEMA_VERSION,
            },
            "same_plane_discipline": (
                "Movement metrics and economy/aim/positioning metrics are NEVER combined "
                "into a single number. Each metric below names its plane via the 'plane' key."
            ),
        },
        "metrics": {
            "movement": {
                "plane": "mvd_event_rate_finite_difference",
                "promotion_status": "promoted" if move_promotable else "diagnostic_only",
                "fields": move_block,
            },
            "economy": {
                "plane": "ktx_demoinfo_stream",
                "definition": "item-control share = target pickups / all-player pickups of that single-spawn dm3 item across the match.",
                "gate": "G-E1 item-control share (RA/YA/mega/quad/RL)",
                "promotion_status": "promoted" if econ_promotable else "diagnostic_only",
                "fields": econ_block,
            },
            "aim_combat": {
                "plane": "ktx_demoinfo_stream",
                "definition": {
                    "ddr_ratio": "given / max(taken_all,1) (deepfrag rate.py DDR form)",
                    "ddr_diff": "given - taken_all (rate_individual per-game diff)",
                    "ewep_pct": "ewep / given (share of damage dealt to RL/LG-armed foes)",
                    "kill_efficiency": "kills / (kills+deaths), v19-corrected frag log",
                },
                "gate": "G-A1 DDR, G-A2 frag efficiency (v19), G-A3/A4 EWep distribution",
                "promotion_status": "promoted" if aim_promotable else "diagnostic_only",
                "fields": aim_block,
            },
            "positioning": {
                "plane": "ktx_demoinfo_stream",
                "definition": (
                    "per-player loc-presence share = fraction of the target's own "
                    "position samples whose resolved loc (streams pos.li -> locTable) "
                    "falls in a region of interest. This IS the streams.li per-player "
                    "pass that the v1 anchor was missing (v1 had only match-level "
                    "locGraph node/edge counts)."
                ),
                "gate": "G-P1 presence vs human inter-player spread",
                "promotion_status": "promoted" if pos_promotable else "diagnostic_only",
                "fields": pos_block,
            },
        },
        "provenance": {
            "demos": demo_provenance,
            "n_demos_ok": n_ok,
            "analyzer": {
                "tool": "tools/mvd_analyzer qw-analyze",
                "schema_version": ANALYZER_SCHEMA_VERSION,
                "invocation": "qw-analyze -format json -include positions,velocity <demo>",
                "built_in": "WSL2 Ubuntu-24.04, go1.25.10 (machine hosting policy)",
            },
            "rate_individual": manifest.get("rate_individual", {}),
            "hub_corpus": manifest.get("hub_corpus", {}),
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print(f"wrote {args.output}")
    print(f"  n_demos_ok={n_ok}  players={len(pool_players)}  min_demos/player={min_dpp}")
    print(f"  promotable: move={move_promotable} econ={econ_promotable} "
          f"aim={aim_promotable} pos={pos_promotable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
