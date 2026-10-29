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
