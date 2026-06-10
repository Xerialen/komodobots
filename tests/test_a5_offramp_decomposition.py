"""Regression tests for experiments/a5_distance_standstill/a5_offramp_decomposition.py.

Codex PR #125 blocker: an explicit ``--src`` pointing at the committed
gzip-compressed sweep artifact (``carve-sweep-results.json.gz``) crashed with
UnicodeDecodeError because every existing source file was read as plain-text
JSON. Loading is now centralized in ``_load_json``: a ``.gz`` suffix is read
through ``gzip.open(..., "rt", encoding="utf-8")``, anything else as plain
UTF-8 JSON. These tests pin both paths plus the original missing-plain-json
fallback to ``<src>.gz``.
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    REPO_ROOT / "experiments" / "a5_distance_standstill" / "a5_offramp_decomposition.py"
)
COMMITTED_GZ = (
    REPO_ROOT / "experiments" / "a5_distance_standstill" / "carve-sweep-results.json.gz"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("a5_offramp_decomposition", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


offramp = _load_module()


def minimal_doc() -> dict:
    """Smallest results document main() can decompose end to end."""
    return {
        "results": [
            {
                "name": "cfg-a",
                "config": {"launch_vh": 430},
                "attempts": [
                    {"max_vh": 400},
                    {
                        "max_vh": 435,
                        "release": {
                            "timeout": False,
                            "d_lip": 20,
                            "vh": 433,
                            "heading": -9.0,
                            "pos": [-3580.0, 3824.0, -488.0],
                        },
                        "lip": {
                            "x": -3300.0,
                            "y": 3700.0,
                            "vh": 433,
                            "heading": -9.0,
                            "jump": 1,
                        },
                    },
                ],
            }
        ]
    }


def run_cli(src: Path, out: Path) -> dict:
    """Invoke main() as the CLI would and return the parsed output document."""
    argv = ["a5_offramp_decomposition.py", "--src", str(src), "--out", str(out)]
    with mock.patch.object(sys, "argv", argv), redirect_stdout(StringIO()):
        offramp.main()
    return json.loads(out.read_text(encoding="utf-8"))


class LoadJsonTests(unittest.TestCase):
    def test_plain_json_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc.json"
            path.write_text(json.dumps({"results": []}), encoding="utf-8")
            self.assertEqual(offramp._load_json(path), {"results": []})

    def test_gzip_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc.json.gz"
            with gzip.open(path, "wt", encoding="utf-8") as f:
                json.dump({"results": []}, f)
            self.assertEqual(offramp._load_json(path), {"results": []})


class ExplicitSrcCliTests(unittest.TestCase):
    """The advertised --src invocations must run end to end."""

    def test_explicit_gz_src(self) -> None:
        """Regression: --src <file>.json.gz used to raise UnicodeDecodeError."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "sweep.json.gz"
            with gzip.open(src, "wt", encoding="utf-8") as f:
                json.dump(minimal_doc(), f)
            out_doc = run_cli(src, Path(tmp) / "out.json")
            self.assertEqual(out_doc["n_attempts"], 2)
            self.assertEqual(out_doc["arc_classes"], {"NO-LIP": 1, "WOULD-LAND": 1})

    def test_explicit_plain_json_src(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "sweep.json"
            src.write_text(json.dumps(minimal_doc()), encoding="utf-8")
            out_doc = run_cli(src, Path(tmp) / "out.json")
            self.assertEqual(out_doc["n_attempts"], 2)

    def test_gz_and_plain_src_agree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "sweep.json"
            plain.write_text(json.dumps(minimal_doc()), encoding="utf-8")
            gz = Path(tmp) / "other.json.gz"
            with gzip.open(gz, "wt", encoding="utf-8") as f:
                json.dump(minimal_doc(), f)
            self.assertEqual(
                run_cli(plain, Path(tmp) / "out-plain.json"),
                run_cli(gz, Path(tmp) / "out-gz.json"),
            )

    def test_missing_plain_json_falls_back_to_gz(self) -> None:
        """Original zero-arg behavior: missing <src>.json falls back to <src>.json.gz."""
        with tempfile.TemporaryDirectory() as tmp:
            gz = Path(tmp) / "sweep.json.gz"
            with gzip.open(gz, "wt", encoding="utf-8") as f:
                json.dump(minimal_doc(), f)
            out_doc = run_cli(Path(tmp) / "sweep.json", Path(tmp) / "out.json")
            self.assertEqual(out_doc["n_attempts"], 2)


class CommittedArtifactTests(unittest.TestCase):
    """The exact invocation from the PR body / Codex repro must work."""

    def test_committed_carve_sweep_gz_as_explicit_src(self) -> None:
        self.assertTrue(COMMITTED_GZ.exists(), f"missing artifact: {COMMITTED_GZ}")
        with tempfile.TemporaryDirectory() as tmp:
            out_doc = run_cli(COMMITTED_GZ, Path(tmp) / "carve-test-out.json")
            self.assertGreater(out_doc["n_attempts"], 0)
            self.assertIn("carve_funnel", out_doc)


if __name__ == "__main__":
    unittest.main()
