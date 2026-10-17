"""Probability calibration: ECE, reliability curves, temperature scaling, isotonic."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy.optimize import minimize_scalar  # noqa: E402
from scipy.special import expit  # noqa: E402
from sklearn.isotonic import IsotonicRegression  # noqa: E402

EPS = 1e-6


def _check(probs: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    probs = np.asarray(probs, dtype=float).ravel()
    labels = np.asarray(labels).astype(float).ravel()
    if probs.shape != labels.shape:
        raise ValueError("probs and labels must have the same length")
    if probs.size == 0:
        raise ValueError("empty input")
    if (probs < 0).any() or (probs > 1).any():
        raise ValueError("probs must lie in [0, 1]")
    return probs, labels


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p) - np.log1p(-p)


def nll(probs: np.ndarray, labels: np.ndarray) -> float:
    p = np.clip(probs, EPS, 1 - EPS)
    return float(-np.mean(labels * np.log(p) + (1 - labels) * np.log1p(-p)))


@dataclass(frozen=True)
class ReliabilityCurve:
    edges: np.ndarray  # (B+1,)
    confidence: np.ndarray  # (B,) mean predicted prob per bin (NaN if empty)
    accuracy: np.ndarray  # (B,) observed positive rate per bin (NaN if empty)
    counts: np.ndarray  # (B,)


def reliability_curve(probs: np.ndarray, labels: np.ndarray, n_bins: int = 15) -> ReliabilityCurve:
    """Equal-width bins on P(anomaly); the last bin includes 1.0."""
    probs, labels = _check(probs, labels)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(probs, edges[1:-1], right=False), 0, n_bins - 1)
    counts = np.bincount(idx, minlength=n_bins)
    sum_p = np.bincount(idx, weights=probs, minlength=n_bins)
    sum_y = np.bincount(idx, weights=labels, minlength=n_bins)
    with np.errstate(invalid="ignore", divide="ignore"):
        conf = np.where(counts > 0, sum_p / counts, np.nan)
        acc = np.where(counts > 0, sum_y / counts, np.nan)
    return ReliabilityCurve(edges, conf, acc, counts)


def ece(probs: np.ndarray, labels: np.ndarray, n_bins: int = 15) -> float:
    """Expected calibration error: sum_b (n_b / n) * |acc_b - conf_b|."""
    curve = reliability_curve(probs, labels, n_bins)
    mask = curve.counts > 0
    gaps = np.abs(curve.accuracy[mask] - curve.confidence[mask])
    return float((curve.counts[mask] / curve.counts.sum() * gaps).sum())


class TemperatureScaler:
    """p' = sigmoid(logit(p) / T), T > 0 fit by minimising NLL."""

    def __init__(self) -> None:
        self.temperature = 1.0

    def fit(self, probs: np.ndarray, labels: np.ndarray) -> TemperatureScaler:
        probs, labels = _check(probs, labels)
        z = logit(probs)

        def loss(log_t: float) -> float:
            return nll(expit(z / np.exp(log_t)), labels)

        res = minimize_scalar(loss, bounds=(-4.0, 4.0), method="bounded")
        self.temperature = float(np.exp(res.x))
        return self

    def transform(self, probs: np.ndarray) -> np.ndarray:
        return expit(logit(np.asarray(probs, dtype=float)) / self.temperature)


class IsotonicCalibrator:
    """Monotone non-parametric recalibration (scikit-learn PAV)."""

    def __init__(self) -> None:
        self._iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")

    def fit(self, probs: np.ndarray, labels: np.ndarray) -> IsotonicCalibrator:
        probs, labels = _check(probs, labels)
        self._iso.fit(probs, labels)
        return self

    def transform(self, probs: np.ndarray) -> np.ndarray:
        return self._iso.predict(np.asarray(probs, dtype=float))


def plot_reliability(
    probs: np.ndarray,
    labels: np.ndarray,
    path: str | Path,
    title: str = "Reliability diagram",
    n_bins: int = 15,
) -> float:
    """Save a reliability diagram and return the ECE shown on it."""
    curve = reliability_curve(probs, labels, n_bins)
    value = ece(probs, labels, n_bins)
    fig, (ax, ax2) = plt.subplots(
        2, 1, figsize=(5, 6), gridspec_kw={"height_ratios": [3, 1]}, sharex=True
    )
    mask = curve.counts > 0
    width = 1.0 / n_bins
    centers = (curve.edges[:-1] + curve.edges[1:]) / 2
    ax.plot([0, 1], [0, 1], "--", color="gray", label="perfect")
    ax.bar(centers[mask], curve.accuracy[mask], width=width * 0.9, alpha=0.6, label="observed")
    ax.plot(curve.confidence[mask], curve.accuracy[mask], "o-", color="C3", label="bin mean")
    ax.set_ylabel("observed anomaly rate")
    ax.set_title(f"{title}\nECE = {value:.4f}")
    ax.legend(loc="upper left")
    ax2.bar(centers, curve.counts, width=width * 0.9, color="gray")
    ax2.set_yscale("log")
    ax2.set_xlabel("predicted P(anomaly)")
    ax2.set_ylabel("count")
    fig.tight_layout()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return value
