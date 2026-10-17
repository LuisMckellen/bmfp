"""End-to-end MeshGuard pipeline.

simulate -> vote -> label model -> isolate -> calibrate -> abstain.

Ground truth is used in exactly two places: (1) a small labelled dev split (time blocks) for
calibration and the selective threshold, and (2) evaluation metrics on the held-out blocks.
Labeling, the label model and isolation never see it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, f1_score, roc_auc_score

from . import dawid_skene as ds
from .calibration import IsotonicCalibrator, TemperatureScaler, ece
from .isolation import IsolationResult, inject_rogue, isolate
from .labeling import VoteMatrix, build_vote_matrix
from .selective import (
    CoverageRisk,
    Selection,
    apply_threshold,
    aurc,
    coverage_risk_curve,
    select_threshold,
)
from .simulator import Simulation, simulate

MAX_RISK = 0.05
STRICT_RISK = 0.01
DEV_FRACTION = 0.3
SPLIT_BLOCK = 25
MIN_IMPROVEMENT = 1e-3

ROGUE = {"lf_name": "range_check", "zone": 0, "from_step": 100}


def dev_eval_masks(
    steps: int,
    n_nodes: int,
    seed: int,
    block: int = SPLIT_BLOCK,
    dev_fraction: float = DEV_FRACTION,
) -> tuple[np.ndarray, np.ndarray]:
    """Split examples into dev / eval by random time blocks (all nodes of a block go together)."""
    n_blocks = -(-steps // block)
    rng = np.random.default_rng(seed + 10_000)
    n_dev = max(1, round(dev_fraction * n_blocks))
    dev_blocks = np.zeros(n_blocks, dtype=bool)
    dev_blocks[rng.choice(n_blocks, size=n_dev, replace=False)] = True
    dev_t = np.repeat(dev_blocks, block)[:steps]
    dev = np.repeat(dev_t, n_nodes)
    return dev, ~dev


def stage_metrics(p: np.ndarray, y: np.ndarray) -> dict[str, float]:
    hard = p > 0.5
    return {
        "auroc": float(roc_auc_score(y, p)),
        "auprc": float(average_precision_score(y, p)),
        "f1": float(f1_score(y, hard, zero_division=0)),
        "brier": float(brier_score_loss(y, p)),
        "ece": float(ece(p, y)),
        "false_positive_rate": float(hard[~y].mean()) if (~y).any() else 0.0,
        "recall": float(hard[y].mean()) if y.any() else 0.0,
    }


def lf_true_accuracy(votes: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Evaluation-only: accuracy of each LF among its non-abstaining votes."""
    out = np.full(votes.shape[1], np.nan)
    for j in range(votes.shape[1]):
        nz = votes[:, j] != 0
        if nz.any():
            out[j] = float(((votes[nz, j] == 1) == y[nz]).mean())
    return out


@dataclass
class LabelScores:
    """Posteriors from the label model with and without isolation."""

    ds_plain: ds.DSResult
    ds_quarantine_only: ds.DSResult
    ds_isolated: ds.DSResult
    isolation: IsolationResult
    isolation_quarantine_only: IsolationResult
    majority: np.ndarray


def score_votes(vm: VoteMatrix) -> LabelScores:
    plain = ds.fit(vm.votes)
    pseudo = plain.p_anomaly > 0.5
    full = isolate(vm, pseudo)
    quarantine_only = isolate(vm, pseudo, rogue_weight=1.0)
    return LabelScores(
        ds_plain=plain,
        ds_quarantine_only=ds.fit(vm.votes, quarantine_only.weights),
        ds_isolated=ds.fit(vm.votes, full.weights),
        isolation=full,
        isolation_quarantine_only=quarantine_only,
        majority=ds.majority_vote_probability(vm.votes),
    )


def _check(name: str, before: float, after: float, higher_is_better: bool) -> dict:
    delta = (after - before) * (1 if higher_is_better else -1)
    return {
        "check": name,
        "before": before,
        "after": after,
        "improvement": delta,
        "improved": bool(delta > MIN_IMPROVEMENT),
    }


@dataclass
class PipelineResult:
    metrics: dict
    sim: Simulation
    vote_matrix: VoteMatrix
    p_final: np.ndarray
    p_calibrated: np.ndarray
    labels: np.ndarray
    dev: np.ndarray
    eval: np.ndarray
    curves: dict[str, CoverageRisk] = field(default_factory=dict)
    selection: Selection | None = None


def run_pipeline(
    seed: int = 42, n_sensors: int = 20, steps: int = 500, with_rogue_scenario: bool = True
) -> PipelineResult:
    sim = simulate(seed=seed, n_sensors=n_sensors, steps=steps)
    vm = build_vote_matrix(sim.readings)
    y = sim.truth.labels.reshape(-1)  # evaluation / dev-set only
    dev, evl = dev_eval_masks(steps, n_sensors, seed)

    scores = score_votes(vm)
    p_iso = scores.ds_isolated.p_anomaly

    stages = {
        "majority_vote": scores.majority,
        "dawid_skene": scores.ds_plain.p_anomaly,
        "dawid_skene_quarantine_only": scores.ds_quarantine_only.p_anomaly,
        "dawid_skene_isolation": p_iso,
    }
    stage_results = {k: stage_metrics(v[evl], y[evl]) for k, v in stages.items()}

    # Calibration (fit on dev blocks, scored on eval blocks).
    temp = TemperatureScaler().fit(p_iso[dev], y[dev])
    iso_cal = IsotonicCalibrator().fit(p_iso[dev], y[dev])
    p_temp = temp.transform(p_iso)
    p_isocal = iso_cal.transform(p_iso)
    calibration = {
        "temperature": temp.temperature,
        "ece_before": ece(p_iso[evl], y[evl]),
        "ece_temperature": ece(p_temp[evl], y[evl]),
        "ece_isotonic": ece(p_isocal[evl], y[evl]),
        "brier_before": stage_results["dawid_skene_isolation"]["brier"],
        "brier_temperature": stage_metrics(p_temp[evl], y[evl])["brier"],
        "brier_isotonic": stage_metrics(p_isocal[evl], y[evl])["brier"],
    }

    # Selective prediction: threshold picked on dev, reported on eval.
    sel_dev = select_threshold(p_temp[dev], y[dev], MAX_RISK)
    sel_eval = apply_threshold(p_temp[evl], y[evl], sel_dev.threshold)
    curve_raw = coverage_risk_curve(p_iso[evl], y[evl])
    curve_cal = coverage_risk_curve(p_temp[evl], y[evl])
    accepted = np.abs(p_temp[evl] - 0.5) + 0.5 >= sel_dev.threshold
    anomalies_eval = y[evl]
    caught = (p_temp[evl] > 0.5) & accepted & anomalies_eval
    selective = {
        "max_risk": MAX_RISK,
        "threshold_from_dev": sel_dev.threshold,
        "dev_coverage": sel_dev.coverage,
        "dev_risk": sel_dev.risk,
        "eval_coverage": sel_eval.coverage,
        "eval_risk": sel_eval.risk,
        "eval_anomaly_recall_among_all": (
            float(caught.sum() / anomalies_eval.sum()) if anomalies_eval.any() else 0.0
        ),
        "aurc_raw": aurc(curve_raw),
        "aurc_calibrated": aurc(curve_cal),
        "full_coverage_risk": float(curve_cal.risk[-1]),
    }

    strict_dev = select_threshold(p_temp[dev], y[dev], STRICT_RISK)
    strict_eval = apply_threshold(p_temp[evl], y[evl], strict_dev.threshold)
    selective["strict"] = {
        "max_risk": STRICT_RISK,
        "threshold_from_dev": strict_dev.threshold,
        "eval_coverage": strict_eval.coverage,
        "eval_risk": strict_eval.risk,
    }

    lf = {}
    true_acc = lf_true_accuracy(vm.votes, y)
    for j, name in enumerate(vm.lf_names):
        lf[name] = {
            "estimated_accuracy": float(scores.ds_plain.accuracy[j]),
            "true_accuracy_eval_only": float(true_acc[j]),
            "abstain_rate": float((vm.votes[:, j] == 0).mean()),
        }

    metrics: dict = {
        "config": {"seed": seed, "n_sensors": n_sensors, "steps": steps},
        "n_examples": int(y.size),
        "n_dev": int(dev.sum()),
        "n_eval": int(evl.sum()),
        "anomaly_rate": float(y.mean()),
        "faulty_nodes": {
            str(n): {"regime": int(sim.truth.regimes[-1, n]), "onset": sim.truth.onsets[int(n)]}
            for n in sim.truth.faulty_nodes
        },
        "stages_eval": stage_results,
        "lf": lf,
        "ds_converged": scores.ds_plain.converged,
        "isolation_clean": {
            "quarantined": scores.isolation.quarantined(),
            "sensor_windows_down_weighted": int(scores.isolation.rogue_sensor.sum()),
        },
        "calibration": calibration,
        "selective": selective,
    }

    checks = [
        _check(
            "DS vs majority vote: AUPRC",
            *_pair(stage_results, "majority_vote", "dawid_skene", "auprc"),
            True,
        ),
        _check(
            "DS vs majority vote: F1",
            *_pair(stage_results, "majority_vote", "dawid_skene", "f1"),
            True,
        ),
        _check(
            "DS vs majority vote: Brier",
            *_pair(stage_results, "majority_vote", "dawid_skene", "brier"),
            False,
        ),
        _check(
            "Isolation (clean run) vs DS: AUPRC",
            *_pair(stage_results, "dawid_skene", "dawid_skene_isolation", "auprc"),
            True,
        ),
        _check(
            "Isolation (clean run) vs DS: F1",
            *_pair(stage_results, "dawid_skene", "dawid_skene_isolation", "f1"),
            True,
        ),
        _check(
            "Quarantine only (clean run) vs DS: F1",
            *_pair(stage_results, "dawid_skene", "dawid_skene_quarantine_only", "f1"),
            True,
        ),
        _check(
            "Temperature scaling: ECE",
            calibration["ece_before"],
            calibration["ece_temperature"],
            False,
        ),
        _check("Isotonic: ECE", calibration["ece_before"], calibration["ece_isotonic"], False),
        _check(
            "Temperature scaling: AURC", selective["aurc_raw"], selective["aurc_calibrated"], False
        ),
    ]

    if with_rogue_scenario:
        rogue_vm = inject_rogue(vm, **ROGUE)
        rs = score_votes(rogue_vm)
        zone_rows = np.zeros((sim.readings.values.shape[0], n_sensors), dtype=bool)
        zone_rows[ROGUE["from_step"] :, ROGUE["zone"] * 5 : (ROGUE["zone"] + 1) * 5] = True
        in_zone = zone_rows.reshape(-1) & evl
        variants = {
            "no_isolation": rs.ds_plain.p_anomaly,
            "quarantine_only": rs.ds_quarantine_only.p_anomaly,
            "isolation": rs.ds_isolated.p_anomaly,
        }
        scenario = {"injected": dict(ROGUE), "variants_eval": {}, "variants_rogue_zone": {}}
        for name, p in variants.items():
            scenario["variants_eval"][name] = stage_metrics(p[evl], y[evl])
            zone_y = y[in_zone]
            hard = p[in_zone] > 0.5
            scenario["variants_rogue_zone"][name] = {
                "n": int(in_zone.sum()),
                "false_positive_rate": float(hard[~zone_y].mean()) if (~zone_y).any() else 0.0,
                "accuracy": float((hard == zone_y).mean()),
            }
        scenario["quarantined"] = rs.isolation.quarantined()
        scenario["injected_rogue_quarantined"] = any(
            n == ROGUE["lf_name"] and z == ROGUE["zone"] for n, z, _ in rs.isolation.quarantined()
        )
        metrics["rogue_scenario"] = scenario
        v = scenario["variants_eval"]
        checks += [
            _check(
                "Isolation (rogue LF injected) vs DS: AUPRC",
                v["no_isolation"]["auprc"],
                v["isolation"]["auprc"],
                True,
            ),
            _check(
                "Isolation (rogue LF injected) vs DS: F1",
                v["no_isolation"]["f1"],
                v["isolation"]["f1"],
                True,
            ),
            _check(
                "Isolation (rogue LF injected) vs DS: false-positive rate in rogue zone",
                scenario["variants_rogue_zone"]["no_isolation"]["false_positive_rate"],
                scenario["variants_rogue_zone"]["isolation"]["false_positive_rate"],
                False,
            ),
        ]

    metrics["checks"] = checks
    flags = [
        f"NEGATIVE RESULT: {c['check']} did not improve ({c['before']:.4f} -> {c['after']:.4f})"
        for c in checks
        if not c["improved"]
    ]
    if selective["eval_risk"] > MAX_RISK:
        flags.append(
            f"NEGATIVE RESULT: selective threshold from dev gives eval risk "
            f"{selective['eval_risk']:.4f} > max_risk {MAX_RISK}"
        )
    if selective["full_coverage_risk"] <= MAX_RISK:
        flags.append(
            f"NOTE: full-coverage risk {selective['full_coverage_risk']:.4f} is already "
            f"<= max_risk {MAX_RISK}, so the {MAX_RISK} threshold abstains on almost nothing"
        )
    if not metrics["ds_converged"]:
        flags.append("WARNING: Dawid-Skene EM did not converge within max_iter")
    metrics["flags"] = flags

    return PipelineResult(
        metrics=metrics,
        sim=sim,
        vote_matrix=vm,
        p_final=p_iso,
        p_calibrated=p_temp,
        labels=y,
        dev=dev,
        eval=evl,
        curves={"uncalibrated": curve_raw, "temperature-scaled": curve_cal},
        selection=sel_eval,
    )


def _pair(stage_results: dict, a: str, b: str, key: str) -> tuple[float, float]:
    return stage_results[a][key], stage_results[b][key]
