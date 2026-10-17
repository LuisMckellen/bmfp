"""Experiments E1..E7, aggregation over seeds, generated findings, plots and the results page.

Every number in ``reports/bmfp_results.md`` and in the findings is formatted from the
aggregated run data at the moment it is written; nothing is typed in by hand.
"""

from __future__ import annotations

import itertools
import json
import math
import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from .cell import is_cds, repair_cds
from .metrics import clean
from .sim import FLAP_CYCLES, Config, Simulation, run
from .topology import (
    CAGE_NAMES,
    cage,
    cage_facts,
    cds_search,
    is_dominating,
    is_exact_partition,
    min_cds_exact,
    min_dominating_exact,
    partition_probability,
    ring,
    stem_triple,
)

DEFAULT_SEEDS = (1, 2, 3, 4, 5)


@dataclass(frozen=True)
class Plan:
    """Durations and sweeps. ``FULL`` is the published suite; ``QUICK`` is for tests."""

    seeds: tuple[int, ...] = DEFAULT_SEEDS
    e1_trials: int = 20000
    e1_exact_cds_max_n: int = 24
    e1_cds_search_iters: int = 1000
    e2_duration: float = 600.0
    e3_duration: float = 300.0
    e3_kill_at: float = 120.0
    e3_fractions: tuple[float, ...] = (0.5, 0.6, 1.0)
    e4_seeds: tuple[int, ...] = (1, 2, 3)
    e4_duration: float = 300.0
    e4_rates: tuple[float, ...] = (10.0, 20.0, 40.0, 80.0)
    e4_losses: tuple[float, ...] = (0.0, 0.05)
    e4_routings: tuple[str, ...] = ("chill", "duplicate", "stripe")
    e4_fixed: tuple[tuple[float, float], ...] = ((20.0, 0.05), (80.0, 0.0))
    e5_duration: float = 600.0
    e5_active: tuple[float, ...] = (0.2, 0.35, 0.5)
    e5_standby: tuple[float, ...] = (0.0, 0.3, 0.6, 1.0)
    e6_duration: float = 300.0
    e6_rates: tuple[float, ...] = (0.0, 0.02, 0.05, 0.1)
    # E7 sensitivity: how the findings move with the ASSUMPTIONS they rest on
    e7_seeds: tuple[int, ...] = (1, 2, 3)
    e7_duration: float = 600.0
    e7_hotspots: tuple[float, ...] = (0.0, 0.15, 0.3)
    e7_rates: tuple[float, ...] = (20.0, 40.0)
    e7_rto_loads: tuple[tuple[float, float], ...] = ((20.0, 40.0), (80.0, 40.0), (20.0, 10.0))
    e7_rto_fractions: tuple[float, ...] = (0.5, 0.6, 1.0)
    e7_res_rates: tuple[float, ...] = (20.0, 80.0)
    e7_res_duration: float = 300.0
    e7_promotes: tuple[int, ...] = (0, 1, 2)


FULL = Plan()
QUICK = Plan(
    seeds=(1, 2),
    e1_trials=300,
    e1_exact_cds_max_n=12,
    e1_cds_search_iters=20,
    e2_duration=90.0,
    e3_duration=95.0,
    e3_kill_at=65.0,
    e4_seeds=(1,),
    e4_duration=30.0,
    e4_rates=(10.0, 40.0),
    e5_duration=60.0,
    e6_duration=60.0,
    e6_rates=(0.0, 0.1),
    e4_fixed=((10.0, 0.0),),
    e7_seeds=(1,),
    e7_duration=60.0,
    e7_hotspots=(0.0, 0.3),
    e7_rates=(20.0,),
    e7_rto_loads=((20.0, 40.0), (20.0, 10.0)),
    e7_res_rates=(20.0,),
    e7_res_duration=60.0,
    e7_promotes=(1, 2),
)

CASE_IDS = {0.5: "kill50", 0.6: "kill60", 1.0: "kill100"}


# --------------------------------------------------------------------------- aggregation
def agg(values: Iterable) -> dict:
    """``{mean, min, max, n}`` over the non-None values (all None -> None fields, n = 0)."""
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return {"mean": None, "min": None, "max": None, "n": 0}
    return {"mean": sum(vals) / len(vals), "min": min(vals), "max": max(vals), "n": len(vals)}


def value_or_list(values: Sequence):
    vals = list(values)
    return vals[0] if all(v == vals[0] for v in vals) else vals


def run_seeds(base: Config, seeds: Sequence[int]) -> list[dict]:
    return [Simulation(replace(base, seed=s)).run().summary for s in seeds]


def summarize(summaries: list[dict], metrics: Sequence[str]) -> dict:
    return {m: agg(s[m] for s in summaries) for m in metrics}


# --------------------------------------------------------------------------- E1
# Figure 6 (v1.7b) draws "the same twelve-node cell" as a ring with every third node ACTIVE.
FIG6_RING_N = 12
FIG6_DRAWN_ACTIVE = (0, 3, 6, 9)


def figure6_ring() -> dict:
    """The cell Figure 6 actually draws: a 12-node ring, 4 of its nodes ACTIVE."""
    adj = ring(FIG6_RING_N)
    return {
        "n": FIG6_RING_N,
        "drawn_active": list(FIG6_DRAWN_ACTIVE),
        "drawn_dominating": is_dominating(adj, FIG6_DRAWN_ACTIVE),
        "drawn_cds": is_cds(adj, FIG6_DRAWN_ACTIVE, range(FIG6_RING_N)),
        "min_dominating": min_dominating_exact(adj),
        "min_cds": min_cds_exact(adj, 1, FIG6_RING_N),
    }


def e1_topology(plan: Plan = FULL) -> list[dict]:
    """One row per cage. ``cds_search`` is the smallest CDS containing the three stems that
    a seeded randomised search found: proof that one that small exists, not a minimum."""
    rows = []
    for name in CAGE_NAMES:
        g = cage(name)
        facts = cage_facts(g)
        pp = {}
        exact = []
        for k in range(1, 7):
            rng = random.Random(f"bmfp-e1-{name}-{k}")
            pp[str(k)] = partition_probability(g, k, trials=plan.e1_trials, rng=rng)
            exact.append(is_exact_partition(g.n, k))
        lower = math.ceil((g.n - 2) / 2)
        stems = list(stem_triple(name))
        promoted, _ = repair_cds(g.adj, set(stems), range(g.n), [0.0] * g.n)
        greedy = len(stems) + len(promoted)
        exact_cds = min_cds_exact(g.adj, lower, greedy) if g.n <= plan.e1_exact_cds_max_n else None
        found = cds_search(
            g.adj, stems, plan.e1_cds_search_iters, random.Random(f"bmfp-e1-cds-{name}")
        )
        rows.append(
            {
                **facts,
                "partition_probability": pp,
                "partition_exact": exact,
                "cds_lower_bound": lower,
                "cds_greedy": greedy,
                "cds_search": min(found, greedy),
                "cds_exact": exact_cds,
            }
        )
    return rows


# --------------------------------------------------------------------------- E2
E2_METRICS = (
    "state_changes_per_min",
    "state_changes_per_min_vsepr",
    "state_changes_per_min_resonance",
    "all_state_changes_per_min",
    "fairness_moves_per_min",
    "flaps",
    "vsepr_flaps",
    "demotions",
    "promotions",
    "vsepr_repair_promotions",
    "vsepr_candidates",
    "vsepr_cooldown_skips",
    "vsepr_no_swap",
    "vsepr_no_swap_any",
    "active_fraction_start",
    "active_fraction_end",
    "active_fraction_mean",
    "mean_max_avg_load_ratio",
    "mean_peak_relay_load",
    "mean_avg_relay_load",
    "deliverable_ratio",
    "delivery_ratio",
    "ghost_time_share",
    "share_to_asleep",
    "to_asleep_delivered_share",
    "mean_hops",
    "drops_congestion",
)
# E2 variants: name -> Config overrides. naive_cell reads v1.7d's "cell average" literally
# (mean over every believed-alive node); naive uses the mean over ACTIVE relays.
E2_VARIANTS = {
    "naive": {"vsepr": "naive"},
    "damped": {"vsepr": "damped"},
    "off": {"vsepr": "off"},
    "naive_cell": {"vsepr": "naive", "vsepr_average": "cell"},
}
E2_LABELS = {
    "naive": "naive (journal rule, ACTIVE average)",
    "damped": "damped (proposed fix)",
    "off": "off",
    "naive_cell": "naive, cell average (journal wording)",
}


def e2_vsepr(plan: Plan = FULL) -> dict:
    out = {"seeds": list(plan.seeds), "duration": plan.e2_duration, "variants": {}}
    for variant, over in E2_VARIANTS.items():
        base = Config(cage="C60", duration=plan.e2_duration, **over)
        sums = run_seeds(base, plan.seeds)
        out["variants"][variant] = summarize(sums, E2_METRICS)
    return out


# --------------------------------------------------------------------------- E3
E3_METRICS = (
    "rto_service_s",
    "rto_journal_formula_s",
    "rpo_s",
    "first_delivery_after_kill_s",
    "refill_after_kill_s",
    "detect_time_s",
    "baseline_ratio",
    "min_ratio_after_kill",
    "ratio_dip",
    "killed",
    "drops_stale_view",
    "drops_no_route",
    "captain_reelections",
    "skipped_cycles",
    "cds_impossible",
    "view_split_s",
    "drops_src_dead",
)
# E3 rows that restate inputs rather than measure anything (labelled in the results table)
E3_INPUT_ROWS = {
    "rto_journal_formula_s": "inputs: detection + mitosis/meiosis time",
    "detect_time_s": "input: detect_delay",
    "refill_after_kill_s": "inputs: detection + mitosis/meiosis, or + rejoin_delay (assumption)",
}


def e3_recovery(plan: Plan = FULL) -> dict:
    g = cage("C60")
    out = {
        "seeds": list(plan.seeds),
        "duration": plan.e3_duration,
        "kill_at": plan.e3_kill_at,
        "cage": g.name,
        "n": g.n,
        "cases": {},
    }
    for frac in plan.e3_fractions:
        cid = CASE_IDS.get(frac, f"kill{int(round(frac * 100))}")
        base = Config(
            cage="C60", duration=plan.e3_duration, kill_at=plan.e3_kill_at, kill_fraction=frac
        )
        sums = []
        series = None
        for i, s in enumerate(plan.seeds):
            res = Simulation(replace(base, seed=s)).run()
            sums.append(res.summary)
            if i == 0:
                # the recovery metric's own data: outcomes timed when they happen, and sends
                # offered while no node was alive count as unserved (total death plots as 0)
                series = {"seed": s, **res.extra["outcome_seconds"]}
        case = summarize(sums, E3_METRICS)
        case["kill_fraction"] = frac
        case["death_event"] = value_or_list([s["death_event"] for s in sums])
        case["path"] = value_or_list([s["path"] for s in sums])
        case["series"] = series
        out["cases"][cid] = case
    return out


# --------------------------------------------------------------------------- E4
STATIC_CELL = {"active_fraction": 1.0, "vsepr": "off", "resonance": "off"}
FIXED_BACKBONE = {"vsepr": "off", "resonance": "off"}


def _e4_rows(plan: Plan, extra: dict) -> list[dict]:
    rows = []
    for routing, rate, loss in itertools.product(plan.e4_routings, plan.e4_rates, plan.e4_losses):
        base = Config(
            cage="C60",
            duration=plan.e4_duration,
            routing=routing,
            send_rate=rate,
            link_loss=loss,
            **extra,
        )
        sums = run_seeds(base, plan.e4_seeds)
        rows.append(
            {
                "routing": routing,
                "send_rate": rate,
                "link_loss": loss,
                "deliverable_ratio": agg(s["deliverable_ratio"] for s in sums),
                "tx_per_delivered": agg(s["tx_per_delivered"] for s in sums),
                "duplicates_per_delivered": agg(s["duplicates_per_delivered"] for s in sums),
                "out_of_order_per_delivered": agg(s["out_of_order_per_delivered"] for s in sums),
                "congestion_drops": agg(s["drops_congestion"] for s in sums),
                "mean_paths": agg((s["mean_paths"] if s["hell_attempts"] else 1.0) for s in sums),
                "mean_hops": agg(s["mean_hops"] for s in sums),
                "p95_latency_ms": agg(s["p95_latency_ms"] for s in sums),
                "active_fraction_mean": agg(s["active_fraction_mean"] for s in sums),
            }
        )
    return rows


def e4_hell(plan: Plan = FULL) -> dict:
    """Spec rows: the living cell (default Config). Naive VSEPR resizes the backbone in
    response to each routing mode's load, so ``fixed_rows`` repeat some of them on a frozen
    backbone (VSEPR and resonance off: the same ACTIVE set for every mode).
    ``static_rows`` (extension): the v1.2 fullerene, where hell mode was introduced and every
    node relays (no states yet)."""
    fixed = [
        r
        for (rate, loss) in plan.e4_fixed
        for r in _e4_rows(replace(plan, e4_rates=(rate,), e4_losses=(loss,)), FIXED_BACKBONE)
    ]
    order = {rt: i for i, rt in enumerate(plan.e4_routings)}
    fixed.sort(key=lambda r: (order[r["routing"]], r["send_rate"], r["link_loss"]))
    return {
        "seeds": list(plan.e4_seeds),
        "duration": plan.e4_duration,
        "rows": _e4_rows(plan, {}),
        "fixed_cell": dict(FIXED_BACKBONE),
        "fixed_rows": fixed,
        "static_cell": dict(STATIC_CELL),
        "static_rows": _e4_rows(plan, STATIC_CELL),
    }


# --------------------------------------------------------------------------- E5
def e5_offline(plan: Plan = FULL) -> dict:
    rows = []
    for af in plan.e5_active:
        sums = run_seeds(
            Config(cage="C60", duration=plan.e5_duration, active_fraction=af), plan.seeds
        )
        rows.append(
            {
                "active_fraction": af,
                "share_to_asleep": agg(s["share_to_asleep"] for s in sums),
                "initial_active_fraction": agg(s["active_fraction_start"] for s in sums),
                "ghost_time_share": agg(s["ghost_time_share"] for s in sums),
                "delivery_ratio": agg(s["delivery_ratio"] for s in sums),
            }
        )
    ghost_rows = []
    for sf in plan.e5_standby:
        sums = run_seeds(
            Config(cage="C60", duration=plan.e5_duration, standby_fraction=sf), plan.seeds
        )
        ghost_rows.append(
            {
                "standby_fraction": sf,
                "share_to_asleep": agg(s["share_to_asleep"] for s in sums),
                "ghost_time_share": agg(s["ghost_time_share"] for s in sums),
                "delivery_ratio": agg(s["delivery_ratio"] for s in sums),
            }
        )
    return {
        "seeds": list(plan.seeds),
        "duration": plan.e5_duration,
        "rows": rows,
        "ghost_pool_rows": ghost_rows,
    }


# --------------------------------------------------------------------------- E6
def e6_churn(plan: Plan = FULL) -> dict:
    rows = []
    for cr in plan.e6_rates:
        sums = run_seeds(Config(cage="C60", duration=plan.e6_duration, churn_rate=cr), plan.seeds)
        rows.append(
            {
                "churn_rate": cr,
                "deliverable_ratio": agg(s["deliverable_ratio"] for s in sums),
                "stale_view_drops": agg(s["drops_stale_view"] for s in sums),
                "state_changes_per_min": agg(s["state_changes_per_min"] for s in sums),
                "no_route_drops": agg(s["drops_no_route"] for s in sums),
                "leaves": agg(s["leaves"] for s in sums),
            }
        )
    return {"seeds": list(plan.seeds), "duration": plan.e6_duration, "rows": rows}


# --------------------------------------------------------------------------- E7
E7_VSEPR_METRICS = (
    "state_changes_per_min_vsepr",
    "vsepr_flaps",
    "flaps",
    "demotions",
    "active_fraction_mean",
    "mean_max_avg_load_ratio",
    "mean_peak_relay_load",
    "share_to_asleep",
    "deliverable_ratio",
    "drops_congestion",
)
E7_RTO_METRICS = (
    "rto_service_s",
    "min_ratio_after_kill",
    "first_delivery_after_kill_s",
    "drops_congestion",
)
E7_RES_METRICS = (
    "flaps",
    "state_changes_per_min_resonance",
    "mean_hops",
    "drops_congestion",
    "deliverable_ratio",
)
E7_PROMOTE_METRICS = (
    "active_fraction_end",
    "active_fraction_mean",
    "demotions",
    "promotions",
    "vsepr_repair_promotions",
    "vsepr_flaps",
    "state_changes_per_min_vsepr",
)


def e7_sensitivity(plan: Plan = FULL) -> dict:
    """How the findings move with the ASSUMPTIONS they rest on (C60, default Config otherwise).

    * ``vsepr``: VSEPR variant x hotspot_fraction x send_rate (the E2 numbers assume 0.3 and
      20 msg/s).
    * ``rto``: kill share x (send_rate, relay_capacity) (E3 assumes 20 msg/s against 40/s per
      relay; only their ratio matters).
    * ``resonance``: resonance on vs off with VSEPR off (a fixed backbone size), at two rates.
    * ``promote``: naive VSEPR with 0, 1 or 2 promotions per demotion (the journal says 2).
    """
    out: dict = {"seeds": list(plan.e7_seeds), "duration": plan.e7_duration}
    rows = []
    for variant in ("naive", "damped", "off"):
        for h in plan.e7_hotspots:
            for rate in plan.e7_rates:
                base = Config(
                    cage="C60",
                    duration=plan.e7_duration,
                    vsepr=variant,
                    hotspot_fraction=h,
                    send_rate=rate,
                )
                sums = run_seeds(base, plan.e7_seeds)
                rows.append(
                    {
                        "vsepr": variant,
                        "hotspot_fraction": h,
                        "send_rate": rate,
                        **summarize(sums, E7_VSEPR_METRICS),
                    }
                )
    out["vsepr"] = {
        "seeds": list(plan.e7_seeds),
        "duration": plan.e7_duration,
        "rows": rows,
    }
    rows = []
    for frac in plan.e7_rto_fractions:
        for rate, cap in plan.e7_rto_loads:
            base = Config(
                cage="C60",
                duration=plan.e3_duration,
                kill_at=plan.e3_kill_at,
                kill_fraction=frac,
                send_rate=rate,
                relay_capacity=cap,
            )
            sums = run_seeds(base, plan.seeds)
            rows.append(
                {
                    "case": CASE_IDS.get(frac, f"kill{int(round(frac * 100))}"),
                    "kill_fraction": frac,
                    "send_rate": rate,
                    "relay_capacity": cap,
                    "load_ratio": rate / cap,
                    **summarize(sums, E7_RTO_METRICS),
                }
            )
    out["rto"] = {
        "seeds": list(plan.seeds),
        "duration": plan.e3_duration,
        "kill_at": plan.e3_kill_at,
        "rows": rows,
    }
    rows = []
    for rate in plan.e7_res_rates:
        for res in ("off", "on"):
            base = Config(
                cage="C60",
                duration=plan.e7_res_duration,
                vsepr="off",
                resonance=res,
                send_rate=rate,
            )
            sums = run_seeds(base, plan.e7_seeds)
            rows.append({"resonance": res, "send_rate": rate, **summarize(sums, E7_RES_METRICS)})
    out["resonance"] = {
        "seeds": list(plan.e7_seeds),
        "duration": plan.e7_res_duration,
        "vsepr": "off",
        "rows": rows,
    }
    rows = []
    for k in plan.e7_promotes:
        base = Config(cage="C60", duration=plan.e2_duration, vsepr="naive", vsepr_promote=k)
        sums = run_seeds(base, plan.seeds)
        rows.append({"vsepr_promote": k, **summarize(sums, E7_PROMOTE_METRICS)})
    out["promote"] = {"seeds": list(plan.seeds), "duration": plan.e2_duration, "rows": rows}
    return out


# --------------------------------------------------------------------------- findings
def _m(d: dict | None, key: str = "mean"):
    if not isinstance(d, dict):
        return None
    return d.get(key)


def _pct(x, digits: int = 1) -> str:
    return "n/a" if x is None else f"{100 * x:.{digits}f}%"


def _num(x, digits: int = 1) -> str:
    return "n/a" if x is None else f"{x:.{digits}f}"


def _range(d: dict | None, digits: int = 1, pct: bool = False) -> str:
    if not isinstance(d, dict) or d.get("mean") is None:
        return "n/a"
    f = (lambda v: _pct(v, digits)) if pct else (lambda v: _num(v, digits))
    if d["min"] == d["max"]:
        return f(d["mean"])
    return f"{f(d['mean'])} ({f(d['min'])}–{f(d['max'])})"


def _row(rows: list[dict], **match) -> dict | None:
    for r in rows:
        if all(r.get(k) == v for k, v in match.items()):
            return r
    return None


# Figures quoted from the journal (not measured, never derived from a run): the claims the
# findings test are phrased against them.
JOURNAL_FIG6_ACTIVE = 4  # v1.7b Figure 6: "4 active" nodes of 12
JOURNAL_C20_USER_BAND = (11, 30)  # v1.7 / Figure 3: the C20 user band
JOURNAL_FLASH_WAKE_MS = 50  # v1.7a: flash-wake budget


def _change(new, old) -> str:
    """'37% lower' / '5% higher' / 'unchanged' (within 2%)."""
    if new is None or old is None or not old:
        return "n/a"
    d = (new - old) / old
    if abs(d) < 0.02:
        return "unchanged"
    return f"{abs(100 * d):.0f}% {'lower' if d < 0 else 'higher'}"


def _approx_pp(row: dict, k: int, digits: int) -> str:
    """Partition probability for k removals, flagged when it is a Monte Carlo estimate."""
    v = row["partition_probability"][str(k)]
    exact = (row.get("partition_exact") or [True] * 6)[k - 1]
    return _pct(v, digits) if exact else f"about {_pct(v, digits)} (Monte Carlo)"


CLAIM = "claim"  # the journal asserts something works; confirmed = it holds
PROBLEM = "problem"  # the journal's review (or a run) raised a problem; confirmed = it is real
VERDICT_KEY = (
    "Each finding is a *claim* the journal makes or a *problem* raised against it (by the "
    "journal's own review, Part VII, or by these runs). For a claim, *confirmed* means the "
    "claim holds in the simulator; for a problem, *confirmed* means the problem is real in the "
    "simulator. *refuted* is the opposite, *partly* is in between, and *not simulated* means "
    "the simulator cannot speak to it."
)


def _finding(
    fid: str,
    problem: str,
    kind: str,
    journal_ref: str,
    verdict: str,
    measured: str,
    next_step: str,
) -> dict:
    return {
        "id": fid,
        "problem": problem,
        "kind": kind,
        "journal_ref": journal_ref,
        "verdict": verdict,
        "measured": measured,
        "next_step": next_step,
    }


def _span(lo, hi, f: Callable[[float], str]) -> str:
    """'a–b', or one value when both format the same."""
    if lo is None or hi is None:
        return "n/a"
    a, b = f(lo), f(hi)
    return a if a == b else f"{a}–{b}"


def _rows_span(rows: Iterable[dict], key: str, f: Callable[[float], str]) -> str:
    """Lowest seed minimum to highest seed maximum of ``key`` over ``rows``."""
    lo = [_m(r.get(key), "min") for r in rows]
    hi = [_m(r.get(key), "max") for r in rows]
    lo = [v for v in lo if v is not None]
    hi = [v for v in hi if v is not None]
    return _span(min(lo, default=None), max(hi, default=None), f)


def _list(xs: Iterable) -> str:
    return "/".join(f"{x:g}" for x in xs)


def make_findings(res: dict) -> list[dict]:
    """One entry per journal claim or open problem the simulator can speak to.

    Every number is formatted from ``res``; every verdict is computed from it. ``kind`` says
    whether the entry tests a claim or a problem (see ``VERDICT_KEY``).
    """
    out: list[dict] = []
    topo = res.get("topology") or []
    vs = (res.get("vsepr") or {}).get("variants", {})
    recov = res.get("recovery") or {}
    rec = recov.get("cases", {})
    hell_block = res.get("hell") or {}
    hell = hell_block.get("rows", [])
    off = res.get("offline") or {}
    sens = res.get("sensitivity") or {}
    s_vs = (sens.get("vsepr") or {}).get("rows", [])
    s_rto = (sens.get("rto") or {}).get("rows", [])
    s_res = sens.get("resonance") or {}
    s_prom = (sens.get("promote") or {}).get("rows", [])
    cfg = Config()
    c60 = next((r for r in topo if r["cage"] == "C60"), topo[-1] if topo else None)

    def s_row(**match) -> dict | None:
        return _row(s_vs, **match)

    def default_rate(rows: list[dict]) -> float | None:
        rates = sorted({r["send_rate"] for r in rows})
        if not rates:
            return None
        return cfg.send_rate if cfg.send_rate in rates else rates[0]

    rate0 = default_rate(s_vs)
    e2_dur = (res.get("vsepr") or {}).get("duration")
    per_e2_run = f"per {e2_dur:g} s run" if isinstance(e2_dur, (int, float)) else "per run"
    hs = sorted({r["hotspot_fraction"] for r in s_vs})
    rates = sorted({r["send_rate"] for r in s_vs})
    settings = [(h, r) for h in hs for r in rates]
    sweep_txt = (
        f"hotspot_fraction {_span(hs[0], hs[-1], lambda x: f'{x:g}')} × "
        f"{_span(rates[0], rates[-1], lambda x: f'{x:g}')} msg/s"
        if settings
        else ""
    )

    # Figure 0: no single failed checkpoint can cut the ball in half
    if topo:
        ks = sorted(int(k) for k in topo[0]["partition_probability"])
        safe = 0
        for k in ks:
            if all(r["partition_probability"][str(k)] == 0 for r in topo):
                safe = k
            else:
                break
        exhaustive = all(
            all((r.get("partition_exact") or [True] * 6)[k - 1] for r in topo)
            for k in range(1, safe + 1)
        )
        cuts = sorted({r["min_vertex_cut"] for r in topo})
        cut = cuts[0]
        kmax = ks[-1]
        safe_txt = {1: "1 node", 2: "1 or 2 nodes"}.get(safe, f"1 to {safe} nodes")
        out.append(
            _finding(
                "topology-cut",
                "No single failed checkpoint can cut the ball in half",
                CLAIM,
                "Part I · Figure 0",
                "confirmed" if safe >= 1 else "refuted",
                f"Removing any {safe_txt} never disconnected the survivors in "
                f"{', '.join(r['cage'] for r in topo)}"
                f"{' (exhaustive)' if exhaustive else ''}; the minimum vertex cut is "
                f"{'/'.join(str(c) for c in cuts)}, so {cut} failures can isolate a node: "
                f"{_approx_pp(c60, cut, 2)} of {cut}-node and {_approx_pp(c60, kmax, 1)} of "
                f"{kmax}-node removals split {c60['cage']}.",
                f"Quote the guarantee as 'survives any {cut - 1} node failures' and say what "
                "happens to a split cell (whose view wins).",
            )
        )
        c12 = next((r for r in topo if r["cage"] == "C12"), None)
        af0 = _m((vs.get("naive") or {}).get("active_fraction_start"))
        if c12 is not None:
            fig6 = figure6_ring()
            best12 = c12["cds_exact"] if c12["cds_exact"] is not None else c12["cds_lower_bound"]
            fits = [x <= JOURNAL_FIG6_ACTIVE for x in (fig6["min_cds"], best12)]
            verdict = "confirmed" if all(fits) else ("partly" if any(fits) else "refuted")
            found = c60.get("cds_search")
            found_txt = (
                f", and a {found}-node valid set containing the three stems exists "
                "(randomised search)"
                if found is not None and found < c60["cds_greedy"]
                else ""
            )
            out.append(
                _finding(
                    "valid-active-sets",
                    f"Three valid ACTIVE sets of {JOURNAL_FIG6_ACTIVE} in a {fig6['n']}-node cell",
                    CLAIM,
                    "v1.7b · Figure 6",
                    verdict,
                    "Formalising 'valid ACTIVE set' as a connected dominating set (only ACTIVE "
                    "nodes relay, every node one hop from one): on the "
                    f"{fig6['n']}-node ring Figure 6 draws, its {JOURNAL_FIG6_ACTIVE} ACTIVE "
                    "nodes (every third) "
                    f"{'dominate' if fig6['drawn_dominating'] else 'do not dominate'} the ring "
                    f"but {'are' if fig6['drawn_cds'] else 'are not'} connected, and the "
                    f"smallest valid set has {fig6['min_cds']} nodes (domination alone needs "
                    f"{fig6['min_dominating']}). On C12, the 3-regular 12-node cell this "
                    f"simulator assumes (truncated tetrahedron), it has {best12} nodes "
                    f"({'exact search' if c12['cds_exact'] else 'bound'}), and any 3-regular "
                    f"cell needs at least (n-2)/2: {c60['cds_lower_bound']} of {c60['n']} in "
                    f"{c60['cage']}. The configured active_fraction "
                    f"{_pct(cfg.active_fraction, 0)} is below that floor, so the greedy builder "
                    f"starts the cell at {c60['cds_greedy']} nodes ({_pct(af0, 1)} ACTIVE)"
                    f"{found_txt}.",
                    "Figure 6's sets dominate the ring but cannot relay: require the ACTIVE "
                    "nodes to be connected (or let STANDBY nodes relay), then re-derive the "
                    "battery claim from the share that must stay awake (at least half of a "
                    "cubic cell).",
                )
            )

    # Hell mode is ambiguous: the spec's E4 (living cell), a frozen backbone, the static cell
    static = hell_block.get("static_rows") or []
    fixed = hell_block.get("fixed_rows") or []
    if hell:
        rate = 20.0 if any(r["send_rate"] == 20.0 for r in hell) else hell[0]["send_rate"]
        loss = 0.05 if any(r["link_loss"] == 0.05 for r in hell) else hell[-1]["link_loss"]
        rts = ("chill", "duplicate", "stripe")
        lr = {rt: _row(hell, routing=rt, send_rate=rate, link_loss=loss) for rt in rts}
        sr = {rt: _row(static, routing=rt, send_rate=rate, link_loss=loss) for rt in rts}
        fr = {rt: _row(fixed, routing=rt, send_rate=rate, link_loss=loss) for rt in rts}
        ftop = max((r["send_rate"] for r in fixed if r["link_loss"] == 0.0), default=None)
        fcong = {rt: _row(fixed, routing=rt, send_rate=ftop, link_loss=0.0) for rt in rts}

        def differ(rows: dict) -> bool:
            if not all(rows.values()):
                return False
            d_tx, s_tx = (
                _m(rows["duplicate"]["tx_per_delivered"]),
                _m(rows["stripe"]["tx_per_delivered"]),
            )
            d_r, s_r = (
                _m(rows["duplicate"]["deliverable_ratio"]),
                _m(rows["stripe"]["deliverable_ratio"]),
            )
            return (
                d_tx is not None and s_tx is not None and s_tx > 0 and abs(d_tx - s_tx) / s_tx > 0.1
            ) or (d_r is not None and s_r is not None and abs(d_r - s_r) > 0.01)

        def costs(rows: dict) -> str:
            def one(rt: str) -> tuple[str, str]:
                return (
                    _num(_m(rows[rt]["tx_per_delivered"]), 2),
                    _pct(_m(rows[rt]["deliverable_ratio"])),
                )

            (dt, dr), (st, sr_), (ct, cr) = one("duplicate"), one("stripe"), one("chill")
            return (
                f"duplicating costs {dt} transmissions per delivered message and delivers "
                f"{dr}, striping {st} and {sr_}, chill {ct} and {cr}"
            )

        if all(lr.values()):
            act = " / ".join(_pct(_m(lr[rt].get("active_fraction_mean")), 0) for rt in rts)
            fixed_txt = ""
            if all(fr.values()):
                fixed_txt = (
                    " Naive VSEPR resizes the backbone to each mode's load (ACTIVE averaged "
                    f"{act} for {' / '.join(rts)}), so those figures compare different "
                    "backbones; on a frozen backbone (VSEPR and resonance off, ACTIVE "
                    f"{_pct(_m(fr['chill'].get('active_fraction_mean')), 0)} for every mode) "
                    f"the same load gives: {costs(fr)}."
                )
            cong_txt = ""
            if all(fcong.values()):
                cong_txt = (
                    f" At {ftop:g} msg/s on the frozen backbone congestion drops per run were "
                    + ", ".join(f"{rt} {_num(_m(fcong[rt]['congestion_drops']), 0)}" for rt in rts)
                    + "."
                )
            static_txt = ""
            if all(sr.values()):
                static_txt = (
                    f" On the static v1.2 fullerene (extension: every node relays, about "
                    f"{_num(_m(sr['duplicate']['mean_paths']), 2)} paths) the readings split "
                    f"further: {costs(sr)}."
                )
            out.append(
                _finding(
                    "hell-ambiguity",
                    "Hell mode is ambiguous",
                    PROBLEM,
                    "Part VII · Open problems (v1.2)",
                    "confirmed" if differ(lr) or differ(sr) or differ(fr) else "refuted",
                    f"In the living cell at {rate:g} msg/s and {_pct(loss, 0)} per-hop loss: "
                    f"{costs(lr)}.{fixed_txt} Only "
                    f"{_num(_m(lr['duplicate']['mean_paths']), 2)} node-disjoint relay paths "
                    "exist per message in the living cell (the ACTIVE backbone is nearly a "
                    f"tree), so 'all paths' rarely means {cfg.k_paths}.{cong_txt}{static_txt}",
                    "Pick one reading (duplicate buys loss tolerance with bandwidth; stripe "
                    "saves bandwidth but needs every path) and write its cost into the spec.",
                )
            )

    # VSEPR will oscillate
    if vs:
        nv, dv, ov = vs.get("naive", {}), vs.get("damped", {}), vs.get("off", {})
        cv = vs.get("naive_cell", {})
        n_dem = _m(nv.get("demotions"))
        n_flaps = _m(nv.get("vsepr_flaps"))
        d_flaps = _m(dv.get("vsepr_flaps"))
        a0, a1 = _m(nv.get("active_fraction_start")), _m(nv.get("active_fraction_end"))
        if not n_dem:
            verdict = "partly"
        elif n_flaps and (d_flaps is None or n_flaps > d_flaps):
            verdict = "confirmed"
        else:
            verdict = "refuted" if not n_flaps else "partly"
        txt = (
            "Naive VSEPR (the v1.7d rule, with 'cell average' read as the mean over ACTIVE "
            f"relays: a formalisation) made {_num(_m(nv.get('state_changes_per_min_vsepr')))} "
            f"ACTIVE changes/min and {_num(n_flaps)} VSEPR flaps {per_e2_run} (a node "
            f"reversed within {FLAP_CYCLES} cycles), grew ACTIVE from "
            f"{_pct(a0, 0)} to {_pct(a1, 0)} and cut GHOST time to "
            f"{_pct(_m(nv.get('ghost_time_share')))}."
        )
        if cv:
            txt += (
                " Read literally, with the average over every node of the cell (sleeping ones "
                f"included), it made {_num(_m(cv.get('state_changes_per_min_vsepr')))} "
                f"changes/min and {_num(_m(cv.get('vsepr_flaps')))} flaps."
            )
        h0 = s_row(vsepr="naive", hotspot_fraction=0.0, send_rate=rate0) if s_vs else None
        if settings:
            more = sum(
                1
                for h, r in settings
                if (s_row(vsepr="naive", hotspot_fraction=h, send_rate=r) or {})
                and _m(s_row(vsepr="naive", hotspot_fraction=h, send_rate=r)["vsepr_flaps"])
                > (_m(s_row(vsepr="damped", hotspot_fraction=h, send_rate=r)["vsepr_flaps"]) or 0)
            )
            txt += (
                f" The rates rest on the assumed hotspot ({_pct(cfg.hotspot_fraction, 0)} of "
                "traffic to one node)"
                + (
                    f": with none, the naive rule made "
                    f"{_num(_m(h0['state_changes_per_min_vsepr']))} changes/min and "
                    f"{_num(_m(h0['vsepr_flaps']))} flaps at {rate0:g} msg/s"
                    if h0
                    else ""
                )
                + f"; it flapped more than the damped rule in {more} of {len(settings)} "
                f"sensitivity settings ({sweep_txt})."
            )
        prom = {r["vsepr_promote"]: r for r in s_prom}
        if {0, 1} <= set(prom):
            p0, p1 = prom[0], prom[1]
            p_def = prom.get(cfg.vsepr_promote)
            txt += (
                " ACTIVE grows because the cold nodes promoted for a demoted relay rarely "
                "restore the backbone, so CDS repair promotes more, and nothing ever shrinks "
                "the set: with one promotion per demotion the rule itself nets zero, yet repair "
                f"added {_num(_m(p1['vsepr_repair_promotions']))} nodes per run and ACTIVE "
                f"ended at {_pct(_m(p1['active_fraction_end']), 0)}; with none, repair alone "
                f"replaced the demoted relays ({_num(_m(p0['vsepr_repair_promotions']))} "
                f"promoted for {_num(_m(p0['demotions']))} demoted) and ACTIVE ended at "
                f"{_pct(_m(p0['active_fraction_end']), 0)}"
                + (
                    f"; with the journal's {cfg.vsepr_promote}, at "
                    f"{_pct(_m(p_def['active_fraction_end']), 0)}."
                    if p_def
                    else "."
                )
            )
        cand = _m(dv.get("vsepr_candidates"))
        if cand is not None:
            txt += (
                f" Damped: {_num(_m(dv.get('state_changes_per_min_vsepr')))} changes/min and "
                f"{_num(d_flaps)} VSEPR flaps, because it barely acts: of {_num(cand)} "
                f"candidates per run the cooldown skipped "
                f"{_num(_m(dv.get('vsepr_cooldown_skips')))}, and for "
                f"{_num(_m(dv.get('vsepr_no_swap_any')))} no one-for-one swap with any "
                "non-ACTIVE node keeps a valid backbone, so it demoted "
                f"{_num(_m(dv.get('demotions')))}. Its low flap count is inactivity, not "
                f"damping. Under it {_pct(_m(dv.get('share_to_asleep')))} of messages go to "
                f"sleeping devices against {_pct(_m(nv.get('share_to_asleep')))} under naive, "
                f"and resonance alone still makes {_num(_m(dv.get('flaps')))} flaps "
                f"{per_e2_run} (VSEPR off: {_num(_m(ov.get('flaps')))})."
            )
        else:
            txt += (
                f" Damped: {_num(_m(dv.get('state_changes_per_min_vsepr')))} changes/min, "
                f"{_num(d_flaps)} flaps."
            )
        out.append(
            _finding(
                "vsepr-oscillation",
                "VSEPR will oscillate",
                PROBLEM,
                "Part VII · Open problems (v1.7d)",
                verdict,
                txt,
                "Give damping a feasible move set before judging it (a 2-for-1 swap, or "
                "STANDBY nodes that relay), check every demotion against the backbone, then "
                "test the gaming case (flood a node to force it out).",
            )
        )

        r_n, r_d, r_o = (_m(v.get("mean_max_avg_load_ratio")) for v in (nv, dv, ov))
        p_n, p_d, p_o = (_m(v.get("mean_peak_relay_load")) for v in (nv, dv, ov))
        f_n, f_d, f_o = (_m(v.get("active_fraction_mean")) for v in (nv, dv, ov))
        if None not in (r_n, r_d, r_o, p_n, p_d, p_o) and n_dem:
            # balancing is judged on the max/avg ratio (a lower peak from simply having more
            # relays is not balancing); the damped rule is the equal-ACTIVE-set test
            balanced_n = r_n < 0.95 * r_o
            balanced_d = r_d < 0.95 * r_o
            if balanced_n and balanced_d:
                flat_verdict = "confirmed"
            elif balanced_n or balanced_d:
                flat_verdict = "partly"
            else:
                flat_verdict = "refuted"
            if r_n > 1.05 * r_o:
                shape = "less even, not flatter"
            elif balanced_n:
                shape = "flatter"
            else:
                shape = "no flatter"
            scaled = p_o * f_o / f_n if (f_n and f_o) else None
            txt = (
                f"Per {cfg.vsepr_period:g} s cycle the busiest relay's load over the mean "
                f"relay load (1.0 = flat) was {_num(r_n, 2)} under naive VSEPR against "
                f"{_num(r_o, 2)} without it: load got {shape}. The busiest relay did carry "
                f"{_num(p_n)} msg/s against {_num(p_o)} ({_change(p_n, p_o)}), but the "
                f"ACTIVE set also grew from {_pct(f_o, 0)} to {_pct(f_n, 0)} of the cell"
                + (
                    f", and the no-VSEPR peak spread over that many relays is {_num(scaled)} msg/s"
                    if scaled is not None
                    else ""
                )
                + f". At an equal ACTIVE set ({_pct(f_d, 0)}) the damped rule gave peak "
                f"{_num(p_d)} msg/s ({_change(p_d, p_o)}) and ratio {_num(r_d, 2)} after "
                f"{_num(_m(dv.get('demotions')))} demotions per run, so whether a rotation "
                "rule can balance load at all is not shown."
            )
            if settings:
                flat = sum(
                    1
                    for h, r in settings
                    if (s_row(vsepr="naive", hotspot_fraction=h, send_rate=r) or {})
                    and _m(
                        s_row(vsepr="naive", hotspot_fraction=h, send_rate=r)[
                            "mean_max_avg_load_ratio"
                        ]
                    )
                    < 0.95
                    * _m(
                        s_row(vsepr="off", hotspot_fraction=h, send_rate=r)[
                            "mean_max_avg_load_ratio"
                        ]
                    )
                )
                h0o = s_row(vsepr="off", hotspot_fraction=0.0, send_rate=rate0)
                txt += (
                    (
                        f" With no hotspot (an assumption: the default sends "
                        f"{_pct(cfg.hotspot_fraction, 0)} of traffic to one node) the naive "
                        f"ratio was {_num(_m(h0['mean_max_avg_load_ratio']), 2)} against "
                        f"{_num(_m(h0o['mean_max_avg_load_ratio']), 2)};"
                        if h0 and h0o
                        else ""
                    )
                    + f" naive was at least 5% flatter than no VSEPR in {flat} of "
                    f"{len(settings)} sensitivity settings ({sweep_txt})."
                )
            out.append(
                _finding(
                    "vsepr-flattening",
                    "VSEPR flattens load: hotspots self-cancel",
                    CLAIM,
                    "v1.7d · EFFECT",
                    flat_verdict,
                    txt,
                    "Judge any balancing rule at a fixed ACTIVE count (adding relays lowers "
                    "the peak by itself), and find where the peak sits before choosing what "
                    "to rotate.",
                )
            )

    # Resonance's own cost, at a fixed backbone size
    res_rows = s_res.get("rows") or []
    if res_rows:
        rr = sorted({r["send_rate"] for r in res_rows})
        lo_r, hi_r = rr[0], rr[-1]
        on_lo = _row(res_rows, resonance="on", send_rate=lo_r)
        off_lo = _row(res_rows, resonance="off", send_rate=lo_r)
        on_hi = _row(res_rows, resonance="on", send_rate=hi_r)
        off_hi = _row(res_rows, resonance="off", send_rate=hi_r)
        if on_lo and off_lo:
            f_on, h_on, h_off = (
                _m(on_lo["flaps"]),
                _m(on_lo["mean_hops"]),
                _m(off_lo["mean_hops"]),
            )
            costly = bool(f_on) and (
                (h_on or 0) > 1.05 * (h_off or 0)
                or (
                    on_hi
                    and off_hi
                    and (_m(on_hi["drops_congestion"]) or 0)
                    > 1.5 * (_m(off_hi["drops_congestion"]) or 0)
                )
            )
            hi_txt = ""
            if on_hi and off_hi and hi_r != lo_r:
                hi_txt = (
                    f" At {hi_r:g} msg/s congestion drops went from "
                    f"{_num(_m(off_hi['drops_congestion']), 0)} to "
                    f"{_num(_m(on_hi['drops_congestion']), 0)} per run and the deliverable "
                    f"ratio from {_pct(_m(off_hi['deliverable_ratio']))} to "
                    f"{_pct(_m(on_hi['deliverable_ratio']))}."
                )
            base_txt = ""
            if vs:
                base_txt = (
                    " The same resonance runs inside every VSEPR comparison: the damped and "
                    f"VSEPR-off cells of E2 make {_num(_m(vs.get('damped', {}).get('flaps')))} "
                    f"and {_num(_m(vs.get('off', {}).get('flaps')))} flaps {per_e2_run} with "
                    "almost no VSEPR moves."
                )
            out.append(
                _finding(
                    "resonance-cost",
                    "Resonance flaps and lengthens paths",
                    PROBLEM,
                    "v1.7b · Resonance",
                    "confirmed" if costly else "refuted",
                    f"With VSEPR off (so the backbone keeps its size), resonance at the assumed "
                    f"{cfg.resonance_period:g} s period and {cfg.resonance_swaps} swaps per "
                    "round (the journal says 'continuously') made "
                    f"{_num(f_on)} flaps per {_num(s_res.get('duration'), 0)} s run "
                    f"({_num(_m(on_lo['state_changes_per_min_resonance']))} ACTIVE changes/min) "
                    f"against {_num(_m(off_lo['flaps']))} without it, and with it the mean path "
                    f"grew from {_num(h_off, 2)} to {_num(h_on, 2)} hops at {lo_r:g} msg/s."
                    f"{hi_txt}{base_txt}",
                    "Choose the period from a flap budget and only swap a relay out for one "
                    "that keeps paths as short; then measure whether rotation spreads wear "
                    "at all.",
                )
            )

    # Captains are not elected yet
    if rec:
        k50, k60, k100 = rec.get("kill50", {}), rec.get("kill60", {}), rec.get("kill100", {})
        n_cell = recov.get("n")
        kill_at = recov.get("kill_at")
        cc = cfg.captain_count
        tie = ""
        if (
            kill_at is not None
            and abs(kill_at / cfg.vsepr_period - round(kill_at / cfg.vsepr_period)) < 1e-9
        ):
            tie = (
                f"; the kill at t = {kill_at:g} s shares an instant with a VSEPR tick, which runs "
                "just after it"
            )
        reel = " / ".join(_num(_m(rec[c].get("captain_reelections"))) for c in rec)
        out.append(
            _finding(
                "captain-election",
                "Captains are not elected yet",
                PROBLEM,
                "Part VII · Open problems (v1.7c)",
                "partly",
                f"Rule written and exercised: term k elects the {cc} believed-alive "
                f"non-GHOST nodes with the smallest (id - {cc}k) mod n, re-electing as soon "
                f"as a captain's death is detected ({reel} re-elections per run for "
                f"{'/'.join(rec)}). A captain job runs only while some captain is truly "
                f"alive and awake: {_num(_m(k100.get('skipped_cycles')))} VSEPR cycles "
                f"skipped per kill100 run{tie}. "
                "Split-brain is not modelled: the view stays global even when the survivors "
                f"are physically split (kill50: split for "
                f"{_range(k50.get('view_split_s'))} s per run).",
                "Define what each side of a split does, then simulate a partition.",
            )
        )

        # RTO arithmetic
        fd100 = _m(k100.get("first_delivery_after_kill_s"))
        rto100 = _m(k100.get("rto_service_s"))
        rto60 = _m(k60.get("rto_service_s"))
        f100 = _m(k100.get("rto_journal_formula_s"))
        f60 = _m(k60.get("rto_journal_formula_s"))
        rpo_lo = min(
            (v for v in (_m(c.get("rpo_s"), "min") for c in rec.values()) if v is not None),
            default=None,
        )
        rpo_hi = max(
            (v for v in (_m(c.get("rpo_s"), "max") for c in rec.values()) if v is not None),
            default=None,
        )

        def vs_formula(m, f) -> str:
            if m is None or f is None:
                return "against"
            if abs(m - f) <= 0.25:
                return "in line with"
            return "sooner than" if m < f else "later than"

        base_load = cfg.send_rate / cfg.relay_capacity
        heavy = sorted({r["load_ratio"] for r in s_rto if r["load_ratio"] > base_load})
        load_txt = ""
        if heavy:
            hl = heavy[-1]
            pairs = sorted(
                {(r["send_rate"], r["relay_capacity"]) for r in s_rto if r["load_ratio"] == hl}
            )

            def heavy_rows(case: str) -> list[dict]:
                return [r for r in s_rto if r["case"] == case and r["load_ratio"] == hl]

            def base_rows(case: str) -> list[dict]:
                return [r for r in s_rto if r["case"] == case and r["load_ratio"] == base_load]

            load_txt = (
                " That holds while the rebuilt backbone has spare capacity, at the assumed "
                f"{cfg.send_rate:g} msg/s against {cfg.relay_capacity:g} msg/s per relay "
                f"(both assumptions; only their ratio matters): at a load ratio of {hl:g} ("
                + " and ".join(f"{a:g}/{b:g}" for a, b in pairs)
                + ") partial death came back after "
                f"{_rows_span(heavy_rows('kill60'), 'rto_service_s', lambda x: _num(x))} s "
                "and total death after "
                f"{_rows_span(heavy_rows('kill100'), 'rto_service_s', lambda x: _num(x))} s, "
                "with "
                f"{_rows_span(heavy_rows('kill60'), 'drops_congestion', lambda x: _num(x, 0))}"
                " congestion drops per partial-death run against "
                f"{_rows_span(base_rows('kill60'), 'drops_congestion', lambda x: _num(x, 0))}."
                " Mitosis refills the empty slots as STANDBY, so the rebuilt backbone is only "
                "what CDS repair promotes."
            )
        base_rto = rto100 if rto100 is not None else fd100
        verdict = (
            "confirmed" if (base_rto is not None and base_rto > cfg.meiosis_time) else "partly"
        )
        out.append(
            _finding(
                "rto-arithmetic",
                "RTO is detection plus rebuild, not rebuild alone"
                if verdict == "confirmed"
                else "RTO arithmetic",
                PROBLEM,
                "Part VII · Open problems: “RTO arithmetic” (v1.7e)",
                verdict,
                f"Measured from the failure instant, total death (meiosis) served again after "
                f"{_range(k100.get('rto_service_s'), 2)} s (first delivery "
                f"{_num(fd100, 2)} s), {vs_formula(rto100, f100)} the formula's "
                f"{_num(f100)} s, and partial death ({_num(_m(k60.get('killed')), 0)} of "
                f"{n_cell if n_cell is not None else 'n/a'}, mitosis) after "
                f"{_range(k60.get('rto_service_s'), 2)} s, {vs_formula(rto60, f60)} its "
                f"{_num(f60)} s: RTO is detection plus rebuild, not the rebuild alone. RPO "
                f"{_num(rpo_lo)}–{_num(rpo_hi)} s. Detection ({cfg.detect_delay:g} s) and "
                f"rebuild ({cfg.mitosis_time:g} s) are inputs from the journal, so this "
                f"confirms the arithmetic by construction, not the timings.{load_txt}",
                "Quote RTO from the failure; measure detection on a real gossip "
                f"implementation instead of assuming {cfg.detect_delay:g} s, and size relays "
                "for the rebuilt backbone, not the healthy one.",
            )
        )

        if k50:
            d50 = k50.get("death_event")
            never = d50 is False
            rto50 = _m(k50.get("rto_service_s"))
            refill50 = _m(k50.get("refill_after_kill_s"), "min")
            arq = cfg.max_retries * cfg.retry_timeout  # resends can straddle the refill
            when = (
                "once"
                if (rto50 is not None and refill50 is not None and rto50 >= refill50 - arq)
                else "before"
            )
            heavy50 = ""
            if heavy:
                rows50 = [
                    r for r in s_rto if r["case"] == "kill50" and r["load_ratio"] == heavy[-1]
                ]
                if rows50:
                    heavy50 = (
                        f" (at a load ratio of {heavy[-1]:g}: "
                        f"{_rows_span(rows50, 'rto_service_s', lambda x: _num(x))} s)"
                    )
            out.append(
                _finding(
                    "death-threshold",
                    "Killing exactly half: 'more than half' never fires",
                    PROBLEM,
                    "v1.7e · DEATH rule vs Figure 9",
                    "confirmed" if never else "refuted",
                    f"Killing {_num(_m(k50.get('killed')), 0)} of "
                    f"{n_cell if n_cell is not None else 'n/a'} "
                    f"{'never' if never else 'sometimes'} raised CELL_DEATH_EVENT, so no "
                    f"mitosis ran: the deliverable ratio fell to "
                    f"{_pct(_m(k50.get('min_ratio_after_kill')), 0)} and service came back "
                    f"after {_range(k50.get('rto_service_s'))} s{heavy50}, {when} the empty "
                    f"slots were refilled ({_range(k50.get('refill_after_kill_s'))} s: "
                    f"detection plus rejoin_delay = {cfg.rejoin_delay:g} s, an assumption), "
                    f"against {_range(k60.get('rto_service_s'))} s when "
                    f"{_num(_m(k60.get('killed')), 0)} died and mitosis ran. Until the "
                    f"rejoin the believed survivors were split into separate parts "
                    f"({_range(k50.get('view_split_s'))} s per run), so no single backbone "
                    "could exist.",
                    "Trigger mitosis on loss of backbone connectivity (or 'at least half'), "
                    "not on a strict head count.",
                )
            )

    # Offline delivery
    rows = off.get("rows") or []
    grows = off.get("ghost_pool_rows") or []
    if rows:
        base = _row(rows, active_fraction=cfg.active_fraction) or rows[0]
        share = _m(base["share_to_asleep"])
        shares = " / ".join(_pct(_m(r["share_to_asleep"])) for r in rows)
        afs = "/".join(f"{r['active_fraction']:g}" for r in rows)
        init = " / ".join(_pct(_m(r["initial_active_fraction"]), 0) for r in rows)
        gtxt = ""
        if grows:
            gtxt = (
                " Changing the sleeping pool instead (standby_fraction "
                + "/".join(f"{r['standby_fraction']:g}" for r in grows)
                + " of the non-ACTIVE nodes) gave "
                + " / ".join(_pct(_m(r["share_to_asleep"])) for r in grows)
                + "."
            )
        nv, dv, ov = (vs.get(k, {}) for k in ("naive", "damped", "off"))
        var_txt = ""
        if nv and dv and ov:
            var_txt = (
                " The share follows the size of the sleeping pool: "
                f"{_pct(_m(nv.get('share_to_asleep')))} under naive VSEPR, which keeps "
                f"{_pct(_m(nv.get('active_fraction_mean')), 0)} of the cell ACTIVE, "
                f"{_pct(_m(dv.get('share_to_asleep')))} with the damped rule and "
                f"{_pct(_m(ov.get('share_to_asleep')))} with VSEPR off"
            )
            h0s = [
                s_row(vsepr=v, hotspot_fraction=0.0, send_rate=rate0)
                for v in ("naive", "damped", "off")
            ]
            if all(h0s):
                var_txt += (
                    "; with no hotspot (an assumption) "
                    + " / ".join(_pct(_m(r["share_to_asleep"])) for r in h0s)
                    + " (naive / damped / off)"
                )
            var_txt += "."
        delivered_txt = ""
        dshare = _m(nv.get("to_asleep_delivered_share")) if nv else None
        if dshare is not None:
            delivered_txt = (
                f", and a resend that found the device awake delivered {_pct(dshare)} of those"
            )
        c60_greedy = c60["cds_greedy"] if c60 else None
        c60_found = c60.get("cds_search") if c60 else None
        floor_txt = (
            f"the greedy CDS builder ({c60_greedy} nodes"
            + (
                f"; a {c60_found}-node valid set exists"
                if c60_found is not None and c60_greedy is not None and c60_found < c60_greedy
                else ""
            )
            + "), not the setting, decides"
            if c60_greedy is not None
            else "the CDS construction, not the setting, decides"
        )
        verdict = "confirmed" if share and share >= 0.05 else ("partly" if share else "refuted")
        out.append(
            _finding(
                "offline-delivery",
                "Messages to sleeping devices are lost" if share else "Offline delivery",
                PROBLEM,
                "Part VII · Open problems: “Offline delivery”",
                verdict,
                "Nothing stores and forwards, so a message to a device the cell believes "
                "asleep (GHOST) is dropped unless a resend finds it awake: in the default cell "
                f"{_pct(share)} of messages went to a sleeping device{delivered_txt}.{var_txt} "
                f"active_fraction {afs} gave {shares}: the cell starts at {init} ACTIVE "
                f"either way, because {floor_txt}.{gtxt} The store-and-forward design itself "
                "is not simulated.",
                "Decide who stores and forwards (read Briar and Scuttlebutt); a mailbox on "
                "the GHOST node's ACTIVE neighbours is the smallest experiment.",
            )
        )

    out.append(
        _finding(
            "gateway-server",
            "The gateway is a server",
            PROBLEM,
            "Part VII · Open problems",
            "not simulated",
            "The gateway is modelled as an external store that never fails (it holds "
            "checkpoints and runs meiosis), so total-death recovery depends on it by "
            "construction. Removing it is not simulated.",
            "Name it infrastructure, or move its jobs to the stems one at a time.",
        )
    )
    out.append(
        _finding(
            "push-wake",
            "Waking a phone needs push",
            PROBLEM,
            "Part VII · Open problems (v1.7a)",
            "not simulated",
            "GHOST nodes change state the instant a captain decides; no APNs/FCM wake "
            f"latency is modelled, so the journal's {JOURNAL_FLASH_WAKE_MS} ms flash-wake "
            "target is untested here.",
            "Measure real wake latency on one phone, then requote flash wake.",
        )
    )
    out.append(
        _finding(
            "group-rekeying",
            "Group token rekeying",
            PROBLEM,
            "Part VII · Open problems (v1.6)",
            "not simulated",
            "No security layer is simulated: tokens, weekly rotation and MLS are out of scope.",
            "Read MLS (RFC 9420) and model member removal cost.",
        )
    )
    c20 = next((r for r in topo if r["cage"] == "C20"), None)
    if c20 is not None:
        lo, hi = JOURNAL_C20_USER_BAND
        fits = hi <= c20["n"]
        out.append(
            _finding(
                "c20-count",
                f"A full C20 holds {c20['n']} devices, not {hi} users"
                if not fits
                else f"C20 fits the {lo} to {hi} user band",
                PROBLEM,
                "Part VII · Open problems: “What the number in C20 counts” (v1.7, Figure 3)",
                "confirmed",
                f"Built from coordinates, C20 has {c20['n']} nodes, {c20['links']} links, "
                f"{c20['faces']} faces and diameter {c20['diameter']}. The simulator counts "
                f"nodes, so a full C20 holds {c20['n']} devices and the journal's {lo} to "
                f"{hi} user band {'fits' if fits else 'does not fit'}.",
                f"Restate the bands as node counts (C20 = {lo} to {c20['n']} users).",
            )
        )
    return out


# --------------------------------------------------------------------------- markdown
def _cell(d, digits: int = 2, pct: bool = False) -> str:
    if not isinstance(d, dict):
        return "n/a" if d is None else str(d)
    if d.get("mean") is None:
        return "n/a"
    f = (lambda v: f"{100 * v:.1f}%") if pct else (lambda v: f"{v:.{digits}f}")
    if abs(d["max"] - d["min"]) < 1e-12:
        return f(d["mean"])
    return f"{f(d['mean'])} [{f(d['min'])}, {f(d['max'])}]"


def provenance_table() -> str:
    lines = [
        "| Parameter | Default | Source |",
        "|---|---|---|",
    ]
    for p in Config.provenance():
        if p["name"] in ("seed", "record_frames"):
            continue
        lines.append(f"| `{p['name']}` | {p['default']} | {p['src']}: {p['doc']} |")
    return "\n".join(lines)


E4_HEADER = (
    "| Routing | Send rate | Link loss | Deliverable ratio | Tx / delivered | "
    "Duplicates / delivered | Out-of-order / delivered | Congestion drops | "
    "Disjoint paths / msg | ACTIVE share (mean) |"
)
E4_RULE = "|---|---|---|---|---|---|---|---|---|---|"
PCT_KEYS = {
    "active_fraction_start",
    "active_fraction_end",
    "active_fraction_mean",
    "deliverable_ratio",
    "delivery_ratio",
    "ghost_time_share",
    "share_to_asleep",
    "to_asleep_delivered_share",
    "min_ratio_after_kill",
}


def _e4_line(r: dict) -> str:
    return (
        f"| {r['routing']} | {r['send_rate']:g} | {r['link_loss']:g} | "
        f"{_cell(r['deliverable_ratio'], 2, True)} | {_cell(r['tx_per_delivered'])} | "
        f"{_cell(r['duplicates_per_delivered'], 3)} | "
        f"{_cell(r['out_of_order_per_delivered'], 4)} | "
        f"{_cell(r['congestion_drops'], 0)} | {_cell(r['mean_paths'])} | "
        f"{_cell(r.get('active_fraction_mean'), 2, True)} |"
    )


def _metric_table(rows: list[dict], keys: Sequence[str], metrics: Sequence[str]) -> list[str]:
    """Rows of settings (``keys``) by metrics, each cell mean [min, max]."""
    head = "| " + " | ".join(list(keys) + list(metrics)) + " |"
    out = [head, "|" + "---|" * (len(keys) + len(metrics))]
    for r in rows:
        cells = [f"{r[k]:g}" if isinstance(r[k], (int, float)) else str(r[k]) for k in keys]
        cells += [_cell(r.get(m), 2, m in PCT_KEYS) for m in metrics]
        out.append("| " + " | ".join(cells) + " |")
    return out


def results_markdown(res: dict) -> str:
    L: list[str] = []
    seeds = (res.get("vsepr") or {}).get("seeds", [])
    L.append("# BMFP simulator results")
    L.append("")
    L.append(
        "Generated by `bmfp experiments --out reports/`. Cells are mean [min, max] over seeds "
        f"{seeds} unless a table says otherwise. Every journal timing used below (3 s detection, "
        "1.5 s mitosis/meiosis, 10 s checkpoints, 30 s VSEPR, 2x threshold, 5-minute captain "
        "terms, 3 stems) is an *input*, not a result. E7 varies the main ASSUMPTIONS (hotspot, "
        "send rate, relay capacity, resonance, promotions per demotion) to show which findings "
        "depend on them."
    )
    L.append("")
    L.append("## Parameters: journal inputs vs assumptions")
    L.append("")
    L.append(provenance_table())
    L.append("")
    topo = res.get("topology") or []
    if topo:
        L.append("## E1 · Topology")
        L.append("")
        L.append(
            "| Cage | Solid | Nodes | Links | Degree | Diameter | Min vertex cut | Faces | "
            "P(split) k=1 | k=2 | k=3 | k=4 | k=5 | k=6 | CDS floor (n-2)/2 | Greedy CDS | "
            "Smallest CDS found (stems kept) | Exact min CDS |"
        )
        L.append("|" + "---|" * 18)
        for r in topo:
            pp = r["partition_probability"]
            ex = r.get("partition_exact", [True] * 6)
            cells = [f"{pp[str(k)]:.4f}{'' if ex[k - 1] else '*'}" for k in range(1, 7)]
            L.append(
                f"| {r['cage']} | {r.get('solid', '')} | {r['n']} | {r['links']} | {r['degree']} | "
                f"{r['diameter']} | {r['min_vertex_cut']} | {r['faces']} | "
                + " | ".join(cells)
                + f" | {r['cds_lower_bound']} | {r['cds_greedy']} | "
                f"{r.get('cds_search', 'n/a')} | "
                f"{r['cds_exact'] if r['cds_exact'] is not None else 'not searched'} |"
            )
        L.append("")
        L.append(
            "P(split) = share of k-node removals that disconnect the survivors; exact enumeration "
            f"unless marked * (Monte Carlo, {FULL.e1_trials} samples in the full suite). CDS = "
            "connected dominating set, the formal 'valid ACTIVE set'. Greedy CDS = the builder "
            "the simulator starts every cell with (stems first); smallest found = a seeded "
            "randomised search that keeps the three stems (an upper bound: it proves a CDS that "
            "small exists); exact = branch-and-bound search. C12 and C24 are ASSUMPTIONS (the "
            "journal names C20 and C60)."
        )
        L.append("")
        if any(r["cage"] == "C12" for r in topo):
            f6 = figure6_ring()
            L.append(
                f"Figure 6 as drawn (a {f6['n']}-node ring, ACTIVE nodes "
                f"{', '.join(str(v) for v in f6['drawn_active'])}): the drawn set dominates the "
                f"ring: {f6['drawn_dominating']}; it is a CDS: {f6['drawn_cds']}. Minimum "
                f"dominating set {f6['min_dominating']}, minimum CDS {f6['min_cds']} (exact)."
            )
            L.append("")
    vs = res.get("vsepr")
    if vs:
        names = list(vs["variants"])
        L.append(f"## E2 · VSEPR variants (C60, {vs['duration']:g} s)")
        L.append("")
        L.append("| Metric | " + " | ".join(E2_LABELS.get(v, v) for v in names) + " |")
        L.append("|---|" + "---|" * len(names))
        for m in E2_METRICS:
            L.append(
                f"| {m} | "
                + " | ".join(_cell(vs["variants"][v].get(m), 2, m in PCT_KEYS) for v in names)
                + " |"
            )
        L.append("")
        L.append(
            "naive reads v1.7d's 'twice the cell average' as twice the mean load of the ACTIVE "
            "relays (FORMALISATION); naive_cell reads it literally, as the mean over every "
            "believed-alive node, sleeping ones included. state_changes_per_min = "
            "ACTIVE<->non-ACTIVE transitions made by VSEPR (incl. its CDS "
            "repair), fairness and resonance; the _vsepr / _resonance rows split it by source. "
            "Fairness only moves GHOST<->STANDBY (fairness_moves_per_min). flaps = a node "
            f"reversing its last ACTIVE transition within {FLAP_CYCLES} VSEPR cycles "
            f"({FLAP_CYCLES * Config().vsepr_period:g} s); vsepr_flaps = those where VSEPR made "
            "one of the two moves. vsepr_repair_promotions = nodes the CDS repair promoted after "
            "a VSEPR cycle. vsepr_candidates = nodes above the threshold, summed over cycles; "
            "for the damped rule, vsepr_cooldown_skips were skipped by the cooldown, "
            "vsepr_no_swap had no allowed one-for-one swap that keeps a CDS and "
            "vsepr_no_swap_any had none with any non-ACTIVE node. mean_max_avg_load_ratio = per "
            "cycle, the busiest ACTIVE relay's load over the mean ACTIVE relay load; "
            "mean_peak_relay_load and mean_avg_relay_load are that numerator and denominator in "
            "msg-equivalents relayed per second, so a change in the size of the ACTIVE set shows "
            "up instead of hiding in the ratio. to_asleep_delivered_share = of the messages sent "
            "to a sleeping device, the share a resend still delivered."
        )
        L.append("")
    rec = res.get("recovery")
    if rec:
        L.append(
            f"## E3 · Recovery after a scripted kill (C60, kill at t={rec['kill_at']:g} s, "
            f"{rec['duration']:g} s runs)"
        )
        L.append("")
        cases = list(rec["cases"])
        L.append("| Metric | " + " | ".join(cases) + " |")
        L.append("|---|" + "---|" * len(cases))
        for m in ("death_event", "path"):
            L.append(f"| {m} | " + " | ".join(str(rec["cases"][c][m]) for c in cases) + " |")
        pct3 = {"baseline_ratio", "min_ratio_after_kill", "ratio_dip"}
        for m in E3_METRICS:
            label = f"{m} *({E3_INPUT_ROWS[m]})*" if m in E3_INPUT_ROWS else m
            L.append(
                f"| {label} | "
                + " | ".join(_cell(rec["cases"][c][m], 2, m in pct3) for c in cases)
                + " |"
            )
        L.append("")
        L.append(
            "Rows marked *inputs* restate configured values (journal inputs and the rejoin_delay "
            "assumption); they are not measurements. rto_service_s: from the kill to the first "
            "delivered message at which the service is back: its 0.1 s step, its first second "
            "and 10 forward 5 s windows (1 s apart) all have a deliverable ratio >= 95% of the "
            "pre-kill baseline. Outcomes are timed when they happen (arrival, or the last "
            "attempt of a dropped message) and sends offered while no node is alive count as "
            "unserved, so no instant without service can qualify. It can precede the rebuild "
            "only where ARQ resends carry the last pre-rebuild messages across it. "
            "view_split_s: seconds the believed-alive nodes were split into separate parts. "
            "RPO = kill time - last checkpoint. All at the assumed 20 msg/s and 40 msg/s relay "
            "capacity; E7 varies both."
        )
        L.append("")
    hell = res.get("hell")
    if hell:
        L.append(f"## E4 · Hell mode readings (C60, {hell['duration']:g} s, seeds {hell['seeds']})")
        L.append("")
        L.append("Living cell (default Config: naive VSEPR and resonance on).")
        L.append("")
        L.append(E4_HEADER)
        L.append(E4_RULE)
        for r in hell["rows"]:
            L.append(_e4_line(r))
        L.append("")
        if hell.get("fixed_rows"):
            L.append(
                "Frozen backbone (extension: "
                + ", ".join(f"{k}={v}" for k, v in hell["fixed_cell"].items())
                + "). Naive VSEPR resizes the backbone in response to each routing mode's load, "
                "so the living-cell rows above compare different ACTIVE sets; these rows give "
                "every mode the same one."
            )
            L.append("")
            L.append(E4_HEADER)
            L.append(E4_RULE)
            for r in hell["fixed_rows"]:
                L.append(_e4_line(r))
            L.append("")
        if hell.get("static_rows"):
            L.append(
                "Static-fullerene rows (extension, ASSUMPTION: "
                + ", ".join(f"{k}={v}" for k, v in hell["static_cell"].items())
                + "). Hell mode is a v1.2 feature, older than the ACTIVE/STANDBY/GHOST states, "
                "so this is the cell it was designed for: every node relays."
            )
            L.append("")
            L.append(E4_HEADER)
            L.append(E4_RULE)
            for r in hell["static_rows"]:
                L.append(_e4_line(r))
            L.append("")
    off = res.get("offline")
    if off:
        L.append(f"## E5 · Offline delivery (C60, {off['duration']:g} s)")
        L.append("")
        L.append(
            "| active_fraction (config) | Share sent to a GHOST device | Initial ACTIVE share | "
            "GHOST time share | Delivery ratio (all) |"
        )
        L.append("|---|---|---|---|---|")
        for r in off["rows"]:
            L.append(
                f"| {r['active_fraction']:g} | {_cell(r['share_to_asleep'], 2, True)} | "
                f"{_cell(r['initial_active_fraction'], 2, True)} | "
                f"{_cell(r['ghost_time_share'], 2, True)} | {_cell(r['delivery_ratio'], 2, True)} |"
            )
        L.append("")
        if off.get("ghost_pool_rows"):
            L.append(
                "GHOST pool sweep (extension: the active_fraction sweep above cannot move the "
                "ACTIVE share below the CDS floor, so this varies standby_fraction, the STANDBY "
                "share of the nodes left after ACTIVE, instead):"
            )
            L.append("")
            L.append(
                "| standby_fraction | Share sent to a GHOST device | GHOST time share | "
                "Delivery ratio (all) |"
            )
            L.append("|---|---|---|---|")
            for r in off["ghost_pool_rows"]:
                L.append(
                    f"| {r['standby_fraction']:g} | {_cell(r['share_to_asleep'], 2, True)} | "
                    f"{_cell(r['ghost_time_share'], 2, True)} | "
                    f"{_cell(r['delivery_ratio'], 2, True)} |"
                )
            L.append("")
    ch = res.get("churn")
    if ch:
        L.append(f"## E6 · Churn (C60, {ch['duration']:g} s)")
        L.append("")
        L.append(
            "| Churn (leaves/s) | Deliverable ratio | Stale-view drops | No-route drops | "
            "State changes / min | Leaves |"
        )
        L.append("|---|---|---|---|---|---|")
        for r in ch["rows"]:
            L.append(
                f"| {r['churn_rate']:g} | {_cell(r['deliverable_ratio'], 2, True)} | "
                f"{_cell(r['stale_view_drops'], 1)} | {_cell(r['no_route_drops'], 1)} | "
                f"{_cell(r['state_changes_per_min'], 1)} | {_cell(r['leaves'], 1)} |"
            )
        L.append("")
    se = res.get("sensitivity")
    if se:
        L.append("## E7 · Sensitivity to the assumptions")
        L.append("")
        v7 = se.get("vsepr") or {}
        if v7.get("rows"):
            L.append(
                f"VSEPR variant x hotspot_fraction x send_rate (C60, {v7['duration']:g} s, seeds "
                f"{v7['seeds']}; E2 uses hotspot_fraction {Config().hotspot_fraction:g} and "
                f"{Config().send_rate:g} msg/s):"
            )
            L.append("")
            L.extend(
                _metric_table(
                    v7["rows"], ("vsepr", "hotspot_fraction", "send_rate"), E7_VSEPR_METRICS
                )
            )
            L.append("")
        r7 = se.get("rto") or {}
        if r7.get("rows"):
            L.append(
                f"Recovery x load (C60, kill at t={r7['kill_at']:g} s, {r7['duration']:g} s, "
                f"seeds {r7['seeds']}; load_ratio = send_rate / relay_capacity, E3 uses "
                f"{Config().send_rate / Config().relay_capacity:g}):"
            )
            L.append("")
            L.extend(
                _metric_table(
                    r7["rows"],
                    ("case", "send_rate", "relay_capacity", "load_ratio"),
                    E7_RTO_METRICS,
                )
            )
            L.append("")
        s7 = se.get("resonance") or {}
        if s7.get("rows"):
            L.append(
                f"Resonance on vs off with VSEPR {s7.get('vsepr', 'off')} (C60, "
                f"{s7['duration']:g} s, seeds {s7['seeds']}; resonance_period "
                f"{Config().resonance_period:g} s and {Config().resonance_swaps} swaps per round "
                "are ASSUMPTIONS):"
            )
            L.append("")
            L.extend(_metric_table(s7["rows"], ("resonance", "send_rate"), E7_RES_METRICS))
            L.append("")
        p7 = se.get("promote") or {}
        if p7.get("rows"):
            L.append(
                f"Naive VSEPR with 0, 1 or 2 promotions per demotion (C60, {p7['duration']:g} s, "
                f"seeds {p7['seeds']}; the journal says {Config().vsepr_promote}):"
            )
            L.append("")
            L.extend(_metric_table(p7["rows"], ("vsepr_promote",), E7_PROMOTE_METRICS))
            L.append("")
    fs = res.get("findings") or []
    if fs:
        L.append("## Findings")
        L.append("")
        L.append(VERDICT_KEY)
        L.append("")
        L.append("| Finding | Kind | Journal ref | Verdict | Measured | Next step |")
        L.append("|---|---|---|---|---|---|")
        for f in fs:
            L.append(
                f"| {f['problem']} | {f.get('kind', '')} | {f['journal_ref']} | "
                f"**{f['verdict']}** | {f['measured']} | {f['next_step']} |"
            )
        L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------- plots
def make_plots(res: dict, out: Path) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    paths: list[Path] = []

    def save(fig, name: str) -> None:
        p = out / name
        fig.tight_layout()
        fig.savefig(p, dpi=110)
        plt.close(fig)
        paths.append(p)

    topo = res.get("topology")
    if topo:
        fig, ax = plt.subplots(figsize=(6, 4))
        for r in topo:
            ks = list(range(1, 7))
            ax.plot(
                ks,
                [r["partition_probability"][str(k)] for k in ks],
                marker="o",
                linewidth=2,
                label=r["cage"],
            )
        ax.set_xlabel("nodes removed (k)")
        ax.set_ylabel("share of removals that split the cell")
        ax.set_title("E1 · partition probability")
        ax.grid(True, linewidth=0.5)
        if ax.get_legend_handles_labels()[0]:
            ax.legend()
        save(fig, "e1_topology.png")
    vs = res.get("vsepr")
    if vs:
        fig, axes = plt.subplots(1, 2, figsize=(9, 3.5))
        names = list(vs["variants"])
        for ax, m, title in (
            (axes[0], "state_changes_per_min_vsepr", "VSEPR ACTIVE changes / min"),
            (axes[1], "active_fraction_end", "ACTIVE fraction at end"),
        ):
            d = [vs["variants"][v][m] for v in names]
            means = [x["mean"] or 0 for x in d]
            lo = [(x["mean"] or 0) - (x["min"] or 0) for x in d]
            hi = [(x["max"] or 0) - (x["mean"] or 0) for x in d]
            ax.bar(names, means, yerr=[lo, hi], capsize=4)
            ax.set_title(title)
            ax.grid(True, axis="y", linewidth=0.5)
        save(fig, "e2_vsepr.png")
    rec = res.get("recovery")
    if rec:
        fig, ax = plt.subplots(figsize=(7, 3.5))
        for cid, case in rec["cases"].items():
            s = case.get("series")
            if not s:
                continue
            ax.plot(
                s["t"], [math.nan if x is None else x for x in s["ratio"]], linewidth=1.5, label=cid
            )
        ax.axvline(rec["kill_at"], linestyle="--", linewidth=1)
        ax.set_xlabel("time (s)")
        ax.set_ylabel("served / offered (1 s, outcome time)")
        ax.set_title(f"E3 · recovery after the kill (seed {rec['seeds'][0]})")
        ax.grid(True, linewidth=0.5)
        if ax.get_legend_handles_labels()[0]:
            ax.legend()
        save(fig, "e3_recovery.png")
    hell = res.get("hell")
    if hell:
        losses = sorted({r["link_loss"] for r in hell["rows"]})
        sets = [("living", hell["rows"])]
        if hell.get("static_rows"):
            sets.append(("static v1.2", hell["static_rows"]))
        fixed = hell.get("fixed_rows") or []
        fixed_cfgs = sorted({(r["send_rate"], r["link_loss"]) for r in fixed})
        n_rows = len(sets) + (1 if fixed_cfgs else 0)
        n_cols = max(len(losses), len(fixed_cfgs))
        fig, axes = plt.subplots(n_rows, n_cols, figsize=(4 * n_cols, 3.3 * n_rows), squeeze=False)
        if fixed_cfgs:
            # one routing per bar: delivery under loss, congestion drops without it
            for ax, (rate, loss) in zip(axes[-1], fixed_cfgs, strict=False):
                rows = [r for r in fixed if r["send_rate"] == rate and r["link_loss"] == loss]
                key, ylab = (
                    ("deliverable_ratio", "deliverable ratio")
                    if loss > 0
                    else ("congestion_drops", "congestion drops per run")
                )
                names = [r["routing"] for r in rows]
                vals = [r[key]["mean"] or 0 for r in rows]
                if loss > 0:  # dots on a zoomed axis (bars would imply a zero baseline)
                    ax.plot(names, vals, "o", markersize=8)
                    ax.set_ylim(max(0.0, min(vals) - 0.05), 1.0)
                else:
                    ax.bar(names, vals)
                ax.set_title(f"E4 · frozen backbone · {rate:g} msg/s, loss {loss:g}")
                ax.set_ylabel(ylab)
                ax.grid(True, axis="y", linewidth=0.5)
            for ax in axes[-1][len(fixed_cfgs) :]:
                ax.axis("off")
        for (label, data), axrow in zip(sets, axes, strict=False):
            for ax, loss in zip(axrow, losses, strict=True):
                for rt in sorted({r["routing"] for r in data}):
                    rows = [r for r in data if r["routing"] == rt and r["link_loss"] == loss]
                    if not rows:
                        continue
                    ax.plot(
                        [r["send_rate"] for r in rows],
                        [r["tx_per_delivered"]["mean"] for r in rows],
                        marker="o",
                        linewidth=2,
                        label=rt,
                    )
                ax.set_title(f"E4 · {label} · link loss {loss:g}")
                ax.set_xlabel("send rate (msg/s)")
                ax.set_ylabel("transmissions per delivered")
                ax.grid(True, linewidth=0.5)
                if ax.get_legend_handles_labels()[0]:
                    ax.legend()
        save(fig, "e4_hell.png")
    off = res.get("offline")
    if off:
        fig, ax = plt.subplots(figsize=(5, 3.5))
        rows = off.get("ghost_pool_rows") or []
        ax.bar(
            [f"sf={r['standby_fraction']:g}" for r in rows],
            [r["share_to_asleep"]["mean"] or 0 for r in rows],
        )
        ax.set_ylabel("share of messages sent to a GHOST")
        ax.set_title("E5 · offline delivery")
        ax.grid(True, axis="y", linewidth=0.5)
        save(fig, "e5_offline.png")
    ch = res.get("churn")
    if ch:
        fig, ax = plt.subplots(figsize=(5, 3.5))
        ax.plot(
            [r["churn_rate"] for r in ch["rows"]],
            [r["deliverable_ratio"]["mean"] for r in ch["rows"]],
            marker="o",
            linewidth=2,
        )
        ax.set_xlabel("churn (leaves/s)")
        ax.set_ylabel("deliverable delivery ratio")
        ax.set_title("E6 · churn")
        ax.grid(True, linewidth=0.5)
        save(fig, "e6_churn.png")
    se = res.get("sensitivity")
    if se:
        fig, axes = plt.subplots(1, 2, figsize=(9, 3.5))
        ax = axes[0]
        v7 = (se.get("vsepr") or {}).get("rows") or []
        rate0 = Config().send_rate
        rates7 = sorted({r["send_rate"] for r in v7})
        r0 = rate0 if rate0 in rates7 else (rates7[0] if rates7 else None)
        for variant in ("naive", "damped", "off"):
            rows = [r for r in v7 if r["vsepr"] == variant and r["send_rate"] == r0]
            if rows:
                ax.plot(
                    [r["hotspot_fraction"] for r in rows],
                    [r["vsepr_flaps"]["mean"] or 0 for r in rows],
                    marker="o",
                    linewidth=2,
                    label=variant,
                )
        ax.set_xlabel("hotspot_fraction (assumption)")
        ax.set_ylabel("VSEPR flaps per run")
        ax.set_title(f"E7 · VSEPR flaps vs hotspot ({r0:g} msg/s)" if r0 else "E7 · VSEPR")
        ax.grid(True, linewidth=0.5)
        if ax.get_legend_handles_labels()[0]:
            ax.legend()
        ax = axes[1]
        r7 = (se.get("rto") or {}).get("rows") or []
        cases = sorted({r["case"] for r in r7})
        loads = list(dict.fromkeys(f"{r['send_rate']:g}/{r['relay_capacity']:g}" for r in r7))
        for i, case in enumerate(cases):
            rows = [r for r in r7 if r["case"] == case]
            xs = [
                loads.index(f"{r['send_rate']:g}/{r['relay_capacity']:g}") + (i - 1) * 0.12
                for r in rows
            ]
            mean = [r["rto_service_s"]["mean"] or 0 for r in rows]
            lo = [m - (r["rto_service_s"]["min"] or 0) for m, r in zip(mean, rows, strict=True)]
            hi = [(r["rto_service_s"]["max"] or 0) - m for m, r in zip(mean, rows, strict=True)]
            ax.errorbar(xs, mean, yerr=[lo, hi], fmt="o", capsize=4, label=case)
        ax.set_xticks(range(len(loads)), loads)
        ax.set_xlabel("send_rate / relay_capacity (assumptions)")
        ax.set_ylabel("service RTO (s)")
        ax.set_title("E7 · recovery vs load (dot: mean, bar: seed range)")
        ax.grid(True, linewidth=0.5)
        if ax.get_legend_handles_labels()[0]:
            ax.legend()
        save(fig, "e7_sensitivity.png")
    return paths


# --------------------------------------------------------------------------- suite
EXPERIMENTS: dict[str, tuple[str, Callable[[Plan], object]]] = {
    "topology": ("e1_topology", e1_topology),
    "vsepr": ("e2_vsepr", e2_vsepr),
    "recovery": ("e3_recovery", e3_recovery),
    "hell": ("e4_hell", e4_hell),
    "offline": ("e5_offline", e5_offline),
    "churn": ("e6_churn", e6_churn),
    "sensitivity": ("e7_sensitivity", e7_sensitivity),
}


def run_suite(
    out: Path | str | None = None,
    plan: Plan = FULL,
    plots: bool = True,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Run E1..E7, generate findings; write JSON/PNG/markdown into ``out`` if given."""
    res: dict = {}
    for key, (_fname, fn) in EXPERIMENTS.items():
        if progress:
            progress(key)
        res[key] = clean(fn(plan))
    res["findings"] = make_findings(res)
    if out is not None:
        write_reports(res, Path(out), plots=plots)
    return res


def write_reports(res: dict, out: Path, plots: bool = True) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for key, (fname, _fn) in EXPERIMENTS.items():
        if key in res:
            (out / f"{fname}.json").write_text(json.dumps(res[key], indent=1) + "\n")
    (out / "findings.json").write_text(json.dumps(res["findings"], indent=1) + "\n")
    (out / "bmfp_results.md").write_text(results_markdown(res) + "\n")
    if plots:
        make_plots(res, out)


def load_reports(path: Path | str) -> dict:
    """Load a previous ``bmfp experiments`` output directory."""
    p = Path(path)
    res = {}
    for key, (fname, _fn) in EXPERIMENTS.items():
        f = p / f"{fname}.json"
        if not f.exists():
            raise FileNotFoundError(f"{f} missing; run `bmfp experiments --out {p}` first")
        res[key] = json.loads(f.read_text())
    res["findings"] = make_findings(res)
    return res


def quick_run(**kw) -> dict:
    """Convenience: one run's summary."""
    return run(**kw).summary
