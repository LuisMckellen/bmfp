"""One test (or more) per semantic rule of SPEC.md."""

import math
import random
import re

import pytest

from bmfp import events as ev
from bmfp.cell import ACTIVE, GHOST, STANDBY, is_cds
from bmfp.sim import Config, Msg, Simulation, run
from bmfp.topology import cage, stem_triple


def quiet(**kw) -> Simulation:
    """A cell with no traffic and no resonance, so rules can be driven by hand."""
    base = dict(cage="C60", duration=1000.0, send_rate=0.0, resonance="off")
    base.update(kw)
    return Simulation(Config(**base))


def removable(sim: Simulation) -> list[int]:
    """Non-stem ACTIVE nodes whose removal keeps the backbone valid."""
    act = sim.active_set()
    alive = sim.believed_alive()
    return [v for v in sorted(act) if not sim.nodes[v].stem and is_cds(sim.adj, act - {v}, alive)]


def states(sim: Simulation, st: int) -> list[int]:
    return [v for v in range(sim.n) if sim.believed[v] and sim.nodes[v].state == st]


# --------------------------------------------------------------------------- config
def test_config_rejects_bad_values():
    for bad in (
        dict(routing="flood"),
        dict(vsepr="hard"),
        dict(resonance="maybe"),
        dict(duration=0),
        dict(link_loss=1.5),
        dict(cage="C70"),
    ):
        with pytest.raises((ValueError, KeyError)):
            Config(**bad)


def test_config_provenance_labels_every_field():
    rows = Config.provenance()
    assert {r["name"] for r in rows} == set(Config().to_dict())
    labels = {r["name"]: r["src"] for r in rows}
    for journal in (
        "detect_delay",
        "mitosis_time",
        "meiosis_time",
        "checkpoint_period",
        "vsepr_period",
        "vsepr_factor",
        "captain_term",
        "stem_count",
    ):
        assert labels[journal].startswith("JOURNAL"), journal
    for assumed in ("send_rate", "relay_capacity", "hotspot_fraction", "rejoin_delay"):
        assert labels[assumed].startswith("ASSUMPTION"), assumed
    assert labels["vsepr_cooldown_cycles"] == "PROPOSED FIX"


# --------------------------------------------------------------------------- initial cell
def test_initial_cell_stems_cds_and_split():
    sim = quiet()
    assert sim.stems == sorted(stem_triple("C60"))
    assert all(sim.nodes[s].state == ACTIVE and sim.nodes[s].stem for s in sim.stems)
    act = sim.active_set()
    assert is_cds(sim.adj, act, range(60))
    assert len(act) >= round(0.35 * 60)
    rest = 60 - len(act)
    assert len(states(sim, STANDBY)) == round(0.3 * rest)  # a share of the remainder (spec)
    assert len(act) + len(states(sim, STANDBY)) + len(states(sim, GHOST)) == 60


@pytest.mark.parametrize("sf", [0.0, 0.3, 0.6, 1.0])
def test_standby_fraction_is_a_share_of_the_remainder(sf):
    sim = quiet(standby_fraction=sf)
    rest = 60 - len(sim.active_set())
    assert len(states(sim, STANDBY)) == round(sf * rest)
    assert len(states(sim, GHOST)) == rest - round(sf * rest)


def test_initial_active_fraction_binds_above_cds_floor():
    sim = quiet(active_fraction=0.8)
    assert len(sim.active_set()) == 48


def test_initial_captains_follow_rule_term0():
    sim = quiet()
    elig = [v for v in range(60) if sim.nodes[v].state != GHOST]
    assert sim.captains == sorted(elig[:3])


# --------------------------------------------------------------------------- VSEPR naive
def test_naive_demotes_above_twice_average_and_promotes_two_coldest_ghosts():
    sim = quiet(vsepr="naive")
    hot = removable(sim)[0]
    for v in sim.active_set():
        sim.nodes[v].window_load = 1.0
    sim.nodes[hot].window_load = 10.0
    ghosts = states(sim, GHOST)
    for i, g in enumerate(ghosts):
        sim.nodes[g].total_load = 100.0 + i
    c1, c2 = ghosts[-1], ghosts[-2]
    sim.nodes[c1].total_load, sim.nodes[c2].total_load = 0.1, 0.2
    n_before = len(sim.active_set())
    sim._on_vsepr(30.0, None)
    assert sim.demotions == 1 and sim.promotions == 2
    assert sim.nodes[hot].state == GHOST
    assert sim.nodes[c1].state == ACTIVE and sim.nodes[c2].state == ACTIVE
    assert len(sim.active_set()) >= n_before + 1  # 2 in, 1 out: the set grows
    assert any(e["kind"] == ev.VSEPR and f"node {hot}" in e["text"] for e in sim.events)


def test_naive_threshold_is_strictly_greater_than_factor_times_average():
    sim = quiet(vsepr="naive")
    act = sorted(sim.active_set())
    for v in act:
        sim.nodes[v].window_load = 1.0
    sim._on_vsepr(30.0, None)  # everybody exactly at the average
    assert sim.demotions == 0


def test_naive_has_no_hysteresis():
    sim = quiet(vsepr="naive")
    hot = removable(sim)[0]
    for v in sim.active_set():
        sim.nodes[v].window_load = 1.0
    sim.nodes[hot].window_load = 10.0
    sim.nodes[hot].promoted_cycle = 0  # promoted in the cycle that just ended
    sim._on_vsepr(30.0, None)
    assert sim.demotions == 1


def test_naive_falls_back_to_standby_when_no_ghost():
    sim = quiet(vsepr="naive")
    for g in states(sim, GHOST):
        sim.nodes[g].state = STANDBY
    sim.relay_version += 1
    hot = removable(sim)[0]
    for v in sim.active_set():
        sim.nodes[v].window_load = 1.0
    sim.nodes[hot].window_load = 10.0
    sb = states(sim, STANDBY)
    sim._on_vsepr(30.0, None)
    assert sim.promotions == 2
    assert sum(sim.nodes[v].state == ACTIVE for v in sb) >= 2


def test_stems_are_never_demoted():
    sim = quiet(vsepr="naive")
    for v in sim.active_set():
        sim.nodes[v].window_load = 0.1
    for s in sim.stems:
        sim.nodes[s].window_load = 100.0
    sim._on_vsepr(30.0, None)
    assert sim.demotions == 0
    assert all(sim.nodes[s].state == ACTIVE for s in sim.stems)


def test_window_load_reset_after_cycle():
    sim = quiet()
    for nd in sim.nodes:
        nd.window_load = 3.0
    sim._on_vsepr(30.0, None)
    assert all(nd.window_load == 0.0 for nd in sim.nodes)


def test_vsepr_off_still_runs_fairness_and_keeps_cds():
    sim = quiet(vsepr="off")
    hot = removable(sim)[0]
    for v in sim.active_set():
        sim.nodes[v].window_load = 1.0
    sim.nodes[hot].window_load = 50.0
    for t in (30.0, 60.0, 90.0):
        sim._on_vsepr(t, None)
    assert sim.demotions == 0
    assert sim.fairness_wakes > 0
    assert is_cds(sim.adj, sim.active_set(), sim.believed_alive())


# --------------------------------------------------------------------------- VSEPR damped
def _heat(sim, hot_nodes, hot=10.0):
    for v in sim.active_set():
        sim.nodes[v].window_load = 1.0
    for h in hot_nodes:
        sim.nodes[h].window_load = hot


def test_damped_keeps_active_count_constant_and_cds():
    sim = quiet(vsepr="damped")
    n0 = len(sim.active_set())
    _heat(sim, removable(sim)[:3])
    sim.cycle = 5  # past every cooldown
    sim._on_vsepr(180.0, None)
    assert sim.demotions >= 1
    assert sim.demotions == sim.promotions
    assert len(sim.active_set()) == n0
    assert is_cds(sim.adj, sim.active_set(), sim.believed_alive())


def test_damped_caps_demotions_per_cycle():
    sim = quiet(vsepr="damped", vsepr_max_demotions_frac=0.05)
    sim.cycle = 5
    act = sim.active_set()
    hot = [v for v in sorted(act) if not sim.nodes[v].stem]
    _heat(sim, hot[:12], hot=1.0)
    for v in sim.stems:
        sim.nodes[v].window_load = 0.0
    for v in act - set(hot[:12]):
        sim.nodes[v].window_load = 0.0
    sim._on_vsepr(180.0, None)
    assert sim.demotions <= math.ceil(0.05 * len(act))


def test_damped_skips_recently_promoted_candidates():
    sim = quiet(vsepr="damped")
    hot = removable(sim)[0]
    _heat(sim, [hot])
    sim.cycle = 5
    sim.nodes[hot].promoted_cycle = 5  # promoted one cycle before the next
    sim._on_vsepr(180.0, None)  # cycle 6: 6 - 5 = 1 <= 2
    assert sim.demotions == 0 and sim.nodes[hot].state == ACTIVE
    sim.nodes[hot].window_load = 10.0
    sim._on_vsepr(210.0, None)  # cycle 7: still within cooldown (2)
    assert sim.demotions == 0
    sim.nodes[hot].window_load = 10.0
    for v in sim.active_set() - {hot}:
        sim.nodes[v].window_load = 1.0
    sim._on_vsepr(240.0, None)  # cycle 8: cooldown over
    assert sim.demotions == 1


def test_damped_demoted_nodes_not_repromoted_during_cooldown():
    sim = quiet(vsepr="damped")
    sim.cycle = 5
    first = removable(sim)[0]
    _heat(sim, [first])
    sim._on_vsepr(180.0, None)
    assert sim.nodes[first].state == GHOST
    sim.nodes[first].total_load = -1.0  # now the coldest node in the cell
    second = [v for v in removable(sim) if v != first][0]
    _heat(sim, [second])
    sim._on_vsepr(210.0, None)
    assert sim.nodes[first].state != ACTIVE


def test_damped_full_run_active_count_never_changes_without_failures():
    res = run(cage="C60", duration=300.0, seed=2, vsepr="damped")
    assert len(set(res.series["active"])) == 1
    assert res.summary["active_fraction_end"] == res.summary["active_fraction_start"]


class CycleLog(Simulation):
    """Records, per VSEPR cycle, the demotions, promotions and the promotable pool."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.cycles = []

    def _on_vsepr(self, t, payload):
        pool = sum(1 for v in self.believed_alive() if self.nodes[v].state != ACTIVE)
        d0, p0, live = self.demotions, self.promotions, self.captain_alive()
        super()._on_vsepr(t, payload)
        self.cycles.append((self.demotions - d0, self.promotions - p0, pool, live))


def test_naive_full_run_promotes_vsepr_promote_per_demotion_and_inflates():
    sim = CycleLog(Config(cage="C60", duration=300.0, seed=2, vsepr="naive"))
    s = sim.run().summary
    assert s["demotions"] > 0
    for dem, pro, pool, live in sim.cycles:
        # exactly vsepr_promote per demotion, unless the GHOST+STANDBY pool runs dry
        assert pro == min(sim.cfg.vsepr_promote * dem, pool)
        assert live or dem == pro == 0
    assert any(dem and pro == 2 * dem for dem, pro, _, _ in sim.cycles)
    assert s["active_fraction_end"] > s["active_fraction_start"]


# --------------------------------------------------------------------------- fairness
def test_fairness_wakes_ghost_after_two_cycles_and_keeps_counts():
    sim = quiet(vsepr="off", standby_fraction=0.6)  # more STANDBY than GHOST: counts kept
    g = states(sim, GHOST)[0]
    n_ghost = len(states(sim, GHOST))
    assert n_ghost <= len(states(sim, STANDBY))
    sim._on_vsepr(30.0, None)  # one period [0, 30) completed as GHOST
    assert sim.nodes[g].state == GHOST and sim.nodes[g].ghost_streak == 1
    sim._on_vsepr(60.0, None)  # two periods completed: a third is not allowed
    assert sim.nodes[g].state == STANDBY
    assert len(states(sim, GHOST)) == n_ghost
    assert any("Fairness woke" in e["text"] for e in sim.events)


def test_fairness_without_enough_standby_wakes_all_and_shrinks_ghost_pool():
    sim = quiet(vsepr="off")  # 20 GHOST, 8 STANDBY: the swap cannot be one for one
    ghosts, standby = states(sim, GHOST), states(sim, STANDBY)
    assert len(ghosts) > len(standby)
    sim._on_vsepr(30.0, None)
    sim._on_vsepr(60.0, None)
    assert all(sim.nodes[v].state == STANDBY for v in ghosts)  # the journal rule wins
    assert sorted(states(sim, GHOST)) == sorted(standby)  # every STANDBY went to sleep
    sim._on_vsepr(90.0, None)
    sim._on_vsepr(120.0, None)
    assert len(states(sim, GHOST)) == len(standby)  # then counts are kept


def test_demoted_node_woken_two_cycles_later():
    sim = quiet(vsepr="naive", standby_fraction=0.6)
    hot = removable(sim)[0]
    _heat(sim, [hot])
    sim._on_vsepr(30.0, None)
    assert sim.nodes[hot].state == GHOST and sim.nodes[hot].ghost_streak == 0
    sim._on_vsepr(60.0, None)
    assert sim.nodes[hot].state == GHOST and sim.nodes[hot].ghost_streak == 1
    sim._on_vsepr(90.0, None)
    assert sim.nodes[hot].state == STANDBY


class GhostStay(Simulation):
    """Longest uninterrupted GHOST stay of any node, in seconds."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.since = {v: 0.0 for v in range(self.n) if self.nodes[v].state == GHOST}
        self.longest = 0.0

    def set_state(self, v, new, t, source):
        old = self.nodes[v].state
        super().set_state(v, new, t, source)
        if old != GHOST and new == GHOST:
            self.since[v] = t
        elif old == GHOST and new != GHOST and v in self.since:
            self.longest = max(self.longest, t - self.since.pop(v))

    def result(self):
        for t0 in self.since.values():
            self.longest = max(self.longest, self.cfg.duration - t0)
        return super().result()


@pytest.mark.parametrize("vsepr", ["naive", "damped", "off"])
def test_no_node_stays_ghost_more_than_two_cycles(vsepr):
    sim = GhostStay(Config(seed=1, duration=600.0, vsepr=vsepr))
    s = sim.run().summary
    assert s["skipped_cycles"] == 0
    limit = sim.cfg.fairness_max_ghost_cycles * sim.cfg.vsepr_period
    assert 0 < sim.longest <= limit + 1e-9


def test_fairness_sleeps_longest_awake_standby():
    sim = quiet(vsepr="off")
    sb = states(sim, STANDBY)
    for i, v in enumerate(sb):
        sim.nodes[v].awake_since = 50.0 + i
    oldest = sb[-1]
    sim.nodes[oldest].awake_since = -5.0
    for t in (30.0, 60.0, 90.0):
        sim._on_vsepr(t, None)
    assert sim.nodes[oldest].state == GHOST


# --------------------------------------------------------------------------- resonance
def test_resonance_swaps_hot_active_with_cold_standby_keeping_cds():
    sim = quiet(resonance="on")
    act = sim.active_set()
    for v in act:
        sim.nodes[v].window_load = 0.0
    n0 = len(act)
    sim._on_resonance(5.0, None)
    assert 1 <= sim.resonance_swaps_done <= 2
    assert len(sim.active_set()) == n0
    assert is_cds(sim.adj, sim.active_set(), sim.believed_alive())
    assert all(sim.nodes[s].state == ACTIVE for s in sim.stems)


def test_resonance_and_vsepr_skipped_without_live_captain():
    sim = quiet(resonance="on")
    for c in sim.captains:
        sim.nodes[c].alive = False
    sim._on_vsepr(30.0, None)
    sim._on_resonance(35.0, None)
    assert sim.skipped_cycles == 1 and sim.skipped_resonance == 1
    assert sim.vsepr_cycles == 0


def test_repair_needs_a_live_captain_like_every_captain_job():
    sim = quiet()
    hole = removable(sim)[0]
    sim.nodes[hole].state = STANDBY  # break nothing yet: the set is still a CDS
    sim.relay_version += 1
    for v in sorted(sim.active_set()):
        if not sim.nodes[v].stem and v not in sim.captains:
            sim.nodes[v].state = GHOST  # now the backbone is broken
    sim.relay_version += 1
    assert not is_cds(sim.adj, sim.active_set(), sim.believed_alive())
    for c in sim.captains:
        sim.nodes[c].alive = False  # dead but still in the (stale) view
    assert sim.repair(1.0, "recovery") == [] and sim.skipped_repairs == 1
    sim.nodes[sim.captains[0]].alive = True
    assert sim.repair(2.0, "recovery")
    assert is_cds(sim.adj, sim.active_set(), sim.believed_alive())


# --------------------------------------------------------------------------- captains
def test_captain_term_rotation_rule():
    sim = quiet()
    sim._on_term(300.0, None)
    assert sim.term == 1
    elig = [v for v in range(60) if sim.believed[v] and sim.nodes[v].state != GHOST]
    elig.sort(key=lambda v: ((v - 3) % 60, v))
    assert sim.captains == sorted(elig[:3])


def test_captain_reelected_immediately_on_detected_death():
    sim = quiet()
    dead = sim.captains[0]
    sim.nodes[dead].alive = False
    sim._on_detect(3.0, ("kill", [(dead, sim.nodes[dead].incarnation)]))
    assert dead not in sim.captains and len(sim.captains) == 3
    assert sim.captain_reelections == 1
    assert all(sim.believed[c] and sim.nodes[c].state != GHOST for c in sim.captains)


def test_dead_stem_replaced_by_lowest_load_active():
    sim = quiet()
    stem = sim.stems[0]
    others = sorted(v for v in sim.active_set() if not sim.nodes[v].stem)
    for i, v in enumerate(others):
        sim.nodes[v].total_load = 10.0 + i
    sim.nodes[others[-1]].total_load = 0.0
    sim.nodes[stem].alive = False
    sim._on_detect(3.0, ("kill", [(stem, 0)]))
    assert stem not in sim.stems and others[-1] in sim.stems and len(sim.stems) == 3


# --------------------------------------------------------------------------- failure
def test_detection_happens_after_detect_delay():
    early = Simulation(Config(duration=22.9, kill_at=20.0, kill_fraction=0.5, seed=3))
    early.run()
    dead = [v for v in range(60) if not early.nodes[v].alive]
    assert len(dead) == 30 and all(early.believed[v] for v in dead)
    late = Simulation(Config(duration=23.1, kill_at=20.0, kill_fraction=0.5, seed=3))
    late.run()
    assert not any(late.believed[v] for v in dead)
    assert late.incident["detect_t"] == pytest.approx(23.0)


def test_stale_view_drops_only_between_kill_and_detect():
    sim = Simulation(Config(duration=80.0, kill_at=20.0, kill_fraction=0.5, seed=1))
    res = sim.run()
    stale_bins = [b for (b, r), c in res.extra["fail_by_bin"].items() if r == "stale_view" and c]
    assert stale_bins, "a stale view must cost something"
    assert min(stale_bins) >= 20 and max(stale_bins) <= 23


def test_no_death_event_when_exactly_half_dies():
    s = run(duration=200.0, kill_at=120.0, kill_fraction=0.5, seed=1).summary
    assert s["killed"] == 30 and not s["death_event"] and s["path"] == "none"
    assert s["rto_journal_formula_s"] == 3.0


@pytest.mark.parametrize("frac,dies", [(0.5, False), (7 / 12, True)])
def test_death_threshold_is_strictly_more_than_half_c12(frac, dies):
    s = run(cage="C12", duration=60.0, kill_at=30.0, kill_fraction=frac, seed=1).summary
    assert s["death_event"] is dies


def test_partial_death_runs_mitosis_on_time():
    res = run(duration=150.0, kill_at=120.0, kill_fraction=0.6, seed=2)
    s = res.summary
    assert s["death_event"] and s["path"] == "mitosis" and s["death_events"] == 1
    t_m = [e["t"] for e in res.events if e["kind"] == ev.MITOSIS_DONE]
    assert t_m == [pytest.approx(120.0 + 3.0 + 1.5)]
    assert res.series["dead"][-1] == 0  # every vacant slot refilled


@pytest.mark.parametrize("detect,meio", [(3.0, 1.5), (2.0, 0.5)])
def test_total_death_runs_meiosis_at_detect_plus_meiosis_time(detect, meio):
    res = run(
        duration=60.0,
        kill_at=30.0,
        kill_fraction=1.0,
        seed=1,
        detect_delay=detect,
        meiosis_time=meio,
    )
    s = res.summary
    assert s["path"] == "meiosis" and s["death_event"]
    t_m = [e["t"] for e in res.events if e["kind"] == ev.MEIOSIS_DONE]
    assert t_m == [pytest.approx(30.0 + detect + meio)]
    assert s["rto_journal_formula_s"] == pytest.approx(detect + meio)
    assert s["first_delivery_after_kill_s"] >= detect + meio


def test_meiosis_restores_checkpoint_active_set():
    sim = Simulation(
        Config(
            duration=25.0,
            kill_at=20.0,
            kill_fraction=1.0,
            seed=4,
            checkpoint_phase=3.0,
            send_rate=5.0,
        )
    )
    sim.run()
    cp = sim.last_cp
    assert cp["t"] == pytest.approx(13.0)
    for v, st in enumerate(cp["states"]):
        if st == ACTIVE:
            assert sim.nodes[v].state == ACTIVE
    assert sim.stems == sorted(cp["stems"])
    assert sim.incident["path"] == "meiosis"
    assert sim.incident["rpo_s"] == pytest.approx(20.0 - 13.0)


def test_checkpoints_every_period_and_rpo():
    s = run(duration=100.0, checkpoint_phase=0.0, send_rate=1.0).summary
    assert s["checkpoints"] == 10
    s = run(duration=200.0, kill_at=120.0, kill_fraction=1.0, checkpoint_phase=3.0).summary
    assert s["rpo_s"] == pytest.approx(7.0)


def test_rpo_bounded_by_checkpoint_period_across_seeds():
    for seed in range(1, 6):
        s = run(duration=140.0, kill_at=120.0, kill_fraction=0.6, seed=seed).summary
        assert 0.0 <= s["rpo_s"] < 10.0


def test_no_checkpoint_while_cell_is_dead():
    sim = Simulation(
        Config(
            duration=24.0,
            kill_at=10.0,
            kill_fraction=1.0,
            checkpoint_phase=0.0,
            send_rate=1.0,
            meiosis_time=50.0,
        )
    )
    sim.run()
    assert sim.last_cp["t"] == pytest.approx(0.0)  # 10 s tick is after the kill (same time)
    assert sim.checkpoints == 1


def test_rejoin_refills_vacant_slots_after_delay():
    res = run(duration=160.0, kill_at=100.0, kill_fraction=0.5, seed=1, rejoin_delay=20.0)
    dead = res.series["dead"]
    assert dead[110] == 30 and dead[-1] == 0
    assert res.summary["joins"] == 30


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_kill_half_recovers_only_after_rejoin(seed):
    res = run(duration=300.0, kill_at=120.0, kill_fraction=0.5, seed=seed)
    s = res.summary
    assert s["refill_after_kill_s"] == pytest.approx(3.0 + 20.0)
    # service is back with the refill; it can lead it only by the ARQ window, when resends of
    # the last pre-refill messages succeed just after it (SPEC section 10)
    arq = Config().max_retries * Config().retry_timeout
    assert s["rto_service_s"] is not None
    assert s["rto_service_s"] >= s["refill_after_kill_s"] - arq - 1e-9
    # the believed survivors are split from detection until the batch rejoin
    assert s["view_split_s"] == pytest.approx(20.0)
    assert s["cds_impossible"] == 1  # one failed repair (at detection), not one per JOIN
    assert s["joins"] == 30
    assert sum(1 for e in res.events if e["kind"] == ev.JOIN) == 1


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_total_death_rto_not_before_first_delivery_or_respawn(seed):
    s = run(duration=300.0, kill_at=120.0, kill_fraction=1.0, seed=seed).summary
    assert s["path"] == "meiosis"
    assert s["rto_service_s"] >= s["first_delivery_after_kill_s"] - 1e-9
    assert s["rto_service_s"] >= s["refill_after_kill_s"]  # nothing can serve before respawn


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_partial_death_rto_not_before_detection_and_bounded_by_arq(seed):
    cfg = Config(duration=300.0, kill_at=120.0, kill_fraction=0.6, seed=seed)
    s = run(cfg).summary
    assert s["path"] == "mitosis"
    assert s["rto_service_s"] >= s["detect_time_s"]
    # only ARQ resends can carry service across the rebuild ahead of it
    arq = cfg.max_retries * cfg.retry_timeout
    assert s["rto_service_s"] >= s["refill_after_kill_s"] - arq
    assert s["view_split_s"] == pytest.approx(cfg.mitosis_time)


def test_detect_time_alias_matches_spec_name():
    s = run(duration=140.0, kill_at=120.0, kill_fraction=0.6, seed=1).summary
    assert s["detect_time"] == s["detect_time_s"] == pytest.approx(3.0)
    q = run(duration=20.0).summary
    assert q["detect_time"] is None and q["detect_time_s"] is None


def test_churn_leaves_and_joins():
    s = run(duration=200.0, churn_rate=0.2, seed=3).summary
    assert s["leaves"] > 10 and s["joins"] > 0
    assert s["drops_stale_view"] + s["drops_dst_dead"] > 0
    assert run(duration=50.0, churn_rate=0.0).summary["leaves"] == 0


# --------------------------------------------------------------------------- traffic
def _manual_msg(sim, src, dst, seq=0, t=1.0):
    m = Msg(sim._next_mid, src, dst, seq, t, sim.nodes[dst].alive, 1, sim.nodes[src].incarnation)
    sim._next_mid += 1
    sim.msgs[m.id] = m
    sim.sent += 1
    return m


def _delivers(sim):
    return [e for e in sim.q._heap if e[2] == ev.DELIVER]


def _all_active(routing, n="C12"):
    return quiet(cage=n, active_fraction=1.0, vsepr="off", routing=routing, path_rotation=True)


def _far_pair(sim):
    g = cage(sim.cfg.cage)
    from bmfp.topology import bfs_dist

    d = bfs_dist(g.adj, 0)
    return 0, d.index(max(d))


def test_duplicate_sends_full_copy_on_each_disjoint_path():
    sim = _all_active("duplicate")
    src, dst = _far_pair(sim)  # 3 hops apart in C12
    sim._attempt(_manual_msg(sim, src, dst), 1.0)
    assert sim.duplicates == 2  # 3 copies, the first arrival delivers
    assert sim.hell_paths == 3
    hops = _delivers(sim)[0][3][1]
    assert hops == 3  # the shortest copy arrives first
    assert sim.tx == int(sim.tx) and sim.tx >= 3 * 3  # one full copy per hop on every path


def test_stripe_fragments_cost_one_third_and_need_all():
    sim = _all_active("stripe")
    src, dst = _far_pair(sim)
    sim._attempt(_manual_msg(sim, src, dst), 1.0)
    assert sim.duplicates == 0 and sim.hell_paths == 3
    hops = _delivers(sim)[0][3][1]  # latency path = the longest fragment
    total_hops = sim.tx * 3  # each fragment hop costs 1/3
    assert total_hops == pytest.approx(round(total_hops))
    assert 3 <= sim.tx <= hops
    assert hops >= 3


def test_stripe_fails_when_one_fragment_dies_but_duplicate_survives():
    for routing, delivered in (("stripe", False), ("duplicate", True)):
        sim = _all_active(routing)
        src, dst = _far_pair(sim)
        victim = sim.adj[dst][0]
        sim.nodes[victim].alive = False  # still believed alive: stale view
        m = _manual_msg(sim, src, dst)
        sim._attempt(m, 1.0)
        assert bool(_delivers(sim)) is delivered, routing
        if not delivered:
            assert sim.fail_by_bin[(1, "stale_view")] == 1


def test_chill_uses_a_single_path():
    sim = _all_active("chill")
    src, dst = _far_pair(sim)
    sim._attempt(_manual_msg(sim, src, dst), 1.0)
    hops = _delivers(sim)[0][3][1]
    assert sim.tx == hops == 3 and sim.hell_attempts == 0


def test_dst_asleep_drop_has_no_transmissions():
    sim = quiet()
    g = states(sim, GHOST)[0]
    src = next(v for v in range(60) if v != g)
    sim._attempt(_manual_msg(sim, src, g), 1.0)
    assert sim.tx == 0 and sim.fail_by_bin[(1, "dst_asleep")] == 1


def test_arq_retries_until_max_then_drops():
    s = run(duration=30.0, link_loss=1.0, seed=1).summary
    assert s["delivered"] == 0
    assert s["attempts"] == 3 * s["sent"]
    assert s["retries"] == 2 * s["sent"]
    assert s["drops_link_loss"] + s["drops_dst_asleep"] + s["drops_no_route"] == s["sent"]
    s0 = run(duration=30.0, link_loss=1.0, seed=1, max_retries=0).summary
    assert s0["attempts"] == s0["sent"] and s0["retries"] == 0


def test_retry_scheduled_after_retry_timeout():
    sim = quiet(link_loss=1.0, retry_timeout=0.25)
    src, dst = next(
        (a, b) for a in sim.active_set() for b in sim.adj[a] if sim.nodes[b].state == ACTIVE
    )
    sim._attempt(_manual_msg(sim, src, dst), 2.0)
    retries = [e for e in sim.q._heap if e[2] == ev.RETRY]
    assert len(retries) == 1 and retries[0][0] == pytest.approx(2.25)


def test_out_of_order_counted_per_flow():
    sim = quiet()
    a = _manual_msg(sim, 1, 2, seq=0)
    b = _manual_msg(sim, 1, 2, seq=1)
    c = _manual_msg(sim, 3, 2, seq=0)
    sim._on_deliver(1.1, (b.id, 2))
    sim._on_deliver(1.2, (c.id, 2))
    sim._on_deliver(1.3, (a.id, 2))
    assert sim.out_of_order == 1 and sim.delivered == 3


def test_token_bucket_congestion_drops():
    s = run(duration=30.0, relay_capacity=1.0, relay_burst=1.0, send_rate=40.0, seed=2).summary
    assert s["drops_congestion"] > 0


def test_adaptive_switches_on_utilisation():
    hi = run(duration=30.0, routing="adaptive_duplicate", adaptive_threshold=-1.0).summary
    lo = run(duration=30.0, routing="adaptive_duplicate", adaptive_threshold=1e9).summary
    assert hi["hell_attempts"] > 0 and lo["hell_attempts"] == 0
    st = run(duration=30.0, routing="adaptive_stripe", adaptive_threshold=-1.0).summary
    assert st["hell_attempts"] > 0 and st["duplicates"] == 0


def test_hotspot_share_of_destinations():
    sim = Simulation(Config(duration=200.0, send_rate=50.0, hotspot_fraction=0.3, seed=5))
    sim.run()
    to_hot = sum(c for (s, d), c in sim.flows.items() if d == sim.hotspot)
    total = sum(sim.flows.values())
    assert abs(to_hot / total - (0.3 + 0.7 / 59)) < 0.02


def _run_with_route_stream(seed_text, **kw):
    sim = Simulation(Config(duration=60.0, seed=1, **kw))
    sim.route_rng = random.Random(seed_text)  # swap the stream that samples paths
    return sim.run().summary


def test_path_rotation_off_is_deterministic_regardless_of_route_stream():
    a = _run_with_route_stream("stream-a", path_rotation=False)
    b = _run_with_route_stream("stream-b", path_rotation=False)
    assert a == b  # lowest-id predecessors: the route stream is never read
    c = _run_with_route_stream("stream-a", path_rotation=True)
    d = _run_with_route_stream("stream-b", path_rotation=True)
    assert c != d  # with rotation the sampled paths (and so the loads) depend on it


def test_no_sends_from_a_fully_dead_cell():
    s = run(duration=140.0, kill_at=120.0, kill_fraction=1.0, seed=1).summary
    assert s["skipped_sends"] > 0
    assert s["sent"] == s["delivered"] + s["drops_total"]


# --------------------------------------------------------------------------- invariants
CONSERVATION_CASES = [
    dict(),
    dict(vsepr="damped"),
    dict(vsepr="off", resonance="off"),
    dict(routing="duplicate", link_loss=0.05),
    dict(routing="stripe", link_loss=0.05),
    dict(routing="adaptive_stripe", send_rate=80.0),
    dict(kill_at=40.0, kill_fraction=0.6),
    dict(kill_at=40.0, kill_fraction=1.0),
    dict(churn_rate=0.2),
    dict(churn_rate=0.5, link_loss=0.3),
    dict(cage="C20", relay_capacity=2.0),
]


@pytest.mark.parametrize("kw", CONSERVATION_CASES)
def test_conservation_sent_equals_delivered_plus_drops(kw):
    s = run(duration=80.0, seed=7, **kw).summary
    assert s["sent"] == s["delivered"] + s["drops_total"]
    assert s["deliverable_delivered"] <= s["deliverable_sent"] <= s["sent"]


@pytest.mark.parametrize("vsepr", ["naive", "damped", "off"])
def test_cds_invariant_holds_at_end(vsepr):
    s = run(duration=200.0, seed=3, vsepr=vsepr).summary
    assert s["cds_valid_end"] and s["cds_impossible"] == 0


def test_determinism_per_seed():
    a = run(duration=120.0, seed=11, kill_at=60.0, kill_fraction=0.6, record_frames=True)
    b = run(duration=120.0, seed=11, kill_at=60.0, kill_fraction=0.6, record_frames=True)
    assert a.summary == b.summary and a.series == b.series and a.events == b.events
    assert a.frames == b.frames
    c = run(duration=120.0, seed=12, kill_at=60.0, kill_fraction=0.6)
    assert c.summary != a.summary


def test_summary_keys_stable_across_configs():
    k1 = set(run(duration=20.0).summary)
    k2 = set(run(duration=40.0, kill_at=30.0, routing="stripe").summary)
    assert k1 == k2


def test_frames_shape_and_alphabet():
    res = run(duration=50.0, kill_at=20.0, kill_fraction=0.6, record_frames=True)
    f = res.frames
    assert len(f["states"]) == len(f["loads"]) == len(res.series["t"]) == 50
    assert all(len(s) == 60 and set(s) <= set("ASGD") for s in f["states"])
    assert all(len(s) == 60 and s.isdigit() for s in f["loads"])
    assert "D" in f["states"][21] and "D" not in f["states"][0]
    assert all(len(st) == 3 for st in f["stems"])
    assert len(f["captains"]) == 50


def test_series_counts_add_up():
    res = run(duration=60.0, kill_at=30.0, kill_fraction=0.5)
    s = res.series
    for i in range(60):
        assert s["active"][i] + s["standby"][i] + s["ghost"][i] + s["dead"][i] == 60
    assert sum(s["sent"]) == res.summary["sent"]
    assert sum(s["delivered"]) == res.summary["delivered"]


def test_simulation_runs_once():
    sim = quiet(duration=5.0)
    sim.run()
    with pytest.raises(RuntimeError):
        sim.run()


@pytest.mark.parametrize("frac,refill", [(0.5, 3.0 + 20.0), (0.6, 3.0 + 1.5), (1.0, 3.0 + 1.5)])
def test_refill_time_follows_recovery_path(frac, refill):
    s = run(duration=200.0, kill_at=120.0, kill_fraction=frac, seed=1).summary
    assert s["refill_after_kill_s"] == pytest.approx(refill)
    assert run(duration=30.0).summary["refill_after_kill_s"] is None


# --------------------------------------------------------------------------- review fixes
@pytest.mark.parametrize(
    "kw", [dict(standby_fraction=0.0), dict(standby_fraction=1.0), dict(active_fraction=0.8)]
)
def test_hotspot_and_checkpoint_phase_do_not_depend_on_the_initial_split(kw):
    """Their own random streams: changing the STANDBY share (E5's sweep) or the ACTIVE share
    must not change the popular node or the checkpoint phase (common random numbers)."""
    for seed in (1, 2, 3, 4, 5):
        base = Simulation(Config(seed=seed, duration=60.0, send_rate=0.0))
        other = Simulation(Config(seed=seed, duration=60.0, send_rate=0.0, **kw))
        assert other.hotspot == base.hotspot
        cp = lambda sim: [e[0] for e in sim.q._heap if e[2] == ev.CHECKPOINT]  # noqa: E731
        assert cp(other) == cp(base)


def test_resonance_event_names_node_ids_unambiguously():
    sim = quiet(resonance="on")
    for v in sim.active_set():
        sim.nodes[v].window_load = 0.0
    sim._on_resonance(5.0, None)
    txt = next(e["text"] for e in sim.events if e["kind"] == ev.RESONANCE)
    pairs = re.findall(r"node (\d+) \(ACTIVE->STANDBY\) with node (\d+) \(STANDBY->ACTIVE\)", txt)
    assert txt.startswith("Resonance swapped node ") and len(pairs) == sim.resonance_swaps_done
    for h, r in pairs:
        assert sim.nodes[int(h)].state == STANDBY and sim.nodes[int(r)].state == ACTIVE
    assert not re.search(r"\b\d+ (ACTIVE|STANDBY|GHOST)\s*->", txt)


def test_event_texts_tell_ids_from_counts():
    res = run(duration=200.0, kill_at=100.0, kill_fraction=0.5, seed=1)
    for e in res.events:
        # an id list always follows the word node(s); a count is always followed by a noun
        assert not re.search(r"\bpromoted \d", e["text"]), e
        assert not re.search(r"\bwoke \d", e["text"]), e
    join = next(e["text"] for e in res.events if e["kind"] == ev.JOIN)
    assert re.search(r"; \d+ nodes? promoted by CDS repair$", join)


def test_naive_inflates_active_even_with_one_promotion_per_demotion():
    """The inflation is not only the 2-for-1 rule: the promoted cold node rarely restores the
    backbone, so CDS repair promotes more and nothing shrinks the set."""
    s = run(duration=600.0, seed=1, vsepr="naive", vsepr_promote=1).summary
    assert s["promotions"] == s["demotions"] > 0  # the rule itself nets zero
    assert s["vsepr_repair_promotions"] > 0
    assert s["active_fraction_end"] > s["active_fraction_start"] + 0.1


def test_cell_average_reading_demotes_more():
    """v1.7d says 'cell average': read literally (sleeping nodes count with zero relayed
    load) the threshold is lower than the mean over ACTIVE relays."""
    sims = {}
    for avg in ("active", "cell"):
        sim = quiet(vsepr="naive", vsepr_average=avg)
        act = sorted(sim.active_set())
        for i, v in enumerate(act):
            sim.nodes[v].window_load = 1.0 + (i % 3)  # 1, 2, 3, ... mean 2 over ACTIVE
        sim._on_vsepr(30.0, None)
        sims[avg] = sim
    assert sims["active"].vsepr_candidates == 0  # 3 is not above 2 x 2
    assert sims["cell"].vsepr_candidates > 0  # the cell mean is diluted by GHOST/STANDBY
    with pytest.raises(ValueError):
        Config(vsepr_average="median")


def test_damped_counts_why_candidates_are_not_demoted():
    sim = quiet(vsepr="damped")
    act = sorted(sim.active_set())
    for v in act:
        sim.nodes[v].window_load = 1.0
    hot = [v for v in act if not sim.nodes[v].stem]
    for v in hot[:4]:
        sim.nodes[v].window_load = 50.0
    sim.nodes[hot[0]].promoted_cycle = 0  # in cooldown at cycle 1
    sim._on_vsepr(30.0, None)
    s = sim
    assert s.vsepr_candidates == 4
    accounted = s.demotions + s.vsepr_cooldown_skips + s.vsepr_no_swap + s.vsepr_capped
    assert accounted == s.vsepr_candidates
    assert s.vsepr_cooldown_skips == 1
    assert s.vsepr_no_swap_any <= s.vsepr_no_swap


def test_a_sleeping_captain_runs_no_captain_job():
    sim = quiet(resonance="on")
    for c in sim.captains:
        sim.nodes[c].state = GHOST  # elected awake, later sent to sleep
    sim.relay_version += 1
    assert not sim.captain_alive()
    sim._on_resonance(5.0, None)
    assert sim.skipped_resonance == 1
    sim.nodes[sim.captains[0]].state = STANDBY
    assert sim.captain_alive()


def test_messages_to_sleeping_devices_are_tracked_to_their_outcome():
    s = run(duration=300.0, seed=2).summary
    assert s["addressed_asleep"] == pytest.approx(s["share_to_asleep"] * s["sent"])
    assert 0.0 <= s["to_asleep_delivered_share"] < 0.2  # almost all are lost
    assert s["drops_dst_asleep"] <= s["addressed_asleep"] * 1.2


def test_unserved_series_counts_sends_with_no_live_sender():
    res = run(duration=140.0, kill_at=120.0, kill_fraction=1.0, seed=1)
    se, s = res.series, res.summary
    assert sum(se["unserved"]) == s["skipped_sends"] > 0
    assert all(u == 0 for t, u in zip(se["t"], se["unserved"], strict=True) if t < 120)
    assert sum(se["sent"]) == s["sent"]  # unserved sends are not in sent
