"""Tests for the catalog FRESHNESS guard (validate_catalog.validate_freshness, #315).

Anti-recurrence test for the staleness incident: a gitignored/regenerable catalog
built BEFORE the actor_ticks-population code (PR #296) shipped with player_ticks full
but actor_ticks EMPTY, silently breaking the all-player (agent_observation) analysis.
The guard must FAIL exactly that state and PASS a fresh build.

Pure stdlib; runs under `python -m unittest`. Follows the komodobots convention:
scripts/ on sys.path, modules imported top-level. Builds a tiny in-memory catalog
from the committed synthetic-demo helper (no .qwd corpus needed in CI).
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
# scripts/ for the modules under test; HERE (tests/) so the sibling test helper imports
# under both `pytest` and plain `python -m unittest tests.test_catalog_freshness`.
for _p in (str(SCRIPTS), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import catalog_load            # noqa: E402
import catalog_etl_qwd as etl  # noqa: E402
import validate_catalog as V   # noqa: E402

# reuse the committed observed-others synthetic demo so the fresh build has BOTH the
# self ego rows and real observed-other rows in actor_ticks.
from test_catalog_etl_qwd import _synthetic_demo_with_observed  # noqa: E402

REPO_ROOT = HERE.parent
CATALOG_DIR = REPO_ROOT / "data" / "catalog"


class TestCatalogFreshnessGuard(unittest.TestCase):
    def setUp(self):
        self.con = catalog_load.connect()
        catalog_load.load_maps(self.con, CATALOG_DIR / "maps.seed.json")
        self.map_id = self.con.execute(
            "SELECT map_id FROM maps WHERE name='dm3'").fetchone()[0]

    def _build_fresh(self):
        """A tiny but FRESH catalog: real per-tick rows + populated actor_ticks."""
        ins = etl.insert_demo(self.con, self.map_id, _synthetic_demo_with_observed(), "train")
        return ins

    def test_fresh_build_has_actor_ticks_and_passes_guard(self):
        # (a) a fresh build populates actor_ticks (self ego + observed others) ...
        ins = self._build_fresh()
        (n_pt,) = self.con.execute("SELECT COUNT(*) FROM player_ticks").fetchone()
        (n_actor,) = self.con.execute("SELECT COUNT(*) FROM actor_ticks").fetchone()
        self.assertGreater(n_pt, 0)
        self.assertGreater(n_actor, 0, "fresh build must populate actor_ticks")
        self.assertGreaterEqual(n_actor, n_pt,
                                "self ego row is inserted for every player_ticks row")
        self.assertGreater(ins["actor_ticks"], 0)
        # ... and the freshness guard is silent on it.
        self.assertEqual(V.validate_freshness(self.con), [])

    def test_guard_flags_synthetically_emptied_actor_ticks(self):
        # (b) simulate a pre-#296 STALE artifact: per-tick layer full, actor_ticks wiped.
        self._build_fresh()
        self.con.execute("DELETE FROM actor_ticks")
        (n_pt,) = self.con.execute("SELECT COUNT(*) FROM player_ticks").fetchone()
        (n_actor,) = self.con.execute("SELECT COUNT(*) FROM actor_ticks").fetchone()
        self.assertGreater(n_pt, 0)
        self.assertEqual(n_actor, 0)
        errs = V.validate_freshness(self.con)
        self.assertTrue(any("freshness" in e and "STALE" in e for e in errs), errs)
        # the aggregate validate() must also surface it (this is the build/validation path).
        self.assertTrue(
            any("freshness" in e for e in V.validate(self.con, raise_on_error=False)), errs)
        # and it raises through the loud-failure path.
        with self.assertRaises(V.CatalogError):
            V.validate(self.con, raise_on_error=True)

    def test_static_only_catalog_is_not_flagged_as_stale(self):
        # A legitimately-empty catalog (static spine only: NO player_ticks, NO actor_ticks)
        # is NOT a staleness signal and must pass the guard. Guarding against false-positives
        # that would block a valid spine-only build.
        (n_pt,) = self.con.execute("SELECT COUNT(*) FROM player_ticks").fetchone()
        (n_actor,) = self.con.execute("SELECT COUNT(*) FROM actor_ticks").fetchone()
        self.assertEqual(n_pt, 0)
        self.assertEqual(n_actor, 0)
        self.assertEqual(V.validate_freshness(self.con), [])

    def test_missing_actor_ticks_table_is_not_flagged(self):
        # An OLDER schema with no actor_ticks table at all must not crash the guard nor
        # be reported as stale (it is a different/older catalog shape, not a stale #296 build).
        self._build_fresh()
        self.con.execute("DROP TABLE actor_ticks")
        self.assertEqual(V.validate_freshness(self.con), [])


if __name__ == "__main__":
    unittest.main()
