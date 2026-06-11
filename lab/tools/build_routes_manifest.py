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
Per-map file `<map>.json` (maps: dm3, dm2, frobodm2, trick -- non-dm3 maps
carry empty route lists until routes are censused there):

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
import sys
from pathlib import Path

SCHEMA = "komodobots.routes.v1"
SCHEMA_V = 1
MAPS = ("dm3", "dm2", "frobodm2", "trick")   # dashboard map set (records_build)
POLYLINE_TARGET_HZ = 12.5    # ~5-10 Hz is plenty for display; 12.5 keeps the
                             # shortest routes comfortably dense (sng_to_rl
                             # spot check: >100 points) while staying small

REPO = Path(__file__).resolve().parent.parent.parent
CENSUS_PATH = (REPO / "experiments" / "nav_doctrine" / "evidence"
               / "trick-census" / "census.json")
REPLAY_DIR = REPO / "experiments" / "nav_doctrine" / "evidence" / "replay"
DEFAULT_OUT = REPO / "lab" / "dashboard" / "public" / "data" / "routes"

GAP_FIELDS = ("edge", "land", "required_speed", "human_speed_at_edge",
              "hard", "type")


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
