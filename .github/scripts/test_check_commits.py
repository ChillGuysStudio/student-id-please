"""Tests for the commit policy checker."""

import unittest

from check_commits import validate_subject


class ValidateSubjectTests(unittest.TestCase):
    def test_accepts_documented_types_and_scopes(self):
        for commit_type in (
            "feat",
            "fix",
            "docs",
            "style",
            "refactor",
            "test",
            "chore",
        ):
            with self.subTest(commit_type=commit_type):
                self.assertTrue(
                    validate_subject(
                        f"{commit_type}(applicant-service): update validation rules"
                    )
                )

    def test_accepts_lab_scope(self):
        self.assertTrue(validate_subject("docs(lab-0): update workflow rules"))

    def test_rejects_undocumented_formats(self):
        invalid_subjects = (
            "update workflow rules",
            "build(ci): update workflow rules",
            "chore: update workflow rules",
            "chore(CI): update workflow rules",
            "chore(ci):",
            "chore(ci):  padded summary ",
        )
        for subject in invalid_subjects:
            with self.subTest(subject=subject):
                self.assertFalse(validate_subject(subject))


if __name__ == "__main__":
    unittest.main()
