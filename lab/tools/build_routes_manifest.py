#!/usr/bin/env python3
"""Routes manifest builder for the lab dashboard (LD-C1, issue #90).

Exports the committed trick census + human replay trajectories as a stable,
versioned per-map manifest under `lab/dashboard/public/data/routes/`. The
Mockup view (#97), KPI dock (#100/#101) and control drawer (#105) consume
these files; the dashboard never parses experiment-internal files ad hoc.
Stdlib only. Outputs are committed; rerunning the builder over the same
committed sources is byte-identical (no wall clock anywhere).

Sources (committed, never artifacts/ -- the manifests must be reproducible
from a bare checkout, and artifacts/ is gitignored):

  experiments/nav_doctrine/evidence/trick-census/census.json
      11 dm3 routes: duration_s, active/peak speeds, gaps[] with edge/land
      xyz + required_speed + human_speed_at_edge, teleports.
  experiments/nav_doctrine/evidence/replay/dm3_<route>.cmds
      Human trajectories, one frame per line:
      `msec ox oy oz vx vy vz pitch yaw roll fwd side up buttons`
      (the format BotLab3D.parseCmdsPath() already renders).

Schema `komodobots.routes.v1`
-----------------------------
Per-map file `<map>.json` (maps: dm3, dm2, frobodm2, trick, ztricks --
non-dm3 maps carry empty route lists until routes are censused there; ztricks
currently carries the A5 Distance route control metadata plus the successful
11th `getspeed.qwd` human reference and a spawn-floor speed-gain drill):

{
  "schema": "komodobots.routes.v1",
  "v": 1,
  "map": "dm3",
  "routes": [                        # sorted by name; [] for empty maps
    {
      "name": "sng_to_rl",
      "human": {                     # census stats, the dashboard's "human bar"
        "duration_s": 8.99,
        "active_mean_speed": 388.3,
        "peak_speed": 615.4
      },
      "polyline": [[x, y, z], ...],  # downsampled human path (display only):
                                     #  every Nth .cmds frame, N = round(fps /
                                     #  POLYLINE_TARGET_HZ), last frame always
                                     #  kept, coords rounded to 0.1 qu
      "gaps": [                      # census gap geometry for gap markers
        { "edge": [x, y, z], "land": [x, y, z],
          "required_speed": 525.3, "human_speed_at_edge": 528.6,
          "hard": true, "type": "leap" }
      ],
      "teleports": [                 # teleporter entrance/exit markers
        { "from": [x, y, z], "to": [x, y, z] }
      ],
      "source": {                    # per-route provenance
        "census": "experiments/nav_doctrine/evidence/trick-census/census.json",
        "cmds": "experiments/nav_doctrine/evidence/replay/dm3_sng_to_rl.cmds",
        "cmds_sha256": "<hex>"       # over LF-normalized text (see below)
      }
    }
  ],
  "provenance": {
    "census": "experiments/nav_doctrine/evidence/trick-census/census.json",
    "census_sha256": "<hex>",
    "polyline_target_hz": 12.5
  }
}

Index file `index.json` (which maps exist and where):

{
  "schema": "komodobots.routes.v1",
  "v": 1,
  "maps": [
    { "map": "dm3", "file": "dm3.json", "routes": 11 },
    { "map": "dm2", "file": "dm2.json", "routes": 0 },
    ...
  ]
}

Determinism notes
-----------------
* Hashes are sha256 over LF-normalized text (CRLF -> LF): git stores the
  sources with LF but `core.autocrlf` checkouts see CRLF on Windows, and the
  hash must not depend on the platform of the machine that ran the build.
* Output files are written with explicit "\n" and marked `-text` in
  .gitattributes, so a rebuild diffs clean on every platform.
* Per-map files are compact JSON (a polyline under indent=2 would put every
  coordinate on its own line); index.json is small and indented for humans.

Usage:
  python lab/tools/build_routes_manifest.py [--out-dir DIR]

  --out-dir DIR   output directory (default lab/dashboard/public/data/routes)

Exit codes: 0 ok; 2 usage.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

SCHEMA = "komodobots.routes.v1"
SCHEMA_V = 1
MAPS = ("dm3", "dm2", "frobodm2", "trick", "ztricks")   # dashboard map set
POLYLINE_TARGET_HZ = 12.5    # ~5-10 Hz is plenty for display; 12.5 keeps the
                             # shortest routes comfortably dense (sng_to_rl
                             # spot check: >100 points) while staying small

REPO = Path(__file__).resolve().parent.parent.parent
CENSUS_PATH = (REPO / "experiments" / "nav_doctrine" / "evidence"
               / "trick-census" / "census.json")
REPLAY_DIR = REPO / "experiments" / "nav_doctrine" / "evidence" / "replay"
DEFAULT_OUT = REPO / "lab" / "dashboard" / "public" / "data" / "routes"
ZTRICKS_A5_DIR = REPO / "experiments" / "a5_distance_standstill"
ZTRICKS_A5_REPORT = ZTRICKS_A5_DIR / "a5-distance-standstill.md"
ZTRICKS_ALIGNED_CMDS = ZTRICKS_A5_DIR / "getspeed-aligned.cmds"
ZTRICKS_HUMAN_REPLAY = ZTRICKS_A5_DIR / "human-replay.json"
ZTRICKS_ALIGNMENT_META = ZTRICKS_A5_DIR / "alignment-meta.json"
ZTRICKS_WINNING_ATTEMPT = 11
ZTRICKS_SPAWN_ORIGIN = [-1168.0, 1632.0, -496.0]
ZTRICKS_SPAWN_ANGLE_DEG = 315.0
ZTRICKS_SPAWN_LEFT_YAW_DEG = 45.0

GAP_FIELDS = ("edge", "land", "required_speed", "human_speed_at_edge",
              "hard", "type")

ZTRICKS_DISTANCE_CONTROL = {
    "mode": 23,
    "fixed_goal": 8,
    "spawn_origin": "-3434.375 3686.875 -488",
    "spawn_velocity": "259 -172 0",
    "replay_file": "",
    "cvars": {
        "k_fb_moveprobe_s23_launch_vh": 430,
        "k_fb_moveprobe_s23_launch_angle": 50,
        "k_fb_moveprobe_s21_swing": 8,
        "k_fb_moveprobe_s23_launch_target_x": -3044.1,
        "k_fb_moveprobe_s23_launch_target_y": 3760.5,
        "k_fb_moveprobe_s23_launch_target_z": -488,
        "k_fb_moveprobe_s23_lip_x": -3348,
        "k_fb_moveprobe_s23_release_vh": 470,
        "k_fb_moveprobe_s23_release_vh_min": 453,
        "k_fb_moveprobe_s23_carve_d": 95,
        "k_fb_moveprobe_s23_carve_angle": 52,
        "k_fb_moveprobe_s23_carve_side": 1,
        "k_fb_moveprobe_s23_release_lip": 35,
        "k_fb_moveprobe_s23_refcurve": 1,
        "k_fb_moveprobe_s23_refcurve_vh_min": 0,
        "k_fb_moveprobe_s23_refcurve_entry_x": -3439.375,
        "k_fb_moveprobe_s23_refcurve_entry_y": 3758.125,
        "k_fb_moveprobe_s23_refcurve_y": 3768.5,
        "k_fb_moveprobe_s23_refcurve_y_tol": 24,
        "k_fb_moveprobe_s23_yawlead_min": -12,
        "k_fb_moveprobe_s23_yawlead_max": -4,
        "k_fb_moveprobe_s23_targeterr_min": -2,
        "k_fb_moveprobe_s23_targeterr_max": 10,
    },
}


def point_at_yaw(origin: list[float], yaw_deg: float, distance: float) -> list[float]:
    """Quake yaw projection on the XY plane: 0 = +X, 90 = +Y."""
    yaw = math.radians(yaw_deg)
    return [
        origin[0] + math.cos(yaw) * distance,
        origin[1] + math.sin(yaw) * distance,
        origin[2],
    ]


def rounded_point(point: list[float]) -> list[float]:
    return [round(c, 1) for c in point]


def sha256_normalized(path: Path) -> str:
    """sha256 over LF-normalized text -- platform-independent (see header)."""
    text = path.read_text(encoding="utf-8")
    return hashlib.sha256(
        text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def parse_cmds_points(path: Path) -> list[list[float]]:
    """All [x, y, z] frames of a replay .cmds file (header/comments skipped)."""
    points = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cols = line.split()
        if len(cols) < 4:
            continue
        points.append([float(cols[1]), float(cols[2]), float(cols[3])])
    return points


def parse_cmd_rows(path: Path) -> list[dict]:
    """Replay .cmds rows with position, velocity, input, and timing fields."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cols = line.split()
        if len(cols) < 14:
            continue
        rows.append({
            "msec": int(float(cols[0])),
            "origin": [float(cols[1]), float(cols[2]), float(cols[3])],
            "velocity": [float(cols[4]), float(cols[5]), float(cols[6])],
            "forwardmove": int(float(cols[10])),
            "sidemove": int(float(cols[11])),
            "upmove": int(float(cols[12])),
            "buttons": int(float(cols[13])),
        })
    return rows


def parse_cmds_fps(path: Path) -> float:
    """Read `fps=<number>` from the replay header."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("#"):
            break
        for part in line.split():
            if part.startswith("fps="):
                return float(part.split("=", 1)[1])
    return 0.0


def downsample(points: list[list[float]], fps: float) -> list[list[float]]:
    """Every Nth frame at ~POLYLINE_TARGET_HZ, last frame always kept,
    coordinates rounded to 0.1 qu (display polyline, not a data trace)."""
    if not points:
        return []
    stride = max(1, round(fps / POLYLINE_TARGET_HZ)) if fps > 0 else 1
    sampled = points[::stride]
    if (len(points) - 1) % stride != 0:
        sampled.append(points[-1])
    return [[round(c, 1) for c in p] for p in sampled]


def horizontal_speed(row: dict) -> float:
    vx, vy = row["velocity"][0], row["velocity"][1]
    return math.hypot(vx, vy)


def is_distance_landing(row: dict) -> bool:
    """A5 locked far-platform detector, using player-origin coordinates."""
    x, y, z = row["origin"]
    return abs(z + 488.0) < 0.5 and x > -3100.0 and 3600.0 <= y <= 3824.0


def find_ztricks_landing_row(rows: list[dict], lip_row: int, end_row: int) -> int:
    for idx in range(lip_row, min(end_row, len(rows) - 1) + 1):
        if is_distance_landing(rows[idx]):
            return idx
    raise ValueError("ztricks winning attempt has no far-platform landing row")


def build_route(name: str, ent: dict, census_rel: str) -> dict:
    cmds_path = REPLAY_DIR / f"dm3_{name}.cmds"
    polyline = downsample(parse_cmds_points(cmds_path), ent.get("fps", 0.0))
    gaps = [{k: g.get(k) for k in GAP_FIELDS} for g in ent.get("gaps", ())]
    teleports = [{"from": t.get("from"), "to": t.get("to")}
                 for t in ent.get("teleports", ())]
    return {
        "name": name,
        "human": {
            "duration_s": ent.get("duration_s"),
            "active_mean_speed": ent.get("active_mean_speed"),
            "peak_speed": ent.get("peak_speed"),
        },
        "polyline": polyline,
        "gaps": gaps,
        "teleports": teleports,
        "source": {
            "census": census_rel,
            "cmds": cmds_path.relative_to(REPO).as_posix(),
            "cmds_sha256": sha256_normalized(cmds_path),
        },
    }


def build_ztricks_distance_route() -> dict:
    """Build the ztricks Distance route from the successful 11th getspeed.qwd attempt.

    The A5 evidence shows speed alone is not a sufficient scalar gate for this jump:
    the winning attempt is distinguished by release/heading geometry. Therefore the
    gap keeps `required_speed` null while carrying the human lip speed separately.
    """
    human_replay = json.loads(ZTRICKS_HUMAN_REPLAY.read_text(encoding="utf-8"))
    alignment = json.loads(ZTRICKS_ALIGNMENT_META.read_text(encoding="utf-8"))
    rows = parse_cmd_rows(ZTRICKS_ALIGNED_CMDS)
    fps = parse_cmds_fps(ZTRICKS_ALIGNED_CMDS)

    attempt = next(
        a for a in human_replay["attempt_table"]
        if a["attempt"] == ZTRICKS_WINNING_ATTEMPT
    )
    start_row, attempt_end_row = attempt["rows"]
    lip_row = attempt["lip_row"]
    landing_row = find_ztricks_landing_row(rows, lip_row, attempt_end_row)
    segment = rows[start_row:landing_row + 1]
    active_rows = [
        r for r in segment
        if r["forwardmove"] or r["sidemove"] or r["upmove"] or r["buttons"]
    ]
    speeds = [horizontal_speed(r) for r in segment]
    active_speeds = [horizontal_speed(r) for r in active_rows] or speeds
    points = [r["origin"] for r in segment]

    route_rel = ZTRICKS_A5_REPORT.relative_to(REPO).as_posix()
    cmds_rel = ZTRICKS_ALIGNED_CMDS.relative_to(REPO).as_posix()
    human_replay_rel = ZTRICKS_HUMAN_REPLAY.relative_to(REPO).as_posix()
    alignment_rel = ZTRICKS_ALIGNMENT_META.relative_to(REPO).as_posix()

    return {
        "name": "distance_standstill",
        "human": {
            "duration_s": round(sum(r["msec"] for r in segment) / 1000.0, 3),
            "active_mean_speed": round(sum(active_speeds) / len(active_speeds), 1),
            "peak_speed": round(max(speeds), 1),
        },
        "polyline": downsample(points, fps),
        "gaps": [
            {
                "edge": [round(c, 1) for c in rows[lip_row]["origin"]],
                "land": [round(c, 1) for c in rows[landing_row]["origin"]],
                "required_speed": None,
                "human_speed_at_edge": round(attempt["lip_vh"], 1),
                "hard": True,
                "type": "distance_standstill",
            }
        ],
        "teleports": [],
        "source": {
            "census": route_rel,
            "cmds": cmds_rel,
            "cmds_sha256": sha256_normalized(ZTRICKS_ALIGNED_CMDS),
            "human_replay": human_replay_rel,
            "human_replay_sha256": sha256_normalized(ZTRICKS_HUMAN_REPLAY),
            "alignment_meta": alignment_rel,
            "alignment_meta_sha256": sha256_normalized(ZTRICKS_ALIGNMENT_META),
        },
        "reference": {
            "demo": "getspeed.qwd",
            "demo_sha256": alignment["sha256"],
            "attempt": ZTRICKS_WINNING_ATTEMPT,
            "attempt_rows": attempt["rows"],
            "route_rows": [start_row, landing_row],
            "lip_row": lip_row,
            "landing_row": landing_row,
            "lip_speed": round(attempt["lip_vh"], 1),
            "landing_speed": round(horizontal_speed(rows[landing_row]), 1),
            "launch_heading_deg": round(attempt["launch_heading_deg"], 1),
            "jump_bit_at_lip": bool(attempt["jump_bit_at_lip"]),
            "landed_recorded": bool(attempt["landed_recorded"]),
            "landed_sim": bool(attempt["landed_sim"]),
            "required_speed_note": (
                "Speed alone is not sufficient; A5 identifies terminal "
                "release heading/geometry as the decisive gate."
            ),
        },
        "control": ZTRICKS_DISTANCE_CONTROL,
    }


def build_ztricks_spawn_left_speedjump_route() -> dict:
    """Build a flat-ground ztricks speedjump calibration route from the real spawn.

    This is intentionally not a ledge-completion route. It rotates the same
    terminal speedjump/reference-curve primitive onto the map's spawn-floor
    "turn 90 left" lane and measures whether the controller gains speed.
    """
    lip = point_at_yaw(ZTRICKS_SPAWN_ORIGIN, ZTRICKS_SPAWN_LEFT_YAW_DEG, 350.0)
    target = point_at_yaw(ZTRICKS_SPAWN_ORIGIN, ZTRICKS_SPAWN_LEFT_YAW_DEG, 526.0)
    polyline = [
        rounded_point(point_at_yaw(ZTRICKS_SPAWN_ORIGIN, ZTRICKS_SPAWN_LEFT_YAW_DEG, d))
        for d in (0.0, 128.0, 256.0, 384.0, 526.0)
    ]
    return {
        "name": "spawn_left_speedjump",
        "human": {
            "duration_s": None,
            "active_mean_speed": None,
            "peak_speed": None,
        },
        "polyline": polyline,
        "gaps": [],
        "teleports": [],
        "source": {
            "map_entities": (
                "lab/dashboard/public/data/map_entities/ztricks.json"
            ),
            "spawn_angle_source": (
                "ztricks.bsp entity lump: info_player_deathmatch angle 315"
            ),
        },
        "reference": {
            "type": "spawn_floor_speed_gain",
            "spawn_origin": rounded_point(ZTRICKS_SPAWN_ORIGIN),
            "spawn_angle_deg": ZTRICKS_SPAWN_ANGLE_DEG,
            "left_yaw_deg": ZTRICKS_SPAWN_LEFT_YAW_DEG,
            "synthetic_lip": rounded_point(lip),
            "target": rounded_point(target),
            "success_metric": "horizontal_speed_gain",
            "success_note": (
                "Same speedjump controller as ztricks Distance, but no ledge "
                "completion gate; evaluate start-to-peak horizontal speed gain."
            ),
        },
        "control": {
            "mode": 23,
            "fixed_goal": 0,
            "spawn_origin": "-1168 1632 -496",
            "spawn_velocity": "0 0 0",
            "replay_file": "",
            "cvars": {
                "k_fb_moveprobe_s23_launch_vh": 430,
                "k_fb_moveprobe_s23_launch_angle": 50,
                "k_fb_moveprobe_s21_swing": 8,
                "k_fb_moveprobe_s23_launch_target_x": round(target[0], 1),
                "k_fb_moveprobe_s23_launch_target_y": round(target[1], 1),
                "k_fb_moveprobe_s23_launch_target_z": round(target[2], 1),
                "k_fb_moveprobe_s23_lip_x": round(lip[0], 1),
                "k_fb_moveprobe_s23_release_vh": 470,
                "k_fb_moveprobe_s23_release_vh_min": 1,
                "k_fb_moveprobe_s23_carve_d": 95,
                "k_fb_moveprobe_s23_carve_angle": 52,
                "k_fb_moveprobe_s23_carve_side": 1,
                "k_fb_moveprobe_s23_release_lip": 35,
                "k_fb_moveprobe_s23_refcurve": 1,
                "k_fb_moveprobe_s23_refcurve_vh_min": 0,
                "k_fb_moveprobe_s23_refcurve_yaw_offset": ZTRICKS_SPAWN_LEFT_YAW_DEG,
                "k_fb_moveprobe_s23_yawlead_min": -12,
                "k_fb_moveprobe_s23_yawlead_max": -4,
                "k_fb_moveprobe_s23_targeterr_min": -2,
                "k_fb_moveprobe_s23_targeterr_max": 10,
            },
        },
    }


def build_manifests() -> dict[str, dict]:
    """All five output documents, keyed by file name."""
    census = json.loads(CENSUS_PATH.read_text(encoding="utf-8"))
    census_rel = CENSUS_PATH.relative_to(REPO).as_posix()
    provenance = {
        "census": census_rel,
        "census_sha256": sha256_normalized(CENSUS_PATH),
        "polyline_target_hz": POLYLINE_TARGET_HZ,
    }

    out: dict[str, dict] = {}
    index_maps = []
    for map_name in MAPS:
        routes = []
        if map_name == "dm3":
            routes = [build_route(name, census[name], census_rel)
                      for name in sorted(census)]
        elif map_name == "ztricks":
            routes = [
                build_ztricks_distance_route(),
                build_ztricks_spawn_left_speedjump_route(),
            ]
        out[f"{map_name}.json"] = {
            "schema": SCHEMA,
            "v": SCHEMA_V,
            "map": map_name,
            "routes": routes,
            "provenance": provenance,
        }
        index_maps.append({"map": map_name, "file": f"{map_name}.json",
                           "routes": len(routes)})
    out["index.json"] = {"schema": SCHEMA, "v": SCHEMA_V, "maps": index_maps}
    return out


def render(name: str, doc: dict) -> bytes:
    """Deterministic bytes for one output file (see determinism notes)."""
    if name == "index.json":
        text = json.dumps(doc, indent=2)
    else:
        text = json.dumps(doc, separators=(",", ":"))
    return (text + "\n").encode("utf-8")


def write_manifests(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, doc in build_manifests().items():
        path = out_dir / name
        path.write_bytes(render(name, doc))
        written.append(path)
    return written


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    out_dir = DEFAULT_OUT
    i = 0
    while i < len(args):
        if args[i] == "--out-dir" and i + 1 < len(args):
            out_dir = Path(args[i + 1]); i += 1
        else:
            print(__doc__)
            return 2
        i += 1

    written = write_manifests(out_dir)
    for path in written:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if path.name == "index.json":
            counts = ", ".join(f"{m['map']}={m['routes']}" for m in doc["maps"])
            print(f"{path.name}: {counts}")
        else:
            pts = sum(len(r["polyline"]) for r in doc["routes"])
            print(f"{path.name}: {len(doc['routes'])} routes, "
                  f"{pts} polyline points, {path.stat().st_size} bytes")
    print(f"\nwrote {len(written)} files -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
