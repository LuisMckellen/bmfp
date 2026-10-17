import json

import numpy as np
import pytest
from typer.testing import CliRunner

from meshguard.cli import app
from meshguard.pipeline import dev_eval_masks, lf_true_accuracy, run_pipeline, stage_metrics


@pytest.fixture(scope="module")
def result():
    return run_pipeline(seed=42)


def test_split_is_a_partition():
    dev, evl = dev_eval_masks(500, 20, seed=1)
    assert (dev ^ evl).all()
    assert 0.2 < dev.mean() < 0.4


def test_split_keeps_blocks_together():
    dev, _ = dev_eval_masks(500, 20, seed=1)
    per_step = dev.reshape(500, 20)
    assert (per_step == per_step[:, :1]).all()


def test_split_deterministic_and_seed_dependent():
    a, _ = dev_eval_masks(500, 20, 1)
    b, _ = dev_eval_masks(500, 20, 1)
    c, _ = dev_eval_masks(500, 20, 2)
    np.testing.assert_array_equal(a, b)
    assert not np.array_equal(a, c)


def test_stage_metrics_perfect():
    y = np.array([0, 0, 1, 1], dtype=bool)
    m = stage_metrics(np.array([0.0, 0.0, 1.0, 1.0]), y)
    assert m["auprc"] == 1.0 and m["f1"] == 1.0 and m["brier"] == 0.0


def test_lf_true_accuracy_known():
    votes = np.array([[1], [1], [-1], [0]])
    y = np.array([True, False, False, True])
    assert lf_true_accuracy(votes, y)[0] == pytest.approx(2 / 3)


def test_pipeline_deterministic():
    a = run_pipeline(seed=3, with_rogue_scenario=False)
    b = run_pipeline(seed=3, with_rogue_scenario=False)
    np.testing.assert_array_equal(a.p_final, b.p_final)
    assert a.metrics["stages_eval"] == b.metrics["stages_eval"]


def test_pipeline_metrics_are_json_serialisable(result):
    json.dumps(result.metrics, default=str)


def test_label_model_beats_chance_by_a_wide_margin(result):
    st = result.metrics["stages_eval"]["dawid_skene"]
    assert st["auroc"] > 0.95 and st["f1"] > 0.7


def test_estimated_lf_accuracy_is_close_to_true_on_real_run(result):
    # only meaningful as a sanity bound; LFs are correlated so we allow a loose margin
    for name, d in result.metrics["lf"].items():
        assert abs(d["estimated_accuracy"] - d["true_accuracy_eval_only"]) < 0.15, name


def test_rogue_scenario_quarantines_injected_lf(result):
    assert result.metrics["rogue_scenario"]["injected_rogue_quarantined"]


def test_flags_are_reported_not_hidden(result):
    flags = result.metrics["flags"]
    bad = [c for c in result.metrics["checks"] if not c["improved"]]
    assert sum(f.startswith("NEGATIVE RESULT") for f in flags) == len(bad)


def test_calibrated_probabilities_valid(result):
    assert ((result.p_calibrated >= 0) & (result.p_calibrated <= 1)).all()


def test_selective_threshold_from_dev_only(result):
    s = result.metrics["selective"]
    assert 0.5 <= s["threshold_from_dev"] <= 1.0 and 0 < s["eval_coverage"] <= 1.0


def test_cli_run_writes_all_reports(tmp_path):
    out = tmp_path / "rep"
    r = CliRunner().invoke(
        app, ["run", "--seed", "42", "--sensors", "20", "--steps", "500", "--out", str(out)]
    )
    assert r.exit_code == 0, r.output
    for f in (
        "metrics.json",
        "reliability_before.png",
        "reliability_after.png",
        "coverage_risk.png",
        "votes_sample.csv",
    ):
        assert (out / f).exists() and (out / f).stat().st_size > 100, f
    m = json.loads((out / "metrics.json").read_text())
    assert m["config"] == {"seed": 42, "n_sensors": 20, "steps": 500}
    assert "dawid_skene" in r.output and "ECE" in r.output


def test_cli_metrics_reproducible(tmp_path):
    runner = CliRunner()
    for name in ("a", "b"):
        runner.invoke(app, ["run", "--seed", "5", "--out", str(tmp_path / name)])
    assert (tmp_path / "a" / "metrics.json").read_text() == (
        tmp_path / "b" / "metrics.json"
    ).read_text()


def test_cli_sweep_table(tmp_path):
    out = tmp_path / "t.md"
    r = CliRunner().invoke(app, ["sweep", "--seed", "1", "--seed", "2", "--out", str(out)])
    assert r.exit_code == 0, r.output
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 4 and lines[2].startswith("| 1 |")
