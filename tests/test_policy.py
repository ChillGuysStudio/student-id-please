"""Policy unit tests and hook integration tests in disposable Git repositories."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_commits
import check_pr
import check_push


ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_NOSYSTEM="1",
           GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
# Do not let the parent repository's Git context leak into temporary repos.
for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
    ENV.pop(key, None)
ZERO = "0" * 40
BODY = """## Why?
Invalid requests currently reach the database.
## Changes
Add input validation before saving records.
## How to Test?
Run python3 -m unittest discover -s tests; all checks pass.
"""


@contextmanager
def in_directory(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def pr(title="feat(lab-2): validate requests", head="any-branch", base="dev", body=BODY):
    return {
        "title": title, "body": body,
        "head": {"ref": head, "repo": {"full_name": "team/project"}},
        "base": {"ref": base, "repo": {"full_name": "team/project"}},
    }


class SubjectTests(unittest.TestCase):
    def test_conventional_subjects(self):
        for subject in (
            "feat: add validation", "fix(api): prevent retries", "docs!: remove guide",
            "refactor(core)!: change contract", "chore(v1.0.0): release",
            "style(ui-layout): align buttons", "test: x", "fix: fixed a bug",
        ):
            with self.subTest(subject=subject):
                self.assertTrue(check_commits.validate_subject(subject))

    def test_invalid_subjects(self):
        for subject in (
            "", "feat: ", "Feat: add validation", "build: update tools", "Merge branch dev",
            "feat(): add validation", "fix(scope with spaces): bug", "fix:  bug",
            "fix: bug ", "fix: bug\nbody", "chore(v1..0): release", "fix!!: bug",
            "fix?: bug", "fix!?: bug",
        ):
            with self.subTest(subject=subject):
                self.assertFalse(check_commits.validate_subject(subject))

    def test_message_file_checks_first_line_only(self):
        with tempfile.TemporaryDirectory() as directory:
            message = Path(directory) / "message"
            for content, valid in (
                ("fix: prevent crash\n\nAny body text\n# comment\n", True),
                ("invalid\n\nfix: valid body is not a subject\n", False),
                ("\nfix: later line\n", False), ("", False),
                ("chore(v1.0.0)!: release\r\nbody\r\n", True),
            ):
                with self.subTest(content=content):
                    message.write_text(content)
                    result = subprocess.run(
                        [sys.executable, str(SCRIPTS / "check_commits.py"),
                         "--message-file", str(message)], env=ENV, capture_output=True,
                    )
                    self.assertEqual(result.returncode == 0, valid, result.stderr)


class PRTests(unittest.TestCase):
    def test_task_branches_are_not_enforced(self):
        for head in ("dev", "task/free-form", "feat/lab-99/different-lab", "patch-1"):
            check_pr.check_policy(pr(head=head))
        fork = pr()
        fork["head"]["repo"]["full_name"] = "contributor/fork"
        check_pr.check_policy(fork)

    def test_release_title_and_repository(self):
        release = pr("chore(v1.0.0): release", "dev", "main")
        check_pr.check_policy(release)
        for change in (
            {"title": "chore(lab-1): release"}, {"title": "chore(v1.0): release"},
            {"title": "chore(v1.0.0)!: release"},
            {"title": "chore(v1.0.0)?: release"},
            {"head": {"ref": "task", "repo": {"full_name": "team/project"}}},
            {"head": {"ref": "dev", "repo": {"full_name": "fork/project"}}},
            {"head": {"ref": "dev", "repo": None}},
            {"head": {"ref": "dev", "repo": {}}},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                check_pr.check_policy(dict(release, **change))

    def test_task_title_and_target(self):
        check_pr.check_policy(pr("fix(lab-12): x"))
        for title in ("feat: add tests", "feat(v1.0.0): release", "feat(lab-X): work",
                      "feat(lab-1)!: work", "feat(lab-1)?: work",
                      "feat(lab-1): ", "feat(lab-1): work "):
            with self.subTest(title=title), self.assertRaises(ValueError):
                check_pr.check_policy(pr(title))
        with self.assertRaises(ValueError):
            check_pr.check_policy(pr(base="staging"))

    def test_sections_and_placeholders(self):
        template = (ROOT / ".github/pull_request_template.md").read_text()
        for body in (None, "", template, BODY.replace("## Why?", "## Reason"),
                     BODY + "\n## Why?\nDuplicate reason\n"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                check_pr.check_policy(pr(body=body))
        for heading in check_pr.TEMPLATE_PROMPTS:
            for placeholder in ("", "TODO", "TBD", "N/A", "...", "- [ ] **TODO**",
                                "<!-- real-looking text -->", "Your description here",
                                check_pr.TEMPLATE_PROMPTS[heading]):
                body = "\n".join(
                    f"## {name}\n{placeholder if name == heading else 'Verified behavior changes.'}\n"
                    for name in check_pr.TEMPLATE_PROMPTS
                )
                with self.subTest(heading=heading, placeholder=placeholder), self.assertRaises(ValueError):
                    check_pr.check_policy(pr(body=body))
        check_pr.check_policy(pr(body=BODY.replace("\n", "\r\n")))
        check_pr.check_policy(pr(body=BODY.replace("Add input", "Describe input")))
        with self.assertRaises(ValueError):
            check_pr.check_policy(pr(body="<!--\n" + BODY + "\n-->"))

    def test_event_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / "event.json"
            for payload, valid in ((pr(), True), (pr(title="invalid"), False)):
                event.write_text(json.dumps({"pull_request": payload}))
                result = subprocess.run(
                    [sys.executable, str(SCRIPTS / "check_pr.py")],
                    env=dict(ENV, GITHUB_EVENT_PATH=str(event)), capture_output=True,
                )
                self.assertEqual(result.returncode == 0, valid, result.stderr)


class GitPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="policy test ")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-b", "dev")
        self.git("config", "user.name", "Policy Test")
        self.git("config", "user.email", "policy@example.invalid")
        self.base = self.commit("initial historical subject")
        self.git("switch", "-c", "task")
        for relative in (".github/scripts", ".githooks", "scripts"):
            shutil.copytree(ROOT / relative, self.repo / relative,
                            ignore=shutil.ignore_patterns("__pycache__"))

    def git(self, *args, check=True):
        return subprocess.run(["git", *args], cwd=self.repo, env=ENV, check=check,
                              capture_output=True, text=True)

    def commit(self, subject):
        self.git("-c", "core.hooksPath=/dev/null", "commit", "--allow-empty", "-m", subject)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def update(self, local, remote=None, target="task", local_ref="HEAD"):
        return f"{local_ref} {local} refs/heads/{target} {remote or ZERO}\n"

    def push_check(self, records):
        with in_directory(self.repo):
            check_push.check_push(records.splitlines())

    def hook(self, records):
        return subprocess.run(
            [str(self.repo / ".githooks/pre-push"), "origin", "unreachable.invalid"],
            cwd=self.repo, env=ENV, input=records, capture_output=True, text=True,
        )

    def test_range_checks_every_commit_and_pr_empty(self):
        bad = self.commit("not conventional")
        head = self.commit("fix: repair behavior")
        with in_directory(self.repo):
            self.assertEqual([sha for sha, _ in check_commits.commits_in_range(self.base, head)],
                             [bad, head])
            with self.assertRaisesRegex(ValueError, bad[:7]):
                check_commits.check_range(self.base, head)
            with self.assertRaisesRegex(ValueError, "does not introduce"):
                check_commits.check_range(head, head)
            check_commits.check_range(head, head, allow_empty=True)
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "check_commits.py"), self.base, head],
            cwd=self.repo, env=ENV, capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_merge_introduces_side_branch_commits(self):
        self.git("switch", "-c", "side")
        bad = self.commit("bad side subject")
        self.git("switch", "task")
        self.commit("fix: valid task")
        self.git("merge", "--no-ff", "side", "-m", "chore: merge side")
        with in_directory(self.repo), self.assertRaisesRegex(ValueError, bad[:7]):
            check_commits.check_range(self.base, "HEAD")

    def test_new_branch_baseline_available_locally_or_via_origin(self):
        good = self.commit("feat: implement behavior")
        self.push_check(self.update(good))
        self.assertEqual(self.hook(self.update(good)).returncode, 0)
        self.git("update-ref", "refs/remotes/origin/dev", self.base)
        self.git("branch", "-D", "dev")
        self.push_check(self.update(good))
        self.git("update-ref", "-d", "refs/remotes/origin/dev")
        with self.assertRaisesRegex(ValueError, "baseline"):
            self.push_check(self.update(good))
        self.assertNotEqual(self.hook(self.update(good)).returncode, 0)

    def test_new_branch_prefers_origin_dev_over_unpublished_local_dev(self):
        bad = self.commit("invalid unpublished dev subject")
        self.git("update-ref", "refs/heads/dev", bad)
        good = self.commit("feat: valid task subject")
        self.git("update-ref", "refs/remotes/origin/dev", self.base)
        with in_directory(self.repo):
            self.assertEqual(check_push.new_branch_base(), self.base)
        with self.assertRaisesRegex(ValueError, bad[:7]):
            self.push_check(self.update(good))
        result = self.hook(self.update(good))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(bad[:7], result.stderr)
        # Local dev is the fallback only when origin/dev is unavailable.
        self.git("update-ref", "-d", "refs/remotes/origin/dev")
        with in_directory(self.repo):
            self.assertEqual(check_push.new_branch_base(), bad)
        self.push_check(self.update(good))

    def test_new_branch_invalid_and_non_head_refs(self):
        bad = self.commit("invalid new subject")
        self.git("update-ref", "refs/remotes/origin/task", bad)
        self.git("switch", "--detach", self.base)
        for ref in ("refs/heads/task", "refs/remotes/origin/task"):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                self.push_check(self.update(bad, local_ref=ref))
        good = self.commit("fix: detached change")
        self.push_check(self.update(good, local_ref="HEAD"))

    def test_existing_remote_range_and_no_new_commits(self):
        historical = self.commit("invalid remote history")
        good = self.commit("fix: correct introduced change")
        self.push_check(self.update(good, historical))
        self.push_check(self.update(good, good))
        self.assertEqual(self.hook(self.update(good, good)).returncode, 0)
        bad = self.commit("invalid introduced change")
        with self.assertRaises(ValueError):
            self.push_check(self.update(bad, historical))
        self.assertNotEqual(self.hook(self.update(bad, historical)).returncode, 0)

    def test_force_pushes_allowed_except_main(self):
        remote = self.commit("fix: old remote change")
        self.git("switch", "--detach", self.base)
        local = self.commit("fix: replacement change")
        for target in ("task", "dev"):
            self.push_check(self.update(local, remote, target))
            self.push_check(self.update(self.base, remote, target))
        with self.assertRaisesRegex(ValueError, "Force pushes"):
            self.push_check(self.update(local, remote, "main"))
        with self.assertRaisesRegex(ValueError, "Force pushes"):
            self.push_check(self.update(self.base, remote, "main"))
        self.push_check(self.update(local, self.base, "main"))
        self.push_check(self.update(local, local, "main"))

    def test_multi_ref_and_deletions(self):
        good = self.commit("fix: valid subject")
        bad = self.commit("invalid subject")
        records = self.update(good, self.base) + self.update(bad, good, "dev")
        self.assertNotEqual(self.hook(records).returncode, 0)
        self.push_check(self.update(ZERO, bad))
        self.push_check(self.update("0" * 64, "1" * 64))
        for target in ("main", "dev"):
            records = self.update(ZERO, good, target, local_ref="(delete)")
            with self.subTest(target=target):
                with self.assertRaisesRegex(ValueError, f"Deleting {target}"):
                    self.push_check(records)
                result = self.hook(records)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"Deleting {target}", result.stderr)
        self.push_check("")
        for record in ("HEAD nonsense refs/heads/task " + ZERO, "incomplete",
                       self.update(good, "1" * 40)):
            with self.subTest(record=record), self.assertRaises((ValueError, subprocess.CalledProcessError)):
                self.push_check(record)

    def test_hook_installation_and_commit_hook(self):
        script = self.repo / "scripts/install-hooks.sh"

        def install(*args):
            return subprocess.run([str(script), *args], cwd=self.repo, env=ENV,
                                  capture_output=True, text=True)

        self.assertEqual(install().returncode, 0)
        self.assertEqual(self.git("config", "--local", "--get", "core.hooksPath").stdout.strip(),
                         ".githooks")
        self.assertEqual(install().returncode, 0)
        self.assertNotEqual(install("--unknown").returncode, 0)
        self.git("config", "core.hooksPath", "custom-hooks")
        self.assertNotEqual(install().returncode, 0)
        self.assertEqual(self.git("config", "core.hooksPath").stdout.strip(), "custom-hooks")
        self.git("config", "core.hooksPath", "")
        self.assertNotEqual(install().returncode, 0)
        self.assertEqual(install("--force").returncode, 0)
        self.assertEqual(self.git("commit", "--allow-empty", "-m", "fix: good\n\nBody text").returncode, 0)
        self.assertNotEqual(self.git("commit", "--allow-empty", "-m", "bad", check=False).returncode, 0)

    def test_real_push_through_hook(self):
        bare = self.repo / "remote.git"
        self.git("init", "--bare", str(bare))
        self.git("remote", "add", "origin", str(bare))
        self.git("config", "core.hooksPath", ".githooks")
        self.commit("feat: valid change")
        self.git("push", "origin", "task")
        self.commit("bad introduced subject")
        self.assertNotEqual(self.git("push", "origin", "task", check=False).returncode, 0)
        # The rejected ref remains unchanged on the remote.
        self.assertNotEqual(self.git("rev-parse", "HEAD").stdout,
                            self.git("rev-parse", "refs/remotes/origin/task").stdout)


if __name__ == "__main__":
    unittest.main()
