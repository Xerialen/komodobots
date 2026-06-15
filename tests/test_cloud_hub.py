"""Smoke tests for cloud/cloud_hub.py — no server or box needed (CI-safe, stdlib only)."""
import importlib.util
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("cloud_hub", ROOT / "cloud" / "cloud_hub.py")
cloud_hub = importlib.util.module_from_spec(_SPEC)
# cloud_hub reads sys.argv at import for the optional bind/port; neutralize it for tests.
_saved_argv = sys.argv
sys.argv = ["cloud_hub"]
try:
    _SPEC.loader.exec_module(cloud_hub)
finally:
    sys.argv = _saved_argv


class SafeChildTests(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        # KTX auto-demo name with [] — the exact case the hub previously 404'd on.
        open(os.path.join(self.base, "4on4_leap[dm3]20260615-2036.mvd"), "w").close()

    def test_accepts_url_encoded_bracket_demo_name(self):
        p = cloud_hub._safe_child(self.base, "4on4_leap%5Bdm3%5D20260615-2036.mvd")
        self.assertIsNotNone(p)
        self.assertTrue(p.endswith("4on4_leap[dm3]20260615-2036.mvd"))

    def test_accepts_plain_name(self):
        open(os.path.join(self.base, "a.mvd"), "w").close()
        self.assertIsNotNone(cloud_hub._safe_child(self.base, "a.mvd"))

    def test_rejects_traversal_and_empty(self):
        self.assertIsNone(cloud_hub._safe_child(self.base, "../etc/passwd"))
        self.assertIsNone(cloud_hub._safe_child(self.base, "%2e%2e%2fpasswd"))  # ../passwd
        self.assertIsNone(cloud_hub._safe_child(self.base, "sub/dir.mvd"))
        self.assertIsNone(cloud_hub._safe_child(self.base, ""))


class ListingTests(unittest.TestCase):
    def test_online_demos_missing_dir_is_empty(self):
        cloud_hub.ONLINE_DEMOS_DIR = "/no/such/dir"
        self.assertEqual(cloud_hub.online_demos_json(), [])

    def test_attempts_parses_route_and_runid(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "dm3"))
        open(os.path.join(d, "dm3", "myroute__RUN123.mvd"), "w").close()
        cloud_hub.ATTEMPTS_DIR = d
        items = cloud_hub.attempts_json()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["map"], "dm3")
        self.assertEqual(items[0]["route"], "myroute")
        self.assertEqual(items[0]["runid"], "RUN123")
        self.assertTrue(items[0]["url"].startswith("/demos/attempts/dm3/"))

    def test_guess_map(self):
        self.assertEqual(cloud_hub._guess_map("4on4_leap[dm3]x.mvd"), "dm3")
        self.assertEqual(cloud_hub._guess_map("foo_dm2_bar.mvd"), "dm2")
        self.assertEqual(cloud_hub._guess_map("frobodm2_run.mvd"), "frobodm2")


if __name__ == "__main__":
    unittest.main()
