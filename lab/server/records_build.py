#!/usr/bin/env python3
"""Records store builder for the lab dashboard (LD-D1, issue #93).

Builds `records.json` -- the single source of truth the KPI dock and Demo view
consume: the record-holding value per (map, route, kind), each linked to its
demo file and the event timestamp inside that demo, plus per-route aggregates.
Stdlib only. Run artifacts are the source of truth; the registry is always
rebuildable from them, so the UI treats records.json as read-only data.

Schema `komodobots.records.v1`
------------------------------
{
  "schema": "komodobots.records.v1",
  "maps": {
    "<map>": {                      # dm3, dm2, frobodm2, trick (all present;
      "routes": {                   #  non-dm3 maps have empty route sets)
        "<route>": {                # all 11 censused dm3 routes, always present
          "records": {
            "fastest_time":      <record|null>,   # fastest FINISH (any path), s, lower=better
            "first_completion":  <record|null>,   # first on-route completion (set once)
            "peak_speed":        <record|null>,   # highest on-route peak, qu/s, higher=better
            "edge_speed":        <record|null>,   # highest launch-edge crossing, qu/s, higher=better
            "active_mean_speed": <record|null>    # highest whole-run active-mean speed, qu/s — the Speedometer primary
          },
          "aggregates": {
            "attempts":      <int>,        # scored attempts across all runs
            "finishes":      <int>,        # attempts that reached the goal (any path)
            "median_time_s": <float|null>, # median finish time across finishes
            "human_time_s":  <float>       # census duration_s (the bar)
          }
        }
      }
    }
  },
  "provenance": { runs_scanned, runs_scored, skipped{reason: count},
                  archive_verified, runs_dir, census }
}

A <record> is:
  { "value": <float>, "units": "s"|"qu/s", "run_id": "<runid>",
    "demo_url": "/demos/files/non-games/lab/Komodobots/<map>/<route>__<runid>.mvd",
    "demo_archived": true|false|null,   # null = archive listing unavailable
    "event_t_s": <float|null>,          # DEMO-relative seconds of the event
    "set_at": "YYYY-MM-DD",             # derived from the run id (deterministic)
    "human_ref": { "value": <float>, "source": "<census field>",
                   "demo_url": ".../Komodobots/human/dm3_<route>.qwd" } }

`event_t_s` alignment: trace rows carry the SERVER clock; the demo-relative
time is `t - server_start_time_s`, where server_start_time_s is the ServerTime
of the demo's kind-0 event in events.txt (the same alignment the QWD diagnosis
established; see scripts/compare_qwd_sng_hybrid_probe.load_run_timing). When
events.txt has no kind-0 ServerTime, event_t_s is null (honest absence), never
a guessed offset.

Finish vs completion (lab/SPEC.md glossary):
  finish     = the attempt reached the route's goal by ANY path
               (classification REACHED_RL). Feeds The Race + fastest_time.
  completion = a finish that did the trick: route progress >= 80% (the
               verify_route PASS route criterion) AND, when the route has a
               censused hard gap, a qualifying crossing of its launch edge
               (route_metrics.edge_crossing). Route progress alone cannot
               distinguish the two -- ANY arrival is within 150 qu of the
               human path's end, so route% saturates near 100 -- the leap is
               what makes it "the human way". Feeds Jump Count via
               first_completion.

Per-run scoring is cached as `records-scoring.json` (schema
`komodobots.run-scoring.v1`) inside each run dir, keyed by SCORING_REV +
route, so rebuilds are cheap; delete the caches (or bump SCORING_REV) to force
a full rescore. The scorer composes the SAME primitives verify_route.py uses
(load_route / segment_attempts / classify / route_progress and the
route_metrics library) -- no second metric definition is introduced.

Eligible runs: run.env has MAP=dm3 and MOVEPROBE_REPLAY_FILE naming a censused
route (dm3_<route>.cmds), and trace.csv exists (built by run_dm3.py's
build_trace step). Everything else is counted in provenance.skipped.

Verdicts: the eye-test store `verdicts.json` (schema `komodobots.verdicts.v1`:
route -> {verdict: pass|close|fail, note, run_id, date}) lives BESIDE
records.json on the SSD. It is human-entered (the bridge write path lands in
LD-F5 #106); --publish seeds it from lab/server/verdicts.seed.json only when
it does not exist remotely, and never overwrites it.

Usage:
  python lab/server/records_build.py --rebuild [--runs-dir DIR] [--out FILE]
         [--archive-list FILE | --archive-ssh HOST] [--publish [HOST]]
  python lab/server/records_build.py --append <run_id> [--publish]

  --rebuild            scan every run dir and regenerate records.json
  --append RUN_ID      force-rescore one run, then rebuild (run_dm3.py hook)
  --runs-dir DIR       run artifacts root (default <repo>/artifacts/lab-runs)
  --out FILE           output path (default <runs-dir>/../records/records.json)
  --archive-list FILE  file of archived demo paths (one per line) to verify
                       demo_url against (deterministic; used by tests/evidence)
  --archive-ssh HOST   list the SSD archive live over ssh instead
  --publish [HOST]     atomically publish records.json (and seed verdicts.json
                       if absent) to HOST:/mnt/usb-ssd/.../Komodobots/records/
                       (default host: servexeri)

Exit codes: 0 ok; 2 usage; 3 publish failed (build output is still written).
The run_dm3.py hook treats any non-zero exit as a loud warning, never a lab-run
failure (issue #93: publish failure must not fail the lab run).
"""

from __future__ import annotations

import logging
import json
import math
import re
import statistics
import subprocess
import sys
from pathlib import Path


LOGGER = logging.getLogger(__name__)
REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import verify_route as vr                      # noqa: E402
from route_metrics import (                    # noqa: E402
    legit_segment, edge_crossing, active_mean_speed,
)

SCHEMA = "komodobots.records.v1"
SCORING_SCHEMA = "komodobots.run-scoring.v1"
SCORING_REV = 1          # bump to invalidate every records-scoring.json cache
SCORING_CACHE = "records-scoring.json"

MAPS = ("dm3", "dm2", "frobodm2", "trick")     # the dashboard map set (#90/#91)
ARCHIVE_ROOT = "/mnt/usb-ssd/non-games/lab/Komodobots"
DEMO_URL_PREFIX = "/demos/files/non-games/lab/Komodobots"
DEFAULT_PUBLISH_HOST = "servexeri"
VERDICTS_SEED = Path(__file__).resolve().parent / "verdicts.seed.json"

RECORD_KINDS = ("fastest_time", "first_completion", "peak_speed", "edge_speed", "active_mean_speed")
ON_ROUTE_XTRACK = 150.0       # same corridor route_progress credits progress in
COMPLETION_ROUTE_PCT = 80.0   # verify_route PASS route criterion = "on-route"

RUN_ID_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})T\d{6}Z$")
REPLAY_ROUTE_RE = re.compile(r"dm3_([a-z0-9_]+)\.cmds$")
ARCHIVE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


# ---------------------------------------------------------------- run scanning

def read_run_env(run_dir: Path) -> dict:
    env = {}
    path = run_dir / "run.env"
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def route_for_run(env: dict, census: dict) -> tuple[str | None, str | None]:
    """(route_name, skip_reason). A run is eligible when it is a dm3 run whose
    uploaded replay names a censused route -- the replay file IS the declared
    route of the attempt (run_dm3.py always passes one)."""
    if env.get("MAP") != "dm3":
        return None, "not_dm3"
    m = REPLAY_ROUTE_RE.search(env.get("MOVEPROBE_REPLAY_FILE", ""))
    if not m:
        return None, "no_route_replay"
    route = m.group(1)
    if route != vr.DEFAULT_ROUTE and route not in census:
        return None, "unknown_route"
    return route, None


def server_start_time_s(run_dir: Path) -> float | None:
    """ServerTime of the demo's kind-0 event: the server clock at demo start.
    Same alignment source as compare_qwd_sng_hybrid_probe.load_run_timing."""
    path = run_dir / "events.txt"
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("kind") != 0:
                continue
            data = event.get("data") or {}
            server = data.get("Data") or {}
            try:
                return float(server["ServerTime"])
            except (KeyError, TypeError, ValueError):
                return None
    return None


def load_trace_rows(run_dir: Path, route: dict) -> list[dict]:
    """verify_route.load_trace, parameterized by run dir (same row contract)."""
    import csv
    path = run_dir / "trace.csv"
    gx, gy, gz = route["goal"]
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            row = {
                "t": float(r["t"]), "x": float(r["x"]), "y": float(r["y"]),
                "z": float(r["z"]), "vh": float(r["vh"]),
                "onground": int(r["onground"]), "over_void": int(r["over_void"]),
            }
            if route["native_dist"]:
                row["dist_goal"] = float(r["dist_to_rl"])
            else:
                row["dist_goal"] = math.sqrt(
                    (row["x"] - gx) ** 2 + (row["y"] - gy) ** 2 + (row["z"] - gz) ** 2)
            rows.append(row)
    return rows


# ---------------------------------------------------------------- run scoring

def score_attempt(seg: list[dict], route: dict, H, cum, hmean) -> dict:
    """Score one legit attempt segment with verify_route's own primitives."""
    cls, closest, _, _ = vr.classify(seg, route["geom"])

    # arrival: first row within REACH_RL (3D) of the goal
    arrive_i = None
    for i, r in enumerate(seg):
        if r["dist_goal"] < vr.REACH_RL:
            arrive_i = i
            break
    finish_time_s = finish_t = None
    if cls == "REACHED_RL" and arrive_i is not None:
        finish_t = seg[arrive_i]["t"]
        finish_time_s = round(finish_t - seg[0]["t"], 3)

    # route% + on-route peak in one pass (route_progress semantics: only rows
    # within ON_ROUTE_XTRACK of the human path and not over the void count)
    upto = seg if arrive_i is None else seg[: arrive_i + 1]
    best_arc = 0.0
    peak = None
    for r in upto:
        if r["over_void"]:
            continue
        arc, d = vr.nearest_arc(H, cum, r["x"], r["y"])
        if d > ON_ROUTE_XTRACK:
            continue
        if arc > best_arc:
            best_arc = arc
        if peak is None or r["vh"] > peak["speed"]:
            peak = {"speed": round(r["vh"], 1), "t": r["t"]}
    route_pct = round(100.0 * best_arc / cum[-1], 1) if cum[-1] else 0.0

    ms = active_mean_speed(seg, threshold=1.0, reach=vr.REACH_RL)
    speed_pct = round(100.0 * ms / hmean, 1) if hmean else 0.0
    ams = round(ms, 1) if ms else None

    edge = None
    crossing = edge_crossing(seg, route["gap"], route["tele_entrances"])
    if crossing is not None:
        edge = {"speed": round(crossing[0], 1), "t": crossing[1]}

    # completion = finish + on-route + (the leap, when the route has one).
    # See the module docstring: route% saturates on any arrival, so the
    # hard-gap launch-edge crossing is the discriminating "did the trick" bit.
    completion = (cls == "REACHED_RL"
                  and route_pct >= COMPLETION_ROUTE_PCT
                  and (route["gap"] is None or edge is not None))
    return {
        "classification": cls,
        "route_pct": route_pct,
        "speed_pct": speed_pct,
        "active_mean_speed": ams,
        "finish": cls == "REACHED_RL",
        "completion": completion,
        "finish_time_s": finish_time_s,
        "finish_t": finish_t,
        "peak": peak,
        "edge": edge,
    }


def score_run(run_dir: Path, route_name: str) -> dict:
    route = vr.load_route(route_name)
    H, cum, hmean = vr.load_human(route)
    rows = load_trace_rows(run_dir, route)
    segs = vr.segment_attempts(rows, route)
    attempts = []
    for s, e in segs:
        seg = legit_segment(rows[s:e], route["tele_entrances"])
        if len(seg) < 3:
            continue
        attempts.append(score_attempt(seg, route, H, cum, hmean))
    return {
        "schema": SCORING_SCHEMA,
        "scoring_rev": SCORING_REV,
        "run_id": run_dir.name,
        "map": "dm3",
        "route": route_name,
        "server_start_time_s": server_start_time_s(run_dir),
        "attempts": attempts,
    }


def scored_run(run_dir: Path, route_name: str, force: bool = False) -> dict:
    """Per-run scoring with the records-scoring.json cache."""
    cache = run_dir / SCORING_CACHE
    if not force and cache.is_file():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if (data.get("schema") == SCORING_SCHEMA
                    and data.get("scoring_rev") == SCORING_REV
                    and data.get("route") == route_name):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    data = score_run(run_dir, route_name)
    try:
        cache.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:                       # cache is an optimization only
        print(f"WARNING: could not cache scoring for {run_dir.name}: {exc}",
              file=sys.stderr)
    return data


# ------------------------------------------------------------ records assembly

def set_at_date(run_id: str) -> str | None:
    m = RUN_ID_RE.match(run_id)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def demo_event_t(scoring: dict, t: float | None) -> float | None:
    """Server-clock t -> demo-relative seconds (see module docstring)."""
    start = scoring.get("server_start_time_s")
    if t is None or start is None:
        return None
    return round(t - start, 3)


def make_record(value, units, scoring, t, human_ref, archived):
    run_id = scoring["run_id"]
    demo_stem = demo_archive_stem(scoring)
    return {
        "value": value,
        "units": units,
        "run_id": run_id,
        "demo_url": f"{DEMO_URL_PREFIX}/{scoring['map']}/{demo_stem}.mvd",
        "demo_archived": archived(scoring["map"], demo_stem),
        "event_t_s": demo_event_t(scoring, t),
        "set_at": set_at_date(run_id),
        "human_ref": human_ref,
    }


def demo_archive_stem(scoring: dict) -> str:
    """Filename stem used for released bot demos on the SSD."""
    run_id = scoring["run_id"]
    route = scoring.get("route")
    if route and ARCHIVE_NAME_RE.fullmatch(route):
        return f"{route}__{run_id}"
    return run_id


def census_human_refs(census: dict, route: str) -> dict:
    """Human anchors per record kind: census value + provenance + the human
    reference demo (archived under <archive>/human/, browsable like lab demos)."""
    ent = census.get(route, {})
    hard = [g for g in ent.get("gaps", ()) if g.get("hard")]
    demo_url = f"{DEMO_URL_PREFIX}/human/dm3_{route}.qwd"
    refs = {
        "fastest_time": {"value": ent.get("duration_s"),
                         "source": "census duration_s", "demo_url": demo_url},
        "first_completion": {"value": ent.get("duration_s"),
                             "source": "census duration_s", "demo_url": demo_url},
        "peak_speed": {"value": ent.get("peak_speed"),
                       "source": "census peak_speed", "demo_url": demo_url},
        "edge_speed": None,
        "active_mean_speed": {"value": ent.get("active_mean_speed"),
                              "source": "census active_mean_speed", "demo_url": demo_url},
    }
    if hard:
        refs["edge_speed"] = {"value": hard[-1].get("human_speed_at_edge"),
                              "source": "census final hard gap human_speed_at_edge",
                              "demo_url": demo_url}
    return refs


def build_route_entry(route: str, scorings: list[dict], census: dict,
                      archived) -> dict:
    refs = census_human_refs(census, route)
    records = {k: None for k in RECORD_KINDS}
    finish_times = []
    attempts = finishes = 0
    first_completion = None       # (run_id, attempt_idx) ordering = history

    for scoring in sorted(scorings, key=lambda s: s["run_id"]):
        for idx, a in enumerate(scoring["attempts"]):
            attempts += 1
            if a["finish"]:
                finishes += 1
                if a["finish_time_s"] is not None:
                    finish_times.append(a["finish_time_s"])
                    cur = records["fastest_time"]
                    if cur is None or a["finish_time_s"] < cur["value"]:
                        records["fastest_time"] = make_record(
                            a["finish_time_s"], "s", scoring, a["finish_t"],
                            refs["fastest_time"], archived)
            if a["completion"] and first_completion is None:
                first_completion = make_record(
                    a["finish_time_s"], "s", scoring, a["finish_t"],
                    refs["first_completion"], archived)
            if a["peak"] is not None:
                cur = records["peak_speed"]
                if cur is None or a["peak"]["speed"] > cur["value"]:
                    records["peak_speed"] = make_record(
                        a["peak"]["speed"], "qu/s", scoring, a["peak"]["t"],
                        refs["peak_speed"], archived)
            if a["edge"] is not None:
                cur = records["edge_speed"]
                if cur is None or a["edge"]["speed"] > cur["value"]:
                    records["edge_speed"] = make_record(
                        a["edge"]["speed"], "qu/s", scoring, a["edge"]["t"],
                        refs["edge_speed"], archived)
            # active_mean_speed: highest whole-run active-mean speed (qu/s).
            # Stored per-attempt as speed_pct * hmean / 100 is already in the
            # scoring dict as speed_pct; we re-derive the raw qu/s value here.
            # score_attempt stores "speed_pct" which is ms/hmean*100, but does
            # NOT store the raw ms value; we recompute from score_attempt output.
            # We store active_mean_speed directly in the scoring dict so we can
            # pick it up here without re-running route_metrics.
            ams = a.get("active_mean_speed")
            if ams is not None and ams > 0:
                cur = records["active_mean_speed"]
                if cur is None or ams > cur["value"]:
                    records["active_mean_speed"] = make_record(
                        round(ams, 1), "qu/s", scoring, a.get("finish_t"),
                        refs["active_mean_speed"], archived)
    records["first_completion"] = first_completion

    return {
        "records": records,
        "aggregates": {
            "attempts": attempts,
            "finishes": finishes,
            "median_time_s": (round(statistics.median(finish_times), 3)
                              if finish_times else None),
            "human_time_s": census.get(route, {}).get("duration_s"),
        },
    }


def load_census() -> dict:
    path = vr._resolve(REPO / "artifacts" / "trick-census" / "census.json",
                       vr.NAV_EVID / "trick-census" / "census.json")
    return json.loads(path.read_text(encoding="utf-8"))


def build(runs_dir: Path, archive_paths: set[str] | None,
          force_run_id: str | None = None) -> dict:
    census = load_census()

    if archive_paths is None:
        def archived(map_name, demo_stem):
            return None
    else:
        def archived(map_name, demo_stem):
            return f"{map_name}/{demo_stem}.mvd" in archive_paths

    by_route: dict[str, list[dict]] = {r: [] for r in census}
    skipped: dict[str, int] = {}
    scanned = scored = 0
    run_dirs = sorted(d for d in runs_dir.iterdir() if d.is_dir()) \
        if runs_dir.is_dir() else []
    for run_dir in run_dirs:
        scanned += 1
        env = read_run_env(run_dir)
        if not env:
            skipped["no_run_env"] = skipped.get("no_run_env", 0) + 1
            continue
        route, reason = route_for_run(env, census)
        if route is None:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        if not (run_dir / "trace.csv").is_file():
            skipped["no_trace"] = skipped.get("no_trace", 0) + 1
            continue
        force = force_run_id is not None and run_dir.name == force_run_id
        by_route.setdefault(route, []).append(scored_run(run_dir, route, force))
        scored += 1

    maps = {}
    for map_name in MAPS:
        routes = {}
        if map_name == "dm3":
            for route in sorted(census):
                routes[route] = build_route_entry(
                    route, by_route.get(route, []), census, archived)
        maps[map_name] = {"routes": routes}

    return {
        "schema": SCHEMA,
        "maps": maps,
        "provenance": {
            "runs_scanned": scanned,
            "runs_scored": scored,
            "skipped": dict(sorted(skipped.items())),
            "archive_verified": archive_paths is not None,
            "runs_dir": str(runs_dir),
            "census": "artifacts/trick-census/census.json "
                      "(committed fallback: experiments/nav_doctrine/evidence)",
        },
    }


# ------------------------------------------------------------ archive listing

def archive_paths_from_file(path: Path) -> set[str]:
    """Normalize an archive listing to '<map>/<file>.mvd' relative paths."""
    out = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip().replace("\\", "/")
        if not line or not line.endswith(".mvd"):
            continue
        parts = line.split("/")
        if len(parts) >= 2:
            out.add(f"{parts[-2]}/{parts[-1]}")
    return out


def archive_paths_over_ssh(host: str) -> set[str] | None:
    proc = subprocess.run(
        ["ssh", host, f"find {ARCHIVE_ROOT} -name '*.mvd' -type f 2>/dev/null"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"WARNING: archive listing over ssh failed (rc={proc.returncode}): "
              f"{proc.stderr.strip()} -- demo_archived will be null",
              file=sys.stderr)
        return None
    out = set()
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.endswith(".mvd"):
            parts = line.split("/")
            if len(parts) >= 2:
                out.add(f"{parts[-2]}/{parts[-1]}")
    return out


# ----------------------------------------------------------------- publishing

def publish(out_path: Path, host: str) -> bool:
    """Atomic replace on the SSD records dir; seeds verdicts.json only when it
    does not exist remotely. Returns False on any failure (caller warns)."""
    remote_dir = f"{ARCHIVE_ROOT}/records"
    steps = [
        ["ssh", host, f"mkdir -p {remote_dir}"],
        ["scp", str(out_path), f"{host}:{remote_dir}/.records.json.tmp"],
        ["ssh", host, f"mv -f {remote_dir}/.records.json.tmp {remote_dir}/records.json"],
    ]
    for cmd in steps:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"WARNING: publish step failed (rc={proc.returncode}): "
                  f"{' '.join(cmd)}\n{proc.stderr.strip()}", file=sys.stderr)
            return False
    # seed verdicts.json IF absent (never overwrite the human's verdicts)
    if VERDICTS_SEED.is_file():
        check = subprocess.run(
            ["ssh", host, f"test -e {remote_dir}/verdicts.json && echo exists"],
            capture_output=True, text=True)
        if "exists" not in check.stdout:
            for cmd in (
                ["scp", str(VERDICTS_SEED), f"{host}:{remote_dir}/.verdicts.json.tmp"],
                ["ssh", host, f"mv -f {remote_dir}/.verdicts.json.tmp {remote_dir}/verdicts.json"],
            ):
                proc = subprocess.run(cmd, capture_output=True, text=True)
                if proc.returncode != 0:
                    print(f"WARNING: verdicts seed failed (rc={proc.returncode}): "
                          f"{' '.join(cmd)}\n{proc.stderr.strip()}", file=sys.stderr)
                    return False
            print(f"seeded {remote_dir}/verdicts.json")
    return True


# ----------------------------------------------------------------------- main

def summarize(data: dict) -> str:
    lines = ["route                | attempts finishes | fastest_time first_completion peak_speed edge_speed active_mean_speed"]
    for route, ent in data["maps"]["dm3"]["routes"].items():
        agg = ent["aggregates"]
        cells = []
        for kind in RECORD_KINDS:
            rec = ent["records"][kind]
            cells.append("-" if rec is None else f"{rec['value']}{rec['units'][0]}")
        lines.append(f"{route:20s} | {agg['attempts']:8d} {agg['finishes']:8d} | "
                     + " ".join(f"{c:>12s}" for c in cells))
    p = data["provenance"]
    lines.append(f"runs: scanned={p['runs_scanned']} scored={p['runs_scored']} "
                 f"skipped={p['skipped']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    rebuild = append_id = None
    runs_dir = REPO / "artifacts" / "lab-runs"
    out_path = None
    archive_list = archive_ssh = None
    do_publish = False
    publish_host = DEFAULT_PUBLISH_HOST

    def value_after(idx):
        if idx + 1 >= len(args):
            raise SystemExit(f"{args[idx]} needs a value (see --help)")
        return args[idx + 1]

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--rebuild":
            rebuild = True
        elif a == "--append":
            append_id = value_after(i); i += 1
        elif a == "--runs-dir":
            runs_dir = Path(value_after(i)); i += 1
        elif a == "--out":
            out_path = Path(value_after(i)); i += 1
        elif a == "--archive-list":
            archive_list = Path(value_after(i)); i += 1
        elif a == "--archive-ssh":
            archive_ssh = value_after(i); i += 1
        elif a == "--publish":
            do_publish = True
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                publish_host = args[i + 1]; i += 1
        else:
            print(__doc__)
            return 2
        i += 1
    if not rebuild and append_id is None:
        print(__doc__)
        return 2

    archive_paths = None
    if archive_list is not None:
        archive_paths = archive_paths_from_file(archive_list)
    elif archive_ssh is not None:
        archive_paths = archive_paths_over_ssh(archive_ssh)

    data = build(runs_dir, archive_paths, force_run_id=append_id)

    if out_path is None:
        out_path = runs_dir.parent / "records" / "records.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n",
                        encoding="utf-8")
    print(summarize(data))
    print(f"\nwrote {out_path}")

    if do_publish and not publish(out_path, publish_host):
        return 3
    if do_publish:
        print(f"published -> {publish_host}:{ARCHIVE_ROOT}/records/records.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
