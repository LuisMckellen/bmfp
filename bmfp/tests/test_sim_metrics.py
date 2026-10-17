"""Hand-driven checks of the metrics the experiments and findings depend on, plus the
dead-source rule and the CDS invariant after every state-changing step."""

import pytest

from bmfp import events as ev
from bmfp.cell import ACTIVE, GHOST, STANDBY, components, is_cds
from bmfp.routing import CHILL, DUPLICATE
from bmfp.sim import FLAP_CYCLES, Config, Msg, Simulation, run


def quiet(**kw) -> Simulation:
    base = dict(cage="C60", duration=120.0, send_rate=0.0, resonance="off", vsepr="off")
    base.update(kw)
    return Simulation(Config(**base))


def non_stem_active(sim):
    return [v for v in sorted(sim.active_set()) if not sim.nodes[v].stem]


def msg(sim, src, dst, t=1.0):
    m = Msg(sim._next_mid, src, dst, 0, t, sim.nodes[dst].alive, 1, sim.nodes[src].incarnation)
    sim._next_mid += 1
    sim.msgs[m.id] = m
    sim.sent += 1
    return m


def queued(sim, kind):
    return [e for e in sim.q._heap if e[2] == kind]


def neighbours_active(sim):
    return next(
        (a, b) for a in sorted(sim.active_set()) for b in sim.adj[a] if b in sim.active_set()
    )


# --------------------------------------------------------------------------- dead sources
def test_retry_from_dead_source_is_dropped_without_sending():
    sim = quiet(link_loss=1.0)
    src, dst = neighbours_active(sim)
    m = msg(sim, src, dst)
    sim._attempt(m, 1.0)  # lost on the link: a resend is scheduled
    assert len(queued(sim, ev.RETRY)) == 1 and sim.attempts == 1
    tx0 = sim.tx
    sim.nodes[src].alive = False
    sim._on_retry(1.2, m.id)
    assert sim.drops["src_dead"] == 1 and m.id not in sim.msgs
    assert sim.tx == tx0 and sim.attempts == 1  # nothing was transmitted
    assert not queued(sim, ev.DELIVER)
    assert sim.series.dsent[1] == 1  # still a deliverable message that was not delivered


def test_retry_from_a_fresh_device_in_the_slot_is_dropped():
    sim = quiet(link_loss=1.0)
    src, dst = neighbours_active(sim)
    m = msg(sim, src, dst)
    sim._attempt(m, 1.0)
    sim.nodes[src] = sim._new_node(src, 1.1, STANDBY, sim.nodes[src].incarnation + 1)
    sim._on_retry(1.2, m.id)
    assert sim.drops["src_dead"] == 1


def test_churn_never_delivers_from_a_dead_source():
    class Watch(Simulation):
        bad = 0

        def _attempt(self, m, t):
            if not self.nodes[m.src].alive:
                n0 = len(queued(self, ev.DELIVER))
                super()._attempt(m, t)
                self.bad += len(queued(self, ev.DELIVER)) - n0
                return
            super()._attempt(m, t)

    sim = Watch(Config(seed=1, duration=200.0, churn_rate=0.3, link_loss=0.15))
    s = sim.run().summary
    assert sim.bad == 0 and s["drops_src_dead"] > 0
    assert s["sent"] == s["delivered"] + s["drops_total"]


# --------------------------------------------------------------------------- arrival
@pytest.mark.parametrize("latency", [0.005, 0.02])
def test_deliver_time_is_attempt_time_plus_hops_times_hop_latency(latency):
    sim = quiet(cage="C12", active_fraction=1.0, hop_latency=latency)
    dist = sim._bfs(0)[0]
    dst = dist.index(max(dist))
    hops = dist[dst]
    sim._attempt(msg(sim, 0, dst, t=2.0), 2.0)
    (t, _, _, (mid, h)) = queued(sim, ev.DELIVER)[0]
    assert h == hops and t == pytest.approx(2.0 + hops * latency)
    sim._on_deliver(t, (mid, h))
    assert sim.latencies == [pytest.approx(hops * latency)]


# --------------------------------------------------------------------------- utilisation
def test_util_prev_is_demand_over_capacity_times_relays():
    sim = quiet(routing="adaptive_duplicate", relay_capacity=40.0)
    n_relay = len(sim.active_set())
    sim.bin_demand = 123.0
    sim._on_bin(1.0, 0)
    assert sim.util_prev == pytest.approx(123.0 / (40.0 * n_relay))
    assert sim.bin_demand == 0.0  # the next bin starts from zero


def test_adaptive_mode_switches_strictly_above_threshold():
    sim = quiet(routing="adaptive_duplicate", adaptive_threshold=0.9)
    sim.util_prev = 0.9
    assert sim._mode() == CHILL
    sim.util_prev = 0.9000001
    assert sim._mode() == DUPLICATE


def test_util_prev_counts_relayed_load_only():
    sim = quiet(cage="C12", active_fraction=1.0)
    sim._attempt(msg(sim, 0, sim.adj[0][0]), 1.0)  # one hop: no relay involved
    assert sim.bin_demand == 0.0
    dist = sim._bfs(0)[0]
    far = dist.index(3)
    sim._attempt(msg(sim, 0, far), 1.0)  # three hops: two relays
    assert sim.bin_demand == pytest.approx(2.0)


# --------------------------------------------------------------------------- flaps
def test_flap_is_a_reversal_within_two_vsepr_cycles():
    sim = quiet()
    a, b, c = non_stem_active(sim)[:3]
    window = FLAP_CYCLES * sim.cfg.vsepr_period
    sim.set_state(a, GHOST, 30.0, "vsepr")
    sim.set_state(a, ACTIVE, 30.0 + window, "vsepr_repair")  # at the edge: a flap
    assert sim.flaps == 1 and sim.vsepr_flaps == 1
    sim.set_state(b, STANDBY, 30.0, "resonance")
    sim.set_state(b, ACTIVE, 30.0 + window + 0.1, "resonance")  # too late: not a flap
    assert sim.flaps == 1
    sim.set_state(c, STANDBY, 40.0, "resonance")
    sim.set_state(c, ACTIVE, 50.0, "resonance")  # a flap, but VSEPR made neither move
    assert sim.flaps == 2 and sim.vsepr_flaps == 1


def test_recovery_moves_are_not_flaps():
    sim = quiet()
    a = non_stem_active(sim)[0]
    sim.set_state(a, GHOST, 30.0, "vsepr")
    sim.set_state(a, ACTIVE, 31.0, "recovery")
    assert sim.flaps == 0


# --------------------------------------------------------------------------- change rates
def test_state_change_rates_count_active_boundary_crossings_per_source():
    sim = quiet(duration=120.0)  # 2 minutes
    a, b, c = non_stem_active(sim)[:3]
    g = [v for v in range(60) if sim.nodes[v].state == GHOST][:2]
    sim.set_state(a, GHOST, 30.0, "vsepr")  # crossing (vsepr)
    sim.set_state(g[0], ACTIVE, 30.0, "vsepr_repair")  # crossing (vsepr, via repair)
    sim.set_state(b, STANDBY, 35.0, "resonance")  # crossing (resonance)
    sim.set_state(g[1], STANDBY, 60.0, "fairness")  # no crossing: GHOST -> STANDBY
    sim.set_state(c, STANDBY, 70.0, "recovery")  # crossing, but not a rotation source
    s = sim.result().summary
    assert s["state_changes_per_min"] == pytest.approx(3 / 2)
    assert s["state_changes_per_min_vsepr"] == pytest.approx(2 / 2)
    assert s["state_changes_per_min_vsepr_repair"] == pytest.approx(1 / 2)
    assert s["state_changes_per_min_resonance"] == pytest.approx(1 / 2)
    assert s["fairness_moves_per_min"] == pytest.approx(1 / 2)
    assert s["all_state_changes_per_min"] == pytest.approx(4 / 2)
    assert s["recovery_state_changes"] == 1


# --------------------------------------------------------------------------- shares
def test_ghost_time_share_and_share_to_asleep_in_a_frozen_cell():
    # no VSEPR tick before t = 30 and no resonance: the states never change
    sim = Simulation(Config(duration=25.0, resonance="off", vsepr="off", seed=4, send_rate=30.0))
    n_ghost = sum(1 for nd in sim.nodes if nd.state == GHOST)
    s = sim.run().summary
    assert s["ghost_time_share"] == pytest.approx(n_ghost / 60)
    assert s["sent"] > 0
    assert s["share_to_asleep"] == pytest.approx(s["drops_dst_asleep"] / s["sent"])


# --------------------------------------------------------------------------- cycle loads
def test_cycle_load_ratio_peak_and_average():
    sim = quiet()
    act = sorted(sim.active_set())
    for v in act:
        sim.nodes[v].window_load = 3.0
    hot = non_stem_active(sim)[0]
    sim.nodes[hot].window_load = 30.0
    sim._on_vsepr(30.0, None)
    avg = (3.0 * (len(act) - 1) + 30.0) / len(act)
    s = sim.result().summary
    assert s["mean_max_avg_load_ratio"] == pytest.approx(30.0 / avg)
    assert s["mean_peak_relay_load"] == pytest.approx(30.0 / 30.0)  # per second of the cycle
    assert s["mean_avg_relay_load"] == pytest.approx(avg / 30.0)


def test_cycle_loads_none_without_relayed_traffic():
    s = quiet().result().summary
    assert s["mean_max_avg_load_ratio"] is None and s["mean_peak_relay_load"] is None


# --------------------------------------------------------------------------- CDS per step
class CdsChecked(Simulation):
    """Checks the CDS invariant over the believed view after every state-changing handler."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.checked = 0
        self.violations = []

    def _check(self, where):
        if not self.captain_alive():
            return  # no captain can act: the invariant is restored by the next one
        alive = self.believed_alive()
        act = self.active_set()
        for comp in components(self.adj, alive):
            if not is_cds(self.adj, act & set(comp), comp):
                self.violations.append((round(self.now, 3), where))
                return
        self.checked += 1


for _name in ("_on_vsepr", "_on_resonance", "_on_detect", "_on_mitosis", "_on_meiosis", "_on_join"):

    def _wrap(name):
        orig = getattr(Simulation, name)

        def f(self, t, p):
            orig(self, t, p)
            self._check(name)

        return f

    setattr(CdsChecked, _name, _wrap(_name))


@pytest.mark.parametrize(
    "kw",
    [
        dict(),
        dict(vsepr="damped"),
        dict(kill_at=60.0, kill_fraction=0.5),
        dict(kill_at=60.0, kill_fraction=0.6),
        dict(kill_at=60.0, kill_fraction=1.0),
        dict(churn_rate=0.1),
        dict(cage="C20", churn_rate=0.05),
    ],
)
def test_cds_holds_after_every_state_changing_step(kw):
    sim = CdsChecked(Config(seed=2, duration=200.0, **kw))
    sim.run()
    assert sim.checked > 5 and sim.violations == []


# --------------------------------------------------------------------------- outcome bins
def test_outcome_seconds_count_total_death_as_unserved():
    res = run(duration=140.0, kill_at=120.0, kill_fraction=1.0, seed=1)
    o = res.extra["outcome_seconds"]
    assert len(o["t"]) == len(o["ratio"]) == len(o["offered"]) == 140
    for b in (121, 122, 123):  # every node dead, nothing respawned yet
        assert o["offered"][b] > 0 and o["ratio"][b] == 0.0
    assert o["ratio"][110] == 1.0
    assert sum(o["served"]) == res.summary["deliverable_delivered"]
