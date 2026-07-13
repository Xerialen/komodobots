#!/usr/bin/env python3
"""Mirror the Dragonbot goals & metrics feed onto the central dashboard.

Issue #483 (companion to the dragonbot repo's own feed ticket, PR #56 on
Xerialen/dragonbot main): fetches the committed
``artifacts/hub/goals-metrics.json`` (schema ``dragonbot.hub_feed.v1``) from
Xerialen/dragonbot main over the GitHub REST contents API and republishes it
at a same-origin static path the dashboard polls
(``src/dragonbotFeed.ts``'s ``useDragonbotFeed``).

Same pattern as ``version_history_build.py``'s ``_fetch_merged_prs_api``: a
plain authenticated REST call, no ``gh`` CLI dependency required (this repo's
convention prefers ``gh`` where available; this script targets a single-file
contents fetch instead of PR listing, so it always uses the REST API
directly — ``gh api repos/<repo>/contents/<path>`` would work too, but a
bare ``urllib`` call keeps the token-resolution logic in one place and
testable without invoking a subprocess).

Token resolution order (servexeri kb2hub-sync convention):
  1. ``$GITHUB_TOKEN`` env var (matches version_history_build.py).
  2. A ``github.com`` credential parsed from ``~/.git-credentials``
     (``git credential-store`` format: ``https://<user>:<token>@github.com``).
     This is the PAT the owner already has provisioned on servexeri for git
     operations; issue #483 asks this script to reuse it rather than
     provisioning a second token.

Fail-closed (issue #483 acceptance criteria): every side-effecting step
(token resolution, HTTP fetch, JSON parse, schema/shape validation) happens
BEFORE the output file is touched. Any failure raises and ``main`` exits
non-zero without writing anything — the previously-published file (the
dashboard's "last-good snapshot") is left completely untouched, and the
dashboard renders it with a stale banner (client-side logic in
dragonbotFeed.ts / DragonbotPanel.tsx). This script never fabricates or
partially-writes a feed.

The output additionally carries a ``fetchedUtc`` timestamp — NOT part of the
upstream ``dragonbot.hub_feed.v1`` schema, which has no generation timestamp
of its own (it is a committed artifact). This lets the dashboard flag a
build-side-stale snapshot (this script's own GitHub fetch has been failing,
even though the static file fetch from the dashboard succeeds) independent of
an outright same-origin fetch failure.

Stdlib only. Pure helpers are unit-tested by tests/test_dragonbot_hub_feed_build.py.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LOGGER = logging.getLogger(__name__)

SCHEMA = "dragonbot.hub_feed.v1"
DEFAULT_REPO = "Xerialen/dragonbot"
DEFAULT_PATH = "artifacts/hub/goals-metrics.json"
DEFAULT_REF = "main"
DEFAULT_GIT_CREDENTIALS = Path.home() / ".git-credentials"


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------


def read_token_from_git_credentials(text: str, host: str = "github.com") -> str | None:
    """Parse a ``git credential-store`` file's contents for ``host``'s PAT.

    Lines look like ``https://<user>:<token>@github.com``; returns the first
    matching token, or None if the host is not present. Malformed lines are
    skipped, not fatal.
    """
    pattern = re.compile(r"^https?://[^:/@]*:([^@]+)@" + re.escape(host) + r"(?:/|$)")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = pattern.match(line)
        if m:
            return m.group(1)
    return None


def resolve_token(env: dict[str, str], git_credentials_path: Path) -> str:
    """Prefer $GITHUB_TOKEN, fall back to ~/.git-credentials, else raise."""
    env_token = (env.get("GITHUB_TOKEN") or "").strip()
    if env_token:
        return env_token
    if git_credentials_path.is_file():
        token = read_token_from_git_credentials(
            git_credentials_path.read_text(encoding="utf-8", errors="replace")
        )
        if token:
            return token
    raise RuntimeError(
        "no GitHub token available: set $GITHUB_TOKEN or provision a "
        f"github.com credential in {git_credentials_path}"
    )


def contents_api_url(repo: str, path: str, ref: str) -> str:
    return f"https://api.github.com/repos/{repo}/contents/{path}?ref={ref}"


def decode_contents_response(payload: dict) -> str:
    """Extract + base64-decode the ``content`` field of a GitHub contents-API
    response. GitHub wraps base64 content with embedded newlines; join before
    decoding."""
    encoding = payload.get("encoding")
    if encoding != "base64":
        raise ValueError(f"unexpected contents-API encoding: {encoding!r}")
    raw = payload.get("content", "")
    return base64.b64decode("".join(raw.splitlines())).decode("utf-8")


def validate_feed(data: object) -> dict:
    """Raise ValueError if `data` is not a well-shaped dragonbot.hub_feed.v1
    document; otherwise return it (typed as dict for callers)."""
    if not isinstance(data, dict):
        raise ValueError(f"feed is not a JSON object (got {type(data).__name__})")
    if data.get("schema") != SCHEMA:
        raise ValueError(f"unexpected schema {data.get('schema')!r}, expected {SCHEMA!r}")
    if not isinstance(data.get("goals"), list):
        raise ValueError("feed.goals is missing or not a list")
    if not isinstance(data.get("batches"), list):
        raise ValueError("feed.batches is missing or not a list")
    return data


def build_output(feed: dict, fetched_utc: str) -> dict:
    """Wrap the validated upstream feed with build-side metadata. Additive
    only — every upstream field passes through unchanged; see module
    docstring for why `fetchedUtc` is not part of the schema proper."""
    return {**feed, "fetchedUtc": fetched_utc}


# ---------------------------------------------------------------------------
# Side-effecting runtime
# ---------------------------------------------------------------------------


def fetch_feed_json(repo: str, path: str, ref: str, token: str, timeout: int = 20) -> dict:
    url = contents_api_url(repo, path, ref)
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "dragonbot-hub-feed-build",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)
    text = decode_contents_response(payload)
    return json.loads(text)


def write_atomic(out_path: Path, doc: dict) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    tmp.replace(out_path)


def configure_logging() -> None:
    level_name = os.environ.get("KOMODOBOTS_LOG_LEVEL", "WARNING").upper()
    level = getattr(logging, level_name, logging.WARNING)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--path", default=DEFAULT_PATH, help="path within the repo to the feed JSON")
    ap.add_argument("--ref", default=DEFAULT_REF)
    ap.add_argument("--git-credentials", type=Path, default=DEFAULT_GIT_CREDENTIALS)
    ap.add_argument("--out", required=True, type=Path)
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    configure_logging()
    try:
        token = resolve_token(dict(os.environ), args.git_credentials)
        raw = fetch_feed_json(args.repo, args.path, args.ref, token)
        feed = validate_feed(raw)
    except Exception as exc:  # noqa: BLE001 - fail-closed: log and exit non-zero
        # Deliberately never touch args.out below this point — the
        # previously-published snapshot (if any) stays exactly as it was.
        LOGGER.error("dragonbot hub feed fetch failed, leaving last-good snapshot in place: %s", exc)
        print(f"FAILED (fail-closed, {args.out} untouched): {exc}", file=sys.stderr)
        return 1

    fetched_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = build_output(feed, fetched_utc)
    write_atomic(args.out, doc)
    print(
        f"wrote {args.out}: {len(doc.get('goals', []))} goal(s), "
        f"{len(doc.get('batches', []))} batch(es), fetched {fetched_utc}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
