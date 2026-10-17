"""Selective prediction: coverage-risk curve and threshold selection.

Confidence of an example is ``max(p, 1 - p)``; the model abstains below a threshold.
Risk is the error rate of the hard prediction (``p > 0.5``) on the accepted examples.
Ties in confidence are accepted or rejected together.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


@dataclass(frozen=True)
class CoverageRisk:
    thresholds: np.ndarray  # confidence cut-offs, descending
    coverage: np.ndarray  # fraction accepted at each cut-off, ascending
    risk: np.ndarray  # error rate among accepted


@dataclass(frozen=True)
class Selection:
    threshold: float  # accept iff confidence >= threshold; inf = accept nothing
    coverage: float
    risk: float


def confidence(probs: np.ndarray) -> np.ndarray:
    probs = np.asarray(probs, dtype=float)
    return np.maximum(probs, 1.0 - probs)


def _errors(probs: np.ndarray, labels: np.ndarray) -> np.ndarray:
    return ((np.asarray(probs) > 0.5) != np.asarray(labels).astype(bool)).astype(float)


def coverage_risk_curve(probs: np.ndarray, labels: np.ndarray) -> CoverageRisk:
    probs = np.asarray(probs, dtype=float).ravel()
    labels = np.asarray(labels).ravel()
    if probs.shape != labels.shape or probs.size == 0:
        raise ValueError("probs and labels must be non-empty and the same length")
    conf = confidence(probs)
    err = _errors(probs, labels)
    order = np.argsort(-conf, kind="stable")
    conf_s, err_s = conf[order], err[order]
    n = conf_s.size
    ends = np.flatnonzero(np.r_[conf_s[1:] != conf_s[:-1], True])  # last index of tie groups
    cum_err = np.cumsum(err_s)[ends]
    accepted = ends + 1
    return CoverageRisk(conf_s[ends], accepted / n, cum_err / accepted)


def select_threshold(probs: np.ndarray, labels: np.ndarray, max_risk: float = 0.05) -> Selection:
    """Lowest confidence cut-off (max coverage) whose accepted-set risk is <= ``max_risk``."""
    if not 0.0 <= max_risk <= 1.0:
        raise ValueError("max_risk must be in [0, 1]")
    curve = coverage_risk_curve(probs, labels)
    ok = np.flatnonzero(curve.risk <= max_risk)
    if ok.size == 0:
        return Selection(float("inf"), 0.0, 0.0)
    i = ok.max()
    return Selection(float(curve.thresholds[i]), float(curve.coverage[i]), float(curve.risk[i]))


def apply_threshold(probs: np.ndarray, labels: np.ndarray, threshold: float) -> Selection:
    """Coverage and risk of a fixed threshold on (possibly different) data."""
    conf = confidence(np.asarray(probs, dtype=float).ravel())
    accept = conf >= threshold
    if not accept.any():
        return Selection(float(threshold), 0.0, 0.0)
    err = _errors(np.asarray(probs).ravel(), np.asarray(labels).ravel())
    return Selection(float(threshold), float(accept.mean()), float(err[accept].mean()))


def aurc(curve: CoverageRisk) -> float:
    """Area under the risk-coverage curve (lower is better)."""
    cov = np.r_[0.0, curve.coverage]
    risk = np.r_[curve.risk[0], curve.risk]
    return float(np.sum(np.diff(cov) * (risk[1:] + risk[:-1]) / 2))


def plot_coverage_risk(
    curves: dict[str, CoverageRisk],
    path: str | Path,
    max_risk: float | None = None,
    marker: Selection | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(6, 4))
    for name, c in curves.items():
        ax.plot(c.coverage, c.risk, label=name)
    if max_risk is not None:
        ax.axhline(max_risk, ls="--", color="gray", label=f"max risk {max_risk}")
    if marker is not None and marker.coverage > 0:
        ax.plot([marker.coverage], [marker.risk], "ko", label="chosen threshold (eval)")
    ax.set_xlabel("coverage")
    ax.set_ylabel("risk (error rate on accepted)")
    ax.set_title("Coverage-risk curve")
    ax.legend()
    fig.tight_layout()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)
