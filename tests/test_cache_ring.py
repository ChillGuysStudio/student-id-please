import collections
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cache_ring", ROOT / "scripts/cache_ring.py")
ring = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ring)


class CacheRing(unittest.TestCase):
    def test_vectors_match_the_reference(self):
        self.assertEqual(json.loads(ring.VECTORS.read_text()), ring.vectors())

    def test_removing_a_node_moves_only_its_keys(self):
        three = ring.Ring(["cache-1:6379", "cache-2:6379", "cache-3:6379"])
        two = ring.Ring(["cache-1:6379", "cache-2:6379"])
        keys = [f"v1:k:{i}" for i in range(20000)]
        for key in keys:
            owner = three.node_for(key)
            if owner != "cache-3:6379":
                self.assertEqual(two.node_for(key), owner)
            self.assertEqual(three.node_for(key, skip={owner}), three.nodes_for(key)[1])
        shares = collections.Counter(three.node_for(k) for k in keys)
        self.assertTrue(all(0.25 < n / len(keys) < 0.42 for n in shares.values()), shares)

    def test_skipping_every_node_finds_none(self):
        nodes = ["cache-1:6379", "cache-2:6379"]
        self.assertIsNone(ring.Ring(nodes).node_for("k", skip=set(nodes)))
        with self.assertRaises(ValueError):
            ring.Ring(["cache-1:6379", "cache-1:6379"])

    def test_known_positions(self):
        # Computed independently with `printf %s TEXT | sha256sum`.
        self.assertEqual(ring.position(""), 0xe3b0c44298fc1c14)
        self.assertEqual(ring.position("abc"), 0xba7816bf8f01cfea)


if __name__ == "__main__":
    unittest.main()
