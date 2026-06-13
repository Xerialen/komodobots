#!/usr/bin/env python3
"""Stage-0 Spike 4 — build the DM3 4on4 elite-anchor distributions.

Reads the committed movement-signature evidence (S7c, MVD-event-rate plane) plus
the per-demo ``analysis.json`` of each anchor demo (qw-analyze, KTX-stream plane)
and emits ``references/dm3_4on4_anchors.json`` with PER-PLAYER spread + pool
min/max for every gate-relevant metric.

SAME-PLANE DISCIPLINE
---------------------
Two distinct measurement planes are used and are NEVER mixed in a single metric:

  * ``mvd_event_rate_finite_difference`` — horizontal speed / air ratios. Derived
    by ``scripts/extract_movement_metrics.py`` from qw-analyze ``-format events``
    kind:5 player-origin samples (native MVD position event rate, ~13 ms), speed =
    hypot(dx,dy)/dt between consecutive samples. This is the SAME plane the bot is
    scored on (bot lab runs emit the same events.txt). NOT a 100 Hz pmove trace.
  * ``ktx_demoinfo_stream`` — economy / aim / combat / positioning. Derived from
    the KTX ``mvdhidden_dmgdone`` damage stream, the KTX item took/respawn
    timeline, the v19-corrected frag log, and the loc graph, all carried in
    qw-analyze ``analysis.json``. Count/share-based, plane-agnostic w.r.t. speed.

Movement values are read verbatim from the committed S7c signature JSON so this
script does not re-derive them on a different plane. Economy/aim/positioning are
read from the on-disk anchor ``analysis.json`` files (outside this Git tree, under
the main ``komodobots`` checkout's ``artifacts/`` — gitignored large binaries).

n < 5 distinct demos per band => DIAGNOSTIC-ONLY (program §6 discipline). Today
n = 6 demos across 3 players (2 each), so every band is DIAGNOSTIC-ONLY.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from collections import Counter

# --- Provenance constants (pinned, not guessed) -----------------------------

ANCHOR_PLAYERS = ("Milton", "carapace", "yeti")

# (target_player, run_id, analysis.json relative dir under the human-demos root,
#  demo filename, sha256) — sha256 cross-checked against the S7c aggregate.
ANCHOR_DEMOS = [
    ("Milton", "s5a-milton-dm3-blue-vs-anza-20260602-2022",
     "s5a/s5a-milton-dm3-blue-vs-anza-20260602-2022",
     "4on4_blue_vs_anza[dm3]20260602-2022.mvd",
     "9ca8f72b3afa95ba87830a83478c51bb9b3dd626b733190a4ca2d84b4d66490e"),
    ("Milton", "s7b-milton-dm3-blue-vs-red-20260601-1914",
     "s7b/s7b-milton-dm3-blue-vs-red-20260601-1914",
     "4on4_blue_vs_red[dm3]20260601-1914.mvd",
     "9acddc0807f997cbf59b0873907666f1a16af6624f2691389c22583781d85193"),
    ("carapace", "s5b-carapace-dm3-book-vs-s-20260526-2011",
     "s5b/s5b-carapace-dm3-book-vs-s-20260526-2011",
     "4on4_book_vs_-s-[dm3]20260526-2011.mvd",
     "45f653c08fbb5488e2619a24ee0dd71347316e60265b8e4caaff0f3607ce0f30"),
    ("carapace", "s7b-carapace-dm3-s-vs-sr-20260520-2032",
     "s7b/s7b-carapace-dm3-s-vs-sr-20260520-2032",
     "4on4_-s-_vs_]sr[[dm3]20260520-2032.mvd",
     "2eed3c5acf9cc0b22f391d08ac5eba7c2198b2ba12afb4c27992676fbf00894d"),
    ("yeti", "s5b-yeti-dm3-red-vs-blue-20260530-0322",
     "s5b/s5b-yeti-dm3-red-vs-blue-20260530-0322",
     "4on4_red_vs_blue[dm3]20260530-0322.mvd",
     "adedb2eccb861ebbc96f551fc21c738dc8740ecd327ea11990ede2802f83aff7"),
    ("yeti", "s7b-yeti-dm3-red-vs-blue-20260528-2109",
     "s7b/s7b-yeti-dm3-red-vs-blue-20260528-2109",
     "4on4_red_vs_blue[dm3]20260528-2109.mvd",
     "fa3792df611f650db9c47627812e63f277c9cb2bbb2f06dda4c291ad04e33246"),
]

# Key economy items (KTX item-timeline ``kind`` codes seen in the dm3 corpus).
ECON_ITEMS = {
    "mh": "mega_health",
    "ra": "red_armor",
    "ya": "yellow_armor",
    "quad": "quad",
    "rl": "rocket_launcher",
}

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SIGNATURES = (
    REPO_ROOT / "experiments" / "human_comparison" / "evidence"
    / "player-signatures-s7c-dm3.json"
)
# Anchor analysis.json live in the main checkout's gitignored artifacts/.
DEFAULT_DEMO_ROOT = REPO_ROOT.parent / "komodobots" / "artifacts" / "human-demos"


def stats(values):
    """min/mean/max/spread + n for a list of numbers (None-safe)."""
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


def per_player_block(rows_by_player, key):
    """Build {per_player:{player:{values:[...],stats}}, pool:{stats}, n}."""
    per_player = {}
    pool_vals = []
    for player, rows in rows_by_player.items():
        vals = [r.get(key) for r in rows]
        per_player[player] = {"values": [round(v, 4) if isinstance(v, (int, float)) else v
                                         for v in vals],
                              "stats": stats(vals)}
        pool_vals.extend(vals)
    return {
        "per_player": per_player,
        "pool": stats(pool_vals),
        "n_demos": len(pool_vals),
    }


# --- Movement axis (committed S7c signatures, MVD-event-rate plane) ----------

MOVEMENT_FIELDS = [
    "avg_horizontal_speed_qu_per_s",
    "p95_horizontal_speed_qu_per_s",
    "stationary_time_ratio",
    "low_speed_time_ratio",
    "airborne_proxy_time_ratio",
    "jump_cadence_per_min",
]


def load_movement(signatures_path: Path):
    sig = json.loads(signatures_path.read_text(encoding="utf-8"))
    rows_by_player = {}
    demos_by_player = {}
    for row in sig.get("player_signatures", []):
        player = row.get("target_player") or row.get("player")
        vals = row.get("values", {})
        rows_by_player.setdefault(player, []).append(vals)
        demos_by_player.setdefault(player, []).append(row.get("demo"))
    metrics = {field: per_player_block(rows_by_player, field) for field in MOVEMENT_FIELDS}
    return metrics, sig.get("stage"), sig.get("source_aggregate_path")


# --- Economy / aim / positioning (per-demo analysis.json, KTX-stream plane) --

def load_analysis(demo_root: Path, rel_dir: str):
    path = demo_root / rel_dir / "analysis.json"
    if not path.exists():
        return None, str(path)
    return json.loads(path.read_text(encoding="utf-8")), str(path)


def econ_for_demo(analysis, target):
    """Item-control SHARE for the target on each key economy item.

    Share = (target pickups of item X) / (all-player pickups of item X across the
    whole match). dm3 items are single-spawn (one mega/ra/ya/quad/rl entity), so
    this is a clean contested-pickup share. Plane: ktx_demoinfo_stream.
    """
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
        out[f"{label}_takes"] = tgt
        out[f"{label}_total_takes"] = total
    return out


def aim_for_demo(analysis, target):
    """DDR, EWep, frag efficiency. Plane: ktx_demoinfo_stream.

    DDR family:
      * ddr_ratio   = given / max(taken_enemy,1)        (deepfrag rate.py form)
      * ddr_diff    = given - taken_all                 (rate_individual per-game)
    EWep:
      * ewep_pct    = ewep / given                      (share of dmg on armed foes)
    Frag efficiency (v19-corrected match.players[]):
      * kill_eff    = kills / (kills + deaths)
      * suicides    capped/reported (no fall-feeding)
    """
    dmg = analysis.get("damage", {}).get("byPlayer", {}).get(target, {})
    given = dmg.get("given", 0)
    taken = dmg.get("taken", 0)            # all sources (enemy+team+self+env)
    ewep = dmg.get("ewep", 0)
    out = {
        "damage_given": given,
        "damage_taken_all": taken,
        "ewep": ewep,
        "ddr_ratio": round(given / max(taken, 1), 4),
        "ddr_diff": given - taken,
        "ewep_pct": round(ewep / given, 4) if given else None,
        # EWep victim-weapon buckets (victim's held weapons at hit time)
        "enemyVsSg": dmg.get("enemyVsSg", 0),
        "enemyVsMid": dmg.get("enemyVsMid", 0),
        "enemyVsLg": dmg.get("enemyVsLg", 0),
        "enemyVsRl": dmg.get("enemyVsRl", 0),
        "enemyVsBoth": dmg.get("enemyVsBoth", 0),
    }
    # v19-corrected frag-log scoreboard from match.players[]
    for p in analysis.get("match", {}).get("players", []):
        if p.get("name") == target:
            kills = p.get("kills", 0)
            deaths = p.get("deaths", 0)
            out["frags_net"] = p.get("frags", 0)
            out["kills"] = kills
            out["deaths"] = deaths
            out["suicides"] = p.get("suicides", 0)
            out["kill_efficiency"] = round(kills / (kills + deaths), 4) if (kills + deaths) else None
            break
    return out


def positioning_for_demo(analysis, target):
    """Loc presence: top locs the target's movement passed through.

    Plane: ktx_demoinfo_stream (locGraph nodes/edges are loc-resolved from the
    same position stream). DIAGNOSTIC-ONLY per program G-P1 (PVS-aware presence
    needs the reference pool widened). We report the target's loc-node visit
    spread as a coarse posture signal, not a gate threshold.
    """
    lg = analysis.get("locGraph", {})
    nodes = lg.get("locs", []) or lg.get("nodes", [])
    # locGraph here is not per-player; we surface match-level node/edge counts as a
    # coarse map-coverage descriptor. Per-player loc presence requires streams.li,
    # deferred to a streams-based pass (flagged in the README as not-yet-populated).
    return {
        "locgraph_node_count": len(nodes) if isinstance(nodes, list) else None,
        "locgraph_edge_count": len(lg.get("edges", [])) if isinstance(lg.get("edges"), list) else None,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--signatures", type=Path, default=DEFAULT_SIGNATURES)
    ap.add_argument("--demo-root", type=Path, default=DEFAULT_DEMO_ROOT)
    ap.add_argument("--output", type=Path,
                    default=REPO_ROOT / "references" / "dm3_4on4_anchors.json")
    ap.add_argument("--analyzer-schema-version", type=int, default=21,
                    help="schemaVersion of the on-disk anchor analysis.json")
    args = ap.parse_args()

    # 1. Movement (committed, MVD-event-rate plane)
    movement_metrics, movement_stage, movement_src = load_movement(args.signatures)

    # 2. Economy / aim / positioning (per-demo analysis.json, KTX-stream plane)
    econ_rows, aim_rows, pos_rows = {}, {}, {}
    demo_provenance = []
    missing = []
    for target, run_id, rel_dir, demo, sha in ANCHOR_DEMOS:
        analysis, path = load_analysis(args.demo_root, rel_dir)
        prov = {"target_player": target, "run_id": run_id, "demo": demo,
                "sha256": sha, "analysis_path": path}
        if analysis is None:
            missing.append(run_id)
            prov["status"] = "MISSING_analysis_json"
            demo_provenance.append(prov)
            continue
        prov["status"] = "ok"
        prov["analysis_schema_version"] = analysis.get("schemaVersion")
        prov["map"] = analysis.get("match", {}).get("map")
        prov["duration_ms"] = analysis.get("match", {}).get("duration")
        demo_provenance.append(prov)
        econ_rows.setdefault(target, []).append(econ_for_demo(analysis, target))
        aim_rows.setdefault(target, []).append(aim_for_demo(analysis, target))
        pos_rows.setdefault(target, []).append(positioning_for_demo(analysis, target))

    def block(rows_by_player, keys):
        return {k: per_player_block(rows_by_player, k) for k in keys}

    econ_keys = [f"{lbl}_control_share" for lbl in ECON_ITEMS.values()]
    aim_keys = ["ddr_ratio", "ddr_diff", "ewep_pct", "kill_efficiency",
                "damage_given", "damage_taken_all", "ewep", "kills", "deaths", "suicides"]
    pos_keys = ["locgraph_node_count", "locgraph_edge_count"]

    n_demos = len([d for d in demo_provenance if d.get("status") == "ok"])
    n_players = len(ANCHOR_PLAYERS)
    demos_per_player = {p: sum(1 for d in ANCHOR_DEMOS if d[0] == p) for p in ANCHOR_PLAYERS}
    min_demos_per_player = min(demos_per_player.values()) if demos_per_player else 0
    # Program §6 discipline: a band is trustworthy as a pass/fail threshold only when
    # the pool is wide enough on BOTH axes — distinct players AND demos per player.
    # The infeasibility floor for trustworthy bands is >= 5 players with >= 5 demos
    # each; today's 3 players x 2 demos is far below that, so DIAGNOSTIC-ONLY.
    diagnostic_only = (n_players < 5) or (min_demos_per_player < 5) or (n_demos < 5)

    payload = {
        "schema": "komodobots.dm3_4on4_anchors.v1",
        "stage": "stage0-spike4-anchor-build",
        "map": "dm3",
        "diagnostic_only": diagnostic_only,
        "diagnostic_only_reason": (
            f"n={n_demos} demos across {n_players} players "
            f"(min {min_demos_per_player} demos/player). Trustworthy-band floor is "
            ">=5 players AND >=5 demos/player; this pool is far below it, so EVERY "
            "band is DIAGNOSTIC-ONLY per program §6 discipline. Bands are the "
            "empirical per-player min/max, not single-point thresholds; no gate may "
            "pass/fail a bot on them until the pool widens."
        ),
        "pool_size": {
            "n_demos": n_demos,
            "n_players": n_players,
            "demos_per_player": demos_per_player,
            "min_demos_per_player": min_demos_per_player,
            "trustworthy_band_floor": {"players": 5, "demos_per_player": 5},
        },
        "anchor_players": list(ANCHOR_PLAYERS),
        "anchor_player_selection": {
            "axis": "fantasyquake/scripts/rate_individual.py (carry-corrected "
                    "blended individual+team rating)",
            "evidence": {
                "Milton": "rank #1/108 (tb4_s2 pool), blended=3334.93, games=1224",
                "carapace": "rank #2/108 (tb4_s2 pool), blended=3046.47, games=710",
                "yeti": "not in tb4_s2 reporting pool but 1510 4on4 games in qw-stats.db; "
                        "recognised elite, carried in the S5b/S7b movement reference",
            },
            "note": "rate_individual ranks INDIVIDUAL skill (de-carried), unlike "
                    "rate_4on4.py team W/L; this is the program's clone-selection axis.",
        },
        "measurement_planes": {
            "movement": {
                "id": "mvd_event_rate_finite_difference",
                "description": "qw-analyze -format events kind:5 player-origin samples "
                               "(native MVD position event rate ~13 ms); horizontal "
                               "speed = hypot(dx,dy)/dt between consecutive samples; "
                               "percentiles unweighted per accepted segment. Teleport "
                               "guard drops > 2500 qu/s segments. SAME plane the bot is "
                               "scored on. NOT a 100 Hz pmove trace.",
                "source_script": "scripts/extract_movement_metrics.py "
                                 "(schema komodobots.movement_metrics.v2)",
                "derived_from": "experiments/human_comparison/evidence/"
                                "player-signatures-s7c-dm3.json",
            },
            "economy_aim_positioning": {
                "id": "ktx_demoinfo_stream",
                "description": "qw-analyze analysis.json: KTX mvdhidden_dmgdone damage "
                               "stream (given/taken/EWep buckets), KTX item took/respawn "
                               "timeline, v19-corrected frag log (match.players[] "
                               "kills/deaths/suicides), locGraph. Count/share-based — "
                               "plane-agnostic w.r.t. movement speed.",
                "analyzer_schema_version": args.analyzer_schema_version,
                "analyzer_current_schema_version": 32,
                "schema_caveat": "Anchor analysis.json were produced at schemaVersion=21; "
                                 "the analyzer source is now v32. The damage/items/frag "
                                 "fields used here are stable across that range, but "
                                 "re-analysis at v32 is the clean path before any gate "
                                 "goes non-diagnostic.",
            },
            "same_plane_discipline": "Movement metrics and economy/aim metrics are NEVER "
                                     "combined into a single number. Each metric below "
                                     "names its plane via the 'plane' key.",
        },
        "metrics": {
            "movement": {
                "plane": "mvd_event_rate_finite_difference",
                "source_stage": movement_stage,
                "source_aggregate_path": movement_src,
                "fields": movement_metrics,
            },
            "economy": {
                "plane": "ktx_demoinfo_stream",
                "definition": "item-control share = target pickups / all-player pickups "
                              "of that item across the match (dm3 single-spawn items).",
                "gate": "G-E1 item-control share (RA/YA/mega/quad/RL)",
                "fields": block(econ_rows, econ_keys),
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
                "fields": block(aim_rows, aim_keys),
            },
            "positioning": {
                "plane": "ktx_demoinfo_stream",
                "status": "PARTIAL — match-level locGraph coverage only; per-player loc "
                          "presence (G-P1) needs a streams.li pass, not yet populated.",
                "gate": "G-P1 presence (DIAGNOSTIC-ONLY per program until pool widens)",
                "fields": block(pos_rows, pos_keys),
            },
        },
        "provenance": {
            "demos": demo_provenance,
            "n_demos_ok": n_demos,
            "missing_demos": missing,
            "rate_individual": {
                "script": "fantasyquake/scripts/rate_individual.py",
                "db": "fantasyquake/backups/qw-stats.db",
                "ratings_artifact": "fantasyquake/data/individual_ratings.json",
                "ratings_git_commit": "4f5fa39",
                "window": "all-time",
            },
            "movement_signatures": {
                "path": "experiments/human_comparison/evidence/player-signatures-s7c-dm3.json",
                "stage": movement_stage,
            },
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print(f"wrote {args.output}")
    print(f"  n_demos_ok={n_demos}  diagnostic_only={diagnostic_only}  missing={missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
