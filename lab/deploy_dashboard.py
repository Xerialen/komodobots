#!/usr/bin/env python3
"""LD-A2 (#85): deploy the lab dashboard to the servexeri web tier.

The deployed page must keep its URL (http://192.168.86.33:8095/botlab/), and the
web root (`~/local-hub/web/`) also serves sibling pages (/qtv/, /demos/, /games/,
...) whose files must NEVER be touched by this script. Safety is structural:
every rsync destination is validated against a closed allowlist of exactly two
directories, and sibling entry-HTML hashes are captured before and after every
remote sync and compared in-process (non-zero exit on any drift).

Modes (exactly one):

  --stage          (default) Build lab/dashboard, ship dist/ to
                   servexeri:~/local-hub/web/botlab-staged/ . ADDITIVE: the
                   staged dir is new; nothing currently served is modified.
                   Re-runnable; the second run is a content no-op (idempotency
                   is checked via rsync --checksum itemized output).
                   Note: because the app is built with base /botlab/, the
                   staged copy is not fully browsable until cutover - that is
                   deliberate (the staged artifact is byte-identical to what
                   cutover promotes).

  --cutover        Promote botlab-staged/ -> botlab/ on servexeri (the live
                   URL). Takes a tar.gz backup of the current botlab/ into
                   ~/local-hub/web-backups/ first (additive), then
                   rsync --delete within botlab/ only. THIS IS THE LIVE
                   SAME-URL CUTOVER: requires --confirm-live and runs only on
                   owner approval.

  --audit-assets   Read-only report: for each legacy chunk in the shared
                   ~/local-hub/web/assets/, list which pages outside
                   botlab*/ reference it. Chunks referenced by nothing outside
                   the old botlab are removal candidates AFTER cutover; this
                   mode never deletes anything.

Transport: the local dist/ is tarred in-memory and extracted into a remote
mktemp dir over a single ssh pipe, then rsync runs *on servexeri* from that
temp dir into the validated target (rsync is not required on the local
machine; servexeri has /usr/bin/rsync).

Stdlib only. Pure command-builders/parsers below are unit-tested by
tests/test_deploy_dashboard.py.
"""

from __future__ import annotations

import logging
import argparse
import io
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path


LOGGER = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = REPO_ROOT / "lab" / "dashboard"
DIST_DIR = DASHBOARD_DIR / "dist"

WEB_ROOT = "~/local-hub/web"
STAGE_DIR = f"{WEB_ROOT}/botlab-staged"
LIVE_DIR = f"{WEB_ROOT}/botlab"
BACKUP_DIR = "~/local-hub/web-backups"

# The ONLY directories this script is ever allowed to rsync --delete into.
ALLOWED_RSYNC_DESTS = (STAGE_DIR, LIVE_DIR)

DEFAULT_HOST = "servexeri"


def configure_logging() -> None:
    level_name = os.environ.get("KOMODOBOTS_LOG_LEVEL", "WARNING").upper()
    level = getattr(logging, level_name, logging.WARNING)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------


def validate_remote_target(path: str) -> str:
    """Return `path` with exactly one trailing slash iff it is an allowed
    rsync destination; raise ValueError otherwise. This is the structural
    guard that makes touching siblings impossible by construction."""
    normalized = path.rstrip("/")
    if normalized not in ALLOWED_RSYNC_DESTS:
        raise ValueError(
            f"Refusing rsync destination {path!r}: not in allowlist "
            f"{ALLOWED_RSYNC_DESTS}"
        )
    return normalized + "/"


def rsync_cmd(src_dir: str, dst_dir: str) -> str:
    """Remote-side rsync: archive, itemized, checksum quick-check (so an
    unchanged rebuild with fresh mtimes still reads as a content no-op),
    --delete scoped to the validated destination only."""
    dst = validate_remote_target(dst_dir)
    src = src_dir.rstrip("/") + "/"
    return f"rsync -aic --delete {src} {dst}"


def stage_cmds(tmp_dir: str) -> list[str]:
    """Remote commands for --stage: sync the extracted temp dir into the
    staged target, then drop the temp dir."""
    return [
        rsync_cmd(tmp_dir, STAGE_DIR),
        f"rm -rf {tmp_dir}",
    ]


def cutover_cmds(timestamp: str) -> list[str]:
    """Remote commands for --cutover. Backup of the live dir is taken BEFORE
    the promote; the promote syncs the staged dir into the live dir."""
    backup = (
        f"mkdir -p {BACKUP_DIR} && "
        f"tar -czf {BACKUP_DIR}/botlab-pre-cutover-{timestamp}.tar.gz "
        f"-C {WEB_ROOT} botlab"
    )
    return [
        f"test -f {STAGE_DIR}/index.html",
        backup,
        rsync_cmd(STAGE_DIR, LIVE_DIR),
    ]


def sibling_hash_cmd() -> str:
    """Hash every entry HTML in the web root except botlab*/ - the
    do-not-overwrite-siblings evidence. Depth 2 covers each page dir's
    index.html plus the root index.html."""
    return (
        f"cd {WEB_ROOT} && find . -maxdepth 2 -name '*.html' "
        "-not -path './botlab/*' -not -path './botlab-staged/*' "
        "| sort | xargs sha256sum"
    )


def audit_assets_cmd() -> str:
    """Read-only: for each shared legacy chunk in web/assets/, grep the rest
    of the web root (excluding assets/ itself and botlab*/) for references."""
    return (
        f"cd {WEB_ROOT} && for f in assets/*; do "
        'n=$(basename "$f"); '
        "refs=$(grep -rlI --exclude-dir=assets --exclude-dir=botlab "
        '--exclude-dir=botlab-staged -- "$n" . | sort | tr "\\n" " "); '
        'if [ -z "$refs" ]; then echo "CANDIDATE (no reference outside old botlab): $n"; '
        'else echo "KEEP $n <- $refs"; fi; done'
    )


def staged_file_list_cmd() -> str:
    return f"find {STAGE_DIR} -type f | sort"


def parse_rsync_itemized(output: str) -> list[str]:
    """Return the SUBSTANTIVE itemized-changes lines: transfers, creations,
    and deletions. Attribute-only lines (leading '.') such as directory
    mtime touches are not content changes and are excluded."""
    changes = []
    for line in output.splitlines():
        line = line.rstrip()
        if not line:
            continue
        if line.startswith("*deleting"):
            changes.append(line)
        elif line[0] in (">", "<", "c", "h"):
            changes.append(line)
        # leading "." = attribute-only; anything else (rsync chatter) ignored
    return changes


def is_noop(output: str) -> bool:
    return not parse_rsync_itemized(output)


def parse_hash_lines(output: str) -> dict[str, str]:
    """sha256sum output -> {path: hash}."""
    hashes: dict[str, str] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, path = parts
        hashes[path.lstrip("*")] = digest
    return hashes


def diff_hashes(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Human-readable drift report; empty list == siblings untouched."""
    problems = []
    for path in sorted(set(before) | set(after)):
        if path not in after:
            problems.append(f"MISSING after sync: {path}")
        elif path not in before:
            problems.append(f"NEW file appeared: {path}")
        elif before[path] != after[path]:
            problems.append(
                f"CHANGED: {path} {before[path][:12]}... -> {after[path][:12]}..."
            )
    return problems


def tar_dist_bytes(dist_dir: Path) -> bytes:
    """Gzipped tar of dist_dir contents with arcnames relative to dist_dir
    (no leading directory component, no absolute paths)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in sorted(dist_dir.rglob("*")):
            tar.add(
                path,
                arcname=path.relative_to(dist_dir).as_posix(),
                recursive=False,  # rglob already yields every child
            )
    return buf.getvalue()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--stage", action="store_true", help="additive staging deploy (default)")
    mode.add_argument("--cutover", action="store_true", help="promote staged -> live URL (owner approval)")
    mode.add_argument("--audit-assets", action="store_true", help="read-only legacy shared-assets reference report")
    parser.add_argument("--confirm-live", action="store_true", help="required with --cutover")
    parser.add_argument("--host", default=DEFAULT_HOST, help="SSH host (default: servexeri)")
    parser.add_argument("--skip-build", action="store_true", help="reuse the existing dist/ instead of rebuilding")
    args = parser.parse_args(argv)
    if args.cutover and not args.confirm_live:
        parser.error("--cutover modifies the live URL; it requires --confirm-live (owner approval)")
    if not (args.cutover or args.audit_assets):
        args.stage = True
    return args


# ---------------------------------------------------------------------------
# Side-effecting runtime
# ---------------------------------------------------------------------------


def require_tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise RuntimeError(f"Required tool not found on PATH: {name}")
    return found


def ssh_run(host: str, command: str, *, input_bytes: bytes | None = None, check: bool = True) -> str:
    proc = subprocess.run(
        ["ssh", host, command],
        input=input_bytes,
        capture_output=True,
    )
    out = proc.stdout.decode("utf-8", errors="replace")
    err = proc.stderr.decode("utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise RuntimeError(f"ssh {host} {command!r} failed ({proc.returncode}):\n{err}")
    return out


def build_dashboard() -> None:
    npm = require_tool("npm")
    if not (DASHBOARD_DIR / "node_modules").is_dir():
        print("== npm ci (node_modules missing) ==")
        subprocess.run([npm, "ci"], cwd=str(DASHBOARD_DIR), check=True)
    print("== npm run build ==")
    subprocess.run([npm, "run", "build"], cwd=str(DASHBOARD_DIR), check=True)
    if not (DIST_DIR / "index.html").is_file():
        raise RuntimeError(f"Build produced no {DIST_DIR / 'index.html'}")


def capture_sibling_hashes(host: str) -> dict[str, str]:
    return parse_hash_lines(ssh_run(host, sibling_hash_cmd()))


def assert_siblings_untouched(before: dict[str, str], after: dict[str, str]) -> None:
    problems = diff_hashes(before, after)
    if problems:
        print("SIBLING INTEGRITY FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        raise SystemExit(2)
    print(f"Sibling integrity: PASS ({len(before)} entry-HTML hashes unchanged)")


def do_stage(host: str, skip_build: bool) -> None:
    if not skip_build:
        build_dashboard()
    elif not (DIST_DIR / "index.html").is_file():
        raise RuntimeError("--skip-build but no existing dist/index.html")

    before = capture_sibling_hashes(host)

    tmp_dir = ssh_run(host, "mktemp -d /tmp/botlab-deploy.XXXXXX").strip()
    print(f"== shipping dist/ to {host}:{tmp_dir} ==")
    ssh_run(host, f"tar -xzf - -C {tmp_dir}", input_bytes=tar_dist_bytes(DIST_DIR))

    sync_cmd, cleanup_cmd = stage_cmds(tmp_dir)
    print(f"== {sync_cmd} ==")
    itemized = ssh_run(host, sync_cmd)
    ssh_run(host, cleanup_cmd)

    changes = parse_rsync_itemized(itemized)
    if changes:
        print(f"rsync itemized changes ({len(changes)}):")
        for line in changes:
            print(f"  {line}")
    else:
        print("rsync itemized changes: NONE (content no-op - idempotent re-run)")

    assert_siblings_untouched(before, capture_sibling_hashes(host))

    print("== staged file list ==")
    print(ssh_run(host, staged_file_list_cmd()).rstrip())
    print(f"\nStaged (ADDITIVE) at {host}:{STAGE_DIR}. The live URL is untouched;")
    print("promote with --cutover --confirm-live on owner approval.")


def do_cutover(host: str) -> None:
    print("!! LIVE CUTOVER: replacing the content behind :8095/botlab/ !!")
    before = capture_sibling_hashes(host)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for cmd in cutover_cmds(timestamp):
        print(f"== {cmd} ==")
        out = ssh_run(host, cmd)
        if out.strip():
            print(out.rstrip())
    assert_siblings_untouched(before, capture_sibling_hashes(host))
    print("Cutover complete. Validate http://192.168.86.33:8095/botlab/ in a browser")
    print(f"(rollback: extract {BACKUP_DIR}/botlab-pre-cutover-{timestamp}.tar.gz).")


def do_audit(host: str) -> None:
    print("== legacy shared-assets reference audit (read-only) ==")
    print(ssh_run(host, audit_assets_cmd()).rstrip())
    print("\nNothing was deleted. CANDIDATE lines are safe to remove only AFTER")
    print("cutover, once the old botlab entry HTML no longer references them.")


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    configure_logging()
    require_tool("ssh")
    mode = "cutover" if args.cutover else "audit-assets" if args.audit_assets else "stage"
    LOGGER.info("starting dashboard deploy mode=%s host=%s", mode, args.host)
    if args.cutover:
        do_cutover(args.host)
    elif args.audit_assets:
        do_audit(args.host)
    else:
        do_stage(args.host, args.skip_build)
    LOGGER.info("completed dashboard deploy mode=%s host=%s", mode, args.host)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
