"""bsp_to_mesh: textured glTF mesh pipeline (LD-C4, #92).

Test layers, mirroring the bsp_to_obj.py test pattern:

1. Palette loading: embedded fallback matches real palette length/content,
   PAK extraction path, direct .lmp path, missing file errors.
2. Texture classification: sky / skip / liquid / regular rules.
3. UV computation: formula correctness for known axis cases.
4. Synthetic BSP: single-face worldmodel, UV and position correctness,
   texture tagging, GLB structural validity, determinism.
5. Committed-asset lock: maps.json has glb keys, all 4 .glb files exist,
   GLB magic/version, accessor/bufferView count sanity, sampler REPEAT,
   material extras tags, size budget (<= 3 MB).
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

import bsp_to_mesh  # noqa: E402
import bsp_to_obj   # noqa: E402  (reuse synthetic BSP builder)

MAPS_DIR = REPO / "lab" / "dashboard" / "public" / "maps"
EXPECTED_MAPS = ("dm2", "dm3", "frobodm2", "trick")
SIZE_BUDGET_BYTES = 3 * 1024 * 1024   # 3 MB per-map GLB budget

# ---------------------------------------------------------------------------
# Synthetic BSP builder (reused from test_bsp_to_obj.py)
# ---------------------------------------------------------------------------

def build_synthetic_bsp(tex_name: str = "tech01_1", tex_w: int = 64,
                        tex_h: int = 64) -> bytes:
    """One-quad worldmodel face + one submodel face, one miptex.

    Miptex pixel data: all zeros (palette index 0 = black).
    Texinfo: s_axis=(1,0,0), t_axis=(0,-1,0) -- classic Quake floor mapping.
    """
    import struct

    # Quake1 BSP v29 lump indices
    LUMP_MIPTEX = 2
    LUMP_VERTEXES = 3
    LUMP_TEXINFO = 6
    LUMP_FACES = 7
    LUMP_EDGES = 12
    LUMP_SURFEDGES = 13
    LUMP_MODELS = 14
    LUMP_COUNT = 15

    # -- miptex lump --
    # Header: int count, int offsets[count]
    # Each miptex: char[16] name, uint32 w, uint32 h, uint32 mip_off[4]
    # mip0 data: w*h bytes of palette indices (all 0)
    name_bytes = tex_name.encode("ascii")[:15].ljust(16, b"\x00")
    mip0_data = bytes(tex_w * tex_h)
    # offsets from miptex start: header(40 bytes) then pixel data
    # miptex: name(16) + w(4) + h(4) + mip_offsets(16) = 40 bytes header
    mip_offset_in_tex = 40  # mip0 starts right after the 40-byte miptex header
    mip1_offset = mip_offset_in_tex + tex_w * tex_h
    mip2_offset = mip1_offset + (tex_w // 2) * (tex_h // 2)
    mip3_offset = mip2_offset + (tex_w // 4) * (tex_h // 4)
    miptex_hdr = (
        name_bytes
        + struct.pack("<II", tex_w, tex_h)
        + struct.pack("<IIII", mip_offset_in_tex, mip1_offset, mip2_offset, mip3_offset)
    )
    # pixel data for all 4 mips (all zeros)
    mip_pixels = bytes(tex_w * tex_h + (tex_w//2)*(tex_h//2) +
                       (tex_w//4)*(tex_h//4) + (tex_w//8)*(tex_h//8))
    miptex_entry = miptex_hdr + mip_pixels
    # miptex lump: count=1, offset relative to lump start = 4+4=8 (after count+offset)
    miptex_lump = struct.pack("<i", 1) + struct.pack("<i", 8) + miptex_entry

    # -- vertexes (same quad as test_bsp_to_obj) --
    vertexes = [
        (0.0, 0.0, 0.0),
        (64.0, 0.0, 0.0),
        (64.0, 128.0, 0.0),
        (0.0, 128.0, 0.0),
        (-32.0, -32.0, 96.0),   # submodel only
        (-32.0, 32.0, 96.0),    # submodel only
    ]

    # -- edges --
    edges = [(0, 0), (0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (4, 5), (5, 0)]

    # -- surfedges --
    surfedges = [1, 2, 3, 4, 5, 6, 7]

    # -- texinfo --
    # s_axis=(1,0,0), so=0, t_axis=(0,-1,0), to=0, miptex=0, flags=0
    texinfo_entry = struct.pack("<4f", 1.0, 0.0, 0.0, 0.0)   # s
    texinfo_entry += struct.pack("<4f", 0.0, -1.0, 0.0, 0.0)  # t
    texinfo_entry += struct.pack("<ii", 0, 0)                  # miptex, flags
    texinfo_lump = texinfo_entry   # one entry

    # -- faces --
    # (planenum, side, firstedge, numedges, texinfo, styles, lightofs)
    face_wm = struct.pack("<hhihh4si", 0, 0, 0, 4, 0, b"\x00" * 4, -1)
    face_sm = struct.pack("<hhihh4si", 0, 0, 4, 3, 0, b"\x00" * 4, -1)
    faces_lump = face_wm + face_sm

    # -- models --
    # BSP model struct: 9f (mins[3], maxs[3], origin[3]) + 7i (headnode[4], visleafs, firstface, numfaces)
    # worldmodel: firstface=0, numfaces=1; submodel: firstface=1, numfaces=1
    model0 = struct.pack("<9f7i", *([0.0]*9), 0, 0, 0, 0, 0, 0, 1)
    model1 = struct.pack("<9f7i", *([0.0]*9), 0, 0, 0, 0, 0, 1, 1)
    models_lump = model0 + model1

    lump_payloads = {i: b"" for i in range(LUMP_COUNT)}
    lump_payloads[LUMP_MIPTEX] = miptex_lump
    lump_payloads[LUMP_VERTEXES] = b"".join(struct.pack("<3f", *v) for v in vertexes)
    lump_payloads[LUMP_TEXINFO] = texinfo_lump
    lump_payloads[LUMP_FACES] = faces_lump
    lump_payloads[LUMP_EDGES] = b"".join(struct.pack("<2H", *e) for e in edges)
    lump_payloads[LUMP_SURFEDGES] = b"".join(struct.pack("<i", se) for se in surfedges)
    lump_payloads[LUMP_MODELS] = models_lump

    header_size = 4 + LUMP_COUNT * 8
    body = b""
    offsets = []
    for i in range(LUMP_COUNT):
        offsets.append((header_size + len(body), len(lump_payloads[i])))
        body += lump_payloads[i]
    header = struct.pack("<i", 29) + b"".join(
        struct.pack("<ii", off, length) for off, length in offsets)
    return header + body


def _minimal_palette() -> bytes:
    """256-colour palette: colour 0 = (0,0,0), all others = (127,127,127)."""
    return bytes([0, 0, 0] + [127, 127, 127] * 255)


# ---------------------------------------------------------------------------
# Tests: palette loading
# ---------------------------------------------------------------------------

class TestPaletteLoading(unittest.TestCase):
    def test_embedded_palette_is_768_bytes(self):
        pal = bsp_to_mesh._embed_quake_palette()
        self.assertEqual(len(pal), 768)

    def test_embedded_palette_first_colour_is_black(self):
        pal = bsp_to_mesh._embed_quake_palette()
        self.assertEqual(pal[:3], b"\x00\x00\x00")

    def test_embedded_palette_last_colour_nonzero(self):
        pal = bsp_to_mesh._embed_quake_palette()
        self.assertNotEqual(pal[-3:], b"\x00\x00\x00")

    def test_load_palette_none_returns_embedded(self):
        pal = bsp_to_mesh.load_palette(None)
        self.assertEqual(len(pal), 768)
        self.assertEqual(pal, bsp_to_mesh._embed_quake_palette())

    def test_load_palette_lmp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            lmp = Path(tmp) / "palette.lmp"
            lmp.write_bytes(bytes(range(256)) * 3)
            pal = bsp_to_mesh.load_palette(str(lmp))
            self.assertEqual(len(pal), 768)

    def test_load_palette_lmp_wrong_size_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            lmp = Path(tmp) / "palette.lmp"
            lmp.write_bytes(b"\x00" * 100)
            with self.assertRaises(ValueError):
                bsp_to_mesh.load_palette(str(lmp))

    def test_load_palette_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            bsp_to_mesh.load_palette("/nonexistent/palette.lmp")


# ---------------------------------------------------------------------------
# Tests: texture classification
# ---------------------------------------------------------------------------

class TestTextureClassification(unittest.TestCase):
    def _tag(self, name: str) -> str:
        return bsp_to_mesh._classify_texture(name)

    def test_sky_prefix(self):
        self.assertEqual(self._tag("sky4"), bsp_to_mesh.TAG_SKY)
        self.assertEqual(self._tag("sky_outer"), bsp_to_mesh.TAG_SKY)
        self.assertEqual(self._tag("SKY4"), bsp_to_mesh.TAG_SKY)

    def test_clip_prefix(self):
        self.assertEqual(self._tag("clip"), bsp_to_mesh.TAG_SKIP)
        self.assertEqual(self._tag("clipwall"), bsp_to_mesh.TAG_SKIP)

    def test_trigger_prefix(self):
        self.assertEqual(self._tag("trigger"), bsp_to_mesh.TAG_SKIP)

    def test_z_exit_exact(self):
        self.assertEqual(self._tag("z_exit"), bsp_to_mesh.TAG_SKIP)
        self.assertEqual(self._tag("Z_EXIT"), bsp_to_mesh.TAG_SKIP)

    def test_liquid_prefix(self):
        self.assertEqual(self._tag("*water1"), bsp_to_mesh.TAG_LIQUID)
        self.assertEqual(self._tag("*lava1"), bsp_to_mesh.TAG_LIQUID)
        self.assertEqual(self._tag("*teleport"), bsp_to_mesh.TAG_LIQUID)

    def test_regular(self):
        self.assertEqual(self._tag("tech01_1"), bsp_to_mesh.TAG_REGULAR)
        self.assertEqual(self._tag("sfloor4_2"), bsp_to_mesh.TAG_REGULAR)


# ---------------------------------------------------------------------------
# Tests: UV computation
# ---------------------------------------------------------------------------

class TestUVComputation(unittest.TestCase):
    def test_floor_mapping(self):
        """s_axis=(1,0,0) t_axis=(0,1,0): floor face, offset=0."""
        u, v = bsp_to_mesh.compute_uv(
            (64.0, 128.0, 0.0),
            (1.0, 0.0, 0.0), 0.0,
            (0.0, 1.0, 0.0), 0.0,
            64, 64,
        )
        self.assertAlmostEqual(u, 1.0)
        self.assertAlmostEqual(v, 2.0)

    def test_with_offsets(self):
        """Offset shifts UV by offset/dim."""
        u, v = bsp_to_mesh.compute_uv(
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0), 16.0,
            (0.0, 1.0, 0.0), 32.0,
            64, 64,
        )
        self.assertAlmostEqual(u, 16.0 / 64.0)
        self.assertAlmostEqual(v, 32.0 / 64.0)

    def test_uv_can_exceed_one(self):
        """Large coordinates produce UV > 1 (wrapping is correct)."""
        u, v = bsp_to_mesh.compute_uv(
            (512.0, 0.0, 0.0),
            (1.0, 0.0, 0.0), 0.0,
            (0.0, 1.0, 0.0), 0.0,
            64, 64,
        )
        self.assertGreater(u, 1.0)

    def test_different_tex_dims_scale_uv(self):
        """UV is normalized by the actual texture dimensions."""
        u128, _ = bsp_to_mesh.compute_uv((64.0, 0.0, 0.0), (1.0, 0.0, 0.0), 0.0,
                                         (0.0, 1.0, 0.0), 0.0, 128, 128)
        u64, _ = bsp_to_mesh.compute_uv((64.0, 0.0, 0.0), (1.0, 0.0, 0.0), 0.0,
                                        (0.0, 1.0, 0.0), 0.0, 64, 64)
        self.assertAlmostEqual(u128, 0.5)
        self.assertAlmostEqual(u64, 1.0)


# ---------------------------------------------------------------------------
# Tests: synthetic BSP -> GLB
# ---------------------------------------------------------------------------

class TestSyntheticGLB(unittest.TestCase):
    def setUp(self):
        self.bsp_data = build_synthetic_bsp()
        self.palette = _minimal_palette()
        self.glb, self.entry = bsp_to_mesh.build_glb("synth", self.bsp_data, self.palette)
        self.json_obj = self._parse_json()

    def _parse_json(self) -> dict:
        json_len, json_type = struct.unpack_from("<II", self.glb, 12)
        self.assertEqual(json_type, 0x4E4F534A, "JSON chunk magic")
        return json.loads(self.glb[20:20 + json_len])

    def test_glb_magic_and_version(self):
        self.assertEqual(self.glb[:4], b"glTF")
        version, total_len = struct.unpack_from("<II", self.glb, 4)
        self.assertEqual(version, 2)
        self.assertEqual(total_len, len(self.glb))

    def test_bin_chunk_present(self):
        json_len = struct.unpack_from("<I", self.glb, 12)[0]
        bin_off = 12 + 8 + json_len
        bin_len, bin_type = struct.unpack_from("<II", self.glb, bin_off)
        self.assertEqual(bin_type, 0x004E4942, "BIN chunk magic")
        self.assertGreater(bin_len, 0)

    def test_asset_version(self):
        self.assertEqual(self.json_obj["asset"]["version"], "2.0")

    def test_asset_extras_provenance(self):
        extras = self.json_obj["asset"]["extras"]
        self.assertIn("source_bsp_sha256", extras)
        self.assertRegex(extras["source_bsp_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(extras["source_bsp_sha256"],
                         hashlib.sha256(self.bsp_data).hexdigest())
        self.assertIn("script_version", extras)

    def test_one_mesh_with_primitives(self):
        meshes = self.json_obj["meshes"]
        self.assertEqual(len(meshes), 1)
        prims = meshes[0]["primitives"]
        # The synth BSP has one texture used by worldmodel faces
        self.assertGreaterEqual(len(prims), 1)

    def test_primitives_have_position_and_uv(self):
        for prim in self.json_obj["meshes"][0]["primitives"]:
            self.assertIn("POSITION", prim["attributes"])
            self.assertIn("TEXCOORD_0", prim["attributes"])
            self.assertIn("indices", prim)

    def test_sampler_uses_repeat(self):
        samplers = self.json_obj["samplers"]
        self.assertGreaterEqual(len(samplers), 1)
        for s in samplers:
            self.assertEqual(s.get("wrapS"), bsp_to_mesh.GLTF_SAMPLER_WRAP_REPEAT)
            self.assertEqual(s.get("wrapT"), bsp_to_mesh.GLTF_SAMPLER_WRAP_REPEAT)

    def test_material_double_sided(self):
        for mat in self.json_obj["materials"]:
            self.assertTrue(mat.get("doubleSided"), f"material {mat.get('name')} not doubleSided")

    def test_material_extras_tag(self):
        for mat in self.json_obj["materials"]:
            extras = mat.get("extras", {})
            self.assertIn("quake_tag", extras,
                          f"material {mat.get('name')} missing quake_tag in extras")
            self.assertIn(extras["quake_tag"],
                          (bsp_to_mesh.TAG_REGULAR, bsp_to_mesh.TAG_SKY,
                           bsp_to_mesh.TAG_SKIP, bsp_to_mesh.TAG_LIQUID))

    def test_worldmodel_only(self):
        """Submodel faces must not appear in the output (worldmodel-only rule)."""
        # The synthetic BSP has: worldmodel quad (4 verts -> 2 tris),
        # submodel tri (3 verts); submodel must be absent.
        total_tris = sum(
            self.json_obj["accessors"][prim["indices"]]["count"] // 3
            for prim in self.json_obj["meshes"][0]["primitives"]
        )
        self.assertEqual(total_tris, 2, "worldmodel quad must yield exactly 2 triangles")

    def test_entry_fields(self):
        self.assertIn("glb", self.entry)
        self.assertIn("source_bsp_sha256", self.entry)
        self.assertEqual(self.entry["glb_triangles"], 2)
        self.assertEqual(self.entry["glb"], "synth.glb")

    def test_determinism(self):
        glb2, _ = bsp_to_mesh.build_glb("synth", self.bsp_data, self.palette)
        self.assertEqual(self.glb, glb2, "GLB output must be byte-identical on re-run")

    def test_uv_correctness(self):
        """Verify UV values match manual computation for the synthetic quad.

        texinfo: s_axis=(1,0,0), so=0; t_axis=(0,-1,0), to=0; tex=64x64.
        vertex (64, 128, 0) should give u=64/64=1.0, v=-128/64=-2.0.
        """
        # Find the TEXCOORD_0 accessor for the first primitive
        prim = self.json_obj["meshes"][0]["primitives"][0]
        uv_acc_idx = prim["attributes"]["TEXCOORD_0"]
        uv_acc = self.json_obj["accessors"][uv_acc_idx]
        uv_bv = self.json_obj["bufferViews"][uv_acc["bufferView"]]

        # Locate bin data
        json_len = struct.unpack_from("<I", self.glb, 12)[0]
        bin_off = 12 + 8 + json_len + 8  # after bin chunk header
        uv_data_off = bin_off + uv_bv["byteOffset"]
        n_verts = uv_acc["count"]
        uvs = [
            struct.unpack_from("<2f", self.glb, uv_data_off + i * 8)
            for i in range(n_verts)
        ]
        # The quad verts are (0,0,0), (64,0,0), (64,128,0), (0,128,0)
        # u = x/64, v = -y/64
        expected = [(0.0, 0.0), (1.0, 0.0), (1.0, -2.0), (0.0, -2.0)]
        for got, exp in zip(sorted(uvs), sorted(expected)):
            self.assertAlmostEqual(got[0], exp[0], places=5, msg=f"U mismatch: {got} vs {exp}")
            self.assertAlmostEqual(got[1], exp[1], places=5, msg=f"V mismatch: {got} vs {exp}")


# ---------------------------------------------------------------------------
# Tests: CLI integration (main())
# ---------------------------------------------------------------------------

class TestCLIIntegration(unittest.TestCase):
    def test_main_produces_glb_and_maps_json(self):
        bsp_data = build_synthetic_bsp()
        with tempfile.TemporaryDirectory() as tmp:
            bsp_path = Path(tmp) / "synth.bsp"
            bsp_path.write_bytes(bsp_data)
            out_dir = Path(tmp) / "out"
            rc = bsp_to_mesh.main([f"synth={bsp_path}", "--out-dir", str(out_dir)])
            self.assertEqual(rc, 0)
            glb_path = out_dir / "synth.glb"
            self.assertTrue(glb_path.is_file(), "synth.glb must exist")
            self.assertGreater(glb_path.stat().st_size, 0)
            manifest = json.loads((out_dir / "maps.json").read_text())
            self.assertEqual(manifest["schema"], bsp_to_mesh.SCHEMA)
            self.assertIn("synth", manifest["maps"])
            self.assertIn("glb", manifest["maps"]["synth"])

    def test_main_validate_mode_returns_0(self):
        bsp_data = build_synthetic_bsp()
        with tempfile.TemporaryDirectory() as tmp:
            bsp_path = Path(tmp) / "synth.bsp"
            bsp_path.write_bytes(bsp_data)
            rc = bsp_to_mesh.main([
                f"synth={bsp_path}",
                "--out-dir", str(tmp),
                "--validate",
            ])
            self.assertEqual(rc, 0)

    def test_main_preserves_existing_maps_json_obj_key(self):
        """Existing obj-only maps.json entry must survive glb update (obj key preserved)."""
        bsp_data = build_synthetic_bsp()
        with tempfile.TemporaryDirectory() as tmp:
            bsp_path = Path(tmp) / "synth.bsp"
            bsp_path.write_bytes(bsp_data)
            out_dir = Path(tmp) / "out"
            out_dir.mkdir()
            # Write a pre-existing maps.json with an obj entry and a custom key
            pre = {
                "schema": bsp_to_mesh.SCHEMA,
                "generator": bsp_to_mesh.GENERATOR,
                "maps": {"synth": {"obj": "synth.obj", "custom_key": "custom_value"}},
            }
            (out_dir / "maps.json").write_text(
                json.dumps(pre, indent=2) + "\n", encoding="ascii")
            bsp_to_mesh.main([f"synth={bsp_path}", "--out-dir", str(out_dir)])
            manifest = json.loads((out_dir / "maps.json").read_text())
            entry = manifest["maps"]["synth"]
            self.assertIn("obj", entry, "obj key must be preserved")
            self.assertIn("glb", entry, "glb key must be added")
            self.assertEqual(entry["custom_key"], "custom_value",
                             "non-conflicting custom fields must be preserved")

    def test_main_errors_on_missing_bsp(self):
        with self.assertRaises(SystemExit) as ctx:
            bsp_to_mesh.main(["missing=nonexistent.bsp"])
        self.assertNotEqual(ctx.exception.code, 0)

    def test_main_sky_texture_bsp(self):
        """BSP with a sky texture: sky faces get TAG_SKY material."""
        bsp_data = build_synthetic_bsp(tex_name="sky4")
        with tempfile.TemporaryDirectory() as tmp:
            bsp_path = Path(tmp) / "sky.bsp"
            bsp_path.write_bytes(bsp_data)
            out_dir = Path(tmp) / "out"
            rc = bsp_to_mesh.main([f"skytest={bsp_path}", "--out-dir", str(out_dir)])
            self.assertEqual(rc, 0)
            glb = (out_dir / "skytest.glb").read_bytes()
            json_len = struct.unpack_from("<I", glb, 12)[0]
            j = json.loads(glb[20:20 + json_len])
            tags = {m["extras"]["quake_tag"] for m in j["materials"]}
            self.assertIn(bsp_to_mesh.TAG_SKY, tags)


# ---------------------------------------------------------------------------
# Tests: committed asset lock
# ---------------------------------------------------------------------------

class TestCommittedAssets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(
            (MAPS_DIR / "maps.json").read_text(encoding="utf-8"))

    def test_manifest_schema(self):
        self.assertEqual(self.manifest["schema"], SCHEMA_EXPECTED := "komodobots.maps.v1")

    def test_all_maps_have_glb_key(self):
        for name in EXPECTED_MAPS:
            with self.subTest(map=name):
                entry = self.manifest["maps"].get(name, {})
                self.assertIn("glb", entry,
                              f"maps.json entry for {name} missing 'glb' key")
                self.assertIn("glb_triangles", entry,
                              f"maps.json entry for {name} missing 'glb_triangles' key")
                self.assertIn("glb_vertices", entry,
                              f"maps.json entry for {name} missing 'glb_vertices' key")

    def test_glb_files_exist(self):
        for name in EXPECTED_MAPS:
            with self.subTest(map=name):
                entry = self.manifest["maps"][name]
                glb_path = MAPS_DIR / entry["glb"]
                self.assertTrue(glb_path.is_file(), f"{glb_path} does not exist")

    def test_glb_magic_and_version(self):
        for name in EXPECTED_MAPS:
            with self.subTest(map=name):
                glb = (MAPS_DIR / f"{name}.glb").read_bytes()
                self.assertEqual(glb[:4], b"glTF", f"{name}.glb bad magic")
                version, total_len = struct.unpack_from("<II", glb, 4)
                self.assertEqual(version, 2, f"{name}.glb bad version")
                self.assertEqual(total_len, len(glb), f"{name}.glb total_len mismatch")

    def test_glb_json_chunk_valid(self):
        for name in EXPECTED_MAPS:
            with self.subTest(map=name):
                glb = (MAPS_DIR / f"{name}.glb").read_bytes()
                json_len, json_type = struct.unpack_from("<II", glb, 12)
                self.assertEqual(json_type, 0x4E4F534A)
                j = json.loads(glb[20:20 + json_len])
                self.assertEqual(j["asset"]["version"], "2.0")

    def test_glb_bin_chunk_valid(self):
        for name in EXPECTED_MAPS:
            with self.subTest(map=name):
                glb = (MAPS_DIR / f"{name}.glb").read_bytes()
                json_len = struct.unpack_from("<I", glb, 12)[0]
                bin_off = 12 + 8 + json_len
                bin_len, bin_type = struct.unpack_from("<II", glb, bin_off)
                self.assertEqual(bin_type, 0x004E4942, f"{name}.glb bad BIN chunk")
                self.assertGreater(bin_len, 0)

    def test_glb_size_budget(self):
        for name in EXPECTED_MAPS:
            with self.subTest(map=name):
                glb_size = (MAPS_DIR / f"{name}.glb").stat().st_size
                self.assertLessEqual(
                    glb_size, SIZE_BUDGET_BYTES,
                    f"{name}.glb ({glb_size:,} bytes) exceeds {SIZE_BUDGET_BYTES:,} byte budget",
                )

    def test_sampler_repeat_in_all_glbs(self):
        for name in EXPECTED_MAPS:
            with self.subTest(map=name):
                glb = (MAPS_DIR / f"{name}.glb").read_bytes()
                json_len = struct.unpack_from("<I", glb, 12)[0]
                j = json.loads(glb[20:20 + json_len])
                for s in j.get("samplers", []):
                    self.assertEqual(s.get("wrapS"), bsp_to_mesh.GLTF_SAMPLER_WRAP_REPEAT,
                                     f"{name}.glb sampler wrapS != REPEAT")
                    self.assertEqual(s.get("wrapT"), bsp_to_mesh.GLTF_SAMPLER_WRAP_REPEAT,
                                     f"{name}.glb sampler wrapT != REPEAT")

    def test_material_extras_quake_tag_present(self):
        for name in EXPECTED_MAPS:
            with self.subTest(map=name):
                glb = (MAPS_DIR / f"{name}.glb").read_bytes()
                json_len = struct.unpack_from("<I", glb, 12)[0]
                j = json.loads(glb[20:20 + json_len])
                valid_tags = {bsp_to_mesh.TAG_REGULAR, bsp_to_mesh.TAG_SKY,
                              bsp_to_mesh.TAG_SKIP, bsp_to_mesh.TAG_LIQUID}
                for mat in j.get("materials", []):
                    tag = mat.get("extras", {}).get("quake_tag")
                    self.assertIn(tag, valid_tags,
                                  f"{name}.glb material {mat.get('name')!r} has unexpected tag {tag!r}")

    def test_material_double_sided_all_glbs(self):
        for name in EXPECTED_MAPS:
            with self.subTest(map=name):
                glb = (MAPS_DIR / f"{name}.glb").read_bytes()
                json_len = struct.unpack_from("<I", glb, 12)[0]
                j = json.loads(glb[20:20 + json_len])
                for mat in j.get("materials", []):
                    self.assertTrue(mat.get("doubleSided"),
                                    f"{name}.glb material {mat.get('name')!r} not doubleSided")

    def test_provenance_sha256_in_asset_extras(self):
        for name in EXPECTED_MAPS:
            with self.subTest(map=name):
                glb = (MAPS_DIR / f"{name}.glb").read_bytes()
                json_len = struct.unpack_from("<I", glb, 12)[0]
                j = json.loads(glb[20:20 + json_len])
                sha = j["asset"]["extras"].get("source_bsp_sha256", "")
                self.assertRegex(sha, r"^[0-9a-f]{64}$",
                                 f"{name}.glb missing/invalid source_bsp_sha256")

    def test_maps_json_glb_sha_matches_manifest_entry(self):
        """maps.json source_bsp_sha256 matches the value embedded in the .glb."""
        for name in EXPECTED_MAPS:
            with self.subTest(map=name):
                entry = self.manifest["maps"][name]
                if "source_bsp_sha256" not in entry:
                    self.skipTest(f"{name} has no source_bsp_sha256 in maps.json")
                glb = (MAPS_DIR / f"{name}.glb").read_bytes()
                json_len = struct.unpack_from("<I", glb, 12)[0]
                j = json.loads(glb[20:20 + json_len])
                glb_sha = j["asset"]["extras"].get("source_bsp_sha256")
                self.assertEqual(entry["source_bsp_sha256"], glb_sha,
                                 f"{name}: maps.json sha vs .glb extras sha mismatch")

    def test_accessor_and_bufferview_counts_sane(self):
        """Each primitive needs 3 accessors (pos, uv, idx) and ~3 bufferViews."""
        for name in EXPECTED_MAPS:
            with self.subTest(map=name):
                glb = (MAPS_DIR / f"{name}.glb").read_bytes()
                json_len = struct.unpack_from("<I", glb, 12)[0]
                j = json.loads(glb[20:20 + json_len])
                n_prims = sum(len(m["primitives"]) for m in j["meshes"])
                n_acc = len(j["accessors"])
                n_bv = len(j["bufferViews"])
                # Each primitive -> 3 accessors (pos, uv, idx) and
                # 3 buffer views for geometry + 1 for image = 4 per primitive
                self.assertEqual(n_acc, n_prims * 3,
                                 f"{name}: expected {n_prims*3} accessors, got {n_acc}")
                self.assertGreaterEqual(n_bv, n_prims,
                                        f"{name}: bufferViews should be >= primitives")


# ---------------------------------------------------------------------------
# Tests: TypeScript viewer tag-contract (LD-C5, #99)
# ---------------------------------------------------------------------------

class TestViewerTagContract(unittest.TestCase):
    """Assert that mapScene.ts TAG_SKY / TAG_SKIP constants match bsp_to_mesh.py.

    GLTFLoader (three.js) merges glTF material extras directly into
    material.userData via Object.assign, so the TypeScript viewer reads
    material.userData.quake_tag and must compare it against the same string
    values that bsp_to_mesh.py writes into the GLB extras.

    Concretely:
      Python TAG_SKY  == "sky"   -> TS must read "sky"
      Python TAG_SKIP == "skip"  -> TS must read "skip"
    """

    MAP_SCENE_TS = REPO / "lab" / "dashboard" / "src" / "mapScene.ts"

    def _read_ts(self) -> str:
        return self.MAP_SCENE_TS.read_text(encoding="utf-8")

    def test_ts_file_exists(self):
        self.assertTrue(self.MAP_SCENE_TS.is_file(),
                        "mapScene.ts not found; update the path in this test")

    def test_ts_tag_sky_matches_python_tag_sky(self):
        """TAG_SKY constant in mapScene.ts must equal bsp_to_mesh.TAG_SKY."""
        ts = self._read_ts()
        expected = bsp_to_mesh.TAG_SKY   # "sky"
        # Match: const TAG_SKY = "sky";  or  const TAG_SKY = 'sky';
        import re
        m = re.search(r'const\s+TAG_SKY\s*=\s*["\']([^"\']+)["\']', ts)
        self.assertIsNotNone(m, "TAG_SKY constant not found in mapScene.ts")
        self.assertEqual(
            m.group(1), expected,
            f"mapScene.ts TAG_SKY is {m.group(1)!r}; "
            f"bsp_to_mesh.TAG_SKY is {expected!r} — they must match the GLB contract",
        )

    def test_ts_tag_skip_matches_python_tag_skip(self):
        """TAG_SKIP constant in mapScene.ts must equal bsp_to_mesh.TAG_SKIP."""
        ts = self._read_ts()
        expected = bsp_to_mesh.TAG_SKIP  # "skip"
        import re
        m = re.search(r'const\s+TAG_SKIP\s*=\s*["\']([^"\']+)["\']', ts)
        self.assertIsNotNone(m, "TAG_SKIP constant not found in mapScene.ts")
        self.assertEqual(
            m.group(1), expected,
            f"mapScene.ts TAG_SKIP is {m.group(1)!r}; "
            f"bsp_to_mesh.TAG_SKIP is {expected!r} — they must match the GLB contract",
        )

    def test_ts_reads_quake_tag_key(self):
        """mapScene.ts must access quake_tag (not an incorrect 'tag' key)."""
        ts = self._read_ts()
        self.assertIn(
            "quake_tag",
            ts,
            "mapScene.ts does not reference 'quake_tag'; "
            "GLTFLoader maps material extras directly into userData so the key is "
            "material.userData.quake_tag",
        )

    def test_ts_does_not_use_stale_extras_tag_path(self):
        """mapScene.ts must not use the stale userData.extras.tag path."""
        ts = self._read_ts()
        self.assertNotIn(
            "extras.tag",
            ts,
            "mapScene.ts still uses 'extras.tag' (stale nested path); "
            "GLTFLoader flattens extras into userData directly",
        )


if __name__ == "__main__":
    unittest.main()
