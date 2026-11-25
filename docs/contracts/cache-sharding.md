# Cache sharding contract

The cache runs on three nodes. Each service decides which node holds a key with a consistent-hash ring, so a key always lives on one node and every process picks the same node. This contract extends the [cache contract](cache.md). Its rules for values, times to live, tombstones, and failures stay in force for each node.

## How the ring works

Every node gets 160 points on a circle of 2^64 positions. A point is the hash of `<node>#<index>`, for index 0 to 159, where `<node>` is the entry of `CACHE_NODES`, such as `cache-2:6379`. A key's position is the hash of the key. The key belongs to the node of the first point at or after its position, wrapping past the end to the first point.

The hash is the first 8 bytes of SHA-256 over the UTF-8 text, read as an unsigned big-endian integer. Python has it in `hashlib` and Java in `MessageDigest`, so neither needs a library. Points with equal positions sort by node name.

Many points per node spread each node's share over the whole circle. With three nodes, the shares of 100,000 keys were 36%, 33%, and 31%. More points did not make them consistently closer: with 256 and 512 points, the largest share was 36% and 35%.

## What moves when the nodes change

Only the keys between a changed node's points and the points before them change owner. Measured over 100,000 keys:

| Change | Keys that move | Where they go |
| --- | --- | --- |
| Remove one of three nodes | 31% | Only the removed node's keys, to the next node on the circle |
| Add a fourth node | 26% | Only to the new node |
| Modulo hashing, three nodes to two | 67% | Almost everywhere |

A moved key is a miss at its new node and is loaded from the datastore once. Nothing is copied between nodes, because every value can be loaded again.

## Failures

A service keeps a separate state for each node. A failed command sends that node into the 1-second back-off of the cache contract. The other nodes are not affected.

While a node is in back-off, its keys go to the next distinct node clockwise. The `order` field of the test vectors lists that sequence. Reads, fills, and tombstones all follow it, so a skipped node costs only misses for its share of keys. When the back-off ends, the node's keys return to it.

Processes do not share their view of a failure. One process can skip a node that another still reaches. A tombstone written to the fallback node is then not seen by a process that reads the owner, and a value that the owner kept from before the failure can be read after the node returns. Both cases end when the time to live ends, which is the staleness bound of the cache contract. Session's versioned values refuse a lower revision on each node, so a returning node cannot replace a newer session than it holds.

## Configuration

`CACHE_NODES` lists the nodes, for example `cache-1:6379,cache-2:6379,cache-3:6379`. All processes use the same list in the same spelling, because the spelling is hashed. A list with one node uses that node for every key. An empty list turns the cache off.

## Compared with Redis Cluster

Redis Cluster also spreads keys over several nodes, but it does not use a ring.

| | This ring | Redis Cluster |
| --- | --- | --- |
| Placement | Key hash against 160 points for each node | `CRC16(key) mod 16384` gives one of 16,384 slots. Each slot is assigned to one primary. |
| Who knows the layout | Each client computes it from `CACHE_NODES` | The nodes gossip the slot map over the cluster bus. Clients cache it and follow `MOVED` and `ASK` replies. |
| Adding a node | About a quarter of the keys miss once | An operator moves slots. Redis copies their keys with `MIGRATE`, and clients get `ASK` during the move. |
| Losing a node | Its keys miss at the next node | A replica of the node is promoted, so no key is lost. Without a replica, the node's slots fail and the cluster can stop accepting writes. |
| Keys in one command | Any keys, each on its own node | Only keys in one slot. `{tags}` in a key force a slot. |
| Balance | Statistical, a few percent apart | Exact, because slots are counted and assigned |
| Moving parts | Three plain Redis processes | Cluster mode, the bus port, and at least three primaries, usually with replicas |

Redis Cluster places data exactly and keeps it through a node failure, which matters when Redis is the store of record. This cache is never the store of record: a lost key is one datastore read. The ring needs no cluster protocol, no migration, and no slot administration, and its behavior during a failure is simply a miss. That trade is right for a cache, and it is why the services implement the ring.

## Test vectors

[`cache-ring-v1/vectors.json`](cache-ring-v1/vectors.json) holds hash positions and, for 64 keys, the order on three nodes and the owner on one, two, three, and four nodes and with `cache-2:6379` skipped. `scripts/cache_ring.py` is the reference implementation and writes the file. Each service tests its ring against it. An independent Java implementation matched all 64 keys.
