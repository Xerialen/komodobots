"""Recorder evidence-integrity tests for scripts/prewar_movecheck.py (#453).

Two blockers Codex/@Xerialen flagged on PR #453: (1) the demo artifact could be
attributed to the wrong run, (2) the live sidecar's /dev/shm region was not
isolated per run. These lock the fixes. Stdlib only — no live server.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for sub in ("scripts", "lab/server"):
    p = str(REPO / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import prewar_movecheck as pw  # noqa: E402


class SelectRunDemoTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="demos-"))
        self.run_id = "20260628T120000Z"
        self.demo_name = f"prewar_movecheck_dm3_{self.run_id}"
        self.after = 1_000_000.0  # the run's start.marker mtime

    def _mvd(self, name: str, mtime: float, size: int = 60_000) -> Path:
        p = self.dir / name
        p.write_bytes(b"x" * size)
        os.utime(p, (mtime, mtime))
        return p

    def test_selects_this_runs_demo_ignoring_a_newer_unrelated_one(self):
        # The exact bug: a concurrent unrelated demo, written LATER, must not be
        # picked just because it is the newest *.mvd in the shared dir.
        mine = self._mvd(f"{self.demo_name}.mvd", self.after + 10)
        self._mvd("4on4_frog_vs_leap[dm3]20260628-1201.mvd", self.after + 100)  # newer, unrelated
        self._mvd(f"prewar_movecheck_dm3_20260628T119999Z.mvd", self.after + 99)  # another run, newer
        got = pw.select_run_demo(self.dir, self.demo_name, self.after)
        self.assertEqual(got, mine)

    def test_matches_a_date_suffixed_variant_by_prefix(self):
        # KTX may append k_demoname_date -> match by prefix, not equality.
        suff = self._mvd(f"{self.demo_name}20260628-1200.mvd", self.after + 5)
        got = pw.select_run_demo(self.dir, self.demo_name, self.after)
        self.assertEqual(got, suff)

    def test_ignores_pre_existing_stale_and_empty_matches(self):
        self._mvd(f"{self.demo_name}.mvd", self.after - 50)          # older than the run -> stale
        self._mvd(f"{self.demo_name}_empty.mvd", self.after + 5, size=0)  # zero-byte -> not a recording
        self.assertIsNone(pw.select_run_demo(self.dir, self.demo_name, self.after))

    def test_none_when_run_produced_nothing(self):
        self._mvd("ffa_4[dm3]20260628-1200.mvd", self.after + 5)  # someone else's demo only
        self.assertIsNone(pw.select_run_demo(self.dir, self.demo_name, self.after))


class MakeRunIdTest(unittest.TestCase):
    def test_distinct_across_ports_same_second(self):
        # Two runs launched in the same second on different ports must get
        # distinct attempt ids (deterministically, via the port component).
        a, b = pw.make_run_id(28599), pw.make_run_id(28600)
        self.assertNotEqual(a, b)
        self.assertIn("p28599", a)
        self.assertIn("p28600", b)

    def test_distinct_on_repeat_same_port_same_second(self):
        # Same port, same second (sequential reuse) -> still unique (random suffix).
        ids = {pw.make_run_id(28599) for _ in range(50)}
        self.assertEqual(len(ids), 50, "same-second same-port ids must not collide")

    def test_derived_artifacts_are_distinct_across_concurrent_runs(self):
        a, b = pw.make_run_id(28599), pw.make_run_id(28600)
        # run_dir, demo prefix, and shm all derive from run_id -> all distinct.
        self.assertNotEqual(f"prewar_movecheck_dm3_{a}", f"prewar_movecheck_dm3_{b}")
        self.assertNotEqual(f"experiments/prewar-movecheck/{a}",
                            f"experiments/prewar-movecheck/{b}")
        self.assertNotEqual(pw.default_shm_name(a), pw.default_shm_name(b))


class DefaultShmNameTest(unittest.TestCase):
    def test_derives_from_collision_proof_run_id(self):
        a = pw.default_shm_name(pw.make_run_id(28599))
        b = pw.default_shm_name(pw.make_run_id(28600))
        self.assertNotEqual(a, b)

    def test_not_the_old_shared_constant(self):
        name = pw.default_shm_name(pw.make_run_id(28599))
        self.assertNotEqual(name, "komodo_move_t07_prewar")
        self.assertTrue(name.startswith("komodo_move_prewar_"))


class ScoreHookBestEffortTest(unittest.TestCase):
    """T5.2 (#428): the --score post-run hook is best-effort. route_eval's expected failures raise
    SystemExit (BaseException, not Exception), so the hook MUST swallow SystemExit too -- otherwise a
    scoring failure would kill an already-valid live run (P1-2)."""

    def setUp(self):
        sys.path.insert(0, str(REPO / "experiments" / "route_observatory"))
        import route_eval  # noqa: PLC0415
        self.route_eval = route_eval
        self._orig = route_eval.evaluate_run
        self._orig_multi = route_eval.evaluate_run_multi

    def tearDown(self):
        self.route_eval.evaluate_run = self._orig
        self.route_eval.evaluate_run_multi = self._orig_multi

    def test_hook_swallows_systemexit_from_route_eval(self):
        def _raise(*_a, **_k):
            raise SystemExit("synthetic route_eval failure")

        self.route_eval.evaluate_run = _raise
        with tempfile.TemporaryDirectory() as td:
            # Must return None WITHOUT raising -- the recorded run/verdict stands.
            self.assertIsNone(pw._run_route_eval_score(Path(td), (1,), Path(td), n_bots=1))

    def test_hook_scores_multi_bot_via_evaluate_run_multi(self):
        # PR2: with --bots>1 the hook scores EACH seeded bot per-route via evaluate_run_multi, passing
        # the seeds (NOT a fail-closed SKIP, and NOT the single-bot evaluate_run path).
        seen = {}

        def _multi(run_dir, **k):
            seen["seeds"] = k.get("seeds")
            return {"run_id": "r", "route_evals": []}

        self.route_eval.evaluate_run_multi = _multi
        self.route_eval.evaluate_run = lambda *a, **k: self.fail("single-bot path must not run")
        seeds = [(1, "A", (0.0, 0.0, 0.0)), (2, "B", (100.0, 0.0, 0.0))]
        with tempfile.TemporaryDirectory() as td:
            pw._run_route_eval_score(Path(td), (1, 2), Path(td), seeds=seeds, n_bots=2)
        self.assertEqual(seen["seeds"], seeds)


class BuildScoreCvarBlockTest(unittest.TestCase):
    """T5.2 (#428) --score cvar emission: highway-gate cvars always; PR2 DIRECTED multi-bot emits
    BOTH intents per slot -- spawn_origin (START) AND fixed_goal (END marker), edict=slot+1 -- because
    the handoff gate is INTENT-FIRST (spawn-snap alone does not latch the route)."""

    def test_single_bot_emits_gate_only_no_seed(self):
        block = pw.build_score_cvar_block((1, 2))                     # spectator edict 1 + 1 bot edict 2
        self.assertIn("set k_fb_moveprobe_live_highway_gate_s2 1", block)
        self.assertIn("set k_fb_moveprobe_live_log 1", block)
        self.assertNotIn("spawn_origin", block)                      # free spawn (PR1 single-bot)
        self.assertNotIn("fixed_goal", block)

    def test_multi_bot_seeds_each_edict_with_both_intents(self):
        # Codex r3: every assigned slot gets BOTH start (spawn_origin) AND end (fixed_goal) intent.
        seeds = [(1, "ra_tunnel_mega_rl", (192.0, -208.0, -176.0)),
                 (2, "enter_ra_mid_ledge_top", (249.5, -315.9, 68.8))]
        end_markers = {"ra_tunnel_mega_rl": 7, "enter_ra_mid_ledge_top": 12}
        block = pw.build_score_cvar_block((1, 2, 3), seeds, end_markers)   # spectator + 2 bots
        # slot k -> EDICT k+1; the spectator edict 1 is NEVER seeded
        self.assertIn('set k_fb_moveprobe_spawn_origin_s2 "192.0 -208.0 -176.0"', block)
        self.assertIn("set k_fb_moveprobe_fixed_goal_s2 7", block)
        self.assertIn('set k_fb_moveprobe_spawn_origin_s3 "249.5 -315.9 68.8"', block)
        self.assertIn("set k_fb_moveprobe_fixed_goal_s3 12", block)
        self.assertNotIn("spawn_origin_s1", block)
        self.assertNotIn("fixed_goal_s1", block)
        self.assertIn("set k_fb_moveprobe_live_highway_gate_s3 1", block)

    def test_directed_seed_without_valid_end_marker_raises(self):
        # The directed contract is both-intents-or-nothing AND the END marker must be a POSITIVE
        # 1-based index: missing, empty, OR a no-op 0/negative/non-int must all RAISE -- never emit a
        # START-only (un-latchable) or fixed_goal-0 (no-op = un-directed) run.
        seeds = [(1, "ra_tunnel_mega_rl", (192.0, -208.0, -176.0))]
        for bad in (None, {}, {"ra_tunnel_mega_rl": 0}, {"ra_tunnel_mega_rl": -3},
                    {"ra_tunnel_mega_rl": 7.0}, {"other": 7}):
            with self.assertRaises(ValueError):
                pw.build_score_cvar_block((1, 2), seeds, bad)


class WriteCfgDirectedTest(unittest.TestCase):
    """T5.2 (#428) PR2: directed runs (seeds set) couple fixed_goal with k_matchless 1 -- a marker
    INDEX is meaningful only under the 65-item matchless set (run-ledger.md:11). Undirected/single-bot
    stays prewar (k_matchless 0)."""

    def _write(self, **kw):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "x.cfg"
            pw.write_cfg(cfg, port=28599, map_name="dm3", timelimit=10, shm_name="t",
                         stale_ticks=10, bot_edicts=(1, 2, 3), **kw)
            return cfg.read_text()

    def test_directed_is_matchless_with_both_cvars(self):
        seeds = [(1, "A", (1.0, 2.0, 3.0)), (2, "B", (4.0, 5.0, 6.0))]
        cfg = self._write(score=True, seeds=seeds, end_markers={"A": 7, "B": 12}, directed=True)
        self.assertIn("set k_matchless 1", cfg)
        self.assertIn('set k_fb_moveprobe_spawn_origin_s2 "1.0 2.0 3.0"', cfg)
        self.assertIn("set k_fb_moveprobe_fixed_goal_s2 7", cfg)
        self.assertIn("set k_fb_moveprobe_fixed_goal_s3 12", cfg)

    def test_undirected_is_prewar_no_seed_cvars(self):
        cfg = self._write(score=True, seeds=None, end_markers=None, directed=False)
        self.assertIn("set k_matchless 0", cfg)
        self.assertNotIn("spawn_origin", cfg)
        self.assertNotIn("fixed_goal", cfg)


class MainDirectedGateTest(unittest.TestCase):
    """T5.2 (#428) PR2 (Codex r3): a directed --score --bots>1 run with an EMPTY end-marker map must
    fail loud (exit 2) BEFORE standing up mvdsv/KTX -- never silently produce un-directed scores."""

    def test_empty_marker_map_fails_before_server(self):
        canon = {"highways": [
            {"id": "h_a", "route_class": "base", "start_xyz": [0, 0, 0], "end_xyz": [9, 9, 9]},
            {"id": "h_b", "route_class": "base", "start_xyz": [1, 1, 1], "end_xyz": [8, 8, 8]},
        ]}  # base highways present, but NO end_marker on any -> empty map -> fail-loud
        orig = pw.CANON_PATH
        with tempfile.TemporaryDirectory() as td:
            cpath = Path(td) / "canon.json"
            cpath.write_text(json.dumps(canon), encoding="utf-8")
            pw.CANON_PATH = cpath
            try:
                rc = pw.main(["--score", "--bots", "2", "--port", "28599"])
            finally:
                pw.CANON_PATH = orig
        self.assertEqual(rc, 2)

    def test_nonpositive_marker_also_fails_before_server(self):
        # A malformed end_marker: 0 (an engine no-op) must NOT satisfy the directed contract -- the
        # run must still fail loud (exit 2) before startup, not launch un-directed.
        canon = {"highways": [
            {"id": "h_a", "route_class": "base", "start_xyz": [0, 0, 0], "end_xyz": [9, 9, 9],
             "end_marker": 0},
            {"id": "h_b", "route_class": "base", "start_xyz": [1, 1, 1], "end_xyz": [8, 8, 8],
             "end_marker": 5},
        ]}
        orig = pw.CANON_PATH
        with tempfile.TemporaryDirectory() as td:
            cpath = Path(td) / "canon.json"
            cpath.write_text(json.dumps(canon), encoding="utf-8")
            pw.CANON_PATH = cpath
            try:
                rc = pw.main(["--score", "--bots", "2", "--port", "28599"])
            finally:
                pw.CANON_PATH = orig
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
