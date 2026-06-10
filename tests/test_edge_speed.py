"""edge_speed: the launch-edge crossing metric (issue #63).

Locks the sprint's headline-metric foundations against the committed evidence:

  * census anchor: the human dm3 sng_to_rl replay crosses its final hard gap
    at exactly the census numbers -- edge speed 528.6 qu/s, required 525.3;
  * route parameterization: sng_shortcut2 (458.8), and the multi-crossing
    loop routes hilljump (528.9, lip traversed 3x) and rl_to_bridge (467.3,
    2x) all reproduce their census final-hard-gap anchors the same way;
  * geometric crossing semantics: bot-shaped trajectories that never cross
    return None (not 0), teleport-sized steps can never register a crossing,
    crossings outside the corridor / off the lip height are rejected, and the
    LAST crossing wins -- the launch that decides the attempt, so an early
    fast crossing of a multi-crossed lip can never fake a pass for a slow
    goal-gating launch (Codex PR #82 P2);
  * verify_route reports the metric (DoD: "verify_route --route sng_to_rl
    reports the edge metric") without touching the existing output lines.

The pmove-validation sim anchor (sim 529.0 vs recorded 528.6 qu/s at the
census crossing; the report's own pair is 529.1/528.2 at its frame-511
convention) is documented in the A0 PR body: artifacts/pmove-validation/ is
local-only (gitignored), so it cannot be locked in CI.
"""

import csv
import json
import math
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
RUNS = REPO / "artifacts" / "lab-runs"
NAV_EVID = REPO / "experiments" / "nav_doctrine" / "evidence"
CENSUS = NAV_EVID / "trick-census" / "census.json"

sys.path.insert(0, str(SCRIPTS))

from route_metrics import edge_speed, final_hard_gap  # noqa: E402

# Synthetic gap: launch plane is x = 0 (edge->land direction +x), lip at z 0.
GAP = {"edge": [0.0, 0.0, 0.0], "land": [200.0, 0.0, -50.0]}


def run(points, vh=500.0):
    """Rows from (x, y, z) points at constant reported speed."""
    return [{"x": x, "y": y, "z": z, "vh": vh} for x, y, z in points]


def load_cmds_rows(path):
    """Human replay -> metric rows (vh = |(vx, vy)|, the census convention)."""
    rows = []
    for ln in open(path):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        p = ln.split()
        if len(p) < 14:
            continue
        rows.append({"x": float(p[1]), "y": float(p[2]), "z": float(p[3]),
                     "vh": math.hypot(float(p[4]), float(p[5]))})
    return rows


class TestCensusAnchors(unittest.TestCase):
    """The two locked anchors, from committed evidence only (CI-clean)."""

    def setUp(self):
        self.census = json.loads(CENSUS.read_text())

    def _route_edge_speed(self, name):
        ent = self.census[name]
        gap = final_hard_gap(ent)
        rows = load_cmds_rows(NAV_EVID / "replay" / f"dm3_{name}.cmds")
        tele = tuple((t["from"][0], t["from"][1]) for t in ent["teleports"])
        return gap, edge_speed(rows, gap, tele_entrances=tele)

    def test_sng_to_rl_anchor_528_6(self):
        gap, v = self._route_edge_speed("sng_to_rl")
        # the census content itself (the numbers the sprint gate quotes)
        self.assertEqual(gap["required_speed"], 525.3)
        self.assertEqual(gap["human_speed_at_edge"], 528.6)
        # the metric reproduces the census anchor exactly
        self.assertIsNotNone(v)
        self.assertEqual(round(v, 1), 528.6)

    def test_sng_shortcut2_anchor_458_8(self):
        gap, v = self._route_edge_speed("sng_shortcut2")
        self.assertEqual(gap["required_speed"], 437.0)
        self.assertEqual(gap["human_speed_at_edge"], 458.8)
        self.assertIsNotNone(v)
        self.assertEqual(round(v, 1), 458.8)

    def test_multi_crossing_routes_measure_the_final_gap(self):
        # hilljump crosses its final gap's plane 3 times (the route bounces
        # over one trench lip), rl_to_bridge twice. The census's final hard
        # gap is the LAST traversal; an earlier traversal must not be the
        # measurement (Codex PR #82 P2: it could fake a pass).
        for name in ("hilljump", "rl_to_bridge"):
            with self.subTest(route=name):
                gap, v = self._route_edge_speed(name)
                self.assertIsNotNone(v)
                self.assertEqual(round(v, 1), gap["human_speed_at_edge"])

    def test_sng_to_rl_without_sanctioned_teleporter_never_crosses(self):
        # The human route teleports once (sanctioned). Without sanctioning it,
        # legit_segment truncates there and the edge is never reached: None.
        ent = self.census["sng_to_rl"]
        rows = load_cmds_rows(NAV_EVID / "replay" / "dm3_sng_to_rl.cmds")
        self.assertIsNone(edge_speed(rows, final_hard_gap(ent)))


class TestCrossingSemantics(unittest.TestCase):
    def test_speed_at_first_row_past_edge(self):
        # walk the plane at x=0 from -35; rows get distinct speeds so the
        # asserted value identifies WHICH row was measured: the first row
        # at/past the plane (x=+2), the census edge-frame convention.
        pts = [(-35.0, 0.0, 0.0), (-28.0, 0.0, 0.0), (-21.0, 0.0, 0.0),
               (-14.0, 0.0, 0.0), (-7.0, 0.0, 0.0), (2.0, 0.0, 0.0),
               (9.0, 0.0, 0.0)]
        rows = [{"x": x, "y": y, "z": z, "vh": 400.0 + i}
                for i, (x, y, z) in enumerate(pts)]
        self.assertEqual(edge_speed(rows, GAP), 405.0)

    def test_never_crossing_returns_none_not_zero(self):
        v = edge_speed(run([(-300.0, 0.0, 0.0), (-200.0, 0.0, 0.0),
                            (-101.0, 0.0, 0.0)]), GAP)
        self.assertIsNone(v)
        self.assertNotEqual(v, 0.0)

    def test_short_input_returns_none(self):
        self.assertIsNone(edge_speed([], GAP))
        self.assertIsNone(edge_speed(run([(5.0, 0.0, 0.0)]), GAP))
        self.assertIsNone(edge_speed(run([(-5.0, 0.0, 0.0)]), GAP))

    def test_crossing_outside_corridor_rejected(self):
        # crosses the infinite plane 200 qu cross-track of the edge point:
        # a different part of the map, not this gap (corridor is 160).
        self.assertIsNone(edge_speed(run([(-5.0, 200.0, 0.0),
                                          (2.0, 200.0, 0.0)]), GAP))

    def test_crossing_below_the_lip_rejected(self):
        # fell into the pit (> 100 qu below the lip), then drifted across the
        # plane: that is not a launch (the census DEEP_DROP criterion).
        self.assertIsNone(edge_speed(run([(-5.0, 0.0, -150.0),
                                          (2.0, 0.0, -150.0)]), GAP))

    def test_teleport_step_cannot_register_a_crossing(self):
        approach = [(-80.0, 0.0, 0.0), (-72.0, 0.0, 0.0), (-64.0, 0.0, 0.0)]
        thrown = approach + [(280.0, 0.0, 0.0), (288.0, 0.0, 0.0)]
        # stray teleport: legit_segment truncates before the plane -> None
        self.assertIsNone(edge_speed(run(thrown), GAP))
        # sanctioned teleport: landing stays in the segment, but the throw
        # itself is not player movement, so it is not a crossing either
        self.assertIsNone(edge_speed(run(thrown), GAP,
                                     tele_entrances=((-64.0, 0.0),)))

    def test_last_crossing_wins(self):
        # cross fast early, come back behind the plane, cross again slow: the
        # LAST crossing is the measurement -- the launch that decides the
        # attempt. An early fast crossing of a multi-crossed lip must never
        # report a passing edge speed for a slow goal-gating launch
        # (Codex PR #82 P2).
        rows = (run([(-9.0, 0.0, 0.0), (2.0, 0.0, 0.0)], vh=600.0)
                + run([(-9.0, 0.0, 0.0), (2.0, 0.0, 0.0)], vh=300.0))
        self.assertEqual(edge_speed(rows, GAP), 300.0)

    def test_no_gap_returns_none(self):
        self.assertIsNone(edge_speed(run([(-5.0, 0.0, 0.0),
                                          (2.0, 0.0, 0.0)]), None))


class TestFinalHardGap(unittest.TestCase):
    def test_selects_last_hard_gap(self):
        ent = {"gaps": [{"hard": False, "id": 0}, {"hard": True, "id": 1},
                        {"hard": True, "id": 2}]}
        self.assertEqual(final_hard_gap(ent)["id"], 2)

    def test_none_when_no_hard_gaps(self):
        self.assertIsNone(final_hard_gap({"gaps": [{"hard": False}]}))
        self.assertIsNone(final_hard_gap({"gaps": []}))


# --- verify_route reporting (DoD) -------------------------------------------

TRACE_FIELDS = ["t", "x", "y", "z", "vh", "onground", "over_void", "dist_to_rl"]
SNG = (-895.0, -129.0)
# default-route launch edge / landing (dm3_jump_geom.json, the validated ref)
EDGE = (1476.9, 52.6, 5.5)
LAND = (1614.8, 362.9)


def write_trace(run_id, rows):
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "trace.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=TRACE_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return run_dir


def trace_row(i, x, y, z, vh):
    return {"t": i / 100.0, "x": round(x, 3), "y": round(y, 3), "z": round(z, 3),
            "vh": vh, "onground": 1, "over_void": 0, "dist_to_rl": 2400.0}


class TestVerifyRouteReportsEdge(unittest.TestCase):
    def setUp(self):
        self.run_id = f"_test_edge_{uuid.uuid4().hex[:8]}"

    def tearDown(self):
        shutil.rmtree(RUNS / self.run_id, ignore_errors=True)

    def _score(self, rows, *args):
        write_trace(self.run_id, rows)
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "verify_route.py"), self.run_id, *args],
            cwd=REPO, capture_output=True, text=True,
        )

    def test_no_crossing_reports_none(self):
        # walks off the SNG pad, never near the edge (the gate test's shape)
        rows = [trace_row(i, SNG[0] + 4.0 * i, SNG[1], 0.0, 200.0)
                for i in range(60)]
        out = self._score(rows)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("edge_speed[crossing]: None (0/1 attempts crossed the "
                      "launch edge; required >= 526.2)", out.stdout)

    def test_crossing_value_reported(self):
        # straight legit path (steps < TELEPORT_JUMP) from the SNG pad to just
        # short of the edge, then across the launch plane at vh 555.
        ux, uy = LAND[0] - EDGE[0], LAND[1] - EDGE[1]
        n = math.hypot(ux, uy)
        ux, uy = ux / n, uy / n
        bx, by = EDGE[0] - 30.0 * ux, EDGE[1] - 30.0 * uy   # 30 qu before the lip
        steps = 16
        pts = [(SNG[0] + (bx - SNG[0]) * f / steps,
                SNG[1] + (by - SNG[1]) * f / steps, EDGE[2])
               for f in range(steps + 1)]
        pts += [(EDGE[0] + 5.0 * ux, EDGE[1] + 5.0 * uy, EDGE[2]),
                (EDGE[0] + 20.0 * ux, EDGE[1] + 20.0 * uy, EDGE[2])]
        rows = [trace_row(i, x, y, z, 555.0) for i, (x, y, z) in enumerate(pts)]
        out = self._score(rows)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("edge_speed[crossing]: best 555.0 qu/s (1/1 attempts "
                      "crossed the launch edge; required >= 526.2)", out.stdout)

    def test_metrics_flag_appends_edge_field(self):
        rows = [trace_row(i, SNG[0] + 4.0 * i, SNG[1], 0.0, 200.0)
                for i in range(60)]
        out = self._score(rows, "--metrics")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn(" edge=None", out.stdout)


if __name__ == "__main__":
    unittest.main()
