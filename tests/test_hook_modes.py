"""Check hook permissions recorded by Git, including on shared filesystems."""

from pathlib import Path
import subprocess
import unittest


class HookModeTests(unittest.TestCase):
    def test_git_records_executable_hooks(self):
        root = Path(__file__).resolve().parents[1]
        paths = (".githooks/commit-msg", ".githooks/pre-push", "scripts/install-hooks.sh")
        result = subprocess.run(
            ["git", "ls-files", "--stage", "--", *paths],
            cwd=root, capture_output=True, text=True, check=True,
        )
        modes = {
            line.split("\t", 1)[1]: line.split()[0]
            for line in result.stdout.splitlines()
        }
        for path in paths:
            self.assertEqual(modes.get(path), "100755", path)


if __name__ == "__main__":
    unittest.main()
