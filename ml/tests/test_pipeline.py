"""ml/ tests — run by the NON-GATING ml-tests.yml CI (installs requirements first).

Split into:
  * dependency-free tests (Welford, parity-of-imports) — always run,
  * DuckDB/pyarrow smoke tests — skipped if those deps are absent, so the file is
    importable even in the stdlib-only environment (it just skips the heavy cases).
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ML = HERE.parent
REPO_ROOT = ML.parent
sys.path.insert(0, str(ML / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import normalize_fit as NF   # noqa: E402  (dependency-free core)

CATALOG_DIR = REPO_ROOT / "data" / "catalog"
FIXTURE_DIR = REPO_ROOT / "data" / "fixtures" / "dm3_milton_211436"
STATS = CATALOG_DIR / "normalization_stats.template.json"

_HAVE_DUCKDB = importlib.util.find_spec("duckdb") is not None
_HAVE_PYARROW = importlib.util.find_spec("pyarrow") is not None


class TestWelford(unittest.TestCase):
    def test_mean_std(self):
        w = NF.fit_feature([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
        self.assertAlmostEqual(w.mean, 5.0, places=9)
        self.assertAlmostEqual(w.std, 2.0, places=9)  # population std (ddof=0)
        self.assertEqual((w.lo, w.hi), (2.0, 9.0))

    def test_chan_merge_matches_single_pass(self):
        data = [1.0, 2.0, 3.0, 10.0, 20.0, 30.0, 7.0]
        full = NF.fit_feature(data)
        a = NF.fit_feature(data[:3])
        b = NF.fit_feature(data[3:])
        merged = a.merge(b)
        self.assertAlmostEqual(merged.mean, full.mean, places=9)
        self.assertAlmostEqual(merged.std, full.std, places=9)
        self.assertEqual(merged.n, full.n)

    def test_specs_emit_valid_methods(self):
        w = NF.fit_feature([1.0, 2.0, 3.0])
        self.assertEqual(w.zscore_spec()["method"], "zscore")
        self.assertEqual(w.minmax_spec(clip=[0, 10])["method"], "minmax")


class TestParityImport(unittest.TestCase):
    def test_ml_imports_shared_in_tree_features(self):
        # the parity guarantee: ml/ uses the SAME transforms as the in-tree path
        from features import transforms as T
        self.assertAlmostEqual(T.minmax(1499.0, -984.0, 2048.0), 2483.0 / 3032.0, places=9)


@unittest.skipUnless(_HAVE_DUCKDB and _HAVE_PYARROW, "duckdb/pyarrow not installed")
class TestBuildFeaturesSmoke(unittest.TestCase):
    def test_emits_parquet_and_pit_join(self):
        import build_features as BF
        norm = json.loads(STATS.read_text(encoding="utf-8"))
        rows = BF.build_actor_features(FIXTURE_DIR, norm)
        self.assertEqual(len(rows), 8)            # 8 actors
        self.assertTrue(all("pos_x_n" in r for r in rows))
        # Milton holds quad in the snapshot
        milton = next(r for r in rows if r["actor"] == "Milton")
        self.assertEqual(milton["has_quad"], 1)

        with tempfile.TemporaryDirectory() as d:
            out = BF.emit_parquet(rows, Path(d) / "shard.parquet")
            import pyarrow.parquet as pq
            tbl = pq.read_table(out)
            self.assertEqual(tbl.num_rows, 8)

        con, _ = __import__("catalog_load").build(CATALOG_DIR, FIXTURE_DIR)
        pit = BF.pit_join_demo(con, FIXTURE_DIR)
        self.assertEqual(len(pit), 9)             # 9 frags in the sample window
        # ASOF must attach a weapon picked at-or-before each frag (no future leak)
        for t, killer, victim, weapon, picked_at in pit:
            if picked_at is not None:
                self.assertLessEqual(picked_at, t)


if __name__ == "__main__":
    unittest.main()
