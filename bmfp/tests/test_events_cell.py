import itertools
import random

import pytest

from bmfp import events as ev
from bmfp.cell import (
    ACTIVE,
    GHOST,
    STANDBY,
    STATE_CHARS,
    Node,
    components,
    find_swap,
    is_cds,
    repair_cds,
    undominated,
)
from bmfp.topology import cage, stem_triple


# --------------------------------------------------------------------------- events
def test_queue_orders_by_time():
    q = ev.EventQueue()
    q.push(3.0, ev.SEND, "c")
    q.push(1.0, ev.SEND, "a")
    q.push(2.0, ev.SEND, "b")
    assert [q.pop()[3] for _ in range(3)] == ["a", "b", "c"]


def test_queue_ties_break_by_insertion():
    q = ev.EventQueue()
    for i, kind in enumerate((ev.VSEPR, ev.KILL, ev.BIN, ev.SEND)):
        q.push(5.0, kind, i)
    out = [q.pop() for _ in range(4)]
    assert [o[3] for o in out] == [0, 1, 2, 3]
    assert [o[1] for o in out] == sorted(o[1] for o in out)


def test_queue_rejects_unknown_kind_and_nan():
    q = ev.EventQueue()
    with pytest.raises(ValueError):
        q.push(1.0, "TELEPORT")
    with pytest.raises(ValueError):
        q.push(float("nan"), ev.SEND)


def test_queue_len_bool_peek_and_counter():
    q = ev.EventQueue()
    assert not q and len(q) == 0 and q.peek_time() is None
    q.push(2.0, ev.BIN)
    q.push(1.0, ev.BIN)
    assert q and len(q) == 2 and q.peek_time() == 1.0 and q.pushed == 2
    q.pop()
    q.pop()
    with pytest.raises(IndexError):
        q.pop()


def test_all_spec_event_kinds_exist():
    for k in (
        "SEND RETRY DELIVER RESONANCE VSEPR CHECKPOINT CAPTAIN_TERM KILL LEAVE DETECT "
        "DEATH_EVENT MITOSIS_DONE MEIOSIS_DONE JOIN BIN"
    ).split():
        assert k in ev.KINDS


# --------------------------------------------------------------------------- cell / CDS
def test_state_flag_values_match_journal_v17c():
    assert (GHOST, ACTIVE, STANDBY) == (0, 1, 2)
    assert STATE_CHARS == {ACTIVE: "A", STANDBY: "S", GHOST: "G"}


def test_node_defaults():
    nd = Node(id=4)
    assert nd.alive and nd.state == GHOST and not nd.stem
    assert nd.window_load == nd.total_load == 0.0 and nd.state_changes == 0


def test_cds_all_active_is_valid():
    g = cage("C20")
    assert is_cds(g.adj, range(20), range(20))


def test_cds_empty_active_is_invalid_and_empty_alive_valid():
    g = cage("C12")
    assert not is_cds(g.adj, [], range(12))
    assert is_cds(g.adj, [], [])


def test_cds_detects_undominated_node():
    g = cage("C12")
    # neighbourhood-free active set: node 0 and its neighbours not active
    active = set(range(12)) - {0, *g.adj[0]}
    assert 0 in undominated(g.adj, active, range(12))
    assert not is_cds(g.adj, active, range(12))


def test_cds_detects_disconnected_backbone():
    g = cage("C60")
    a = 0
    far = max(range(60), key=lambda v: len(set(g.adj[v]) & set(g.adj[a])) == 0 and v)
    active = {a, *g.adj[a], far, *g.adj[far]}
    # dominated or not, two separated stars are not connected
    assert not is_cds(g.adj, active, active | set(range(60)))


def test_cds_ignores_dead_nodes():
    g = cage("C12")
    alive = set(range(12)) - {0}
    active = set(range(12)) - {0}
    assert is_cds(g.adj, active, alive)


@pytest.mark.parametrize("name", ["C12", "C20", "C24", "C60"])
def test_repair_from_stems_gives_cds(name):
    g = cage(name)
    stems = set(stem_triple(name))
    promoted, ok = repair_cds(g.adj, stems, range(g.n), [0.0] * g.n)
    assert ok
    assert is_cds(g.adj, stems | set(promoted), range(g.n))
    assert len(set(promoted)) == len(promoted)
    assert not stems & set(promoted)


@pytest.mark.parametrize("name", ["C12", "C20", "C24", "C60"])
def test_cds_size_respects_cubic_lower_bound(name):
    g = cage(name)
    promoted, ok = repair_cds(g.adj, set(), range(g.n), [0.0] * g.n)
    assert ok
    assert len(promoted) >= (g.n - 2) / 2


def test_repair_is_deterministic():
    g = cage("C60")
    loads = [random.Random(3).random() for _ in range(60)]
    a = repair_cds(g.adj, {0}, range(60), loads)
    b = repair_cds(g.adj, {0}, range(60), loads)
    assert a == b


def test_repair_tie_break_prefers_lowest_load():
    g = cage("C12")
    loads = [1.0] * 12
    loads[7] = 0.0
    promoted, ok = repair_cds(g.adj, set(), range(12), loads)
    assert ok and promoted[0] == 7


def test_repair_reports_impossible_when_alive_set_split():
    g = cage("C60")
    alive = set(range(60)) - set(g.adj[0])  # node 0 is cut off
    promoted, ok = repair_cds(g.adj, set(), alive, [0.0] * 60)
    assert not ok
    act = set(promoted)
    # but every component still has its own dominating backbone
    for comp in components(g.adj, alive):
        assert is_cds(g.adj, act & set(comp), comp)


def test_repair_noop_on_valid_set():
    g = cage("C20")
    promoted, ok = repair_cds(g.adj, range(20), range(20), [0.0] * 20)
    assert promoted == [] and ok


def test_components_sorted_and_cover():
    g = cage("C12")
    comps = components(g.adj, [0, *g.adj[0], 11])
    assert sum(len(c) for c in comps) == 5
    assert comps == sorted(comps, key=lambda c: c[0])


def test_find_swap_result_is_always_a_cds():
    g = cage("C20")
    rng = random.Random(5)
    checked = 0
    for _ in range(40):
        seed = {rng.randrange(20)}
        base, _ = repair_cds(g.adj, seed, range(20), [rng.random() for _ in range(20)])
        active = seed | set(base) | set(rng.sample(range(20), rng.randrange(0, 4)))
        out = rng.choice(sorted(active))
        pool = [v for v in range(20) if v not in active]
        r = find_swap(g.adj, active, set(range(20)), out, pool)
        if r is not None:
            checked += 1
            assert is_cds(g.adj, (active - {out}) | {r}, range(20))
        else:
            for c in pool:
                assert not is_cds(g.adj, (active - {out}) | {c}, range(20))
    assert checked > 0


def test_find_swap_none_when_pool_empty():
    g = cage("C12")
    act = set(range(12))
    assert find_swap(g.adj, act, set(range(12)), 0, []) is None


def test_exhaustive_cds_small_matches_bound_argument():
    g = cage("C12")
    sizes = [
        k
        for k in range(1, 8)
        if any(is_cds(g.adj, c, range(12)) for c in itertools.combinations(range(12), k))
    ]
    assert min(sizes) >= 5  # (n - 2) / 2 for a cubic graph
