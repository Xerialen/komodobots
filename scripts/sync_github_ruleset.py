"""Sync the repository's GitHub branch ruleset from a committed manifest."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

DEFAULT_MANIFEST = Path(".github/rulesets/prod-dev-branch-protection.json")
DEFAULT_REPO = "Xerialen/komodobots"


class GhError(RuntimeError):
    """Raised when a gh command fails."""


Runner = Callable[[list[str], str | None], str]


def gh_runner(args: list[str], stdin: str | None = None) -> str:
    completed = subprocess.run(
        ["gh", *args],
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise GhError(f"gh {' '.join(args)} failed: {detail}")
    return completed.stdout


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"name", "target", "enforcement", "conditions", "rules"}
    missing = sorted(required - data.keys())
    if missing:
        raise ValueError(f"{path} is missing required field(s): {', '.join(missing)}")
    if data["target"] != "branch":
        raise ValueError(f"{path} target must be 'branch'")
    return normalize_ruleset(data)


def normalize_ruleset(data: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "name": data["name"],
        "target": data["target"],
        "enforcement": data["enforcement"],
        "bypass_actors": data.get("bypass_actors", []),
        "conditions": data["conditions"],
        "rules": data["rules"],
    }
    normalized["rules"] = sorted(
        (normalize_rule(rule) for rule in normalized["rules"]),
        key=lambda rule: rule["type"],
    )
    return normalized


def normalize_rule(rule: dict[str, Any]) -> dict[str, Any]:
    normalized = {"type": rule["type"]}
    if "parameters" in rule:
        normalized["parameters"] = rule["parameters"]
    return normalized


def find_ruleset(rulesets: Iterable[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for ruleset in rulesets:
        if ruleset.get("name") == name:
            return ruleset
    return None


def get_rulesets(repo: str, runner: Runner) -> list[dict[str, Any]]:
    payload = runner(["api", f"repos/{repo}/rulesets"], None)
    if not payload.strip():
        return []
    data = json.loads(payload)
    if isinstance(data, dict):
        return data.get("rulesets", [])
    return data


def get_ruleset(repo: str, ruleset_id: int, runner: Runner) -> dict[str, Any]:
    payload = runner(["api", f"repos/{repo}/rulesets/{ruleset_id}"], None)
    return normalize_ruleset(json.loads(payload))


def repo_delete_branch_on_merge(repo: str, runner: Runner) -> bool:
    payload = runner(
        [
            "repo",
            "view",
            repo,
            "--json",
            "deleteBranchOnMerge",
            "--jq",
            ".deleteBranchOnMerge",
        ],
        None,
    )
    return payload.strip().lower() == "true"


def diff_rulesets(expected: dict[str, Any], actual: dict[str, Any] | None) -> list[str]:
    if actual is None:
        return [f"missing ruleset {expected['name']!r}"]
    diffs: list[str] = []
    for key in ("target", "enforcement", "bypass_actors", "conditions", "rules"):
        if actual.get(key) != expected.get(key):
            diffs.append(f"{key} differs")
    return diffs


def check(repo: str, manifest: dict[str, Any], runner: Runner) -> list[str]:
    ruleset_stub = find_ruleset(get_rulesets(repo, runner), manifest["name"])
    actual = None
    if ruleset_stub is not None:
        actual = get_ruleset(repo, int(ruleset_stub["id"]), runner)

    diffs = diff_rulesets(manifest, actual)
    if not repo_delete_branch_on_merge(repo, runner):
        diffs.append("repository deleteBranchOnMerge is false")
    return diffs


def apply(repo: str, manifest: dict[str, Any], runner: Runner) -> str:
    ruleset_stub = find_ruleset(get_rulesets(repo, runner), manifest["name"])
    body = json.dumps(manifest, separators=(",", ":"))

    if ruleset_stub is None:
        payload = runner(
            [
                "api",
                "--method",
                "POST",
                f"repos/{repo}/rulesets",
                "--input",
                "-",
            ],
            body,
        )
        result = json.loads(payload)
        action = f"created ruleset {manifest['name']} ({result.get('id')})"
    else:
        ruleset_id = int(ruleset_stub["id"])
        runner(
            [
                "api",
                "--method",
                "PUT",
                f"repos/{repo}/rulesets/{ruleset_id}",
                "--input",
                "-",
            ],
            body,
        )
        action = f"updated ruleset {manifest['name']} ({ruleset_id})"

    runner(["repo", "edit", repo, "--delete-branch-on-merge"], None)
    return action + "; ensured deleteBranchOnMerge=true"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="verify live GitHub settings")
    mode.add_argument("--apply", action="store_true", help="create/update live GitHub settings")
    return parser


def main(argv: list[str] | None = None, runner: Runner = gh_runner) -> int:
    args = build_parser().parse_args(argv)
    manifest = load_manifest(args.manifest)

    try:
        if args.check:
            diffs = check(args.repo, manifest, runner)
            if diffs:
                for diff in diffs:
                    print(f"DIFF: {diff}")
                return 1
            print("GitHub branch ruleset matches manifest.")
            return 0

        print(apply(args.repo, manifest, runner))
        return 0
    except GhError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
