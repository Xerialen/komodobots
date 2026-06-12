"""Map-entity importer tests for lab/tools/import_map_entities.py.

The real import source is the sibling mvd_analyzer checkout, but tests use a
tiny temporary git repo so CI does not need that checkout.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lab" / "tools"))

import import_map_entities as ime  # noqa: E402


def _run_git(repo: Path, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout.strip()


def _git_bytes(repo: Path, args: list[str]) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed: "
            f"{proc.stderr.decode('utf-8', errors='replace')}"
        )
    return proc.stdout


def _write_source_map(repo: Path, map_name: str, entities: list[dict]) -> None:
    path = repo / "mvd-analytics" / "mapents" / "data" / f"{map_name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "map": map_name,
        "version": 1,
        "entities": entities,
    }, indent=1) + "\n", encoding="utf-8")


class ImportMapEntitiesTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.mkdtemp()
        self.tmp = Path(self._td)
        self.source = self.tmp / "mvd_analyzer"
        self.source.mkdir()
        _run_git(self.source, ["init"])
        _run_git(self.source, ["config", "user.email", "test@example.invalid"])
        _run_git(self.source, ["config", "user.name", "Test"])

        _write_source_map(self.source, "dm3", [
            {"type": "item", "class": "weapon_rocketlauncher", "kind": "rl",
             "x": 1, "y": 2, "z": 3},
            {"type": "spawn", "class": "info_player_deathmatch",
             "x": 4, "y": 5, "z": 6},
        ])
        _write_source_map(self.source, "ztricks", [
            {"type": "teleportDst", "class": "info_teleport_destination",
             "x": -3520, "y": 3712, "z": -480},
        ])
        _run_git(self.source, ["add", "."])
        _run_git(self.source, ["commit", "--no-verify", "-m", "seed mapents"])
        self.head = _run_git(self.source, ["rev-parse", "HEAD"])

    def tearDown(self):
        import shutil
        shutil.rmtree(self._td, ignore_errors=True)

    def test_import_writes_per_map_files_and_index(self):
        out = self.tmp / "out"
        written = ime.import_map_entities(
            source_repo=self.source,
            ref="HEAD",
            out_dir=out,
            maps=("dm3", "ztricks"),
        )

        self.assertEqual(
            sorted(p.name for p in written),
            ["dm3.json", "index.json", "ztricks.json"],
        )
        index = json.loads((out / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["schema"], ime.SCHEMA)
        self.assertEqual(index["source"]["commit"], self.head)
        self.assertEqual(index["source"]["path"], ime.SOURCE_PATH)
        self.assertEqual([m["map"] for m in index["maps"]], ["dm3", "ztricks"])
        self.assertEqual(index["maps"][0]["entities"], 2)
        self.assertEqual(index["maps"][0]["types"], {"item": 1, "spawn": 1})
        self.assertEqual(index["maps"][1]["entities"], 1)
        self.assertEqual(index["maps"][1]["types"], {"teleportDst": 1})

        source_raw = _git_bytes(
            self.source,
            ["show", "HEAD:mvd-analytics/mapents/data/ztricks.json"],
        )
        self.assertEqual((out / "ztricks.json").read_bytes(), source_raw)

    def test_missing_map_file_fails_loud(self):
        with self.assertRaises(ime.ImportErrorWithContext):
            ime.import_map_entities(
                source_repo=self.source,
                ref="HEAD",
                out_dir=self.tmp / "out",
                maps=("missing",),
            )

    def test_validate_rejects_missing_coordinate(self):
        with self.assertRaises(ime.ImportErrorWithContext):
            ime.validate_map_entity_doc("bad", {
                "map": "bad",
                "version": 1,
                "entities": [{"type": "item", "class": "item_health", "x": 1, "y": 2}],
            })

    def test_default_maps_include_ztricks(self):
        self.assertIn("ztricks", ime.DEFAULT_MAPS)


if __name__ == "__main__":
    unittest.main()
