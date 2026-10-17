"""Node model, the v1.7c STATE_FLAG states, and connected-dominating-set checks.

A *valid ACTIVE set* (journal v1.7b, Figure 6) is formalised here as a **connected
dominating set (CDS)** over the believed-alive nodes: every believed-alive node is ACTIVE
or adjacent to an ACTIVE node, and the ACTIVE nodes induce a connected subgraph. This is
the standard "virtual backbone" of ad-hoc networking: only backbone nodes relay, and every
node is one hop from the backbone.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field

from .routing import TokenBucket

# STATE_FLAG byte, journal v1.7c: 0 is GHOST, 1 is ACTIVE, 2 is STANDBY.
GHOST = 0
ACTIVE = 1
STANDBY = 2
STATE_NAMES = {GHOST: "GHOST", ACTIVE: "ACTIVE", STANDBY: "STANDBY"}
STATE_CHARS = {ACTIVE: "A", STANDBY: "S", GHOST: "G"}
DEAD_CHAR = "D"

Adj = Sequence[Sequence[int]]
NEVER = -(10**9)


@dataclass
class Node:
    """One slot of the cell. ``alive`` is the truth; the cell's view is kept by the simulation."""

    id: int
    alive: bool = True
    state: int = GHOST
    stem: bool = False
    ghost_streak: int = 0
    window_load: float = 0.0  # relayed load since the last VSEPR cycle
    total_load: float = 0.0  # relayed load since this node joined
    bin_load: float = 0.0  # relayed load in the current 1 s bin
    promoted_cycle: int = NEVER  # VSEPR cycle index of the last move into ACTIVE
    demoted_cycle: int = NEVER  # VSEPR cycle index of the last move out of ACTIVE
    state_changes: int = 0
    incarnation: int = 0  # bumped every time a fresh node takes the slot
    awake_since: float = 0.0  # time the node last left GHOST
    last_flip_t: float = NEVER  # time of the last ACTIVE boundary crossing
    last_flip_dir: int = 0  # +1 into ACTIVE, -1 out of ACTIVE
    last_flip_src: str = ""
    bucket: TokenBucket | None = field(default=None, repr=False)


# --------------------------------------------------------------------------- graph helpers
def components(adj: Adj, nodes: Collection[int]) -> list[list[int]]:
    """Connected components of the subgraph induced by ``nodes`` (sorted, by min id)."""
    inside = set(nodes)
    seen: set[int] = set()
    out = []
    for s in sorted(inside):
        if s in seen:
            continue
        comp = [s]
        seen.add(s)
        stack = [s]
        while stack:
            u = stack.pop()
            for v in adj[u]:
                if v in inside and v not in seen:
                    seen.add(v)
                    comp.append(v)
                    stack.append(v)
        out.append(sorted(comp))
    return out


def _labels(adj: Adj, nodes: Collection[int]) -> dict[int, int]:
    lab = {}
    for i, comp in enumerate(components(adj, nodes)):
        for v in comp:
            lab[v] = i
    return lab


def undominated(adj: Adj, active: Collection[int], alive: Collection[int]) -> list[int]:
    act = set(active)
    return sorted(v for v in alive if v not in act and not any(u in act for u in adj[v]))


def is_cds(adj: Adj, active: Collection[int], alive: Collection[int]) -> bool:
    """True if ``active`` (restricted to ``alive``) is a connected dominating set of ``alive``.

    An empty ``alive`` set is trivially satisfied.
    """
    alive_s = set(alive)
    if not alive_s:
        return True
    act = set(active) & alive_s
    if not act:
        return False
    for v in alive_s:
        if v in act:
            continue
        for u in adj[v]:
            if u in act:
                break
        else:
            return False
    # connectivity of the induced ACTIVE subgraph
    start = next(iter(act))
    seen = {start}
    stack = [start]
    while stack:
        u = stack.pop()
        for v in adj[u]:
            if v in act and v not in seen:
                seen.add(v)
                stack.append(v)
    return len(seen) == len(act)


def swap_preserves_cds(
    adj: Adj, active: Collection[int], alive: Collection[int], out: int, inn: int
) -> bool:
    """Exact check: is ``active - {out} + {inn}`` a CDS of ``alive``?"""
    trial = (set(active) - {out}) | {inn}
    return is_cds(adj, trial, alive)


def swap_filter(
    adj: Adj, active: set[int], alive: set[int], out: int
) -> tuple[list[int], dict[int, int], int]:
    """Precompute what a replacement for ``out`` must satisfy.

    Returns ``(private, labels, n_comps)``: the nodes dominated only by ``out`` (each must be
    in the replacement's closed neighbourhood) and the component labels of the ACTIVE set
    without ``out`` (the replacement must touch every component). Both are necessary
    conditions; callers confirm with :func:`is_cds`.
    """
    rest = active - {out}
    private = []
    for v in (out, *adj[out]):
        if v not in alive or v in rest:
            continue
        if not any(u in rest for u in adj[v]):
            private.append(v)
    labels = _labels(adj, rest)
    n_comps = len(set(labels.values()))
    return private, labels, n_comps


def replacement_ok_fast(
    adj: Adj, cand: int, private: list[int], labels: dict[int, int], n_comps: int
) -> bool:
    closed = (cand, *adj[cand])
    for p in private:
        if p not in closed:
            return False
    if n_comps == 0:
        return True
    touched = {labels[u] for u in adj[cand] if u in labels}
    return len(touched) == n_comps


def find_swap(
    adj: Adj,
    active: set[int],
    alive: set[int],
    out: int,
    pool: Sequence[int],
) -> int | None:
    """First node of ``pool`` (in order) that can replace ``out`` keeping a CDS, else None."""
    private, labels, n_comps = swap_filter(adj, active, alive, out)
    rest = active - {out}
    for c in pool:
        if c in active or c not in alive:
            continue
        if not replacement_ok_fast(adj, c, private, labels, n_comps):
            continue
        if is_cds(adj, rest | {c}, alive):
            return c
    return None


# --------------------------------------------------------------------------- repair
def repair_cds(
    adj: Adj,
    active: Collection[int],
    alive: Collection[int],
    load: Mapping[int, float] | Sequence[float],
) -> tuple[list[int], bool]:
    """Greedy deterministic promotion until ``active`` is a CDS of ``alive``.

    Returns ``(promoted, ok)``: the nodes to promote, in order, and whether the result is
    a CDS. ``ok`` is False exactly when the believed-alive nodes are themselves split into
    several components (no single connected backbone can exist); in that case every
    component still gets its own connected dominating backbone, so traffic inside a part
    keeps flowing.

    Greedy rule (per component of the alive graph):
      * no ACTIVE node yet: promote the node covering the most nodes of its closed
        neighbourhood;
      * otherwise promote the non-ACTIVE node adjacent to the backbone that joins the most
        ACTIVE components, then dominates the most undominated nodes;
      * if every node is dominated but the backbone is in pieces and no single node joins
        two pieces, promote the interior of a shortest connecting path.
    Ties: lowest load, then lowest id.
    """
    alive_s = set(alive)
    act = set(active) & alive_s
    promoted: list[int] = []

    def ld(v: int) -> float:
        return load[v]

    for comp in components(adj, alive_s):
        cset = set(comp)
        guard = 0
        while True:
            guard += 1
            if guard > 4 * len(comp) + 4:  # pragma: no cover - defensive
                break
            act_c = act & cset
            if not act_c:
                best = min(
                    comp, key=lambda v: (-sum(1 for u in (v, *adj[v]) if u in cset), ld(v), v)
                )
                act.add(best)
                promoted.append(best)
                continue
            undom = {v for v in comp if v not in act and not any(u in act for u in adj[v])}
            labels = _labels(adj, act_c)
            n_comps = len(set(labels.values()))
            if not undom and n_comps == 1:
                break
            best = None
            best_key = None
            for c in comp:
                if c in act:
                    continue
                touched = {labels[u] for u in adj[c] if u in labels}
                if not touched:
                    continue
                newly = sum(1 for u in (c, *adj[c]) if u in undom)
                key = (-len(touched), -newly, ld(c), c)
                if best_key is None or key < best_key:
                    best_key = key
                    best = c
            if (
                best is not None
                and best_key is not None
                and (-best_key[0] >= 2 or -best_key[1] >= 1)
            ):
                act.add(best)
                promoted.append(best)
                continue
            path = _connecting_path(adj, act_c, cset, labels)
            if not path:  # pragma: no cover - cannot happen inside a connected component
                break
            for v in path:
                act.add(v)
                promoted.append(v)
    return promoted, is_cds(adj, act, alive_s)


def _connecting_path(
    adj: Adj, act_c: set[int], comp: set[int], labels: dict[int, int]
) -> list[int]:
    """Interior (non-ACTIVE) nodes of a shortest path from ACTIVE component 0 to another."""
    srcs = sorted(v for v in act_c if labels[v] == 0)
    prev: dict[int, int | None] = {s: None for s in srcs}
    frontier = list(srcs)
    while frontier:
        nxt = []
        for u in frontier:
            for v in adj[u]:
                if v not in comp or v in prev:
                    continue
                if v in act_c:
                    if labels[v] != 0:
                        path = []
                        w: int | None = u
                        while w is not None and w not in act_c:
                            path.append(w)
                            w = prev[w]
                        return path[::-1]
                    continue
                prev[v] = u
                nxt.append(v)
        frontier = nxt
    return []
