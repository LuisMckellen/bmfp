"""Failure-domain isolation: zones of sensors, LF quarantine and rogue-sensor down-weighting.

The ring is cut into zones of ``zone_size`` consecutive sensors. Time is cut into windows.
Inside each (LF, zone, window) cell the LF's non-abstaining votes are scored against pseudo
labels (the label model's hard posterior; no ground truth). An LF whose cell accuracy stays
below ``acc_threshold`` for ``k`` consecutive evidence-bearing windows is quarantined in that
zone from the next window on (latched). Separately, a sensor whose votes across all LFs agree
with the pseudo labels less than ``acc_threshold`` in a window has its votes down-weighted
in the following window.

Quarantine is applied causally in time, but the pseudo labels come from a batch fit of the
label model, so this is an offline analysis, not a streaming implementation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .labeling import VoteMatrix

ZONE_SIZE = 5
WINDOW = 25
K_WINDOWS = 3
ACC_THRESHOLD = 0.55
MIN_VOTES = 20
ROGUE_WEIGHT = 0.5


@dataclass(frozen=True)
class IsolationResult:
    weights: np.ndarray  # (T*N, J) in [0, 1]
    quarantine_start: np.ndarray  # (J, Z) first window under quarantine, -1 = never
    window_accuracy: np.ndarray  # (J, Z, W) NaN where there was too little evidence
    rogue_sensor: np.ndarray  # (N, W) bool: sensor flagged in that window
    lf_names: list[str]
    window: int

    def quarantined(self) -> list[tuple[str, int, int]]:
        """(lf name, zone, first affected step) for every quarantined pair."""
        j_idx, z_idx = np.nonzero(self.quarantine_start >= 0)
        return [
            (self.lf_names[j], int(z), int(self.quarantine_start[j, z]) * self.window)
            for j, z in zip(j_idx, z_idx, strict=True)
        ]


def n_zones(n_nodes: int, zone_size: int = ZONE_SIZE) -> int:
    return -(-n_nodes // zone_size)


def inject_rogue(
    vm: VoteMatrix, lf_name: str, zone: int, from_step: int, zone_size: int = ZONE_SIZE
) -> VoteMatrix:
    """Return a copy of ``vm`` in which one LF has its votes inverted in one zone."""
    j = vm.lf_names.index(lf_name)
    tens = vm.tensor.copy()
    nodes = np.arange(zone * zone_size, min((zone + 1) * zone_size, vm.n_nodes))
    if nodes.size == 0:
        raise ValueError("zone out of range")
    tens[from_step:, nodes, j] *= -1
    votes = tens.reshape(vm.votes.shape)
    return VoteMatrix(votes, list(vm.lf_names), vm.steps, vm.n_nodes)


def isolate(
    vm: VoteMatrix,
    pseudo: np.ndarray,
    zone_size: int = ZONE_SIZE,
    window: int = WINDOW,
    k: int = K_WINDOWS,
    acc_threshold: float = ACC_THRESHOLD,
    min_votes: int = MIN_VOTES,
    rogue_weight: float = ROGUE_WEIGHT,
) -> IsolationResult:
    """Compute quarantine decisions and vote weights from pseudo labels (bool, length T*N)."""
    t_len, n, j_len = vm.steps, vm.n_nodes, len(vm.lf_names)
    tens = vm.tensor
    pseudo = np.asarray(pseudo, dtype=bool).reshape(t_len, n)
    zones = n_zones(n, zone_size)
    n_win = -(-t_len // window)
    zone_of = np.arange(n) // zone_size

    win_acc = np.full((j_len, zones, n_win), np.nan)
    for w in range(n_win):
        sl = slice(w * window, min((w + 1) * window, t_len))
        v = tens[sl]  # (t, N, J)
        voted = v != 0
        right = (v == 1) == pseudo[sl][..., None]
        for z in range(zones):
            cols = zone_of == z
            cnt = voted[:, cols, :].sum(axis=(0, 1))  # (J,)
            hit = (voted & right)[:, cols, :].sum(axis=(0, 1))
            ok = cnt >= min_votes
            win_acc[ok, z, w] = hit[ok] / cnt[ok]

    quarantine_start = np.full((j_len, zones), -1, dtype=int)
    for j in range(j_len):
        for z in range(zones):
            streak = 0
            for w in range(n_win):
                a = win_acc[j, z, w]
                if np.isnan(a):
                    continue
                streak = streak + 1 if a < acc_threshold else 0
                if streak >= k:
                    quarantine_start[j, z] = w + 1
                    break

    weights = np.ones((t_len, n, j_len))
    for j in range(j_len):
        for z in range(zones):
            start = quarantine_start[j, z]
            if 0 <= start < n_win:
                weights[start * window :, zone_of == z, j] = 0.0

    # Rogue sensors: judged on window w, down-weighted in window w+1.
    rogue = np.zeros((n, n_win), dtype=bool)
    for w in range(n_win):
        sl = slice(w * window, min((w + 1) * window, t_len))
        v = tens[sl]
        voted = (v != 0) & (weights[sl] > 0)
        right = (v == 1) == pseudo[sl][..., None]
        cnt = voted.sum(axis=(0, 2))
        hit = (voted & right).sum(axis=(0, 2))
        with np.errstate(invalid="ignore", divide="ignore"):
            agree = np.where(cnt >= min_votes, hit / np.maximum(cnt, 1), np.nan)
        rogue[:, w] = agree < acc_threshold
        cols = np.flatnonzero(rogue[:, w])
        if w + 1 < n_win and cols.size:
            lo, hi = (w + 1) * window, min((w + 2) * window, t_len)
            weights[lo:hi, cols, :] *= rogue_weight

    return IsolationResult(
        weights=weights.reshape(t_len * n, j_len),
        quarantine_start=quarantine_start,
        window_accuracy=win_acc,
        rogue_sensor=rogue,
        lf_names=list(vm.lf_names),
        window=window,
    )
