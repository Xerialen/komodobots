#!/usr/bin/env python3
"""Archive lab-run MVDs to the servexeri demo SSD (issue #64).

User directive (2026-06-10): EVERY lab attempt's MVD is archived to
`servexeri:/mnt/usb-ssd/non-games/lab/Komodobots/<map>/<run_id>.mvd`.

Two entry points:

1. Post-run hook -- `run_frobodm2_lab.py` calls `archive_run_demo()` after each
   completed run. The copy happens entirely server-side (the recorded demo is
   already in `~/komodobots-lab/runs/<run_id>/demo.mvd`), is sha256-verified,
   idempotent (skip-if-identical), and NEVER fatal to the run: any archive
   failure is a loud stderr warning, because the run's data must survive an
   SSD hiccup.

2. Backfill -- `python scripts/demo_archive.py --backfill` reconciles every
   known MVD source against the SSD tree and copies what is missing:
     * local `artifacts/lab-runs/<run_id>/demo.mvd` (map from `run.env`),
     * server-side `~/komodobots-lab/runs/<run_id>/demo.mvd` (map from `run.env`),
     * the local ezQuake review mirrors: the lab runner's watch mirror
       `C:\\nQuake\\qw\\matchinfo\\demos\\tricks\\dm3\\<label>__<run_id>.mvd`
       (where `run_frobodm2_lab.py --record-trick-name` dual-writes) plus the
       older `C:\\nQuake\\qw\\tricks\\dm3\\<run_id>.mvd` location,
     * the repo's `tricks/<map>/*.mvd` evidence demos (the 16 committed ones
       plus any local-only copies in the same tree -- for some historical runs
       these are the ONLY remaining bytes).
   Everything is sha256-verified (sources hashed, SSD hashed, the SSD is
   re-read after installs) and a per-map count table is printed:
   sources found / already archived / newly copied / unverifiable.

Naming decision for repo `tricks/` demos: they are named `<label>__<run_id>.mvd`
(some older ones are label-only, e.g. `trick_accel_full__solo_lab_d200.mvd`).
They are archived under their FULL original filename --
`<SSD>/<map>/<label>__<run_id>.mvd` -- NOT normalized to `<run_id>.mvd`. The
repo copy is a separately-produced artifact and may differ byte-wise from the
run dir's `demo.mvd` for the same run id; normalizing would collide two
different byte streams under one archive name (and the mismatch guard would
then rightly refuse the second forever). Keeping the full stem is collision-free
and preserves the label context the evidence was committed with.

All SSD writes are atomic on the destination filesystem: copy to
`<dst>.part.$$` first, verify the temp's sha256, then `mv` into place. An
existing destination with a different hash is NEVER overwritten (reported as
`mismatch` instead).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "lab-runs"
# Both local ezQuake review-mirror locations are scanned. The first is where
# `run_frobodm2_lab.py --record-trick-name` actually dual-writes (it must stay
# in sync with NQUAKE_TRICKS_DM3_DIR in scripts/run_frobodm2_lab.py); the
# second is the older mirror location kept for any historical copies.
NQUAKE_TRICKS_DM3_DIRS = (
    Path(r"C:\nQuake\qw\matchinfo\demos\tricks\dm3"),
    Path(r"C:\nQuake\qw\tricks\dm3"),
)
REPO_TRICKS_DIR = REPO_ROOT / "tricks"

DEFAULT_HOST = "servexeri"
SSD_ROOT = "/mnt/usb-ssd/non-games/lab/Komodobots"
# Relative to $HOME on the lab host (matches run_frobodm2_lab.py's rundir).
REMOTE_RUNS_DIR = "komodobots-lab/runs"
REMOTE_STAGING_DIR = "komodobots-lab/.archive-staging"

# Same character sets run_frobodm2_lab.py enforces at argparse time. They keep
# every remote path one safe token (no slashes, no dot segments, no
# whitespace), so run_id/map can be passed as `bash -s --` argv safely.
_MAP_NAME_RE = re.compile(r"[A-Za-z0-9_+-]+\Z")
_RUN_ID_RE = re.compile(r"[A-Za-z0-9_-]+\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

ARCHIVE_OK_STATUSES = ("copied", "identical")


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested in tests/test_demo_archive.py)
# ---------------------------------------------------------------------------


def validate_map_name(map_name: str) -> str:
    if not _MAP_NAME_RE.fullmatch(map_name or ""):
        raise ValueError(f"Invalid map name for archival: {map_name!r}")
    return map_name


def validate_run_id(run_id: str) -> str:
    if not _RUN_ID_RE.fullmatch(run_id or ""):
        raise ValueError(f"Invalid run id for archival: {run_id!r}")
    return run_id


def ssd_archive_path(map_name: str, run_id: str) -> str:
    """Map a run's (map, run_id) to its canonical SSD archive path."""
    return f"{SSD_ROOT}/{validate_map_name(map_name)}/{validate_run_id(run_id)}.mvd"


def ssd_archive_path_safe(map_name: str, run_id: str) -> str:
    try:
        return ssd_archive_path(map_name, run_id)
    except ValueError:
        return ""


def parse_sha256_text(text: str) -> str:
    """Extract a sha256 hex digest from `sha256sum` output or a bare hash line.

    Returns "" when no valid digest is present (e.g. empty/garbled file).
    """
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        token = stripped.split()[0].lower()
        if _SHA256_RE.fullmatch(token):
            return token
    return ""


def parse_run_env_map(text: str) -> str:
    """Extract MAP=<name> from a run.env body; "" when absent or invalid."""
    for line in (text or "").splitlines():
        if line.startswith("MAP="):
            value = line.split("=", 1)[1].strip()
            return value if _MAP_NAME_RE.fullmatch(value) else ""
    return ""


def parse_inventory_tsv(text: str) -> list[dict[str, str]]:
    """Parse `run_id<TAB>map<TAB>sha256<TAB>size` manifest lines.

    Malformed lines (wrong field count, bad run id/map/sha) are skipped -- a
    single garbled entry must not poison the whole reconcile.
    """
    rows: list[dict[str, str]] = []
    for line in (text or "").splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 4:
            continue
        run_id, map_name, sha, size = (p.strip() for p in parts)
        if not _RUN_ID_RE.fullmatch(run_id):
            continue
        if not _MAP_NAME_RE.fullmatch(map_name):
            continue
        if not _SHA256_RE.fullmatch(sha.lower()):
            continue
        rows.append({"run_id": run_id, "map": map_name, "sha256": sha.lower(), "size": size})
    return rows


def parse_archive_result(text: str) -> dict[str, str]:
    """Parse the LAST `KB_ARCHIVE k=v ...` line from remote archiver output.

    Returns at least {"status": ...}; status is "no-result" when the output
    has no parseable line (ssh died, wrong script, ...).
    """
    result: dict[str, str] = {}
    for fields in _iter_archive_lines(text):
        result = fields
    result.setdefault("status", "no-result")
    return result


def parse_all_archive_results(text: str) -> dict[tuple[str, str], dict[str, str]]:
    """Parse EVERY `KB_ARCHIVE` line into {(map, run_id): fields}."""
    results: dict[tuple[str, str], dict[str, str]] = {}
    for fields in _iter_archive_lines(text):
        if "run" in fields and "map" in fields:
            results[(fields["map"], fields["run"])] = fields
    return results


def _iter_archive_lines(text: str):
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("KB_ARCHIVE "):
            continue
        fields: dict[str, str] = {}
        for token in line.split()[1:]:
            key, sep, value = token.partition("=")
            if sep:
                fields[key] = value
        if fields:
            yield fields


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Remote scripts (piped over `ssh host bash -s --`, REMOTE_SCRIPT-style).
# Only `set -u`, deliberately NOT `set -e`: every outcome must be reported as
# a KB_ARCHIVE status line instead of an opaque non-zero exit.
# ---------------------------------------------------------------------------

# Shared installer: atomically install $1 (source file) as $root/$3/$2.mvd,
# verifying against expected sha256 $4 ("" = trust the source's current hash).
_INSTALL_FN = r"""
root="%(ssd_root)s"

emit() { # rid map status sha
  printf 'KB_ARCHIVE run=%%s map=%%s status=%%s sha256=%%s dst=%%s\n' \
    "$1" "$2" "$3" "$4" "$root/$2/$1.mvd"
}

install_one() { # src rid map expected_sha
  src="$1"; rid="$2"; map="$3"; want="$4"
  dst_dir="$root/$map"
  dst="$dst_dir/$rid.mvd"
  if [ ! -s "$src" ]; then emit "$rid" "$map" missing-src ""; return 0; fi
  src_sha="$(sha256sum -- "$src" 2>/dev/null | cut -d' ' -f1)"
  if [ -z "$src_sha" ]; then emit "$rid" "$map" hash-failed ""; return 0; fi
  if [ -n "$want" ] && [ "$src_sha" != "$want" ]; then
    emit "$rid" "$map" src-changed "$src_sha"; return 0
  fi
  if [ -e "$dst" ]; then
    dst_sha="$(sha256sum -- "$dst" 2>/dev/null | cut -d' ' -f1)"
    if [ -z "$dst_sha" ]; then
      emit "$rid" "$map" hash-failed "$src_sha"
    elif [ "$dst_sha" = "$src_sha" ]; then
      emit "$rid" "$map" identical "$src_sha"
    else
      emit "$rid" "$map" mismatch "$src_sha"
    fi
    return 0
  fi
  mkdir -p -- "$dst_dir" 2>/dev/null || { emit "$rid" "$map" mkdir-failed "$src_sha"; return 0; }
  tmp="$dst.part.$$"
  if ! cp -- "$src" "$tmp" 2>/dev/null; then
    rm -f -- "$tmp"; emit "$rid" "$map" copy-failed "$src_sha"; return 0
  fi
  out_sha="$(sha256sum -- "$tmp" 2>/dev/null | cut -d' ' -f1)"
  if [ "$out_sha" != "$src_sha" ]; then
    rm -f -- "$tmp"; emit "$rid" "$map" verify-failed "$src_sha"; return 0
  fi
  if ! mv -- "$tmp" "$dst" 2>/dev/null; then
    rm -f -- "$tmp"; emit "$rid" "$map" mv-failed "$src_sha"; return 0
  fi
  emit "$rid" "$map" copied "$src_sha"
}
""" % {"ssd_root": SSD_ROOT}

# Post-run hook: archive one run dir's demo.mvd. argv: run_id map_name
ARCHIVE_ONE_SCRIPT = (
    "set -u\n"
    + _INSTALL_FN
    + f'\ninstall_one "$HOME/{REMOTE_RUNS_DIR}/$1/demo.mvd" "$1" "$2" ""\n'
)

# Backfill installer: plan lines arrive on fd 3 (a quoted heredoc prepended by
# `_install_plan`, so plan content is data, never code):
#   kind<TAB>run_id<TAB>map<TAB>sha       kind: run | staging
BACKFILL_INSTALL_SCRIPT = (
    "set -u\n"
    + _INSTALL_FN
    + rf"""
while IFS="$(printf '\t')" read -r kind rid map sha <&3; do
  [ -n "$rid" ] || continue
  case "$kind" in
    run)     src="$HOME/{REMOTE_RUNS_DIR}/$rid/demo.mvd" ;;
    staging) src="$HOME/{REMOTE_STAGING_DIR}/${{map}}__${{rid}}.mvd" ;;
    *)       emit "$rid" "$map" bad-plan-kind ""; continue ;;
  esac
  install_one "$src" "$rid" "$map" "$sha"
done
exit 0
"""
)

REMOTE_RUNS_INVENTORY_SCRIPT = r"""
set -u
for d in "$HOME"/%(runs)s/*/; do
  [ -s "${d}demo.mvd" ] || continue
  rid="$(basename "$d")"
  map="$(sed -n 's/^MAP=//p' "${d}run.env" 2>/dev/null | head -n 1)"
  sha="$(sha256sum -- "${d}demo.mvd" | cut -d' ' -f1)"
  size="$(stat -c %%s -- "${d}demo.mvd")"
  printf '%%s\t%%s\t%%s\t%%s\n' "$rid" "${map:-}" "$sha" "$size"
done
""" % {"runs": REMOTE_RUNS_DIR}

SSD_INVENTORY_SCRIPT = r"""
set -u
for f in %(root)s/*/*.mvd; do
  [ -e "$f" ] || continue
  map="$(basename "$(dirname "$f")")"
  rid="$(basename "$f" .mvd)"
  sha="$(sha256sum -- "$f" | cut -d' ' -f1)"
  size="$(stat -c %%s -- "$f")"
  printf '%%s\t%%s\t%%s\t%%s\n' "$rid" "$map" "$sha" "$size"
done
""" % {"root": SSD_ROOT}


def _ssh_script(
    host: str,
    script: str,
    argv: list[str] | None = None,
    *,
    timeout: float = 600.0,
) -> subprocess.CompletedProcess[str]:
    """Pipe a bash script to the host over ssh stdin. Does not raise on rc != 0."""
    raw = subprocess.run(
        ["ssh", host, "bash", "-s", "--", *(argv or [])],
        input=script.replace("\r\n", "\n").encode("utf-8"),
        capture_output=True,
        timeout=timeout,
    )
    return subprocess.CompletedProcess(
        raw.args,
        raw.returncode,
        raw.stdout.decode("utf-8", "replace"),
        raw.stderr.decode("utf-8", "replace"),
    )


# ---------------------------------------------------------------------------
# Post-run hook
# ---------------------------------------------------------------------------


def archive_run_demo(
    host: str,
    run_id: str,
    map_name: str,
    *,
    local_run_dir: Path | None = None,
    timeout: float = 180.0,
) -> dict[str, str]:
    """Archive one completed run's server-side MVD to the SSD. NEVER raises.

    Returns the parsed result dict (status `copied`/`identical` on success).
    On any failure prints a loud warning to stderr and carries on -- the lab
    run itself must not die on an archive problem.
    """
    result: dict[str, str]
    try:
        validate_run_id(run_id)
        validate_map_name(map_name)
        proc = _ssh_script(host, ARCHIVE_ONE_SCRIPT, [run_id, map_name], timeout=timeout)
        result = parse_archive_result(proc.stdout)
        if result["status"] == "no-result":
            stderr_lines = (proc.stderr or "").strip().splitlines()
            result["detail"] = stderr_lines[-1] if stderr_lines else f"ssh exit {proc.returncode}"
    except Exception as exc:  # noqa: BLE001 - the hook must never kill a run
        result = {"status": "error", "detail": str(exc)}

    result.setdefault("dst", ssd_archive_path_safe(map_name, run_id))
    line = (
        f"demo_archive status={result.get('status', '')} "
        f"dst={result.get('dst', '')} sha256={result.get('sha256', '')}"
    )
    print(line)
    if result.get("status") not in ARCHIVE_OK_STATUSES:
        print(
            "WARNING: SSD demo archival FAILED (non-fatal; the run's data is intact "
            f"in artifacts/ and on {host}): {result}",
            file=sys.stderr,
        )
        print(
            "WARNING: re-archive later with: python scripts/demo_archive.py "
            f"--host {host} --run-id {run_id} --map {map_name}",
            file=sys.stderr,
        )
    if local_run_dir is not None:
        try:
            (local_run_dir / "archive.result.txt").write_text(line + "\n", encoding="utf-8")
        except OSError:
            pass
    return result


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------


def collect_local_artifact_sources() -> tuple[list[dict[str, str]], list[str]]:
    """Hash every artifacts/lab-runs/<rid>/demo.mvd; map comes from run.env."""
    rows: list[dict[str, str]] = []
    skipped: list[str] = []
    if not ARTIFACT_ROOT.is_dir():
        return rows, skipped
    for run_dir in sorted(ARTIFACT_ROOT.iterdir()):
        demo = run_dir / "demo.mvd"
        if not run_dir.is_dir() or not demo.is_file() or demo.stat().st_size == 0:
            continue
        run_id = run_dir.name
        if not _RUN_ID_RE.fullmatch(run_id):
            skipped.append(f"artifacts: bad run id {run_id!r}")
            continue
        env_path = run_dir / "run.env"
        map_name = ""
        if env_path.is_file():
            map_name = parse_run_env_map(env_path.read_text(encoding="utf-8", errors="replace"))
        if not map_name:
            skipped.append(f"artifacts: no MAP in run.env for {run_id}")
            continue
        rows.append(
            {
                "run_id": run_id,
                "map": map_name,
                "sha256": sha256_file(demo),
                "size": str(demo.stat().st_size),
                "where": "artifacts",
                "path": str(demo),
            }
        )
    return rows, skipped


def collect_nquake_dm3_sources(
    mirror_dirs: tuple[Path, ...] = NQUAKE_TRICKS_DM3_DIRS,
) -> tuple[list[dict[str, str]], list[str]]:
    """Hash the local ezQuake review mirrors (dm3 by construction).

    Scans every configured mirror dir: the runner's watch mirror holds
    `<label>__<run_id>.mvd` names (same stems as `tricks/dm3/`, so the full
    stem is the archive run id, consistent with the repo-tricks naming
    decision), the older location holds bare `<run_id>.mvd` names. Missing
    dirs are skipped. If the same stem appears in more than one mirror,
    reconcile() groups the rows by (map, stem) and flags a source-conflict
    when the hashes disagree.
    """
    rows: list[dict[str, str]] = []
    skipped: list[str] = []
    for mirror_dir in mirror_dirs:
        if not mirror_dir.is_dir():
            continue
        for path in sorted(mirror_dir.glob("*.mvd")):
            run_id = path.stem
            if not _RUN_ID_RE.fullmatch(run_id):
                skipped.append(f"nquake: non-run-id mvd name {path.name!r}")
                continue
            if path.stat().st_size == 0:
                skipped.append(f"nquake: empty mvd {path.name!r}")
                continue
            rows.append(
                {
                    "run_id": run_id,
                    "map": "dm3",
                    "sha256": sha256_file(path),
                    "size": str(path.stat().st_size),
                    "where": "nquake",
                    "path": str(path),
                }
            )
    return rows, skipped


def collect_repo_tricks_sources(
    tricks_root: Path = REPO_TRICKS_DIR,
) -> tuple[list[dict[str, str]], list[str]]:
    """Hash the repo's `tricks/<map>/*.mvd` evidence demos.

    Named `<label>__<run_id>.mvd` (older ones label-only). The FULL stem is
    the archive run id, so the SSD keeps the original filename -- see the
    module docstring for why it is never normalized to `<run_id>.mvd`.
    """
    rows: list[dict[str, str]] = []
    skipped: list[str] = []
    if not tricks_root.is_dir():
        return rows, skipped
    for map_dir in sorted(tricks_root.iterdir()):
        if not map_dir.is_dir():
            continue
        map_name = map_dir.name
        if not _MAP_NAME_RE.fullmatch(map_name):
            skipped.append(f"repo-tricks: bad map dir name {map_name!r}")
            continue
        for path in sorted(map_dir.glob("*.mvd")):
            stem = path.stem
            if not _RUN_ID_RE.fullmatch(stem):
                skipped.append(f"repo-tricks: hostile mvd name {path.name!r}")
                continue
            if path.stat().st_size == 0:
                skipped.append(f"repo-tricks: empty mvd {path.name!r}")
                continue
            rows.append(
                {
                    "run_id": stem,
                    "map": map_name,
                    "sha256": sha256_file(path),
                    "size": str(path.stat().st_size),
                    "where": "repo-tricks",
                    "path": str(path),
                }
            )
    return rows, skipped


def collect_remote_run_sources(host: str) -> list[dict[str, str]]:
    proc = _ssh_script(host, REMOTE_RUNS_INVENTORY_SCRIPT, timeout=900.0)
    if proc.returncode != 0:
        raise RuntimeError(
            f"remote runs inventory failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    rows = parse_inventory_tsv(proc.stdout)
    for row in rows:
        row["where"] = "server"
        row["path"] = f"~/{REMOTE_RUNS_DIR}/{row['run_id']}/demo.mvd"
    return rows


def collect_ssd_inventory(host: str) -> list[dict[str, str]]:
    proc = _ssh_script(host, SSD_INVENTORY_SCRIPT, timeout=900.0)
    if proc.returncode != 0:
        raise RuntimeError(f"SSD inventory failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return parse_inventory_tsv(proc.stdout)


def reconcile(
    sources: list[dict[str, str]],
    ssd_rows: list[dict[str, str]],
) -> dict[str, object]:
    """Group sources by (map, run_id) and classify against the SSD state."""
    by_key: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in sources:
        by_key.setdefault((row["map"], row["run_id"]), []).append(row)
    ssd_by_key = {(r["map"], r["run_id"]): r["sha256"] for r in ssd_rows}

    already: list[tuple[str, str]] = []
    to_copy: list[dict[str, str]] = []  # one preferred source per missing key
    unverifiable: list[dict[str, str]] = []

    for key in sorted(by_key):
        map_name, run_id = key
        rows = by_key[key]
        shas = sorted({r["sha256"] for r in rows})
        ssd_sha = ssd_by_key.get(key)
        if len(shas) > 1:
            # Sources disagree among themselves. If the SSD already holds one
            # of the candidate hashes the archive is at least as good as any
            # source; otherwise nobody can say which bytes are authoritative.
            if ssd_sha in shas:
                already.append(key)
            else:
                unverifiable.append(
                    {
                        "map": map_name,
                        "run_id": run_id,
                        "reason": "source-conflict",
                        "detail": ", ".join(f"{r['where']}={r['sha256'][:12]}" for r in rows),
                    }
                )
            continue
        if ssd_sha is not None:
            if ssd_sha == shas[0]:
                already.append(key)
            else:
                unverifiable.append(
                    {
                        "map": map_name,
                        "run_id": run_id,
                        "reason": "ssd-mismatch",
                        "detail": f"ssd={ssd_sha[:12]} source={shas[0][:12]} (never overwritten)",
                    }
                )
            continue
        # Missing on the SSD: prefer a server-side source (no upload needed),
        # then artifacts, then the nQuake mirror, then the repo tricks tree.
        order = {"server": 0, "artifacts": 1, "nquake": 2, "repo-tricks": 3}
        best = sorted(rows, key=lambda r: order.get(r["where"], 9))[0]
        to_copy.append(best)

    source_keys = set(by_key)
    ssd_only = sorted(k for k in ssd_by_key if k not in source_keys)
    return {
        "by_key": by_key,
        "already": already,
        "to_copy": to_copy,
        "unverifiable": unverifiable,
        "ssd_only": ssd_only,
    }


def _stage_uploads(host: str, uploads: list[dict[str, str]], batch_size: int = 40) -> None:
    """Copy local demos to a temp dir as <map>__<run_id>.mvd, then batch-scp them up.

    The map prefix keeps two same-run_id demos from DIFFERENT maps (a case
    reconcile() deliberately keeps separate) from clobbering each other in the
    shared staging dir; the installer's staging branch reads the same name."""
    proc = _ssh_script(host, f'mkdir -p "$HOME/{REMOTE_STAGING_DIR}"\n', timeout=60.0)
    if proc.returncode != 0:
        raise RuntimeError(f"could not create staging dir: {proc.stderr.strip()}")
    with tempfile.TemporaryDirectory(prefix="kb-archive-") as tmp:
        tmp_dir = Path(tmp)
        staged: list[str] = []
        for row in uploads:
            dst = tmp_dir / f"{row['map']}__{row['run_id']}.mvd"
            shutil.copy2(row["path"], dst)
            staged.append(str(dst))
        for index in range(0, len(staged), batch_size):
            batch = staged[index : index + batch_size]
            raw = subprocess.run(
                ["scp", "-q", *batch, f"{host}:{REMOTE_STAGING_DIR}/"],
                capture_output=True,
                text=True,
                timeout=1800,
            )
            if raw.returncode != 0:
                raise RuntimeError(f"scp staging batch failed: {raw.stderr.strip()}")


def _install_plan(
    host: str, plan: list[tuple[str, str, str, str]]
) -> dict[tuple[str, str], dict[str, str]]:
    """Run the remote installer for (kind, run_id, map, sha) plan entries."""
    lines = "".join("\t".join(item) + "\n" for item in plan)
    full = "exec 3<<'KB_PLAN_EOF'\n" + lines + "KB_PLAN_EOF\n" + BACKFILL_INSTALL_SCRIPT
    proc = _ssh_script(host, full, timeout=3600.0)
    if proc.returncode != 0:
        raise RuntimeError(
            f"backfill installer failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    return parse_all_archive_results(proc.stdout)


def _cleanup_staging(host: str) -> None:
    proc = _ssh_script(host, f'rm -rf "$HOME/{REMOTE_STAGING_DIR}"\n', timeout=120.0)
    if proc.returncode != 0:
        print(f"WARNING: could not clean staging dir on {host}: {proc.stderr.strip()}", file=sys.stderr)


def _count_table(
    state: dict[str, object],
    copied_ok: list[tuple[str, str]],
    unverifiable: list[dict[str, str]],
    applied: bool,
) -> str:
    by_key = state["by_key"]
    already = state["already"]
    ssd_only = state["ssd_only"]
    maps = sorted({m for m, _ in by_key} | {m for m, _ in ssd_only})
    lines = [
        "| map | sources found | already archived | newly copied | unverifiable | ssd-only |",
        "|---|---|---|---|---|---|",
    ]
    totals = [0, 0, 0, 0, 0]
    for map_name in maps:
        found = sum(1 for (m, _r) in by_key if m == map_name)
        arch = sum(1 for (m, _r) in already if m == map_name)
        new = sum(1 for (m, _r) in copied_ok if m == map_name)
        unv = sum(1 for u in unverifiable if u["map"] == map_name)
        only = sum(1 for (m, _r) in ssd_only if m == map_name)
        for i, v in enumerate((found, arch, new, unv, only)):
            totals[i] += v
        lines.append(f"| {map_name} | {found} | {arch} | {new} | {unv} | {only} |")
    unmapped = sum(1 for u in unverifiable if u["map"] == "?")
    if unmapped:
        totals[3] += unmapped
        lines.append(f"| ? | 0 | 0 | 0 | {unmapped} | 0 |")
    lines.append(
        f"| **total** | **{totals[0]}** | **{totals[1]}** | **{totals[2]}** "
        f"| **{totals[3]}** | **{totals[4]}** |"
    )
    if not applied:
        lines.append("")
        lines.append("(dry run: nothing copied; planned copies reported in the log above)")
    return "\n".join(lines)


def backfill(host: str, *, apply: bool) -> int:
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[backfill] start {started} host={host} apply={apply}")

    print("[backfill] hashing local artifacts/lab-runs ...")
    artifact_rows, skipped_a = collect_local_artifact_sources()
    print(f"[backfill]   {len(artifact_rows)} demos")
    print("[backfill] hashing local nQuake dm3 mirror ...")
    nquake_rows, skipped_n = collect_nquake_dm3_sources()
    print(f"[backfill]   {len(nquake_rows)} demos")
    print("[backfill] hashing repo tricks/<map> evidence demos ...")
    repo_rows, skipped_r = collect_repo_tricks_sources()
    print(f"[backfill]   {len(repo_rows)} demos")
    print("[backfill] hashing server-side run dirs (ssh) ...")
    server_rows = collect_remote_run_sources(host)
    print(f"[backfill]   {len(server_rows)} demos")
    print("[backfill] hashing SSD archive (ssh) ...")
    ssd_rows = collect_ssd_inventory(host)
    print(f"[backfill]   {len(ssd_rows)} archived files")

    sources = server_rows + artifact_rows + nquake_rows + repo_rows
    state = reconcile(sources, ssd_rows)
    to_copy: list[dict[str, str]] = state["to_copy"]
    unverifiable: list[dict[str, str]] = list(state["unverifiable"])

    for note in skipped_a + skipped_n + skipped_r:
        unverifiable.append({"map": "?", "run_id": "?", "reason": "skipped-source", "detail": note})

    uploads = [r for r in to_copy if r["where"] in ("artifacts", "nquake", "repo-tricks")]
    server_copies = [r for r in to_copy if r["where"] == "server"]
    print(
        f"[backfill] plan: {len(server_copies)} server-side copies, "
        f"{len(uploads)} uploads, {len(state['already'])} already archived, "
        f"{len(unverifiable)} unverifiable, {len(state['ssd_only'])} ssd-only"
    )

    copied_ok: list[tuple[str, str]] = []
    if apply and to_copy:
        plan: list[tuple[str, str, str, str]] = [
            ("run", r["run_id"], r["map"], r["sha256"]) for r in server_copies
        ]
        if uploads:
            print(f"[backfill] staging {len(uploads)} local demos to {host}:{REMOTE_STAGING_DIR} ...")
            _stage_uploads(host, uploads)
            plan += [("staging", r["run_id"], r["map"], r["sha256"]) for r in uploads]
        print(f"[backfill] installing {len(plan)} demos on the SSD ...")
        results = _install_plan(host, plan)
        if uploads:
            _cleanup_staging(host)
        for r in to_copy:
            key = (r["map"], r["run_id"])
            status = results.get(key, {}).get("status", "no-result")
            if status in ARCHIVE_OK_STATUSES:
                copied_ok.append(key)
            else:
                unverifiable.append(
                    {
                        "map": r["map"],
                        "run_id": r["run_id"],
                        "reason": f"install-{status}",
                        "detail": f"source={r['where']}",
                    }
                )
        # Belt and braces: re-read the SSD and confirm every install landed
        # with the exact source hash.
        print("[backfill] re-verifying SSD state ...")
        ssd_after = {(r["map"], r["run_id"]): r["sha256"] for r in collect_ssd_inventory(host)}
        for r in to_copy:
            key = (r["map"], r["run_id"])
            if key in copied_ok and ssd_after.get(key) != r["sha256"]:
                copied_ok.remove(key)
                unverifiable.append(
                    {"map": r["map"], "run_id": r["run_id"], "reason": "post-verify-failed", "detail": ""}
                )

    table = _count_table(state, copied_ok, unverifiable, apply)
    print()
    print(table)
    if unverifiable:
        print("\nUnverifiable detail:")
        for item in unverifiable:
            print(f"  - {item['map']}/{item['run_id']}: {item['reason']} {item['detail']}")

    report_dir = REPO_ROOT / "artifacts"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"demo-archive-backfill-{stamp}.md"
    detail_lines = [
        f"# Demo archive backfill {stamp}",
        "",
        f"- Host: `{host}`  Apply: `{apply}`",
        f"- Sources: server={len(server_rows)} artifacts={len(artifact_rows)} "
        f"nquake_dm3={len(nquake_rows)} repo_tricks={len(repo_rows)}",
        f"- SSD files before: {len(ssd_rows)}",
        "",
        table,
        "",
    ]
    if unverifiable:
        detail_lines.append("## Unverifiable")
        detail_lines.append("")
        for item in unverifiable:
            detail_lines.append(f"- `{item['map']}/{item['run_id']}`: {item['reason']} {item['detail']}")
    report_path.write_text("\n".join(detail_lines) + "\n", encoding="utf-8")
    print(f"\nreport={report_path}")
    return 0 if not unverifiable else 2


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Archive lab MVDs to the servexeri demo SSD (#64)."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="SSH host. Defaults to servexeri.")
    parser.add_argument(
        "--backfill", action="store_true", help="Reconcile all known sources against the SSD."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="With --backfill: plan and count table only, no copies."
    )
    parser.add_argument("--run-id", default=None, help="Archive one server-side run dir (with --map).")
    parser.add_argument("--map", dest="map_name", default=None, help="Map for --run-id.")
    args = parser.parse_args(argv)

    if args.backfill:
        return backfill(args.host, apply=not args.dry_run)
    if args.run_id and args.map_name:
        result = archive_run_demo(args.host, args.run_id, args.map_name)
        return 0 if result.get("status") in ARCHIVE_OK_STATUSES else 1
    parser.error("nothing to do: pass --backfill, or --run-id RID --map MAP")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
