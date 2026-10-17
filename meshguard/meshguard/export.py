"""Export MeshGuard results for the portfolio website (``docs/data/meshguard-data.js``).

Every number the site shows about MeshGuard comes from this file, and this file comes from
``meshguard export-web``. Output is byte-identical across runs.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from .calibration import ece, reliability_curve
from .pipeline import run_pipeline
from .selective import CoverageRisk
from .simulator import NORMAL, REGIME_NAMES

GENERATOR = "meshguard export-web --out docs/data"
DEFAULT_SEEDS = (42, 43, 44, 45, 46)
DETAIL_SEED = 42
PIPELINE = [
    {"id": "simulate", "label": "Simulate ring"},
    {"id": "label", "label": "6 labeling functions"},
    {"id": "ds", "label": "Dawid–Skene"},
    {"id": "isolation", "label": "Failure-domain isolation"},
    {"id": "calibration", "label": "Calibration"},
    {"id": "selective", "label": "Selective prediction"},
]
STAGE_KEYS = ("auroc", "auprc", "f1", "brier", "ece", "false_positive_rate", "recall")


def _r(x: float | None, nd: int = 6) -> float | None:
    if x is None:
        return None
    x = float(x)
    if math.isnan(x) or math.isinf(x):
        return None
    return round(x, nd)


def _downsample(curve: CoverageRisk, max_points: int = 200) -> dict:
    n = len(curve.coverage)
    idx = np.unique(np.linspace(0, n - 1, min(n, max_points)).round().astype(int))
    return {
        "coverage": [_r(curve.coverage[i]) for i in idx],
        "risk": [_r(curve.risk[i]) for i in idx],
    }


def _reliability(probs: np.ndarray, labels: np.ndarray) -> dict:
    c = reliability_curve(probs, labels)
    return {
        "conf": [_r(v) for v in c.confidence],
        "acc": [_r(v) for v in c.accuracy],
        "count": [int(v) for v in c.counts],
        "ece": _r(ece(probs, labels)),
    }


def _sweep_row(m: dict) -> dict:
    rs = m.get("rogue_scenario", {})
    variants = rs.get("variants_eval", {})
    sel = m["selective"]
    return {
        "seed": m["config"]["seed"],
        "anomaly_rate": _r(m["anomaly_rate"]),
        "n_eval": m["n_eval"],
        "stages": {name: {k: _r(v[k]) for k in STAGE_KEYS} for name, v in m["stages_eval"].items()},
        "calibration": {
            k: _r(m["calibration"][k])
            for k in ("temperature", "ece_before", "ece_temperature", "ece_isotonic")
        },
        "selective": {
            "max_risk": sel["max_risk"],
            "eval_coverage": _r(sel["eval_coverage"]),
            "eval_risk": _r(sel["eval_risk"]),
            "full_coverage_risk": _r(sel["full_coverage_risk"]),
            "strict": {k: _r(sel["strict"][k]) for k in ("max_risk", "eval_coverage", "eval_risk")},
        },
        "rogue": {
            **rs.get("injected", {}),
            "quarantined": bool(rs.get("injected_rogue_quarantined", False)),
            "f1_no_isolation": _r(variants.get("no_isolation", {}).get("f1")),
            "f1_isolation": _r(variants.get("isolation", {}).get("f1")),
            "auprc_no_isolation": _r(variants.get("no_isolation", {}).get("auprc")),
            "auprc_isolation": _r(variants.get("isolation", {}).get("auprc")),
        },
        "flags": list(m["flags"]),
    }


def _detail(res) -> dict:
    m = res.metrics
    ev, y = res.eval, res.labels
    sim = res.sim
    values = sim.readings.values
    faulty = [int(n) for n in sim.truth.faulty_nodes]
    healthy = [n for n in range(values.shape[1]) if n not in faulty][:2]
    steps = list(range(0, values.shape[0], 2))

    def regime(n: int) -> str:
        return REGIME_NAMES[int(sim.truth.regimes[-1, n])] if n in faulty else REGIME_NAMES[NORMAL]

    series = [
        {
            "node": n,
            "regime": regime(n),
            "onset": sim.truth.onsets.get(n),
            "values": [_r(values[t, n], 3) for t in steps],
        }
        for n in faulty + healthy
    ]
    curves = res.curves
    return {
        "seed": m["config"]["seed"],
        "lf": [
            {
                "name": name,
                "estimated_accuracy": _r(d["estimated_accuracy"]),
                "true_accuracy_eval_only": _r(d["true_accuracy_eval_only"]),
                "abstain_rate": _r(d["abstain_rate"]),
            }
            for name, d in m["lf"].items()
        ],
        "reliability": {
            "before": _reliability(res.p_final[ev], y[ev]),
            "after": _reliability(res.p_calibrated[ev], y[ev]),
        },
        "coverage_risk": {
            "uncalibrated": _downsample(curves["uncalibrated"]),
            "calibrated": _downsample(curves["temperature-scaled"]),
            "selection": {
                "coverage": _r(res.selection.coverage),
                "risk": _r(res.selection.risk),
                "max_risk": m["selective"]["max_risk"],
            },
        },
        "faulty_nodes": [
            {"node": n, "regime": regime(n), "onset": sim.truth.onsets[n]} for n in faulty
        ],
        "stream_sample": {"steps": steps, "series": series},
    }


def build_site_data(seeds: tuple[int, ...] = DEFAULT_SEEDS, detail_seed: int = DETAIL_SEED) -> dict:
    sweep, detail = [], None
    for s in seeds:
        res = run_pipeline(seed=s)
        sweep.append(_sweep_row(res.metrics))
        if s == detail_seed:
            detail = _detail(res)
    if detail is None:
        detail = _detail(run_pipeline(seed=detail_seed))
    return {
        "schema": 1,
        "generator": GENERATOR,
        "pipeline": PIPELINE,
        "seeds": list(seeds),
        "sweep": sweep,
        "detail": detail,
    }


def to_js(data: dict) -> str:
    return (
        "window.MESHGUARD_DATA = "
        + json.dumps(data, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        + ";\n"
    )


def write_site_data(out_dir: str | Path, seeds: tuple[int, ...] = DEFAULT_SEEDS) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "meshguard-data.js"
    path.write_text(to_js(build_site_data(seeds)), encoding="utf-8")
    return path
