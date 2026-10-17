import json

import pytest

from meshguard.export import build_site_data, to_js


@pytest.fixture(scope="module")
def data():
    return build_site_data(seeds=(42,), detail_seed=42)


def test_top_level_schema(data):
    assert data["schema"] == 1
    assert data["generator"].startswith("meshguard export-web")
    assert [p["id"] for p in data["pipeline"]][0] == "simulate"
    assert data["seeds"] == [42] and len(data["sweep"]) == 1


def test_sweep_row_keys(data):
    row = data["sweep"][0]
    assert set(row["stages"]) == {
        "majority_vote",
        "dawid_skene",
        "dawid_skene_quarantine_only",
        "dawid_skene_isolation",
    }
    assert set(row["stages"]["dawid_skene"]) >= {"auprc", "f1", "ece", "brier"}
    assert set(row["calibration"]) == {
        "temperature",
        "ece_before",
        "ece_temperature",
        "ece_isotonic",
    }
    assert row["rogue"]["lf_name"] == "range_check" and isinstance(
        row["rogue"]["quarantined"], bool
    )
    assert row["selective"]["strict"]["max_risk"] == 0.01


def test_detail_shapes(data):
    d = data["detail"]
    assert len(d["reliability"]["before"]["conf"]) == 15
    assert len(d["coverage_risk"]["calibrated"]["coverage"]) <= 200
    assert len(d["lf"]) == 6
    steps = d["stream_sample"]["steps"]
    assert all(len(s["values"]) == len(steps) for s in d["stream_sample"]["series"])
    regimes = {s["regime"] for s in d["stream_sample"]["series"]}
    assert "normal" in regimes and len(regimes) >= 3


def test_js_wrapper_is_valid_json_and_deterministic(data):
    js = to_js(data)
    assert js.startswith("window.MESHGUARD_DATA = ") and js.endswith(";\n")
    json.loads(js[len("window.MESHGUARD_DATA = ") : -2])
    assert to_js(build_site_data(seeds=(42,), detail_seed=42)) == js
