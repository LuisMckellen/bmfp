import numpy as np
import pytest

from meshguard import dawid_skene as ds
from meshguard.isolation import (
    ACC_THRESHOLD,
    K_WINDOWS,
    WINDOW,
    ZONE_SIZE,
    inject_rogue,
    isolate,
    n_zones,
)
from meshguard.labeling import LF_NAMES, VoteMatrix, build_vote_matrix
from meshguard.simulator import simulate


def synthetic_vm(t=400, n=20, accs=(0.95, 0.9, 0.9, 0.85, 0.85, 0.8), seed=0, prior=0.2):
    """Independent LFs on random per-example truth; returns (VoteMatrix, truth)."""
    rng = np.random.default_rng(seed)
    y = rng.random((t, n)) < prior
    truth = np.where(y, 1, -1)
    cols = []
    for a in accs:
        v = np.where(rng.random((t, n)) < a, truth, -truth).astype(np.int8)
        cols.append(v)
    votes = np.stack(cols, axis=-1).reshape(t * n, len(accs))
    names = [f"lf{j}" for j in range(len(accs))]
    return VoteMatrix(votes, names, t, n), y.reshape(-1)


def test_n_zones():
    assert n_zones(20) == 4 and n_zones(21) == 5 and n_zones(5) == 1


def test_inject_rogue_flips_only_target():
    vm, _ = synthetic_vm(t=100)
    r = inject_rogue(vm, "lf2", zone=1, from_step=40)
    a, b = vm.tensor, r.tensor
    nodes = np.arange(5, 10)
    np.testing.assert_array_equal(b[40:, nodes, 2], -a[40:, nodes, 2])
    np.testing.assert_array_equal(b[:40], a[:40])
    other = np.setdiff1d(np.arange(20), nodes)
    np.testing.assert_array_equal(b[:, other], a[:, other])
    np.testing.assert_array_equal(
        np.delete(b[:, nodes], 2, axis=2), np.delete(a[:, nodes], 2, axis=2)
    )


def test_inject_rogue_does_not_mutate_original():
    vm, _ = synthetic_vm(t=100)
    before = vm.votes.copy()
    inject_rogue(vm, "lf0", 0, 10)
    np.testing.assert_array_equal(vm.votes, before)


def test_inject_rogue_bad_zone():
    vm, _ = synthetic_vm(t=100)
    with pytest.raises(ValueError):
        inject_rogue(vm, "lf0", zone=9, from_step=0)


def test_clean_synthetic_has_no_quarantine():
    vm, y = synthetic_vm()
    res = isolate(vm, y)
    assert res.quarantined() == []
    assert (res.weights == 1.0).mean() > 0.97


@pytest.mark.parametrize("zone", [0, 1, 2, 3])
@pytest.mark.parametrize("lf", ["lf0", "lf3", "lf5"])
def test_injected_rogue_is_quarantined_on_synthetic(zone, lf):
    vm, y = synthetic_vm()
    rogue = inject_rogue(vm, lf, zone, from_step=100)
    res = isolate(rogue, y)
    q = res.quarantined()
    assert (lf, zone) in [(n, z) for n, z, _ in q]
    assert len(q) == 1


def test_quarantine_timing_is_k_windows_after_injection():
    vm, y = synthetic_vm()
    res = isolate(inject_rogue(vm, "lf0", 0, from_step=100), y)
    ((_, _, start_step),) = res.quarantined()
    assert start_step == 100 + K_WINDOWS * WINDOW


def test_quarantine_zeroes_weights_only_for_target_after_start():
    vm, y = synthetic_vm()
    res = isolate(inject_rogue(vm, "lf1", 2, from_step=100), y)
    w = res.weights.reshape(400, 20, 6)
    nodes = np.arange(10, 15)
    assert (w[175:, nodes, 1] == 0).all()
    assert (w[:175, nodes, 1] == 1).all()
    assert (np.delete(w[:, nodes], 1, axis=2) == 1).mean() > 0.95
    other = np.setdiff1d(np.arange(20), nodes)
    assert (w[:, other, 1] == 1).mean() > 0.95


def test_short_burst_below_k_windows_not_quarantined():
    vm, y = synthetic_vm()
    t = vm.tensor.copy()
    t[100 : 100 + 2 * WINDOW, :5, 0] *= -1  # only two bad windows
    bad = VoteMatrix(t.reshape(vm.votes.shape), vm.lf_names, vm.steps, vm.n_nodes)
    assert isolate(bad, y).quarantined() == []


def test_k_param_controls_sensitivity():
    vm, y = synthetic_vm()
    t = vm.tensor.copy()
    t[100 : 100 + 2 * WINDOW, :5, 0] *= -1
    bad = VoteMatrix(t.reshape(vm.votes.shape), vm.lf_names, vm.steps, vm.n_nodes)
    assert len(isolate(bad, y, k=2).quarantined()) == 1


def test_window_accuracy_nan_when_too_few_votes():
    vm, y = synthetic_vm(t=100)
    votes = np.zeros_like(vm.votes)
    sparse = VoteMatrix(votes, vm.lf_names, vm.steps, vm.n_nodes)
    res = isolate(sparse, y)
    assert np.isnan(res.window_accuracy).all() and res.quarantined() == []


def test_rogue_sensor_downweighted_next_window():
    vm, y = synthetic_vm()
    t = vm.tensor.copy()
    t[100:125, 7, :] *= -1  # sensor 7 wrong in window 4 only
    bad = VoteMatrix(t.reshape(vm.votes.shape), vm.lf_names, vm.steps, vm.n_nodes)
    res = isolate(bad, y)
    assert res.rogue_sensor[7, 4] and res.rogue_sensor[:, 4].sum() == 1
    w = res.weights.reshape(400, 20, 6)
    assert (w[125:150, 7] == 0.5).all()
    assert (w[100:125, 7] == 1.0).all()


def test_rogue_weight_one_disables_sensor_downweighting():
    vm, y = synthetic_vm()
    t = vm.tensor.copy()
    t[100:125, 7, :] *= -1
    bad = VoteMatrix(t.reshape(vm.votes.shape), vm.lf_names, vm.steps, vm.n_nodes)
    assert (isolate(bad, y, rogue_weight=1.0).weights == 1.0).all()


def test_weights_in_unit_interval():
    vm, y = synthetic_vm()
    res = isolate(inject_rogue(vm, "lf0", 0, 100), y)
    assert res.weights.min() >= 0 and res.weights.max() <= 1


def test_isolation_does_not_use_ground_truth_argument_name():
    # the only label-like input is `pseudo`; make sure it is positional and boolean-coerced
    vm, y = synthetic_vm(t=100)
    a = isolate(vm, y.astype(int))
    b = isolate(vm, y)
    np.testing.assert_array_equal(a.weights, b.weights)


def test_constants_match_spec():
    assert ZONE_SIZE == 5 and K_WINDOWS == 3 and ACC_THRESHOLD == 0.55


# --- integration: real simulator + real LFs + Dawid-Skene -----------------------------------


@pytest.fixture(scope="module")
def real():
    sim = simulate(seed=42)
    return build_vote_matrix(sim.readings)


def test_quarantine_fires_with_injected_rogue_end_to_end(real):
    rogue = inject_rogue(real, "range_check", zone=0, from_step=100)
    pseudo = ds.fit(rogue.votes).p_anomaly > 0.5
    res = isolate(rogue, pseudo)
    hits = [(n, z, s) for n, z, s in res.quarantined() if n == "range_check" and z == 0]
    assert hits, res.quarantined()
    assert hits[0][2] == 175


@pytest.mark.parametrize("lf", ["range_check", "neighbor_correlation", "stuck_value"])
def test_quarantine_fires_for_each_good_lf(real, lf):
    rogue = inject_rogue(real, lf, zone=0, from_step=100)
    pseudo = ds.fit(rogue.votes).p_anomaly > 0.5
    names = [n for n, z, _ in isolate(rogue, pseudo).quarantined() if z == 0]
    assert lf in names


def test_rogue_in_one_zone_does_not_quarantine_that_lf_elsewhere(real):
    rogue = inject_rogue(real, "range_check", zone=0, from_step=100)
    pseudo = ds.fit(rogue.votes).p_anomaly > 0.5
    zones = {z for n, z, _ in isolate(rogue, pseudo).quarantined() if n == "range_check"}
    assert zones == {0}


def test_isolation_names_cover_all_lfs(real):
    res = isolate(real, ds.fit(real.votes).p_anomaly > 0.5)
    assert res.lf_names == LF_NAMES
    assert res.quarantine_start.shape == (6, 4)
