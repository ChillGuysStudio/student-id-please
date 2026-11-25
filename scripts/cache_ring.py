#!/usr/bin/env python3
"""Reference consistent-hash ring of the cache sharding contract, and its test vectors.

`python3 scripts/cache_ring.py` rewrites docs/contracts/cache-ring-v1/vectors.json.
Services implement the same ring in their own language and test it against that file.
"""
import bisect
import hashlib
import json
from pathlib import Path

POINTS = 160
VECTORS = Path(__file__).resolve().parents[1] / "docs/contracts/cache-ring-v1/vectors.json"


def position(text):
    """The first 8 bytes of SHA-256 over UTF-8 text, as an unsigned big-endian integer."""
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")


class Ring:
    def __init__(self, nodes):
        if not nodes or len(set(nodes)) != len(nodes):
            raise ValueError("nodes must be distinct and not empty")
        points = sorted((position(f"{node}#{i}"), node) for node in nodes for i in range(POINTS))
        self.positions = [p for p, _ in points]
        self.owners = [n for _, n in points]
        self.nodes = list(nodes)

    def nodes_for(self, key):
        """Every node in the order a key tries them: its owner first, then the next distinct nodes clockwise."""
        start = bisect.bisect_left(self.positions, position(key)) % len(self.positions)
        order = []
        for i in range(len(self.positions)):
            node = self.owners[(start + i) % len(self.positions)]
            if node not in order:
                order.append(node)
                if len(order) == len(self.nodes):
                    break
        return order

    def node_for(self, key, skip=()):
        """The first node of the key's order that is not skipped, or None."""
        return next((n for n in self.nodes_for(key) if n not in skip), None)


def keys(count):
    shapes = ("v1:player:account:{}", "v1:session:context:{}", "v1:rules:rule_version:{}", "v1:applicant:preset-list:{}:20:first")
    return [shapes[i % len(shapes)].format(f"{i:08x}-0000-4000-8000-{i:012x}") for i in range(count)]


def vectors():
    three = ["cache-1:6379", "cache-2:6379", "cache-3:6379"]
    rings = {"three": three, "two": three[:2], "four": three + ["cache-4:6379"], "one": three[:1]}
    out = {"version": 1, "points_per_node": POINTS, "hash": "sha256, first 8 bytes, unsigned big-endian",
           "point_text": "<node>#<index>", "rings": rings,
           "positions": [{"text": t, "position": str(position(t))} for t in ("", "cache-1:6379#0", "v1:player:account:x", "é")],
           "keys": []}
    rs = {name: Ring(nodes) for name, nodes in rings.items()}
    for key in keys(64):
        out["keys"].append({"key": key, "position": str(position(key)), "order": rs["three"].nodes_for(key),
                            **{f"node_{name}": r.node_for(key) for name, r in rs.items() if name != "three"},
                            "node_without_cache_2": rs["three"].node_for(key, skip={"cache-2:6379"})})
    return out


if __name__ == "__main__":
    VECTORS.write_text(json.dumps(vectors(), indent=1, ensure_ascii=False) + "\n")
    print(f"Wrote {VECTORS}")
