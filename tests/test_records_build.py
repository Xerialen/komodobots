"""Records store builder (LD-D1, issue #93): lab/server/records_build.py.

Locks the records.json contract the KPI dock and Demo view consume:

  * schema komodobots.records.v1: all four maps present, all 11 censused dm3
    routes always present (honest empty cells, never missing keys);
  * a completing run sets fastest_time / first_completion / peak_speed /
    edge_speed with the run's id, route-based canonical demo_url, a demo-relative
    event_t_s (trace server clock minus the demo's kind-0 ServerTime), and
    the census human_ref beside every bot value;
  * finish vs completion: REACHED_RL = finish (any path); completion
    additionally requires route progress >= 80% AND the route's hard-gap
    launch-edge crossing (the trick) -- a finish that arrived without the
    leap never sets first_completion;
  * aggregates: attempts / finishes / median_time_s / human_time_s (census);
  * eligibility: non-dm3 runs, runs without a route replay, unknown routes,
    and traceless runs are skipped and counted in provenance.skipped;
  * idempotency: a second rebuild over the same inputs is byte-identical
    (no wall-clock anywhere in the output -- set_at derives from the run id);
  * --append rescoring: a new faster run takes fastest_time over;
  * archive verification: demo_archived reflects the listing; null without one;
  * run_dm3.py hook: records_update_cmd is additive (append + publish) and the
    committed verdicts seed is valid komodobots.verdicts.v1.

The fixture bot run replays the committed human sng_to_rl trajectory as a bot
trace, so classification (REACHED_RL), route%~100, the launch-edge crossing
(census anchor 528.6 qu/s), and the goal arrival are all real geometry, not
mocks. route_metrics.edge_crossing's timestamp is locked against the same
anchor (edge_speed must equal edge_crossing[0]).
"""

import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "lab" / "server"))

import records_build as rb                     # noqa: E402
import run_dm3                                  # noqa: E402
from route_metrics import edge_speed, edge_crossing, final_hard_gap  # noqa: E402

EVID = REPO / "experiments" / "dm3_sng_to_rl_observability" / "evidence"
HUMAN_CMDS = EVID / "dm3_sng_to_rl.cmds"
CENSUS = (REPO / "experiments" / "nav_doctrine" / "evidence"
          / "trick-census" / "census.json")
RL = (1591.0, 526.0, -88.0)
SERVER_START = 100.0     # fixture demo kind-0 ServerTime (seconds)


def human_points():
    pts = []
    for ln in HUMAN_CMDS.read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        p = ln.split()
        if len(p) < 14:
            continue
        pts.append((float(p[1]), float(p[2]), float(p[3]),
                    math.hypot(float(p[4]), float(p[5]))))
    return pts


def write_run(runs_dir: Path, run_id: str, *, map_name="dm3",
              replay="bots/replay/dm3_sng_to_rl.cmds", trace_rows=None,
              events=True, t0=SERVER_START + 5.0, dt=0.0125):
    """A synthetic lab run dir: run.env (+ events.txt) (+ trace.csv)."""
    d = runs_dir / run_id
    d.mkdir(parents=True)
    (d / "run.env").write_text(
        f"RUN_ID={run_id}\nMAP={map_name}\nMOVEPROBE_MODE=21\n"
        f"MOVEPROBE_REPLAY_FILE={replay}\n")
    if events:
        ev = {"kind": 0, "data": {"Data": {"ServerTime": SERVER_START}}}
        (d / "events.txt").write_text(json.dumps(ev) + "\n")
    if trace_rows is not None:
        lines = ["i,t,x,y,z,vx,vy,vz,vh,onground,fwd,side,up,yaw,yaw_rate,"
                 "dir_speed,floor_z,height_above_floor,over_void,dist_to_rl,"
                 "replay_cursor,divergence_qu"]
        for i, (x, y, z, vh) in enumerate(trace_rows):
            t = t0 + i * dt
            drl = math.sqrt((x - RL[0]) ** 2 + (y - RL[1]) ** 2 + (z - RL[2]) ** 2)
            lines.append(f"{i},{t:.4f},{x},{y},{z},0,0,0,{vh},1,0,0,0,0,0,0,"
                         f"-176.0,1.0,0,{drl:.1f},0,0.0")
        (d / "trace.csv").write_text("\n".join(lines) + "\n")
    return d


class RecordsBuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.human = human_points()
        cls.census = json.loads(CENSUS.read_text())

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="records-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.runs = self.tmp / "lab-runs"
        self.runs.mkdir()

    def build(self, archive_paths=None, force=None):
        return rb.build(self.runs, archive_paths, force_run_id=force)

    def completing_run(self, run_id, dt=0.0125, **kw):
        """The committed human trajectory replayed as a bot trace."""
        return write_run(self.runs, run_id, trace_rows=self.human, dt=dt, **kw)

    # ---------------------------------------------------------------- schema

    def test_schema_shape_and_honest_empty_state(self):
        data = self.build()
        self.assertEqual(data["schema"], "komodobots.records.v1")
        self.assertEqual(sorted(data["maps"]), sorted(["dm3", "dm2", "frobodm2", "trick"]))
        self.assertEqual(data["maps"]["dm2"]["routes"], {})
        routes = data["maps"]["dm3"]["routes"]
        self.assertEqual(sorted(routes), sorted(self.census))   # all 11, always
        ent = routes["sng_to_rl"]
        self.assertEqual({k: v for k, v in ent["records"].items()},
                         {k: None for k in rb.RECORD_KINDS})    # no record yet
        self.assertEqual(ent["aggregates"]["attempts"], 0)
        self.assertEqual(ent["aggregates"]["human_time_s"],
                         self.census["sng_to_rl"]["duration_s"])

    # ------------------------------------------------------------- a real run

    def test_completing_run_sets_all_four_records(self):
        self.completing_run("20260608T120000Z")
        data = self.build()
        ent = data["maps"]["dm3"]["routes"]["sng_to_rl"]
        agg = ent["aggregates"]
        self.assertEqual(agg["attempts"], 1)
        self.assertEqual(agg["finishes"], 1)
        self.assertAlmostEqual(agg["median_time_s"],
                               ent["records"]["fastest_time"]["value"])

        for kind in rb.RECORD_KINDS:
            rec = ent["records"][kind]
            self.assertIsNotNone(rec, kind)
            self.assertEqual(rec["run_id"], "20260608T120000Z")
            self.assertEqual(rec["demo_url"],
                             "/demos/files/non-games/lab/Komodobots/dm3/"
                             "sng_to_rl__20260608T120000Z.mvd")
            self.assertEqual(rec["set_at"], "2026-06-08")
            self.assertIsNone(rec["demo_archived"])     # no listing given
            self.assertIsNotNone(rec["human_ref"])

        # census anchors beside the bot values, pointing at the archived
        # human reference demo
        self.assertEqual(ent["records"]["fastest_time"]["human_ref"]["value"],
                         self.census["sng_to_rl"]["duration_s"])
        self.assertEqual(ent["records"]["fastest_time"]["human_ref"]["demo_url"],
                         "/demos/files/non-games/lab/Komodobots/human/"
                         "dm3_sng_to_rl.qwd")
        gap = final_hard_gap(self.census["sng_to_rl"])
        self.assertEqual(ent["records"]["edge_speed"]["human_ref"]["value"],
                         gap["human_speed_at_edge"])
        # the human trajectory crosses its own censused edge at the census speed
        self.assertAlmostEqual(ent["records"]["edge_speed"]["value"], 528.6,
                               delta=0.5)

    def test_event_t_s_is_demo_relative(self):
        self.completing_run("20260608T120000Z")    # trace t starts at +5 s
        data = self.build()
        recs = data["maps"]["dm3"]["routes"]["sng_to_rl"]["records"]
        # arrival ~ human duration (8.99 s) after the 5 s pre-roll
        ft = recs["fastest_time"]
        self.assertIsNotNone(ft["event_t_s"])
        self.assertAlmostEqual(ft["event_t_s"], 5.0 + ft["value"], places=3)
        # edge crossing strictly before arrival, after demo start
        self.assertGreater(ft["event_t_s"], recs["edge_speed"]["event_t_s"])
        self.assertGreater(recs["edge_speed"]["event_t_s"], 0)

    def test_event_t_s_null_without_server_time(self):
        self.completing_run("20260608T120000Z", events=False)
        data = self.build()
        ft = data["maps"]["dm3"]["routes"]["sng_to_rl"]["records"]["fastest_time"]
        self.assertIsNotNone(ft)
        self.assertIsNone(ft["event_t_s"])         # honest absence, not 0

    # -------------------------------------------------- finish vs completion

    def test_off_route_finish_never_sets_first_completion(self):
        # teleport-free straight line from the start pad to the goal: arrives
        # (REACHED_RL = finish) but never crosses the route's launch edge
        # (closest approach ~443 qu from the censused edge point), so it did
        # not do the trick -> not a completion.
        start = self.human[0]
        n = 400
        rows = []
        for i in range(n + 1):
            f = i / n
            rows.append((start[0] + f * (RL[0] - start[0]),
                         start[1] + f * (RL[1] - start[1]),
                         start[2] + f * (RL[2] - start[2]), 200.0))
        write_run(self.runs, "20260608T130000Z", trace_rows=rows)
        data = self.build()
        ent = data["maps"]["dm3"]["routes"]["sng_to_rl"]
        self.assertEqual(ent["aggregates"]["finishes"], 1)
        self.assertIsNotNone(ent["records"]["fastest_time"])    # finish counts
        self.assertIsNone(ent["records"]["first_completion"])   # not on-route

    # ------------------------------------------------------------ eligibility

    def test_ineligible_runs_are_skipped_and_counted(self):
        write_run(self.runs, "20260608T140000Z", map_name="trick")
        write_run(self.runs, "20260608T140100Z", replay="")
        write_run(self.runs, "20260608T140200Z", replay="bots/replay/dm3_nosuch.cmds")
        write_run(self.runs, "20260608T140300Z")               # no trace.csv
        data = self.build()
        self.assertEqual(data["provenance"]["runs_scored"], 0)
        self.assertEqual(data["provenance"]["skipped"],
                         {"not_dm3": 1, "no_route_replay": 1,
                          "unknown_route": 1, "no_trace": 1})

    # ------------------------------------------------------------ idempotency

    def test_rebuild_is_idempotent_and_clock_free(self):
        self.completing_run("20260608T120000Z")
        first = json.dumps(self.build(), indent=2, sort_keys=False)
        second = json.dumps(self.build(), indent=2, sort_keys=False)
        self.assertEqual(first, second)            # cache hit path
        # force a full rescore: still byte-identical (no wall-clock anywhere)
        third = json.dumps(self.build(force="20260608T120000Z"),
                           indent=2, sort_keys=False)
        self.assertEqual(first, third)

    def test_append_improves_fastest_time(self):
        self.completing_run("20260608T120000Z")
        before = self.build()
        # a second run, same trajectory at double tick rate = half the time
        self.completing_run("20260609T120000Z", dt=0.00625)
        after = self.build(force="20260609T120000Z")
        ft_b = before["maps"]["dm3"]["routes"]["sng_to_rl"]["records"]["fastest_time"]
        ft_a = after["maps"]["dm3"]["routes"]["sng_to_rl"]["records"]["fastest_time"]
        self.assertEqual(ft_a["run_id"], "20260609T120000Z")
        self.assertAlmostEqual(ft_a["value"], ft_b["value"] / 2.0, places=2)
        agg = after["maps"]["dm3"]["routes"]["sng_to_rl"]["aggregates"]
        self.assertEqual((agg["attempts"], agg["finishes"]), (2, 2))
        # first_completion is historical: the FIRST run keeps it
        fc = after["maps"]["dm3"]["routes"]["sng_to_rl"]["records"]["first_completion"]
        self.assertEqual(fc["run_id"], "20260608T120000Z")

    # ------------------------------------------------------- archive listing

    def test_demo_archived_reflects_listing(self):
        self.completing_run("20260608T120000Z")
        listing = {"dm3/sng_to_rl__20260608T120000Z.mvd"}
        ft = self.build(archive_paths=listing)["maps"]["dm3"]["routes"][
            "sng_to_rl"]["records"]["fastest_time"]
        self.assertIs(ft["demo_archived"], True)
        ft = self.build(archive_paths=set())["maps"]["dm3"]["routes"][
            "sng_to_rl"]["records"]["fastest_time"]
        self.assertIs(ft["demo_archived"], False)

    def test_archive_list_file_normalization(self):
        f = self.tmp / "listing.txt"
        f.write_text("/mnt/usb-ssd/non-games/lab/Komodobots/dm3/a.mvd\n"
                     "dm3\\b.mvd\nnot-a-demo.txt\n\n")
        self.assertEqual(rb.archive_paths_from_file(f),
                         {"dm3/a.mvd", "dm3/b.mvd"})

    # ------------------------------------------------------------- hook + seed

    def test_run_dm3_hook_command_is_additive_append_publish(self):
        cmd = run_dm3.records_update_cmd("20260608T120000Z")
        self.assertIn("--append", cmd)
        self.assertIn("20260608T120000Z", cmd)
        self.assertIn("--publish", cmd)
        self.assertTrue(str(cmd[1]).endswith("records_build.py"))

    def test_verdicts_seed_is_valid_v1(self):
        seed = json.loads(rb.VERDICTS_SEED.read_text())
        self.assertEqual(seed["schema"], "komodobots.verdicts.v1")
        for route, v in seed["routes"].items():
            self.assertIn(route, self.census)
            self.assertIn(v["verdict"], ("pass", "close", "fail"))
            self.assertIn("note", v)
            self.assertIn("run_id", v)
            self.assertIn("date", v)

    # ------------------------------------------------- edge_crossing contract

    def test_edge_crossing_matches_edge_speed_on_census_anchor(self):
        rows = [{"t": 1.0 + i * 0.0125, "x": x, "y": y, "z": z, "vh": vh}
                for i, (x, y, z, vh) in enumerate(self.human)]
        gap = final_hard_gap(self.census["sng_to_rl"])
        # the route's one sanctioned teleporter: without it legit_segment
        # truncates the trajectory at the throw, before the edge
        teles = tuple((t["from"][0], t["from"][1])
                      for t in self.census["sng_to_rl"]["teleports"])
        speed = edge_speed(rows, gap, teles)
        crossing = edge_crossing(rows, gap, teles)
        self.assertAlmostEqual(speed, 528.6, delta=0.5)   # census anchor
        self.assertEqual(crossing[0], speed)
        self.assertGreater(crossing[1], 1.0)              # a real row t

    def test_edge_crossing_without_t_reports_none_timestamp(self):
        gap = {"edge": [0.0, 0.0, 0.0], "land": [200.0, 0.0, -50.0]}
        rows = [{"x": -30.0, "y": 0.0, "z": 0.0, "vh": 400.0},
                {"x": 5.0, "y": 0.0, "z": 0.0, "vh": 405.0}]
        self.assertEqual(edge_crossing(rows, gap), (405.0, None))
        self.assertEqual(edge_speed(rows, gap), 405.0)


if __name__ == "__main__":
    unittest.main()
