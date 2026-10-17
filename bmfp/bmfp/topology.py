"""Cage topologies (3-regular polyhedral graphs) and connectivity analysis.

Every cage is built from standard 3D vertex coordinates. Edges are the vertex pairs at the
minimum pairwise distance (relative tolerance 1e-6), so nothing about the graph is typed
in by hand: the link count, degree and diameter all fall out of the geometry.

Node ids are assigned deterministically by sorting the rounded coordinates.
"""

from __future__ import annotations

import itertools
import math
import random
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cache

PHI = (1.0 + math.sqrt(5.0)) / 2.0

Adj = Sequence[Sequence[int]]


@dataclass(frozen=True)
class Cage:
    """An immutable cage graph with unit-sphere coordinates."""

    name: str
    n: int
    edges: tuple[tuple[int, int], ...]
    adj: tuple[tuple[int, ...], ...]
    coords: tuple[tuple[float, float, float], ...]

    @property
    def links(self) -> int:
        return len(self.edges)


# --------------------------------------------------------------------------- coordinates
def _signs(values: Sequence[float]) -> list[tuple[float, ...]]:
    """All sign combinations of ``values`` (zeros are not doubled)."""
    choices = [(v,) if v == 0 else (v, -v) for v in values]
    return [tuple(c) for c in itertools.product(*choices)]


def _cyclic(t: Sequence[float]) -> list[tuple[float, ...]]:
    a, b, c = t
    return [(a, b, c), (b, c, a), (c, a, b)]


def _truncated_tetrahedron() -> list[tuple[float, ...]]:
    # All permutations of (±1, ±1, ±3) with an even number of minus signs.
    pts = set()
    for perm in set(itertools.permutations((1.0, 1.0, 3.0))):
        for s in _signs(perm):
            if sum(1 for x in s if x < 0) % 2 == 0:
                pts.add(s)
    return sorted(pts)


def _dodecahedron() -> list[tuple[float, ...]]:
    pts = set(_signs((1.0, 1.0, 1.0)))
    for t in ((0.0, 1.0 / PHI, PHI), (1.0 / PHI, PHI, 0.0), (PHI, 0.0, 1.0 / PHI)):
        pts.update(_signs(t))
    return sorted(pts)


def _truncated_octahedron() -> list[tuple[float, ...]]:
    pts = set()
    for perm in itertools.permutations((0.0, 1.0, 2.0)):
        pts.update(_signs(perm))
    return sorted(pts)


def _truncated_icosahedron() -> list[tuple[float, ...]]:
    # Even (cyclic) permutations of (0, ±1, ±3φ), (±1, ±(2+φ), ±2φ), (±φ, ±2, ±(2φ+1)).
    pts = set()
    for base in ((0.0, 1.0, 3 * PHI), (1.0, 2 + PHI, 2 * PHI), (PHI, 2.0, 2 * PHI + 1)):
        for t in _cyclic(base):
            pts.update(_signs(t))
    return sorted(pts)


_BUILDERS = {
    "C12": ("truncated tetrahedron", _truncated_tetrahedron),
    "C20": ("dodecahedron", _dodecahedron),
    "C24": ("truncated octahedron", _truncated_octahedron),
    "C60": ("truncated icosahedron", _truncated_icosahedron),
}

SOLIDS = {name: solid for name, (solid, _) in _BUILDERS.items()}


def build_cage(name: str, points: Iterable[Sequence[float]], tol: float = 1e-6) -> Cage:
    """Build a cage from raw vertex coordinates (edges = minimum-distance pairs)."""
    raw = [tuple(float(x) for x in p) for p in points]
    # deterministic ids: sort rounded coordinates
    raw.sort(key=lambda p: tuple(round(x, 9) for x in p))
    n = len(raw)
    if n < 4:
        raise ValueError("a cage needs at least 4 vertices")
    d2 = {}
    for i in range(n):
        for j in range(i + 1, n):
            d2[(i, j)] = sum((raw[i][k] - raw[j][k]) ** 2 for k in range(3))
    dmin = min(d2.values())
    edges = tuple(sorted(p for p, d in d2.items() if math.sqrt(d) <= math.sqrt(dmin) * (1 + tol)))
    nbrs: list[list[int]] = [[] for _ in range(n)]
    for i, j in edges:
        nbrs[i].append(j)
        nbrs[j].append(i)
    adj = tuple(tuple(sorted(x)) for x in nbrs)
    coords = []
    for p in raw:
        r = math.sqrt(sum(x * x for x in p))
        coords.append(tuple(x / r for x in p))
    return Cage(name=name, n=n, edges=edges, adj=adj, coords=tuple(coords))  # type: ignore[arg-type]


@cache
def cage(name: str) -> Cage:
    """Look up a cage by name (C12, C20, C24, C60)."""
    try:
        _, builder = _BUILDERS[name]
    except KeyError as exc:
        raise KeyError(f"unknown cage {name!r}; choose from {sorted(_BUILDERS)}") from exc
    return build_cage(name, builder())


CAGE_NAMES = tuple(_BUILDERS)
CAGES = {name: cage(name) for name in CAGE_NAMES}


# --------------------------------------------------------------------------- analysis
def bfs_dist(adj: Adj, src: int, removed: Iterable[int] = ()) -> list[int]:
    """Hop distances from ``src``; -1 for unreachable or removed nodes."""
    gone = set(removed)
    dist = [-1] * len(adj)
    if src in gone:
        return dist
    dist[src] = 0
    q = deque([src])
    while q:
        u = q.popleft()
        for v in adj[u]:
            if dist[v] < 0 and v not in gone:
                dist[v] = dist[u] + 1
                q.append(v)
    return dist


def is_connected(adj: Adj, removed: Iterable[int] = ()) -> bool:
    """True if the nodes that survive ``removed`` form one connected component.

    Zero or one surviving node counts as connected.
    """
    gone = set(removed)
    alive = [v for v in range(len(adj)) if v not in gone]
    if len(alive) <= 1:
        return True
    dist = bfs_dist(adj, alive[0], gone)
    return all(dist[v] >= 0 for v in alive)


def diameter(adj: Adj) -> int:
    """Largest shortest-path distance (graph must be connected)."""
    best = 0
    for s in range(len(adj)):
        d = bfs_dist(adj, s)
        if min(d) < 0:
            raise ValueError("graph is disconnected")
        best = max(best, max(d))
    return best


def all_pairs_dist(adj: Adj) -> list[list[int]]:
    return [bfs_dist(adj, s) for s in range(len(adj))]


def min_vertex_cut(adj: Adj, max_k: int = 3) -> int | None:
    """Exact minimum vertex cut size up to ``max_k`` (brute force; small graphs only).

    Checks every removal of k = 1, 2, ... nodes. For k = 3 the neighbourhoods are tried
    first (a 3-regular graph is always cut by removing one node's three neighbours).
    Returns None if no cut of size <= max_k exists.
    """
    n = len(adj)
    for k in range(1, max_k + 1):
        if n - k < 2:
            return None
        if k == len(adj[0]):
            for v in range(n):
                if len(adj[v]) == k and not is_connected(adj, adj[v]):
                    return k
        for combo in itertools.combinations(range(n), k):
            if not is_connected(adj, combo):
                return k
    return None


def faces(n: int, e: int) -> int:
    """Face count of a convex polyhedron via Euler's formula V - E + F = 2."""
    return 2 - n + e


EXACT_PARTITION_LIMIT = 150_000  # enumerate every k-set up to this many (bitmask check)


def neighbour_masks(adj: Adj) -> list[int]:
    """Bit ``u`` of ``masks[v]`` is set when u is a neighbour of v."""
    out = [0] * len(adj)
    for v, nbrs in enumerate(adj):
        for u in nbrs:
            out[v] |= 1 << u
    return out


def reach_mask(start: int, inside: int, nb: Sequence[int]) -> int:
    """Nodes of ``inside`` (a bitmask) reachable from the bitmask ``start`` within it."""
    seen = start & inside
    frontier = seen
    while frontier:
        new = 0
        m = frontier
        while m:
            b = m & -m
            new |= nb[b.bit_length() - 1]
            m ^= b
        frontier = new & inside & ~seen
        seen |= frontier
    return seen


def mask_connected(mask: int, nb: Sequence[int]) -> bool:
    """True if the nodes in ``mask`` induce a connected subgraph (empty counts as connected)."""
    if mask == 0:
        return True
    return reach_mask(mask & -mask, mask, nb) == mask


def partition_probability(
    g: Cage, k: int, trials: int = 20000, rng: random.Random | None = None
) -> float:
    """Fraction of k-node removals that disconnect the surviving nodes.

    Exact enumeration when C(n, k) <= ``EXACT_PARTITION_LIMIT``, else Monte Carlo with
    ``trials`` samples drawn from ``rng`` (required for determinism; defaults to Random(0)).
    """
    n = g.n
    if k <= 0:
        return 0.0
    if k >= n - 1:
        return 0.0
    total = math.comb(n, k)
    if total <= EXACT_PARTITION_LIMIT:
        nb = neighbour_masks(g.adj)
        full = (1 << n) - 1
        bits = [1 << i for i in range(n)]
        cut = sum(
            1 for c in itertools.combinations(bits, k) if not mask_connected(full & ~sum(c), nb)
        )
        return cut / total
    rng = rng or random.Random(0)
    nodes = list(range(n))
    cut = 0
    for _ in range(trials):
        if not is_connected(g.adj, rng.sample(nodes, k)):
            cut += 1
    return cut / trials


def is_exact_partition(n: int, k: int) -> bool:
    return math.comb(n, k) <= EXACT_PARTITION_LIMIT


# --------------------------------------------------------------------------- backbones
def _closed_masks(adj: Adj) -> list[int]:
    return [m | (1 << v) for v, m in enumerate(neighbour_masks(adj))]


def min_cds_exact(adj: Adj, lower: int, upper: int) -> int | None:
    """Exact size of a minimum connected dominating set, searched for k = lower..upper.

    Branch and bound over bitmasks: while some node is undominated, branch on the closed
    neighbourhood of the lowest one (every dominating set contains one of those nodes);
    once everything is dominated but the set is in pieces, branch on the neighbours of its
    first piece (a connected superset must contain one). Prune when the undominated nodes
    outnumber 4 per remaining slot (a node dominates at most itself and 3 neighbours in a
    cubic graph; ``max_cover`` generalises it). None if no CDS of size <= upper exists.
    """
    nb = neighbour_masks(adj)
    closed = _closed_masks(adj)
    n = len(adj)
    full = (1 << n) - 1
    max_cover = 1 + max((len(a) for a in adj), default=0)

    def search(k: int) -> bool:
        seen: set[int] = set()

        def rec(S: int, dom: int, size: int) -> bool:
            if S in seen:
                return False
            seen.add(S)
            if dom == full:
                first = reach_mask(S & -S, S, nb)
                if first == S:
                    return True
                if size == k:
                    return False
                bnd = 0
                m = first
                while m:
                    b = m & -m
                    bnd |= nb[b.bit_length() - 1]
                    m ^= b
                cand = bnd & ~S
            else:
                if size == k:
                    return False
                und = full & ~dom
                if und.bit_count() > max_cover * (k - size):
                    return False
                cand = closed[(und & -und).bit_length() - 1]
            m = cand
            while m:
                b = m & -m
                m ^= b
                if rec(S | b, dom | closed[b.bit_length() - 1], size + 1):
                    return True
            return False

        return rec(0, 0, 0)

    for k in range(max(1, lower), upper + 1):
        if search(k):
            return k
    return None


def min_dominating_exact(adj: Adj) -> int:
    """Exact size of a minimum dominating set (connectivity not required)."""
    closed = _closed_masks(adj)
    n = len(adj)
    full = (1 << n) - 1
    max_cover = 1 + max((len(a) for a in adj), default=0)

    def rec(dom: int, left: int) -> bool:
        if dom == full:
            return True
        und = full & ~dom
        if left == 0 or und.bit_count() > max_cover * left:
            return False
        m = closed[(und & -und).bit_length() - 1]
        while m:
            b = m & -m
            m ^= b
            if rec(dom | closed[b.bit_length() - 1], left - 1):
                return True
        return False

    for k in range(1, n + 1):
        if rec(0, k):
            return k
    return n


def is_dominating(adj: Adj, nodes: Iterable[int]) -> bool:
    closed = _closed_masks(adj)
    dom = 0
    for v in nodes:
        dom |= closed[v]
    return dom == (1 << len(adj)) - 1


def cds_search(adj: Adj, forced: Iterable[int], iters: int, rng: random.Random) -> int:
    """Size of the smallest CDS containing ``forced`` found by randomised pruning.

    Each round starts from every node and drops nodes in a random order whenever the rest
    is still a CDS. A heuristic: the result is an upper bound on the true minimum (it
    proves that a CDS of that size exists), not the minimum itself.
    """
    nb = neighbour_masks(adj)
    closed = _closed_masks(adj)
    n = len(adj)
    full = (1 << n) - 1
    keep = 0
    for v in forced:
        keep |= 1 << v

    def ok(S: int) -> bool:
        dom = 0
        m = S
        while m:
            b = m & -m
            dom |= closed[b.bit_length() - 1]
            m ^= b
        return dom == full and mask_connected(S, nb)

    best = n
    order = list(range(n))
    for _ in range(max(1, iters)):
        rng.shuffle(order)
        S = full
        for v in order:
            if keep >> v & 1:
                continue
            T = S & ~(1 << v)
            if ok(T):
                S = T
        best = min(best, S.bit_count())
    return best


def ring(n: int) -> tuple[tuple[int, ...], ...]:
    """The n-node cycle (Figure 6 draws its 12-node cell as one)."""
    return tuple(tuple(sorted(((v - 1) % n, (v + 1) % n))) for v in range(n))


def cage_facts(g: Cage) -> dict:
    """Degree, diameter, min vertex cut and face count of a cage."""
    degs = {len(a) for a in g.adj}
    return {
        "cage": g.name,
        "solid": SOLIDS.get(g.name, ""),
        "n": g.n,
        "links": g.links,
        "degree": degs.pop() if len(degs) == 1 else None,
        "diameter": diameter(g.adj),
        "min_vertex_cut": min_vertex_cut(g.adj),
        "faces": faces(g.n, g.links),
    }


@cache
def stem_triple(name: str) -> tuple[int, int, int]:
    """Three nodes that maximise pairwise hop distance (min pair first, then sum).

    Ties go to the lexicographically smallest triple, so the choice is deterministic.
    """
    g = cage(name)
    return far_triple(g.adj)


def far_triple(adj: Adj) -> tuple[int, int, int]:
    d = all_pairs_dist(adj)
    n = len(adj)
    best_key = None
    best = (0, 1, 2)
    for a, b, c in itertools.combinations(range(n), 3):
        ab, ac, bc = d[a][b], d[a][c], d[b][c]
        key = (min(ab, ac, bc), ab + ac + bc)
        if best_key is None or key > best_key:
            best_key = key
            best = (a, b, c)
    return best
