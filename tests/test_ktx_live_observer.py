"""Conservative live observer tests (LD-H3.7, issue #183)."""

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lab" / "server"))

import ktx_live_observer as live  # noqa: E402


def frame(sequence: int = 1) -> dict:
    return {
        "source": "qtv-scoreboard",
        "sequence": sequence,
        "received_at": "2026-06-14T20:00:00Z",
        "status": "live",
        "match_id": "dm2-final",
        "map": "dm2",
        "mode": "team",
        "server_time": 123.4,
        "clock": 456.7,
        "duration": 1200,
        "teams": [
            {"name": "The Vipers", "score": 12},
            {"name": "The Rangers", "score": 10},
        ],
        "players": [
            {"slot": 1, "name": "viper-1", "team": "The Vipers", "frags": 5, "deaths": 3, "ping": 20},
            {"slot": 5, "name": "ranger-1", "team": "The Rangers", "frags": 4, "deaths": 4, "ping": 25},
        ],
    }


class KtxLiveObserverTest(unittest.TestCase):
    def test_live_frame_emits_only_provisional_safe_fields(self):
        data = live.normalize_live_frame(frame())

        self.assertEqual(data["schema"], "komodobots.ktx_live_observer.v1")
        self.assertTrue(data["source"]["provisional"])
        self.assertFalse(data["source"]["final"])
        self.assertEqual(data["match"]["map"], "dm2")
        self.assertEqual(data["teams"][0]["score"], 12)
        self.assertEqual(data["players"][0]["frags"], 5)
        self.assertIn("damage_done", data["unavailable_until_final"])
        self.assertEqual(data["warnings"], [])

    def test_post_game_only_fields_are_ignored_not_faked(self):
        raw = frame()
        raw["damage_done"] = 999
        raw["teams"][0]["damage_done"] = 888
        raw["players"][0]["damage_done"] = 777
        raw["players"][0]["health_pickups"] = 3

        data = live.normalize_live_frame(raw)

        self.assertNotIn("damage_done", data["match"])
        self.assertNotIn("damage_done", data["teams"][0])
        self.assertNotIn("damage_done", data["players"][0])
        self.assertNotIn("health_pickups", data["players"][0])
        warnings = "; ".join(data["warnings"])
        self.assertIn("ignored post-game-only live match field: damage_done", warnings)
        self.assertIn("ignored post-game-only live team field: damage_done", warnings)
        self.assertIn("ignored post-game-only live player field: health_pickups", warnings)

    def test_stale_reconnect_frame_is_ignored(self):
        state = live.LiveObserverState()
        first = state.apply_frame(frame(sequence=10))
        stale = state.apply_frame(frame(sequence=9))

        self.assertIs(stale, first)
        self.assertEqual(state.last_sequence, 10)
        self.assertEqual(state.stale_frames, 1)
        self.assertIn("ignored stale live frame sequence=9", stale["warnings"])

    def test_disconnect_marks_snapshot_stale(self):
        state = live.LiveObserverState()
        state.apply_frame(frame(sequence=2))
        snap = state.mark_disconnected()

        self.assertEqual(snap["status"], "disconnected")
        self.assertTrue(snap["stale"])
        self.assertIn("observer disconnected", "; ".join(snap["warnings"]))

    def test_disconnect_before_first_frame_is_explicit(self):
        snap = live.LiveObserverState().mark_disconnected()

        self.assertEqual(snap["status"], "disconnected")
        self.assertTrue(snap["stale"])
        self.assertEqual(snap["players"], [])

    def test_cli_normalizes_one_frame(self):
        with tempfile.TemporaryDirectory(prefix="live-observer-") as tmp:
            src = Path(tmp) / "frame.json"
            src.write_text(json.dumps(frame()), encoding="utf-8")
            buf = StringIO()
            with redirect_stdout(buf):
                self.assertEqual(live.main([str(src)]), 0)
            self.assertIn("komodobots.ktx_live_observer.v1", buf.getvalue())

    def test_optional_ktx_event_stream_is_read_only_and_disabled(self):
        proposal = live.OPTIONAL_KTX_EVENT_STREAM_PROPOSAL
        self.assertEqual(proposal["default"], "disabled")
        self.assertIn("read-only", proposal["direction"])
        self.assertIn("no bot/moveprobe", proposal["exclusions"])


if __name__ == "__main__":
    unittest.main()
