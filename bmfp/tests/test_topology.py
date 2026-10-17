import itertools
import math
import random

import pytest

from bmfp.cell import is_cds
from bmfp.topology import (
    CAGE_NAMES,
    CAGES,
    PHI,
    build_cage,
    cage,
    cage_facts,
    cds_search,
    diameter,
    faces,
    far_triple,
    is_connected,
    is_dominating,
    is_exact_partition,
    min_cds_exact,
    min_dominating_exact,
    min_vertex_cut,
    partition_probability,
    ring,
    stem_triple,
)

EXPECTED = {
    # name: (nodes, links, diameter, faces)
    "C12": (12, 18, 3, 8),
    "C20": (20, 30, 5, 12),
    "C24": (24, 36, 6, 14),
    "C60": (60, 90, 9, 32),
}


@pytest.mark.parametrize("name", CAGE_NAMES)
def test_node_and_link_counts(name):
    g = cage(name)
    n, links, _, _ = EXPECTED[name]
    assert g.n == n == len(g.adj) == len(g.coords)
    assert g.links == links == len(g.edges)


@pytest.mark.parametrize("name", CAGE_NAMES)
def test_three_regular(name):
    assert all(len(nb) == 3 for nb in cage(name).adj)


@pytest.mark.parametrize("name", CAGE_NAMES)
def test_connected(name):
    assert is_connected(cage(name).adj)


@pytest.mark.parametrize("name", CAGE_NAMES)
def test_diameter(name):
    assert diameter(cage(name).adj) == EXPECTED[name][2]


@pytest.mark.parametrize("name", CAGE_NAMES)
def test_euler_faces(name):
    g = cage(name)
    assert faces(g.n, g.links) == EXPECTED[name][3]


@pytest.mark.parametrize("name", CAGE_NAMES)
def test_min_vertex_cut_is_three(name):
    assert min_vertex_cut(cage(name).adj) == 3


@pytest.mark.parametrize("name", CAGE_NAMES)
def test_single_and_double_failures_never_partition(name):
    g = cage(name)
    for k in (1, 2):
        for combo in itertools.combinations(range(g.n), k):
            assert is_connected(g.adj, combo), (name, combo)


@pytest.mark.parametrize("name", CAGE_NAMES)
def test_removing_a_neighbourhood_isolates_the_node(name):
    g = cage(name)
    for v in range(g.n):
        assert not is_connected(g.adj, g.adj[v])


@pytest.mark.parametrize("name", CAGE_NAMES)
def test_coordinates_on_unit_sphere_and_edges_equal_length(name):
    g = cage(name)
    for c in g.coords:
        assert math.isclose(sum(x * x for x in c), 1.0, rel_tol=1e-9)
    lengths = [math.dist(g.coords[i], g.coords[j]) for i, j in g.edges]
    assert max(lengths) - min(lengths) < 1e-9


@pytest.mark.parametrize("name", CAGE_NAMES)
def test_edges_sorted_pairs_and_adjacency_consistent(name):
    g = cage(name)
    assert list(g.edges) == sorted(g.edges)
    for i, j in g.edges:
        assert i < j
        assert j in g.adj[i] and i in g.adj[j]
    assert all(list(nb) == sorted(nb) for nb in g.adj)


def test_registry_and_lookup():
    assert set(CAGES) == set(CAGE_NAMES) == {"C12", "C20", "C24", "C60"}
    assert cage("C60") is CAGES["C60"]
    with pytest.raises(KeyError):
        cage("C70")


def test_node_ids_deterministic_under_input_order():
    pts = [(1.0, 1.0, 1.0), (1.0, -1.0, -1.0), (-1.0, 1.0, -1.0), (-1.0, -1.0, 1.0)]
    a = build_cage("T", pts)
    b = build_cage("T", list(reversed(pts)))
    assert a == b
    assert a.links == 6  # tetrahedron: everyone at the same distance


def test_c60_hexagon_pentagon_counts_via_euler():
    # 12 pentagons + 20 hexagons: 5*12 + 6*20 = 2 * 90 edge-face incidences
    g = cage("C60")
    assert faces(g.n, g.links) == 12 + 20
    assert 5 * 12 + 6 * 20 == 2 * g.links


def test_golden_ratio_constant():
    assert math.isclose(PHI * PHI, PHI + 1)


def test_partition_probability_exact_small_k():
    g = cage("C12")
    assert partition_probability(g, 1) == 0.0
    assert partition_probability(g, 2) == 0.0
    # exact: 12 neighbourhoods isolate a node; others may also cut
    p3 = partition_probability(g, 3)
    assert p3 >= 12 / math.comb(12, 3)
    assert is_exact_partition(12, 3)


def test_partition_probability_monte_carlo_is_seeded():
    g = cage("C60")
    assert not is_exact_partition(60, 4)
    a = partition_probability(g, 4, trials=500, rng=random.Random(7))
    b = partition_probability(g, 4, trials=500, rng=random.Random(7))
    assert a == b
    assert 0.0 <= a <= 0.1


def test_partition_probability_c60_k3_is_exact_and_matches_closed_form():
    # in C60 (cubic, girth 5) the only 3-node cuts are the 60 node neighbourhoods
    g = cage("C60")
    assert is_exact_partition(60, 3) and is_exact_partition(24, 6) and is_exact_partition(20, 6)
    assert partition_probability(g, 3) == 60 / math.comb(60, 3)


def test_bitmask_partition_matches_plain_enumeration():
    g = cage("C20")
    for k in (3, 4):
        plain = sum(
            1 for c in itertools.combinations(range(g.n), k) if not is_connected(g.adj, c)
        ) / math.comb(g.n, k)
        assert partition_probability(g, k) == plain


def test_exact_cds_and_dominating_sets():
    assert min_cds_exact(cage("C12").adj, 1, 12) == 6
    assert min_cds_exact(cage("C20").adj, 1, 20) == 10
    # Figure 6 draws the 12-node cell as a ring: 4 nodes dominate it, a backbone needs 10
    r = ring(12)
    assert min_dominating_exact(r) == 4 and min_cds_exact(r, 1, 12) == 10
    assert is_dominating(r, (0, 3, 6, 9)) and not is_cds(r, (0, 3, 6, 9), range(12))
    # brute force agrees on C12
    adj = cage("C12").adj
    best = min(
        k
        for k in range(1, 13)
        if any(is_cds(adj, c, range(12)) for c in itertools.combinations(range(12), k))
    )
    assert best == 6


def test_cds_search_is_an_upper_bound_with_forced_nodes():
    g = cage("C60")
    stems = stem_triple("C60")
    a = cds_search(g.adj, stems, 50, random.Random("x"))
    b = cds_search(g.adj, stems, 50, random.Random("x"))
    assert a == b and 29 <= a <= 32  # never below the (n - 2) / 2 floor


def test_partition_probability_edge_cases():
    g = cage("C12")
    assert partition_probability(g, 0) == 0.0
    assert partition_probability(g, 11) == 0.0


def test_cage_facts():
    f = cage_facts(cage("C60"))
    assert f == {
        "cage": "C60",
        "solid": "truncated icosahedron",
        "n": 60,
        "links": 90,
        "degree": 3,
        "diameter": 9,
        "min_vertex_cut": 3,
        "faces": 32,
    }


def test_stem_triple_maximises_spread():
    g = cage("C60")
    a, b, c = stem_triple("C60")
    from bmfp.topology import bfs_dist

    d = [bfs_dist(g.adj, x) for x in (a, b, c)]
    spread = min(d[0][b], d[0][c], d[1][c])
    # no other triple has a larger minimum pairwise distance
    assert spread >= 6
    assert far_triple(g.adj) == (a, b, c)
    assert len({a, b, c}) == 3


def test_is_connected_trivial_cases():
    g = cage("C12")
    assert is_connected(g.adj, range(11))
    assert is_connected(g.adj, range(12))
