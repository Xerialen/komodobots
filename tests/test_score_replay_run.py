from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from score_replay_run import score_player


WITHIN = {"max_h": 32.0, "max_v": 24.0, "max_3d": 32.0}


def _replay_state(frame_count, max_cursor, h=10.0, v=5.0, d3=11.0):
    return {
        "frame_count": frame_count,
        "max_cursor": max_cursor,
        "sample_count": 5,
        "max_divergence_h_qu": h,
        "max_divergence_v_qu": v,
        "max_divergence_qu": d3,
        "final_divergence_qu": d3,
    }


class ScoreReplayRunTest(unittest.TestCase):
    def test_throttled_max_cursor_still_passes_when_complete_event_reached_end(self):
        # Codex P1: command logging is throttled so the sampled max_cursor lags
        # frame_count-1, but the completion event reached the final frame. The
        # run must score PASS, not FAIL, on coverage.
        replay_state = _replay_state(frame_count=100, max_cursor=80)
        event_player = {"final_cursor": 99, "event_counts": ["activate", "complete"]}
        result = score_player(replay_state, event_player, **WITHIN)
        self.assertTrue(result["checks"]["replayed_full_stream"])
        self.assertEqual(result["verdict"], "PASS")

    def test_no_complete_event_falls_back_to_sampled_cursor(self):
        # Without a completion event, an incomplete sampled cursor must remain a
        # coverage failure (no event cursor to trust).
        replay_state = _replay_state(frame_count=100, max_cursor=80)
        event_player = {"final_cursor": None, "event_counts": ["activate"]}
        result = score_player(replay_state, event_player, **WITHIN)
        self.assertFalse(result["checks"]["replayed_full_stream"])
        self.assertEqual(result["verdict"], "FAIL")

    def test_divergence_failure_is_independent_of_coverage(self):
        # Full coverage but divergence over threshold still fails on divergence.
        replay_state = _replay_state(frame_count=100, max_cursor=99, h=400.0, d3=410.0)
        event_player = {"final_cursor": 99, "event_counts": ["activate", "complete"]}
        result = score_player(replay_state, event_player, **WITHIN)
        self.assertTrue(result["checks"]["replayed_full_stream"])
        self.assertFalse(result["checks"]["horizontal_within"])
        self.assertEqual(result["verdict"], "FAIL")


if __name__ == "__main__":
    unittest.main()
