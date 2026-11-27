import collections
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import seed_university_catalog as seed  # noqa: E402


class CatalogBuilderTest(unittest.TestCase):
    def test_catalog_counts_and_kinds(self):
        catalog = seed.build_catalog((ROOT / 'docs/contracts/simulation.md').read_text())
        self.assertEqual(len(catalog), 69)
        self.assertEqual(dict(collections.Counter(item['kind'] for item in catalog)),
                         {'academic_year': 1, 'program': 4, 'course': 32, 'schedule': 32})
        self.assertEqual(len({seed.natural(item) for item in catalog}), 69)


if __name__ == '__main__':
    unittest.main()


class SeedCredentialsTest(unittest.TestCase):
    """The saved seed player survives a stack reset only as a file. A reset removes the player itself."""

    def setUp(self):
        import tempfile
        from unittest import mock
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        path = Path(self.directory.name) / 'seed-admin.json'
        patcher = mock.patch.object(seed, 'CREDENTIALS', path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.path, self.mock = path, mock
        self.saved = {'username': 'seedadminold', 'email': 'old@example.test', 'password': 'old', 'player_id': '00000000-0000-4000-8000-000000000001'}
        path.write_text(__import__('json').dumps(self.saved))

    def calls(self, login_status):
        def call(base, method, path, body=None, token=None, key=None):
            if path == '/api/v1/auth/login':
                return login_status, {}
            return 201, {'player_id': '00000000-0000-4000-8000-000000000002'}
        return call

    def test_a_saved_player_that_still_exists_is_reused(self):
        with self.mock.patch.object(seed, 'call', side_effect=self.calls(200)) as call:
            self.assertEqual(seed.load_credentials('http://gateway'), self.saved)
        self.assertEqual([c.args[2] for c in call.call_args_list], ['/api/v1/auth/login'])

    def test_a_saved_player_removed_by_a_reset_is_registered_again(self):
        with self.mock.patch.object(seed, 'call', side_effect=self.calls(401)):
            creds = seed.load_credentials('http://gateway')
        self.assertEqual(creds['player_id'], '00000000-0000-4000-8000-000000000002')
        self.assertNotEqual(creds['password'], 'old')
        self.assertEqual(__import__('json').loads(self.path.read_text()), creds)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_another_login_failure_stops_the_seed(self):
        with self.mock.patch.object(seed, 'call', side_effect=self.calls(503)):
            with self.assertRaises(RuntimeError):
                seed.load_credentials('http://gateway')
        self.assertEqual(__import__('json').loads(self.path.read_text()), self.saved)
