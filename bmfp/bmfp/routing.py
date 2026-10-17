"""Path selection: chill (one shortest path), duplicate and stripe (node-disjoint paths).

Rule shared by every mode: a path may start and end at any node (the sender and receiver
can be in any state), but every *interior* node must be a relay, i.e. a believed-alive
ACTIVE node. ``relay`` is a boolean mask over node ids.

``bfs_counts`` runs one BFS from ``src`` that expands only ``src`` and relay nodes, so the
distances and shortest-path counts it returns are valid for every destination at once
(non-relay nodes are reached as leaves but never expanded). That lets the simulator cache
one BFS per source while the relay set is unchanged.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

Adj = Sequence[Sequence[int]]

CHILL = "chill"
DUPLICATE = "duplicate"
STRIPE = "stripe"
ADAPTIVE_DUPLICATE = "adaptive_duplicate"
ADAPTIVE_STRIPE = "adaptive_stripe"
ROUTINGS = (CHILL, DUPLICATE, STRIPE, ADAPTIVE_DUPLICATE, ADAPTIVE_STRIPE)


def bfs_counts(
    adj: Adj,
    src: int,
    relay: Sequence[bool],
    banned_edge: tuple[int, int] | None = None,
) -> tuple[list[int], list[int]]:
    """Distances and numbers of shortest paths from ``src`` using relays as interiors.

    Returns ``(dist, count)``; ``dist[v] == -1`` means unreachable.
    """
    n = len(adj)
    dist = [-1] * n
    cnt = [0] * n
    dist[src] = 0
    cnt[src] = 1
    frontier = [src]
    while frontier:
        nxt = []
        for u in frontier:
            if u != src and not relay[u]:
                continue  # endpoint-only node: reached, never expanded
            du = dist[u] + 1
            cu = cnt[u]
            for v in adj[u]:
                if banned_edge is not None and ((u, v) == banned_edge or (v, u) == banned_edge):
                    continue
                dv = dist[v]
                if dv < 0:
                    dist[v] = du
                    cnt[v] = cu
                    nxt.append(v)
                elif dv == du:
                    cnt[v] += cu
        frontier = nxt
    return dist, cnt


def sample_path(
    adj: Adj,
    dist: Sequence[int],
    cnt: Sequence[int],
    src: int,
    dst: int,
    relay: Sequence[bool],
    rng: random.Random | None,
    banned_edge: tuple[int, int] | None = None,
) -> list[int] | None:
    """One shortest path src -> dst.

    With ``rng`` the path is drawn uniformly among all shortest paths (each predecessor is
    picked with probability proportional to its path count). Without ``rng`` the
    lowest-id predecessor is taken at every step (deterministic path).
    """
    if dist[dst] < 0 or src == dst:
        return None
    path = [dst]
    v = dst
    while v != src:
        dv = dist[v] - 1
        preds = []
        for u in adj[v]:
            if dist[u] != dv or (u != src and not relay[u]):
                continue
            if banned_edge is not None and ((u, v) == banned_edge or (v, u) == banned_edge):
                continue
            preds.append(u)
        if not preds:  # pragma: no cover - inconsistent dist/cnt input
            return None
        if rng is None or len(preds) == 1:
            u = preds[0]
        else:
            total = sum(cnt[p] for p in preds)
            r = rng.random() * total
            acc = 0
            u = preds[-1]
            for p in preds:
                acc += cnt[p]
                if r < acc:
                    u = p
                    break
        path.append(u)
        v = u
    path.reverse()
    return path


def shortest_path(
    adj: Adj, src: int, dst: int, relay: Sequence[bool], rng: random.Random | None = None
) -> list[int] | None:
    dist, cnt = bfs_counts(adj, src, relay)
    return sample_path(adj, dist, cnt, src, dst, relay, rng)


def disjoint_paths(
    adj: Adj,
    src: int,
    dst: int,
    relay: Sequence[bool],
    k: int,
    rng: random.Random | None = None,
    first: tuple[list[int], list[int]] | None = None,
) -> list[list[int]]:
    """Up to ``k`` node-disjoint paths, greedily.

    Take a shortest path, remove its interior nodes from the relay set (and the direct
    src-dst edge if the path used it), repeat. Greedy is not maximum-flow optimal, but it
    is the obvious reading of "open every path" and it is deterministic per rng state.
    ``first`` may pass a cached ``(dist, cnt)`` for the first BFS.
    """
    mask = list(relay)
    banned: tuple[int, int] | None = None
    paths: list[list[int]] = []
    for i in range(k):
        if i == 0 and first is not None:
            dist, cnt = first
        else:
            dist, cnt = bfs_counts(adj, src, mask, banned)
        p = sample_path(adj, dist, cnt, src, dst, mask, rng, banned)
        if p is None:
            break
        paths.append(p)
        for v in p[1:-1]:
            mask[v] = False
        if len(p) == 2:
            banned = (src, dst)
    return paths


def paths_are_node_disjoint(paths: Sequence[Sequence[int]]) -> bool:
    seen: set[int] = set()
    direct = 0
    for p in paths:
        if len(p) == 2:
            direct += 1
        for v in p[1:-1]:
            if v in seen:
                return False
            seen.add(v)
    return direct <= 1


class TokenBucket:
    """Rate limiter: refill ``rate`` tokens/s up to ``burst`` (v1.3 rate limiting; Part VIII)."""

    __slots__ = ("rate", "burst", "tokens", "t")

    def __init__(self, rate: float, burst: float, t: float = 0.0) -> None:
        self.rate = float(rate)
        self.burst = float(burst)
        self.tokens = float(burst)
        self.t = float(t)

    def refill(self, t: float) -> None:
        if t > self.t:
            self.tokens = min(self.burst, self.tokens + (t - self.t) * self.rate)
            self.t = t

    def take(self, t: float, cost: float) -> bool:
        """Consume ``cost`` tokens at time ``t`` if available."""
        self.refill(t)
        if self.tokens + 1e-9 >= cost:
            self.tokens -= cost
            return True
        return False
