"""Unit tests for scripts/audit_extraction_coverage.py — the T1 coverage audit (#389).

Pure stdlib (the feature registry is JSON since T1.1 #418). Loads NO database, hits NO network. Exercises:
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
        refs = audit.parse_registry_sources(audit.REGISTRY_JSON)
        # registry v5 DEFINES features over the unpopulated resource columns
        self.assertIn("player_ticks.health", refs)
        self.assertIn("player_ticks.armor", refs)

    def test_registry_captures_mixedcase_and_digit_columns(self):
        # source tokens whose column carries uppercase/digits must not be dropped
        refs = audit.parse_registry_sources(audit.REGISTRY_JSON)
        self.assertIn("region_control_timeline.teamA_control", refs)
        self.assertIn("audio_cues.intensity0", refs)


class TestClassification(unittest.TestCase):
    def test_known_gaps_classify_gap(self):
        # After T4 the actor_ticks state + resources are extracted; T8 #396 flips actor_visibility.*
        # GAP -> DERIVED. The GAPs that REMAIN: the active-weapon columns (STAT_ACTIVEWEAPON is parsed
        # by the mvd-reader but not surfaced -> WS-1 analyzer-fitness), player_ticks.armor_type (an
        # ETL-wiring gap; the `at` stream exists), and audio_cues.* (the one remaining T8 gap).
        for table, col in [
            ("player_ticks", "armor_type"), ("player_ticks", "weapon"),
            ("actor_ticks", "weapon"),
            ("audio_cues", "src_type"),
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

    def test_t7_geometry_regime_legphase_derived(self):
        # T7: [G] geometry + [R] regime + leg-phase columns classify DERIVED on BOTH tables (G5
        # closed). They are computed (dm3.bsp traces + kinematics + route_legs), not raw decoder
        # fields — DERIVED, the same honest verdict as onground/hspeed.
        for col in ("floor_height", "over_void", "wall_dist", "ledge_ahead", "ramp_normal_z",
                    "regime", "leg_phase"):
            self.assertEqual(audit.classify_column("player_ticks", col)[0], audit.DERIVED,
                             f"player_ticks.{col} should be DERIVED (T7)")
            self.assertEqual(audit.classify_column("actor_ticks", col)[0], audit.DERIVED,
                             f"actor_ticks.{col} should be DERIVED (T7)")

    def test_t8_actor_visibility_derived(self):
        # T8 #396: the POMDP actor_visibility.* columns classify DERIVED (FOV + dm3.bsp hull-0 LOS
        # raycast + carried-forward belief, derived offline — not raw decoder fields). audio_cues
        # stays the one remaining T8 derived gap (out of #396 scope).
        for col in ("is_visible", "pvs_visible", "in_fov", "los_clear", "vis_angle_source",
                    "last_seen_ox", "time_since_seen_s", "seen_ever"):
            self.assertEqual(audit.classify_column("actor_visibility", col)[0], audit.DERIVED,
                             f"actor_visibility.{col} should be DERIVED (T8)")
        self.assertEqual(audit.classify_column("audio_cues", "src_type")[0], audit.GAP)

    def test_t9_training_connection_noted_without_new_gap(self):
        # T9 #397 (capstone): the report's scoping section now NOTES the training-connection
        # template (dataset_spec reader + worked consumer + train-only refit) is delivered. It is
        # a downstream consumer deliverable, so it must add NO schema column / change no verdict
        # (the counts stay what the schema dictates) and must NOT trip the G4/G5 absent guards.
        schema = audit.parse_schema_tables(audit.SCHEMA_SQL)
        etl_mvd = audit.parse_etl_inserts(audit.ETL_MVD)
        etl_qwd = audit.parse_etl_inserts(audit.ETL_QWD)
        refs = audit.parse_registry_sources(audit.REGISTRY_JSON)
        report, _ = audit.build_report(schema, etl_mvd, etl_qwd, refs)
        self.assertIn("Training connection (T9 #397", report)
        self.assertIn("dataset_spec.yaml", report)
        self.assertIn("assemble_obs_template.py", report)
        # the T9 note must not reintroduce a G4/G5 "absent from the schema" contradiction.
        self.assertFalse(audit._report_claims_g4_absent(report))
        self.assertFalse(audit._report_claims_g5_absent(report))

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
        # T8 #396: the last_seen_* belief siblings inherit DERIVED from last_seen_ox (was GAP).
        self.assertEqual(audit.classify_column("actor_visibility", "last_seen_vz")[0], audit.DERIVED)
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
        refs = audit.parse_registry_sources(audit.REGISTRY_JSON)
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

    def test_g4_absent_guard_detects_contradiction(self):
        # #404 P1 anti-recurrence: with T6 ammo/powerup columns extracted, the report prose
        # must NOT also claim those G4 columns are "absent from the schema". The detector
        # returns False on the corrected report and True on the stale/contradictory phrasing.
        schema = audit.parse_schema_tables(audit.SCHEMA_SQL)
        etl_mvd = audit.parse_etl_inserts(audit.ETL_MVD)
        etl_qwd = audit.parse_etl_inserts(audit.ETL_QWD)
        refs = audit.parse_registry_sources(audit.REGISTRY_JSON)
        report, _ = audit.build_report(schema, etl_mvd, etl_qwd, refs)

        # T6 columns really are extracted, so the contradiction would be live if the prose said absent.
        for col in ("shells", "nails", "rockets", "cells", "quad_rem", "pent_rem", "ring_rem"):
            self.assertEqual(audit.classify_column("player_ticks", col)[0], audit.EXTRACTED)

        # The corrected report must not trip the guard.
        self.assertFalse(audit._report_claims_g4_absent(report),
                         "corrected report must not assert G4 ammo/powerup columns are absent")

        # Inject the old stale clause; the guard MUST fire (robust to wording, matches the claim).
        stale = report + ("\nThe ammo/powerup source columns (G4) are still absent from the "
                          "schema entirely, so they do not appear as columns here.\n")
        self.assertTrue(audit._report_claims_g4_absent(stale),
                        "guard must detect the G4-absent contradiction in stale prose")

    def test_g5_absent_guard_detects_contradiction(self):
        # T7 #395 anti-recurrence (mirrors G4): with the [G]/[R]/leg-phase columns now DERIVED
        # (schema-present), the report prose must NOT claim those G5 columns are "absent from the
        # schema". The detector is False on the corrected report, True on the stale phrasing.
        schema = audit.parse_schema_tables(audit.SCHEMA_SQL)
        etl_mvd = audit.parse_etl_inserts(audit.ETL_MVD)
        etl_qwd = audit.parse_etl_inserts(audit.ETL_QWD)
        refs = audit.parse_registry_sources(audit.REGISTRY_JSON)
        report, _ = audit.build_report(schema, etl_mvd, etl_qwd, refs)

        # The T7 columns really are schema-present (DERIVED), so the contradiction would be live.
        for col in ("floor_height", "over_void", "wall_dist", "ledge_ahead", "ramp_normal_z",
                    "regime", "leg_phase"):
            self.assertEqual(audit.classify_column("player_ticks", col)[0], audit.DERIVED)

        self.assertFalse(audit._report_claims_g5_absent(report),
                         "corrected report must not assert G5 [G]/[R]/leg-phase columns are absent")

        stale = report + ("\nOnly the [G]/[R]/leg-phase columns (G5) remain absent from the "
                          "schema entirely, so they do not appear as columns here.\n")
        self.assertTrue(audit._report_claims_g5_absent(stale),
                        "guard must detect the G5-absent contradiction in stale prose")

    def test_schema33_provenance_guard_detects_stale_report(self):
        # #437 anti-recurrence: WS-0 reconciled the inventory to MVD schema v35 (state.weapon_active
        # / mvd.hidden.usercmd are present), so the generated report must NOT still advertise the
        # retired schema-33 provenance. The detector is False on the corrected report, True on stale.
        schema = audit.parse_schema_tables(audit.SCHEMA_SQL)
        etl_mvd = audit.parse_etl_inserts(audit.ETL_MVD)
        etl_qwd = audit.parse_etl_inserts(audit.ETL_QWD)
        refs = audit.parse_registry_sources(audit.REGISTRY_JSON)
        report, _ = audit.build_report(schema, etl_mvd, etl_qwd, refs)

        # The inventory really is v35-based, so a schema-33 mention in the report would be a live
        # contradiction.
        self.assertIn("state.weapon_active", audit.DECODER_INVENTORY)
        self.assertFalse(audit._report_advertises_stale_schema33(report),
                         "corrected v35 report must not advertise retired schema-33 provenance")

        stale = report + ("\nSourced from the committed static reference + qw-analyze schema-33 "
                          "`-include` groups + getStateAt field codes.\n")
        self.assertTrue(audit._report_advertises_stale_schema33(stale),
                        "guard must detect stale schema-33 provenance in the report")


if __name__ == "__main__":
    unittest.main()
