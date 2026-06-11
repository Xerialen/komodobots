"""Routes manifest builder (LD-C1, issue #90): lab/tools/build_routes_manifest.py.

Locks the komodobots.routes.v1 contract the Mockup view, KPI dock and control
drawer consume:

  * all four dashboard maps emit a manifest plus index.json; non-dm3 maps are
    honest empty route lists, never missing files;
  * dm3 reproduces the 11 censused routes (sorted by name) with non-empty
    downsampled polylines, census human stats, gap markers (edge/land xyz,
    required_speed, human_speed_at_edge, hard, type), teleports, and
    per-route source provenance (census + .cmds path + sha256);
  * the sng_to_rl decisive gap carries the 526-region required_speed the
    census measured (525.3 required vs 528.6 human at the edge);
  * hashes are over LF-normalized text so they are identical on Linux CI and
    autocrlf Windows checkouts;
  * determinism/idempotency: two builds are byte-identical, and the COMMITTED
    manifests match a fresh build byte-for-byte -- which is exactly the
    ticket's `build && git diff --stat` shows-no-diff gate.

Fixtures are the committed real assets (census.json + replay .cmds), the same
precedent as test_records_build (#93/#123).
"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lab" / "tools"))

import build_routes_manifest as brm            # noqa: E402

CENSUS = json.loads(brm.CENSUS_PATH.read_text(encoding="utf-8"))
COMMITTED = REPO / "lab" / "dashboard" / "public" / "data" / "routes"


def fresh_build() -> dict[str, bytes]:
    return {name: brm.render(name, doc)
            for name, doc in brm.build_manifests().items()}


class TestSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = brm.build_manifests()

    def test_all_five_files_emitted(self):
        self.assertEqual(
            sorted(self.docs),
            sorted(["dm3.json", "dm2.json", "frobodm2.json", "trick.json",
                    "index.json"]))

    def test_schema_and_version_everywhere(self):
        for name, doc in self.docs.items():
            self.assertEqual(doc["schema"], "komodobots.routes.v1", name)
            self.assertEqual(doc["v"], 1, name)

    def test_dm3_reproduces_the_11_censused_routes_sorted(self):
        names = [r["name"] for r in self.docs["dm3.json"]["routes"]]
        self.assertEqual(len(names), 11)
        self.assertEqual(names, sorted(CENSUS))

    def test_non_dm3_maps_are_honest_empty_lists(self):
        for name in ("dm2.json", "frobodm2.json", "trick.json"):
            doc = self.docs[name]
            self.assertEqual(doc["routes"], [], name)
            self.assertIn("provenance", doc, name)

    def test_index_lists_all_maps_in_dashboard_order(self):
        maps = self.docs["index.json"]["maps"]
        self.assertEqual([m["map"] for m in maps],
                         ["dm3", "dm2", "frobodm2", "trick"])
        self.assertEqual([m["file"] for m in maps],
                         ["dm3.json", "dm2.json", "frobodm2.json",
                          "trick.json"])
        self.assertEqual([m["routes"] for m in maps], [11, 0, 0, 0])

    def test_every_route_has_nonempty_polyline_of_xyz_points(self):
        for route in self.docs["dm3.json"]["routes"]:
            poly = route["polyline"]
            self.assertGreater(len(poly), 0, route["name"])
            for p in poly:
                self.assertEqual(len(p), 3, route["name"])
                for c in p:
                    self.assertIsInstance(c, float, route["name"])

    def test_human_stats_come_straight_from_census(self):
        for route in self.docs["dm3.json"]["routes"]:
            ent = CENSUS[route["name"]]
            self.assertEqual(route["human"], {
                "duration_s": ent["duration_s"],
                "active_mean_speed": ent["active_mean_speed"],
                "peak_speed": ent["peak_speed"],
            }, route["name"])

    def test_gap_and_teleport_counts_match_census(self):
        for route in self.docs["dm3.json"]["routes"]:
            ent = CENSUS[route["name"]]
            self.assertEqual(len(route["gaps"]), len(ent["gaps"]),
                             route["name"])
            self.assertEqual(len(route["teleports"]), len(ent["teleports"]),
                             route["name"])
            for gap in route["gaps"]:
                self.assertEqual(sorted(gap), sorted(brm.GAP_FIELDS),
                                 route["name"])


class TestSngToRlSpotChecks(unittest.TestCase):
    """The ticket's named acceptance route."""

    @classmethod
    def setUpClass(cls):
        doc = brm.build_manifests()["dm3.json"]
        cls.sng = next(r for r in doc["routes"] if r["name"] == "sng_to_rl")

    def test_polyline_longer_than_100_points(self):
        self.assertGreater(len(self.sng["polyline"]), 100)

    def test_polyline_ends_at_the_rl_goal(self):
        # the human trajectory's last frame is the arrival at RL
        x, y, z = self.sng["polyline"][-1]
        self.assertAlmostEqual(x, 1591.0, delta=2.0)
        self.assertAlmostEqual(y, 526.0, delta=2.0)
        self.assertAlmostEqual(z, -88.0, delta=2.0)

    def test_decisive_gap_required_speed_in_the_526_region(self):
        final_hard = [g for g in self.sng["gaps"] if g["hard"]][-1]
        self.assertAlmostEqual(final_hard["required_speed"], 525.3, places=1)
        self.assertTrue(520.0 <= final_hard["required_speed"] <= 530.0)
        self.assertAlmostEqual(final_hard["human_speed_at_edge"], 528.6,
                               places=1)
        self.assertEqual(final_hard["type"], "leap")
        self.assertEqual(len(final_hard["edge"]), 3)
        self.assertEqual(len(final_hard["land"]), 3)

    def test_teleport_entrance_and_exit_present(self):
        self.assertEqual(len(self.sng["teleports"]), 1)
        tp = self.sng["teleports"][0]
        self.assertEqual(sorted(tp), ["from", "to"])
        self.assertEqual(len(tp["from"]), 3)
        self.assertEqual(len(tp["to"]), 3)

    def test_source_provenance_paths_and_hash(self):
        src = self.sng["source"]
        self.assertEqual(
            src["census"],
            "experiments/nav_doctrine/evidence/trick-census/census.json")
        self.assertEqual(
            src["cmds"],
            "experiments/nav_doctrine/evidence/replay/dm3_sng_to_rl.cmds")
        # independent recomputation of the LF-normalized hash
        raw = (REPO / src["cmds"]).read_text(encoding="utf-8")
        expect = hashlib.sha256(
            raw.replace("\r\n", "\n").encode("utf-8")).hexdigest()
        self.assertEqual(src["cmds_sha256"], expect)


class TestDeterminism(unittest.TestCase):
    def test_hash_is_line_ending_invariant(self):
        with tempfile.TemporaryDirectory() as tmp:
            lf = Path(tmp) / "lf.txt"
            crlf = Path(tmp) / "crlf.txt"
            lf.write_bytes(b"# header\n1 2 3\n")
            crlf.write_bytes(b"# header\r\n1 2 3\r\n")
            self.assertEqual(brm.sha256_normalized(lf),
                             brm.sha256_normalized(crlf))

    def test_provenance_hashes_are_hex_sha256(self):
        doc = brm.build_manifests()["dm3.json"]
        hashes = [doc["provenance"]["census_sha256"]]
        hashes += [r["source"]["cmds_sha256"] for r in doc["routes"]]
        for h in hashes:
            self.assertRegex(h, r"^[0-9a-f]{64}$")

    def test_two_builds_are_byte_identical(self):
        self.assertEqual(fresh_build(), fresh_build())

    def test_write_manifests_is_idempotent_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "routes"
            first = {p.name: p.read_bytes() for p in brm.write_manifests(out)}
            second = {p.name: p.read_bytes() for p in brm.write_manifests(out)}
            self.assertEqual(first, second)

    def test_committed_manifests_match_a_fresh_build(self):
        """The ticket's measurement: rebuild produces no git diff. Committed
        files are `-text` in .gitattributes, so bytes compare exactly."""
        built = fresh_build()
        for name, blob in built.items():
            committed = COMMITTED / name
            self.assertTrue(committed.is_file(),
                            f"{name} missing from {COMMITTED} -- run "
                            f"`python lab/tools/build_routes_manifest.py`")
            self.assertEqual(
                committed.read_bytes(), blob,
                f"{name} is stale -- rerun "
                f"`python lab/tools/build_routes_manifest.py` and commit")


class TestDownsampling(unittest.TestCase):
    def test_stride_targets_the_documented_hz(self):
        pts = [[float(i), 0.0, 0.0] for i in range(100)]
        out = brm.downsample(pts, fps=75.0)        # stride 6
        self.assertEqual(out[0], [0.0, 0.0, 0.0])
        self.assertEqual(out[1], [6.0, 0.0, 0.0])
        self.assertEqual(out[-1], [99.0, 0.0, 0.0])   # last frame always kept

    def test_last_frame_not_duplicated_when_on_stride(self):
        pts = [[float(i), 0.0, 0.0] for i in range(13)]
        out = brm.downsample(pts, fps=75.0)        # 0,6,12 -- 12 is on-stride
        self.assertEqual([p[0] for p in out], [0.0, 6.0, 12.0])

    def test_zero_fps_keeps_every_frame(self):
        pts = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
        self.assertEqual(brm.downsample(pts, fps=0.0), pts)

    def test_empty_points(self):
        self.assertEqual(brm.downsample([], fps=77.0), [])


if __name__ == "__main__":
    unittest.main()
