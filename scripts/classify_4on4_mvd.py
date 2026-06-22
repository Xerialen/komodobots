#!/usr/bin/env python3
"""classify_4on4_mvd.py — validate + classify the human 4on4 dm3 corpus from .mvd (#358).

Discriminator = qw-analyze's match read (the authoritative mvd_analyzer logic):
active players are spectator-filtered (the *spectator userinfo flag, a real team, and
non-zero frags), and teams are the valid team names. A 1v1 duel -> 2 players; a 4on4 ->
8 in 2 teams. This is robust to the tournament spectators that fooled the client-slot count.

It does NOT trust the filename: `[ztndm3]` contains the substring "dm3" but is a different
map, so TRAIN requires qw-analyze map == "The Abandoned Base".

Bot-lab exclusion: the active-player read separates 4on4 from duels/spectators but CANNOT
tell a human 4on4 from a bot 4on4 (both are 8 active players in 2 teams on dm3). KTX lab/bot
matches use the DEFAULT team names red/blue (docs/20_ML_DATA_ARCHITECTURE: `4on4_red_vs_blue`
/ `4on4_frog_vs_leap` = bot-generated lab output). So a dm3 4on4 whose two teams are exactly
{red, blue} is classified EXCLUDED (bot_lab_default_teams). A few genuine human pugs on
default teams are dropped with them — an accepted trade for corpus purity (BC must not learn
bot movement); the per-demo parse is recorded, so a player-nick re-parse can recover them if
ever needed.

Modes (share classify_row, so both yield identical labels):
  --demo-dir   <dir>           parse every .mvd with qw-analyze, then classify.
  --reclassify <manifest.json> re-apply the rule to an already-parsed manifest (no qw-analyze).
"""
import argparse, json, logging, os, subprocess, sys, time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed

DM3_TITLE = "The Abandoned Base"
LOGGER = logging.getLogger(__name__)


def classify_row(row, team_min):
    """Apply the TRAIN/EXCLUDED rule to an already-parsed row (map/active_players/teams).

    Deterministic and a pure function of the recorded parse fields, so it is identical
    whether called live in analyze_one() or re-applied to a recorded manifest (--reclassify)."""
    if not row.get("ok"):
        row["class"] = "EXCLUDED"
        return row
    n, nt = row["active_players"], len(row["teams"] or [])
    teamset = {(t or "").strip().lower() for t in (row["teams"] or [])}
    row["class"] = "EXCLUDED"
    if row["map"] != DM3_TITLE:
        row["reason"] = "not_dm3 (map=%r)" % row["map"]
    elif nt != 2:
        row["reason"] = "not 2 teams (%d): %s" % (nt, row["teams"])
    elif teamset == {"red", "blue"}:
        row["reason"] = ("bot_lab_default_teams (red/blue = KTX lab/bot default per docs/20; "
                         "a bot 4on4 is indistinguishable from human by the active-player read)")
    elif n < team_min:
        row["reason"] = "too few active players (%d < %d)" % (n, team_min)
    else:
        row["class"] = "TRAIN"
        row["reason"] = "4on4 dm3 (%d active players, 2 teams, real clans)" % n
    return row


def analyze_one(arg):
    path, qwa, team_min = arg
    row = {"path": path, "demo": os.path.basename(path), "map": None,
           "active_players": None, "teams": None, "class": "EXCLUDED",
           "reason": None, "ok": False}
    try:
        out = subprocess.run([qwa, "-format", "json", path],
                             capture_output=True, timeout=180)
        if out.returncode != 0 or not out.stdout:
            row["reason"] = "qwanalyze_failed rc=%d %s" % (
                out.returncode, out.stderr[:120].decode("utf-8", "replace"))
            return row
        r = json.loads(out.stdout)
        m = r.get("match") or {}
        players = m.get("players") or []
        teams = m.get("teams") or []
        row["map"] = m.get("map") or ""
        row["active_players"] = len(players)
        row["teams"] = [t.get("name") for t in teams]
        row["ok"] = True
    except subprocess.TimeoutExpired:
        row["reason"] = "qwanalyze_timeout"
        return row
    except Exception as e:  # noqa: BLE001
        row["reason"] = "error %s: %s" % (type(e).__name__, e)
        return row
    return classify_row(row, team_min)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-dir", help="dir of .mvd to parse with qw-analyze (e.g. 4on4-corpus/demos)")
    ap.add_argument("--reclassify", help="re-apply classify_row() to an existing manifest's recorded parse (no qw-analyze)")
    ap.add_argument("--name-contains", default="dm3", help="substring filter on filename (default dm3; map is re-checked by parse)")
    ap.add_argument("--limit", type=int, default=0, help="0=all; else only the first N (sampling)")
    ap.add_argument("--qwa", default=os.path.expanduser("~/qw-sim/bin/qw-analyze-v20"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--team-min", type=int, default=6, help="min active players for a 4on4 (default 6, allows churn)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not a.demo_dir and not a.reclassify:
        ap.error("one of --demo-dir (parse) or --reclassify (re-apply rule) is required")

    t0 = time.time()
    if a.reclassify:
        prev = json.load(open(a.reclassify))
        rows = [classify_row(r, a.team_min) for r in prev["demos"]]
        LOGGER.info("reclassify: re-applied classify_row to %d recorded demos (team_min=%d)", len(rows), a.team_min)
    else:
        sub = a.name_contains.lower()
        names = sorted(n for n in os.listdir(a.demo_dir)
                       if n.lower().endswith(".mvd") and sub in n.lower())
        if a.limit:
            names = names[:a.limit]
        paths = [os.path.join(a.demo_dir, n) for n in names]
        rows = []
        LOGGER.info("classify: %d .mvd with %d workers (qwa=%s) ...", len(paths), a.workers, a.qwa)
        with ProcessPoolExecutor(max_workers=a.workers) as ex:
            futs = [ex.submit(analyze_one, (p, a.qwa, a.team_min)) for p in paths]
            done = 0
            for f in as_completed(futs):
                rows.append(f.result())
                done += 1
                if done % 25 == 0 or done == len(paths):
                    LOGGER.info("  %d/%d", done, len(paths))

    rows.sort(key=lambda r: r["demo"])
    train = [r for r in rows if r["class"] == "TRAIN"]
    bot_excluded = sum(1 for r in rows if (r.get("reason") or "").startswith("bot_lab_default_teams"))
    ap_hist = Counter(r["active_players"] for r in rows if r["ok"])
    nt_hist = Counter(len(r["teams"] or []) for r in rows if r["ok"])
    map_hist = Counter(r["map"] for r in rows if r["ok"])
    out = {
        "schema": "komodobots.human_4on4_dm3_mvd_manifest.v2",
        "ticket": "#358 / F-DATA-1 (.mvd via qw-analyze active-player read + bot-lab default-team exclusion)",
        "team_min": a.team_min,
        "counts": {"scanned": len(rows), "train": len(train),
                   "excluded": len(rows) - len(train),
                   "bot_lab_default_teams_excluded": bot_excluded,
                   "parse_ok": sum(1 for r in rows if r["ok"]),
                   "active_player_hist": dict(sorted(ap_hist.items())),
                   "teams_count_hist": dict(sorted(nt_hist.items())),
                   "map_hist": dict(map_hist.most_common(8))},
        "demos": rows,
    }
    with open(a.out, "w") as fh:
        json.dump(out, fh, indent=1)
    c = out["counts"]
    LOGGER.info("\n=== DONE %s  (%.1fs) ===", a.out, time.time() - t0)
    LOGGER.info("scanned=%d TRAIN=%d EXCLUDED=%d (bot_lab_default_teams=%d) parse_ok=%d",
                c["scanned"], c["train"], c["excluded"], c["bot_lab_default_teams_excluded"], c["parse_ok"])
    LOGGER.info("active_player_hist: %s", json.dumps(c["active_player_hist"]))
    LOGGER.info("teams_count_hist: %s", json.dumps(c["teams_count_hist"]))
    LOGGER.info("map_hist: %s", json.dumps(c["map_hist"]))


if __name__ == "__main__":
    main()
