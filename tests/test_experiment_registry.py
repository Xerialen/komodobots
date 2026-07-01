"""Gating tests for the experiment run-registry (T4.2 / #426) — stdlib only.

The journal's honesty properties, each locked here because the tuning loop (#429)
will trust them: start+final join (crashed runs stay visible), torn-tail tolerance,
seed-invariant config_id (the lucky-seed guard groups replicates), the
environment-hash comparability guard (never rank across different code/data/routes),
provenance-incomplete records are visible but never rankable, and ckpt sha256
verification detects severed artifact lineage.
"""
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT / "ml" / "pipeline"))

import experiment_registry as XR          # noqa: E402


def _args(**over):
    a = {"db": None, "norm_artifact": None, "anchors": None, "split": "val",
         "horizon": 385, "n_reset_segments": 64, "select_grade_segments": 12,
         "lr": 3e-5, "clip": 0.2, "seed": 0, "out_ckpt": "runs/x.pt",
         "registry": "auto"}
    a.update(over)
    return a


def _grade(frac=0.5, ratio=1.1, rmse=20.0):
    return {"seg_faster_frac": frac, "median_speedup_ratio": ratio,
            "median_route_rmse_qu": rmse}


class TestWriterReaderRoundtrip(unittest.TestCase):
    def test_start_final_join_and_crashed_run_visible(self):
        with tempfile.TemporaryDirectory() as td:
            reg = Path(td) / "r.jsonl"
            c1 = XR.start_run(reg, _args(), {"w_press": 0.1}, git_sha="a" * 40, now=1000.0)
            XR.finalize_run(reg, c1, {"selected_it": 7,
                                      "route_grade_summary": _grade()},
                            ckpt_path=None, now=1060.0)
            c2 = XR.start_run(reg, _args(lr=1e-4), {}, git_sha="a" * 40, now=2000.0)
            runs = XR.join_runs(XR.read_records(reg))
            self.assertEqual(len(runs), 2)
            done = runs[c1["run_id"]]
            self.assertEqual(done["status"], "completed")
            self.assertEqual(done["final"]["wall_time_s"], 60.0)
            self.assertEqual(done["final"]["result"]["selected_it"], 7)
            # the crashed/running run is IN the journal, marked incomplete
            self.assertEqual(runs[c2["run_id"]]["status"], "incomplete")
            ok, reason = XR.eligible(runs[c2["run_id"]])
            self.assertFalse(ok)
            self.assertIn("incomplete", reason)

    def test_reader_tolerates_torn_trailing_line(self):
        with tempfile.TemporaryDirectory() as td:
            reg = Path(td) / "r.jsonl"
            c = XR.start_run(reg, _args(), {}, git_sha="a" * 40)
            with open(reg, "a", encoding="utf-8") as f:
                f.write('{"record_schema": "komodobots.experiment_run.v1", "kind": "fi')
            with self.assertLogs(XR.LOGGER, level=logging.WARNING):
                recs = XR.read_records(reg)
            self.assertEqual(len(recs), 1)
            self.assertEqual(recs[0]["run_id"], c["run_id"])

    def test_unknown_schema_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            reg = Path(td) / "r.jsonl"
            XR._append(reg, {"record_schema": "somebody.else.v9", "kind": "start",
                             "run_id": "x"})
            with self.assertLogs(XR.LOGGER, level=logging.WARNING):
                runs = XR.join_runs(XR.read_records(reg))
            self.assertEqual(runs, {})


class TestConfigId(unittest.TestCase):
    def test_stable_under_key_order_and_seed(self):
        a = _args(seed=0)
        b = dict(reversed(list(_args(seed=999).items())))   # same config, other seed+order
        self.assertEqual(XR.config_id(a, {"w": 1}), XR.config_id(b, {"w": 1}))

    def test_changes_when_a_hyperparam_changes(self):
        self.assertNotEqual(XR.config_id(_args(lr=3e-5), {}),
                            XR.config_id(_args(lr=1e-4), {}))
        self.assertNotEqual(XR.config_id(_args(), {"w_press": 0.1}),
                            XR.config_id(_args(), {"w_press": 0.2}))

    def test_output_path_invariant(self):
        self.assertEqual(XR.config_id(_args(out_ckpt="runs/a.pt"), {}),
                         XR.config_id(_args(out_ckpt="runs/b.pt"), {}))


class TestEnvironmentGuard(unittest.TestCase):
    def _run_pair(self, reg, sha, frac, now):
        c = XR.start_run(reg, _args(), {}, git_sha=sha, now=now)
        XR.finalize_run(reg, c, {"route_grade_summary": _grade(frac=frac)}, now=now + 60)
        return c

    def test_rank_never_crosses_environment_groups(self):
        with tempfile.TemporaryDirectory() as td:
            reg = Path(td) / "r.jsonl"
            self._run_pair(reg, "a" * 40, frac=0.2, now=1000.0)
            self._run_pair(reg, "a" * 40, frac=0.9, now=2000.0)
            self._run_pair(reg, "b" * 40, frac=0.5, now=3000.0)   # other code version
            groups = XR.rank_runs(XR.join_runs(XR.read_records(reg)))
            self.assertEqual(len(groups), 2, "different code_version -> different group")
            sizes = sorted(len(rs) for rs in groups.values())
            self.assertEqual(sizes, [1, 2])
            # within the 2-run group the higher faster-frac ranks first
            big = next(rs for rs in groups.values() if len(rs) == 2)
            self.assertEqual(
                big[0][1]["final"]["result"]["route_grade_summary"]["seg_faster_frac"], 0.9)

    def test_best_cli_refuses_mixed_groups(self):
        with tempfile.TemporaryDirectory() as td:
            reg = Path(td) / "r.jsonl"
            self._run_pair(reg, "a" * 40, frac=0.2, now=1000.0)
            self._run_pair(reg, "b" * 40, frac=0.5, now=2000.0)
            self.assertEqual(XR.main(["--registry", str(reg), "best"]), 1)
            env = next(iter(XR.rank_runs(XR.join_runs(XR.read_records(reg)))))
            self.assertEqual(XR.main(["--registry", str(reg), "best", "--env", env]), 0)


class TestProvenance(unittest.TestCase):
    def test_missing_code_version_is_visible_but_ineligible(self):
        with tempfile.TemporaryDirectory() as td:
            reg = Path(td) / "r.jsonl"
            with self.assertLogs(XR.LOGGER, level=logging.WARNING):
                c = XR.start_run(reg, _args(), {}, git_sha=None, tree_root=td)
            self.assertTrue(c["provenance_incomplete"])
            XR.finalize_run(reg, c, {"route_grade_summary": _grade()})
            runs = XR.join_runs(XR.read_records(reg))
            ok, reason = XR.eligible(runs[c["run_id"]])
            self.assertFalse(ok)
            self.assertIn("provenance", reason)
            self.assertEqual(XR.rank_runs(runs), {})
            self.assertEqual(len(runs), 1)          # still listed

    def test_code_version_file_resolution(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "CODE_VERSION").write_text("c" * 40 + "\n")
            sha, source = XR.resolve_code_version(None, tree_root=td)
            self.assertEqual(sha, "c" * 40)
            self.assertEqual(source, "file")
        sha, source = XR.resolve_code_version("d" * 40, tree_root="/nonexistent")
        self.assertEqual((sha, source), ("d" * 40, "arg"))

    def test_ungraded_run_ineligible_but_completed(self):
        with tempfile.TemporaryDirectory() as td:
            reg = Path(td) / "r.jsonl"
            c = XR.start_run(reg, _args(), {}, git_sha="a" * 40)
            XR.finalize_run(reg, c, {"selected_it": 3, "route_grade_summary": None})
            runs = XR.join_runs(XR.read_records(reg))
            self.assertEqual(runs[c["run_id"]]["status"], "completed")
            ok, reason = XR.eligible(runs[c["run_id"]])
            self.assertFalse(ok)
            self.assertIn("route_grade", reason)


class TestVerifyAndDiff(unittest.TestCase):
    def test_verify_detects_tamper_and_missing(self):
        with tempfile.TemporaryDirectory() as td:
            reg = Path(td) / "r.jsonl"
            ck = Path(td) / "model.pt"
            ck.write_bytes(b"weights-v1")
            c = XR.start_run(reg, _args(), {}, git_sha="a" * 40)
            XR.finalize_run(reg, c, {"route_grade_summary": _grade()}, ckpt_path=ck)
            self.assertEqual(XR.main(["--registry", str(reg), "verify"]), 0)
            ck.write_bytes(b"weights-TAMPERED")
            self.assertEqual(XR.main(["--registry", str(reg), "verify"]), 1)
            ck.unlink()
            self.assertEqual(XR.main(["--registry", str(reg), "verify"]), 1)

    def test_diff_reports_config_delta_only(self):
        with tempfile.TemporaryDirectory() as td:
            reg = Path(td) / "r.jsonl"
            c1 = XR.start_run(reg, _args(lr=3e-5), {"w_press": 0.1}, git_sha="a" * 40)
            c2 = XR.start_run(reg, _args(lr=1e-4), {"w_press": 0.3}, git_sha="a" * 40)
            runs = XR.join_runs(XR.read_records(reg))
            delta = XR.diff_configs(runs[c1["run_id"]], runs[c2["run_id"]])
            self.assertEqual(set(delta), {"args.lr", "reward_config.w_press"})
            self.assertEqual(delta["args.lr"], (3e-5, 1e-4))

    def test_list_cli_smoke(self):
        with tempfile.TemporaryDirectory() as td:
            reg = Path(td) / "r.jsonl"
            c = XR.start_run(reg, _args(), {}, git_sha="a" * 40)
            XR.finalize_run(reg, c, {"route_grade_summary": _grade()})
            self.assertEqual(XR.main(["--registry", str(reg), "list"]), 0)

    def test_registry_path_resolution(self):
        self.assertIsNone(XR.registry_path_for("runs/x.pt", "off"))
        self.assertIsNone(XR.registry_path_for("runs/x.pt", None))
        auto = XR.registry_path_for("/data/runs/x.pt", "auto")
        self.assertEqual(Path(auto), Path("/data/runs/experiment_registry.jsonl"))
        self.assertEqual(XR.registry_path_for("runs/x.pt", "/tmp/j.jsonl"), "/tmp/j.jsonl")

    def test_records_are_json_serializable_with_path_args(self):
        # Path objects in args (as rl_onspeed resolves some) must not break the writer.
        with tempfile.TemporaryDirectory() as td:
            reg = Path(td) / "r.jsonl"
            c = XR.start_run(reg, _args(out_ckpt=Path(td) / "x.pt"), {}, git_sha="a" * 40)
            recs = XR.read_records(reg)
            self.assertEqual(recs[0]["run_id"], c["run_id"])
            json.dumps(recs[0])


if __name__ == "__main__":
    unittest.main()
