#!/usr/bin/env python3
"""experiment_registry.py — append-only JSONL journal of RL training runs (T4.2 / #426).

WHAT THIS IS
============
One JSON line per event, two events per training run:

  kind="start"  — appended when training begins: the full resolved config (args +
                  fully-resolved reward config), the pinned data identity (sha256 of
                  the db / norm artifact / anchors), the code version, and the
                  environment hash. A start with no matching final = the run crashed
                  or is still running — failed runs stay visible in the journal.
  kind="final"  — appended after the checkpoint is saved: the selection outcome
                  (selected_it / selected_reason / saved_params), the honest
                  route-grade summary of the SELECTED candidate when
                  --select-by-route-grade produced one (None otherwise — the field is
                  nullable by design so the journal works with every selection mode),
                  and the ckpt path + sha256 so severed artifact lineage is detectable
                  (`verify`).

HONESTY CONTRACT (why the odd-looking guards exist)
---------------------------------------------------
* code_version — the pinnacle run dir is synced via `git archive` and is NOT a git
  checkout, so `git rev-parse` is unavailable exactly where real runs happen. The
  resolution order is: explicit --git-sha arg > a CODE_VERSION file at the tree root
  (the sync recipe writes it) > `git rev-parse HEAD` (dev boxes / CI). If ALL fail the
  record is written with code_version=None + provenance_incomplete=true and is
  INELIGIBLE for `best`/ranking — visible in `list`, never citable as evidence. A
  silent "UNKNOWN" default is exactly what the ML review gate blocks on.
* environment_hash — sha256 over (code_version, data sha256s, eval-route pins). Runs
  whose environment hashes differ were trained/graded under different code, data,
  normalization, or route sets; ranking them against each other is apples-to-oranges,
  so `best` operates per environment group and REFUSES a silent global answer when
  more than one group exists.
* config_id — sha256 over the canonical tuned config EXCLUDING the seed and
  run-specific outputs, so seed-replicates of one configuration group together (the
  tuning loop's lucky-seed guard re-runs a winning config across seeds and needs them
  to share an id).

The writer functions raise on real errors; the training-loop call sites wrap them in
try/except with a loud warning — a journal bug must never kill a finished training
run, but it must never fail silently either.

Registry file convention: `experiment_registry.jsonl` next to the checkpoints
(rl_onspeed --registry auto). Reading tolerates a torn trailing line (a crash mid-
append loses that line, never the file).

CLI:  list [--registry P]           runs joined start+final, grouped by environment
      best [--registry P] [--env H] top eligible run per environment group
      diff RUN_A RUN_B              config delta between two runs
      verify [--registry P]         recompute ckpt sha256s, flag missing/tampered
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import platform
import subprocess
import sys
import time
import uuid
from pathlib import Path

LOGGER = logging.getLogger(__name__)

RECORD_SCHEMA = "komodobots.experiment_run.v1"

# Excluded from config_id: run-specific outputs + the seed (seed-replicates of one
# configuration must share a config_id — the tuning loop's lucky-seed guard).
_CONFIG_ID_EXCLUDE = {"out_ckpt", "registry", "seed", "git_sha"}


# --------------------------------------------------------------------------- hashing
def sha256_file(path, chunk=1 << 20):
    """Streaming sha256 of a file; (hexdigest, size_bytes) or (None, None) if unreadable."""
    p = Path(path)
    try:
        h = hashlib.sha256()
        size = 0
        with open(p, "rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
                size += len(b)
        return h.hexdigest(), size
    except OSError:
        return None, None


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def config_id(args_dict, reward_config):
    """Stable 12-hex id of the tuned configuration (seed- and output-path-invariant)."""
    cfg = {k: v for k, v in dict(args_dict).items() if k not in _CONFIG_ID_EXCLUDE}
    return hashlib.sha256(
        _canonical({"args": cfg, "reward_config": dict(reward_config or {})}).encode()
    ).hexdigest()[:12]


def environment_hash(code_version, data, eval_pins):
    """12-hex hash of everything that makes two runs' grades comparable."""
    return hashlib.sha256(
        _canonical({"code_version": code_version, "data": data, "eval_pins": eval_pins}).encode()
    ).hexdigest()[:12]


def registry_path_for(out_ckpt, registry_arg="auto"):
    """Resolve the --registry CLI value: 'off' -> None, 'auto' -> the journal next to
    the checkpoint (experiment_registry.jsonl in the out-ckpt dir), else the given path."""
    r = str(registry_arg or "off").strip()
    if r.lower() == "off":
        return None
    if r.lower() == "auto":
        return str(Path(out_ckpt).expanduser().resolve().parent / "experiment_registry.jsonl")
    return str(Path(r).expanduser())


# ------------------------------------------------------------------- code version
def resolve_code_version(explicit=None, tree_root=None):
    """(sha_or_None, source). Order: explicit arg > CODE_VERSION file > git rev-parse.

    The CODE_VERSION file is how a non-git run dir (pinnacle, synced via git archive)
    carries provenance: the sync recipe writes `git rev-parse HEAD` into it at the
    tree root before shipping.
    """
    if explicit:
        return str(explicit).strip(), "arg"
    root = Path(tree_root) if tree_root else Path(__file__).resolve().parents[2]
    f = root / "CODE_VERSION"
    if f.is_file():
        sha = f.read_text().strip()
        if sha:
            return sha, "file"
    try:
        sha = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if sha:
            return sha, "git"
    except (OSError, subprocess.SubprocessError):
        pass
    return None, "missing"


# ------------------------------------------------------------------------- writer
def _append(registry_path, record):
    p = Path(registry_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, default=str)
    with open(p, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
    return record


def start_run(registry_path, args_dict, reward_config, git_sha=None, tree_root=None, now=None):
    """Append the start record; returns the run context finalize_run() needs.

    Hashes the data inputs ONCE here (the db can be GBs — a few seconds, paid at
    start, reused at finalize via the returned context).
    """
    args_dict = dict(args_dict)
    code_version, cv_source = resolve_code_version(git_sha, tree_root)
    if code_version is None:
        LOGGER.warning(
            "experiment_registry: NO code version (no --git-sha, no CODE_VERSION file, "
            "not a git checkout) — record flagged provenance_incomplete, ineligible for ranking")
    db_sha, db_bytes = sha256_file(args_dict["db"]) if args_dict.get("db") else (None, None)
    norm_sha, _ = (sha256_file(args_dict["norm_artifact"])
                   if args_dict.get("norm_artifact") else (None, None))
    anch_sha, _ = sha256_file(args_dict["anchors"]) if args_dict.get("anchors") else (None, None)
    data = {
        "db_path": args_dict.get("db"), "db_sha256": db_sha, "db_bytes": db_bytes,
        "norm_path": args_dict.get("norm_artifact"), "norm_sha256": norm_sha,
        "anchors_path": args_dict.get("anchors"), "anchors_sha256": anch_sha,
    }
    # The pins that determine WHICH held-out routes the honest grade runs on: the
    # holdout selection is deterministic given (db, split, horizon, skip, count).
    eval_pins = {
        "split": args_dict.get("split"),
        "horizon": args_dict.get("horizon"),
        "holdout_skip": args_dict.get("n_reset_segments"),
        "select_grade_segments": args_dict.get("select_grade_segments"),
    }
    ts = float(now) if now is not None else time.time()
    ctx = {
        "run_id": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(ts)) + "-" + uuid.uuid4().hex[:8],
        "config_id": config_id(args_dict, reward_config),
        "environment_hash": environment_hash(code_version, data, eval_pins),
        "code_version": code_version,
        "provenance_incomplete": code_version is None,
        "t_start": ts,
    }
    record = {
        "record_schema": RECORD_SCHEMA, "kind": "start",
        "run_id": ctx["run_id"],
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
        "code_version": code_version, "code_version_source": cv_source,
        "provenance_incomplete": ctx["provenance_incomplete"],
        "config_id": ctx["config_id"], "environment_hash": ctx["environment_hash"],
        "args": args_dict, "reward_config": dict(reward_config or {}),
        "data": data, "eval_pins": eval_pins,
        "env": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            # taken from the already-loaded module — this module never imports torch
            "torch": getattr(sys.modules.get("torch"), "__version__", None),
        },
    }
    _append(registry_path, record)
    return ctx


def finalize_run(registry_path, ctx, result, ckpt_path=None, now=None):
    """Append the final record: selection outcome + honest grade + ckpt lineage."""
    ts = float(now) if now is not None else time.time()
    ck_sha, ck_bytes = sha256_file(ckpt_path) if ckpt_path else (None, None)
    record = {
        "record_schema": RECORD_SCHEMA, "kind": "final",
        "run_id": ctx["run_id"],
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
        "config_id": ctx["config_id"], "environment_hash": ctx["environment_hash"],
        "provenance_incomplete": ctx.get("provenance_incomplete", False),
        "status": "completed",
        "wall_time_s": round(ts - ctx.get("t_start", ts), 1),
        "result": dict(result or {}),
        "ckpt": {"path": (str(ckpt_path) if ckpt_path else None),
                 "sha256": ck_sha, "bytes": ck_bytes},
    }
    _append(registry_path, record)
    return record


# ------------------------------------------------------------------------- reader
def read_records(registry_path):
    """All parseable records; a torn trailing line (crash mid-append) is skipped loudly."""
    p = Path(registry_path)
    out = []
    if not p.is_file():
        return out
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            LOGGER.warning("experiment_registry: skipping unparseable line %d of %s", i, p)
    return out


def join_runs(records):
    """run_id -> {"start": rec|None, "final": rec|None, "status": ...}.

    status: "completed" | "incomplete" (start with no final = crashed or running).
    """
    runs = {}
    for r in records:
        if r.get("record_schema") != RECORD_SCHEMA:
            LOGGER.warning("experiment_registry: skipping record with schema %r",
                           r.get("record_schema"))
            continue
        slot = runs.setdefault(r.get("run_id"), {"start": None, "final": None})
        kind = r.get("kind")
        if kind in ("start", "final"):
            slot[kind] = r
    for run in runs.values():
        run["status"] = (run["final"] or {}).get("status", "incomplete")
    return runs


def eligible(run):
    """(ok, reason). Eligible for ranking = completed + full provenance + a route grade."""
    if run.get("final") is None:
        return False, "incomplete (no final record — crashed or still running)"
    if (run["final"].get("provenance_incomplete")
            or (run["start"] or {}).get("provenance_incomplete")):
        return False, "provenance_incomplete (no code version pinned)"
    if not (run["final"].get("result") or {}).get("route_grade_summary"):
        return False, "no route_grade_summary (run not graded by the honest route-grade)"
    return True, "eligible"


def _grade_key(run):
    # Mirrors route_grade.rank_by_route_grade's ordering (kept local: this CLI must
    # run standalone with no repo sys.path setup).
    s = run["final"]["result"]["route_grade_summary"]
    return (s.get("seg_faster_frac", 0.0),
            s.get("median_speedup_ratio", 0.0),
            -s.get("median_route_rmse_qu", 0.0))


def rank_runs(runs):
    """{environment_hash: [eligible runs, best first]} — never ranks across groups."""
    groups = {}
    for rid, run in runs.items():
        ok, _ = eligible(run)
        if not ok:
            continue
        env = run["final"].get("environment_hash")
        groups.setdefault(env, []).append((rid, run))
    return {env: sorted(rs, key=lambda x: _grade_key(x[1]), reverse=True)
            for env, rs in groups.items()}


def diff_configs(run_a, run_b):
    """{key: (a_value, b_value)} over args + reward_config where the two runs differ."""
    out = {}
    for section in ("args", "reward_config"):
        a = (run_a["start"] or {}).get(section, {})
        b = (run_b["start"] or {}).get(section, {})
        for k in sorted(set(a) | set(b)):
            if a.get(k) != b.get(k):
                out[f"{section}.{k}"] = (a.get(k), b.get(k))
    return out


# ---------------------------------------------------------------------------- CLI
def _fmt_run(rid, run):
    st = run["status"]
    res = (run["final"] or {}).get("result", {}) or {}
    g = res.get("route_grade_summary") or {}
    grade = (f"faster_frac={g.get('seg_faster_frac')} ratio={g.get('median_speedup_ratio')}"
             if g else "ungraded")
    cfg = (run["start"] or run["final"] or {}).get("config_id", "?")
    env = (run["start"] or run["final"] or {}).get("environment_hash", "?")
    flag = " PROVENANCE-INCOMPLETE" if not eligible(run)[0] and "provenance" in eligible(run)[1] else ""
    return f"{rid}  cfg={cfg} env={env} {st:<10} {grade}{flag}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--registry", default="experiment_registry.jsonl")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p_best = sub.add_parser("best")
    p_best.add_argument("--env", default=None,
                        help="environment_hash to rank within (required when several exist)")
    p_diff = sub.add_parser("diff")
    p_diff.add_argument("run_a")
    p_diff.add_argument("run_b")
    sub.add_parser("verify")
    a = ap.parse_args(argv)

    runs = join_runs(read_records(a.registry))
    if a.cmd == "list":
        for rid in sorted(runs):
            print(_fmt_run(rid, runs[rid]))
        print(f"{len(runs)} run(s) in {a.registry}")
        return 0

    if a.cmd == "best":
        groups = rank_runs(runs)
        if not groups:
            print("no eligible runs (completed + provenance-complete + route-graded)")
            return 1
        if a.env is None and len(groups) > 1:
            print(f"REFUSING a global 'best': {len(groups)} environment groups (different "
                  "code/data/norm/route pins — grades are not comparable across them).")
            for env, rs in groups.items():
                print(f"  --env {env}  ({len(rs)} run(s))")
            return 1
        env = a.env if a.env is not None else next(iter(groups))
        if env not in groups:
            print(f"no eligible runs in environment group {env}")
            return 1
        rid, run = groups[env][0]
        print(_fmt_run(rid, run))
        print(json.dumps({"args": run["start"]["args"],
                          "reward_config": run["start"]["reward_config"]},
                         indent=2, sort_keys=True, default=str))
        return 0

    if a.cmd == "diff":
        for rid in (a.run_a, a.run_b):
            if rid not in runs:
                print(f"unknown run_id {rid}")
                return 1
        delta = diff_configs(runs[a.run_a], runs[a.run_b])
        for k, (va, vb) in delta.items():
            print(f"{k}: {va!r} -> {vb!r}")
        print(f"{len(delta)} differing key(s)")
        return 0

    if a.cmd == "verify":
        bad = 0
        for rid, run in sorted(runs.items()):
            ck = (run["final"] or {}).get("ckpt") or {}
            if not ck.get("path") or not ck.get("sha256"):
                continue
            sha, _ = sha256_file(ck["path"])
            if sha is None:
                print(f"{rid}: MISSING {ck['path']}")
                bad += 1
            elif sha != ck["sha256"]:
                print(f"{rid}: SHA MISMATCH {ck['path']} (recorded {ck['sha256'][:12]}…, "
                      f"actual {sha[:12]}…)")
                bad += 1
            else:
                print(f"{rid}: ok")
        return 1 if bad else 0
    return 2


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
