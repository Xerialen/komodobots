import json
import tempfile
import unittest
from pathlib import Path

from scripts import sync_github_ruleset


def write_manifest(data):
    temp = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8")
    with temp:
        json.dump(data, temp)
    return Path(temp.name)


class FakeGh:
    def __init__(self, rulesets=None, detail=None, delete_branch_on_merge=True):
        self.rulesets = rulesets or []
        self.detail = detail
        self.delete_branch_on_merge = delete_branch_on_merge
        self.calls = []

    def __call__(self, args, stdin=None):
        self.calls.append((args, stdin))
        command = " ".join(args)
        if args[:2] == ["api", "repos/Xerialen/komodobots/rulesets"]:
            return json.dumps(self.rulesets)
        if args[:2] == ["api", "repos/Xerialen/komodobots/rulesets/42"]:
            return json.dumps(self.detail)
        if args[:3] == ["repo", "view", "Xerialen/komodobots"]:
            return "true\n" if self.delete_branch_on_merge else "false\n"
        if "--method" in args and "POST" in args:
            return json.dumps({"id": 99})
        if "--method" in args and "PUT" in args:
            return json.dumps({"id": 42})
        if args[:3] == ["repo", "edit", "Xerialen/komodobots"]:
            self.delete_branch_on_merge = True
            return ""
        raise AssertionError(f"unexpected gh call: {command}")


class SyncGitHubRulesetTest(unittest.TestCase):
    def setUp(self):
        self.manifest = {
            "name": "prod-dev-branch-protection",
            "target": "branch",
            "enforcement": "active",
            "bypass_actors": [],
            "conditions": {
                "ref_name": {
                    "include": ["refs/heads/main", "refs/heads/dev"],
                    "exclude": [],
                }
            },
            "rules": [
                {"type": "deletion"},
                {"type": "non_fast_forward"},
            ],
        }

    def test_load_manifest_requires_branch_target(self):
        path = write_manifest({**self.manifest, "target": "tag"})
        self.addCleanup(path.unlink)

        with self.assertRaisesRegex(ValueError, "target must be 'branch'"):
            sync_github_ruleset.load_manifest(path)

    def test_normalize_ruleset_sorts_rules_for_stable_compare(self):
        manifest = {
            **self.manifest,
            "rules": [
                {"type": "non_fast_forward"},
                {"type": "deletion"},
            ],
        }

        normalized = sync_github_ruleset.normalize_ruleset(manifest)

        self.assertEqual([rule["type"] for rule in normalized["rules"]], ["deletion", "non_fast_forward"])

    def test_check_reports_missing_ruleset_and_repo_auto_delete_drift(self):
        fake = FakeGh(delete_branch_on_merge=False)

        diffs = sync_github_ruleset.check("Xerialen/komodobots", self.manifest, fake)

        self.assertEqual(
            diffs,
            [
                "missing ruleset 'prod-dev-branch-protection'",
                "repository deleteBranchOnMerge is false",
            ],
        )

    def test_check_passes_when_live_ruleset_matches_manifest(self):
        fake = FakeGh(
            rulesets=[{"id": 42, "name": "prod-dev-branch-protection"}],
            detail=self.manifest,
        )

        diffs = sync_github_ruleset.check("Xerialen/komodobots", self.manifest, fake)

        self.assertEqual(diffs, [])

    def test_apply_creates_ruleset_and_enables_auto_delete(self):
        fake = FakeGh()

        result = sync_github_ruleset.apply("Xerialen/komodobots", self.manifest, fake)

        self.assertIn("created ruleset prod-dev-branch-protection", result)
        self.assertIn(
            ["repo", "edit", "Xerialen/komodobots", "--delete-branch-on-merge"],
            [call[0] for call in fake.calls],
        )

    def test_apply_updates_existing_ruleset(self):
        fake = FakeGh(rulesets=[{"id": 42, "name": "prod-dev-branch-protection"}])

        result = sync_github_ruleset.apply("Xerialen/komodobots", self.manifest, fake)

        self.assertIn("updated ruleset prod-dev-branch-protection (42)", result)
        api_calls = [call[0] for call in fake.calls if "--method" in call[0]]
        self.assertEqual(api_calls[0][api_calls[0].index("--method") + 1], "PUT")


if __name__ == "__main__":
    unittest.main()
