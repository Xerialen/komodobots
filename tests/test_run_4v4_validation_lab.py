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

    def test_sidecar_fields_is_newline_argv_list(self) -> None:
        fields = live4v4.build_sidecar_fields(
            "~/t0.3-venv/bin/python", "~/komodo-t0.3/scripts/move_policy_sidecar.py",
            "~/move_bc_policy.pt", 77,
        )
        parts = fields.strip("\n").split("\n")
        # exactly python, script, ckpt, hz -- decoded into a bash array remotely
        self.assertEqual(parts[0], "~/t0.3-venv/bin/python")
        self.assertEqual(parts[1], "~/komodo-t0.3/scripts/move_policy_sidecar.py")
        self.assertEqual(parts[2], "~/move_bc_policy.pt")
        self.assertEqual(parts[3], "77")
        self.assertNotIn("--create", fields)  # KTX owns the region; sidecar mirrors
        self.assertNotIn("&&", fields)  # not a shell string anymore -- argv pieces

    def test_sidecar_fields_preserve_paths_with_spaces(self) -> None:
        fields = live4v4.build_sidecar_fields(
            "/opt/py venv/bin/python", "/srv/move policy/move_policy_sidecar.py",
            "/models/move bc.pt", 60,
        )
        parts = fields.strip("\n").split("\n")
        # a space in a path stays a single argv element (was unsafe under the old
        # eval-on-concatenated-string path)
        self.assertEqual(parts[0], "/opt/py venv/bin/python")
        self.assertEqual(parts[2], "/models/move bc.pt")

    def test_b64_roundtrips(self) -> None:
        import base64

        text = 'set a 1\nset b "x"\n'
        self.assertEqual(base64.b64decode(live4v4._b64(text)).decode("utf-8"), text)

    def test_remote_script_wires_live_leap(self) -> None:
        script = live4v4.REMOTE_SCRIPT
        self.assertIn('live_leap="${9:-0}"', script)
        self.assertIn('shm_name="${10:-}"', script)
        self.assertIn('leap_cvars_b64="${11:-}"', script)
        self.assertIn('sidecar_fields_b64="${12:-}"', script)
        # cfg gets the leap cvars; sidecar attaches once the region appears
        self.assertIn("base64 -d >> \"$cfg_path\"", script)
        self.assertIn('[ -e "/dev/shm/$shm_name" ]', script)
        # P2: NO eval of the sidecar command -- argv decoded into a bash array,
        # ~ expanded, run as a real argv
        self.assertNotIn('eval "$sidecar', script)
        self.assertIn("mapfile -t _sc", script)
        self.assertIn('sc_py="${sc_py/#\\~/$HOME}"', script)
        self.assertIn('"$sc_py" "$sc_script" --shm-name "$shm_name" --ckpt "$sc_ckpt" --hz "$sc_hz"', script)
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
        self.assertIn('echo "$rc" > "$rundir/sidecar.exitcode"', script)
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
                sidecar_fields="py\nscript\nckpt\n77\n",
            )
        # last four positional args after team2: live_leap, shm, b64(cvars), b64(fields)
        tail = captured["cmd"][-4:]
        self.assertEqual(tail[0], "1")
        self.assertEqual(tail[1], "komodo_move_t07")
        self.assertEqual(live4v4._b64("set k_fb_moveprobe_mode_s2 30\n"), tail[2])
        self.assertEqual(live4v4._b64("py\nscript\nckpt\n77\n"), tail[3])

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


def _cum_line(slot: int, verb: str, live: int, total: int) -> str:
    """A throttled [moveprobe-live] line carrying the per-slot CUMULATIVE counters."""
    if verb == "LIVE":
        return (
            f"[moveprobe-live] slot {slot} LIVE fwd=1 side=-1 jump=0 "
            f"(req={total} ans={max(0, total - 1)}) live={live}/{total}"
        )
    return f"[moveprobe-live] slot {slot} FALLBACK (stock frogbot; req={total} ans=0) live={live}/{total}"


def _old_line(slot: int, verb: str) -> str:
    """A pre-cumulative line (old KTX build, no `live=L/T`)."""
    if verb == "LIVE":
        return f"[moveprobe-live] slot {slot} LIVE fwd=1 side=-1 jump=0 (req=153 ans=152)"
    return f"[moveprobe-live] slot {slot} FALLBACK (stock frogbot; req=8830 ans=8593)"


def _screen_log(slots: dict) -> str:
    """slots: {slot: (live_frames, total_frames)} -> screen.log with throttled lines.

    Emits a partial line then the FINAL cumulative line per slot, so the parser's
    max-total selection (end-of-match cumulative) is exercised.
    """
    lines = ["KTX 1.48 starting", "some unrelated server chatter"]
    for slot, (lf, tf) in slots.items():
        if tf <= 0:
            continue
        mid_t = max(1, tf // 2)
        mid_l = min(lf, mid_t)
        lines.append(_cum_line(slot, "LIVE" if mid_l * 2 >= mid_t else "FALLBACK", mid_l, mid_t))
        lines.append(_cum_line(slot, "LIVE" if lf * 2 >= tf else "FALLBACK", lf, tf))
    return "\n".join(lines) + "\n"


class FreshnessGateTests(unittest.TestCase):
    def _eval(self, counts, **kw):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            rd = Path(td)
            (rd / "screen.log").write_text(_screen_log(counts), encoding="utf-8")
            return live4v4.evaluate_live_freshness(rd, **kw)

    def test_all_leap_slots_mostly_live_passes(self) -> None:
        # (live_frames, total_frames) per leap slot -- true per-frame fractions ~0.9
        ok, rep = self._eval({1: (900, 1000), 2: (880, 1000), 3: (910, 1000), 4: (920, 1000)})
        self.assertTrue(ok)
        self.assertTrue(rep["ok"])
        self.assertTrue(all(rep["slots"][str(s)]["went_live"] for s in (1, 2, 3, 4)))
        self.assertAlmostEqual(rep["slots"]["1"]["fraction"], 0.9, places=3)
        self.assertEqual(rep["slots"]["1"]["total_frames"], 1000)

    def test_one_leap_slot_all_fallback_fails(self) -> None:
        # slot 3 served LIVE on 0 of 4000 frames -> gameable line-ratio would miss
        # this if it flapped, but the cumulative counter catches it
        ok, rep = self._eval({1: (900, 1000), 2: (880, 1000), 3: (0, 4000), 4: (920, 1000)})
        self.assertFalse(ok)
        self.assertFalse(rep["slots"]["3"]["ok"])
        self.assertFalse(rep["slots"]["3"]["went_live"])
        self.assertEqual(rep["slots"]["3"]["fraction"], 0.0)
        self.assertTrue(rep["slots"]["1"]["ok"])

    def test_flapping_sidecar_fails_despite_balanced_loglines(self) -> None:
        # The core P1 case: a sidecar that goes LIVE ~1 frame/s then FALLBACK for
        # ~76 frames emits ~balanced LOG LINES but served LIVE on ~1.3% of frames.
        # The cumulative counter must FAIL it even though the line ratio is ~0.5.
        import tempfile

        flap = (
            "[moveprobe-live] slot 1 LIVE fwd=1 side=0 jump=0 (req=77 ans=77) live=1/77\n"
            "[moveprobe-live] slot 1 FALLBACK (stock frogbot; req=153 ans=77) live=1/153\n"
            "[moveprobe-live] slot 1 LIVE fwd=1 side=0 jump=0 (req=154 ans=154) live=2/154\n"
            "[moveprobe-live] slot 1 FALLBACK (stock frogbot; req=300 ans=154) live=2/300\n"
        )
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td)
            (rd / "screen.log").write_text(flap, encoding="utf-8")
            ok, rep = live4v4.evaluate_live_freshness(rd, leap_slots=(1,))
        self.assertFalse(ok)
        s1 = rep["slots"]["1"]
        # ~equal LIVE/FALLBACK lines, but true fraction is ~2/300
        self.assertEqual(s1["live_loglines"], 2)
        self.assertEqual(s1["fallback_loglines"], 2)
        self.assertLess(s1["fraction"], 0.05)

    def test_disengaged_tail_counts_as_fallback_not_stale_freshness(self) -> None:
        # #422 ML evidence-chain: the C handoff gate emits off-highway DISENGAGED frames as
        # FALLBACK [moveprobe-live] lines (live flat, total advancing), so a run that ends on a
        # long off-highway tail reports the TRUE (low) engaged share -- not a stale high fraction
        # frozen at the last on-highway line. The parser keys on the max-total line, so the tail
        # cannot pass via a stale total.
        import tempfile

        log = "\n".join([
            _cum_line(1, "LIVE", 70, 77),        # on-highway burst -> looks ~0.91 fresh
            _cum_line(1, "FALLBACK", 70, 700),   # DISENGAGED tail: total climbs, live stays flat
            _cum_line(1, "FALLBACK", 70, 1400),  # ... still off-highway (the max-total line)
        ]) + "\n"
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td)
            (rd / "screen.log").write_text(log, encoding="utf-8")
            ok, rep = live4v4.evaluate_live_freshness(rd, leap_slots=(1,))
        s1 = rep["slots"]["1"]
        self.assertEqual(s1["total_frames"], 1400)  # max-total wins, not stuck at the stale 77
        self.assertEqual(s1["live_frames"], 70)
        self.assertAlmostEqual(s1["fraction"], 70 / 1400, places=4)  # true engaged share ~0.05
        self.assertLess(s1["fraction"], 0.5)
        self.assertFalse(ok)  # a long off-highway tail must FAIL the freshness gate

    def test_leap_slot_with_no_cumulative_fails(self) -> None:
        # slot 4 logs only OLD-format lines (no live=L/T) -> can't prove the true
        # per-frame fraction -> fail closed (forces the cumulative-aware KTX build)
        import tempfile

        text = _screen_log({1: (900, 1000), 2: (880, 1000), 3: (910, 1000)})
        text += _old_line(4, "LIVE") + "\n" + _old_line(4, "FALLBACK") + "\n"
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td)
            (rd / "screen.log").write_text(text, encoding="utf-8")
            ok, rep = live4v4.evaluate_live_freshness(rd)
        self.assertFalse(ok)
        self.assertFalse(rep["slots"]["4"]["has_cumulative"])
        self.assertFalse(rep["slots"]["4"]["ok"])
        self.assertTrue(rep["slots"]["1"]["ok"])

    def test_leap_slot_never_seated_fails(self) -> None:
        # slot 4 absent entirely -> no cumulative -> fail closed
        ok, rep = self._eval({1: (900, 1000), 2: (880, 1000), 3: (910, 1000)})
        self.assertFalse(ok)
        self.assertEqual(rep["slots"]["4"]["total_frames"], 0)
        self.assertFalse(rep["slots"]["4"]["ok"])

    def test_threshold_boundary_is_inclusive(self) -> None:
        # exactly at the threshold passes (>=)
        ok, _ = self._eval({1: (500, 1000), 2: (500, 1000), 3: (500, 1000), 4: (500, 1000)}, min_fraction=0.5)
        self.assertTrue(ok)
        # just under fails
        ok2, _ = self._eval({1: (499, 1000), 2: (500, 1000), 3: (500, 1000), 4: (500, 1000)}, min_fraction=0.5)
        self.assertFalse(ok2)

    def test_frog_slots_are_ignored(self) -> None:
        # frog controls (slots 5..8) are stock and never log mode-30; even if they
        # somehow appeared they must not affect the leap verdict
        ok, rep = self._eval(
            {1: (900, 1000), 2: (880, 1000), 3: (910, 1000), 4: (920, 1000), 5: (0, 9000), 6: (0, 9000)}
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
            # all four leap slots served 0 LIVE frames -> masked frog-vs-frog -> fail
            (Path(local_run_dir) / "screen.log").write_text(
                _screen_log({1: (0, 3000), 2: (0, 3000), 3: (0, 3000), 4: (0, 3000)}),
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
