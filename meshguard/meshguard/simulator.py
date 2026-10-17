"""Ring-topology IoT sensor simulator.

Ground truth (regimes, anomaly labels) lives in :class:`GroundTruth` and is kept
apart from the :class:`Readings` that downstream modules may see. Only evaluation
code should touch ``Simulation.truth``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

NORMAL, DRIFTING, STUCK, DEAD = 0, 1, 2, 3
REGIME_NAMES = {NORMAL: "normal", DRIFTING: "drifting", STUCK: "stuck", DEAD: "dead"}
FAULT_REGIMES = (DRIFTING, STUCK, DEAD)

BASE_LEVEL = 20.0
SEASONAL_AMP = 5.0
SEASONAL_PERIOD = 200.0
NOISE_SD = 0.3
OFFSET_SD = 0.5
DRIFT_SLOPE = 0.05  # units per step after onset
SPIKE_PROB = 0.005  # benign spikes on healthy readings (labelled normal)
SPIKE_MAG = 4.0
DROPOUT_PROB = 0.002  # benign NaN dropouts on healthy readings (labelled normal)


@dataclass(frozen=True)
class Readings:
    """What the pipeline is allowed to see."""

    values: np.ndarray  # (T, N) float, NaN = no reading
    neighbors: list[tuple[int, int]]  # ring neighbours per node


@dataclass(frozen=True)
class GroundTruth:
    """Evaluation-only information."""

    regimes: np.ndarray  # (T, N) int regime codes
    labels: np.ndarray  # (T, N) bool, True = anomalous
    faulty_nodes: np.ndarray  # sorted node ids
    onsets: dict[int, int]  # node id -> onset step


@dataclass(frozen=True)
class Simulation:
    readings: Readings
    truth: GroundTruth
    seed: int


def ring_neighbors(n: int) -> list[tuple[int, int]]:
    return [((i - 1) % n, (i + 1) % n) for i in range(n)]


def simulate(
    seed: int = 42,
    n_sensors: int = 20,
    steps: int = 500,
    fault_frac: float = 0.15,
) -> Simulation:
    """Generate one deterministic run.

    At least two nodes are faulty, and the first three faulty nodes cover the
    drifting / stuck / dead regimes (in shuffled order) so every regime appears
    whenever ``n_faulty >= 3``.
    """
    if n_sensors < 4:
        raise ValueError("n_sensors must be >= 4")
    if steps < 50:
        raise ValueError("steps must be >= 50")
    if not 0.0 < fault_frac <= 0.5:
        raise ValueError("fault_frac must be in (0, 0.5]")

    rng = np.random.default_rng(seed)
    t = np.arange(steps)

    # Ambient signal shared by the mesh, plus a slowly varying per-node component
    # so that ring neighbours are more correlated than distant nodes.
    phase = rng.uniform(0, 2 * np.pi)
    ambient = BASE_LEVEL + SEASONAL_AMP * np.sin(2 * np.pi * t / SEASONAL_PERIOD + phase)
    offsets = rng.normal(0.0, OFFSET_SD, n_sensors)
    values = ambient[:, None] + offsets[None, :] + rng.normal(0.0, NOISE_SD, (steps, n_sensors))

    # Benign healthy-sensor glitches (keeps single LFs imperfect, as in real life).
    spikes = rng.random((steps, n_sensors)) < SPIKE_PROB
    values = values + spikes * rng.choice([-1.0, 1.0], (steps, n_sensors)) * SPIKE_MAG
    dropouts = rng.random((steps, n_sensors)) < DROPOUT_PROB

    n_faulty = max(2, round(fault_frac * n_sensors))
    faulty = np.sort(rng.choice(n_sensors, size=n_faulty, replace=False))
    cover = list(rng.permutation(FAULT_REGIMES))
    extra = list(rng.choice(FAULT_REGIMES, size=max(0, n_faulty - len(cover))))
    fault_regimes = (cover + extra)[:n_faulty]
    rng.shuffle(faulty)

    regimes = np.zeros((steps, n_sensors), dtype=int)
    onsets: dict[int, int] = {}
    lo, hi = int(0.2 * steps), int(0.6 * steps)
    for node, regime in zip(faulty, fault_regimes, strict=True):
        node = int(node)
        onset = int(rng.integers(lo, hi))
        onsets[node] = onset
        regimes[onset:, node] = regime
        if regime == DRIFTING:
            values[onset:, node] += DRIFT_SLOPE * np.arange(1, steps - onset + 1)
        elif regime == STUCK:
            values[onset:, node] = values[onset, node]
        else:
            values[onset:, node] = np.nan

    values[dropouts & (regimes == NORMAL)] = np.nan

    truth = GroundTruth(
        regimes=regimes,
        labels=regimes != NORMAL,
        faulty_nodes=np.sort(faulty),
        onsets=onsets,
    )
    return Simulation(Readings(values, ring_neighbors(n_sensors)), truth, seed)
