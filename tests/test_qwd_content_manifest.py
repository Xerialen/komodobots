"""Fixture tests for ``tools/qwd_content_manifest``.

Two layers:

* Synthetic byte-exact demos built in-memory (no corpus dependency) that pin the
  core contracts: the true map comes from the network modellist (never the
  filename), spectator/autotrack POVs are ineligible, a self POV is eligible,
  qizmo compression is detected, and truncated input yields an error record
  rather than a crash.

* Optional checks against the labeled corpus, each skipped when its file is
  absent so the suite still runs on a bare checkout.
"""

from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import qwd_content_manifest as qcm
from tools.qwd_usercmd import qwd_usercmd


# ---------------------------------------------------------------------------
# Synthetic demo builder
# ---------------------------------------------------------------------------

def _cstr(s: str) -> bytes:
    return s.encode("latin1") + b"\x00"


def _svc_serverdata(*, protocol: int = 28, gamedir: str = "qw",
                    playernum_raw: int = 0, levelname: str = "Synthetic Map") -> bytes:
    body = bytes([qcm.SVC_SERVERDATA])
    body += struct.pack("<i", protocol)
    body += struct.pack("<i", 1)            # servercount
    body += _cstr(gamedir)
    body += bytes([playernum_raw & 0xFF])   # POV byte path
    body += _cstr(levelname)
    body += struct.pack("<10f", 800, 100, 320, 500, 10, 0.7, 10, 6, 1, 1)  # movevars
    return body


def _svc_modellist(worldmodel: str, *, start_index: int = 0) -> bytes:
    body = bytes([qcm.SVC_MODELLIST, start_index & 0xFF])
    body += _cstr(worldmodel)
    body += _cstr("progs/player.mdl")
    body += b"\x00"        # empty string terminates list
    body += bytes([0])     # continuation marker (0 == done)
    return body


def _svc_updateuserinfo(slot: int, userid: int, userinfo: str) -> bytes:
    return bytes([qcm.SVC_UPDATEUSERINFO, slot & 0xFF]) + struct.pack("<i", userid) + _cstr(userinfo)


def _dem_read(svc_stream: bytes, *, demotime: float = 0.0, seq_prefix: bool = True) -> bytes:
    """Wrap an svc stream as a dem_read record.

    Real POV demos prefix the svc stream with two int32 seqs; mirror that so the
    offset-8 detection path is exercised.
    """
    body = (b"\x01\x00\x00\x00\x02\x00\x00\x00" + svc_stream) if seq_prefix else svc_stream
    header = struct.pack(qwd_usercmd.RECORD_HEADER_FORMAT, demotime, qwd_usercmd.DEM_READ)
    return header + struct.pack("<i", len(body)) + body


def _dem_cmd(demotime: float, *, forward: int, side: int, up: int, yaw: float) -> bytes:
    payload = struct.pack(
        qwd_usercmd.USERCMD_STRUCT_FORMAT,
        13,          # msec
        0.0, yaw, 0.0,
        forward, side, up,
        0,           # buttons
        0,           # impulse
    )
    header = struct.pack(qwd_usercmd.RECORD_HEADER_FORMAT, demotime, qwd_usercmd.DEM_CMD)
    return header + payload + struct.pack(qwd_usercmd.VIEW_ANGLES_FORMAT, 0.0, yaw, 0.0)


def build_demo(
    *,
    worldmodel: str = "maps/dm6.bsp",
    playernum_raw: int = 0,
    levelname: str = "Synthetic Map",
    roster: list[tuple[int, str, str, bool]] | None = None,
    n_cmds: int = 50,
    moving: bool = True,
    yaw_walking: bool = False,
) -> bytes:
    """Build a minimal but byte-exact POV .qwd.

    ``roster`` entries are (slot, name, team, spectator).
    """
    if roster is None:
        roster = [(0, "selfguy", "red", False), (1, "rival", "blue", False)]

    signon = _svc_serverdata(playernum_raw=playernum_raw, levelname=levelname)
    signon += _svc_modellist(worldmodel)
    for slot, name, team, spec in roster:
        ui = f"\\name\\{name}\\team\\{team}"
        if spec:
            ui += "\\*spectator\\1"
        signon += _svc_updateuserinfo(slot, 1000 + slot, ui)

    out = bytearray()
    out += _dem_read(signon, demotime=0.0)
    for i in range(n_cmds):
        t = 0.013 * (i + 1)
        yaw = (i * 90.0) % 360 if yaw_walking else 90.0
        if moving:
            out += _dem_cmd(t, forward=400, side=0, up=0, yaw=yaw)
        else:
            out += _dem_cmd(t, forward=0, side=0, up=0, yaw=yaw)
    return bytes(out)


# ---------------------------------------------------------------------------
# Synthetic-demo tests (no corpus dependency)
# ---------------------------------------------------------------------------

class SyntheticDemoTests(unittest.TestCase):
    def _write(self, data: bytes, name: str) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="qcm_test_"))
        p = tmp / name
        p.write_bytes(data)
        return p

    def test_true_map_comes_from_bytes_not_filename(self) -> None:
        # Filename screams dm3, but the worldmodel in the stream is dm6.
        data = build_demo(worldmodel="maps/dm6.bsp")
        p = self._write(data, "totally_a_dm3_demo.qwd")
        rec = qcm.parse_qwd(p)
        self.assertEqual(rec["errors"], [])
        self.assertEqual(rec["true_map"], "dm6")
        self.assertEqual(rec["protocol"], 28)
        self.assertEqual(rec["level_title"], "Synthetic Map")

    def test_worldmodel_strips_leading_slash(self) -> None:
        data = build_demo(worldmodel="/maps/dm4.bsp")
        p = self._write(data, "x.qwd")
        rec = qcm.parse_qwd(p)
        self.assertEqual(rec["true_map"], "dm4")

    def test_self_pov_eligible(self) -> None:
        data = build_demo(
            worldmodel="maps/dm2.bsp",
            playernum_raw=0,  # not spectator
            roster=[(0, "selfguy", "red", False), (1, "rival", "blue", False)],
            n_cmds=60,
            moving=True,
        )
        p = self._write(data, "self.qwd")
        rec = qcm.parse_qwd(p)
        self.assertEqual(rec["errors"], [])
        self.assertEqual(rec["pov_kind"], "self")
        self.assertFalse(rec["recording_client_spectator"])
        self.assertTrue(rec["has_usercmds"])
        self.assertGreater(rec["movement_cmd_fraction"], 0.2)
        self.assertTrue(rec["self_pov_eligible"])
        self.assertEqual(rec["mode"], "1on1")
        self.assertEqual(rec["player_count"], 2)

    def test_recording_client_spectator_is_ineligible(self) -> None:
        # High bit set on serverdata playernum => recording client is a spectator.
        data = build_demo(playernum_raw=0x80 | 0, moving=True)
        p = self._write(data, "spec.qwd")
        rec = qcm.parse_qwd(p)
        self.assertTrue(rec["recording_client_spectator"])
        self.assertIn(rec["pov_kind"], ("spectator", "autotrack"))
        self.assertFalse(rec["self_pov_eligible"])

    def test_autotrack_cam_name_is_ineligible(self) -> None:
        data = build_demo(
            playernum_raw=0x80,
            roster=[(0, "commentary-cam", "", True), (1, "p1", "red", False),
                    (2, "p2", "blue", False)],
            moving=False,
        )
        p = self._write(data, "autotrack.qwd")
        rec = qcm.parse_qwd(p)
        self.assertEqual(rec["pov_kind"], "autotrack")
        self.assertFalse(rec["self_pov_eligible"])

    def test_slot_spectator_parsed_from_userinfo(self) -> None:
        data = build_demo(
            roster=[(0, "selfguy", "red", False), (1, "rival", "blue", False),
                    (2, "watcher", "", True)],
        )
        p = self._write(data, "withspec.qwd")
        rec = qcm.parse_qwd(p)
        specs = [r for r in rec["roster"] if r["spectator"]]
        self.assertEqual([s["name"] for s in specs], ["watcher"])
        # spectator excluded from active player count
        self.assertEqual(rec["player_count"], 2)
        self.assertEqual(rec["mode"], "1on1")

    def test_non_standard_count_is_ambiguous(self) -> None:
        data = build_demo(
            roster=[(0, "a", "r", False), (1, "b", "r", False), (2, "c", "b", False)],
        )
        p = self._write(data, "three.qwd")
        rec = qcm.parse_qwd(p)
        self.assertEqual(rec["mode"], "ambiguous")
        self.assertIsNotNone(rec["ambiguity_reason"])
        self.assertEqual(rec["player_count"], 3)

    def test_team_counts(self) -> None:
        data = build_demo(
            worldmodel="maps/dm3.bsp",
            roster=[(0, "a", "red", False), (1, "b", "red", False),
                    (2, "c", "blue", False), (3, "d", "blue", False)],
        )
        p = self._write(data, "2on2.qwd")
        rec = qcm.parse_qwd(p)
        self.assertEqual(rec["mode"], "2on2")
        self.assertEqual(rec["team_counts"], {"red": 2, "blue": 2})

    def test_player_count_uses_peak_not_final_roster(self) -> None:
        # A real 4on4 (8 active) where one slot disconnects (empty updateuserinfo)
        # in a later block. player_count/mode must reflect the peak (8 / 4on4),
        # not the final accumulated roster (7 / ambiguous).
        roster8 = [
            (0, "r1", "red"), (1, "r2", "red"), (2, "r3", "red"), (3, "r4", "red"),
            (4, "b1", "blue"), (5, "b2", "blue"), (6, "b3", "blue"), (7, "b4", "blue"),
        ]
        signon = _svc_serverdata(playernum_raw=0, levelname="Peak Map")
        signon += _svc_modellist("maps/dm3.bsp")
        for slot, name, team in roster8:
            signon += _svc_updateuserinfo(slot, 1000 + slot, f"\\name\\{name}\\team\\{team}")
        out = bytearray()
        out += _dem_read(signon, demotime=0.0)
        for i in range(40):
            out += _dem_cmd(0.013 * (i + 1), forward=400, side=0, up=0, yaw=90.0)
        # late disconnect: slot 7 leaves (empty userinfo) in a later dem_read block
        out += _dem_read(_svc_updateuserinfo(7, 1007, ""), demotime=1.0)
        p = self._write(bytes(out), "peak_then_disconnect.qwd")

        rec = qcm.parse_qwd(p)
        self.assertEqual(rec["errors"], [])
        self.assertEqual(rec["player_count"], 8)
        self.assertEqual(rec["mode"], "4on4")
        self.assertEqual(rec["team_counts"], {"red": 4, "blue": 4})
        # the final accumulated roster reflects the disconnect (slot 7 gone)
        final_active = [r for r in rec["roster"] if not r["spectator"] and r["name"]]
        self.assertEqual(len(final_active), 7)

    def test_truncated_returns_error_not_crash(self) -> None:
        full = build_demo(n_cmds=200)
        # Cut inside a later record's body so framing is broken mid-stream.
        truncated = full[: len(full) // 2 + 3]
        p = self._write(truncated, "truncated.qwd")
        # Must not raise.
        rec = qcm.parse_qwd(p)
        self.assertIsInstance(rec, dict)
        self.assertTrue(rec["errors"], "expected a populated errors list")
        # Deterministic: parsing twice yields identical content.
        rec2 = qcm.parse_qwd(p)
        self.assertEqual(rec["errors"], rec2["errors"])

    def test_garbage_header_is_not_a_qwd(self) -> None:
        self.assertFalse(qcm.looks_like_real_qwd(b"\x80\x01\xba\x1f\x57\xc1\xff\xf5" * 4))

    def test_real_demo_sniffs_true(self) -> None:
        data = build_demo()
        self.assertTrue(qcm.looks_like_real_qwd(data))

    def test_missing_file_is_error_record(self) -> None:
        rec = qcm.parse_qwd("/nonexistent/path/to/demo.qwd")
        self.assertTrue(rec["errors"])
        self.assertFalse(rec["self_pov_eligible"])

    def test_cli_emits_json_lines(self) -> None:
        import io
        import json
        from contextlib import redirect_stdout

        p1 = self._write(build_demo(worldmodel="maps/dm2.bsp"), "a.qwd")
        p2 = self._write(build_demo(worldmodel="maps/dm3.bsp"), "b.qwd")
        buf = io.StringIO()
        with redirect_stdout(buf):
            qcm._cli([str(p1), str(p2)])
        lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 2)
        maps = {json.loads(ln)["true_map"] for ln in lines}
        self.assertEqual(maps, {"dm2", "dm3"})


# ---------------------------------------------------------------------------
# Corpus tests (skipped when files are absent)
# ---------------------------------------------------------------------------

CASE_A = Path("/home/xerial/ctv_decomp/SmackDown3__game_425_FS_CD_1_DM3_delta.qwd")
CASE_B = Path(
    "/home/xerial/ctv_decomp/quakeworld__CHTV_Firing_Squad-Europe_Lege_Artis-"
    "Europe_Autotrack_commentary_DM3_QW_4v4__2006-03-19_[fs]_vs_.la._dm3_000.qwd"
)
CASE_C = Path(
    "/mnt/c/Users/benya/projects/quakeworld/data/challenge-tv-archive/extracted/"
    "challenge-tv.com/demostorage/Quakeworld/locktar/"
    "Locktar - Locktar_vs_AimLess - [dmm3] - [dm2]_000.qwd"
)
CASE_D = Path(
    "/home/xerial/ctv_decomp/quakeworld__CHTV_boohoo-UK_fry-UK_boohoo_dm3_"
    "QuakeWorld_1v1__boohoo_fry.qwd"
)
CASE_F = Path(
    "/mnt/c/Users/benya/projects/quakeworld/data/challenge-tv-archive/extracted/"
    "challenge-tv.com/demostorage/Quakeworld/smackdown/neu/group_c/"
    "adt_jod_1_dm2_camper.qwd"
)


class CorpusTests(unittest.TestCase):
    @unittest.skipUnless(CASE_D.exists(), "case (d) corpus file absent")
    def test_case_d_true_map_from_bytes_dm3_filename_is_dm4(self) -> None:
        rec = qcm.parse_qwd(CASE_D)
        self.assertIn("dm3", CASE_D.name.lower())  # filename lies
        self.assertEqual(rec["true_map"], "dm4")
        self.assertEqual(rec["mode"], "1on1")

    @unittest.skipUnless(CASE_B.exists(), "case (b) corpus file absent")
    def test_case_b_autotrack_ineligible(self) -> None:
        rec = qcm.parse_qwd(CASE_B)
        self.assertEqual(rec["true_map"], "dm3")
        self.assertFalse(rec["self_pov_eligible"])
        self.assertEqual(rec["pov_kind"], "autotrack")

    @unittest.skipUnless(CASE_C.exists(), "case (c) corpus file absent")
    def test_case_c_self_pov_eligible(self) -> None:
        rec = qcm.parse_qwd(CASE_C)
        self.assertEqual(rec["true_map"], "dm2")
        self.assertEqual(rec["mode"], "1on1")
        self.assertEqual(rec["player_count"], 2)
        self.assertTrue(rec["self_pov_eligible"])
        self.assertEqual(rec["pov_player"], "Locktar")
        self.assertFalse(rec["is_compressed"])

    @unittest.skipUnless(CASE_F.exists(), "case (f) corpus file absent")
    def test_case_f_compressed_detection(self) -> None:
        rec = qcm.parse_qwd(CASE_F)
        self.assertTrue(rec["is_compressed"])
        self.assertIsNotNone(rec["compressed_sha256"])
        if rec["errors"]:
            self.skipTest(f"qizmo unavailable: {rec['errors']}")
        self.assertIsNotNone(rec["decompressed_sha256"])
        self.assertNotEqual(rec["compressed_sha256"], rec["decompressed_sha256"])
        self.assertEqual(rec["true_map"], "dm2")
        self.assertIsNotNone(rec["decompressor"])

    @unittest.skipUnless(CASE_A.exists(), "case (a) corpus file absent")
    def test_case_a_self_pov_dm3_4on4(self) -> None:
        rec = qcm.parse_qwd(CASE_A)
        self.assertEqual(rec["true_map"], "dm3")
        self.assertTrue(rec["self_pov_eligible"])
        self.assertEqual(rec["player_count"], 8)
        self.assertEqual(rec["mode"], "4on4")
        self.assertEqual(rec["pov_kind"], "self")


# ---------------------------------------------------------------------------
# qizmo bundle resolution (injectable; no real bundle required)
# ---------------------------------------------------------------------------

class QizmoBundleResolutionTests(unittest.TestCase):
    def test_explicit_override_wins_and_must_exist(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="qcm_qz_"))
        bundle = tmp / "qizmo_bundle.tgz"
        bundle.write_bytes(b"placeholder")  # only existence matters here
        self.assertEqual(qcm._resolve_qizmo_bundle(bundle), bundle)
        self.assertIsNone(qcm._resolve_qizmo_bundle(tmp / "missing.tgz"))

    def test_env_var_override(self) -> None:
        import os

        tmp = Path(tempfile.mkdtemp(prefix="qcm_qz_"))
        bundle = tmp / "qizmo_bundle.tgz"
        bundle.write_bytes(b"x")
        old = os.environ.get(qcm.QIZMO_BUNDLE_ENV)
        try:
            os.environ[qcm.QIZMO_BUNDLE_ENV] = str(bundle)
            self.assertEqual(qcm._resolve_qizmo_bundle(), bundle)
            os.environ[qcm.QIZMO_BUNDLE_ENV] = str(tmp / "nope.tgz")
            self.assertIsNone(qcm._resolve_qizmo_bundle())
        finally:
            if old is None:
                os.environ.pop(qcm.QIZMO_BUNDLE_ENV, None)
            else:
                os.environ[qcm.QIZMO_BUNDLE_ENV] = old

    def test_qwz_without_bundle_is_graceful_error(self) -> None:
        # A non-.qwd ("compressed") input with no available bundle -> error
        # record (never a crash), with the compressed hash still recorded.
        p = Path(tempfile.mkdtemp(prefix="qcm_qz_")) / "x.qwz"
        p.write_bytes(b"\x80\x01\xba\x1f\x57\xc1\xff\xf5" * 8)
        rec = qcm.parse_qwd(p, qizmo_bundle="/definitely/missing/qizmo_bundle.tgz")
        self.assertTrue(rec["is_compressed"])
        self.assertIsNotNone(rec["compressed_sha256"])
        self.assertTrue(rec["errors"])
        self.assertIsNone(rec["decompressed_sha256"])


if __name__ == "__main__":
    unittest.main()
