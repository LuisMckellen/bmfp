"""Dawid-Skene label model, hand-written EM in NumPy (binary class, 3-way votes).

Each labeling function j has a class-conditional confusion matrix
``confusion[j, y, c] = P(vote category c | true class y)`` over the vote categories
(-1, 0, +1), so abstention is modelled as informative rather than ignored. Optional
per-(example, LF) weights scale each vote's contribution to both the E- and M-step; a
weight of 0 removes the vote (used by failure-domain isolation).

Label switching is avoided by initialising from the vote-average posterior, which fixes
class 1 to "the side the +1 votes point to".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import expit, logsumexp

CATEGORIES = (-1, 0, 1)  # index 0 -> -1 (normal), 1 -> 0 (abstain), 2 -> +1 (anomaly)


@dataclass(frozen=True)
class DSResult:
    p_anomaly: np.ndarray  # (M,) posterior P(y=1 | votes)
    prior: float  # P(y=1)
    confusion: np.ndarray  # (J, 2, 3)
    accuracy: np.ndarray  # (J,) accuracy among non-abstaining votes
    n_iter: int
    converged: bool


def _one_hot(votes: np.ndarray) -> np.ndarray:
    return np.stack([votes == c for c in CATEGORIES], axis=-1).astype(float)  # (M, J, 3)


def vote_average_posterior(votes: np.ndarray, weights: np.ndarray | None = None) -> np.ndarray:
    """Weighted mean of non-abstaining votes mapped to [0, 1]; 0.5 when all abstain."""
    w = np.ones(votes.shape) if weights is None else weights
    w = w * (votes != 0)
    total = w.sum(axis=1)
    mean = (w * votes).sum(axis=1) / np.where(total > 0, total, 1.0)
    return np.where(total > 0, (1.0 + mean) / 2.0, 0.5)


def accuracy_from_confusion(confusion: np.ndarray, prior: float) -> np.ndarray:
    """P(vote correct | vote not abstain) for each LF."""
    pi = np.array([1.0 - prior, prior])
    correct = pi[0] * confusion[:, 0, 0] + pi[1] * confusion[:, 1, 2]
    voted = (pi[:, None] * (confusion[:, :, 0] + confusion[:, :, 2]).T).sum(axis=0)
    return np.where(voted > 0, correct / np.where(voted > 0, voted, 1.0), 0.5)


def fit(
    votes: np.ndarray,
    weights: np.ndarray | None = None,
    max_iter: int = 500,
    tol: float = 1e-5,
    smoothing: float = 0.01,
) -> DSResult:
    """Run EM on a ``(M, J)`` matrix of votes in {-1, 0, +1}."""
    votes = np.asarray(votes)
    if votes.ndim != 2:
        raise ValueError("votes must be 2-D (examples, labeling functions)")
    if not np.isin(votes, CATEGORIES).all():
        raise ValueError("votes must be in {-1, 0, +1}")
    if weights is not None and weights.shape != votes.shape:
        raise ValueError("weights must match votes shape")
    if (weights is not None) and (weights < 0).any():
        raise ValueError("weights must be non-negative")

    onehot = _one_hot(votes)  # (M, J, 3)
    if weights is not None:
        onehot = onehot * weights[..., None]

    q = np.clip(vote_average_posterior(votes, weights), 0.02, 0.98)
    prior = 0.5
    confusion = np.full((votes.shape[1], 2, 3), 1.0 / 3.0)
    converged = False
    n_iter = 0
    for _ in range(max_iter):
        n_iter += 1
        # M-step
        prior = float(np.clip(q.mean(), 1e-3, 1 - 1e-3))
        for y, resp in ((0, 1.0 - q), (1, q)):
            counts = np.einsum("m,mjc->jc", resp, onehot) + smoothing
            confusion[:, y, :] = counts / counts.sum(axis=1, keepdims=True)
        # E-step
        log_conf = np.log(confusion)
        ll0 = np.einsum("mjc,jc->m", onehot, log_conf[:, 0, :]) + np.log(1.0 - prior)
        ll1 = np.einsum("mjc,jc->m", onehot, log_conf[:, 1, :]) + np.log(prior)
        q_new = np.exp(ll1 - logsumexp(np.stack([ll0, ll1]), axis=0))
        delta = float(np.max(np.abs(q_new - q)))
        q = q_new
        if delta < tol:
            converged = True
            break

    return DSResult(
        p_anomaly=q,
        prior=prior,
        confusion=confusion.copy(),
        accuracy=accuracy_from_confusion(confusion, prior),
        n_iter=n_iter,
        converged=converged,
    )


def majority_vote_probability(votes: np.ndarray) -> np.ndarray:
    """Baseline: vote average mapped to [0, 1]."""
    return vote_average_posterior(np.asarray(votes))


def logit(p: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    p = np.clip(p, eps, 1 - eps)
    return np.log(p) - np.log1p(-p)


__all__ = ["DSResult", "fit", "majority_vote_probability", "logit", "expit"]
