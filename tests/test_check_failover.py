import importlib.util
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_failover", ROOT / "scripts/check_failover.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class Fake:
    kind = "postgres"

    def __init__(self, promotes=True, loses=False):
        self.promotes, self.loses, self.rows, self.cleaned = promotes, loses, [], False

    def primary(self, skip=None):
        return "db-1" if skip is None else "db-2" if self.promotes else None

    def write(self, node, marker):
        if not (self.loses and node == "db-2"):
            self.rows.append(marker)
        return True

    def read(self, node):
        return self.rows

    def rejoined(self, node):
        return True

    def clean(self, node):
        self.cleaned = True


class CheckFailover(unittest.TestCase):
    def run_fake(self, fake):
        with mock.patch.object(check, "compose", return_value=mock.Mock(returncode=0)) as compose, \
                mock.patch.object(check, "REJOIN", 0.2), mock.patch.dict(check.LIMIT, {"postgres": 0.2}), \
                mock.patch.object(check.time, "sleep"):
            try:
                return check.failover(fake)
            finally:
                # The killed member always starts again.
                self.assertEqual([call.args for call in compose.call_args_list], [("kill", "db-1"), ("start", "db-1")])

    def test_failover_passes_and_cleans_up(self):
        fake = Fake()
        self.assertEqual(self.run_fake(fake)[:2], ("db-1", "db-2"))
        self.assertTrue(fake.cleaned)

    def test_no_promotion_fails_and_restarts_the_member(self):
        with self.assertRaisesRegex(RuntimeError, "no member accepted a write"):
            self.run_fake(Fake(promotes=False))

    def test_a_lost_marker_fails(self):
        fake = Fake(loses=True)
        with self.assertRaisesRegex(RuntimeError, "misses a marker"):
            self.run_fake(fake)
        self.assertTrue(fake.cleaned)

    def test_a_hung_command_counts_as_failed(self):
        with mock.patch.object(check.subprocess, "run", side_effect=check.subprocess.TimeoutExpired("x", 30)):
            self.assertNotEqual(check.compose("ps").returncode, 0)
            self.assertIsNone(check.Postgres("player-db").primary())
            self.assertIsNone(check.Mongo("mongodb").primary())

    def test_primary_selection_reads_each_member(self):
        replies = {"player-db-1": "t", "player-db-2": "f", "player-db-3": "t"}
        with mock.patch.object(check, "compose", side_effect=lambda *a, **k: mock.Mock(returncode=0, stdout=replies[a[2]])):
            self.assertEqual(check.Postgres("player-db").primary(), "player-db-2")
            self.assertIsNone(check.Postgres("player-db").primary(skip="player-db-2"))
            self.assertTrue(check.Postgres("player-db").rejoined("player-db-1"))
            self.assertFalse(check.Postgres("player-db").rejoined("player-db-2"))
        replies = {"mongodb-1": "noise\nfalse\n", "mongodb-2": "", "mongodb-3": "true\n"}
        with mock.patch.object(check, "compose", side_effect=lambda *a, **k: mock.Mock(returncode=0, stdout=replies[a[2]])):
            self.assertEqual(check.Mongo("mongodb").primary(), "mongodb-3")

    def test_it_covers_every_replicated_database(self):
        compose = (ROOT / "compose.yaml").read_text()
        for name in (*check.POSTGRES, *check.MONGO):
            for member in check.members(name):
                self.assertIn(f"\n  {member}:\n", compose)

    def test_unknown_database_is_rejected(self):
        with self.assertRaises(SystemExit):
            check.main(["broker-db"])


if __name__ == "__main__":
    unittest.main()
