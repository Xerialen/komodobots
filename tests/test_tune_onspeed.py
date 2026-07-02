"""Gating tests for the #429 tuning driver — stdlib only, trainer FAKED.

Locks the sweep's honesty properties: deterministic bounded sampling (with the
incumbent control at trial 0 and the buffer-capped minibatch grid), driver-owned
trial identity + done-set resume (config_id is NOT precomputable — auditor MF-1),
the kl_coef/anchor-ceiling pairing (MF-3), seed-averaged config scores that group by
journal config_id and never cross environment groups, grade-key parity with the
route-grade selector's ordering, and a verdict that hard-codes superhuman_claim=false
and refuses cross-environment winners.
"""
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT / "ml"))
sys.path.insert(0, str(REPO_ROOT / "ml" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "experiments" / "route_observatory"))

import tune_onspeed as TN                 # noqa: E402
import experiment_registry as XR          # noqa: E402
import route_grade as RG                  # noqa: E402


def _summary(frac, ratio=1.0, rmse=20.0):
    return {"seg_faster_frac": frac, "median_speedup_ratio": ratio,
            "median_route_rmse_qu": rmse, "n_segments": 12,
            "n_ref_invalid": 0, "n_ref_degenerate": 0}


class TestSampler(unittest.TestCase):
    def test_deterministic_and_bounded(self):
        for i in range(1, 40):
            a = TN.trial_config(429, i)
            b = TN.trial_config(429, i)
            self.assertEqual(a, b, "same (sweep_seed, index) must resample identically")
            self.assertTrue(1e-5 <= a["lr"] <= 3e-4)
            self.assertTrue(0.1 <= a["clip"] <= 0.3)
            self.assertIn(a["kl_coef"], TN.KL_COEF_ARMS)
            self.assertTrue(1e-4 <= a["ent_coef"] <= 3e-2)
            self.assertIn(a["minibatch"], TN.MINIBATCH_GRID)
            self.assertLessEqual(a["minibatch"], 3072,
                                 "above the 12x256 rollout buffer a minibatch is a "
                                 "silent full-batch alias (auditor MF-2)")
            self.assertTrue(0.5 <= a["w_press"] <= 3.0)

    def test_trial_zero_is_the_incumbent_control(self):
        self.assertEqual(TN.trial_config(429, 0), {},
                         "trial 0 = defaults (the named-baseline control)")

    def test_kl_ceiling_pairing(self):
        # auditor MF-3: anchor-off arm must raise the eligibility ceiling, anchored
        # arms must keep the default — sampled across many indices.
        seen_off = seen_on = False
        for i in range(1, 60):
            c = TN.trial_config(7, i)
            if c["kl_coef"] == 0.0:
                seen_off = True
                self.assertEqual(c["kl_anchor_ceiling"], 1e9)
            else:
                seen_on = True
                self.assertEqual(c["kl_anchor_ceiling"], 0.32)
        self.assertTrue(seen_off and seen_on, "both arms must occur in 60 samples")

    def test_different_sweep_seed_changes_the_draw(self):
        draws_a = [TN.trial_config(1, i) for i in range(1, 6)]
        draws_b = [TN.trial_config(2, i) for i in range(1, 6)]
        self.assertNotEqual(draws_a, draws_b)


class TestArgvAndIdentity(unittest.TestCase):
    DATA = {"init_ckpt": "warm.pt", "db": "d.duckdb", "bsp": "m.bsp",
            "norm_artifact": "n.json", "anchors": "a.json"}

    def test_argv_shape(self):
        out = Path("/x/sweep/ckpts/t003_s0.pt")
        argv = TN.trial_argv("python3", "ml/rl_onspeed.py", self.DATA,
                             {"lr": 1e-4, "w_press": 2.0, "kl_anchor_ceiling": 1e9},
                             seed=0, steps=200000, out_ckpt=out,
                             registry="sweep/experiment_registry.jsonl",
                             git_sha="a" * 40, grade_segments=12, n_reset_segments=30)
        s = " ".join(argv)
        self.assertIn("--select-by-route-grade", s)
        self.assertIn("--n-reset-segments 30", s,
                      "the sweep's pool budget must reach the trainer (default 64 can "
                      "exceed the qualifying pool and empty the holdout)")
        self.assertIn("--reward-weight w_press=2.0", s)
        self.assertIn("--kl-anchor-ceiling", s)
        self.assertIn("--lr 1e-04", s.replace("0.0001", "1e-04"))
        self.assertIn("--git-sha", s)
        self.assertIn("--seed 0", s)
        self.assertNotIn("--reset-split", s,
                         "legacy invocation (no reset_split) must stay byte-identical")

    def test_argv_forwards_reset_split_when_set(self):
        argv = TN.trial_argv("python3", "ml/rl_onspeed.py", self.DATA, {},
                             seed=0, steps=1000, out_ckpt="t000_s0.pt",
                             registry="r.jsonl", git_sha="a" * 40,
                             grade_segments=12, n_reset_segments=100,
                             reset_split="train")
        s = " ".join(argv)
        self.assertIn("--reset-split train", s)
        self.assertIn("--n-reset-segments 100", s)
        reg = argv[argv.index("--registry") + 1]
        self.assertTrue(Path(reg).is_absolute(),
                        "--registry must be ABSOLUTE (the child resolves relative "
                        "explicit paths against ITS cwd)")

    def test_trial_identity_roundtrip(self):
        p = TN.trial_ckpt_path("/s", 7, 1003)
        self.assertEqual(TN.trial_index_from_path(p), (7, 1003))
        self.assertIsNone(TN.trial_index_from_path("/foreign/model.pt"))


class TestScoresAndResume(unittest.TestCase):
    def _journal_run(self, reg, out_ckpt, frac, *, sha="a" * 40, final=True, now):
        c = XR.start_run(reg, {"out_ckpt": str(out_ckpt), "db": None,
                               "norm_artifact": None, "anchors": None, "split": "val",
                               "horizon": 385, "n_reset_segments": 64,
                               "select_grade_segments": 12, "lr": 3e-4,
                               "seed": int(str(out_ckpt).rsplit("_s", 1)[1].split(".")[0]),
                               "registry": str(reg)},
                         {"w_press": 1.0}, git_sha=sha, now=now)
        if final:
            XR.finalize_run(reg, c, {"route_grade_summary": _summary(frac)},
                            ckpt_path=None, now=now + 60)
        return c

    def test_done_set_skips_completed_not_crashed(self):
        with tempfile.TemporaryDirectory() as td:
            reg = Path(td) / "r.jsonl"
            done_ck = TN.trial_ckpt_path(td, 1, 0)
            crash_ck = TN.trial_ckpt_path(td, 2, 0)
            self._journal_run(reg, done_ck, 0.5, now=1000.0)               # completed
            self._journal_run(reg, crash_ck, 0.5, final=False, now=2000.0)  # crashed
            done = TN.completed_out_ckpts(XR.join_runs(XR.read_records(reg)))
            self.assertIn(str(done_ck), done)
            self.assertNotIn(str(crash_ck), done,
                             "a crashed trial must be RE-RUN on resume, not skipped")

    def test_config_scores_groups_by_config_and_averages_seeds(self):
        with tempfile.TemporaryDirectory() as td:
            reg = Path(td) / "r.jsonl"
            # config A (trial 1) across two seeds; the args differ ONLY by seed +
            # out_ckpt -> the registry's config_id groups them (seed-invariant).
            self._journal_run(reg, TN.trial_ckpt_path(td, 1, 0), 0.8, now=1000.0)
            self._journal_run(reg, TN.trial_ckpt_path(td, 1, 1001), 0.2, now=2000.0)
            runs = XR.join_runs(XR.read_records(reg))
            scores = TN.config_scores(runs)
            self.assertEqual(len(scores), 1, "seed replicates must share a config_id")
            sc = next(iter(scores.values()))
            self.assertEqual(sc["n"], 2)
            self.assertAlmostEqual(sc["mean_key"][0], 0.5)
            self.assertAlmostEqual(sc["worst_key"][0], 0.2,
                                   msg="the WORST seed must be visible (fragile-winner guard)")
            self.assertAlmostEqual(sc["spread"][0], 0.6)

    def test_scores_never_cross_environment_groups(self):
        with tempfile.TemporaryDirectory() as td:
            reg = Path(td) / "r.jsonl"
            self._journal_run(reg, TN.trial_ckpt_path(td, 1, 0), 0.9, now=1000.0)
            self._journal_run(reg, TN.trial_ckpt_path(td, 1, 1001), 0.9,
                              sha="b" * 40, now=2000.0)   # other code version
            scores = TN.config_scores(XR.join_runs(XR.read_records(reg)))
            self.assertEqual(len(TN.environment_hashes(scores)), 2)
            self.assertEqual(len(scores), 2,
                             "same config under different code must NOT average together")


class TestGradeKeyParity(unittest.TestCase):
    def test_registry_ordering_matches_the_selector(self):
        # XR.grade_key must order candidates exactly as route_grade.rank_by_route_grade
        # (the training selector) does — same fields, same direction.
        weak = _summary(0.3, ratio=0.8, rmse=30.0)
        strong = _summary(0.7, ratio=1.2, rmse=10.0)
        cands = [{"summary": weak}, {"summary": strong}]
        best_i, _reason = RG.rank_by_route_grade(cands, min_valid_segments=1)
        self.assertEqual(best_i, 1)
        self.assertGreater(XR.grade_key(strong), XR.grade_key(weak))
        # rmse tiebreak direction: LOWER rmse wins at equal frac+ratio
        self.assertGreater(XR.grade_key(_summary(0.5, 1.0, 5.0)),
                           XR.grade_key(_summary(0.5, 1.0, 50.0)))


class TestRunSweepEndToEnd(unittest.TestCase):
    @staticmethod
    def _trial_args(out, reg, idx, seed):
        """The arg-shape the fake trainer journals — config_id-identical for one trial
        index across seeds (seed/out_ckpt/registry are excluded from config_id)."""
        return {"out_ckpt": str(out), "db": None, "norm_artifact": None, "anchors": None,
                "split": "val", "horizon": 385, "n_reset_segments": 64,
                "select_grade_segments": 12, "seed": int(seed), "registry": str(reg),
                "cfg": json.dumps(TN.trial_config(429, idx), sort_keys=True)}

    def _fake_runner_factory(self, reg_holder, frac_by_index=None, frac_fn=None):
        """A fake trainer: journals start+final itself (as the real child does) with a
        per-trial grade. frac_fn(idx, seed) overrides frac_by_index[idx]; a None frac
        crashes (start-without-final, exit 1)."""
        def fake(argv, log_path, timeout_s):
            out = argv[argv.index("--out-ckpt") + 1]
            reg = argv[argv.index("--registry") + 1]
            reg_holder.append(reg)
            seed = int(argv[argv.index("--seed") + 1])
            idx, _ = TN.trial_index_from_path(out)
            c = XR.start_run(reg, self._trial_args(out, reg, idx, seed), {},
                             git_sha="a" * 40, now=1000.0 + idx + seed)
            frac = frac_fn(idx, seed) if frac_fn else frac_by_index.get(idx, 0.1)
            if frac is None:
                return 1                      # crash: start-without-final
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"ckpt-" + str(idx).encode())
            XR.finalize_run(reg, c, {"route_grade_summary": _summary(frac)},
                            ckpt_path=out, now=1060.0 + idx + seed)
            return 0
        return fake

    def _args(self, sweep, trials=4, verify_seeds=2, git_sha="a" * 40):
        import argparse
        return argparse.Namespace(
            sweep_dir=str(sweep), init_ckpt="w.pt", db="d.duckdb", bsp="m.bsp",
            norm_artifact="n.json", anchors="a.json", resource_coords=None,
            map="dm3", split="val",
            trials=trials, trial_steps=1000, sweep_seed=429, base_seed=0,
            top_k=2, verify_seeds=verify_seeds, grade_segments=12,
            n_reset_segments=64, horizon=385, max_hours=0, trial_timeout=60,
            git_sha=git_sha, python="python3", trainer="ml/rl_onspeed.py",
            eval_script="ml/eval_broad_closedloop.py")

    def test_sweep_produces_honest_verdict_and_verifies_finalists(self):
        with tempfile.TemporaryDirectory() as td:
            regs = []
            # trial 2 is the best config; trial 3 crashes
            fake = self._fake_runner_factory(regs, {0: 0.2, 1: 0.4, 2: 0.8, 3: None})
            fake_tert = lambda *a, **k: _summary(0.6)   # noqa: E731
            v = TN.run_sweep(self._args(Path(td) / "s"), runner=fake, tertiary=fake_tert)
            self.assertIs(v["superhuman_claim"], False)
            self.assertIn("relative", v["caveat"])
            self.assertEqual(v["counts"]["crashed"], 1)
            self.assertIn("space_bounds", v)
            self.assertEqual(v["sweep_seed"], 429)
            w = v["winner"]
            self.assertIsNotNone(w)
            # winner = trial-2 config, seed-verified to verify_seeds runs
            self.assertEqual(w["n_runs"], 2)
            self.assertEqual(w["tertiary_grade"]["seg_faster_frac"], 0.6)
            self.assertIsNotNone(w["kept"])
            self.assertTrue(Path(w["kept"]["path"]).is_file())
            self.assertEqual(len(w["finalists"]), 2)
            # verdict file written
            vf = json.loads((Path(td) / "s" / "verdict.json").read_text())
            self.assertIs(vf["superhuman_claim"], False)

    def test_disjoint_reset_split_zeroes_the_tertiary_reset_skip(self):
        # --reset-split train: resets live in ANOTHER split's ordering, so the
        # tertiary chunk starts right after the ranking chunk (offset =
        # grade_segments, not n_reset_segments + grade_segments) and every trial
        # argv carries --reset-split. A stale reset-prefix skip here would silently
        # discard grade-split episodes and shrink the pool the flag exists to free.
        with tempfile.TemporaryDirectory() as td:
            argvs = []

            def fake_with_argv(argv, log_path, timeout_s):
                argvs.append(" ".join(str(x) for x in argv))
                return self._fake_runner_factory([], {0: 0.2, 1: 0.8})(
                    argv, log_path, timeout_s)

            seen = {}

            def tert(*a_, **kw):
                seen.update(kw)
                return _summary(0.6)

            a = self._args(Path(td) / "s", trials=2, verify_seeds=1)
            a.reset_split = "train"
            v = TN.run_sweep(a, runner=fake_with_argv, tertiary=tert)
            self.assertIsNotNone(v["winner"])
            self.assertEqual(seen["holdout_offset"], a.grade_segments)
            self.assertTrue(all("--reset-split train" in s for s in argvs), argvs)

    def test_sweep_resume_skips_completed_trials(self):
        with tempfile.TemporaryDirectory() as td:
            regs = []
            fake = self._fake_runner_factory(regs, {0: 0.2, 1: 0.4, 2: 0.8, 3: 0.3})
            fake_tert = lambda *a, **k: _summary(0.6)   # noqa: E731
            a = self._args(Path(td) / "s")
            TN.run_sweep(a, runner=fake, tertiary=fake_tert)
            calls = len(regs)
            TN.run_sweep(a, runner=fake, tertiary=fake_tert)   # second pass: all done
            self.assertEqual(len(regs), calls,
                             "a re-run of a finished sweep must launch ZERO trainers")

    def test_weak_tertiary_refuses_the_crown(self):
        # Codex #474 P1 (adversarial case reproduced): ranked 0.8, tertiary 0.1 ->
        # the pre-registered off-ramp must EXECUTE — no crowned winner, the refused
        # candidate stays audited, nothing blessed into winners/.
        with tempfile.TemporaryDirectory() as td:
            fake = self._fake_runner_factory([], {0: 0.2, 1: 0.4, 2: 0.8, 3: 0.3})
            weak_tert = lambda *a, **k: _summary(0.1)   # noqa: E731  (0.1 < 0.5*0.8)
            v = TN.run_sweep(self._args(Path(td) / "s"), runner=fake, tertiary=weak_tert)
            self.assertIsNone(v["winner"])
            self.assertIn("overfit_to_ranking_routes", v["refusal"])
            rc = v["refused_candidate"]
            self.assertEqual(rc["tertiary_grade"]["seg_faster_frac"], 0.1)
            self.assertNotIn("kept", rc, "a refused candidate must not be blessed")
            self.assertFalse((Path(td) / "s" / "winners").exists())

    def test_missing_tertiary_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            fake = self._fake_runner_factory([], {0: 0.2, 1: 0.4, 2: 0.8, 3: 0.3})
            no_tert = lambda *a, **k: None   # noqa: E731  (eval failed/unreadable)
            v = TN.run_sweep(self._args(Path(td) / "s"), runner=fake, tertiary=no_tert)
            self.assertIsNone(v["winner"])
            self.assertIn("unavailable", v["refusal"])
            self.assertIsNotNone(v["refused_candidate"])

    def test_unverified_config_is_never_crowned(self):
        # Codex #474 P1-2: trial 1 looks best (0.9) and gets seed-verified DOWN to a
        # mean ~0.37; trial 2 (single unverified seed, 0.5) then tops the full
        # ranking — the crown must stay with the VERIFIED finalist + a note emitted.
        with tempfile.TemporaryDirectory() as td:
            def frac(idx, seed):
                if idx == 1:
                    return 0.9 if seed == 0 else 0.1
                return 0.5 if idx == 2 else 0.1
            fake = self._fake_runner_factory([], frac_fn=frac)
            tert = lambda *a, **k: _summary(0.3)   # noqa: E731  (>= 0.5*mean(0.367))
            a = self._args(Path(td) / "s", trials=3, verify_seeds=3)
            a.top_k = 1
            v = TN.run_sweep(a, runner=fake, tertiary=tert)
            w = v["winner"]
            self.assertIsNotNone(w)
            self.assertEqual(w["n_runs"], 3, "the crowned config must be the VERIFIED one")
            self.assertAlmostEqual(w["mean_key"][0], (0.9 + 0.1 + 0.1) / 3, places=6)
            self.assertIn("unverified", v["note"],
                          "an unverified better-ranked config must be surfaced, not crowned")

    def test_resume_fills_the_seed_quota_without_consuming_it(self):
        # Codex #474 P2: seeds 0 and 1001 already complete for the finalist; with
        # --verify-seeds 5 the loop must SKIP those without consuming quota and land
        # exactly 5 completed runs (0,1001,1002,1003,1004).
        with tempfile.TemporaryDirectory() as td:
            sweep = Path(td) / "s"
            (sweep / "ckpts").mkdir(parents=True)
            reg = sweep / "experiment_registry.jsonl"
            for seed in (0, 1001):
                out = TN.trial_ckpt_path(sweep, 2, seed)
                out.write_bytes(b"ckpt-pre")          # real runs always have a ckpt
                c = XR.start_run(reg, self._trial_args(out, reg, 2, seed), {},
                                 git_sha="a" * 40, now=100.0 + seed)
                XR.finalize_run(reg, c, {"route_grade_summary": _summary(0.8)},
                                ckpt_path=out, now=160.0 + seed)
            fake = self._fake_runner_factory([], {0: 0.2, 1: 0.4, 2: 0.8, 3: 0.3})
            tert = lambda *a, **k: _summary(0.6)   # noqa: E731
            a = self._args(sweep, verify_seeds=5)
            a.top_k = 1
            v = TN.run_sweep(a, runner=fake, tertiary=tert)
            self.assertEqual(v["winner"]["n_runs"], 5,
                             "already-complete verification seeds must not consume the quota")

    def test_crashing_verification_seeds_refuse_the_crown(self):
        # Codex #474 round-2 P1: the best trial completes on its first seed but EVERY
        # replacement verification seed crashes — the bounded loop exits with the
        # finalist under-verified; it must NOT be crowned on one seed.
        with tempfile.TemporaryDirectory() as td:
            def frac(idx, seed):
                if idx == 2:
                    return 0.8 if seed == 0 else None   # verification seeds all crash
                return 0.2
            fake = self._fake_runner_factory([], frac_fn=frac)
            tert = lambda *a, **k: _summary(0.6)   # noqa: E731  (never reached)
            a = self._args(Path(td) / "s", trials=3, verify_seeds=3)
            a.top_k = 1
            v = TN.run_sweep(a, runner=fake, tertiary=tert)
            self.assertIsNone(v["winner"],
                              "a one-seed finalist must never be crowned at verify_seeds=3")
            self.assertIn("verify-seeds", v["refusal"])
            self.assertGreater(v["counts"]["crashed"], 0)

    def test_sweep_refuses_without_code_version(self):
        with tempfile.TemporaryDirectory() as td:
            a = self._args(Path(td) / "s", git_sha=None)
            with self.assertRaises(SystemExit):
                # tree_root fallback: this repo IS a git checkout, so force the
                # no-version path by pointing resolve at a bare tmpdir via --git-sha
                # None + a monkeypatched resolver.
                orig = XR.resolve_code_version
                XR.resolve_code_version = lambda e=None, tree_root=None: (None, "missing")
                try:
                    TN.run_sweep(a, runner=lambda *x: 0, tertiary=lambda *x, **k: None)
                finally:
                    XR.resolve_code_version = orig

    def test_verdict_refuses_mixed_environments(self):
        with tempfile.TemporaryDirectory() as td:
            reg_dir = Path(td) / "s"
            (reg_dir / "ckpts").mkdir(parents=True)
            reg = reg_dir / "experiment_registry.jsonl"
            # two completed runs under DIFFERENT code versions, then a sweep pass
            # with a runner that does nothing new (all planned trials "done" via
            # foreign paths is not the point — the verdict must refuse the mix)
            for sha, frac, idx in (("a" * 40, 0.5, 1), ("b" * 40, 0.9, 2)):
                c = XR.start_run(reg, {"out_ckpt": str(TN.trial_ckpt_path(reg_dir, idx, 0)),
                                       "db": None, "norm_artifact": None, "anchors": None,
                                       "split": "val", "horizon": 385,
                                       "n_reset_segments": 64, "select_grade_segments": 12,
                                       "seed": 0, "registry": str(reg)},
                                 {}, git_sha=sha, now=1000.0 * idx)
                XR.finalize_run(reg, c, {"route_grade_summary": _summary(frac)},
                                ckpt_path=None, now=1000.0 * idx + 60)
            a = self._args(reg_dir, trials=0, verify_seeds=1)
            v = TN.run_sweep(a, runner=lambda *x: 0, tertiary=lambda *x, **k: None)
            self.assertIsNone(v["winner"])
            self.assertIn("environment groups", v["refusal"])


if __name__ == "__main__":
    unittest.main()
