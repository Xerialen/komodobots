#!/usr/bin/env python3
"""carve_catalog_slice.py — carve a demo-subset slice out of a full MVD catalog SQLite.

The instrument-pool-growth round (plans/instrument-pool-growth.md): the Phase-4 catalog
(`dm3_4on4_human1537.sqlite`, 117 GB on servexeri) already holds everything; growing the honest
route-grade's qualifying pool is a CARVE, never a re-extraction. This script copies an explicit
demo-sha subset into a new SQLite with the SOURCE's schema (tables + indexes verbatim from its
`sqlite_master` — the slice cannot drift from the catalog schema by construction).

Honesty/provenance rules it enforces (fail closed):
  * subset membership comes ONLY from a committed sha-list file (never a --limit);
  * a requested sha missing from the source is an ERROR (absence of a requested demo must stop
    the build — the PR #449 `build_route_canon` SystemExit precedent), never a silent skip;
  * the source is cross-checked against the committed build record
    (`data/catalog/dm3_4on4_human1537.summary.json` row counts) before any copy — a mismatched
    source is not the artifact the provenance chain names;
  * a source table the policy does not know is an ERROR (fail closed on surprises); a
    CURRENT-schema table absent from the source (vintage gap, e.g. `damage_events` predates the
    Phase-4 build) is tolerated WITH a logged notice — the waiver is documented in the plan;
  * post-carve `PRAGMA foreign_key_check` must be empty and per-table counts are reported.

Stdlib only (sqlite3, json, argparse) — runs on servexeri's bare python3.
"""

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

LOGGER = logging.getLogger(__name__)

# Copy policy per table (see plans/instrument-pool-growth.md §3.2). WHOLE = static/spine tables
# that are FK targets of subset rows (omitting maps/players was the audit-M1 FK hole). Order is
# FK-dependency order: actions after player_ticks (composite FK), actor_ticks/item_events after
# teams. A source table not listed here is a hard error.
WHOLE_TABLES = ("maps", "markers", "nav_edges", "items", "item_value", "players",
                "feature_partitions")
BY_SHA_TABLES = ("demos",)                      # WHERE lower(sha256) IN subset
BY_DEMO_TABLES = ("teams", "item_events", "frag_events", "damage_events",
                  "region_control_timeline")    # WHERE demo_id IN carved demos
BY_EPISODE_TABLES = ("episodes", "player_ticks", "actions", "actor_ticks",
                     "actor_visibility", "audio_cues")
COPY_ORDER = (WHOLE_TABLES + BY_SHA_TABLES + ("episodes", "player_ticks", "actions", "teams",
              "actor_ticks", "actor_visibility", "audio_cues", "item_events", "frag_events",
              "damage_events", "region_control_timeline"))
KNOWN_TABLES = frozenset(WHOLE_TABLES) | frozenset(BY_SHA_TABLES) | \
    frozenset(BY_DEMO_TABLES) | frozenset(BY_EPISODE_TABLES)

# Committed build record of the ONLY source this round carves from. Cross-checked at run time
# (audit S1): a source that does not match the record is not the artifact the plan names.
SUMMARY_JSON = Path(__file__).resolve().parent.parent / "data" / "catalog" / \
    "dm3_4on4_human1537.summary.json"


def read_sha_list(path):
    """Read the committed subset list: '#'-comment header + one sha256 per line, lowercased."""
    shas = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        shas.append(line.lower())
    if not shas:
        raise SystemExit(f"[carve] sha list {path} holds no shas")
    if len(set(shas)) != len(shas):
        raise SystemExit(f"[carve] sha list {path} holds duplicates")
    return shas


def source_tables(con):
    rows = con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {name: sql for name, sql in rows}


def source_indexes(con):
    return [sql for (sql,) in con.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL").fetchall()]


def verify_source_against_summary(con, summary_path):
    """The cheap source re-verification: demos/episodes/player_ticks counts must equal the
    committed Phase-4 build record (`etl.table_counts` in the summary json)."""
    rec = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    expect = {t: rec["etl"]["table_counts"][t] for t in ("demos", "episodes", "player_ticks")}
    for table, want in expect.items():
        got = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if got != want:
            raise SystemExit(f"[carve] source mismatch vs committed summary: {table} has "
                             f"{got} rows, record says {want} — this is not the recorded "
                             f"Phase-4 catalog; refusing to carve")
    LOGGER.info("source matches committed summary (%s)", summary_path.name)


def carve(src, out, sha_list_path, summary_path=SUMMARY_JSON):
    src, out = Path(src), Path(out)
    if out.exists():
        raise SystemExit(f"[carve] refusing to overwrite existing {out}")
    shas = read_sha_list(sha_list_path)

    scon = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        verify_source_against_summary(scon, Path(summary_path))
        tables = source_tables(scon)
        unknown = sorted(set(tables) - KNOWN_TABLES)
        if unknown:
            raise SystemExit(f"[carve] source holds tables the copy policy does not know: "
                             f"{unknown} — extend the policy deliberately, never guess")
        have = [sha for (sha,) in scon.execute("SELECT lower(sha256) FROM demos").fetchall()]
        missing = sorted(set(shas) - set(have))
        if missing:
            raise SystemExit(f"[carve] {len(missing)} requested sha(s) missing from source "
                             f"(first: {missing[0][:16]}…) — absence of a requested demo is an "
                             f"error, not a skip")
    finally:
        scon.close()

    ocon = sqlite3.connect(out)
    try:
        ocon.execute("PRAGMA foreign_keys=OFF")     # bulk copy; checked as a whole afterwards
        ocon.execute(f"ATTACH DATABASE 'file:{src}?mode=ro' AS src")

        for name, sql in sorted(source_tables_attached(ocon).items()):
            ocon.execute(sql)                        # schema verbatim from the SOURCE
        placeholders = ",".join("?" for _ in shas)
        counts = {}
        for table in COPY_ORDER:
            if table not in source_tables_attached(ocon):
                LOGGER.warning("source predates table %s (vintage gap, see the plan's waiver) "
                               "— skipped", table)
                continue
            if table in WHOLE_TABLES:
                ocon.execute(f"INSERT INTO main.{table} SELECT * FROM src.{table}")
            elif table in BY_SHA_TABLES:
                ocon.execute(f"INSERT INTO main.{table} SELECT * FROM src.{table} "
                             f"WHERE lower(sha256) IN ({placeholders})", shas)
            elif table == "episodes":
                ocon.execute("INSERT INTO main.episodes SELECT * FROM src.episodes "
                             "WHERE demo_id IN (SELECT demo_id FROM main.demos)")
            elif table in BY_EPISODE_TABLES:
                ocon.execute(f"INSERT INTO main.{table} SELECT * FROM src.{table} "
                             f"WHERE episode_id IN (SELECT episode_id FROM main.episodes)")
            else:                                    # BY_DEMO event tables
                ocon.execute(f"INSERT INTO main.{table} SELECT * FROM src.{table} "
                             f"WHERE demo_id IN (SELECT demo_id FROM main.demos)")
            counts[table] = ocon.execute(f"SELECT COUNT(*) FROM main.{table}").fetchone()[0]
            LOGGER.info("copied %-24s %12d rows", table, counts[table])

        for sql in source_indexes_attached(ocon):
            ocon.execute(sql)
        ocon.commit()
        ocon.execute("DETACH DATABASE src")

        if ocon.execute("SELECT COUNT(*) FROM demos").fetchone()[0] != len(shas):
            raise SystemExit("[carve] carved demo count != requested list — refusing")
        ocon.execute("PRAGMA foreign_keys=ON")
        fk = ocon.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            raise SystemExit(f"[carve] foreign_key_check found {len(fk)} violations "
                             f"(first: {fk[0]}) — the slice is not internally consistent")
        LOGGER.info("foreign_key_check clean; %d demos carved into %s", len(shas), out)
        return counts
    finally:
        ocon.close()


def source_tables_attached(ocon):
    rows = ocon.execute(
        "SELECT name, sql FROM src.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {name: sql for name, sql in rows}


def source_indexes_attached(ocon):
    return [sql for (sql,) in ocon.execute(
        "SELECT sql FROM src.sqlite_master WHERE type='index' AND sql IS NOT NULL").fetchall()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, help="full catalog sqlite (read-only)")
    ap.add_argument("--out", required=True, help="output slice path (must not exist)")
    ap.add_argument("--demos", required=True, help="committed sha-list file (one sha256/line)")
    ap.add_argument("--summary", default=str(SUMMARY_JSON),
                    help="committed build record to cross-check the source against")
    a = ap.parse_args(argv)
    counts = carve(a.src, a.out, a.demos, a.summary)
    print(json.dumps({"out": str(a.out), "tables": counts}, indent=1))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
