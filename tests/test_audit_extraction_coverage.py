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
                  "frag_events", "damage_events", "teams", "actor_visibility",
                  "audio_cues", "region_control_timeline"):
            self.assertIn(t, schema)
        # constraint lines must NOT leak in as columns
        self.assertNotIn("PRIMARY", schema["player_ticks"])
        self.assertIn("weapon", schema["player_ticks"])
        # the multi-col-per-line AABB row is split correctly
        self.assertEqual(
            {"x_min", "x_max", "y_min", "y_max", "z_min", "z_max"} & set(schema["maps"]),
            {"x_min", "x_max", "y_min", "y_max", "z_min", "z_max"},
        )

    def test_mvd_etl_populates_omniscient_world(self):
        etl = audit.parse_etl_inserts(audit.ETL_MVD)
        self.assertIn("player_ticks", etl)
        self.assertIn("actions", etl)
        # T4: the MVD ETL now populates the omniscient world (was a GAP through T3).
        self.assertIn("actor_ticks", etl)
        for t in ("item_events", "frag_events", "teams"):
            self.assertIn(t, etl, f"MVD ETL should populate {t} (T4)")
        # T5: the MVD ETL also populates the era-gated per-hit damage stream.
        self.assertIn("damage_events", etl, "MVD ETL should populate damage_events (T5)")

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

    def test_registry_captures_mixedcase_and_digit_columns(self):
        # source tokens whose column carries uppercase/digits must not be dropped
        refs = audit.parse_registry_sources(audit.REGISTRY_YAML)
        self.assertIn("region_control_timeline.teamA_control", refs)
        self.assertIn("audio_cues.intensity0", refs)


class TestClassification(unittest.TestCase):
    def test_known_gaps_classify_gap(self):
        # After T4 the actor_ticks state + resources are extracted; the GAPs that REMAIN are the
        # ego armor-skin / active-weapon columns (no honest source) and the T8 derived layers.
        for table, col in [
            ("player_ticks", "armor_type"), ("player_ticks", "weapon"),
            ("actor_ticks", "weapon"),
            ("actor_visibility", "is_visible"), ("audio_cues", "src_type"),
        ]:
            self.assertEqual(audit.classify_column(table, col)[0], audit.GAP,
                             f"{table}.{col} should be GAP")

    def test_t4_actor_world_extracted(self):
        # T4: omniscient actor_ticks state + resources + armor_type flip GAP -> extracted.
        for col in ("ox", "alive", "team_id", "health", "armor", "armor_type"):
            self.assertEqual(audit.classify_column("actor_ticks", col)[0], audit.EXTRACTED,
                             f"actor_ticks.{col} should be extracted (T4)")
        self.assertEqual(audit.classify_column("frag_events", "killer_id")[0], audit.EXTRACTED)
        self.assertEqual(audit.classify_column("teams", "name")[0], audit.EXTRACTED)

    def test_t5_damage_events_extracted(self):
        # T5: damage_events columns + the demos.damage_available era-gate classify extracted (G3 closed).
        for col in ("attacker_id", "victim_id", "weapon", "damage", "is_splash", "is_env"):
            self.assertEqual(audit.classify_column("damage_events", col)[0], audit.EXTRACTED,
                             f"damage_events.{col} should be extracted (T5)")
        self.assertEqual(audit.classify_column("demos", "damage_available")[0], audit.EXTRACTED)

    def test_t6_ammo_powerup_extracted(self):
        # T6: ammo + powerup-remaining source columns classify extracted on BOTH tables (G4 closed).
        for col in ("shells", "nails", "rockets", "cells", "quad_rem", "pent_rem", "ring_rem"):
            self.assertEqual(audit.classify_column("player_ticks", col)[0], audit.EXTRACTED,
                             f"player_ticks.{col} should be extracted (T6)")
            self.assertEqual(audit.classify_column("actor_ticks", col)[0], audit.EXTRACTED,
                             f"actor_ticks.{col} should be extracted (T6)")

    def test_known_extracted_derived_excluded(self):
        self.assertEqual(audit.classify_column("player_ticks", "ox")[0], audit.EXTRACTED)
        # T3: MVD health/armor event stream now populates these (GAP -> extracted)
        self.assertEqual(audit.classify_column("player_ticks", "health")[0], audit.EXTRACTED)
        self.assertEqual(audit.classify_column("player_ticks", "armor")[0], audit.EXTRACTED)
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
