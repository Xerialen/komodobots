"""Contract tests for lab/server/dragonbot_hub_feed_build.py
(dragonbot.hub_feed.v1 mirror, issue #483).

Pure helpers only — no network, no real GitHub token. Stdlib only.
"""

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lab" / "server"))

import dragonbot_hub_feed_build as dhf  # noqa: E402


VALID_FEED = {
    "schema": "dragonbot.hub_feed.v1",
    "goals": [{"id": "G1", "title": "x", "metrics": {}}],
    "batches": [{"batchId": "b1", "date": "2026-07-13", "role": "control",
                 "title": "t", "kind": "control_batch", "arms": ["control"],
                 "validMatches": 8, "invalidMatches": 0, "metrics": {},
                 "analyzerSchemaVersion": None, "decision": None, "eval": None}],
}


class TokenFromGitCredentials(unittest.TestCase):
    def test_extracts_token_for_matching_host(self):
        text = "https://someuser:ghp_ABC123@github.com\n"
        self.assertEqual(dhf.read_token_from_git_credentials(text), "ghp_ABC123")

    def test_ignores_other_hosts(self):
        text = "https://user:tok@example.com\nhttps://user:realtok@github.com\n"
        self.assertEqual(dhf.read_token_from_git_credentials(text), "realtok")

    def test_returns_none_when_absent(self):
        text = "https://user:tok@example.com\n"
        self.assertIsNone(dhf.read_token_from_git_credentials(text))

    def test_ignores_blank_and_malformed_lines(self):
        text = "\n   \nnot-a-url\nhttps://user:tok@github.com\n"
        self.assertEqual(dhf.read_token_from_git_credentials(text), "tok")


class ResolveToken(unittest.TestCase):
    def test_env_var_wins_over_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            creds = Path(tmp) / ".git-credentials"
            creds.write_text("https://user:filetoken@github.com\n", encoding="utf-8")
            token = dhf.resolve_token({"GITHUB_TOKEN": "envtoken"}, creds)
            self.assertEqual(token, "envtoken")

    def test_falls_back_to_file_when_env_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            creds = Path(tmp) / ".git-credentials"
            creds.write_text("https://user:filetoken@github.com\n", encoding="utf-8")
            token = dhf.resolve_token({}, creds)
            self.assertEqual(token, "filetoken")

    def test_raises_when_neither_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope"
            with self.assertRaises(RuntimeError):
                dhf.resolve_token({}, missing)

    def test_blank_env_var_falls_through_to_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            creds = Path(tmp) / ".git-credentials"
            creds.write_text("https://user:filetoken@github.com\n", encoding="utf-8")
            token = dhf.resolve_token({"GITHUB_TOKEN": "   "}, creds)
            self.assertEqual(token, "filetoken")


class ContentsApi(unittest.TestCase):
    def test_url_shape(self):
        url = dhf.contents_api_url("Xerialen/dragonbot", "artifacts/hub/goals-metrics.json", "main")
        self.assertEqual(
            url,
            "https://api.github.com/repos/Xerialen/dragonbot/contents/artifacts/hub/goals-metrics.json?ref=main",
        )

    def test_decode_contents_response_roundtrips_json(self):
        body = json.dumps(VALID_FEED).encode("utf-8")
        # GitHub wraps base64 content across multiple lines.
        b64 = base64.b64encode(body).decode("ascii")
        wrapped = "\n".join(b64[i:i + 20] for i in range(0, len(b64), 20))
        payload = {"encoding": "base64", "content": wrapped}
        decoded = dhf.decode_contents_response(payload)
        self.assertEqual(json.loads(decoded), VALID_FEED)

    def test_decode_rejects_non_base64_encoding(self):
        with self.assertRaises(ValueError):
            dhf.decode_contents_response({"encoding": "utf-8", "content": "{}"})


class ValidateFeed(unittest.TestCase):
    def test_accepts_well_shaped_feed(self):
        self.assertEqual(dhf.validate_feed(VALID_FEED), VALID_FEED)

    def test_rejects_wrong_schema(self):
        bad = {**VALID_FEED, "schema": "something.else.v1"}
        with self.assertRaises(ValueError):
            dhf.validate_feed(bad)

    def test_rejects_missing_goals(self):
        bad = {k: v for k, v in VALID_FEED.items() if k != "goals"}
        with self.assertRaises(ValueError):
            dhf.validate_feed(bad)

    def test_rejects_non_list_batches(self):
        bad = {**VALID_FEED, "batches": "nope"}
        with self.assertRaises(ValueError):
            dhf.validate_feed(bad)

    def test_rejects_non_dict_payload(self):
        with self.assertRaises(ValueError):
            dhf.validate_feed(["not", "a", "dict"])


class BuildOutput(unittest.TestCase):
    def test_wraps_with_fetched_utc_without_mutating_upstream_fields(self):
        out = dhf.build_output(VALID_FEED, "2026-07-13T12:00:00Z")
        self.assertEqual(out["fetchedUtc"], "2026-07-13T12:00:00Z")
        for key, value in VALID_FEED.items():
            self.assertEqual(out[key], value)


class WriteAtomic(unittest.TestCase):
    def test_writes_and_replaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "nested" / "dragonbot-hub-feed.json"
            dhf.write_atomic(out, VALID_FEED)
            self.assertTrue(out.is_file())
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), VALID_FEED)
            # no leftover .tmp file
            self.assertFalse((out.with_suffix(out.suffix + ".tmp")).exists())

    def test_second_write_overwrites_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dragonbot-hub-feed.json"
            dhf.write_atomic(out, VALID_FEED)
            second = {**VALID_FEED, "goals": []}
            dhf.write_atomic(out, second)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["goals"], [])


class MainFailClosed(unittest.TestCase):
    def test_main_leaves_out_untouched_when_token_resolution_fails(self):
        # Force a blank $GITHUB_TOKEN regardless of the host/CI environment so
        # this test deterministically exercises the "no token available"
        # branch rather than attempting a real network call.
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            "os.environ", {"GITHUB_TOKEN": ""}
        ):
            out = Path(tmp) / "dragonbot-hub-feed.json"
            out.write_text(json.dumps(VALID_FEED), encoding="utf-8")
            missing_creds = Path(tmp) / "no-such-git-credentials"
            rc = dhf.main([
                "--out", str(out),
                "--git-credentials", str(missing_creds),
            ])
            self.assertEqual(rc, 1)
            # last-good snapshot must be untouched byte-for-byte
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), VALID_FEED)
            self.assertFalse((out.with_suffix(out.suffix + ".tmp")).exists())

    def test_main_leaves_out_untouched_when_fetch_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dragonbot-hub-feed.json"
            out.write_text(json.dumps(VALID_FEED), encoding="utf-8")
            with mock.patch.object(dhf, "resolve_token", return_value="tok"), mock.patch.object(
                dhf, "fetch_feed_json", side_effect=RuntimeError("network unreachable")
            ):
                rc = dhf.main(["--out", str(out)])
            self.assertEqual(rc, 1)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), VALID_FEED)
            self.assertFalse((out.with_suffix(out.suffix + ".tmp")).exists())


if __name__ == "__main__":
    unittest.main()
