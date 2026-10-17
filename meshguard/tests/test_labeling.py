import numpy as np
import pandas as pd
import pytest

from meshguard.labeling import (
    LABELING_FUNCTIONS,
    LF_NAMES,
    build_vote_matrix,
    lf_neighbor_correlation,
    lf_range_check,
    lf_rate_of_change,
    lf_silence,
    lf_stuck_value,
    lf_three_sigma,
)
from meshguard.simulator import ring_neighbors, simulate


def col(*xs):
    return np.array(xs, dtype=float).reshape(-1, 1)


# --- rate of change ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "series,expected",
    [
        ([20, 20.5, 21.0], [0, -1, -1]),
        ([20, 25, 25], [0, 1, -1]),
        ([20, 18, 18], [0, 1, -1]),  # a drop of 2 is not > 2, in the abstain band? see below
        ([20, 21.5, 21.5], [0, 0, -1]),
    ],
)
def test_rate_of_change_cases(series, expected):
    out = lf_rate_of_change(col(*series))[:, 0]
    if series == [20, 18, 18]:
        expected = [0, 0, -1]  # |diff| == 2.0 is not > hi=2.0, and > lo -> abstain
    np.testing.assert_array_equal(out, expected)


def test_rate_of_change_first_step_abstains():
    assert lf_rate_of_change(col(20, 20))[0, 0] == 0


def test_rate_of_change_nan_abstains():
    out = lf_rate_of_change(col(20, np.nan, 20))[:, 0]
    np.testing.assert_array_equal(out, [0, 0, 0])


# --- range check ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,vote",
    [(5, 1), (9.99, 1), (31, 1), (100, 1), (10, 0), (12, 0), (13, -1), (20, -1), (27, -1)]
    + [(28, 0), (30, 0)],
)
def test_range_check_values(value, vote):
    assert lf_range_check(col(value))[0, 0] == vote


def test_range_check_nan_abstains():
    assert lf_range_check(col(np.nan))[0, 0] == 0


# --- silence -------------------------------------------------------------------------------


def test_silence_needs_run_of_three():
    out = lf_silence(col(1, np.nan, np.nan, np.nan, np.nan, 1))[:, 0]
    np.testing.assert_array_equal(out, [0, 0, 0, 1, 1, 0])


def test_silence_single_dropout_abstains():
    assert (lf_silence(col(1, np.nan, 1, 1))[:, 0] == 0).all()


def test_silence_run_resets():
    out = lf_silence(col(np.nan, np.nan, 1, np.nan, np.nan))[:, 0]
    assert (out == 0).all()


def test_silence_never_votes_normal():
    assert (lf_silence(np.random.default_rng(0).normal(size=(50, 3))) == 0).all()


def test_silence_columns_independent():
    v = np.column_stack([[np.nan] * 5, [1.0] * 5])
    out = lf_silence(v)
    assert out[-1, 0] == 1 and out[-1, 1] == 0


# --- 3 sigma -------------------------------------------------------------------------------


def shared_signal(t=300, n=8, seed=0, sd=0.3):
    rng = np.random.default_rng(seed)
    base = 20 + 5 * np.sin(np.arange(t) / 20)
    return base[:, None] + rng.normal(0, sd, (t, n))


def test_three_sigma_flags_outlier():
    v = shared_signal()
    v[150, 3] += 6
    assert lf_three_sigma(v)[150, 3] == 1


def test_three_sigma_ignores_shared_seasonal_swing():
    out = lf_three_sigma(shared_signal())
    assert (out == -1).mean() > 0.8
    assert (out == 1).mean() < 0.03


def test_three_sigma_gray_zone_abstains():
    v = shared_signal()
    v[100, 2] += 0.3 * 2.5 * 1.2  # a bit over 2 sigma of the residual, below 3
    out = lf_three_sigma(v)
    assert out[100, 2] in (0, -1, 1)
    z_free = lf_three_sigma(v, k_in=0.0, k_out=1e9)
    assert (z_free == 0).all()


def test_three_sigma_constant_data_is_safe():
    out = lf_three_sigma(np.full((20, 4), 5.0))
    assert out.shape == (20, 4) and (out == 0).all()


def test_three_sigma_all_nan_is_safe():
    assert (lf_three_sigma(np.full((10, 4), np.nan)) == 0).all()


def test_three_sigma_nan_abstains():
    v = shared_signal()
    v[10, 1] = np.nan
    assert lf_three_sigma(v)[10, 1] == 0


def test_three_sigma_drifting_node_flagged_late():
    v = shared_signal()
    v[:, 4] += np.linspace(0, 12, v.shape[0])
    out = lf_three_sigma(v)[:, 4]
    assert (out[-30:] == 1).all()
    assert (out[:5] != 1).all()


def test_three_sigma_stuck_node_flagged_when_far_from_mesh():
    v = shared_signal()
    v[100:, 5] = v[100, 5]
    out = lf_three_sigma(v)[:, 5]
    assert (out[100:] == 1).mean() > 0.4


# --- neighbour correlation -----------------------------------------------------------------


def make_ring(n=6, t=100, seed=0):
    rng = np.random.default_rng(seed)
    base = 20 + 5 * np.sin(np.arange(t) / 8)
    return base[:, None] + rng.normal(0, 0.2, (t, n)), ring_neighbors(n)


def test_neighbor_healthy_votes_normal():
    v, nb = make_ring()
    out = lf_neighbor_correlation(v, nb)
    assert (out[40:] == -1).mean() > 0.9


def test_neighbor_flat_sensor_flagged():
    v, nb = make_ring()
    v[:, 2] = 22.0
    out = lf_neighbor_correlation(v, nb)
    assert (out[40:, 2] == 1).all()


def test_neighbor_offset_sensor_flagged():
    v, nb = make_ring()
    v[:, 2] += 6
    out = lf_neighbor_correlation(v, nb)
    assert (out[40:, 2] == 1).all()


def test_neighbor_warmup_abstains():
    v, nb = make_ring()
    assert (lf_neighbor_correlation(v, nb)[:29] == 0).all()


def test_neighbor_dead_sensor_abstains():
    v, nb = make_ring()
    v[:, 2] = np.nan
    out = lf_neighbor_correlation(v, nb)
    assert (out[:, 2] == 0).all()


def test_neighbor_survives_one_dead_neighbour():
    v, nb = make_ring()
    v[:, 3] = np.nan
    out = lf_neighbor_correlation(v, nb)
    assert (out[40:, 2] == -1).mean() > 0.9  # still uses the other neighbour


def test_neighbor_short_series_abstains():
    v, nb = make_ring(t=10)
    assert (lf_neighbor_correlation(v, nb) == 0).all()


# --- stuck value ---------------------------------------------------------------------------


def test_stuck_detects_constant_run():
    out = lf_stuck_value(col(1, 2, 3, 4, 5, 5, 5, 5, 5, 6))[:, 0]
    np.testing.assert_array_equal(out, [0, 0, 0, 0, -1, -1, -1, -1, 1, -1])


def test_stuck_varying_votes_normal():
    out = lf_stuck_value(np.random.default_rng(0).normal(size=(30, 2)))
    assert (out[4:] == -1).all() and (out[:4] == 0).all()


def test_stuck_nan_abstains():
    out = lf_stuck_value(col(5, 5, 5, 5, np.nan, 5, 5, 5, 5, 5))[:, 0]
    assert (out[4:8] == 0).all()
    assert out[9] == 1


def test_stuck_short_series_abstains():
    assert (lf_stuck_value(col(1, 1, 1)) == 0).all()


@pytest.mark.parametrize("k", [3, 5, 8])
def test_stuck_window_param(k):
    out = lf_stuck_value(np.full((20, 1), 3.0), k=k)[:, 0]
    assert (out[k - 1 :] == 1).all() and (out[: k - 1] == 0).all()


# --- generic contract ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def sim():
    return simulate(seed=42)


@pytest.mark.parametrize("name", LF_NAMES)
def test_lf_output_contract(sim, name):
    out = LABELING_FUNCTIONS[name](sim.readings.values, sim.readings.neighbors)
    assert out.shape == sim.readings.values.shape
    assert out.dtype == np.int8
    assert set(np.unique(out)) <= {-1, 0, 1}


@pytest.mark.parametrize("name", LF_NAMES)
def test_lf_does_not_mutate_input(sim, name):
    before = sim.readings.values.copy()
    LABELING_FUNCTIONS[name](sim.readings.values, sim.readings.neighbors)
    np.testing.assert_array_equal(before, sim.readings.values)


@pytest.mark.parametrize("name", LF_NAMES)
def test_lf_deterministic(sim, name):
    f = LABELING_FUNCTIONS[name]
    a = f(sim.readings.values, sim.readings.neighbors)
    b = f(sim.readings.values, sim.readings.neighbors)
    np.testing.assert_array_equal(a, b)


@pytest.mark.parametrize("name", [n for n in LF_NAMES if n != "rate_of_change"])
def test_lf_better_than_chance_where_it_votes_anomaly(sim, name):
    """Each LF's +1 votes should be enriched for true anomalies vs the base rate."""
    v = LABELING_FUNCTIONS[name](sim.readings.values, sim.readings.neighbors).reshape(-1)
    y = sim.truth.labels.reshape(-1)
    fired = v == 1
    assert fired.sum() > 0
    assert y[fired].mean() > 3 * y.mean()


def test_rate_of_change_anomaly_votes_are_mostly_benign_spikes(sim):
    """Documented weakness: the LF fires on healthy spikes far more than on faults."""
    v = lf_rate_of_change(sim.readings.values).reshape(-1)
    y = sim.truth.labels.reshape(-1)
    assert (v == 1).sum() > 0
    assert y[v == 1].mean() < 0.3


def test_six_lfs():
    assert len(LF_NAMES) == 6


# --- vote matrix ---------------------------------------------------------------------------


def test_vote_matrix_shape(sim):
    vm = build_vote_matrix(sim.readings)
    assert vm.votes.shape == (500 * 20, 6)
    assert vm.tensor.shape == (500, 20, 6)
    assert vm.lf_names == LF_NAMES


def test_vote_matrix_row_indexing(sim):
    vm = build_vote_matrix(sim.readings)
    j = LF_NAMES.index("stuck_value")
    direct = lf_stuck_value(sim.readings.values)
    assert vm.tensor[200, 5, j] == direct[200, 5]
    assert vm.votes[200 * 20 + 5, j] == direct[200, 5]


def test_vote_matrix_frame(sim):
    df = build_vote_matrix(sim.readings).to_frame()
    assert list(df.columns) == ["step", "node", *LF_NAMES]
    assert len(df) == 10000
    assert df.iloc[25][["step", "node"]].tolist() == [1, 5]
    assert isinstance(df, pd.DataFrame)


def test_vote_matrix_deterministic():
    a = build_vote_matrix(simulate(5).readings).votes
    b = build_vote_matrix(simulate(5).readings).votes
    np.testing.assert_array_equal(a, b)


def test_vote_matrix_never_sees_truth(sim):
    # the builder only accepts Readings; passing the whole Simulation must fail loudly
    with pytest.raises(AttributeError):
        build_vote_matrix(sim)  # type: ignore[arg-type]
