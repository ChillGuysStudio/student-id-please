"""Test selective service setup without contacting private repositories."""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("services", ROOT / "scripts/services.py")
services = importlib.util.module_from_spec(spec)
spec.loader.exec_module(services)


class ServiceSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.original_run = subprocess.run
        self.patch = patch.object(services, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.git("init", "--quiet")
        self.git("config", "user.email", "test@example.net")
        self.git("config", "user.name", "Test")
        self.git("commit", "--quiet", "--allow-empty", "-m", "chore: baseline")
        self.sha = self.git("rev-parse", "HEAD").stdout.strip()
        paths = [*services.PROFILES["andrei"], "applicant-service", "gateway-service"]
        modules = []
        for path in paths:
            modules.append(f'[submodule "{path}"]\n\tpath = {path}\n\turl = https://invalid.example/{path}.git\n')
            self.git("update-index", "--add", "--cacheinfo", "160000", self.sha, path)
            self.git("config", "--local", f"submodule.{path}.active", "true")
        (self.root / ".gitmodules").write_text("".join(modules))

    def git(self, *args, cwd=None):
        return self.original_run(
            ["git", *args], cwd=cwd or self.root,
            capture_output=True, text=True, check=True,
        )

    def test_only_owned_paths_are_updated(self):
        calls = []
        def run(command, **kwargs):
            if "submodule" in command and "update" in command:
                calls.append(command)
                return subprocess.CompletedProcess(command, 0)
            return self.original_run(command, **kwargs)
        with patch.object(services.subprocess, "run", side_effect=run):
            services.update("andrei")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][-3:], ["--", "moderation-service", "discord-dms-service"])
        self.assertNotIn("--recursive", calls[0])
        for path in services.PROFILES["andrei"]:
            self.assertEqual(self.git("config", f"submodule.{path}.active").stdout.strip(), "true")
        for path in ("applicant-service", "gateway-service"):
            self.assertEqual(self.git("config", f"submodule.{path}.active").stdout.strip(), "false")
        self.assertEqual(self.git("config", "submodule.recurse").stdout.strip(), "false")
        self.assertEqual(self.git("config", "fetch.recurseSubmodules").stdout.strip(), "false")
        self.assertEqual(self.git("config", "push.recurseSubmodules").stdout.strip(), "no")

    def make_service(self, path):
        directory = self.root / path
        directory.mkdir()
        self.git("init", "--quiet", cwd=directory)
        self.git("config", "user.email", "test@example.net", cwd=directory)
        self.git("config", "user.name", "Test", cwd=directory)
        self.git("commit", "--quiet", "--allow-empty", "-m", "chore: service", cwd=directory)
        return directory

    def test_dirty_service_is_rejected(self):
        directory = self.make_service("moderation-service")
        (directory / "local.txt").write_text("uncommitted")
        with self.assertRaisesRegex(ValueError, "local changes"):
            services.check_worktree("moderation-service")

    def test_task_branch_is_not_detached(self):
        self.make_service("moderation-service")
        with self.assertRaisesRegex(ValueError, "task branch"):
            services.check_worktree("moderation-service")

    def test_uninitialized_service_is_not_probed(self):
        with patch.object(services, "git", side_effect=AssertionError("unexpected git call")):
            services.check_worktree("discord-dms-service")


if __name__ == "__main__":
    unittest.main()
