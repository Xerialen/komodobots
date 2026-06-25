"""Unit tests for scripts/audit_extraction_coverage.py — the T1 coverage audit (#389).

Pure stdlib + PyYAML (already a repo dep). Loads NO database, hits NO network. Exercises:
  * the schema/ETL/registry text parsers on the real in-repo artifacts,
  * the per-column classification verdicts (the load-bearing extracted/derived/excluded/GAP),
  * the self-check gate (asserts the known GAP fields classify GAP, no UNCLASSIFIED column),
  * report generation is deterministic and contains the summary + GAP roll-up.
"""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import audit_extraction_coverage as audit  # noqa: E402


class TestParsers(unittest.TestCase):
    def test_schema_parse_has_4on4_tables(self):
        schema = audit.parse_schema_tables(audit.SCHEMA_SQL)
        for t in ("player_ticks", "actor_ticks", "actions", "item_events",
                  "frag_events", "teams", "actor_visibility", "audio_cues",
                  "region_control_timeline"):
            self.assertIn(t, schema)
        # constraint lines must NOT leak in as columns
        self.assertNotIn("PRIMARY", schema["player_ticks"])
        self.assertIn("weapon", schema["player_ticks"])
        # the multi-col-per-line AABB row is split correctly
        self.assertEqual(
            {"x_min", "x_max", "y_min", "y_max", "z_min", "z_max"} & set(schema["maps"]),
            {"x_min", "x_max", "y_min", "y_max", "z_min", "z_max"},
        )

    def test_mvd_etl_populates_no_actor_ticks(self):
        etl = audit.parse_etl_inserts(audit.ETL_MVD)
        self.assertIn("player_ticks", etl)
        self.assertIn("actions", etl)
        # The core "we extract only movement" finding: MVD ETL writes NO actor_ticks.
        self.assertNotIn("actor_ticks", etl)

    def test_qwd_etl_populates_actor_ticks(self):
        etl = audit.parse_etl_inserts(audit.ETL_QWD)
        self.assertIn("actor_ticks", etl)
        # QWD writes weapon=NULL (the column is in the INSERT list even though it's None)
        self.assertIn("weapon", etl["player_ticks"])

    def test_registry_references_resource_gaps(self):
        refs = audit.parse_registry_sources(audit.REGISTRY_YAML)
        # registry v5 DEFINES features over the unpopulated resource columns
        self.assertIn("player_ticks.health", refs)
        self.assertIn("player_ticks.armor", refs)


class TestClassification(unittest.TestCase):
    def test_known_gaps_classify_gap(self):
        for table, col in [
            ("player_ticks", "health"), ("player_ticks", "armor"),
            ("player_ticks", "armor_type"), ("player_ticks", "weapon"),
            ("actor_ticks", "health"), ("actor_ticks", "team_id"),
            ("actor_visibility", "is_visible"), ("audio_cues", "src_type"),
        ]:
            self.assertEqual(audit.classify_column(table, col)[0], audit.GAP,
                             f"{table}.{col} should be GAP")

    def test_known_extracted_derived_excluded(self):
        self.assertEqual(audit.classify_column("player_ticks", "ox")[0], audit.EXTRACTED)
        self.assertEqual(audit.classify_column("player_ticks", "hspeed")[0], audit.DERIVED)
        self.assertEqual(audit.classify_column("player_ticks", "waterlevel")[0], audit.EXCLUDED)

    def test_sibling_columns_inherit_family_verdict(self):
        # axis siblings inherit without a per-axis CLASSIFY entry
        self.assertEqual(audit.classify_column("audio_cues", "src_y")[0], audit.GAP)
        self.assertEqual(audit.classify_column("actor_visibility", "last_seen_vz")[0], audit.GAP)
        self.assertEqual(audit.classify_column("maps", "z_max")[0], audit.EXCLUDED)

    def test_no_unclassified_columns(self):
        schema = audit.parse_schema_tables(audit.SCHEMA_SQL)
        bad = [f"{t}.{c}" for t, cols in schema.items() for c in cols
               if audit.classify_column(t, c)[0] == "UNCLASSIFIED"]
        self.assertEqual(bad, [], f"UNCLASSIFIED columns must get a verdict: {bad}")

    def test_classify_keys_reference_real_columns(self):
        schema = audit.parse_schema_tables(audit.SCHEMA_SQL)
        valid = {f"{t}.{c}" for t, cols in schema.items() for c in cols}
        stale = [k for k in audit.CLASSIFY if k not in valid]
        self.assertEqual(stale, [], f"CLASSIFY has stale keys: {stale}")


class TestReport(unittest.TestCase):
    def test_report_is_deterministic_and_complete(self):
        schema = audit.parse_schema_tables(audit.SCHEMA_SQL)
        etl_mvd = audit.parse_etl_inserts(audit.ETL_MVD)
        etl_qwd = audit.parse_etl_inserts(audit.ETL_QWD)
        refs = audit.parse_registry_sources(audit.REGISTRY_YAML)
        r1, c1 = audit.build_report(schema, etl_mvd, etl_qwd, refs)
        r2, c2 = audit.build_report(schema, etl_mvd, etl_qwd, refs)
        self.assertEqual(r1, r2, "report generation must be deterministic")
        self.assertEqual(c1, c2)
        self.assertGreater(c1[audit.GAP], 0)
        self.assertIn("GENERATED FILE", r1)
        self.assertIn("python3 scripts/audit_extraction_coverage.py", r1)
        self.assertIn("## Summary", r1)
        self.assertEqual(len(audit.PLAN_GAPS), 6)

    def test_self_check_entrypoint_passes(self):
        # the runnable --check gate must not raise
        audit.run_self_checks()


if __name__ == "__main__":
    unittest.main()
