from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MERGE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "review-gate-merge.yml"
RESET_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "review-gate-reset.yml"


def _workflow_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class ReviewGateMergeWorkflowTests(unittest.TestCase):
    def test_draft_promotion_is_reset_only_not_merge_trigger(self) -> None:
        merge = _workflow_text(MERGE_WORKFLOW)
        reset = _workflow_text(RESET_WORKFLOW)

        self.assertIn("types: [labeled, reopened]", merge)
        self.assertNotRegex(merge, r"types:\s*\[[^\]]*ready_for_review")
        self.assertIn("types: [opened, reopened, ready_for_review, synchronize]", reset)

    def test_merge_requires_ready_label_newer_than_draft_promotion(self) -> None:
        merge = _workflow_text(MERGE_WORKFLOW)

        self.assertIn('"repos/$REPO/issues/$PR/timeline"', merge)
        self.assertIn('select(.event == "ready_for_review")', merge)
        self.assertIn('select((.label.name // "") == "gate: ready")', merge)
        self.assertIn("label_after_ready_for_review", merge)
        self.assertIn("'gate: ready' label is not newer than latest ready_for_review", merge)

    def test_merge_requires_ready_verdict_newer_than_draft_promotion(self) -> None:
        merge = _workflow_text(MERGE_WORKFLOW)

        self.assertIn("--arg cutoff \"$latest_ready_for_review_at\"", merge)
        self.assertIn("fromdateiso8601", merge)
        self.assertIn(
            'select($cutoff == "" or ((.created_at | fromdateiso8601) > ($cutoff | fromdateiso8601)))',
            merge,
        )


if __name__ == "__main__":
    unittest.main()
