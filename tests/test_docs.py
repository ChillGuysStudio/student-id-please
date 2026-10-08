"""Test local documentation links and image references."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_docs", ROOT / ".github/scripts/check_docs.py")
check_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_docs)


class DocumentationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch = patch.object(check_docs, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.page = self.root / "README.md"

    def check(self, text):
        self.page.write_text(text)
        return check_docs.check_file(self.page)

    def test_existing_image_and_heading(self):
        (self.root / "architecture.jpg").write_bytes(b"image")
        (self.root / "guide.md").write_text("# Guide\n\n## Run the stack\n")
        self.assertEqual(self.check('<img src="architecture.jpg"/>\n[Run](guide.md#run-the-stack)'), [])

    def test_missing_image(self):
        self.assertIn("missing target", self.check('<img src="missing.jpg"/>')[0])

    def test_missing_heading(self):
        (self.root / "guide.md").write_text("# Guide\n")
        self.assertIn("missing heading", self.check("[Run](guide.md#run)")[0])

    def test_code_examples_are_not_links(self):
        self.assertEqual(self.check("```md\n[Example](missing.md)\n```"), [])

    def test_external_links_are_not_fetched(self):
        self.assertEqual(self.check("[Image](https://invalid.example/image.jpg)"), [])

    def test_path_must_stay_in_repository(self):
        self.assertIn("leaves repository", self.check("[Outside](../secret.md)")[0])


if __name__ == "__main__":
    unittest.main()
