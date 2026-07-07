#!/usr/bin/env python3
"""Build the komodobots2 match-history feed for the Bot Lab dashboard.

Reads the komodobots2 lab data mirror (synced from lanister by
komodobots2-dashboard/sync_from_lanister.sh, normally at
/mnt/usb-ssd/komodobots2-lab/data on servexeri) and emits ONE JSON document,
schema ``komodobots.kb2_matches.v1``, that the dashboard's List View /
Match View / Demo List consume:

- ``matches[]``   — every synced run, newest first: map, game duration
                    (ktxstats), per-team frags, frag margin (candidate −
                    control), winner, the exact cvars the run was started
                    with (run-meta ``extra_cfg_sets``), derived feature tags
                    (hm / fov / routepolicy / dials / harvest / ...), ledger
                    membership, demo URL when the .mvd is published.
- ``jumps[]``     — every successful gapjump (``[gapjump] ... result=LAND``
                    in server.log) with match-relative seconds and a
                    /demo-player/ deep link (event − 5 s pre-roll).
- per-match ``jumps{}`` — attempt accounting per lane: ``attempts`` =
                    launched trials (LAND + FAIL_GAP + FAIL_TIMEOUT),
                    ``lands``, ``declines`` (APP_ABORT/APP_DECLINE/APP_YIELD
                    approach outcomes that never launched), and a per-lane
                    ``lanes{}`` breakdown — so jump success rate is trackable
                    over time (owner requirement 2026-07-07).
- ``jump_lanes{}``— feed-level per-lane aggregate across all included
                    matches: attempts / lands / declines / land_rate.
- ``features{}`` / ``configs{}`` — aggregate frag-margin per derived feature
                    tag and per candidate version stamp, each with a
                    ``best`` run; ``record_holder`` points at the best of
                    each (min games threshold).
- ``ledger``      — passthrough of the counted bench aggregates
                    (records/bench.json, schema komodobots2.bench.v1).

Inputs per run dir (<data>/lab-runs/<run_id>/):
  run-meta.json  komodobots2.run_meta.v1 (required — dirs without it are
                 in-progress and skipped)
  ktxstats.json  KTX end-of-match stats (optional — incomplete runs keep
                 nulls for duration/frags)
  server.log     mvdsv console log (optional — source of gapjump events)
  demo.mvd       optional (synced later); published as a hardlink
                 <publish-dir>/<run_id>.mvd so /demos/files/... serves it.

Deployment: runs on servexeri as step 4 of sync_from_lanister.sh (every
sync pass — 10-min timer plus the bench_poller completion kick), writing to
/mnt/usb-ssd/non-games/lab/Komodobots/records/ which the local-hub serves
as /demos/records/kb2-matches.json.

Stdlib only. Pure helpers are unit-tested by tests/test_kb2_matches_build.py.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

LOGGER = logging.getLogger(__name__)

SCHEMA = "komodobots.kb2_matches.v2"

# Derived feature tags: (tag, predicate over (cvars, candidate_version)).
# Order = display order. Documented in the module docstring; extend here and
# in tests/test_kb2_matches_build.py in the same PR.
def _cvar_truthy(cvars: dict, key: str) -> bool:
    v = str(cvars.get(key, "")).strip()
    return v not in ("", "0")


FEATURE_RULES: list[tuple[str, object]] = [
    ("hm", lambda cv, stamp: _cvar_truthy(cv, "k_hm")),
    ("fov", lambda cv, stamp: _cvar_truthy(cv, "k_hm_fov")),
    ("routepolicy", lambda cv, stamp: _cvar_truthy(cv, "k_kbot_routepolicy")),
    ("dials", lambda cv, stamp: "dials" in stamp.lower()
        or any(k.startswith("k_kbot_dial") for k in cv)),
    ("harvest", lambda cv, stamp: "harvest" in stamp.lower()
        or any("harvest" in k for k in cv)),
    ("weakstack", lambda cv, stamp: _cvar_truthy(cv, "k_kbot_weak_stack")),
    ("sng", lambda cv, stamp: "sng" in stamp.lower()),
    ("carve", lambda cv, stamp: _cvar_truthy(cv, "k_kbot_carve")
        or "carve" in stamp.lower()),
]

GAPJUMP_RE = re.compile(
    r"^\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] \[gapjump\] "
    r"lane=(?P<lane>\S+)"
    r"(?: slot=(?P<slot>\d+))?(?: name=(?P<name>\S+))?"
    r" trial=\d+ result=(?P<result>\S+)"
    r".*?hdist=(?P<hdist>-?\d+)"
    r" peak_speed=(?P<peak>-?\d+)"
    r" tair=(?P<tair>[\d.]+)"
)
MATCH_BEGUN_RE = re.compile(
    r"^\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] The match has begun!"
)
LOG_TS_FMT = "%Y-%m-%d %H:%M:%S"


def derive_features(cvars: dict, candidate_version: str) -> list[str]:
    stamp = candidate_version or ""
    tags = [tag for tag, pred in FEATURE_RULES if pred(cvars, stamp)]
    return tags or ["stock"]


# Gapjump outcome taxonomy (verified against bench server.log 2026-07-07):
#   LAND                       — launched and made the jump (success)
#   FAIL_GAP / FAIL_TIMEOUT    — launched but missed / timed out (failed attempt)
#   APP_ABORT_* / APP_DECLINE_* / APP_YIELD_*
#                              — approach evaluated but never launched (decline)
#   APP_ENGAGE / APP_LAUNCH    — phase-progress breadcrumbs, not outcomes
# Attempts = launches = LAND + FAIL_*; declines are reported for context.
ATTEMPT_FAIL_RESULTS = ("FAIL_GAP", "FAIL_TIMEOUT")
DECLINE_PREFIXES = ("APP_ABORT", "APP_DECLINE", "APP_YIELD")
GAPJUMP_DECLINE_RE = re.compile(
    r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \[gapjump\] "
    r"lane=(?P<lane>\S+)(?: slot=\d+)?(?: name=\S+)?"
    r"(?: trial=\d+)? result=(?P<result>APP_\S+)"
)


def _new_lane_counts() -> dict:
    return {"attempts": 0, "lands": 0, "fails": 0, "declines": 0}


def parse_gapjump_events(log_text: str) -> tuple[list[dict], dict[str, dict]]:
    """(successful lands, per-lane attempt counts) from a bench server.log.

    Lands carry seconds since the (latest) match start; lines before the first
    "The match has begun!" are warmup and skipped — demo time starts at the
    match-begun instant for these lab MVDs. Attempt/decline counting applies
    the same warmup filter so rates describe the counted match only.
    """
    begun: datetime | None = None
    lands: list[dict] = []
    lanes: dict[str, dict] = {}
    for line in log_text.splitlines():
        m = MATCH_BEGUN_RE.match(line)
        if m:
            begun = datetime.strptime(m.group("ts"), LOG_TS_FMT)
            continue
        if begun is None:
            continue
        m = GAPJUMP_RE.match(line)
        if m:
            result = m.group("result")
            lane = lanes.setdefault(m.group("lane"), _new_lane_counts())
            if result == "LAND":
                lane["attempts"] += 1
                lane["lands"] += 1
                t = datetime.strptime(m.group("ts"), LOG_TS_FMT)
                lands.append({
                    "t_s": int((t - begun).total_seconds()),
                    "lane": m.group("lane"),
                    "name": m.group("name"),
                    "hdist": int(m.group("hdist")),
                    "peak_speed": int(m.group("peak")),
                    "tair": float(m.group("tair")),
                })
            elif result in ATTEMPT_FAIL_RESULTS:
                lane["attempts"] += 1
                lane["fails"] += 1
            continue
        m = GAPJUMP_DECLINE_RE.match(line)
        if m and m.group("result").startswith(DECLINE_PREFIXES):
            lanes.setdefault(m.group("lane"), _new_lane_counts())["declines"] += 1
    return lands, lanes


def team_frags_from_ktxstats(stats: dict) -> dict[str, int]:
    frags: dict[str, int] = {}
    for p in stats.get("players", []):
        team = p.get("team") or ""
        frags[team] = frags.get(team, 0) + int(p.get("stats", {}).get("frags", 0))
    return frags


def demo_player_url(demo_url: str, map_name: str, duration: int | None,
                    event_t_s: int) -> str:
    """Host-relative deep link into the hub demo player, 5 s pre-roll.

    The player ignores from<1, so very-early events clamp to 1.
    """
    from_s = max(1, event_t_s - 5)
    url = f"/demo-player/?demoUrl={quote(demo_url, safe='')}&map={map_name}"
    if duration:
        url += f"&duration={duration}"
    url += f"&from={from_s}"
    return url


def summarize_run(run_dir: Path, *, demo_url_base: str,
                  ledger_run_ids: frozenset) -> dict | None:
    """One matches[] row (+ its jump events stashed under "_jumps")."""
    meta_path = run_dir / "run-meta.json"
    if not meta_path.is_file():
        return None  # in-progress / not yet synced
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    stats = None
    stats_path = run_dir / "ktxstats.json"
    if stats_path.is_file():
        try:
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            stats = None

    cand = meta.get("teams", {}).get("candidate", {})
    ctrl = meta.get("teams", {}).get("control", {})
    cvars = meta.get("extra_cfg_sets", {}) or {}
    stamp = cand.get("controller_version") or ""

    duration = stats.get("duration") if stats else None
    team_frags = team_frags_from_ktxstats(stats) if stats else {}
    margin = None
    winner = None
    if team_frags and cand.get("name") in team_frags and ctrl.get("name") in team_frags:
        margin = team_frags[cand["name"]] - team_frags[ctrl["name"]]
        if margin > 0:
            winner = cand["name"]
        elif margin < 0:
            winner = ctrl["name"]
        else:
            winner = "draw"

    demo_url = None
    if (run_dir / "demo.mvd").is_file():
        demo_url = f"{demo_url_base}/{meta['run_id']}.mvd"

    players = []
    if stats:
        for p in stats.get("players", []):
            s = p.get("stats", {})
            d = p.get("dmg", {})
            w = p.get("weapons", {}) or {}
            items = p.get("items", {}) or {}
            speed = p.get("speed", {}) or {}
            ttd = d.get("taken-to-die")
            players.append({
                "name": p.get("name"),
                "team": p.get("team"),
                "frags": s.get("frags", 0),
                "deaths": s.get("deaths", 0),
                "dmg_given": d.get("given", 0),
                "dmg_taken": d.get("taken", 0),
                # owner requirement 2026-07-07: powerups, RL/LG pickups,
                # direct RL hits and taken-to-die must be trackable per match.
                "quad": (items.get("q") or {}).get("took", 0),
                "pent": (items.get("p") or {}).get("took", 0),
                "ring": (items.get("r") or {}).get("took", 0),
                "rl_pickups": ((w.get("rl") or {}).get("pickups") or {}).get("taken", 0),
                "lg_pickups": ((w.get("lg") or {}).get("pickups") or {}).get("taken", 0),
                "rl_direct_hits": ((w.get("rl") or {}).get("acc") or {}).get("hits", 0),
                "rl_attacks": ((w.get("rl") or {}).get("acc") or {}).get("attacks", 0),
                # KTX writes 99999 for "never died"; surface null instead.
                "taken_to_die": None if ttd in (None, 99999) else ttd,
                "avg_speed": speed.get("avg"),
                "max_speed": speed.get("max"),
            })

    jumps: list[dict] = []
    jump_lanes: dict[str, dict] = {}
    log_path = run_dir / "server.log"
    if log_path.is_file():
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
            jumps, jump_lanes = parse_gapjump_events(text)
        except OSError:
            jumps, jump_lanes = [], {}
    name_team = {p["name"]: p["team"] for p in players}
    map_name = meta.get("map") or (stats.get("map") if stats else "") or ""
    for j in jumps:
        j["run_id"] = meta["run_id"]
        j["map"] = map_name
        j["team"] = name_team.get(j["name"]) if j["name"] else None
        j["watch_url"] = (demo_player_url(demo_url, map_name, duration, j["t_s"])
                          if demo_url else None)

    return {
        "run_id": meta["run_id"],
        "started_utc": meta.get("started_utc"),
        "ended_utc": meta.get("ended_utc"),
        "ok": bool(meta.get("ok")),
        "error": meta.get("error"),
        "map": map_name,
        "port": meta.get("port"),
        "timelimit": meta.get("timelimit"),
        "duration_s": duration,
        "candidate": {"team": cand.get("name"), "brain": cand.get("brain"),
                      "version": stamp},
        "control": {"team": ctrl.get("name"), "brain": ctrl.get("brain"),
                    "version": ctrl.get("controller_version")},
        "team_frags": team_frags,
        "frag_margin": margin,
        "winner": winner,
        "cvars": cvars,
        "features": derive_features(cvars, stamp),
        "in_ledger": meta["run_id"] in ledger_run_ids,
        "demo": {"name": stats.get("demo") if stats else None, "url": demo_url},
        "players": players,
        "jumps": {
            "attempts": sum(l["attempts"] for l in jump_lanes.values()),
            "lands": len(jumps),
            "fails": sum(l["fails"] for l in jump_lanes.values()),
            "declines": sum(l["declines"] for l in jump_lanes.values()),
            "lanes": jump_lanes,
        },
        "_jumps": jumps,
    }


def aggregate(matches: list[dict], key_fn) -> dict[str, dict]:
    """Frag-margin aggregate per key (feature tag or version stamp)."""
    agg: dict[str, dict] = {}
    for m in matches:
        if m["frag_margin"] is None:
            continue
        for key in key_fn(m):
            a = agg.setdefault(key, {
                "matches": 0, "wins": 0, "losses": 0, "draws": 0,
                "margin_total": 0, "margin_mean": None, "best": None,
            })
            a["matches"] += 1
            a["margin_total"] += m["frag_margin"]
            cand_team = m["candidate"]["team"]
            if m["winner"] == cand_team:
                a["wins"] += 1
            elif m["winner"] == "draw":
                a["draws"] += 1
            else:
                a["losses"] += 1
            if a["best"] is None or m["frag_margin"] > a["best"]["frag_margin"]:
                a["best"] = {"run_id": m["run_id"],
                             "frag_margin": m["frag_margin"]}
    for a in agg.values():
        a["margin_mean"] = round(a["margin_total"] / a["matches"], 2)
    return agg


def aggregate_jump_lanes(matches: list[dict]) -> dict[str, dict]:
    """Per-lane jump totals across all included matches (newest-first input).

    land_rate = lands/attempts (attempts = actual launches). ``last_land_utc``
    is the started_utc of the newest match where the lane landed at least once,
    so the dashboard can show recency alongside the rate.
    """
    lanes: dict[str, dict] = {}
    for m in matches:
        for lane, counts in (m.get("jumps", {}).get("lanes") or {}).items():
            a = lanes.setdefault(lane, {
                "matches": 0, "attempts": 0, "lands": 0, "fails": 0,
                "declines": 0, "land_rate": None, "last_land_utc": None,
            })
            a["matches"] += 1
            for key in ("attempts", "lands", "fails", "declines"):
                a[key] += counts.get(key, 0)
            if counts.get("lands") and a["last_land_utc"] is None:
                a["last_land_utc"] = m.get("started_utc")
    for a in lanes.values():
        if a["attempts"]:
            a["land_rate"] = round(a["lands"] / a["attempts"], 4)
    return lanes


def record_holder(agg: dict[str, dict], *, min_matches: int = 3) -> dict | None:
    eligible = {k: v for k, v in agg.items() if v["matches"] >= min_matches}
    if not eligible:
        return None
    key = max(eligible, key=lambda k: eligible[k]["margin_mean"])
    return {"key": key, **eligible[key]}


def publish_demos(runs_dir: Path, publish_dir: Path) -> int:
    """Hardlink every synced demo.mvd to <publish_dir>/<run_id>.mvd.

    Hardlinks: same filesystem (both live on the usb-ssd), zero extra space,
    and the demo browser gets a clean per-run filename. Existing links are
    left alone. Returns the number of new links.
    """
    publish_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for run_dir in runs_dir.iterdir():
        src = run_dir / "demo.mvd"
        dst = publish_dir / f"{run_dir.name}.mvd"
        if src.is_file() and not dst.exists():
            os.link(src, dst)
            n += 1
    return n


def build(data_dir: Path, *, demo_url_base: str, max_runs: int = 500) -> dict:
    runs_dir = data_dir / "lab-runs"
    ledger = {}
    ledger_path = data_dir / "records" / "bench.json"
    if ledger_path.is_file():
        try:
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            ledger = {}
    ledger_run_ids = frozenset(
        g.get("run_id") for g in ledger.get("games", []) if g.get("run_id"))

    run_dirs = sorted((d for d in runs_dir.iterdir() if d.is_dir()),
                      key=lambda d: d.name, reverse=True)
    matches: list[dict] = []
    scanned = 0
    failed = 0
    for run_dir in run_dirs:
        scanned += 1
        if len(matches) >= max_runs:
            break
        # Per-run guard: one corrupt artifact (e.g. a run-meta.json truncated
        # by a dropped sftp transfer that still got stamped .synced) must cost
        # exactly one row, never the whole feed — the sync's "a feed failure
        # never fails the sync" intent depends on this (review P2 on PR #482).
        try:
            row = summarize_run(run_dir, demo_url_base=demo_url_base,
                                ledger_run_ids=ledger_run_ids)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            failed += 1
            LOGGER.warning("skipping run %s: %s: %s",
                           run_dir.name, type(exc).__name__, exc)
            continue
        if row is not None:
            matches.append(row)

    matches.sort(key=lambda m: m.get("started_utc") or "", reverse=True)
    jumps = [j for m in matches for j in m.pop("_jumps")]
    jumps.sort(key=lambda j: (j["run_id"], j["t_s"]), reverse=True)

    features = aggregate(matches, lambda m: m["features"])
    configs = aggregate(
        matches, lambda m: [m["candidate"]["version"]]
        if m["candidate"]["version"] else [])

    return {
        "schema": SCHEMA,
        "generated_utc": datetime.now(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {"data_dir": str(data_dir), "runs_scanned": scanned,
                   "runs_included": len(matches), "runs_failed": failed},
        "matches": matches,
        "jumps": jumps,
        "jump_lanes": aggregate_jump_lanes(matches),
        "features": features,
        "configs": configs,
        "record_holder": {
            "feature": record_holder(features),
            "config": record_holder(configs),
        },
        "ledger": {
            "bench": ledger.get("bench", {}),
            "valid_games": (ledger.get("provenance") or {}).get("valid_games"),
        },
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", required=True, type=Path,
                    help="komodobots2 lab data mirror (has lab-runs/, records/)")
    ap.add_argument("--out", required=True, type=Path,
                    help="output kb2-matches.json path")
    ap.add_argument("--publish-demos-dir", type=Path, default=None,
                    help="hardlink synced demo.mvd files here as <run_id>.mvd")
    ap.add_argument("--demo-url-base",
                    default="/demos/files/non-games/lab/Komodobots/kb2",
                    help="URL prefix the published demos are served under")
    ap.add_argument("--max-runs", type=int, default=500)
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.publish_demos_dir is not None:
        n = publish_demos(args.data_dir / "lab-runs", args.publish_demos_dir)
        print(f"published {n} new demo hardlink(s) -> {args.publish_demos_dir}")
    doc = build(args.data_dir, demo_url_base=args.demo_url_base,
                max_runs=args.max_runs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    tmp.replace(args.out)
    print(f"wrote {args.out}: {doc['source']['runs_included']} matches, "
          f"{len(doc['jumps'])} jumps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
