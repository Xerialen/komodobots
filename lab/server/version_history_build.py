#!/usr/bin/env python3
"""Build the version-history feed for the central dashboard.

Emits ``komodobots.kb2_versions.v1`` (kb2-versions.json): every merged PR to
main in the bot-development repo, with an owner-language (jargon-free) name +
summary from the curated layer (kb2_version_summaries.json), joined against
the lab feed (komodobots.kb2_matches.v1) for measured impact:

  bench.games / bench.margin_mean / wins / losses
      — counted-ledger aggregates for the candidate_version stamps this
        merge governs (prefix match against the feed's ``configs`` and
        ``ledger.bench`` blocks)
  test_matches
      — scratch (non-ledger) matches seen in the lab feed for those stamps

Runs where ``gh`` is available (pinnacle), fetching the matches feed from the
hub; publish the output to servexeri /demos/records/ (same dir the feed
lives in). Stdlib only; pure joins are unit-tested by
tests/test_version_history_build.py.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LOGGER = logging.getLogger(__name__)

SCHEMA = "komodobots.kb2_versions.v1"
DEFAULT_REPO = "Xerialen/komodobots2"
DEFAULT_SUMMARIES = Path(__file__).with_name("kb2_version_summaries.json")


def fetch_merged_prs(repo: str) -> list[dict]:
    out = subprocess.run(
        ["gh", "pr", "list", "--repo", repo, "--state", "merged",
         "--base", "main", "--json", "number,title,mergedAt", "--limit", "200"],
        capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def load_feed(src: str) -> dict:
    if src.startswith("http://") or src.startswith("https://"):
        with urllib.request.urlopen(src, timeout=15) as resp:
            return json.load(resp)
    return json.loads(Path(src).read_text(encoding="utf-8"))


def stamp_matches(stamp_prefixes: list[str], key: str) -> bool:
    return any(key.startswith(p) or p in key for p in stamp_prefixes)


def join_impact(stamps: list[str], feed: dict) -> tuple[dict | None, int]:
    """(bench aggregate over the ledger, scratch/test match count)."""
    if not stamps:
        return None, 0
    games = wins = losses = 0
    margin_total = 0.0
    for key, agg in (feed.get("ledger", {}).get("bench") or {}).items():
        if not stamp_matches(stamps, key):
            continue
        n = agg.get("games_scored", 0)
        games += n
        wins += agg.get("candidate_wins", 0)
        losses += agg.get("control_wins", 0)
        if agg.get("frag_margin_mean") is not None:
            margin_total += agg["frag_margin_mean"] * n
    bench = None
    if games > 0:
        bench = {
            "games": games,
            "margin_mean": round(margin_total / games, 2),
            "wins": wins,
            "losses": losses,
        }
    test_matches = sum(
        1 for m in feed.get("matches", [])
        if not m.get("in_ledger")
        and m.get("candidate", {}).get("version")
        and stamp_matches(stamps, m["candidate"]["version"]))
    return bench, test_matches


def build(prs: list[dict], summaries: dict, feed: dict, repo: str) -> dict:
    versions = []
    for pr in prs:
        cur = summaries.get(str(pr["number"]), {})
        stamps = cur.get("stamps", [])
        bench, test_matches = join_impact(stamps, feed)
        versions.append({
            "merged_at": pr.get("mergedAt"),
            "pr": pr.get("number"),
            "title": pr.get("title", ""),
            "name": cur.get("name", pr.get("title", "")),
            "summary": cur.get("summary", pr.get("title", "")),
            "stamps": stamps,
            "bench": bench,
            "test_matches": test_matches,
        })
    versions.sort(key=lambda v: v["merged_at"] or "", reverse=True)
    return {
        "schema": SCHEMA,
        "generated_utc": datetime.now(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": repo,
        "versions": versions,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--summaries", type=Path, default=DEFAULT_SUMMARIES)
    ap.add_argument("--feed",
                    default="http://192.168.86.33:8095/demos/records/kb2-matches.json",
                    help="kb2-matches feed (URL or file)")
    ap.add_argument("--out", required=True, type=Path)
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    summaries = json.loads(args.summaries.read_text(encoding="utf-8"))
    prs = fetch_merged_prs(args.repo)
    feed = load_feed(args.feed)
    doc = build(prs, summaries, feed, args.repo)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    n_cur = sum(1 for v in doc["versions"] if str(v["pr"]) in summaries)
    print(f"wrote {args.out}: {len(doc['versions'])} merge(s), "
          f"{n_cur} with curated summaries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
