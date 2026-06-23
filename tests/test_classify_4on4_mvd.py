#!/usr/bin/env python3
"""Tests for scripts/classify_4on4_mvd.py — the human 4on4 dm3 corpus classifier (#358 / F-DATA-1).

Two layers:
  * pure-function unit tests for classify_row / the provenance helpers (no MVD files needed), and
  * an invariant test over the COMMITTED manifest, so a future edit that corrupts the training
    foundation (a non-dm3 TRAIN row, a missing content lock, a bot-team leak) fails CI loudly.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import classify_4on4_mvd as c  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "data" / "corpus" / "human_4on4_dm3_mvd_manifest.json"
SHA_A = "a" * 64
SHA_B = "b" * 64


def _row(**kw):
    r = {"demo": "x.mvd", "ok": True, "map": c.DM3_TITLE, "active_players": 8,
         "teams": ["-sd-", "]sr["], "class": "EXCLUDED", "reason": None,
         "sha256": None, "size_bytes": None}
    r.update(kw)
    return r


class ClassifyRowTest(unittest.TestCase):
    def test_valid_4on4_is_train(self):
        self.assertEqual(c.classify_row(_row(), 6)["class"], "TRAIN")

    def test_parse_failure_excluded(self):
        self.assertEqual(c.classify_row(_row(ok=False), 6)["class"], "EXCLUDED")

    def test_non_dm3_map_excluded(self):
        out = c.classify_row(_row(map="Blood Run"), 6)
        self.assertEqual(out["class"], "EXCLUDED")
        self.assertIn("not_dm3", out["reason"])

    def test_not_two_teams_excluded(self):
        self.assertEqual(c.classify_row(_row(teams=["-sd-"]), 6)["class"], "EXCLUDED")

    def test_red_blue_bot_default_excluded(self):
        out = c.classify_row(_row(teams=["red", "blue"]), 6)
        self.assertEqual(out["class"], "EXCLUDED")
        self.assertTrue(out["reason"].startswith("bot_lab_default_teams"))

    def test_red_blue_case_insensitive(self):
        self.assertEqual(c.classify_row(_row(teams=["RED", "Blue"]), 6)["class"], "EXCLUDED")

    def test_team_min_boundary(self):
        self.assertEqual(c.classify_row(_row(active_players=6), 6)["class"], "TRAIN")
        self.assertEqual(c.classify_row(_row(active_players=5), 6)["class"], "EXCLUDED")

    def test_classify_row_is_pure_on_provenance(self):
        # re-applying the rule must not touch the content lock fields
        r = _row(sha256=SHA_A, size_bytes=123)
        out = c.classify_row(r, 6)
        self.assertEqual((out["sha256"], out["size_bytes"]), (SHA_A, 123))


class ProvenanceHelperTest(unittest.TestCase):
    def test_parse_corpus_tsv_valid_and_skips_malformed(self):
        text = (
            f"{SHA_A}\t100\tgood.mvd\tservexeri\n"
            f"{SHA_B.upper()}\t200\tupper.mvd\tservexeri\n"   # sha normalized to lower
            f"{SHA_A}\t300\tmissing_source.mvd\n"             # wrong field count -> skip
            f"deadbeef\t400\tbad_sha.mvd\tservexeri\n"        # bad sha -> skip
            f"{SHA_A}\tNaN\tbad_size.mvd\tservexeri\n"        # non-numeric size -> skip
        )
        prov = c.parse_corpus_tsv(text)
        self.assertEqual(prov["good.mvd"], (SHA_A, 100))
        self.assertEqual(prov["upper.mvd"], (SHA_B, 200))
        self.assertNotIn("missing_source.mvd", prov)
        self.assertNotIn("bad_sha.mvd", prov)
        self.assertNotIn("bad_size.mvd", prov)

    def test_merge_provenance_by_basename_no_overwrite(self):
        rows = [_row(demo="a.mvd"), _row(demo="b.mvd", sha256=SHA_B, size_bytes=9)]
        c.merge_provenance(rows, {"a.mvd": (SHA_A, 11), "b.mvd": (SHA_A, 22)})
        self.assertEqual((rows[0]["sha256"], rows[0]["size_bytes"]), (SHA_A, 11))
        self.assertEqual((rows[1]["sha256"], rows[1]["size_bytes"]), (SHA_B, 9))  # preserved

    def test_validate_provenance_flags_unlocked_train_only(self):
        rows = [
            _row(demo="train_ok.mvd", sha256=SHA_A, size_bytes=5),
            _row(demo="train_bad.mvd"),            # TRAIN, no lock -> bad
            _row(demo="excluded.mvd"),             # EXCLUDED, no lock -> ok
        ]
        for r, cls in zip(rows, ("TRAIN", "TRAIN", "EXCLUDED")):
            r["class"] = cls
        bad = c.validate_provenance(rows)
        self.assertEqual(bad, ["train_bad.mvd"])

    def test_validate_provenance_rejects_short_sha_and_zero_size(self):
        rows = [_row(demo="t.mvd"), _row(demo="z.mvd", sha256=SHA_A, size_bytes=0)]
        for r in rows:
            r["class"] = "TRAIN"
        rows[0]["sha256"], rows[0]["size_bytes"] = "abc", 10  # too-short sha
        self.assertEqual(set(c.validate_provenance(rows)), {"t.mvd", "z.mvd"})

    def test_dedupe_keeps_one_canonical_train_per_sha(self):
        # same bytes under two names -> keep the lexicographically-first, demote the rest
        rows = [_row(demo="b_twin.mvd", sha256=SHA_A), _row(demo="a_orig.mvd", sha256=SHA_A),
                _row(demo="c_unique.mvd", sha256=SHA_B)]
        for r in rows:
            r["class"] = "TRAIN"
        n = c.dedupe_train_by_sha(rows)
        self.assertEqual(n, 1)
        kept = sorted(r["demo"] for r in rows if r["class"] == "TRAIN")
        self.assertEqual(kept, ["a_orig.mvd", "c_unique.mvd"])  # a_orig canonical
        demoted = next(r for r in rows if r["class"] == "EXCLUDED")
        self.assertIn("duplicate_content_sha (== a_orig.mvd)", demoted["reason"])


class CommittedManifestInvariantTest(unittest.TestCase):
    """The committed manifest is the training foundation; lock its safety invariants."""

    @classmethod
    def setUpClass(cls):
        cls.man = json.loads(MANIFEST.read_text())
        cls.rows = cls.man["demos"]
        cls.train = [r for r in cls.rows if r["class"] == "TRAIN"]

    def test_schema_is_v3(self):
        self.assertEqual(self.man["schema"], "komodobots.human_4on4_dm3_mvd_manifest.v3")

    def test_counts_match_rows(self):
        self.assertEqual(self.man["counts"]["train"], len(self.train))
        self.assertEqual(self.man["counts"]["scanned"], len(self.rows))

    def test_every_row_has_a_content_lock(self):
        unlocked = [r["demo"] for r in self.rows if not r.get("sha256")]
        self.assertEqual(unlocked, [], "rows missing a content lock")
        self.assertEqual(self.man["provenance"]["rows_with_lock"], len(self.rows))

    def test_provenance_records_the_parser_binary(self):
        # gate item 2: provenance must record the parser that produced the selection fields.
        parser = self.man["provenance"].get("parser")
        self.assertIsInstance(parser, dict, "provenance.parser missing")
        self.assertRegex(parser.get("sha256") or "", r"^[0-9a-f]{64}$")

    def test_train_rows_are_real_4on4_dm3_with_valid_lock(self):
        tm = self.man["team_min"]
        for r in self.train:
            self.assertEqual(r["map"], c.DM3_TITLE, r["demo"])
            self.assertEqual(len(r["teams"]), 2, r["demo"])
            teamset = {(t or "").strip().lower() for t in r["teams"]}
            self.assertNotEqual(teamset, {"red", "blue"}, r["demo"])
            self.assertGreaterEqual(r["active_players"], tm, r["demo"])
            self.assertRegex(r["sha256"], r"^[0-9a-f]{64}$")
            self.assertIsInstance(r["size_bytes"], int)
            self.assertGreater(r["size_bytes"], 0, r["demo"])

    def test_no_bot_or_trick_contamination_in_train(self):
        for r in self.train:
            low = r["demo"].lower()
            for bad in ("milton", "trick", "_bot", "frogbot", "leap"):
                self.assertNotIn(bad, low, "%s contains %r" % (r["demo"], bad))

    def test_unique_demo_and_path_identities(self):
        demos = [r["demo"] for r in self.rows]
        paths = [r["path"] for r in self.rows]
        self.assertEqual(len(demos), len(set(demos)), "duplicate demo basenames")
        self.assertEqual(len(paths), len(set(paths)), "duplicate paths")

    def test_train_content_hashes_are_unique(self):
        # the foundational invariant: no two TRAIN rows share bytes (split-by-demo leakage guard)
        shas = [r["sha256"] for r in self.train]
        self.assertEqual(len(shas), len(set(shas)), "duplicate sha256 across TRAIN rows")

    def test_reclassify_reproduces_committed_labels(self):
        # the full selection (classify_row + dedupe) is a stable function of the recorded fields
        rebuilt = [c.classify_row(dict(r), self.man["team_min"]) for r in self.rows]
        c.dedupe_train_by_sha(rebuilt)
        for orig, got in zip(self.rows, rebuilt):
            self.assertEqual(got["class"], orig["class"], orig["demo"])


if __name__ == "__main__":
    unittest.main()
