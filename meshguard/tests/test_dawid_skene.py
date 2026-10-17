import numpy as np
import pytest

from meshguard.dawid_skene import (
    accuracy_from_confusion,
    fit,
    logit,
    majority_vote_probability,
    vote_average_posterior,
)


def synth(
    m=20000, accs=(0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6), prior=0.3, abstain=0.2, seed=0
):
    """Independent LFs with symmetric accuracy `acc` among non-abstaining votes."""
    rng = np.random.default_rng(seed)
    y = rng.random(m) < prior
    truth_vote = np.where(y, 1, -1)
    votes = np.zeros((m, len(accs)), dtype=np.int8)
    for j, a in enumerate(accs):
        correct = rng.random(m) < a
        v = np.where(correct, truth_vote, -truth_vote)
        v[rng.random(m) < abstain] = 0
        votes[:, j] = v
    return votes, y


# --- mandatory: accuracy recovery -----------------------------------------------------------


@pytest.mark.parametrize("seed", range(5))
def test_recovers_known_accuracies(seed):
    accs = np.array([0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6])
    votes, _ = synth(accs=tuple(accs), seed=seed)
    res = fit(votes)
    np.testing.assert_allclose(res.accuracy, accs, atol=0.05)


@pytest.mark.parametrize(
    "accs",
    [
        (0.9, 0.9, 0.9, 0.9, 0.9),
        (0.99, 0.8, 0.7, 0.9, 0.85, 0.75),
        (0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9),
        (0.97, 0.92, 0.88),
    ],
)
def test_recovers_accuracies_various_sets(accs):
    votes, _ = synth(accs=accs, seed=11)
    res = fit(votes)
    np.testing.assert_allclose(res.accuracy, accs, atol=0.05)


@pytest.mark.parametrize("prior", [0.1, 0.3, 0.5])
def test_recovers_accuracies_across_priors(prior):
    accs = (0.92, 0.88, 0.84, 0.8, 0.76, 0.72)
    votes, _ = synth(accs=accs, prior=prior, m=40000, seed=5)
    res = fit(votes)
    np.testing.assert_allclose(res.accuracy, accs, atol=0.05)
    assert abs(res.prior - prior) < 0.03


@pytest.mark.parametrize("abstain", [0.0, 0.4, 0.7])
def test_recovers_accuracies_across_abstain_rates(abstain):
    accs = (0.92, 0.88, 0.84, 0.8, 0.76, 0.72)
    votes, _ = synth(accs=accs, abstain=abstain, m=40000, seed=2)
    np.testing.assert_allclose(fit(votes).accuracy, accs, atol=0.05)


def test_recovers_asymmetric_confusion():
    rng = np.random.default_rng(3)
    m, prior = 30000, 0.25
    y = rng.random(m) < prior
    # P(+1 | y=1)=0.7, P(-1 | y=1)=0.1; P(+1 | y=0)=0.05, P(-1 | y=0)=0.8
    spec = [
        (0.7, 0.1, 0.05, 0.8),
        (0.6, 0.2, 0.1, 0.7),
        (0.8, 0.05, 0.02, 0.9),
        (0.5, 0.3, 0.1, 0.6),
    ]
    cols = []
    for p11, p1m, p01, p0m in spec:
        u = rng.random(m)
        pos = np.where(y, u < p11, u < p01)
        neg = np.where(y, (u >= p11) & (u < p11 + p1m), (u >= p01) & (u < p01 + p0m))
        cols.append(pos.astype(np.int8) - neg.astype(np.int8))
    res = fit(np.stack(cols, axis=1))
    for j, (p11, p1m, p01, p0m) in enumerate(spec):
        assert abs(res.confusion[j, 1, 2] - p11) < 0.05
        assert abs(res.confusion[j, 0, 0] - p0m) < 0.05
        assert abs(res.confusion[j, 0, 2] - p01) < 0.05
        assert abs(res.confusion[j, 1, 0] - p1m) < 0.05


# --- posterior quality ----------------------------------------------------------------------


def test_posterior_beats_best_single_lf():
    votes, y = synth(seed=1)
    res = fit(votes)
    acc_post = ((res.p_anomaly > 0.5) == y).mean()
    best_single = max(((votes[:, j] == 1) == y)[votes[:, j] != 0].mean() for j in range(8))
    assert acc_post > best_single


def test_posterior_at_least_as_good_as_majority_vote():
    votes, y = synth(seed=2)
    res = fit(votes)
    mv = majority_vote_probability(votes)
    assert ((res.p_anomaly > 0.5) == y).mean() >= ((mv > 0.5) == y).mean() - 0.002


def test_posterior_accuracy_high_on_clean_synthetic():
    votes, y = synth(seed=3)
    assert ((fit(votes).p_anomaly > 0.5) == y).mean() > 0.95


def test_recovers_prior():
    votes, _ = synth(prior=0.2, seed=4)
    assert abs(fit(votes).prior - 0.2) < 0.02


def test_no_label_switching_with_adversarial_lf():
    votes, y = synth(accs=(0.9, 0.9, 0.9, 0.9, 0.85), seed=6)
    res = fit(votes)
    assert ((res.p_anomaly > 0.5) == y).mean() > 0.9  # not inverted


def test_detects_bad_lf():
    votes, _ = synth(accs=(0.95, 0.9, 0.9, 0.9, 0.5), seed=7)
    res = fit(votes)
    assert res.accuracy[4] < 0.6 < res.accuracy[:4].min()


def test_accuracy_ordering_preserved():
    accs = (0.97, 0.9, 0.83, 0.76)
    votes, _ = synth(accs=accs, seed=8)
    assert np.all(np.diff(fit(votes).accuracy) < 0)


# --- structural properties ------------------------------------------------------------------


def test_outputs_valid_probabilities():
    votes, _ = synth(m=2000, seed=9)
    res = fit(votes)
    assert res.p_anomaly.shape == (2000,)
    assert ((res.p_anomaly >= 0) & (res.p_anomaly <= 1)).all()
    assert np.isfinite(res.p_anomaly).all()


def test_confusion_rows_sum_to_one():
    votes, _ = synth(m=2000, seed=9)
    np.testing.assert_allclose(fit(votes).confusion.sum(axis=2), 1.0)


def test_converges_on_clean_data():
    votes, _ = synth(seed=0)
    res = fit(votes)
    assert res.converged and res.n_iter < 500


def test_deterministic():
    votes, _ = synth(m=3000, seed=0)
    np.testing.assert_array_equal(fit(votes).p_anomaly, fit(votes).p_anomaly)


def test_all_abstain_rows_stay_near_prior_and_identical():
    votes, _ = synth(m=3000, seed=0)
    votes[:10] = 0
    res = fit(votes)
    assert np.ptp(res.p_anomaly[:10]) == 0.0
    assert abs(res.p_anomaly[0] - res.prior) < 0.15


def test_unanimous_rows_are_confident():
    votes, _ = synth(m=5000, seed=0)
    votes[0] = 1
    votes[1] = -1
    res = fit(votes)
    assert res.p_anomaly[0] > 0.95 and res.p_anomaly[1] < 0.05


def test_zero_weights_equal_dropping_column():
    votes, _ = synth(m=4000, seed=0)
    w = np.ones(votes.shape)
    w[:, 3] = 0.0
    a = fit(votes, weights=w)
    b = fit(np.delete(votes, 3, axis=1))
    np.testing.assert_allclose(a.p_anomaly, b.p_anomaly, atol=1e-4)


def test_unit_weights_equal_no_weights():
    votes, _ = synth(m=3000, seed=0)
    a = fit(votes, weights=np.ones(votes.shape))
    b = fit(votes)
    np.testing.assert_allclose(a.p_anomaly, b.p_anomaly, atol=1e-9)


def test_dropping_noisy_lf_does_not_hurt_much():
    votes, y = synth(accs=(0.95, 0.9, 0.9, 0.55), seed=0)
    w = np.ones(votes.shape)
    w[:, 3] = 0.0
    dropped = ((fit(votes, w).p_anomaly > 0.5) == y).mean()
    kept = ((fit(votes).p_anomaly > 0.5) == y).mean()
    assert dropped >= kept - 0.005


@pytest.mark.parametrize(
    "bad",
    [np.array([1, -1, 0]), np.array([[2, 0], [0, 0]]), np.array([[0.5, 0]])],
)
def test_invalid_votes_raise(bad):
    with pytest.raises(ValueError):
        fit(bad)


def test_invalid_weights_raise():
    votes = np.zeros((4, 2), dtype=int)
    with pytest.raises(ValueError):
        fit(votes, weights=np.ones((3, 2)))
    with pytest.raises(ValueError):
        fit(votes, weights=-np.ones((4, 2)))


# --- helpers --------------------------------------------------------------------------------


def test_vote_average_posterior_values():
    v = np.array([[1, 1, -1], [-1, -1, 0], [0, 0, 0], [1, 0, 0]])
    np.testing.assert_allclose(vote_average_posterior(v), [2 / 3, 0.0, 0.5, 1.0])


def test_accuracy_from_confusion_perfect():
    conf = np.array([[[1.0, 0, 0], [0, 0, 1.0]]])
    assert accuracy_from_confusion(conf, 0.3)[0] == pytest.approx(1.0)


def test_accuracy_from_confusion_never_votes():
    conf = np.array([[[0, 1.0, 0], [0, 1.0, 0]]])
    assert accuracy_from_confusion(conf, 0.3)[0] == pytest.approx(0.5)


def test_logit_roundtrip_and_clipping():
    p = np.array([0.1, 0.5, 0.9])
    np.testing.assert_allclose(1 / (1 + np.exp(-logit(p))), p)
    assert np.isfinite(logit(np.array([0.0, 1.0]))).all()
