#!/usr/bin/env python3
"""Quake1 BSP v29 -> untextured OBJ mesh exporter for the lab dashboard (LD-C2, #91).

Commits the export path that produced `lab/dashboard/public/dm3.obj` (2026-06-09,
via demopasha `phase0/bsp_parse.py`) so the dashboard map set {dm3, dm2,
frobodm2, trick} can be (re)built from the BSPs at any time. Lineage:
demopasha `phase0/bsp_parse.py` (face/edge/surfedge walk + fan triangulation)
and `scripts/bsp_geom.py` (stdlib-struct v29 lump parsing, no numpy/construct).

Conventions (kept identical to the existing dm3.obj so viewer code needs no
changes -- BotLab3D.tsx loads these with three.js OBJLoader + DoubleSide
material):

- raw Quake coordinates, no axis swap, no scaling (the viewer's quakeCoords.ts
  does the Y-up conversion);
- plain `v x y z` + 1-indexed triangle-only `f a b c` lines, no normals/uvs;
- fan triangulation per face.

Differences from the one-off dm3 export (deliberate, per #91):

- WORLDMODEL FACES ONLY (model 0) -- submodels (doors/plats/triggers) are
  dropped; these meshes are an orientation backdrop, not collision geometry.
- Only vertices referenced by those faces are emitted (remapped, original
  order), so no dead submodel vertices bloat the file.
- ASCII-only header comment (the old file had a mojibake em dash).

Determinism: same BSP bytes in -> byte-identical OBJ out. Floats are printed
as the shortest decimal that round-trips through float32 (matching numpy's
repr used for the original dm3.obj), output is written with explicit LF and
the committed assets are marked `-text` in `.gitattributes`. Provenance (the
source BSP sha256, counts, and the world AABB) is recorded per map in
`maps.json` next to the OBJs -- the AABB center is the Mockup view's
camera-overview start point (#97).

Usage (stdlib only, run from the repo root):

    python lab/tools/bsp_to_obj.py MAP=BSP_PATH [MAP=BSP_PATH ...] \
        [--out-dir lab/dashboard/public/maps]

    # the LD-C2 set, BSPs from the local nQuake install + the WSL mvd bundle:
    python lab/tools/bsp_to_obj.py \
        dm3=C:/nQuake/qw/maps/dm3.bsp \
        dm2=/path/to/dm2.bsp \
        frobodm2=C:/nQuake/qw/maps/frobodm2.bsp \
        trick=C:/nQuake/qw/maps/trick.bsp

BSP sources (none are committed -- ~1 MB game assets):
- locally: `C:\\nQuake\\qw\\maps\\{dm3,frobodm2,trick}.bsp` (no dm2.bsp there);
- WSL Ubuntu-24.04: `~/mvd-mcp-bundle/bsps/dm2.bsp` (also dm3.bsp);
- lab host (read-only): `servexeri:~/nquakesv/qw/maps/*.bsp`.

maps.json is merged per map key (existing entries for maps not on the command
line are preserved) and written sorted, so partial rebuilds stay deterministic.
"""

from __future__ import annotations

import logging
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path


LOGGER = logging.getLogger(__name__)
# Lump indices / record sizes (Quake1 BSP v29) -- from demopasha bsp_parse.py.
LUMP_VERTEXES = 3
LUMP_FACES = 7
LUMP_EDGES = 12
LUMP_SURFEDGES = 13
LUMP_MODELS = 14
LUMP_COUNT = 15

VERTEX_SIZE = 12     # 3f
FACE_SIZE = 20       # h planenum, h side, i firstedge, h numedges, h texinfo, 4b styles, i lightofs
EDGE_SIZE = 4        # 2H
SURFEDGE_SIZE = 4    # i
MODEL_SIZE = 64      # 9f, 7i

SCHEMA = "komodobots.maps.v1"
GENERATOR = "lab/tools/bsp_to_obj.py"
DEFAULT_OUT_DIR = Path("lab/dashboard/public/maps")


def fmt_f32(value: float) -> str:
    """Shortest decimal string that round-trips through float32.

    Matches numpy's float32 repr style used when the original dm3.obj was
    exported: integral values keep a trailing `.0` (e.g. `-984.0`), and
    e.g. float32(12.3) prints as `12.3`, not `12.300000190734863`.
    """
    packed = struct.pack("<f", value)
    for precision in range(1, 18):
        text = f"{value:.{precision}g}"
        if struct.pack("<f", float(text)) == packed:
            break
    if "e" in text:
        # %g picks exponent notation for e.g. 2080.0 ("2.08e+03"); rewrite in
        # fixed notation (same double, so the float32 round-trip is unchanged).
        text = f"{float(text):.10f}".rstrip("0").rstrip(".")
    if "." not in text:
        text += ".0"
    return text


def parse_bsp_geometry(data: bytes) -> dict:
    """Worldmodel triangle mesh from raw BSP v29 bytes.

    Returns {"vertices": [(x,y,z) f32-as-float, ...] referenced-only in
    original order, "triangles": [(i,j,k) 0-based into vertices, ...],
    "worldmodel_faces": int}.
    """
    version = struct.unpack_from("<i", data, 0)[0]
    if version != 29:
        raise ValueError(f"expected BSP v29, got {version}")
    lumps = [struct.unpack_from("<ii", data, 4 + i * 8) for i in range(LUMP_COUNT)]

    vo, vl = lumps[LUMP_VERTEXES]
    vertexes = [struct.unpack_from("<3f", data, vo + k * VERTEX_SIZE)
                for k in range(vl // VERTEX_SIZE)]

    fo, fl = lumps[LUMP_FACES]
    faces = [struct.unpack_from("<hhihh4si", data, fo + k * FACE_SIZE)
             for k in range(fl // FACE_SIZE)]

    eo, el = lumps[LUMP_EDGES]
    edges = [struct.unpack_from("<2H", data, eo + k * EDGE_SIZE)
             for k in range(el // EDGE_SIZE)]

    so, sl = lumps[LUMP_SURFEDGES]
    surfedges = [struct.unpack_from("<i", data, so + k * SURFEDGE_SIZE)[0]
                 for k in range(sl // SURFEDGE_SIZE)]

    # models[0] = the worldmodel; submodels (doors/plats) are skipped.
    mo, _ = lumps[LUMP_MODELS]
    model0 = struct.unpack_from("<9f7i", data, mo)
    firstface, numfaces = model0[14], model0[15]

    # Surfedge walk + fan triangulation (verbatim logic from demopasha).
    triangles_raw: list[tuple[int, int, int]] = []
    for face in faces[firstface:firstface + numfaces]:
        face_firstedge, face_numedges = face[2], face[3]
        verts = []
        for i in range(face_numedges):
            se = surfedges[face_firstedge + i]
            verts.append(edges[se][0] if se >= 0 else edges[-se][1])
        for j in range(1, len(verts) - 1):
            triangles_raw.append((verts[0], verts[j], verts[j + 1]))

    # Emit only referenced vertices, keeping original BSP order.
    referenced = sorted({v for tri in triangles_raw for v in tri})
    remap = {old: new for new, old in enumerate(referenced)}
    return {
        "vertices": [vertexes[old] for old in referenced],
        "triangles": [(remap[a], remap[b], remap[c]) for a, b, c in triangles_raw],
        "worldmodel_faces": numfaces,
    }


def mesh_aabb(vertices) -> dict:
    mins = [min(v[axis] for v in vertices) for axis in range(3)]
    maxs = [max(v[axis] for v in vertices) for axis in range(3)]
    center = [round(0.5 * (mins[a] + maxs[a]), 1) for a in range(3)]
    return {
        "mins": [float(fmt_f32(m)) for m in mins],
        "maxs": [float(fmt_f32(m)) for m in maxs],
        "center": center,
    }


def build_obj_text(map_name: str, mesh: dict) -> str:
    lines = [f"# BSP v29 exported geometry - {map_name} (worldmodel faces only)"]
    lines += [f"v {fmt_f32(x)} {fmt_f32(y)} {fmt_f32(z)}" for x, y, z in mesh["vertices"]]
    lines += [f"f {a + 1} {b + 1} {c + 1}" for a, b, c in mesh["triangles"]]
    return "\n".join(lines) + "\n"


def export_map(map_name: str, bsp_path: Path, out_dir: Path) -> dict:
    """Writes <map>.obj into out_dir; returns the maps.json entry."""
    data = bsp_path.read_bytes()
    mesh = parse_bsp_geometry(data)
    obj_text = build_obj_text(map_name, mesh)
    out_path = out_dir / f"{map_name}.obj"
    out_path.write_text(obj_text, encoding="ascii", newline="\n")
    entry = {
        "obj": f"{map_name}.obj",
        "source_bsp": bsp_path.name,
        "source_bsp_sha256": hashlib.sha256(data).hexdigest(),
        "vertices": len(mesh["vertices"]),
        "triangles": len(mesh["triangles"]),
        "worldmodel_faces": mesh["worldmodel_faces"],
        "aabb": mesh_aabb(mesh["vertices"]),
    }
    print(f"{map_name}: {entry['vertices']} vertices, {entry['triangles']} triangles "
          f"({entry['worldmodel_faces']} worldmodel faces) -> {out_path} "
          f"({out_path.stat().st_size:,} bytes); aabb center {entry['aabb']['center']}")
    return entry


def write_maps_json(out_dir: Path, new_entries: dict) -> Path:
    """Merge new entries into maps.json (existing other-map entries survive)."""
    manifest_path = out_dir / "maps.json"
    maps: dict = {}
    if manifest_path.is_file():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("schema") == SCHEMA and isinstance(previous.get("maps"), dict):
            maps = previous["maps"]
    maps.update(new_entries)
    manifest = {
        "schema": SCHEMA,
        "generator": GENERATOR,
        "maps": {name: maps[name] for name in sorted(maps)},
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n",
        encoding="ascii", newline="\n",
    )
    print(f"maps.json: {sorted(maps)} -> {manifest_path}")
    return manifest_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Export Quake1 BSP v29 worldmodel meshes to OBJ + maps.json "
                    "for the lab dashboard (LD-C2, #91).")
    parser.add_argument("maps", nargs="+", metavar="MAP=BSP_PATH",
                        help="map name and its source .bsp, e.g. dm3=C:/nQuake/qw/maps/dm3.bsp")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                        help=f"output directory (default: {DEFAULT_OUT_DIR})")
    args = parser.parse_args(argv)

    jobs = []
    for spec in args.maps:
        name, sep, path = spec.partition("=")
        if not sep or not name or not path:
            parser.error(f"expected MAP=BSP_PATH, got {spec!r}")
        bsp_path = Path(path)
        if not bsp_path.is_file():
            parser.error(f"BSP not found: {bsp_path}")
        jobs.append((name, bsp_path))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    entries = {name: export_map(name, bsp_path, args.out_dir) for name, bsp_path in jobs}
    write_maps_json(args.out_dir, entries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
