import numpy as np
import pytest

from meshguard.simulator import (
    DEAD,
    DRIFTING,
    NORMAL,
    STUCK,
    Simulation,
    ring_neighbors,
    simulate,
)


@pytest.fixture(scope="module")
def sim() -> Simulation:
    return simulate(seed=42)


def regime_nodes(sim, regime):
    return [n for n in sim.truth.faulty_nodes if sim.truth.regimes[-1, n] == regime]


# --- determinism ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [0, 1, 7, 42, 123])
def test_same_seed_identical(seed):
    a, b = simulate(seed=seed), simulate(seed=seed)
    np.testing.assert_array_equal(a.readings.values, b.readings.values)
    np.testing.assert_array_equal(a.truth.regimes, b.truth.regimes)
    assert a.truth.onsets == b.truth.onsets


@pytest.mark.parametrize("seed", [0, 1, 7, 42])
def test_different_seed_differs(seed):
    a, b = simulate(seed=seed), simulate(seed=seed + 1)
    assert not np.array_equal(a.readings.values, b.readings.values, equal_nan=True)


# --- shape and structure -------------------------------------------------------------------


def test_default_shape(sim):
    assert sim.readings.values.shape == (500, 20)
    assert sim.truth.regimes.shape == (500, 20)
    assert sim.truth.labels.shape == (500, 20)


@pytest.mark.parametrize("n,t", [(4, 50), (10, 100), (20, 500), (33, 321)])
def test_custom_shape(n, t):
    s = simulate(seed=3, n_sensors=n, steps=t)
    assert s.readings.values.shape == (t, n)
    assert len(s.readings.neighbors) == n


@pytest.mark.parametrize("n", [4, 5, 20, 21])
def test_ring_topology(n):
    nb = ring_neighbors(n)
    for i, (left, right) in enumerate(nb):
        assert left == (i - 1) % n and right == (i + 1) % n
        assert i in nb[left] and i in nb[right]


def test_readings_expose_ring(sim):
    assert sim.readings.neighbors == ring_neighbors(20)


# --- ground truth --------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(10))
def test_at_least_two_faulty(seed):
    assert len(simulate(seed=seed).truth.faulty_nodes) >= 2


@pytest.mark.parametrize("seed", range(10))
def test_two_faulty_minimum_on_small_mesh(seed):
    assert len(simulate(seed=seed, n_sensors=6).truth.faulty_nodes) >= 2


@pytest.mark.parametrize("seed", range(10))
def test_all_four_regimes_present(seed):
    s = simulate(seed=seed)
    assert set(np.unique(s.truth.regimes)) == {NORMAL, DRIFTING, STUCK, DEAD}


def test_labels_match_regimes(sim):
    np.testing.assert_array_equal(sim.truth.labels, sim.truth.regimes != NORMAL)


def test_only_faulty_nodes_have_anomalies(sim):
    anomalous_nodes = np.where(sim.truth.labels.any(axis=0))[0]
    np.testing.assert_array_equal(anomalous_nodes, sim.truth.faulty_nodes)


def test_faulty_nodes_normal_before_onset(sim):
    for node, onset in sim.truth.onsets.items():
        assert (sim.truth.regimes[:onset, node] == NORMAL).all()
        assert (sim.truth.regimes[onset:, node] != NORMAL).all()


def test_onsets_in_valid_range(sim):
    for onset in sim.truth.onsets.values():
        assert 100 <= onset < 300


def test_anomaly_rate_is_modest(sim):
    assert 0.02 < sim.truth.labels.mean() < 0.3


# --- regime behaviour ----------------------------------------------------------------------


def test_stuck_is_constant(sim):
    for n in regime_nodes(sim, STUCK):
        seg = sim.readings.values[sim.truth.onsets[n] :, n]
        assert np.ptp(seg) == 0.0


def test_dead_is_nan(sim):
    for n in regime_nodes(sim, DEAD):
        assert np.isnan(sim.readings.values[sim.truth.onsets[n] :, n]).all()


def test_drifting_diverges_from_neighbours(sim):
    for n in regime_nodes(sim, DRIFTING):
        onset = sim.truth.onsets[n]
        healthy = [m for m in range(20) if m not in sim.truth.onsets]
        ref = np.nanmean(sim.readings.values[:, healthy], axis=1)
        gap = sim.readings.values[:, n] - ref
        assert abs(gap[-20:].mean()) > 3 * abs(gap[:onset].std())
        assert gap[-1] > gap[onset]


def test_normal_nodes_are_noisy_and_finite_mostly(sim):
    healthy = [m for m in range(20) if m not in sim.truth.onsets]
    v = sim.readings.values[:, healthy]
    assert np.isnan(v).mean() < 0.01
    assert np.nanstd(np.diff(v, axis=0)) > 0.1


def test_healthy_ring_neighbours_correlated(sim):
    faulty = set(sim.truth.onsets)
    pairs = [(m, m + 1) for m in range(19) if m not in faulty and m + 1 not in faulty]
    v = sim.readings.values
    assert pairs
    for a, b in pairs[:3]:
        ok = ~(np.isnan(v[:, a]) | np.isnan(v[:, b]))
        assert np.corrcoef(v[ok, a], v[ok, b])[0, 1] > 0.9


def test_value_range_plausible_for_healthy(sim):
    healthy = [m for m in range(20) if m not in sim.truth.onsets]
    v = sim.readings.values[:, healthy]
    assert np.nanmin(v) > 5 and np.nanmax(v) < 35


# --- validation ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs", [{"n_sensors": 3}, {"steps": 10}, {"fault_frac": 0.0}, {"fault_frac": 0.9}]
)
def test_invalid_args_raise(kwargs):
    with pytest.raises(ValueError):
        simulate(**kwargs)
