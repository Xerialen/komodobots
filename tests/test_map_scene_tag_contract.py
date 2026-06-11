"""
LD-C5 (#99): mapScene.ts tag-contract tests.

Validates the GLB material tag handling in lab/dashboard/src/mapScene.ts against
the GLB contract written by lab/tools/bsp_to_mesh.py.

Codex P1 (HEAD 2ee6510, discussion_r3395398065):
  mapScene.ts read material.userData.extras.tag and compared with "TAG_SKY"/"TAG_SKIP"
  but bsp_to_mesh.py writes extras.quake_tag = "sky"/"skip" (lowercase).
  Fix: read quake_tag key, compare against lowercase "sky"/"skip".

Codex P2 (HEAD 2ee6510, discussion_r3395398068):
  Wire meshes were always initialized hidden. If setWireframe(true) was called
  before the GLB loaded, wireframeActive was true but wireMeshes empty. Later
  calls returned early (enabled === wireframeActive), so the wireframe never showed
  until the user toggled it off and on again.
  Fix: new wire meshes inherit wireMesh.visible = wireframeActive at creation.

These tests are offline source-inspection only — no browser or Three.js runtime.
"""

import os
import re
import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MAP_SCENE = REPO_ROOT / "lab" / "dashboard" / "src" / "mapScene.ts"
BSP_TO_MESH = REPO_ROOT / "lab" / "tools" / "bsp_to_mesh.py"


def read(path) -> str:
    return path.read_text(encoding="utf-8")


class TagConstantContractTests(unittest.TestCase):
    """The viewer's TAG_SKY/TAG_SKIP constants must match bsp_to_mesh.py values.

    Codex P1 (discussion_r3395398065): the viewer used "TAG_SKY"/"TAG_SKIP"
    (uppercase, wrong) instead of "sky"/"skip" (lowercase, what the converter
    writes into the GLB quake_tag field).
    """

    def setUp(self):
        self.map_scene_src = read(MAP_SCENE)
        self.bsp_src = read(BSP_TO_MESH)

    def _get_bsp_tag_value(self, const_name: str) -> str:
        """Extract value of TAG_SKY/TAG_SKIP/etc from bsp_to_mesh.py."""
        m = re.search(rf'^{const_name}\s*=\s*"([^"]+)"', self.bsp_src, re.MULTILINE)
        self.assertIsNotNone(m, f"{const_name} not found in bsp_to_mesh.py")
        return m.group(1)

    def _get_scene_tag_value(self, const_name: str) -> str:
        """Extract value of TAG_SKY/TAG_SKIP from mapScene.ts."""
        m = re.search(rf'const {const_name}\s*=\s*"([^"]+)"', self.map_scene_src)
        self.assertIsNotNone(m, f"{const_name} not found in mapScene.ts")
        return m.group(1)

    def test_TAG_SKY_value_matches_bsp_to_mesh(self):
        """mapScene.ts TAG_SKY must equal bsp_to_mesh.py TAG_SKY (both "sky")."""
        bsp_val = self._get_bsp_tag_value("TAG_SKY")
        scene_val = self._get_scene_tag_value("TAG_SKY")
        self.assertEqual(
            scene_val, bsp_val,
            f"TAG_SKY mismatch: mapScene={scene_val!r} bsp_to_mesh={bsp_val!r}",
        )

    def test_TAG_SKIP_value_matches_bsp_to_mesh(self):
        """mapScene.ts TAG_SKIP must equal bsp_to_mesh.py TAG_SKIP (both "skip")."""
        bsp_val = self._get_bsp_tag_value("TAG_SKIP")
        scene_val = self._get_scene_tag_value("TAG_SKIP")
        self.assertEqual(
            scene_val, bsp_val,
            f"TAG_SKIP mismatch: mapScene={scene_val!r} bsp_to_mesh={bsp_val!r}",
        )

    def test_TAG_SKY_is_lowercase(self):
        """TAG_SKY constant must be lowercase "sky" not "TAG_SKY" or "SKY"."""
        val = self._get_scene_tag_value("TAG_SKY")
        self.assertEqual(val, "sky", f"TAG_SKY must be lowercase 'sky', got {val!r}")

    def test_TAG_SKIP_is_lowercase(self):
        """TAG_SKIP constant must be lowercase "skip" not "TAG_SKIP" or "SKIP"."""
        val = self._get_scene_tag_value("TAG_SKIP")
        self.assertEqual(val, "skip", f"TAG_SKIP must be lowercase 'skip', got {val!r}")


class QuakeTagExtrasPathTests(unittest.TestCase):
    """mapScene.ts must read the quake_tag key from material extras.

    Codex P1 (discussion_r3395398065): GLTFLoader loads the bsp_to_mesh GLB and
    places material extras under material.userData.  The key is "quake_tag"
    (set by bsp_to_mesh.py line 729: extras: {"quake_texture":..., "quake_tag":...}).
    Reading "tag" instead of "quake_tag" means no material ever matches.
    """

    def setUp(self):
        self.src = read(MAP_SCENE)

    def test_quake_tag_key_read(self):
        """mapScene.ts must look up 'quake_tag' from material userData/extras."""
        self.assertIn(
            "quake_tag",
            self.src,
            "mapScene.ts must read the 'quake_tag' key from material extras",
        )

    def test_old_bare_tag_key_not_used_for_sky_check(self):
        """The old pattern 'extras.tag' / '{ tag?: string }' must not be used
        as the primary lookup for sky/skip classification."""
        # The dangerous pattern: reading .tag (not .quake_tag) from extras
        # Accept comments mentioning "tag" but not code like .tag ?? ""
        bad = re.compile(r'\(extras as \{\s*tag\?:\s*string\s*\}\)\.tag')
        self.assertNotRegex(
            self.src,
            bad,
            "mapScene.ts must not use bare .tag key for sky/skip — use .quake_tag",
        )

    def test_bsp_to_mesh_uses_quake_tag_key(self):
        """bsp_to_mesh.py must write the 'quake_tag' key in material extras
        (regression guard: if the converter key changes, this test also fails
        so both sides must be updated together)."""
        bsp_src = read(BSP_TO_MESH)
        self.assertIn(
            '"quake_tag"',
            bsp_src,
            "bsp_to_mesh.py must write \"quake_tag\" key in material extras",
        )


class WireframePreloadTests(unittest.TestCase):
    """Wire meshes must honor wireframeActive at creation time.

    Codex P2 (discussion_r3395398068): setWireframe(true) before GLB load sets
    wireframeActive=true but leaves wireMeshes empty.  Subsequent loads create
    wire meshes as hidden, and later setWireframe(true) calls return early
    because enabled === wireframeActive is already true.  The user must toggle
    off-then-on to see the wireframe.
    Fix: wireMesh.visible = wireframeActive (not hardcoded false) at creation.
    """

    def setUp(self):
        self.src = read(MAP_SCENE)

    def test_wire_mesh_visible_uses_wireframeActive(self):
        """New wire meshes must be initialized with wireMesh.visible = wireframeActive
        so a pre-load toggle is honored."""
        self.assertIn(
            "wireMesh.visible = wireframeActive",
            self.src,
            "wireMesh.visible must be set to wireframeActive (not hardcoded false)",
        )

    def test_wire_mesh_not_hardcoded_hidden(self):
        """wireMesh.visible = false must NOT appear — it would ignore pre-load state."""
        self.assertNotIn(
            "wireMesh.visible = false",
            self.src,
            "wireMesh.visible must not be hardcoded false (breaks pre-load wireframe toggle)",
        )

    def test_setWireframe_early_return_guard_present(self):
        """setWireframe must still have the idempotent early-return guard."""
        self.assertIn(
            "if (enabled === wireframeActive) return",
            self.src,
            "setWireframe must still short-circuit when state unchanged",
        )


if __name__ == "__main__":
    unittest.main()
