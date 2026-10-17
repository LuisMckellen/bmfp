"""Six heuristic labeling functions and the vote matrix.

Vote convention: +1 = anomaly, -1 = normal, 0 = abstain. Every LF maps the
``(T, N)`` reading array to a ``(T, N)`` int8 array. LFs never see ground truth.
Some thresholds are tuned by eye on the simulator's value ranges; they are
deliberately imperfect so the label model has something to learn.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from .simulator import Readings

ANOMALY, NORMAL_VOTE, ABSTAIN = 1, -1, 0

Neighbors = list[tuple[int, int]]


def lf_rate_of_change(
    values: np.ndarray, neighbors: Neighbors | None = None, hi: float = 2.0, lo: float = 1.0
) -> np.ndarray:
    """Large step-to-step jump -> anomaly; small jump -> normal."""
    jump = np.full(values.shape, np.nan)
    jump[1:] = np.abs(np.diff(values, axis=0))
    out = np.zeros(values.shape, dtype=np.int8)
    out[jump > hi] = ANOMALY
    out[jump <= lo] = NORMAL_VOTE
    return out


def lf_range_check(
    values: np.ndarray,
    neighbors: Neighbors | None = None,
    low: float = 10.0,
    high: float = 30.0,
    safe_low: float = 13.0,
    safe_high: float = 27.0,
) -> np.ndarray:
    """Physically implausible value -> anomaly; comfortably inside the band -> normal."""
    out = np.zeros(values.shape, dtype=np.int8)
    out[(values < low) | (values > high)] = ANOMALY
    out[(values >= safe_low) & (values <= safe_high)] = NORMAL_VOTE
    return out


def lf_silence(
    values: np.ndarray, neighbors: Neighbors | None = None, min_run: int = 3
) -> np.ndarray:
    """A run of at least ``min_run`` missing readings -> anomaly; otherwise abstain."""
    missing = np.isnan(values)
    run = np.zeros(values.shape, dtype=int)
    for t in range(values.shape[0]):
        prev = run[t - 1] if t else 0
        run[t] = np.where(missing[t], prev + 1, 0)
    out = np.zeros(values.shape, dtype=np.int8)
    out[run >= min_run] = ANOMALY
    return out


def lf_three_sigma(
    values: np.ndarray,
    neighbors: Neighbors | None = None,
    k_out: float = 3.0,
    k_in: float = 2.0,
) -> np.ndarray:
    """Robust 3-sigma test on the residual from the per-step mesh median.

    Subtracting the cross-node median removes the shared seasonal signal; sigma is the
    pooled MAD-based estimate over the whole residual matrix (an offline batch statistic).
    Benign spikes on healthy nodes also exceed 3 sigma, so this LF is noisy by design.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        resid = values - np.nanmedian(values, axis=1, keepdims=True)
    finite = resid[~np.isnan(resid)]
    out = np.zeros(values.shape, dtype=np.int8)
    if finite.size == 0:
        return out
    center = np.median(finite)
    sigma = 1.4826 * np.median(np.abs(finite - center))
    if sigma <= 1e-12:
        return out
    z = np.abs(resid - center) / sigma
    out[z > k_out] = ANOMALY
    out[z < k_in] = NORMAL_VOTE
    return out


def lf_neighbor_correlation(
    values: np.ndarray,
    neighbors: Neighbors,
    window: int = 30,
    min_pairs: int = 10,
    corr_low: float = 0.2,
    corr_high: float = 0.6,
    gap_out: float = 3.0,
    gap_in: float = 1.5,
) -> np.ndarray:
    """Trailing-window agreement with the mean of the two ring neighbours.

    Anomaly if the window correlation is low (a flat sensor has correlation 0) or the mean
    gap is large; normal if both correlation and gap look healthy. Windows with fewer than
    ``min_pairs`` finite pairs abstain.
    """
    t_len, n = values.shape
    left = np.array([a for a, _ in neighbors])
    right = np.array([b for _, b in neighbors])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        ref = np.nanmean(np.stack([values[:, left], values[:, right]]), axis=0)
    out = np.zeros(values.shape, dtype=np.int8)
    if t_len < window:
        return out

    xw = sliding_window_view(values, window, axis=0)  # (T-w+1, N, w)
    yw = sliding_window_view(ref, window, axis=0)
    ok = ~(np.isnan(xw) | np.isnan(yw))
    cnt = ok.sum(-1)
    safe = np.maximum(cnt, 1)
    x = np.where(ok, xw, 0.0)
    y = np.where(ok, yw, 0.0)
    mx = x.sum(-1) / safe
    my = y.sum(-1) / safe
    dx = np.where(ok, xw - mx[..., None], 0.0)
    dy = np.where(ok, yw - my[..., None], 0.0)
    sxx, syy, sxy = (dx * dx).sum(-1), (dy * dy).sum(-1), (dx * dy).sum(-1)
    denom = np.sqrt(sxx * syy)
    corr = np.where(denom > 1e-12, sxy / np.where(denom > 1e-12, denom, 1.0), 0.0)
    gap = np.abs(mx - my)

    sub = np.zeros(corr.shape, dtype=np.int8)
    sub[(corr > corr_high) & (gap < gap_in)] = NORMAL_VOTE
    sub[(corr < corr_low) | (gap > gap_out)] = ANOMALY
    sub[cnt < min_pairs] = ABSTAIN
    out[window - 1 :] = sub
    return out


def lf_stuck_value(
    values: np.ndarray, neighbors: Neighbors | None = None, k: int = 5
) -> np.ndarray:
    """Last ``k`` readings exactly identical -> anomaly; varying -> normal; missing -> abstain."""
    out = np.zeros(values.shape, dtype=np.int8)
    if values.shape[0] < k:
        return out
    w = sliding_window_view(values, k, axis=0)  # (T-k+1, N, k)
    finite = ~np.isnan(w).any(-1)
    flat = finite & (w.max(-1) == w.min(-1))
    sub = np.zeros(flat.shape, dtype=np.int8)
    sub[finite & ~flat] = NORMAL_VOTE
    sub[flat] = ANOMALY
    out[k - 1 :] = sub
    return out


LabelingFunction = Callable[[np.ndarray, Neighbors], np.ndarray]

LABELING_FUNCTIONS: dict[str, LabelingFunction] = {
    "rate_of_change": lf_rate_of_change,
    "range_check": lf_range_check,
    "silence": lf_silence,
    "three_sigma": lf_three_sigma,
    "neighbor_correlation": lf_neighbor_correlation,
    "stuck_value": lf_stuck_value,
}
LF_NAMES = list(LABELING_FUNCTIONS)


@dataclass(frozen=True)
class VoteMatrix:
    """Votes for every (step, node) example. Row index = ``t * n_nodes + node``."""

    votes: np.ndarray  # (T*N, J) int8
    lf_names: list[str]
    steps: int
    n_nodes: int

    @property
    def tensor(self) -> np.ndarray:
        """Votes as a (T, N, J) view."""
        return self.votes.reshape(self.steps, self.n_nodes, len(self.lf_names))

    def to_frame(self) -> pd.DataFrame:
        idx = np.arange(self.votes.shape[0])
        df = pd.DataFrame(self.votes, columns=self.lf_names)
        df.insert(0, "node", idx % self.n_nodes)
        df.insert(0, "step", idx // self.n_nodes)
        return df


def build_vote_matrix(readings: Readings) -> VoteMatrix:
    values = readings.values
    cols = [fn(values, readings.neighbors) for fn in LABELING_FUNCTIONS.values()]
    t_len, n = values.shape
    votes = np.stack(cols, axis=-1).reshape(t_len * n, len(cols)).astype(np.int8)
    return VoteMatrix(votes, list(LF_NAMES), t_len, n)
