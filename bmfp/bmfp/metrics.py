"""Run results: per-second time series, the summary dict, and recovery-time computation.

Two attributions are used, for two questions:

* The 1 s ``series`` attribute a message's outcome to the bin in which it was *sent* (first
  attempt), so a bin's delivery ratio is always in [0, 1] even when retries or deliveries
  land in a later second. Transmissions are attributed to the bin of the attempt.
  ``unserved`` counts, per bin, the sends offered while no node was alive: they have no
  sender, so they are not in ``sent``, but they are demand nobody served, so the per-second
  ratio that matches the recovery metric is
  ``deliverable_delivered / (deliverable_sent + unserved)``.
* The 0.1 s recovery bins attribute a message's outcome to the instant it *happened*: a
  delivered message at its arrival, a dropped one at its last attempt, and an offered send
  with no live sender at its offer time. Recovery time asks "when did the service work
  again", so an ARQ resend that succeeds after recovery must count after recovery, not at
  the moment the message was first sent.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

FINE_PER_S = 10  # recovery metrics use 0.1 s send-time bins
SERIES_KEYS = (
    "t",
    "sent",
    "delivered",
    "deliverable_sent",
    "deliverable_delivered",
    "unserved",
    "active",
    "standby",
    "ghost",
    "dead",
    "transmissions",
    "mean_hops",
    "max_load_ratio",
)
DROP_REASONS = (
    "dst_asleep",
    "no_route",
    "dst_dead",
    "stale_view",
    "link_loss",
    "congestion",
    "src_dead",
)


@dataclass
class RunResult:
    """What one simulation run returns."""

    summary: dict
    series: dict[str, list]
    events: list[dict]
    frames: dict | None = None
    extra: dict = field(default_factory=dict)  # internal arrays for tests/experiments

    def to_dict(self) -> dict:
        out = {"summary": self.summary, "series": self.series, "events": self.events}
        if self.frames is not None:
            out["frames"] = self.frames
        return out


class Series:
    """Per-second send-time bins plus 0.1 s outcome-time bins for recovery metrics."""

    def __init__(self, duration: float) -> None:
        self.nb = max(1, int(math.ceil(duration - 1e-9)))
        nb = self.nb
        self.sent = [0] * nb
        self.delivered = [0] * nb
        self.dsent = [0] * nb
        self.ddel = [0] * nb
        self.unserved = [0] * nb  # sends offered while no node was alive (not in ``sent``)
        self.active = [0] * nb
        self.standby = [0] * nb
        self.ghost = [0] * nb
        self.dead = [0] * nb
        self.tx = [0.0] * nb
        self.hops = [0] * nb
        self.max_load_ratio = [0.0] * nb
        nf = nb * FINE_PER_S
        # outcome-time bins (see the module docstring): deliverable outcomes, the served ones,
        # offered sends with no alive source (total death), and the first arrival per bin
        self.fine_ds = [0] * nf
        self.fine_dd = [0] * nf
        self.fine_outage = [0] * nf
        self.fine_first: list[float | None] = [None] * nf

    def bin(self, t: float) -> int:
        b = int(t)
        if b < 0:
            return 0
        return b if b < self.nb else self.nb - 1

    def fine(self, t: float) -> int:
        f = int(t * FINE_PER_S + 1e-9)
        nf = len(self.fine_ds)
        if f < 0:
            return 0
        return f if f < nf else nf - 1

    def offered(self) -> list[int]:
        """Per 0.1 s bin: deliverable outcomes plus sends offered with no live sender."""
        return [a + b for a, b in zip(self.fine_ds, self.fine_outage, strict=True)]

    def outcome_seconds(self) -> dict[str, list]:
        """The recovery metric's own data per 1 s bin: offered, served and their ratio.

        Unlike ``series``, outcomes are timed when they happen and sends offered with no live
        sender count as unserved, so total death plots as 0.0, not as a gap.
        """
        off = self.offered()
        k = FINE_PER_S
        o = [sum(off[i * k : (i + 1) * k]) for i in range(self.nb)]
        s = [sum(self.fine_dd[i * k : (i + 1) * k]) for i in range(self.nb)]
        return {
            "t": list(range(self.nb)),
            "offered": o,
            "served": s,
            "ratio": [round(b / a, 4) if a else None for a, b in zip(o, s, strict=True)],
        }

    def as_dict(self) -> dict[str, list]:
        mean_hops = [
            round(h / d, 4) if d else 0.0 for h, d in zip(self.hops, self.delivered, strict=True)
        ]
        return {
            "t": list(range(self.nb)),
            "sent": list(self.sent),
            "delivered": list(self.delivered),
            "deliverable_sent": list(self.dsent),
            "deliverable_delivered": list(self.ddel),
            "unserved": list(self.unserved),
            "active": list(self.active),
            "standby": list(self.standby),
            "ghost": list(self.ghost),
            "dead": list(self.dead),
            "transmissions": [round(x, 4) for x in self.tx],
            "mean_hops": mean_hops,
            "max_load_ratio": [round(x, 4) for x in self.max_load_ratio],
        }


def ratio(num: float, den: float) -> float | None:
    return num / den if den else None


def _prefix(xs: Sequence[float]) -> list[float]:
    out = [0.0]
    acc = 0.0
    for x in xs:
        acc += x
        out.append(acc)
    return out


def bin_ratios(ds: Sequence[int], dd: Sequence[int]) -> list[float | None]:
    """Per-bin deliverable delivery ratio (None where nothing deliverable was sent)."""
    return [(b / a if a else None) for a, b in zip(ds, dd, strict=True)]


def recovery_metrics(
    offered: Sequence[int],
    served: Sequence[int],
    kill_at: float,
    duration: float,
    *,
    first_served: Sequence[float | None] | None = None,
    baseline_s: float = 60.0,
    window_s: float = 5.0,
    hold_bins: int = 10,
    frac: float = 0.95,
    fine_per_s: int = FINE_PER_S,
) -> dict:
    """Service recovery after a failure at ``kill_at``.

    Inputs are 0.1 s bins in *outcome time* (see the module docstring): ``offered`` counts
    deliverable outcomes plus sends offered while no node was alive, ``served`` the delivered
    ones, and ``first_served`` (optional) the earliest arrival in each bin.

    * ``baseline_ratio``: served / offered over [kill_at - baseline_s, kill_at).
    * ``rto_service_s``: the service is back at the first 0.1 s step T >= kill_at such that,
      with thr = ``frac`` x baseline,

      1. the step [T, T + 0.1 s) itself served at least one message, at ratio >= thr
         (the service exists at T: no earlier instant can qualify);
      2. the first second [T, T + 1 s) has ratio >= thr; and
      3. each of the ``hold_bins`` forward windows [T + j, T + j + window_s), j = 0, 1, ...
         (1 s apart), has ratio >= thr. Windows with nothing offered do not qualify.

      Reported as the first arrival inside that step (or the step start without
      ``first_served``) minus ``kill_at``. None if never reached before the run ends.
      Conditions 1 and 2 are what stop a forward window that *starts* inside the outage
      from passing on the strength of the 95% tolerance alone.
    * ``min_ratio_after_kill``: lowest window ratio for windows starting in
      [kill_at, kill_at + 60 s); ``ratio_dip`` = baseline - that minimum.
    """
    P_ds = _prefix(offered)
    P_dd = _prefix(served)
    nf = len(offered)
    k = int(round(kill_at * fine_per_s))
    b0 = max(0, k - int(round(baseline_s * fine_per_s)))
    base_ds = P_ds[k] - P_ds[b0]
    base_dd = P_dd[k] - P_dd[b0]
    baseline = base_dd / base_ds if base_ds else None
    w = int(round(window_s * fine_per_s))
    step = fine_per_s

    def span(s: int, length: int) -> float | None:
        e = s + length
        if s < 0 or e > nf:
            return None
        a = P_ds[e] - P_ds[s]
        if a <= 0:
            return None
        return (P_dd[e] - P_dd[s]) / a

    def win(s: int) -> float | None:
        return span(s, w)

    rto = None
    if baseline is not None and baseline > 0:
        thr = frac * baseline - 1e-12
        last_start = nf - w - (hold_bins - 1) * step
        s = k
        while s <= last_start:
            ok = served[s] > 0 and (span(s, 1) or 0.0) >= thr and (span(s, step) or 0.0) >= thr
            if ok:
                for j in range(hold_bins):
                    r = win(s + j * step)
                    if r is None or r < thr:
                        ok = False
                        break
            if ok:
                first = first_served[s] if first_served is not None else None
                t_rec = first if first is not None else s / fine_per_s
                rto = max(0.0, t_rec - kill_at)
                break
            s += 1
    mins = []
    s = k
    end = min(nf - w, k + 60 * fine_per_s - 1)
    while s <= end:
        r = win(s)
        if r is not None:
            mins.append(r)
        s += 1
    min_r = min(mins) if mins else None
    return {
        "baseline_ratio": baseline,
        "rto_service_s": rto,
        "min_ratio_after_kill": min_r,
        "ratio_dip": (baseline - min_r) if (baseline is not None and min_r is not None) else None,
    }


def percentile(xs: Sequence[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    idx = min(len(s) - 1, max(0, int(math.ceil(q * len(s))) - 1))
    return s[idx]


def per(num: float, den: float) -> float:
    return num / den if den else 0.0


def clean(obj):
    """Round floats and convert tuples so the structure is compact, stable JSON."""
    if isinstance(obj, float):
        if obj != obj or obj in (math.inf, -math.inf):
            return None
        return round(obj, 6)
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    return obj
