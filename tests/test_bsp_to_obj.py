"""bsp_to_obj: lab map mesh export (LD-C2, #91).

Two layers, mirroring the #134 committed-outputs lock pattern under the
constraint that the source BSPs are NOT committed (~1 MB game assets each):

1. A synthetic in-memory BSP v29 fixture runs the real exporter end to end
   and locks the exact OBJ bytes + maps.json entry + determinism (two runs,
   byte-identical) -- the fresh-build lock CI can actually execute.
2. The committed real assets (lab/dashboard/public/maps/) are checked for
   internal consistency against maps.json: counts, triangle-only faces with
   in-range 1-based indices, AABB mins/maxs/center recomputed from the OBJ
   vertices, LF-only endings, provenance fields well-formed.
"""

import hashlib
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lab" / "tools"))

import bsp_to_obj  # noqa: E402

MAPS_DIR = REPO / "lab" / "dashboard" / "public" / "maps"
EXPECTED_MAPS = ("dm2", "dm3", "frobodm2", "trick")


# ---------------------------------------------------------------------------
# Synthetic BSP v29 fixture: one quad worldmodel face + one submodel face
# that must NOT appear in the export (worldmodel-only rule).
# ---------------------------------------------------------------------------


def build_synthetic_bsp() -> bytes:
    # 6 vertices: 0-3 form the worldmodel quad, 4-5 belong to the submodel
    # face (which reuses vertex 0 so a naive all-faces walk would differ).
    vertexes = [
        (0.0, 0.0, 0.0),
        (64.0, 0.0, 0.0),
        (64.0, 2080.0, 0.0),   # 2080 exercises the no-exponent float path
        (0.0, 64.0, 12.3),     # 12.3 exercises the float32 round-trip path
        (-32.0, -32.0, 96.0),
        (-32.0, 32.0, 96.0),
    ]
    # edges[0] is unused padding by Quake convention (edge 0 cannot be negated)
    edges = [(0, 0), (0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (4, 5), (5, 0)]
    # face 0 (worldmodel quad): surfedges 0..3 -> edges 1,2,3,4 forward
    # face 1 (submodel tri): surfedges 4..6 -> edges 5,6,7 forward
    surfedges = [1, 2, 3, 4, 5, 6, 7]
    faces = [
        # planenum, side, firstedge, numedges, texinfo, styles, lightofs
        (0, 0, 0, 4, 0, b"\x00" * 4, -1),
        (0, 0, 4, 3, 0, b"\x00" * 4, -1),
    ]
    models = [
        # worldmodel: firstface=0 numfaces=1
        ((0.0,) * 9, (0, 0, 0, 0), 0, 0, 1),
        # submodel: firstface=1 numfaces=1
        ((0.0,) * 9, (0, 0, 0, 0), 0, 1, 1),
    ]

    lump_payloads = {i: b"" for i in range(bsp_to_obj.LUMP_COUNT)}
    lump_payloads[bsp_to_obj.LUMP_VERTEXES] = b"".join(
        struct.pack("<3f", *v) for v in vertexes)
    lump_payloads[bsp_to_obj.LUMP_EDGES] = b"".join(
        struct.pack("<2H", *e) for e in edges)
    lump_payloads[bsp_to_obj.LUMP_SURFEDGES] = b"".join(
        struct.pack("<i", se) for se in surfedges)
    lump_payloads[bsp_to_obj.LUMP_FACES] = b"".join(
        struct.pack("<hhihh4si", *f) for f in faces)
    lump_payloads[bsp_to_obj.LUMP_MODELS] = b"".join(
        struct.pack("<9f7i", *m[0], *m[1], m[2], m[3], m[4]) for m in models)

    header_size = 4 + bsp_to_obj.LUMP_COUNT * 8
    body = b""
    offsets = []
    for i in range(bsp_to_obj.LUMP_COUNT):
        offsets.append((header_size + len(body), len(lump_payloads[i])))
        body += lump_payloads[i]
    header = struct.pack("<i", 29) + b"".join(
        struct.pack("<ii", off, length) for off, length in offsets)
    return header + body


EXPECTED_SYNTH_OBJ = (
    "# BSP v29 exported geometry - synth (worldmodel faces only)\n"
    "v 0.0 0.0 0.0\n"
    "v 64.0 0.0 0.0\n"
    "v 64.0 2080.0 0.0\n"
    "v 0.0 64.0 12.3\n"
    "f 1 2 3\n"
    "f 1 3 4\n"
)


class TestFloatFormatting(unittest.TestCase):
    def test_round_trip_and_style(self):
        cases = {
            -984.0: "-984.0",
            0.0: "0.0",
            2080.0: "2080.0",      # must not become 2.08e+03
            12.3: "12.3",          # must not become 12.300000190734863
            -0.5: "-0.5",
        }
        for value, expected in cases.items():
            f32 = struct.unpack("<f", struct.pack("<f", value))[0]
            text = bsp_to_obj.fmt_f32(f32)
            self.assertEqual(text, expected)
            self.assertEqual(
                struct.pack("<f", float(text)), struct.pack("<f", f32),
                f"{text} does not round-trip float32",
            )


class TestSyntheticExport(unittest.TestCase):
    def test_worldmodel_only_geometry(self):
        mesh = bsp_to_obj.parse_bsp_geometry(build_synthetic_bsp())
        self.assertEqual(mesh["worldmodel_faces"], 1)
        # 4 referenced vertices (submodel verts 4,5 dropped), quad -> 2 tris
        self.assertEqual(len(mesh["vertices"]), 4)
        self.assertEqual(mesh["triangles"], [(0, 1, 2), (0, 2, 3)])

    def test_rejects_wrong_version(self):
        bad = struct.pack("<i", 30) + build_synthetic_bsp()[4:]
        with self.assertRaises(ValueError):
            bsp_to_obj.parse_bsp_geometry(bad)

    def test_full_export_locked_and_deterministic(self):
        data = build_synthetic_bsp()
        with tempfile.TemporaryDirectory() as tmp:
            bsp_path = Path(tmp) / "synth.bsp"
            bsp_path.write_bytes(data)
            out_dir = Path(tmp) / "out"
            rc = bsp_to_obj.main([f"synth={bsp_path}", "--out-dir", str(out_dir)])
            self.assertEqual(rc, 0)
            obj_bytes = (out_dir / "synth.obj").read_bytes()
            self.assertEqual(obj_bytes.decode("ascii"), EXPECTED_SYNTH_OBJ)
            self.assertNotIn(b"\r", obj_bytes)  # explicit LF on every platform
            manifest1 = (out_dir / "maps.json").read_bytes()

            # determinism: a second run is byte-identical
            rc = bsp_to_obj.main([f"synth={bsp_path}", "--out-dir", str(out_dir)])
            self.assertEqual(rc, 0)
            self.assertEqual((out_dir / "synth.obj").read_bytes(), obj_bytes)
            self.assertEqual((out_dir / "maps.json").read_bytes(), manifest1)

            entry = json.loads(manifest1)["maps"]["synth"]
            self.assertEqual(entry["source_bsp_sha256"],
                             hashlib.sha256(data).hexdigest())
            self.assertEqual(entry["vertices"], 4)
            self.assertEqual(entry["triangles"], 2)
            self.assertEqual(entry["worldmodel_faces"], 1)
            self.assertEqual(entry["aabb"]["mins"], [0.0, 0.0, 0.0])
            self.assertEqual(entry["aabb"]["maxs"][:2], [64.0, 2080.0])
            self.assertEqual(entry["aabb"]["center"][:2], [32.0, 1040.0])

    def test_maps_json_merge_preserves_other_maps(self):
        data = build_synthetic_bsp()
        with tempfile.TemporaryDirectory() as tmp:
            bsp_path = Path(tmp) / "synth.bsp"
            bsp_path.write_bytes(data)
            out_dir = Path(tmp) / "out"
            bsp_to_obj.main([f"alpha={bsp_path}", "--out-dir", str(out_dir)])
            bsp_to_obj.main([f"beta={bsp_path}", "--out-dir", str(out_dir)])
            manifest = json.loads((out_dir / "maps.json").read_text())
            self.assertEqual(sorted(manifest["maps"]), ["alpha", "beta"])
            self.assertEqual(manifest["schema"], bsp_to_obj.SCHEMA)


# ---------------------------------------------------------------------------
# Committed-asset consistency lock
# ---------------------------------------------------------------------------


def parse_obj(text: str):
    vertices, triangles = [], []
    for line in text.splitlines():
        if line.startswith("v "):
            vertices.append(tuple(float(p) for p in line.split()[1:]))
        elif line.startswith("f "):
            triangles.append(tuple(int(p) for p in line.split()[1:]))
    return vertices, triangles


class TestCommittedAssets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(
            (MAPS_DIR / "maps.json").read_text(encoding="utf-8"))

    def test_manifest_schema_and_map_set(self):
        self.assertEqual(self.manifest["schema"], "komodobots.maps.v1")
        self.assertEqual(tuple(sorted(self.manifest["maps"])), EXPECTED_MAPS)

    def test_objs_match_manifest(self):
        for name, entry in self.manifest["maps"].items():
            with self.subTest(map=name):
                obj_path = MAPS_DIR / entry["obj"]
                raw = obj_path.read_bytes()
                self.assertNotIn(b"\r", raw, f"{obj_path} must be LF-only")
                vertices, triangles = parse_obj(raw.decode("ascii"))
                self.assertEqual(len(vertices), entry["vertices"])
                self.assertEqual(len(triangles), entry["triangles"])
                # triangle-only faces, 1-based indices in range
                for tri in triangles:
                    self.assertEqual(len(tri), 3)
                    for idx in tri:
                        self.assertTrue(1 <= idx <= len(vertices))
                # provenance: 64-hex sha256 of a non-committed source BSP
                self.assertRegex(entry["source_bsp_sha256"], r"^[0-9a-f]{64}$")
                self.assertTrue(entry["source_bsp"].endswith(".bsp"))

    def test_aabb_centers_match_computed_bounds(self):
        for name, entry in self.manifest["maps"].items():
            with self.subTest(map=name):
                obj_path = MAPS_DIR / entry["obj"]
                vertices, _ = parse_obj(obj_path.read_text(encoding="ascii"))
                mins = [min(v[a] for v in vertices) for a in range(3)]
                maxs = [max(v[a] for v in vertices) for a in range(3)]
                self.assertEqual(entry["aabb"]["mins"], mins)
                self.assertEqual(entry["aabb"]["maxs"], maxs)
                self.assertEqual(
                    entry["aabb"]["center"],
                    [round(0.5 * (mins[a] + maxs[a]), 1) for a in range(3)],
                )

    def test_dm3_close_to_legacy_export(self):
        """maps/dm3.obj is the scripted regeneration of the deployed one-off
        public/dm3.obj (all-models export). Worldmodel-only must agree within
        the submodel budget: never more geometry, and within a small delta."""
        legacy = REPO / "lab" / "dashboard" / "public" / "dm3.obj"
        lv, lt = parse_obj(legacy.read_text(encoding="utf-8", errors="replace"))
        nv, nt = parse_obj((MAPS_DIR / "dm3.obj").read_text(encoding="ascii"))
        self.assertLessEqual(len(nv), len(lv))
        self.assertLessEqual(len(nt), len(lt))
        self.assertLess(len(lv) - len(nv), 200)   # dm3 submodels: 88 verts
        self.assertLess(len(lt) - len(nt), 300)   # dm3 submodels: 128 tris


if __name__ == "__main__":
    unittest.main()
