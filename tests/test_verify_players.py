"""Check how the verification suite finds or creates the demo players, without Docker or a running stack."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from verify_suite.stack import Stack, StackError  # noqa: E402


class DemoPlayerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".env").write_text("OPERATOR_CONTROL_TOKEN=operator-token-1\n")
        (self.root / "scripts").mkdir()
        (self.root / "scripts" / "run_newman.sh").write_text("#!/bin/sh\n")

    def environment(self, name, mark):
        directory = self.root / ".local" / "postman" / name
        directory.mkdir(parents=True)
        values = [{"key": "player0", "value": mark}, {"key": "password0", "value": f"pw-{mark}-xx"}]
        (directory / "private-environment.json").write_text(json.dumps({"values": values}))

    def test_latest_environment_is_used(self):
        self.environment("run-a", "first")
        os.utime(self.root / ".local/postman/run-a/private-environment.json", (1, 1))
        self.environment("run-b", "second")
        self.assertEqual(Stack(self.root, "vf-1").players()["player0"], "second")

    def test_missing_players_are_created_with_newman(self):
        stack = Stack(self.root, "vf-1")
        messages = []
        stack.notice = messages.append

        def fake_newman(*args, **kwargs):
            self.environment("run-new", "created")
            return mock.Mock(returncode=0)
        with mock.patch("verify_suite.stack.subprocess.run", side_effect=fake_newman) as run:
            self.assertEqual(stack.players()["player0"], "created")
        self.assertIn("run_newman.sh", run.call_args[0][0][0])
        self.assertTrue(messages)

    def test_failed_newman_run_is_reported(self):
        stack = Stack(self.root, "vf-1")
        with mock.patch("verify_suite.stack.subprocess.run", return_value=mock.Mock(returncode=1)):
            with self.assertRaises(StackError):
                stack.players()

    def test_player_passwords_are_redacted_once_loaded(self):
        self.environment("run-a", "first")
        stack = Stack(self.root, "vf-1")
        stack.players()
        self.assertNotIn("pw-first-xx", stack.redactor.scrub("login pw-first-xx"))

    def test_a_missing_env_file_names_the_setup_command(self):
        (self.root / ".env").unlink()
        with self.assertRaises(StackError) as raised:
            Stack(self.root, "vf-1")
        self.assertIn("scripts/setup.py", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
