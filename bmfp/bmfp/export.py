"""Write ``docs/data/bmfp-data.js`` for the portfolio site.

The file contains exactly ``window.BMFP_DATA = <compact json>;`` and is byte-identical
across runs (every run is seeded, dict order is fixed, floats are rounded).
By default the experiment suite is recomputed; ``from_reports`` reuses a previous
``bmfp experiments`` output directory instead (explicit opt-in).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .experiments import FULL, QUICK, Plan, load_reports, run_suite
from .metrics import clean
from .sim import Config, Simulation
from .topology import CAGE_NAMES, cage, diameter

GENERATOR = "bmfp export-web --out docs/data"
PREFIX = "window.BMFP_DATA = "
MAX_EVENTS = 400


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    blurb: str
    overrides: dict


SCENARIOS = (
    Scenario(
        "baseline",
        "Naive VSEPR, as written",
        "The journal's v1.7d rule (inputs): every {vsepr_period:g} s, any non-stem ACTIVE node "
        "above {vsepr_factor:g}x the average load goes GHOST and {vsepr_promote} cold GHOST nodes "
        "are promoted in its place. 'Average' is read as the mean over ACTIVE relays (the "
        "journal says 'cell average'; a formalisation).",
        {"vsepr": "naive", "duration": 600.0},
    ),
    Scenario(
        "damped",
        "Damped VSEPR (proposed fix)",
        "The review's fix, not the journal's rule: a {vsepr_cooldown_cycles}-cycle cooldown, one "
        "replacement per demotion, at most {max_dem_pct:g}% of ACTIVE demoted per cycle, and only "
        "if the backbone stays valid.",
        {"vsepr": "damped", "duration": 600.0},
    ),
    Scenario(
        "kill-half",
        "Kill half the cell",
        "Part IX's workload: {killed} of {n} nodes die at t = {kill_at:g} s. The death rule says "
        "MORE than half, so exactly half does not trigger mitosis.",
        {"kill_at": 120.0, "kill_fraction": 0.5, "duration": 300.0},
    ),
    Scenario(
        "kill-60",
        "Kill 60%: mitosis",
        "{killed} of {n} nodes die at t = {kill_at:g} s. Detection after {detect_delay:g} s raises "
        "CELL_DEATH_EVENT and mitosis refills the empty slots after {mitosis_time:g} s (both "
        "inputs taken from the journal).",
        {"kill_at": 120.0, "kill_fraction": 0.6, "duration": 300.0},
    ),
    Scenario(
        "kill-all",
        "Kill everything: meiosis",
        "All {killed} nodes die at t = {kill_at:g} s. The gateway respawns the cell from its last "
        "checkpoint (one every {checkpoint_period:g} s) after detection plus {meiosis_time:g} s "
        "(inputs taken from the journal).",
        {"kill_at": 120.0, "kill_fraction": 1.0, "duration": 300.0},
    ),
    Scenario(
        "hell-duplicate",
        "Hell mode, duplicate reading",
        "Every message is copied onto up to {k_paths} node-disjoint paths at {send_rate:g} msg/s "
        "with {loss_pct:g}% loss per hop (assumptions); the first copy to arrive counts, later "
        "copies are duplicates.",
        {"routing": "duplicate", "send_rate": 40.0, "link_loss": 0.05, "duration": 300.0},
    ),
    Scenario(
        "c20",
        "A C20 cell",
        "The dodecahedron cell from Figure 3 ({n} nodes, {links} links) under the same workload "
        "and the naive VSEPR rule.",
        {"cage": "C20", "vsepr": "naive", "duration": 300.0},
    ),
)


def blurb_for(sc: Scenario, cfg: Config) -> str:
    g = cage(cfg.cage)
    d = cfg.to_dict()
    d.update(
        n=g.n,
        links=g.links,
        killed=int(round(cfg.kill_fraction * g.n)),
        max_dem_pct=100 * cfg.vsepr_max_demotions_frac,
        loss_pct=100 * cfg.link_loss,
    )
    return sc.blurb.format(**d)


def _quick_overrides(o: dict) -> dict:
    o = dict(o)
    o["duration"] = 90.0 if "kill_at" not in o else 95.0
    if "kill_at" in o:
        o["kill_at"] = 65.0
    return o


def cages_block() -> dict:
    out = {}
    for name in CAGE_NAMES:
        g = cage(name)
        out[name] = {
            "n": g.n,
            "links": g.links,
            "diameter": diameter(g.adj),
            "edges": [list(e) for e in g.edges],
            "coords": [[round(x, 5) for x in c] for c in g.coords],
        }
    return out


def scenario_block(sc: Scenario, quick: bool = False, seed: int = 1) -> dict:
    o = _quick_overrides(sc.overrides) if quick else dict(sc.overrides)
    cfg = Config(**{"cage": "C60", "seed": seed, "record_frames": True, **o})
    res = Simulation(cfg).run()
    frames = res.frames or {}
    return {
        "id": sc.id,
        "title": sc.title,
        "blurb": blurb_for(sc, cfg),
        "cage": cfg.cage,
        "duration": cfg.duration,
        "seed": cfg.seed,
        "config": clean(cfg.to_dict()),
        "frames": {
            "dt": 1,
            "states": frames.get("states", []),
            "loads": frames.get("loads", []),
            "stems": frames.get("stems", []),
            "captains": frames.get("captains", []),
        },
        "series": clean(res.series),
        "events": clean(res.events[:MAX_EVENTS]),
        "events_total": len(res.events),
        "summary": clean(res.summary),
    }


def build_data(
    quick: bool = False, from_reports: Path | str | None = None, plan: Plan | None = None
) -> dict:
    if from_reports is not None:
        exp = load_reports(from_reports)
    else:
        exp = run_suite(None, plan or (QUICK if quick else FULL), plots=False)
    data = {
        "schema": 1,
        "generator": GENERATOR,
        "cages": cages_block(),
        "states": {"A": "ACTIVE", "S": "STANDBY", "G": "GHOST", "D": "DEAD"},
        "scenarios": [scenario_block(sc, quick=quick) for sc in SCENARIOS],
        "experiments": {
            "topology": exp["topology"],
            "vsepr": exp["vsepr"],
            "recovery": exp["recovery"],
            "hell": exp["hell"],
            "offline": exp["offline"],
            "churn": exp["churn"],
            "sensitivity": exp["sensitivity"],
        },
        "findings": exp["findings"],
    }
    if quick:
        data["quick"] = True
    return clean(data)


def render(data: dict) -> str:
    return PREFIX + json.dumps(data, separators=(",", ":"), ensure_ascii=True) + ";\n"


def write_web_data(
    out_dir: Path | str,
    quick: bool = False,
    from_reports: Path | str | None = None,
    plan: Plan | None = None,
) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "bmfp-data.js"
    path.write_text(render(build_data(quick=quick, from_reports=from_reports, plan=plan)))
    return path
