import numpy as np
import pytest

from meshguard.selective import (
    apply_threshold,
    aurc,
    confidence,
    coverage_risk_curve,
    plot_coverage_risk,
    select_threshold,
)


def calibrated(n=50000, seed=0):
    rng = np.random.default_rng(seed)
    p = rng.random(n)
    return p, rng.random(n) < p


def test_confidence_values():
    np.testing.assert_allclose(confidence(np.array([0.0, 0.3, 0.5, 0.9])), [1, 0.7, 0.5, 0.9])


@pytest.mark.parametrize("seed", range(5))
def test_risk_goes_to_zero_as_coverage_goes_to_zero(seed):
    p, y = calibrated(seed=seed)
    c = coverage_risk_curve(p, y)
    assert c.risk[0] < 0.01
    small = c.coverage < 0.02
    assert small.any() and c.risk[small].max() < 0.02


def test_risk_increases_overall_with_coverage():
    p, y = calibrated()
    c = coverage_risk_curve(p, y)
    assert c.risk[-1] > c.risk[0]
    assert c.risk[len(c.risk) // 2] < c.risk[-1]


def test_full_coverage_risk_is_overall_error():
    p, y = calibrated(n=5000)
    c = coverage_risk_curve(p, y)
    assert c.coverage[-1] == 1.0
    assert c.risk[-1] == pytest.approx(((p > 0.5) != y).mean())


def test_coverage_is_ascending_and_thresholds_descending():
    p, y = calibrated(n=3000)
    c = coverage_risk_curve(p, y)
    assert (np.diff(c.coverage) > 0).all() and (np.diff(c.thresholds) < 0).all()


def test_ties_are_grouped():
    p = np.array([0.9, 0.9, 0.9, 0.6, 0.6])
    y = np.array([1, 1, 0, 1, 0])
    c = coverage_risk_curve(p, y)
    np.testing.assert_allclose(c.coverage, [0.6, 1.0])
    np.testing.assert_allclose(c.risk, [1 / 3, 2 / 5])


@pytest.mark.parametrize("max_risk", [0.01, 0.05, 0.1, 0.2])
def test_selected_threshold_meets_risk_on_same_data(max_risk):
    p, y = calibrated()
    sel = select_threshold(p, y, max_risk)
    assert sel.risk <= max_risk
    assert sel.coverage > 0


def test_selection_is_maximal_coverage():
    p, y = calibrated(n=4000)
    sel = select_threshold(p, y, 0.05)
    c = coverage_risk_curve(p, y)
    worse = c.coverage > sel.coverage
    assert (c.risk[worse] > 0.05).all()


def test_looser_risk_gives_more_coverage():
    p, y = calibrated()
    assert select_threshold(p, y, 0.2).coverage > select_threshold(p, y, 0.02).coverage


def test_perfect_model_full_coverage():
    y = np.array([0, 1] * 50)
    p = np.where(y == 1, 0.99, 0.01)
    sel = select_threshold(p, y, 0.05)
    assert sel.coverage == 1.0 and sel.risk == 0.0


def test_infeasible_returns_empty_selection():
    p = np.full(10, 0.9)
    y = np.zeros(10)
    sel = select_threshold(p, y, 0.05)
    assert sel.coverage == 0.0 and np.isinf(sel.threshold)


def test_apply_threshold_matches_selection_on_same_data():
    p, y = calibrated(n=5000)
    sel = select_threshold(p, y, 0.05)
    again = apply_threshold(p, y, sel.threshold)
    assert again.coverage == pytest.approx(sel.coverage)
    assert again.risk == pytest.approx(sel.risk)


def test_apply_threshold_generalises_roughly():
    p, y = calibrated(n=60000, seed=1)
    sel = select_threshold(p[:30000], y[:30000], 0.05)
    held = apply_threshold(p[30000:], y[30000:], sel.threshold)
    assert held.risk < 0.07


def test_apply_infinite_threshold_accepts_nothing():
    p, y = calibrated(n=100)
    assert apply_threshold(p, y, float("inf")).coverage == 0.0


def test_aurc_better_for_better_model():
    rng = np.random.default_rng(0)
    y = rng.random(5000) < 0.5
    good = np.clip(y + rng.normal(0, 0.3, 5000), 0, 1)
    bad = rng.random(5000)
    assert aurc(coverage_risk_curve(good, y)) < aurc(coverage_risk_curve(bad, y))


@pytest.mark.parametrize("bad", [-0.1, 1.5])
def test_invalid_max_risk(bad):
    with pytest.raises(ValueError):
        select_threshold(np.array([0.5]), np.array([1]), bad)


def test_mismatched_lengths_raise():
    with pytest.raises(ValueError):
        coverage_risk_curve(np.array([0.5, 0.6]), np.array([1]))


def test_plot_coverage_risk_writes_png(tmp_path):
    p, y = calibrated(n=2000)
    c = coverage_risk_curve(p, y)
    out = tmp_path / "cr.png"
    plot_coverage_risk({"m": c}, out, 0.05, select_threshold(p, y, 0.05))
    assert out.exists() and out.stat().st_size > 1000
