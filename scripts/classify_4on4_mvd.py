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
import argparse, hashlib, json, logging, os, re, subprocess, sys, time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed

DM3_TITLE = "The Abandoned Base"
LOGGER = logging.getLogger(__name__)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def sha256_size(path):
    """(sha256_hex, size_bytes) for a file, chunked (matches scripts/analyze_human_mvd.py)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest(), os.path.getsize(path)


def qwa_parser_id(qwa):
    """Identity of the qw-analyze binary that produced the parse fields (gate item 2: parser
    version). Hash the binary so the manifest records WHICH parser read map/teams/active_players.
    NB: this SELECTION parse is parser-version-robust (map/teams/active-player counts are stable
    across schema revisions); the per-tick MOVE extraction in the ETL separately REQUIRES the
    schema-33 binary (per-tick view-yaw/velocity), which is a different, load-bearing concern."""
    path = os.path.expanduser(qwa)
    try:
        sha, size = sha256_size(path)
    except OSError as e:  # noqa: BLE001
        return {"path": qwa, "sha256": None, "size_bytes": None,
                "error": "%s: %s" % (type(e).__name__, e)}
    return {"path": qwa, "sha256": sha, "size_bytes": size}


def parse_corpus_tsv(text):
    """Parse the servexeri 4on4-corpus manifest.tsv: `sha256<TAB>size<TAB>basename<TAB>source`.

    Returns {basename: (sha256, size_bytes)}. Malformed lines (wrong field count, bad sha,
    non-numeric size) are skipped so one garbled row can't poison the whole merge. This is the
    AUTHORITATIVE content lock for the corpus on servexeri:/mnt/usb-ssd/4on4-corpus/manifest.tsv."""
    out = {}
    for line in (text or "").splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 4:
            continue
        sha, size, name, _src = (p.strip() for p in parts)
        sha = sha.lower()
        if not _SHA256_RE.fullmatch(sha) or not size.isdigit() or not name:
            continue
        out[name] = (sha, int(size))
    return out


def merge_provenance(rows, prov):
    """Attach sha256/size_bytes to each row from a {basename: (sha256, size)} map (in place)."""
    for r in rows:
        if r.get("sha256"):
            continue
        hit = prov.get(r["demo"])
        if hit:
            r["sha256"], r["size_bytes"] = hit


def dedupe_train_by_sha(rows):
    """Canonicalize duplicate-content TRAIN rows. Identical bytes (same sha256) under different
    names — e.g. a demo and its content-hash-renamed twin — are a split-by-demo train/eval
    LEAKAGE risk and let stale parse metadata ride on one alias. Keep exactly ONE canonical
    TRAIN row per sha256 (the lexicographically-first `demo`, deterministic); demote the rest to
    EXCLUDED. Returns the number demoted. (EXCLUDED aliases are already out of the train set.)"""
    groups = {}
    for r in rows:
        if r["class"] == "TRAIN" and r.get("sha256"):
            groups.setdefault(r["sha256"], []).append(r)
    demoted = 0
    for _sha, rs in groups.items():
        if len(rs) < 2:
            continue
        rs.sort(key=lambda r: r["demo"])
        canonical = rs[0]["demo"]
        for r in rs[1:]:
            r["class"] = "EXCLUDED"
            r["reason"] = "duplicate_content_sha (== %s)" % canonical
            demoted += 1
    return demoted


def validate_provenance(rows):
    """Every TRAIN row must carry a content lock (64-hex sha256 + positive size_bytes).

    The corpus is the foundation for feature extraction; a TRAIN row without a pinned identity
    means a later run could silently trust a replaced/truncated file. Returns the offending demos."""
    bad = []
    for r in rows:
        if r["class"] != "TRAIN":
            continue
        sha, size = r.get("sha256"), r.get("size_bytes")
        if not (isinstance(sha, str) and _SHA256_RE.fullmatch(sha) and isinstance(size, int) and size > 0):
            bad.append(r["demo"])
    return bad


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
           "reason": None, "ok": False, "sha256": None, "size_bytes": None}
    # content lock from the bytes on disk (parse-independent; even an unparseable demo is pinned)
    try:
        row["sha256"], row["size_bytes"] = sha256_size(path)
    except OSError as e:  # noqa: BLE001
        row["reason"] = "hash_failed %s: %s" % (type(e).__name__, e)
        return row
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
    ap.add_argument("--manifest-tsv", action="append", default=[],
                    help="servexeri content-lock TSV (sha256<TAB>size<TAB>basename<TAB>source) to merge "
                         "sha256/size_bytes by basename; repeatable. Required for --reclassify of a v2 manifest.")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not a.demo_dir and not a.reclassify:
        ap.error("one of --demo-dir (parse) or --reclassify (re-apply rule) is required")

    prov = {}
    for tsv in a.manifest_tsv:
        prov.update(parse_corpus_tsv(open(tsv, encoding="utf-8", errors="replace").read()))
    if a.manifest_tsv:
        LOGGER.info("provenance: loaded %d content-lock entries from %d TSV(s)", len(prov), len(a.manifest_tsv))

    t0 = time.time()
    parser_meta = None
    if a.reclassify:
        prev = json.load(open(a.reclassify))
        # carry the parser identity forward (reclassify does NOT re-parse, so it must not claim a
        # parser it did not run; it inherits the one that produced the recorded parse fields).
        parser_meta = (prev.get("provenance") or {}).get("parser")
        rows = []
        for r in prev["demos"]:
            r.setdefault("sha256", None)
            r.setdefault("size_bytes", None)
            rows.append(classify_row(r, a.team_min))
        LOGGER.info("reclassify: re-applied classify_row to %d recorded demos (team_min=%d)", len(rows), a.team_min)
    else:
        parser_meta = qwa_parser_id(a.qwa)
        LOGGER.info("parser: qw-analyze %s sha=%s", parser_meta.get("path"),
                    (parser_meta.get("sha256") or "?")[:12])
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

    if prov:
        merge_provenance(rows, prov)
    rows.sort(key=lambda r: r["demo"])

    # canonicalize duplicate-content TRAIN rows (same bytes, different names) -> one per sha256.
    n_dedup = dedupe_train_by_sha(rows)
    if n_dedup:
        LOGGER.info("dedup: demoted %d duplicate-content TRAIN alias(es) to EXCLUDED", n_dedup)

    # content-lock gate: a TRAIN row without a pinned (sha256, size_bytes) cannot be a training
    # foundation (a later run would silently trust replaced/truncated bytes). Fail loud.
    bad = validate_provenance(rows)
    if bad:
        LOGGER.error("FATAL: %d TRAIN rows lack a content lock (sha256+size_bytes). "
                     "Pass --manifest-tsv with their hashes (or run --demo-dir to hash on disk). "
                     "First offenders: %s", len(bad), bad[:10])
        sys.exit(3)

    train = [r for r in rows if r["class"] == "TRAIN"]
    bot_excluded = sum(1 for r in rows if (r.get("reason") or "").startswith("bot_lab_default_teams"))
    dup_excluded = sum(1 for r in rows if (r.get("reason") or "").startswith("duplicate_content_sha"))
    ap_hist = Counter(r["active_players"] for r in rows if r["ok"])
    nt_hist = Counter(len(r["teams"] or []) for r in rows if r["ok"])
    map_hist = Counter(r["map"] for r in rows if r["ok"])
    have_lock = sum(1 for r in rows if r.get("sha256"))
    out = {
        "schema": "komodobots.human_4on4_dm3_mvd_manifest.v3",
        "ticket": "#358 / F-DATA-1 (.mvd via qw-analyze active-player read + bot-lab default-team exclusion)",
        "provenance": {
            "content_lock": "every row carries sha256+size_bytes; every TRAIN row is hard-gated to have it",
            "source": "--demo-dir mode hashes each file's own bytes during parse (analyze_one); "
                      "--reclassify mode merges sha256/size by basename from servexeri:"
                      "/mnt/usb-ssd/4on4-corpus/manifest.tsv via --manifest-tsv",
            "parser": parser_meta,
            "parser_note": "the binary above parsed the SELECTION fields (map/teams/active_players), "
                           "which are parser-version-robust; the per-tick MOVE extraction (ETL) "
                           "separately REQUIRES the schema-33 qw-analyze binary",
            "rows_with_lock": have_lock,
        },
        "team_min": a.team_min,
        "counts": {"scanned": len(rows), "train": len(train),
                   "excluded": len(rows) - len(train),
                   "bot_lab_default_teams_excluded": bot_excluded,
                   "duplicate_content_sha_excluded": dup_excluded,
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
