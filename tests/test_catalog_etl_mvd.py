"""Unit tests for scripts/catalog_etl_mvd.py — the MVD action-recovery ETL.

Pure stdlib, runnable on bare python3.12 (no qw-analyze binary, no BSP, no numpy/torch).
Exercises the recovery logic on small synthetic pos-streams:
  * angle16 -> degree conversion,
  * sidemove SIGN = -sign(yaw_rate) flips with the turn direction, gated to the bhop regime,
  * jump emitted on a geometric onground TRUE->FALSE transition, NOT on single-tick flicker,
  * the schema-version guard hard-fails on a schema-21-shaped dict,
  * the manifest reader keeps only EXPLICIT class=='TRAIN' rows and carries their content lock,
  * a sha256 mismatch against the manifest is flagged (provenance verify), and
  * every idm row is held out of training (is_interp=True) until per-head weights exist.
"""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import catalog_etl_mvd as etl  # noqa: E402


class _FakeProber:
    """Stand-in for OngroundProber: returns onground from a caller-supplied per-call sequence,
    so the recovery logic is testable without a BSP. Honors the vz>MAXGROUNDSPEED early-out so
    that branch is exercised too."""

    def __init__(self, flags):
        self._flags = list(flags)
        self._i = 0

    def onground(self, origin, vz):
        g = self._flags[self._i]
        self._i += 1
        if vz > etl.MAXGROUNDSPEED_DEFAULT:
            return False
        return g


class Angle16Test(unittest.TestCase):
    def test_angle16_to_deg(self):
        # 16384 angle16 == 90 deg (quarter turn); 0 == 0; -32768 == -180.
        self.assertAlmostEqual(16384 * etl.ANGLE16_TO_DEG, 90.0, places=4)
        self.assertAlmostEqual(0 * etl.ANGLE16_TO_DEG, 0.0, places=6)
        self.assertAlmostEqual(-32768 * etl.ANGLE16_TO_DEG, -180.0, places=4)

    def test_player_frames_converts_angles_and_keeps_velocity(self):
        pos = {
            "t": [0, 13, 26],
            "x": [10.0, 11.0, 12.0], "y": [0.0, 0.0, 0.0], "z": [-88.0, -88.0, -88.0],
            "vx": [300.0, 305.0, 310.0], "vy": [5.0, 6.0, 7.0], "vz": [0.0, 1.0, 2.0],
            "vya": [16384, 16384, 16384],  # == 90 deg
            "vp": [0, 0, 0],
        }
        frames = etl._player_frames(pos)
        self.assertEqual(len(frames), 3)
        self.assertEqual(frames[0]["msec"], 13)
        self.assertEqual(frames[2]["msec"], 13)  # last tick reuses prior delta
        self.assertAlmostEqual(frames[0]["yaw"], 90.0, places=3)
        # velocity is used directly (analyzer already finite-differenced it)
        self.assertEqual(frames[0]["velocity"], [300.0, 5.0, 0.0])


class StrafeSignTest(unittest.TestCase):
    """sign(sidemove) == -sign(yaw_rate), gated to the >=STRAFE_SIGN_GATE bhop regime."""

    def _seg(self, yaws_deg, hspeed):
        """Build a frame segment at fixed hspeed with a yaw track; onground all False."""
        v = [hspeed, 0.0, 0.0]  # vx so hypot == hspeed
        return [{"origin": [float(i), 0.0, -88.0], "velocity": list(v),
                 "yaw": float(y), "pitch": 0.0, "msec": 13} for i, y in enumerate(yaws_deg)]

    def test_left_turn_gives_positive_sidemove_in_bhop(self):
        # increasing yaw (turning left, +yaw_rate) -> sidemove negative; decreasing -> positive.
        seg = self._seg([0.0, 0.0, 5.0, 10.0, 15.0], hspeed=500.0)  # >gate, rising yaw
        og = [False] * len(seg)
        jump = [False] * len(seg)
        ep = etl._pack_episode(seg, og, jump, 0)
        rows = ep["frames"]
        # tick0: prev_yaw None -> yr 0 -> no strafe label. ticks with +yaw_rate -> side<0.
        turning = [r for r in rows if r["side"] != 0.0]
        self.assertTrue(turning, "expected at least one strafing tick")
        for r in turning:
            self.assertLess(r["side"], 0.0)  # +yaw_rate -> -sidemove (sign still recovered)
            self.assertTrue(r["is_interp"])   # interim hold-out: idm rows excluded until per-head weights
            self.assertAlmostEqual(r["confidence"], etl.STRAFE_CONF)
            self.assertEqual(abs(r["side"]), etl.SIDEMOVE_MAG)  # full-magnitude prior

    def test_right_turn_flips_sign(self):
        seg = self._seg([20.0, 15.0, 10.0, 5.0, 0.0], hspeed=500.0)  # falling yaw -> -yaw_rate
        og = [False] * len(seg)
        ep = etl._pack_episode(seg, og, [False] * len(seg), 0)
        turning = [r for r in ep["frames"] if r["side"] != 0.0]
        self.assertTrue(turning)
        for r in turning:
            self.assertGreater(r["side"], 0.0)  # -yaw_rate -> +sidemove

    def test_below_gate_is_marked_interp(self):
        # same turn but slow (below STRAFE_SIGN_GATE) -> strafe sign unreliable -> is_interp.
        seg = self._seg([0.0, 5.0, 10.0, 15.0], hspeed=200.0)  # < 400
        og = [False] * len(seg)
        ep = etl._pack_episode(seg, og, [False] * len(seg), 0)
        turning = [r for r in ep["frames"] if r["side"] != 0.0]
        self.assertTrue(turning)
        for r in turning:
            self.assertTrue(r["is_interp"])  # below gate -> excluded from training
            self.assertLess(r["confidence"], etl.STRAFE_CONF)

    def test_forwardmove_prior_and_lossless_aim(self):
        seg = self._seg([0.0, 5.0, 10.0], hspeed=500.0)
        ep = etl._pack_episode(seg, [False] * len(seg), [False] * len(seg), 0)
        for r in ep["frames"]:
            self.assertEqual(r["fwd"], etl.FORWARDMOVE_PRIOR)  # forwardmove genuinely lost
            self.assertEqual(r["cmd_yaw"], r["yaw"])           # aim lossless: cmd == view
            self.assertEqual(r["cmd_pitch"], r["pitch"])


class JumpRecoveryTest(unittest.TestCase):
    def _frames(self, vzs):
        return [{"origin": [float(i), 0.0, -88.0], "velocity": [400.0, 0.0, vz],
                 "yaw": 0.0, "pitch": 0.0, "msec": 13} for i, vz in enumerate(vzs)]

    def test_jump_on_true_to_false_transition(self):
        # grounded, grounded, then leaves ground with upward vz and stays airborne.
        og = [True, True, False, False, False]
        vzs = [0.0, 0.0, 200.0, 150.0, 100.0]
        frames = self._frames(vzs)
        jump = etl._recover_jumps(og, frames)
        # press attributed to the LAST grounded tick (index 1).
        self.assertEqual(jump, [False, True, False, False, False])

    def test_no_jump_on_single_tick_flicker(self):
        # a single airborne tick between grounded ticks (flicker) must NOT register a jump
        # (JUMP_MIN_AIR=2 requires a sustained airborne run).
        og = [True, True, False, True, True]
        vzs = [0.0, 0.0, 200.0, 0.0, 0.0]
        frames = self._frames(vzs)
        jump = etl._recover_jumps(og, frames)
        self.assertEqual(sum(jump), 0)

    def test_no_jump_on_ledge_fall_without_upward_intent(self):
        # leaves ground but falling (vz<=0) -> a ledge step-off, not a jump.
        og = [True, True, False, False, False]
        vzs = [0.0, 0.0, -50.0, -80.0, -120.0]
        frames = self._frames(vzs)
        jump = etl._recover_jumps(og, frames)
        self.assertEqual(sum(jump), 0)

    def test_jump_encodes_buttons_and_upmove(self):
        seg = [{"origin": [float(i), 0.0, -88.0], "velocity": [400.0, 0.0, 0.0],
                "yaw": 0.0, "pitch": 0.0, "msec": 13} for i in range(4)]
        og = [True, True, False, False]
        jump = [False, True, False, False]
        ep = etl._pack_episode(seg, og, jump, 0)
        r = ep["frames"][1]
        self.assertTrue(r["buttons"] & etl.BUTTON_JUMP)
        self.assertEqual(r["up"], etl.SIDEMOVE_MAG)
        self.assertEqual(ep["frames"][0]["buttons"], 0)


class OngroundProberEarlyOutTest(unittest.TestCase):
    def test_recover_onground_uses_geometry_and_vz_earlyout(self):
        # _recover_onground calls prober.onground(origin, vz). The fake honors the
        # vz>MAXGROUNDSPEED early-out: a fast-rising frame is forced airborne even when the
        # geometry flag says grounded.
        frames = [
            {"origin": [0.0, 0.0, 0.0], "velocity": [0.0, 0.0, 0.0], "yaw": 0, "pitch": 0, "msec": 13},
            {"origin": [0.0, 0.0, 0.0], "velocity": [0.0, 0.0, 300.0], "yaw": 0, "pitch": 0, "msec": 13},
        ]
        prober = _FakeProber([True, True])  # geometry says grounded both ticks
        og = etl._recover_onground(frames, prober)
        self.assertEqual(og[0], True)
        self.assertEqual(og[1], False)  # vz 300 > 180 -> forced airborne


class SchemaGuardTest(unittest.TestCase):
    def test_schema21_shaped_dict_hard_fails(self):
        # schema 21: pos has only {t,x,y,z,li} -> must raise.
        bad = {"schemaVersion": 21,
               "streams": {"players": [{"pos": {"t": [0], "x": [0], "y": [0], "z": [0], "li": [0]}}]}}
        with self.assertRaises(ValueError) as cm:
            etl._validate_analysis(bad, "demo21.mvd")
        self.assertIn("schema", str(cm.exception).lower())

    def test_schema33_missing_velocity_fields_hard_fails(self):
        bad = {"schemaVersion": 33,
               "streams": {"players": [{"pos": {"t": [0], "x": [0], "y": [0], "z": [0], "li": [0]}}]}}
        with self.assertRaises(ValueError) as cm:
            etl._validate_analysis(bad, "demo33.mvd")
        self.assertIn("vya", str(cm.exception))

    def test_valid_schema33_passes(self):
        good = {"schemaVersion": 33,
                "streams": {"players": [{"pos": {
                    "t": [0], "x": [0], "y": [0], "z": [0], "li": [0],
                    "vp": [0], "vya": [0], "vx": [0], "vy": [0], "vz": [0]}}]}}
        etl._validate_analysis(good, "demo_ok.mvd")  # must not raise


class ManifestTest(unittest.TestCase):
    def _load(self, manifest):
        import json
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(manifest, fh)
            p = Path(fh.name)
        try:
            return etl.load_manifest(p)
        finally:
            p.unlink()

    def test_explicit_train_only_and_carries_content_lock(self):
        sha = "a" * 64
        manifest = {"schema": "v3", "demos": [
            {"path": "/a/train1.mvd", "class": "TRAIN", "sha256": sha, "size_bytes": 10},
            {"path": "/a/holdout.mvd", "class": "HOLDOUT", "sha256": sha, "size_bytes": 10},
            {"path": "/a/train2.mvd", "classification": "TRAIN", "sha256": sha.upper(), "size_bytes": 20},
        ]}
        out = self._load(manifest)
        self.assertEqual([e["path"] for e in out], ["/a/train1.mvd", "/a/train2.mvd"])
        self.assertEqual(out[0]["sha256"], sha)            # carried
        self.assertEqual(out[1]["sha256"], sha)            # normalized to lowercase
        self.assertEqual(out[0]["size_bytes"], 10)

    def test_missing_class_is_rejected_not_defaulted_to_train(self):
        # the old bug: a row with no class was silently treated as TRAIN. It must now be REJECTED.
        out = self._load({"demos": [{"abspath": "/a/noclass.mvd", "sha256": "b" * 64, "size_bytes": 5}]})
        self.assertEqual(out, [])


class ProvenanceVerifyTest(unittest.TestCase):
    def test_extract_demo_flags_sha_mismatch(self):
        import tempfile
        with tempfile.NamedTemporaryFile("wb", suffix=".mvd", delete=False) as fh:
            fh.write(b"not a real demo")
            p = fh.name
        try:
            r = etl.extract_demo(p, "/nonexistent-qwa", "/nonexistent-bsp", expected_sha256="f" * 64)
        finally:
            os.unlink(p)
        self.assertFalse(r["ok"])
        self.assertTrue(r.get("sha_mismatch"))
        self.assertIn("SHA_MISMATCH", r["error"])


class HoldoutInvariantTest(unittest.TestCase):
    """Anti-poisoning: until per-head weights exist, EVERY idm row is held out of training."""

    def _seg(self, yaws_deg, hspeed):
        v = [hspeed, 0.0, 0.0]
        return [{"origin": [float(i), 0.0, -88.0], "velocity": list(v),
                 "yaw": float(y), "pitch": 0.0, "msec": 13} for i, y in enumerate(yaws_deg)]

    def test_all_rows_held_out_regardless_of_gate(self):
        for hspeed in (200.0, 500.0):  # below and above the strafe-sign gate
            seg = self._seg([0.0, 5.0, 10.0, 15.0], hspeed)
            ep = etl._pack_episode(seg, [False] * len(seg), [False] * len(seg), 0)
            self.assertTrue(all(r["is_interp"] for r in ep["frames"]),
                            "every idm row must be is_interp=True (no move head trains)")


class SplitTest(unittest.TestCase):
    """split_for_sha: per-demo, deterministic, content-stable, roughly 70/15/15."""

    def test_deterministic_and_valid_label(self):
        sha = "deadbeef" + "0" * 56
        self.assertEqual(etl.split_for_sha(sha), etl.split_for_sha(sha))  # same demo -> same split
        self.assertIn(etl.split_for_sha(sha), ("train", "val", "test"))

    def test_handles_missing_or_short_sha(self):
        # a demo with no/blank sha must still get a valid label, not crash
        self.assertIn(etl.split_for_sha(None), ("train", "val", "test"))
        self.assertIn(etl.split_for_sha(""), ("train", "val", "test"))

    def test_distribution_is_a_real_partition(self):
        from hashlib import sha256
        counts = {"train": 0, "val": 0, "test": 0}
        for i in range(3000):
            counts[etl.split_for_sha(sha256(str(i).encode()).hexdigest())] += 1
        # generous bounds: confirm a ~70/15/15 spread, not everything in one bucket
        self.assertGreater(counts["train"], 1800)   # ~2100 expected
        self.assertGreater(counts["val"], 250)       # ~450 expected
        self.assertGreater(counts["test"], 250)      # ~450 expected


class StreamingInsertTest(unittest.TestCase):
    """build() streams each demo to SQLite as its parse finishes and never holds all demos'
    frames in RAM at once (the bug task #9 fixes). Control-flow test: extract/insert/static-spine
    are faked, so it needs no qw-analyze, no BSP, no catalog fixture."""

    def test_build_inserts_incrementally_and_bounds_memory(self):
        import hashlib
        import sqlite3
        import catalog_etl_mvd as etl2

        # Each fake demo carries a heavy "payload" that counts itself live on creation and
        # dead on GC. Accumulate-then-insert (the old code) holds all N payloads at once
        # (peak == N); streaming inserts+drops each as it arrives (peak stays ~1).
        live = {"now": 0, "peak": 0}

        class _Payload:
            def __init__(self):
                live["now"] += 1
                live["peak"] = max(live["peak"], live["now"])

            def __del__(self):
                live["now"] -= 1

        N = 60
        entries = [{"path": "/x/d%02d.mvd" % i,
                    "sha256": hashlib.sha256(b"%d" % i).hexdigest(), "size_bytes": 10}
                   for i in range(N)]

        def fake_static_build(catalog_dir, fixture_dir=None, db_path=None):
            con = sqlite3.connect(":memory:")
            con.execute("CREATE TABLE maps (map_id INTEGER PRIMARY KEY, name TEXT)")
            con.execute("INSERT INTO maps (map_id, name) VALUES (1, 'dm3')")
            return con, {"fake_spine": True}

        def fake_extract(path, qw_analyze, bsp_path, sha):
            return {"ok": True, "demo": Path(path).name, "sha256": sha,
                    "n_players": 1, "_payload": _Payload()}

        inserted = []

        def fake_insert(con, map_id, rec, split, demo_id):
            inserted.append((rec["demo"], split))     # records the row; does NOT retain _payload
            return {"player_ticks": 5, "actions": 5}

        res = None
        saved = (etl2.catalog_load.build, etl2.load_manifest, etl2.extract_demo, etl2.insert_demo)
        etl2.catalog_load.build = fake_static_build
        etl2.load_manifest = lambda _p: entries
        etl2.extract_demo = fake_extract
        etl2.insert_demo = fake_insert
        try:
            res = etl2.build(Path("/nope"), Path("/nope.json"), ":memory:", "/bsp", "/qa", workers=1)
        finally:
            (etl2.catalog_load.build, etl2.load_manifest,
             etl2.extract_demo, etl2.insert_demo) = saved
            if res is not None and res.get("con") is not None:
                res["con"].close()

        self.assertEqual(res["summary"]["demos_loaded"], N)      # every demo streamed in
        self.assertEqual(len(inserted), N)                       # insert called once per demo
        self.assertLessEqual(
            live["peak"], 3,
            "streaming should hold ~1 demo's frames at a time, not all %d (peak was %d)"
            % (N, live["peak"]))
        labels = {sp for _, sp in inserted}
        self.assertTrue(labels <= {"train", "val", "test"})      # split assigned per demo by sha
        self.assertGreater(len(labels), 1)                       # a real partition, not all-one
        # the split build() passed for each demo IS split_for_sha(that demo's sha) — provenance
        sha_of = {Path(e["path"]).name: e["sha256"] for e in entries}
        for demo, split in inserted:
            self.assertEqual(split, etl2.split_for_sha(sha_of[demo]))
        # build summary records the versioned, reconstructable split contract
        self.assertEqual(res["summary"]["split_policy"], "group_by_demo_sha256_bucket_v1")
        self.assertEqual(res["summary"]["split_spec"]["thresholds"], {"train": 0.70, "val": 0.85})


class SplitPolicyEmittedTest(unittest.TestCase):
    """The catalog is self-describing: a real insert writes the VERSIONED sha-bucket policy into
    episodes.split_policy (not the QWD positional 'group_by_demo_id'), so a generated catalog
    records which assignment produced `split`. Uses the real schema; no qw-analyze/BSP needed."""

    def test_insert_demo_writes_versioned_sha_split_policy(self):
        import sqlite3
        con = sqlite3.connect(":memory:")
        con.executescript((REPO_ROOT / "scripts" / "catalog_schema.sql").read_text())
        con.execute("INSERT INTO maps (map_id, name, x_min, x_max, y_min, y_max, z_min, z_max, "
                    "diagonal) VALUES (1, 'dm3', 0, 1, 0, 1, 0, 1, 1.0)")
        seg = [{"origin": [float(i), 0.0, -88.0], "velocity": [450.0, 0.0, 0.0],
                "yaw": float(i), "pitch": 0.0, "msec": 13} for i in range(4)]
        ep = etl._pack_episode(seg, [False] * 4, [False] * 4, 0)
        sha = "abc12345" + "0" * 56
        rec = {"demo": "d.mvd", "sha256": sha, "n_players": 1,
               "players": [{"name": "p1", "team": 1, "episodes": [ep]}]}
        split = etl.split_for_sha(sha)
        etl.insert_demo(con, 1, rec, split, 1)
        rows = con.execute("SELECT DISTINCT split, split_policy FROM episodes").fetchall()
        con.close()
        self.assertEqual(etl.SPLIT_POLICY, "group_by_demo_sha256_bucket_v1")
        self.assertEqual(rows, [(split, etl.SPLIT_POLICY)])      # emitted == versioned sha policy


class FailedRunArtifactTest(unittest.TestCase):
    """Fail-closed artifact: a fatal mid-run abort (provenance sha_mismatch) after at least one
    demo has already streamed+committed must leave NO catalog at the canonical --db path — the
    streaming build writes to a `.partial` sibling and only renames to --db on success."""

    def test_fatal_midstream_failure_leaves_no_final_db(self):
        import sqlite3
        import tempfile
        import catalog_etl_mvd as etl2

        d = Path(tempfile.mkdtemp())
        final_db = d / "out.sqlite"
        qa = d / "qw-analyze"; qa.write_text("#!/bin/true\n"); qa.chmod(0o755)
        bsp = d / "dm3.bsp"; bsp.write_bytes(b"x")
        manifest = d / "m.json"; manifest.write_text("[]")  # load_manifest is faked below

        good_sha, bad_sha = "a" * 64, "b" * 64
        entries = [{"path": "/x/good.mvd", "sha256": good_sha, "size_bytes": 10},
                   {"path": "/x/bad.mvd", "sha256": bad_sha, "size_bytes": 10}]
        seg = [{"origin": [float(i), 0.0, -88.0], "velocity": [450.0, 0.0, 0.0],
                "yaw": float(i), "pitch": 0.0, "msec": 13} for i in range(4)]
        ep = etl2._pack_episode(seg, [False] * 4, [False] * 4, 0)

        created = []

        def fake_static_build(catalog_dir, fixture_dir=None, db_path=None):
            con = sqlite3.connect(db_path)  # REAL file at the .partial path -> proves a partial exists
            con.executescript((REPO_ROOT / "scripts" / "catalog_schema.sql").read_text())
            con.execute("INSERT INTO maps (map_id, name, x_min, x_max, y_min, y_max, z_min, z_max, "
                        "diagonal) VALUES (1, 'dm3', 0, 1, 0, 1, 0, 1, 1.0)")
            created.append(con)
            return con, {"fake": True}

        def fake_extract(path, qw_analyze, bsp_path, sha):
            if sha == bad_sha:  # the second demo fails provenance AFTER the first has committed
                return {"ok": False, "demo": "bad.mvd", "sha_mismatch": True,
                        "error": "SHA_MISMATCH manifest=%s on-disk=deadbeef" % bad_sha}
            return {"ok": True, "demo": "good.mvd", "sha256": good_sha, "n_players": 1,
                    "players": [{"name": "p1", "team": 1, "episodes": [ep]}]}

        saved = (etl2.catalog_load.build, etl2.load_manifest, etl2.extract_demo)
        etl2.catalog_load.build = fake_static_build
        etl2.load_manifest = lambda _p: entries
        etl2.extract_demo = fake_extract
        try:
            rc = etl2.main(["--catalog-dir", str(d), "--manifest", str(manifest),
                            "--db", str(final_db), "--qw-analyze", str(qa), "--bsp", str(bsp),
                            "--workers", "1"])
        finally:
            (etl2.catalog_load.build, etl2.load_manifest, etl2.extract_demo) = saved

        self.assertEqual(rc, 3)  # fatal provenance abort
        # the build CLOSED its connection on the fatal path — this is the Windows fix (an open
        # handle there blocks _purge of the .partial with WinError 32); checkable on any OS.
        with self.assertRaises(sqlite3.ProgrammingError):
            created[0].execute("SELECT 1")
        self.assertFalse(final_db.exists(),
                         "a fatal mid-run failure must NOT leave a catalog at the canonical --db")
        # and no partial / sidecars left lingering at the canonical path either
        leftovers = sorted(p.name for p in d.glob("out.sqlite*"))
        self.assertEqual(leftovers, [], "no partial DB or sidecars may survive a failed run")

    def test_successful_run_publishes_db_and_leaves_no_partial(self):
        # symmetric guard: a clean run renames the .partial to the canonical --db (so a broken
        # publish can't silently ship a missing catalog) and leaves no .partial behind.
        import sqlite3
        import tempfile
        import catalog_etl_mvd as etl2

        d = Path(tempfile.mkdtemp())
        final_db = d / "out.sqlite"
        qa = d / "qw-analyze"; qa.write_text("#!/bin/true\n"); qa.chmod(0o755)
        bsp = d / "dm3.bsp"; bsp.write_bytes(b"x")
        manifest = d / "m.json"; manifest.write_text("[]")

        sha = "c" * 64
        entries = [{"path": "/x/ok.mvd", "sha256": sha, "size_bytes": 10}]
        seg = [{"origin": [float(i), 0.0, -88.0], "velocity": [450.0, 0.0, 0.0],
                "yaw": float(i), "pitch": 0.0, "msec": 13} for i in range(4)]
        ep = etl2._pack_episode(seg, [False] * 4, [False] * 4, 0)

        def fake_static_build(catalog_dir, fixture_dir=None, db_path=None):
            con = sqlite3.connect(db_path)
            con.executescript((REPO_ROOT / "scripts" / "catalog_schema.sql").read_text())
            con.execute("INSERT INTO maps (map_id, name, x_min, x_max, y_min, y_max, z_min, z_max, "
                        "diagonal) VALUES (1, 'dm3', 0, 1, 0, 1, 0, 1, 1.0)")
            return con, {"fake": True}

        def fake_extract(path, qw_analyze, bsp_path, _sha):
            return {"ok": True, "demo": "ok.mvd", "sha256": sha, "n_players": 1,
                    "players": [{"name": "p1", "team": 1, "episodes": [ep]}]}

        saved = (etl2.catalog_load.build, etl2.load_manifest, etl2.extract_demo)
        etl2.catalog_load.build = fake_static_build
        etl2.load_manifest = lambda _p: entries
        etl2.extract_demo = fake_extract
        try:
            rc = etl2.main(["--catalog-dir", str(d), "--manifest", str(manifest),
                            "--db", str(final_db), "--qw-analyze", str(qa), "--bsp", str(bsp),
                            "--workers", "1"])
        finally:
            (etl2.catalog_load.build, etl2.load_manifest, etl2.extract_demo) = saved

        self.assertEqual(rc, 0)
        self.assertTrue(final_db.exists(), "a clean run must publish the catalog at --db")
        self.assertFalse((d / "out.sqlite.partial").exists(), "the .partial must be renamed away")

    def test_unexpected_nonruntime_error_also_purges_partial(self):
        # not just the provenance RuntimeError: ANY build failure after the .partial exists (e.g. a
        # sqlite OperationalError mid-insert) must fail closed and leave no out.sqlite* behind.
        import sqlite3
        import tempfile
        import catalog_etl_mvd as etl2

        d = Path(tempfile.mkdtemp())
        final_db = d / "out.sqlite"
        qa = d / "qw-analyze"; qa.write_text("#!/bin/true\n"); qa.chmod(0o755)
        bsp = d / "dm3.bsp"; bsp.write_bytes(b"x")
        manifest = d / "m.json"; manifest.write_text("[]")

        entries = [{"path": "/x/d%d.mvd" % i, "sha256": chr(97 + i) * 64, "size_bytes": 10}
                   for i in range(2)]
        seg = [{"origin": [float(i), 0.0, -88.0], "velocity": [450.0, 0.0, 0.0],
                "yaw": float(i), "pitch": 0.0, "msec": 13} for i in range(4)]
        ep = etl2._pack_episode(seg, [False] * 4, [False] * 4, 0)

        def fake_static_build(catalog_dir, fixture_dir=None, db_path=None):
            con = sqlite3.connect(db_path)  # creates the real .partial file
            con.executescript((REPO_ROOT / "scripts" / "catalog_schema.sql").read_text())
            con.execute("INSERT INTO maps (map_id, name, x_min, x_max, y_min, y_max, z_min, z_max, "
                        "diagonal) VALUES (1, 'dm3', 0, 1, 0, 1, 0, 1, 1.0)")
            return con, {"fake": True}

        def fake_extract(path, qw_analyze, bsp_path, sha):
            return {"ok": True, "demo": Path(path).name, "sha256": sha, "n_players": 1,
                    "players": [{"name": "p1", "team": 1, "episodes": [ep]}]}

        calls = {"n": 0}
        real_insert = etl2.insert_demo

        def flaky_insert(con, map_id, rec, split, demo_id):
            calls["n"] += 1
            if calls["n"] == 2:  # blow up AFTER the first demo has streamed+committed
                raise sqlite3.OperationalError("disk I/O error (simulated)")
            return real_insert(con, map_id, rec, split, demo_id)

        saved = (etl2.catalog_load.build, etl2.load_manifest, etl2.extract_demo, etl2.insert_demo)
        etl2.catalog_load.build = fake_static_build
        etl2.load_manifest = lambda _p: entries
        etl2.extract_demo = fake_extract
        etl2.insert_demo = flaky_insert
        try:
            with self.assertRaises(sqlite3.OperationalError):  # unexpected error surfaces (purged first)
                etl2.main(["--catalog-dir", str(d), "--manifest", str(manifest),
                           "--db", str(final_db), "--qw-analyze", str(qa), "--bsp", str(bsp),
                           "--workers", "1"])
        finally:
            (etl2.catalog_load.build, etl2.load_manifest,
             etl2.extract_demo, etl2.insert_demo) = saved

        leftovers = sorted(p.name for p in d.glob("out.sqlite*"))
        self.assertEqual(leftovers, [], "a non-RuntimeError build failure must also purge the partial")

    def test_existing_canonical_db_survives_failed_rebuild(self):
        # fail-closed must protect the NEW artifact, not destroy the EXISTING one: a failed/empty
        # rebuild must leave the previous known-good canonical catalog intact (it is built into a
        # .partial and only os.replace'd on success), not delete it up front.
        import sqlite3
        import tempfile
        import catalog_etl_mvd as etl2

        d = Path(tempfile.mkdtemp())
        final_db = d / "out.sqlite"
        pre = sqlite3.connect(final_db)            # a pre-existing verified catalog with a sentinel
        pre.execute("CREATE TABLE sentinel (v TEXT)")
        pre.execute("INSERT INTO sentinel VALUES ('GOOD')")
        pre.commit()
        pre.close()
        qa = d / "qw-analyze"; qa.write_text("#!/bin/true\n"); qa.chmod(0o755)
        bsp = d / "dm3.bsp"; bsp.write_bytes(b"x")
        manifest = d / "m.json"; manifest.write_text("[]")
        sha = "f" * 64
        entries = [{"path": "/x/empty.mvd", "sha256": sha, "size_bytes": 10}]

        def fake_static_build(catalog_dir, fixture_dir=None, db_path=None):
            con = sqlite3.connect(db_path)         # builds into the .partial, NOT the canonical db
            con.executescript((REPO_ROOT / "scripts" / "catalog_schema.sql").read_text())
            con.execute("INSERT INTO maps (map_id, name, x_min, x_max, y_min, y_max, z_min, z_max, "
                        "diagonal) VALUES (1, 'dm3', 0, 1, 0, 1, 0, 1, 1.0)")
            return con, {"fake": True}

        def fake_extract(path, qw_analyze, bsp_path, _sha):
            return {"ok": True, "demo": "empty.mvd", "sha256": sha, "n_players": 0, "players": []}

        saved = (etl2.catalog_load.build, etl2.load_manifest, etl2.extract_demo)
        etl2.catalog_load.build = fake_static_build
        etl2.load_manifest = lambda _p: entries
        etl2.extract_demo = fake_extract
        try:
            rc = etl2.main(["--catalog-dir", str(d), "--manifest", str(manifest),
                            "--db", str(final_db), "--qw-analyze", str(qa), "--bsp", str(bsp),
                            "--workers", "1"])
        finally:
            (etl2.catalog_load.build, etl2.load_manifest, etl2.extract_demo) = saved

        self.assertEqual(rc, 2)  # empty-gate failure
        self.assertTrue(final_db.exists(),
                        "a failed rebuild must PRESERVE the existing canonical catalog")
        chk = sqlite3.connect(final_db)
        val = chk.execute("SELECT v FROM sentinel").fetchone()[0]   # still the OLD db, untouched
        chk.close()
        self.assertEqual(val, "GOOD")
        self.assertFalse((d / "out.sqlite.partial").exists())       # only the partial was purged

    # shared fakes for the sidecar tests: a faked static spine (real schema at the .partial path)
    # + a one-demo extract that yields a non-empty catalog so the run reaches the publish step.
    def _sidecar_fixture(self, d):
        import sqlite3
        import catalog_etl_mvd as etl2
        sha = "9" * 64
        entries = [{"path": "/x/ok.mvd", "sha256": sha, "size_bytes": 10}]
        seg = [{"origin": [float(i), 0.0, -88.0], "velocity": [450.0, 0.0, 0.0],
                "yaw": float(i), "pitch": 0.0, "msec": 13} for i in range(4)]
        ep = etl2._pack_episode(seg, [False] * 4, [False] * 4, 0)

        def fake_static_build(catalog_dir, fixture_dir=None, db_path=None):
            con = sqlite3.connect(db_path)
            con.executescript((REPO_ROOT / "scripts" / "catalog_schema.sql").read_text())
            con.execute("INSERT INTO maps (map_id, name, x_min, x_max, y_min, y_max, z_min, z_max, "
                        "diagonal) VALUES (1, 'dm3', 0, 1, 0, 1, 0, 1, 1.0)")
            return con, {"fake": True}

        def fake_extract(path, qw_analyze, bsp_path, _sha):
            return {"ok": True, "demo": "ok.mvd", "sha256": sha, "n_players": 1,
                    "players": [{"name": "p1", "team": 1, "episodes": [ep]}]}

        qa = d / "qw-analyze"; qa.write_text("#!/bin/true\n"); qa.chmod(0o755)
        bsp = d / "dm3.bsp"; bsp.write_bytes(b"x")
        manifest = d / "m.json"; manifest.write_text("[]")
        argv = ["--catalog-dir", str(d), "--manifest", str(manifest), "--db", str(d / "out.sqlite"),
                "--qw-analyze", str(qa), "--bsp", str(bsp), "--workers", "1"]
        return fake_static_build, fake_extract, entries, argv

    @staticmethod
    def _make_stale_wal(db_path):
        # Leave a REAL, valid, uncheckpointed out.sqlite-wal on disk (as a crashed prior run would):
        # a child process writes in WAL mode with autocheckpoint off and exits WITHOUT closing, so
        # the -wal persists, unowned, with a committed-but-uncheckpointed row table old_t('OLD').
        import subprocess
        import sys
        child = ("import sqlite3, os\n"
                 "c = sqlite3.connect(%r)\n"
                 "c.execute('PRAGMA journal_mode=WAL')\n"
                 "c.execute('PRAGMA wal_autocheckpoint=0')\n"
                 "c.execute('CREATE TABLE old_t(v)')\n"
                 "c.execute(\"INSERT INTO old_t VALUES ('OLD')\")\n"
                 "c.commit()\n"
                 "os._exit(0)\n") % str(db_path)
        subprocess.run([sys.executable, "-c", child], check=True)

    def test_successful_rebuild_neutralizes_real_stale_wal(self):
        # a real leftover valid -wal WOULD shadow a freshly replaced main (a reader would see the
        # OLD data). A successful rebuild must neutralize it so the NEW catalog is what readers get.
        import sqlite3
        import tempfile
        import catalog_etl_mvd as etl2

        d = Path(tempfile.mkdtemp())
        final_db = d / "out.sqlite"
        self._make_stale_wal(final_db)
        self.assertTrue((d / "out.sqlite-wal").exists())   # a real valid stale WAL is present

        fsb, fex, entries, argv = self._sidecar_fixture(d)
        saved = (etl2.catalog_load.build, etl2.load_manifest, etl2.extract_demo)
        etl2.catalog_load.build = fsb
        etl2.load_manifest = lambda _p: entries
        etl2.extract_demo = fex
        try:
            rc = etl2.main(argv)
        finally:
            (etl2.catalog_load.build, etl2.load_manifest, etl2.extract_demo) = saved

        self.assertEqual(rc, 0)
        self.assertFalse((d / "out.sqlite-wal").exists(), "the stale WAL must be cleared on publish")
        fresh = sqlite3.connect(final_db)
        names = {r[0] for r in fresh.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        fresh.close()
        self.assertIn("maps", names)             # the NEW catalog is what readers see
        self.assertNotIn("old_t", names)         # the stale WAL no longer shadows the new db

    def test_blocked_sidecar_cleanup_fails_closed(self):
        # if a canonical sidecar cannot be cleared before publish (locked / a live reader), the
        # run must FAIL CLOSED (rc2, no publish), not silently publish a shadowed catalog.
        import pathlib
        import sqlite3
        import tempfile
        import catalog_etl_mvd as etl2

        d = Path(tempfile.mkdtemp())
        final_db = d / "out.sqlite"
        old = sqlite3.connect(final_db)
        old.execute("CREATE TABLE old_marker (v TEXT)")
        old.commit()
        old.close()
        (d / "out.sqlite-shm").write_bytes(b"locked shm")   # a -shm that refuses removal (no -wal,
                                                            # so no checkpoint path is taken)
        fsb, fex, entries, argv = self._sidecar_fixture(d)
        real_unlink = pathlib.Path.unlink

        def locked_unlink(self, *a, **k):
            if str(self) == str(final_db) + "-shm":
                raise PermissionError("WinError 32 (simulated): file in use")
            return real_unlink(self, *a, **k)

        saved = (etl2.catalog_load.build, etl2.load_manifest, etl2.extract_demo)
        etl2.catalog_load.build = fsb
        etl2.load_manifest = lambda _p: entries
        etl2.extract_demo = fex
        pathlib.Path.unlink = locked_unlink
        try:
            rc = etl2.main(argv)
        finally:
            pathlib.Path.unlink = real_unlink
            (etl2.catalog_load.build, etl2.load_manifest, etl2.extract_demo) = saved

        self.assertEqual(rc, 2)  # fail closed — do not publish a catalog a stale sidecar could shadow
        fresh = sqlite3.connect(final_db)
        names = {r[0] for r in fresh.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        fresh.close()
        self.assertIn("old_marker", names)       # still the OLD db — the new build was NOT published
        self.assertNotIn("maps", names)

    def test_replace_failure_preserves_old_db_losslessly(self):
        # if os.replace fails AFTER the old WAL was folded into its main file, the old catalog must
        # still hold every committed row (the fold is lossless), and the new build is not published.
        import sqlite3
        import tempfile
        import catalog_etl_mvd as etl2

        d = Path(tempfile.mkdtemp())
        final_db = d / "out.sqlite"
        self._make_stale_wal(final_db)           # old committed-but-uncheckpointed row old_t('OLD')

        fsb, fex, entries, argv = self._sidecar_fixture(d)
        real_replace = etl2.os.replace

        def boom_replace(src, dst):
            raise OSError("EXDEV (simulated): cannot replace canonical db")

        saved = (etl2.catalog_load.build, etl2.load_manifest, etl2.extract_demo)
        etl2.catalog_load.build = fsb
        etl2.load_manifest = lambda _p: entries
        etl2.extract_demo = fex
        etl2.os.replace = boom_replace
        try:
            rc = etl2.main(argv)
        finally:
            etl2.os.replace = real_replace
            (etl2.catalog_load.build, etl2.load_manifest, etl2.extract_demo) = saved

        self.assertEqual(rc, 2)  # fail closed
        self.assertTrue(final_db.exists(), "the old canonical db must be preserved on a failed publish")
        fresh = sqlite3.connect(final_db)
        names = {r[0] for r in fresh.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        old_rows = [r[0] for r in fresh.execute("SELECT v FROM old_t")] if "old_t" in names else []
        fresh.close()
        self.assertIn("old_t", names)            # the old table survived ...
        self.assertEqual(old_rows, ["OLD"])      # ... WITH its committed row (WAL fold was lossless)
        self.assertNotIn("maps", names)          # the new build was NOT published
        self.assertFalse((d / "out.sqlite.partial").exists())   # only the new partial was purged


class DemoIdDeterminismTest(unittest.TestCase):
    """demo_id must be a stable function of content identity (sha-rank), NOT the parallel
    completion / insertion order — the trainer keys its held-out-demo split on demo_id, so two
    rebuilds of the same manifest+bytes in different orders must map each demo to the same id."""

    def _build_and_read(self, entries):
        import sqlite3
        import catalog_etl_mvd as etl2

        seg = [{"origin": [float(i), 0.0, -88.0], "velocity": [450.0, 0.0, 0.0],
                "yaw": float(i), "pitch": 0.0, "msec": 13} for i in range(4)]
        ep = etl2._pack_episode(seg, [False] * 4, [False] * 4, 0)

        def fake_static_build(catalog_dir, fixture_dir=None, db_path=None):
            con = sqlite3.connect(":memory:")
            con.executescript((REPO_ROOT / "scripts" / "catalog_schema.sql").read_text())
            con.execute("INSERT INTO maps (map_id, name, x_min, x_max, y_min, y_max, z_min, z_max, "
                        "diagonal) VALUES (1, 'dm3', 0, 1, 0, 1, 0, 1, 1.0)")
            return con, {"fake": True}

        def fake_extract(path, qw_analyze, bsp_path, sha):
            return {"ok": True, "demo": Path(path).name, "sha256": sha, "n_players": 1,
                    "players": [{"name": "p1", "team": 1, "episodes": [ep]}]}

        saved = (etl2.catalog_load.build, etl2.load_manifest, etl2.extract_demo)
        etl2.catalog_load.build = fake_static_build
        etl2.load_manifest = lambda _p: entries
        etl2.extract_demo = fake_extract
        try:
            res = etl2.build(Path("/x"), Path("/m.json"), ":memory:", "/bsp", "/qa", workers=1)
            return dict(res["con"].execute("SELECT sha256, demo_id FROM demos").fetchall())
        finally:
            (etl2.catalog_load.build, etl2.load_manifest, etl2.extract_demo) = saved

    def test_demo_id_is_order_independent(self):
        entries = [{"path": "/x/d%d.mvd" % i, "sha256": chr(97 + i) * 64, "size_bytes": 10}
                   for i in range(5)]
        forward = self._build_and_read(entries)
        reverse = self._build_and_read(list(reversed(entries)))
        self.assertEqual(forward, reverse,  # same demo -> same id regardless of insert order
                         "demo_id must come from sha-rank, not insertion order")
        # and it is exactly the sha-rank (1..N over sorted shas)
        expect = {sha: i + 1 for i, sha in enumerate(sorted(e["sha256"] for e in entries))}
        self.assertEqual(forward, expect)


class SummaryDbPathTest(unittest.TestCase):
    """A successful run's printed summary must point at the CANONICAL --db (the published
    artifact), not the internal .partial that build() wrote to and main() renamed away."""

    def test_summary_db_is_canonical_after_success(self):
        import contextlib
        import io
        import json as _json
        import sqlite3
        import tempfile
        import catalog_etl_mvd as etl2

        d = Path(tempfile.mkdtemp())
        final_db = d / "out.sqlite"
        qa = d / "qw-analyze"; qa.write_text("#!/bin/true\n"); qa.chmod(0o755)
        bsp = d / "dm3.bsp"; bsp.write_bytes(b"x")
        manifest = d / "m.json"; manifest.write_text("[]")
        sha = "e" * 64
        entries = [{"path": "/x/ok.mvd", "sha256": sha, "size_bytes": 10}]
        seg = [{"origin": [float(i), 0.0, -88.0], "velocity": [450.0, 0.0, 0.0],
                "yaw": float(i), "pitch": 0.0, "msec": 13} for i in range(4)]
        ep = etl2._pack_episode(seg, [False] * 4, [False] * 4, 0)

        def fake_static_build(catalog_dir, fixture_dir=None, db_path=None):
            con = sqlite3.connect(db_path)
            con.executescript((REPO_ROOT / "scripts" / "catalog_schema.sql").read_text())
            con.execute("INSERT INTO maps (map_id, name, x_min, x_max, y_min, y_max, z_min, z_max, "
                        "diagonal) VALUES (1, 'dm3', 0, 1, 0, 1, 0, 1, 1.0)")
            return con, {"fake": True}

        def fake_extract(path, qw_analyze, bsp_path, _sha):
            return {"ok": True, "demo": "ok.mvd", "sha256": sha, "n_players": 1,
                    "players": [{"name": "p1", "team": 1, "episodes": [ep]}]}

        saved = (etl2.catalog_load.build, etl2.load_manifest, etl2.extract_demo)
        etl2.catalog_load.build = fake_static_build
        etl2.load_manifest = lambda _p: entries
        etl2.extract_demo = fake_extract
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = etl2.main(["--catalog-dir", str(d), "--manifest", str(manifest),
                                "--db", str(final_db), "--qw-analyze", str(qa), "--bsp", str(bsp),
                                "--workers", "1"])
        finally:
            (etl2.catalog_load.build, etl2.load_manifest, etl2.extract_demo) = saved

        self.assertEqual(rc, 0)
        summary = _json.loads(buf.getvalue())
        self.assertEqual(summary["db"], str(final_db))      # canonical, not .partial
        self.assertTrue(Path(summary["db"]).exists())        # the recorded path actually exists
        self.assertFalse((d / "out.sqlite.partial").exists())


if __name__ == "__main__":
    unittest.main()
