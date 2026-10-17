import random
from collections import Counter

import pytest

from bmfp.routing import (
    TokenBucket,
    bfs_counts,
    disjoint_paths,
    paths_are_node_disjoint,
    sample_path,
    shortest_path,
)
from bmfp.topology import bfs_dist, cage

# s=0 -> {1,2} -> 3 -> {4,5,6} -> 7 : 2 * 3 = 6 shortest paths
DIAMOND = (
    (1, 2),
    (0, 3),
    (0, 3),
    (1, 2, 4, 5, 6),
    (3, 7),
    (3, 7),
    (3, 7),
    (4, 5, 6),
)
ALL = [True] * 8


def test_bfs_counts_number_of_shortest_paths():
    dist, cnt = bfs_counts(DIAMOND, 0, ALL)
    assert dist[7] == 4 and cnt[7] == 6
    assert cnt[3] == 2


def test_bfs_distances_match_plain_bfs_when_everyone_relays():
    g = cage("C60")
    dist, _ = bfs_counts(g.adj, 5, [True] * 60)
    assert dist == bfs_dist(g.adj, 5)


def test_uniform_sampling_over_all_shortest_paths():
    rng = random.Random(1)
    dist, cnt = bfs_counts(DIAMOND, 0, ALL)
    seen = Counter(tuple(sample_path(DIAMOND, dist, cnt, 0, 7, ALL, rng)) for _ in range(6000))
    assert len(seen) == 6
    for c in seen.values():
        assert abs(c / 6000 - 1 / 6) < 0.03


def test_deterministic_path_takes_lowest_id_predecessor():
    dist, cnt = bfs_counts(DIAMOND, 0, ALL)
    assert sample_path(DIAMOND, dist, cnt, 0, 7, ALL, None) == [0, 1, 3, 4, 7]


def test_interior_nodes_must_be_relays_but_endpoints_need_not():
    relay = [False, True, False, True, False, True, False, False]
    for seed in range(20):
        p = shortest_path(DIAMOND, 0, 7, relay, random.Random(seed))
        assert p == [0, 1, 3, 5, 7]
    # endpoints 0 and 7 are not relays and still route


def test_non_relay_node_is_reached_but_not_expanded():
    relay = [True, False, True, True, True, True, True, True]
    dist, _ = bfs_counts(DIAMOND, 0, relay)
    assert dist[1] == 1  # reachable as an endpoint
    p = shortest_path(DIAMOND, 0, 7, relay, random.Random(0))
    assert 1 not in p


def test_no_route_returns_none():
    relay = [True, False, False, True, True, True, True, True]
    assert shortest_path(DIAMOND, 0, 7, relay) is None
    assert disjoint_paths(DIAMOND, 0, 7, relay, 3) == []


@pytest.mark.parametrize("name", ["C12", "C20", "C24", "C60"])
def test_three_disjoint_paths_on_full_relay_cage(name):
    g = cage(name)
    rng = random.Random(2)
    for _ in range(30):
        s, d = rng.sample(range(g.n), 2)
        ps = disjoint_paths(g.adj, s, d, [True] * g.n, 3, rng)
        assert 1 <= len(ps) <= 3
        assert paths_are_node_disjoint(ps)
        for p in ps:
            assert p[0] == s and p[-1] == d
            assert all(b in g.adj[a] for a, b in zip(p, p[1:], strict=False))


def test_greedy_finds_three_paths_on_c60_full_relay_mostly():
    g = cage("C60")
    rng = random.Random(4)
    n3 = sum(
        len(disjoint_paths(g.adj, *rng.sample(range(60), 2), [True] * 60, 3, rng)) == 3
        for _ in range(100)
    )
    assert n3 >= 90


def test_direct_edge_used_at_most_once():
    g = cage("C12")
    s, d = 0, g.adj[0][0]
    ps = disjoint_paths(g.adj, s, d, [True] * 12, 3, random.Random(0))
    assert ps[0] == [s, d]
    assert sum(len(p) == 2 for p in ps) == 1
    assert len(ps) == 3 and paths_are_node_disjoint(ps)


def test_k_limits_path_count():
    g = cage("C60")
    for k in (1, 2):
        assert len(disjoint_paths(g.adj, 0, 59, [True] * 60, k, random.Random(0))) == k


def test_paths_are_node_disjoint_detects_overlap():
    assert not paths_are_node_disjoint([[0, 1, 2], [0, 1, 3, 2]])
    assert paths_are_node_disjoint([[0, 1, 2], [0, 3, 2]])


def test_token_bucket_burst_then_rate():
    b = TokenBucket(rate=10.0, burst=3.0)
    assert all(b.take(0.0, 1.0) for _ in range(3))
    assert not b.take(0.0, 1.0)
    assert b.take(0.1, 1.0)  # 0.1 s * 10/s = 1 token
    assert not b.take(0.1, 1.0)


def test_token_bucket_never_exceeds_burst_and_fractional_cost():
    b = TokenBucket(rate=10.0, burst=2.0)
    b.refill(100.0)
    assert b.tokens == 2.0
    assert all(b.take(100.0, 1 / 3) for _ in range(6))
    assert not b.take(100.0, 1 / 3)


def test_token_bucket_time_does_not_go_backwards():
    b = TokenBucket(rate=1.0, burst=1.0, t=5.0)
    assert b.take(5.0, 1.0)
    b.refill(4.0)
    assert b.tokens == 0.0 and b.t == 5.0
