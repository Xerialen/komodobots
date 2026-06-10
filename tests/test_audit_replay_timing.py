from __future__ import annotations

import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import audit_replay_timing as timing


class AuditReplayTimingTests(unittest.TestCase):
    def test_loads_gzip_json_and_compares_cursor_cadence(self) -> None:
        cmds_text = "\n".join(
            [
                "# komodobots.replay.v1 demo=sample frames=3 sha256=x fps=77 aligned=time state_shift=0",
                "13 0 0 24 0 0 0 5.0000 90.0000 0.0000 0 0 0 0",
                "13 1 0 24 320 0 0 5.0000 91.0000 0.0000 400 0 0 2",
                "13 2 0 24 340 0 0 5.0000 92.0000 0.0000 400 -200 0 2",
                "",
            ]
        )
        commands_doc = {
            "commands": [
                {
                    "time_s": 10.000,
                    "ed": 2,
                    "name": "/ bro",
                    "mode": 10,
                    "msec": 13,
                    "angles": {"pitch": 5.0, "yaw": 90.0, "roll": 0.0},
                    "move": {"forward": 0, "side": 0, "up": 0},
                    "buttons": 0,
                    "replay_state": {"active": True, "cursor": 0},
                },
                {
                    "time_s": 10.013,
                    "ed": 2,
                    "name": "/ bro",
                    "mode": 10,
                    "msec": 14,
                    "angles": {"pitch": 5.0, "yaw": 91.0, "roll": 0.0},
                    "move": {"forward": 400, "side": 0, "up": 0},
                    "buttons": 2,
                    "replay_state": {"active": True, "cursor": 1},
                },
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cmds = root / "sample.cmds"
            live = root / "moveprobe-commands.json.gz"
            cmds.write_text(cmds_text, encoding="utf-8")
            with gzip.open(live, "wt", encoding="utf-8") as fh:
                json.dump(commands_doc, fh)

            report = timing.audit_timing(cmds, live, bot_name="/ bro")

        self.assertEqual(report["source_frames"], 3)
        self.assertEqual(report["active_replay_rows"], 2)
        self.assertEqual(report["valid_cursor_rows"], 2)
        self.assertEqual(report["msec_delta_ms"]["max"], 1.0)
        self.assertEqual(report["cursor_time_delta_ms"]["max"], 0.0)
        self.assertEqual(report["first_active_angle_delta_deg"], {"pitch": 0.0, "yaw": 0.0, "roll": 0.0})

    def test_screen_log_parsing_path(self) -> None:
        cmds_text = "\n".join(
            [
                "# komodobots.replay.v1 demo=sample frames=1 sha256=x fps=77 aligned=time state_shift=0",
                "13 0 0 24 0 0 0 5.0000 90.0000 0.0000 0 0 0 0",
                "",
            ]
        )
        screen_log = (
            "FBMOVEPROBE_CMD time=20.000 ed=2 name=/ bro mode=10 msec=13 "
            "angles=5.000,90.000,0.000 move=0,0,0 buttons=0 impulse=0 "
            "replay=1,0,0,1,0.000,0.000,0.000,24.000,0.000,0.000 origin=0.000,0.000,24.000\n"
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cmds = root / "sample.cmds"
            log = root / "screen.log"
            cmds.write_text(cmds_text, encoding="utf-8")
            log.write_text(screen_log, encoding="utf-8")

            report = timing.audit_timing(cmds, log)

        self.assertEqual(report["rows_with_replay_state"], 1)
        self.assertEqual(report["cursor_min"], 0)
        self.assertEqual(report["first_active_angle_delta_deg"]["yaw"], 0.0)


if __name__ == "__main__":
    unittest.main()
