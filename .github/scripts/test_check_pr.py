"""Positive and negative controls for the PR workflow check."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from check_pr import check_docs, check_policy


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.pr = {
            "title": "docs(lab-0): define communication contracts",
            "head": {"ref": "docs/lab-0/communication-contracts", "repo": {"full_name": "ChillGuysStudio/student-id-please"}},
            "base": {"ref": "dev", "repo": {"full_name": "ChillGuysStudio/student-id-please"}},
            "body": "## Why?\nLab requirements\n## Changes\nContracts\n## How to Test?\nCheck docs",
        }

    def test_task_and_release_are_accepted(self):
        check_policy(self.pr)
        self.pr["head"]["ref"] = "dev"
        self.pr["base"]["ref"] = "main"
        check_policy(self.pr)

    def test_bad_title_branch_lab_and_target_are_rejected(self):
        changes = [
            ("title", None, "bad title"),
            ("head", "ref", "bad branch"),
            ("head", "ref", "docs/lab-1/communication-contracts"),
            ("base", "ref", "main"),
            ("base", "ref", "other"),
            ("body", None, "## Why?\n\n## Changes\nContracts\n## How to Test?\nCheck"),
            ("body", None, "Missing required headings"),
        ]
        for key, nested, value in changes:
            with self.subTest(value=value):
                pr = copy.deepcopy(self.pr)
                if nested:
                    pr[key][nested] = value
                else:
                    pr[key] = value
                with self.assertRaises(ValueError):
                    check_policy(pr)

    def test_fork_dev_cannot_target_main(self):
        self.pr["base"]["ref"] = "main"
        self.pr["head"]["ref"] = "dev"
        self.pr["head"]["repo"]["full_name"] = "someone/fork"
        with self.assertRaises(ValueError):
            check_policy(self.pr)


class DocumentTests(unittest.TestCase):
    def check_text(self, text):
        # An empty directory supplies an absent target; mock text instead of
        # writing fixture files into the repository being checked.
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(Path, "read_text", return_value=text):
                check_docs(Path(directory))

    def test_valid_json_and_external_link(self):
        self.check_text('[external](https://example.com)\n```json\n{"x":1}\n```\n')

    def test_invalid_json_is_rejected(self):
        with self.assertRaises(ValueError):
            self.check_text('```json\n{"bad":}\n```\n')

    def test_missing_and_escaping_links_are_rejected(self):
        for target in ("missing.md", "../outside.md"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.check_text(f'[link]({target})')

    def test_fenced_example_links_are_not_real_links(self):
        self.check_text('```markdown\n[example](missing.md)\n```\n')


if __name__ == "__main__":
    unittest.main()
