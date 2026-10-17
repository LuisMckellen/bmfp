import numpy as np
import pytest
from scipy.special import expit

from meshguard.calibration import (
    IsotonicCalibrator,
    TemperatureScaler,
    ece,
    logit,
    nll,
    plot_reliability,
    reliability_curve,
)


def calibrated(n=60000, seed=0):
    rng = np.random.default_rng(seed)
    p = rng.random(n)
    return p, rng.random(n) < p


def overconfident(temp=3.0, n=30000, seed=0):
    """True logits z, model reports sigmoid(temp * z): overconfident for temp > 1."""
    rng = np.random.default_rng(seed)
    z = rng.normal(0, 1.5, n)
    y = rng.random(n) < expit(z)
    return expit(temp * z), y


# --- ECE ------------------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(5))
def test_ece_near_zero_when_calibrated(seed):
    p, y = calibrated(seed=seed)
    assert ece(p, y) < 0.01


@pytest.mark.parametrize("temp", [2.0, 3.0, 5.0])
def test_ece_large_when_overconfident(temp):
    p, y = overconfident(temp)
    assert ece(p, y) > 0.05


def test_ece_large_when_biased():
    p, y = calibrated()
    assert ece(np.clip(p + 0.2, 0, 1), y) > 0.05


def test_ece_perfect_predictions():
    y = np.array([0, 1, 1, 0])
    assert ece(y.astype(float), y) == 0.0


def test_ece_completely_wrong():
    y = np.array([0, 1, 1, 0])
    assert ece(1.0 - y, y) == pytest.approx(1.0)


def test_ece_constant_prediction_known_value():
    y = np.array([1, 0, 0, 0])
    assert ece(np.full(4, 0.5), y) == pytest.approx(0.25)


@pytest.mark.parametrize("bins", [5, 10, 15, 30])
def test_ece_bounds(bins):
    p, y = overconfident()
    assert 0.0 <= ece(p, y, bins) <= 1.0


def test_ece_prob_one_included():
    assert ece(np.array([1.0, 1.0]), np.array([1, 1])) == 0.0


def test_ece_matches_manual_computation():
    p = np.array([0.1, 0.2, 0.8, 0.9, 0.95])
    y = np.array([0, 1, 1, 1, 0])
    # 2 bins: [0, .5): p=.1,.2 -> conf .15, acc .5 ; [.5, 1]: .8,.9,.95 -> conf .8833, acc .6667
    expected = 2 / 5 * abs(0.5 - 0.15) + 3 / 5 * abs(2 / 3 - 0.88333333)
    assert ece(p, y, n_bins=2) == pytest.approx(expected)


@pytest.mark.parametrize(
    "p,y",
    [([0.5, 0.5], [1]), ([], []), ([1.2], [1]), ([-0.1], [0])],
)
def test_ece_rejects_bad_input(p, y):
    with pytest.raises(ValueError):
        ece(np.array(p), np.array(y))


# --- reliability curve ----------------------------------------------------------------------


def test_reliability_counts_sum_to_n():
    p, y = calibrated(n=1000)
    assert reliability_curve(p, y, 10).counts.sum() == 1000


def test_reliability_empty_bins_are_nan():
    c = reliability_curve(np.array([0.05, 0.06]), np.array([0, 1]), 10)
    assert np.isnan(c.accuracy[5]) and c.counts[0] == 2


def test_reliability_calibrated_close_to_diagonal():
    p, y = calibrated()
    c = reliability_curve(p, y, 10)
    assert np.nanmax(np.abs(c.accuracy - c.confidence)) < 0.05


def test_plot_reliability_writes_png(tmp_path):
    p, y = overconfident()
    out = tmp_path / "sub" / "r.png"
    value = plot_reliability(p, y, out, title="t")
    assert out.exists() and out.stat().st_size > 1000
    assert value == pytest.approx(ece(p, y))


# --- temperature scaling --------------------------------------------------------------------


@pytest.mark.parametrize("temp", [2.0, 3.0, 5.0])
def test_temperature_scaling_reduces_ece(temp):
    p, y = overconfident(temp)
    ts = TemperatureScaler().fit(p, y)
    assert ece(ts.transform(p), y) < ece(p, y)


@pytest.mark.parametrize("temp", [2.0, 3.0])
def test_temperature_recovered(temp):
    p, y = overconfident(temp, n=60000)
    assert TemperatureScaler().fit(p, y).temperature == pytest.approx(temp, rel=0.15)


def test_temperature_near_one_when_calibrated():
    p, y = calibrated()
    assert TemperatureScaler().fit(p, y).temperature == pytest.approx(1.0, abs=0.15)


def test_temperature_below_one_for_underconfident():
    p, y = overconfident(0.4)
    assert TemperatureScaler().fit(p, y).temperature < 1.0


def test_temperature_scaling_reduces_nll():
    p, y = overconfident(3.0)
    ts = TemperatureScaler().fit(p, y)
    assert nll(ts.transform(p), y) < nll(p, y)


def test_temperature_scaling_preserves_ranking():
    p, y = overconfident(3.0, n=2000)
    q = TemperatureScaler().fit(p, y).transform(p)
    order = np.argsort(p, kind="stable")
    assert (np.diff(q[order]) >= -1e-12).all()


def test_temperature_handles_extreme_probs():
    p = np.array([0.0, 1.0, 1e-12, 1 - 1e-12] * 50)
    y = np.array([0, 1, 1, 0] * 50)
    out = TemperatureScaler().fit(p, y).transform(p)
    assert np.isfinite(out).all() and ((out >= 0) & (out <= 1)).all()


# --- isotonic -------------------------------------------------------------------------------


def test_isotonic_reduces_ece_out_of_sample():
    p, y = overconfident(3.0, n=40000)
    iso = IsotonicCalibrator().fit(p[:20000], y[:20000])
    assert ece(iso.transform(p[20000:]), y[20000:]) < ece(p[20000:], y[20000:])


def test_isotonic_is_monotone():
    p, y = overconfident(3.0, n=5000)
    iso = IsotonicCalibrator().fit(p, y)
    grid = np.linspace(0, 1, 200)
    assert (np.diff(iso.transform(grid)) >= -1e-12).all()


def test_isotonic_outputs_in_unit_interval():
    p, y = overconfident(3.0, n=5000)
    out = IsotonicCalibrator().fit(p, y).transform(np.array([0.0, 0.5, 1.0]))
    assert ((out >= 0) & (out <= 1)).all()


def test_logit_clips():
    assert np.isfinite(logit(np.array([0.0, 1.0]))).all()
