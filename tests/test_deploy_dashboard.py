"""deploy_dashboard: the rsync allowlist is the sibling-safety guarantee.

LD-A2 (#85). The servexeri web root serves /qtv/, /demos/, /games/ etc. next
to /botlab/; the deploy script must be unable to point rsync --delete at
anything except the two whitelisted botlab dirs, the cutover must be
impossible without the explicit --confirm-live owner flag, and the itemized /
hash parsers that produce the PR evidence must classify correctly.
"""

import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lab"))

from deploy_dashboard import (  # noqa: E402
    LIVE_DIR,
    STAGE_DIR,
    WEB_ROOT,
    audit_assets_cmd,
    cutover_cmds,
    diff_hashes,
    is_noop,
    parse_args,
    parse_hash_lines,
    parse_rsync_itemized,
    rsync_cmd,
    sibling_hash_cmd,
    stage_cmds,
    tar_dist_bytes,
    validate_remote_target,
)


class TestTargetAllowlist(unittest.TestCase):
    def test_stage_and_live_dirs_are_allowed_with_trailing_slash(self):
        self.assertEqual(validate_remote_target(STAGE_DIR), STAGE_DIR + "/")
        self.assertEqual(validate_remote_target(LIVE_DIR), LIVE_DIR + "/")
        # already-slashed input normalizes to exactly one slash
        self.assertEqual(validate_remote_target(LIVE_DIR + "/"), LIVE_DIR + "/")

    def test_web_root_and_siblings_are_refused(self):
        for bad in (
            WEB_ROOT,
            WEB_ROOT + "/",
            f"{WEB_ROOT}/qtv",
            f"{WEB_ROOT}/demos",
            f"{WEB_ROOT}/assets",
            f"{WEB_ROOT}/botlab/..",
            f"{WEB_ROOT}/botlab-staged/../qtv",
            "~/",
            "/",
            "",
        ):
            with self.assertRaises(ValueError, msg=bad):
                validate_remote_target(bad)

    def test_rsync_cmd_scopes_delete_to_validated_dest(self):
        cmd = rsync_cmd("/tmp/botlab-deploy.abc123", STAGE_DIR)
        self.assertIn("--delete", cmd)
        self.assertIn("-aic", cmd)
        self.assertIn("/tmp/botlab-deploy.abc123/ ", cmd)  # src trailing slash
        self.assertTrue(cmd.endswith(STAGE_DIR + "/"))

    def test_rsync_cmd_refuses_unlisted_dest(self):
        with self.assertRaises(ValueError):
            rsync_cmd("/tmp/x", f"{WEB_ROOT}/qtv")


class TestModeCommands(unittest.TestCase):
    def test_stage_cmds_sync_then_cleanup_temp(self):
        sync, cleanup = stage_cmds("/tmp/botlab-deploy.zz")
        self.assertIn(STAGE_DIR + "/", sync)
        self.assertNotIn(LIVE_DIR + "/", sync)
        self.assertEqual(cleanup, "rm -rf /tmp/botlab-deploy.zz")

    def test_cutover_backs_up_before_promote(self):
        cmds = cutover_cmds("20260611T000000Z")
        self.assertEqual(len(cmds), 3)
        self.assertIn(f"{STAGE_DIR}/index.html", cmds[0])  # staged sanity gate
        self.assertIn("tar -czf", cmds[1])
        self.assertIn("botlab-pre-cutover-20260611T000000Z.tar.gz", cmds[1])
        # promote is staged -> live, and runs AFTER the backup
        self.assertIn(STAGE_DIR + "/", cmds[2])
        self.assertTrue(cmds[2].endswith(LIVE_DIR + "/"))

    def test_sibling_hash_cmd_excludes_both_botlab_dirs(self):
        cmd = sibling_hash_cmd()
        self.assertIn("./botlab/*", cmd)
        self.assertIn("./botlab-staged/*", cmd)
        self.assertIn("sha256sum", cmd)
        self.assertIn("-maxdepth 2", cmd)

    def test_audit_cmd_is_grep_only_and_excludes_botlab(self):
        cmd = audit_assets_cmd()
        self.assertIn("grep -rlI", cmd)
        self.assertIn("--exclude-dir=botlab", cmd)
        self.assertIn("--exclude-dir=botlab-staged", cmd)
        for destructive in ("rm ", "rsync", "mv ", "--delete"):
            self.assertNotIn(destructive, cmd)


class TestRsyncItemizedParsing(unittest.TestCase):
    def test_transfers_creations_deletions_are_substantive(self):
        out = (
            ">f+++++++++ index.html\n"
            "cd+++++++++ assets/\n"
            ">f.st...... assets/index-abc123.js\n"
            "*deleting   assets/stale-old.js\n"
        )
        self.assertEqual(len(parse_rsync_itemized(out)), 4)
        self.assertFalse(is_noop(out))

    def test_attribute_only_lines_are_a_noop(self):
        out = ".d..t...... ./\n.f..t...... index.html\n\n"
        self.assertEqual(parse_rsync_itemized(out), [])
        self.assertTrue(is_noop(out))

    def test_empty_output_is_a_noop(self):
        self.assertTrue(is_noop(""))


class TestSiblingHashEvidence(unittest.TestCase):
    BEFORE = "aa11  ./index.html\nbb22  ./qtv/index.html\n"

    def test_identical_hashes_pass(self):
        before = parse_hash_lines(self.BEFORE)
        self.assertEqual(before["./qtv/index.html"], "bb22")
        self.assertEqual(diff_hashes(before, parse_hash_lines(self.BEFORE)), [])

    def test_changed_missing_and_new_files_are_reported(self):
        before = parse_hash_lines(self.BEFORE)
        after = parse_hash_lines("aa11  ./index.html\ncc33  ./qtv/index.html\ndd44  ./demos/index.html\n")
        problems = diff_hashes(before, after)
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("CHANGED: ./qtv/index.html" in p for p in problems))
        self.assertTrue(any("NEW file appeared: ./demos/index.html" in p for p in problems))
        self.assertEqual(
            diff_hashes(before, parse_hash_lines("aa11  ./index.html\n")),
            ["MISSING after sync: ./qtv/index.html"],
        )


class TestTarPayload(unittest.TestCase):
    def test_arcnames_are_relative_with_no_leading_component(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp) / "dist"
            (dist / "assets").mkdir(parents=True)
            (dist / "index.html").write_text("<html/>", encoding="utf-8")
            (dist / "assets" / "app.js").write_text("js", encoding="utf-8")
            payload = tar_dist_bytes(dist)
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
            names = sorted(tar.getnames())
        self.assertEqual(names, ["assets", "assets/app.js", "index.html"])
        for name in names:
            self.assertFalse(name.startswith(("/", "..", "dist")))


class TestArgs(unittest.TestCase):
    def test_default_mode_is_stage(self):
        args = parse_args([])
        self.assertTrue(args.stage)
        self.assertFalse(args.cutover)
        self.assertFalse(args.audit_assets)
        self.assertEqual(args.host, "servexeri")

    def test_cutover_requires_confirm_live(self):
        with self.assertRaises(SystemExit):
            parse_args(["--cutover"])
        args = parse_args(["--cutover", "--confirm-live"])
        self.assertTrue(args.cutover)

    def test_modes_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            parse_args(["--stage", "--cutover", "--confirm-live"])

    def test_audit_and_skip_build_flags(self):
        args = parse_args(["--audit-assets"])
        self.assertTrue(args.audit_assets)
        self.assertFalse(args.stage)
        self.assertTrue(parse_args(["--skip-build"]).skip_build)


if __name__ == "__main__":
    unittest.main()
