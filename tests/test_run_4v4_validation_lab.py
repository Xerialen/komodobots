from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import argparse


REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts"), str(REPO_ROOT / "lab" / "server")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import run_4v4_validation_lab as live4v4  # noqa: E402


class RemoteScriptShapeTests(unittest.TestCase):
    def test_remote_script_refuses_to_clobber_existing_lab_lock(self) -> None:
        self.assertIn("Lab lock already exists; refusing to clobber it", live4v4.REMOTE_SCRIPT)
        self.assertIn('cat "$lab_lock"', live4v4.REMOTE_SCRIPT)

    def test_remote_script_uses_spectator_shim_and_fixed_team_botcmds(self) -> None:
        script = live4v4.REMOTE_SCRIPT
        self.assertIn("--spectator", script)
        self.assertEqual(script.count('--botcmd "addbot 20 $team1"'), 4)
        self.assertEqual(script.count('--botcmd "addbot 20 $team2"'), 4)
        self.assertIn("--botcmd removeall", script)

    def test_remote_script_limits_to_lab_ports_and_denies_production_ports(self) -> None:
        script = live4v4.REMOTE_SCRIPT
        self.assertIn("28599|2860[0-9]", script)
        self.assertIn("28501|28502|28503", script)
        self.assertIn("Refusing production port", script)

    def test_remote_script_copies_raw_ktx_json_sidecar_for_ledger(self) -> None:
        self.assertIn('cp -- "${demo%.mvd}.json" "$rundir/ktxstats.json"', live4v4.REMOTE_SCRIPT)

    def test_remote_config_allows_ktx_4v4_mode(self) -> None:
        script = live4v4.REMOTE_SCRIPT
        self.assertIn("set k_allowed_free_modes 4095", script)
        self.assertIn("set k_defmode 4on4", script)
        self.assertIn("maxclients 9", script)
        self.assertIn("set k_maxclients 8", script)
        self.assertIn("set sv_login 0", script)
        self.assertIn("set k_lockmap 1", script)
        self.assertNotIn("\nk_maxclients 8", script)


class PortSelectionTests(unittest.TestCase):
    def test_choose_lab_port_refuses_non_lab_port(self) -> None:
        with self.assertRaises(RuntimeError):
            live4v4.choose_lab_port("servexeri", 28501, strict=True)

    def test_choose_lab_port_scans_allowlist_only(self) -> None:
        queried: list[int] = []

        def fake_port_down(_host: str, port: int) -> bool:
            queried.append(port)
            return port == 28601

        with patch.object(live4v4, "remote_port_is_down", fake_port_down):
            self.assertEqual(live4v4.choose_lab_port("servexeri", 28599, strict=False), 28601)

        self.assertTrue(all(28599 <= port <= 28609 for port in queried))
        self.assertIn(28601, queried)


class ArgumentValidationTests(unittest.TestCase):
    def test_run_id_rejects_path_or_shell_characters(self) -> None:
        for bad in ("../x", "x;y", "x y"):
            with self.subTest(bad=bad), self.assertRaises(argparse.ArgumentTypeError):
                live4v4.validate_run_id_arg(bad)

    def test_remote_binary_rejects_paths_and_shell_characters(self) -> None:
        self.assertEqual(live4v4.validate_remote_bin_arg("mvdsv-lab"), "mvdsv-lab")
        for bad in ("../mvdsv", "mvdsv;rm", "mvdsv lab"):
            with self.subTest(bad=bad), self.assertRaises(argparse.ArgumentTypeError):
                live4v4.validate_remote_bin_arg(bad)


class LiveLeapWiringTests(unittest.TestCase):
    def test_leap_cvar_block_enables_mode30_on_leap_edicts_only(self) -> None:
        block = live4v4.build_leap_cvar_block("komodo_move_t07", 3)
        # leap bots seat at edicts 2..5 (slots 1..4) behind the slot-0 spectator
        for edict in (2, 3, 4, 5):
            self.assertIn(f"set k_fb_moveprobe_mode_s{edict} 30", block)
        # the frog edicts must stay stock -- never mode 30
        for edict in (1, 6, 7, 8, 9):
            self.assertNotIn(f"set k_fb_moveprobe_mode_s{edict} 30", block)
        self.assertIn('set k_fb_moveprobe_live_shm_name "komodo_move_t07"', block)
        self.assertIn("set k_fb_moveprobe_live_stale_ticks 3", block)
        # the freshness gate needs KTX's LIVE/FALLBACK log turned on
        self.assertIn("set k_fb_moveprobe_live_log 1", block)

    def test_sidecar_command_attaches_without_create(self) -> None:
        cmd = live4v4.build_sidecar_command(
            "~/t0.3-venv/bin/python", "~/komodo-t0.3/scripts/move_policy_sidecar.py",
            "komodo_move_t07", "~/move_bc_policy.pt", 77,
        )
        self.assertIn("cd ~/komodo-t0.3/scripts &&", cmd)
        self.assertIn("--shm-name komodo_move_t07", cmd)
        self.assertIn("--ckpt ~/move_bc_policy.pt", cmd)
        self.assertIn("--hz 77", cmd)
        self.assertNotIn("--create", cmd)  # KTX owns the region; sidecar mirrors

    def test_b64_roundtrips(self) -> None:
        import base64

        text = 'set a 1\nset b "x"\n'
        self.assertEqual(base64.b64decode(live4v4._b64(text)).decode("utf-8"), text)

    def test_remote_script_wires_live_leap(self) -> None:
        script = live4v4.REMOTE_SCRIPT
        self.assertIn('live_leap="${9:-0}"', script)
        self.assertIn('shm_name="${10:-}"', script)
        self.assertIn('leap_cvars_b64="${11:-}"', script)
        self.assertIn('sidecar_cmd_b64="${12:-}"', script)
        # cfg gets the leap cvars; sidecar attaches once the region appears
        self.assertIn("base64 -d >> \"$cfg_path\"", script)
        self.assertIn('[ -e "/dev/shm/$shm_name" ]', script)
        self.assertIn('eval "$sidecar_cmd"', script)
        # and is torn down (cleanup + post-match)
        self.assertIn("move_policy_sidecar.py --shm-name $shm_name", script)

    def test_remote_script_unlinks_region_on_normal_path(self) -> None:
        # The success path clears the EXIT trap (trap - EXIT), so the region must
        # be removed inline post-match, not only in cleanup().
        script = live4v4.REMOTE_SCRIPT
        self.assertIn('rm -f "/dev/shm/$shm_name"', script)
        self.assertIn("trap - EXIT", script)

    def test_remote_script_fails_run_when_live_brain_never_serves(self) -> None:
        # P1: mode 30 falls back to stock Frogbot silently, so the run MUST fail
        # (non-zero exit) if the region never appeared or the sidecar died early --
        # otherwise a frog-vs-frog match gets scored under a live-leap label.
        script = live4v4.REMOTE_SCRIPT
        self.assertIn('touch "$rundir/sidecar.started"', script)
        self.assertIn('echo "$?" > "$rundir/sidecar.exitcode"', script)
        self.assertIn('if [ ! -f "$rundir/sidecar.started" ]; then', script)
        self.assertIn('kill -0 "$sidecar_pid"', script)
        # both integrity failures abort the run before it is scored
        self.assertEqual(script.count("exit 9"), 2)
        self.assertIn("mislabeled as live-leap", script)

    def test_remote_script_gates_shm_cleanup_on_live_and_ownership(self) -> None:
        # P2: cleanup() must not pkill/unlink the shared region unless THIS
        # invocation is a live run that actually started the sidecar -- else a
        # losing lock-race invocation stomps the active run's sidecar/region.
        script = live4v4.REMOTE_SCRIPT
        self.assertIn(
            'if [ "$live_leap" = "1" ] && [ -n "$sidecar_pid" ] && [ -n "$shm_name" ]; then',
            script,
        )

    def test_main_live_leap_requires_leap_team(self) -> None:
        rc = live4v4.main(["--live-leap", "--skip-prereq-check"])
        self.assertEqual(rc, 2)

    def test_run_remote_passes_live_leap_positional_args_in_order(self) -> None:
        import tempfile

        captured: dict = {}

        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return _Proc()

        with tempfile.TemporaryDirectory() as td, patch.object(live4v4, "run", fake_run):
            live4v4.run_remote_4v4_lab(
                host="servexeri", run_id="rid", port=28599, duration=5.0,
                map_name="dm3", timelimit=5, mvdsv_bin="mvdsv-lab",
                team1="leap", team2="frog", local_run_dir=Path(td),
                live_leap=True, shm_name="komodo_move_t07",
                leap_cvars="set k_fb_moveprobe_mode_s2 30\n",
                sidecar_cmd="cd x && y --shm-name komodo_move_t07",
            )
        # last four positional args after team2: live_leap, shm, b64(cvars), b64(cmd)
        tail = captured["cmd"][-4:]
        self.assertEqual(tail[0], "1")
        self.assertEqual(tail[1], "komodo_move_t07")
        self.assertEqual(live4v4._b64("set k_fb_moveprobe_mode_s2 30\n"), tail[2])
        self.assertEqual(live4v4._b64("cd x && y --shm-name komodo_move_t07"), tail[3])

    def test_run_remote_off_by_default(self) -> None:
        import tempfile

        captured: dict = {}

        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return _Proc()

        with tempfile.TemporaryDirectory() as td, patch.object(live4v4, "run", fake_run):
            live4v4.run_remote_4v4_lab(
                host="servexeri", run_id="rid", port=28599, duration=5.0,
                map_name="dm3", timelimit=5, mvdsv_bin="mvdsv-lab",
                team1="leap", team2="frog", local_run_dir=Path(td),
            )
        self.assertEqual(captured["cmd"][-4], "0")  # live_leap off


def _live_line(slot: int, verb: str) -> str:
    if verb == "LIVE":
        return f"[moveprobe-live] slot {slot} LIVE fwd=1 side=-1 jump=0 (req=153 ans=152)"
    return f"[moveprobe-live] slot {slot} FALLBACK (stock frogbot; req=8830 ans=8593)"


def _screen_log(counts: dict) -> str:
    """counts: {slot: (n_live, n_fallback)} -> interleaved screen.log text."""
    lines = ["KTX 1.48 starting", "some unrelated server chatter"]
    for slot, (nl, nf) in counts.items():
        lines += [_live_line(slot, "LIVE")] * nl
        lines += [_live_line(slot, "FALLBACK")] * nf
    return "\n".join(lines) + "\n"


class FreshnessGateTests(unittest.TestCase):
    def _eval(self, counts, **kw):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            rd = Path(td)
            (rd / "screen.log").write_text(_screen_log(counts), encoding="utf-8")
            return live4v4.evaluate_live_freshness(rd, **kw)

    def test_all_leap_slots_mostly_live_passes(self) -> None:
        ok, rep = self._eval({1: (45, 4), 2: (48, 10), 3: (45, 7), 4: (46, 5)})
        self.assertTrue(ok)
        self.assertTrue(rep["ok"])
        self.assertTrue(all(rep["slots"][str(s)]["went_live"] for s in (1, 2, 3, 4)))

    def test_one_leap_slot_all_fallback_fails(self) -> None:
        ok, rep = self._eval({1: (45, 4), 2: (48, 10), 3: (0, 40), 4: (46, 5)})
        self.assertFalse(ok)
        self.assertFalse(rep["slots"]["3"]["ok"])
        self.assertFalse(rep["slots"]["3"]["went_live"])
        # the healthy slots are still individually ok
        self.assertTrue(rep["slots"]["1"]["ok"])

    def test_leap_slot_with_no_loglines_fails(self) -> None:
        # slot 4 never logged at all -> cannot prove freshness -> fail closed
        ok, rep = self._eval({1: (45, 4), 2: (48, 10), 3: (45, 7)})
        self.assertFalse(ok)
        self.assertEqual(rep["slots"]["4"]["live_loglines"], 0)
        self.assertEqual(rep["slots"]["4"]["fallback_loglines"], 0)
        self.assertFalse(rep["slots"]["4"]["ok"])

    def test_transient_minority_fallback_passes(self) -> None:
        # frequent respawns produce some FALLBACK bursts, but LIVE still dominates
        ok, rep = self._eval({1: (80, 20), 2: (80, 20), 3: (80, 20), 4: (80, 20)})
        self.assertTrue(ok)
        self.assertAlmostEqual(rep["slots"]["1"]["fraction"], 0.8, places=3)

    def test_threshold_boundary_is_inclusive(self) -> None:
        # exactly at the threshold passes (>=)
        ok, _ = self._eval({1: (5, 5), 2: (5, 5), 3: (5, 5), 4: (5, 5)}, min_fraction=0.5)
        self.assertTrue(ok)
        # just under fails
        ok2, _ = self._eval({1: (4, 6), 2: (5, 5), 3: (5, 5), 4: (5, 5)}, min_fraction=0.5)
        self.assertFalse(ok2)

    def test_frog_slots_are_ignored(self) -> None:
        # frog controls (slots 5..8) are stock and never log mode-30; even if they
        # somehow appeared as FALLBACK they must not affect the leap verdict
        ok, rep = self._eval(
            {1: (45, 4), 2: (48, 10), 3: (45, 7), 4: (46, 5), 5: (0, 99), 6: (0, 99)}
        )
        self.assertTrue(ok)
        self.assertNotIn("5", rep["slots"])
        self.assertNotIn("6", rep["slots"])

    def test_missing_screen_log_fails_closed(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            ok, rep = live4v4.evaluate_live_freshness(Path(td))
        self.assertFalse(ok)
        self.assertIn("reason", rep)

    def test_main_fails_run_when_brain_fell_back(self) -> None:
        import tempfile

        def fake_scp(host, run_id, local_run_dir):
            Path(local_run_dir).mkdir(parents=True, exist_ok=True)
            # all four leap slots FALLBACK -> masked frog-vs-frog -> must fail
            (Path(local_run_dir) / "screen.log").write_text(
                _screen_log({1: (0, 30), 2: (0, 30), 3: (0, 30), 4: (0, 30)}),
                encoding="utf-8",
            )

        with tempfile.TemporaryDirectory() as td:
            out_root = Path(td) / "runs"
            ledger_out = Path(td) / "ledger.json"
            with patch.object(live4v4, "choose_lab_port", lambda *a, **k: 28599), patch.object(
                live4v4, "write_run_artifacts", lambda *a, **k: {"roster": "r", "plan": "p"}
            ), patch.object(live4v4, "upload_shim", lambda *a, **k: None), patch.object(
                live4v4, "run_remote_4v4_lab", lambda **k: None
            ), patch.object(
                live4v4, "scp_from_remote", fake_scp
            ), patch.object(
                live4v4, "run_analyzer", lambda *a, **k: {}
            ):
                rc = live4v4.main(
                    [
                        "--live-leap",
                        "--leap-team",
                        "--skip-prereq-check",
                        "--run-id",
                        "frtest",
                        "--out-root",
                        str(out_root),
                        "--ledger-out",
                        str(ledger_out),
                        "--team1",
                        "leap",
                        "--team2",
                        "frog",
                    ]
                )
            # assert inside the tempdir context -- it is deleted on block exit
            self.assertEqual(rc, 1)
            rd = out_root / "frtest"
            self.assertTrue((rd / "freshness.json").is_file())
            self.assertTrue((rd / "runner.error.txt").is_file())
            # the ledger was NOT written as a valid game
            self.assertFalse(ledger_out.is_file())


if __name__ == "__main__":
    unittest.main()
