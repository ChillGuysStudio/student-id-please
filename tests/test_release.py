"""Release selection, version validation, and annotated-tag behavior."""

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".github" / "scripts"))
import release


@contextmanager
def in_directory(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def release_pr(title="chore(v2.0.0): publish package", sha="main-sha"):
    return {
        "title": title, "number": 10, "merged_at": "2026-10-06T12:00:00Z",
        "merge_commit_sha": sha,
        "base": {"ref": "main", "repo": {"full_name": "team/project"}},
        "head": {"ref": "dev", "sha": "dev-sha", "repo": {"full_name": "team/project"}},
    }


class ReleaseTests(unittest.TestCase):
    def test_version_from_title(self):
        for title, tag in (
            ("chore(v2.0.0): publish package", "v2.0.0"),
            ("fix(v2.0.1): correct timeout handling", "v2.0.1"),
            ("chore(v0.0.0): publish documentation", "v0.0.0"),
        ):
            with self.subTest(title=title):
                self.assertEqual(release.version_from_title(title), tag)
        for title in ("chore(lab-2): release", "chore(v02.0.0): release", "chore(v2.0): release",
                      "chore(v2.0.0-SNAPSHOT): release", "chore(v2.0.0): release\nextra",
                      "chore(v2.0.0): release "):
            with self.subTest(title=title), self.assertRaises(ValueError):
                release.version_from_title(title)

    def test_selects_rebased_release_instead_of_task_or_old_pr(self):
        pr = release_pr()
        task = {**pr, "base": {"ref": "dev"}}
        old = {**pr, "merge_commit_sha": "old-sha"}
        self.assertEqual(release.release_pr([task, old, pr], "team/project", "main-sha"), pr)
        for prs in ([], [task, old], [pr, pr], [{**pr, "merged_at": None}],
                    [{**pr, "head": {"ref": "dev", "repo": None}}]):
            with self.subTest(prs=prs), self.assertRaises(ValueError):
                release.release_pr(prs, "team/project", "main-sha")

    def test_new_tag_has_empty_annotation_and_exact_source_sha(self):
        for tag in ("v2.0.0", "v2.0.1"):
            with self.subTest(tag=tag), \
                    patch.object(release, "validate_version", return_value=True), \
                    patch.object(release, "api", side_effect=[{"sha": "annotated-sha"}, {}]) as api:
                release.reserve_tag("team/project", tag, "rebased-sha")
            self.assertEqual(api.call_args_list[0].args, ("repos/team/project/git/tags", {
                "tag": tag, "message": "", "object": "rebased-sha", "type": "commit",
            }))
            self.assertEqual(api.call_args_list[1].args, ("repos/team/project/git/refs", {
                "ref": f"refs/tags/{tag}", "sha": "annotated-sha",
            }))

    def test_main_outputs_version_metadata_without_a_message(self):
        for tag in ("v2.0.0", "v2.0.1"):
            with self.subTest(tag=tag), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "output"
                env = {"GITHUB_REPOSITORY": "team/project", "GITHUB_REF": "refs/heads/main",
                       "GITHUB_SHA": "rebased-sha", "GITHUB_OUTPUT": str(output)}
                pr = release_pr(f"chore({tag}): publish package", "rebased-sha")
                with patch.dict(os.environ, env, clear=True), \
                        patch.object(release, "validate_version", return_value=True), \
                        patch.object(release, "api", side_effect=[[pr], {"sha": "annotated-sha"}, {}]):
                    release.main()
                self.assertEqual(output.read_text(), f"tag={tag}\nversion={tag[1:]}\n")

    def test_same_commit_retry_does_not_create_or_move_tag(self):
        with patch.object(release, "validate_version", return_value=False), \
                patch.object(release, "api") as api:
            release.reserve_tag("team/project", "v2.0.0", "rebased-sha")
        api.assert_not_called()


class ReleaseGitTests(unittest.TestCase):
    def test_version_ordering_collision_and_release_pr_reuse(self):
        with tempfile.TemporaryDirectory(prefix="release test ") as root:
            env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_AUTHOR_NAME="Release Test", GIT_AUTHOR_EMAIL="test@example.invalid",
                       GIT_COMMITTER_NAME="Release Test", GIT_COMMITTER_EMAIL="test@example.invalid")
            for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
                env.pop(key, None)
            with patch.dict(os.environ, env, clear=True), in_directory(root):
                def git(*args):
                    return subprocess.check_output(["git", *args], text=True).strip()
                git("init", "-q", "-b", "main")
                git("commit", "--allow-empty", "-qm", "chore: initial release")
                sha = git("rev-parse", "HEAD")
                self.assertTrue(release.validate_version("v2.0.0", sha))
                git("tag", "-a", "v2.0.0", "-m", "Lab 2 completion")
                git("tag", "-a", "v2.0.9", "-m", "Lab 2 hotfix")
                self.assertFalse(release.validate_version("v2.0.0", sha))
                self.assertTrue(release.validate_version("v2.0.10", sha))
                self.assertTrue(release.validate_version("v3.0.0", sha))
                for tag in ("v1.0.1", "v2.0.8"):
                    with self.subTest(tag=tag), self.assertRaises(ValueError):
                        release.validate_version(tag, sha)
                with self.assertRaises(ValueError):
                    release.validate_version("v2.0.0", "different-sha")
                pr = release_pr()
                pr["head"]["sha"] = sha
                with self.assertRaisesRegex(ValueError, "already exists"):
                    release.check_release_pr(pr, "team/project")
                pr["title"] = "fix(v2.0.10): release a hotfix"
                release.check_release_pr(pr, "team/project")


if __name__ == "__main__":
    unittest.main()
