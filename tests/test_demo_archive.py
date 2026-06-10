"""demo_archive: pure-helper coverage for the SSD archival hook + backfill (#64).

Locks the path mapping (map/run_id -> SSD path, hostile names rejected), the
manifest/result parsing (sha256, run.env MAP, inventory TSV, KB_ARCHIVE lines),
the repo tricks/<map> collector (full `<label>__<run_id>` stem kept as the
archive name, never normalized), and the reconcile classification (already
archived / to copy / unverifiable / ssd-only) -- including that an SSD hash
mismatch is NEVER scheduled for an overwrite.
"""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import demo_archive as da  # noqa: E402

SHA_A = "a" * 64
SHA_B = "b" * 64


def src(run_id, map_name, sha, where, path="x"):
    return {"run_id": run_id, "map": map_name, "sha256": sha, "size": "1", "where": where, "path": path}


class TestSsdArchivePath(unittest.TestCase):
    def test_happy_path(self):
        self.assertEqual(
            da.ssd_archive_path("dm3", "20260610T120000Z"),
            "/mnt/usb-ssd/non-games/lab/Komodobots/dm3/20260610T120000Z.mvd",
        )

    def test_custom_run_ids_allowed(self):
        # C1/A3 sessions used descriptive ids like solo_prewar_d130.
        self.assertTrue(da.ssd_archive_path("trick", "solo_prewar_d130").endswith("/trick/solo_prewar_d130.mvd"))

    def test_hostile_names_rejected(self):
        for map_name, run_id in (
            ("../games", "rid"),
            ("dm3/sub", "rid"),
            ("", "rid"),
            ("dm3", "../../etc"),
            ("dm3", "rid x"),
            ("dm3", ""),
            ("dm3", "rid;rm"),
            ("dm 3", "rid"),
        ):
            with self.assertRaises(ValueError, msg=f"{map_name!r}/{run_id!r}"):
                da.ssd_archive_path(map_name, run_id)

    def test_safe_variant_returns_empty(self):
        self.assertEqual(da.ssd_archive_path_safe("../x", "rid"), "")


class TestParsers(unittest.TestCase):
    def test_parse_sha256_text_sha256sum_format(self):
        self.assertEqual(da.parse_sha256_text(f"{SHA_A}  demo.mvd\n"), SHA_A)

    def test_parse_sha256_text_bare_and_uppercase(self):
        self.assertEqual(da.parse_sha256_text(SHA_A.upper()), SHA_A)

    def test_parse_sha256_text_garbage(self):
        for text in ("", "\n", "not-a-hash  demo.mvd", "deadbeef"):
            self.assertEqual(da.parse_sha256_text(text), "")

    def test_parse_run_env_map(self):
        body = "RUN_ID=x\nPORT=28599\nMAP=dm3\nRUNDIR=/home/x\n"
        self.assertEqual(da.parse_run_env_map(body), "dm3")

    def test_parse_run_env_map_missing_or_invalid(self):
        self.assertEqual(da.parse_run_env_map("RUN_ID=x\n"), "")
        self.assertEqual(da.parse_run_env_map("MAP=bad map\n"), "")
        self.assertEqual(da.parse_run_env_map(""), "")

    def test_parse_inventory_tsv(self):
        text = (
            f"rid1\tdm3\t{SHA_A}\t123\n"
            f"rid2\ttrick\t{SHA_B.upper()}\t456\n"
            "short\tline\n"  # wrong field count
            f"bad rid\tdm3\t{SHA_A}\t1\n"  # invalid run id
            f"rid3\tdm3\tnothash\t1\n"  # invalid sha
            f"rid4\tbad/map\t{SHA_A}\t1\n"  # invalid map
        )
        rows = da.parse_inventory_tsv(text)
        self.assertEqual([r["run_id"] for r in rows], ["rid1", "rid2"])
        self.assertEqual(rows[1]["sha256"], SHA_B)  # lowercased

    def test_parse_archive_result_last_line_wins(self):
        out = (
            "noise\n"
            f"KB_ARCHIVE run=r1 map=dm3 status=copy-failed sha256= dst=/x\n"
            f"KB_ARCHIVE run=r1 map=dm3 status=copied sha256={SHA_A} dst=/x\n"
        )
        result = da.parse_archive_result(out)
        self.assertEqual(result["status"], "copied")
        self.assertEqual(result["sha256"], SHA_A)

    def test_parse_archive_result_empty(self):
        self.assertEqual(da.parse_archive_result("")["status"], "no-result")
        self.assertEqual(da.parse_archive_result("random text")["status"], "no-result")

    def test_parse_all_archive_results_keyed_by_map_run(self):
        out = (
            f"KB_ARCHIVE run=r1 map=dm3 status=copied sha256={SHA_A} dst=/x\n"
            f"KB_ARCHIVE run=r1 map=trick status=identical sha256={SHA_B} dst=/y\n"
        )
        results = da.parse_all_archive_results(out)
        self.assertEqual(results[("dm3", "r1")]["status"], "copied")
        self.assertEqual(results[("trick", "r1")]["status"], "identical")


class TestRepoTricksCollector(unittest.TestCase):
    """The repo `tricks/<map>/*.mvd` evidence demos (Codex P2: for some runs
    these are the only remaining copy, so backfill must see them)."""

    def collect(self, build):
        with tempfile.TemporaryDirectory(prefix="kb-tricks-") as tmp:
            root = Path(tmp)
            build(root)
            return da.collect_repo_tricks_sources(root)

    def test_full_label_stem_is_the_archive_name(self):
        body = b"MVD bytes"

        def build(root):
            d = root / "dm3"
            d.mkdir()
            (d / "dm3_sng_to_rl__20260607T151125Z.mvd").write_bytes(body)

        rows, skipped = self.collect(build)
        self.assertEqual(skipped, [])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["run_id"], "dm3_sng_to_rl__20260607T151125Z")
        self.assertEqual(row["map"], "dm3")
        self.assertEqual(row["where"], "repo-tricks")
        self.assertEqual(row["sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(row["size"], str(len(body)))
        # Name mapping: the SSD file keeps the FULL original filename (label
        # prefix included), never normalized to bare <run_id>.mvd.
        self.assertEqual(
            da.ssd_archive_path(row["map"], row["run_id"]),
            "/mnt/usb-ssd/non-games/lab/Komodobots/dm3/dm3_sng_to_rl__20260607T151125Z.mvd",
        )

    def test_label_only_stems_allowed(self):
        def build(root):
            d = root / "dm3"
            d.mkdir()
            (d / "trick_accel_full__solo_lab_d200.mvd").write_bytes(b"x")

        rows, skipped = self.collect(build)
        self.assertEqual(skipped, [])
        self.assertEqual(rows[0]["run_id"], "trick_accel_full__solo_lab_d200")

    def test_hostile_and_empty_names_skipped(self):
        def build(root):
            d = root / "dm3"
            d.mkdir()
            (d / "bad name.mvd").write_bytes(b"x")  # whitespace in stem
            (d / "dots..in.stem.mvd").write_bytes(b"x")  # dot segments
            (d / "empty__20260607T000000Z.mvd").write_bytes(b"")  # zero bytes
            (d / "good__20260607T000001Z.mvd").write_bytes(b"x")

        rows, skipped = self.collect(build)
        self.assertEqual([r["run_id"] for r in rows], ["good__20260607T000001Z"])
        self.assertEqual(len(skipped), 3)

    def test_bad_map_dir_skipped_and_loose_files_ignored(self):
        def build(root):
            bad = root / "dm 3"
            bad.mkdir()
            (bad / "a__20260607T000000Z.mvd").write_bytes(b"x")
            (root / "loose__20260607T000000Z.mvd").write_bytes(b"x")  # not in a map dir

        rows, skipped = self.collect(build)
        self.assertEqual(rows, [])
        self.assertEqual(len(skipped), 1)
        self.assertIn("bad map dir", skipped[0])

    def test_missing_root_is_empty(self):
        with tempfile.TemporaryDirectory(prefix="kb-tricks-") as tmp:
            rows, skipped = da.collect_repo_tricks_sources(Path(tmp) / "no-such-dir")
        self.assertEqual((rows, skipped), ([], []))


class TestReconcile(unittest.TestCase):
    def ssd(self, run_id, map_name, sha):
        return {"run_id": run_id, "map": map_name, "sha256": sha, "size": "1"}

    def test_already_archived_verified(self):
        state = da.reconcile([src("r1", "dm3", SHA_A, "server")], [self.ssd("r1", "dm3", SHA_A)])
        self.assertEqual(state["already"], [("dm3", "r1")])
        self.assertEqual(state["to_copy"], [])
        self.assertEqual(state["unverifiable"], [])

    def test_missing_prefers_server_source(self):
        sources = [
            src("r1", "dm3", SHA_A, "artifacts"),
            src("r1", "dm3", SHA_A, "server"),
            src("r1", "dm3", SHA_A, "nquake"),
        ]
        state = da.reconcile(sources, [])
        self.assertEqual(len(state["to_copy"]), 1)
        self.assertEqual(state["to_copy"][0]["where"], "server")

    def test_missing_local_only_uses_artifacts(self):
        sources = [src("r1", "dm3", SHA_A, "nquake"), src("r1", "dm3", SHA_A, "artifacts")]
        state = da.reconcile(sources, [])
        self.assertEqual(state["to_copy"][0]["where"], "artifacts")

    def test_repo_tricks_is_last_resort_source(self):
        sources = [src("r1", "dm3", SHA_A, "repo-tricks"), src("r1", "dm3", SHA_A, "nquake")]
        state = da.reconcile(sources, [])
        self.assertEqual(state["to_copy"][0]["where"], "nquake")

    def test_repo_tricks_only_source_is_copied(self):
        # Codex P2 scenario: the committed evidence file is the only copy left.
        state = da.reconcile([src("dm3_sng_to_rl__20260607T151125Z", "dm3", SHA_A, "repo-tricks")], [])
        self.assertEqual(len(state["to_copy"]), 1)
        self.assertEqual(state["to_copy"][0]["where"], "repo-tricks")

    def test_source_conflict_is_unverifiable_not_copied(self):
        sources = [src("r1", "dm3", SHA_A, "server"), src("r1", "dm3", SHA_B, "artifacts")]
        state = da.reconcile(sources, [])
        self.assertEqual(state["to_copy"], [])
        self.assertEqual(state["unverifiable"][0]["reason"], "source-conflict")

    def test_source_conflict_resolved_by_ssd(self):
        sources = [src("r1", "dm3", SHA_A, "server"), src("r1", "dm3", SHA_B, "artifacts")]
        state = da.reconcile(sources, [self.ssd("r1", "dm3", SHA_A)])
        self.assertEqual(state["already"], [("dm3", "r1")])
        self.assertEqual(state["unverifiable"], [])

    def test_ssd_mismatch_never_overwritten(self):
        state = da.reconcile([src("r1", "dm3", SHA_A, "server")], [self.ssd("r1", "dm3", SHA_B)])
        self.assertEqual(state["to_copy"], [])
        self.assertEqual(state["unverifiable"][0]["reason"], "ssd-mismatch")

    def test_ssd_only_reported(self):
        state = da.reconcile([], [self.ssd("ghost", "dm3", SHA_A)])
        self.assertEqual(state["ssd_only"], [("dm3", "ghost")])

    def test_same_run_id_on_two_maps_kept_separate(self):
        sources = [src("r1", "dm3", SHA_A, "server"), src("r1", "trick", SHA_B, "server")]
        state = da.reconcile(sources, [])
        self.assertEqual(len(state["to_copy"]), 2)
        self.assertEqual(state["unverifiable"], [])


class TestRemoteScripts(unittest.TestCase):
    """Guard the generated bash against format-string regressions."""

    def test_no_unsubstituted_python_placeholders(self):
        for script in (
            da.ARCHIVE_ONE_SCRIPT,
            da.BACKFILL_INSTALL_SCRIPT,
            da.REMOTE_RUNS_INVENTORY_SCRIPT,
            da.SSD_INVENTORY_SCRIPT,
        ):
            self.assertNotIn("%(", script)
            self.assertNotIn("%%", script)

    def test_install_is_atomic_and_never_set_e(self):
        for script in (da.ARCHIVE_ONE_SCRIPT, da.BACKFILL_INSTALL_SCRIPT):
            self.assertIn('.part.$$', script)
            self.assertIn("set -u", script)
            self.assertNotIn("set -e", script)
            self.assertIn(da.SSD_ROOT, script)
            # bash printf placeholders survived the Python %-formatting
            self.assertIn("KB_ARCHIVE run=%s map=%s status=%s sha256=%s dst=%s", script)

    def test_backfill_reads_plan_from_fd3(self):
        self.assertIn("<&3", da.BACKFILL_INSTALL_SCRIPT)
        self.assertIn("staging", da.BACKFILL_INSTALL_SCRIPT)

    def test_staging_names_are_map_prefixed(self):
        # Two maps may share a run_id (reconcile keeps them separate); the
        # staged filename must carry the map or the uploads clobber each other.
        self.assertIn('${map}__${rid}.mvd', da.BACKFILL_INSTALL_SCRIPT)

    def test_inventory_scripts_cover_expected_roots(self):
        self.assertIn(da.REMOTE_RUNS_DIR, da.REMOTE_RUNS_INVENTORY_SCRIPT)
        self.assertIn(da.SSD_ROOT, da.SSD_INVENTORY_SCRIPT)


class TestCountTable(unittest.TestCase):
    def test_totals_row(self):
        state = {
            "by_key": {("dm3", "r1"): [], ("dm3", "r2"): [], ("trick", "r3"): []},
            "already": [("dm3", "r1")],
            "ssd_only": [("dm2", "old")],
            "to_copy": [],
            "unverifiable": [],
        }
        table = da._count_table(state, [("dm3", "r2"), ("trick", "r3")], [], applied=True)
        self.assertIn("| dm3 | 2 | 1 | 1 | 0 | 0 |", table)
        self.assertIn("| trick | 1 | 0 | 1 | 0 | 0 |", table)
        self.assertIn("| dm2 | 0 | 0 | 0 | 0 | 1 |", table)
        self.assertIn("| **total** | **3** | **1** | **2** | **0** | **1** |", table)


if __name__ == "__main__":
    unittest.main()
