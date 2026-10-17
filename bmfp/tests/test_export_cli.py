import json
from dataclasses import replace

import pytest
import typer
from typer.testing import CliRunner

from bmfp.cli import _parse_set, app
from bmfp.experiments import QUICK
from bmfp.export import PREFIX, SCENARIOS, build_data, render, write_web_data

TINY = replace(
    QUICK,
    seeds=(1,),
    e4_rates=(10.0,),
    e4_losses=(0.0,),
    e5_active=(0.35,),
    e5_standby=(0.3,),
    e6_rates=(0.0,),
)
SERIES_KEYS = {
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
}


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    a = tmp_path_factory.mktemp("a")
    path = write_web_data(a, quick=True, plan=TINY)
    return path


def _load(path):
    txt = path.read_text()
    assert txt.startswith(PREFIX) and txt.endswith(";\n")
    return json.loads(txt[len(PREFIX) : -2])


def test_export_top_level_schema(exported):
    d = _load(exported)
    for k in ("schema", "generator", "cages", "states", "scenarios", "experiments", "findings"):
        assert k in d
    assert d["schema"] == 1 and d["generator"] == "bmfp export-web --out docs/data"
    assert d["states"] == {"A": "ACTIVE", "S": "STANDBY", "G": "GHOST", "D": "DEAD"}
    assert set(d["experiments"]) == {
        "topology",
        "vsepr",
        "recovery",
        "hell",
        "offline",
        "churn",
        "sensitivity",
    }


def test_export_cages(exported):
    cages = _load(exported)["cages"]
    assert set(cages) == {"C12", "C20", "C24", "C60"}
    c60 = cages["C60"]
    assert (c60["n"], c60["links"], c60["diameter"]) == (60, 90, 9)
    assert len(c60["edges"]) == 90 and len(c60["coords"]) == 60
    assert all(len(e) == 2 and e[0] < e[1] for e in c60["edges"])


def test_export_scenarios_shape(exported):
    d = _load(exported)
    ids = [s["id"] for s in d["scenarios"]]
    assert ids == [
        "baseline",
        "damped",
        "kill-half",
        "kill-60",
        "kill-all",
        "hell-duplicate",
        "c20",
    ]
    assert len(set(ids)) == len(ids) == len(SCENARIOS)
    for s in d["scenarios"]:
        n = d["cages"][s["cage"]]["n"]
        fr, se = s["frames"], s["series"]
        assert set(se) == SERIES_KEYS
        assert fr["dt"] == 1
        assert len(fr["states"]) == len(se["t"]) == len(fr["loads"]) == len(fr["stems"])
        assert len(fr["captains"]) == len(se["t"])
        assert all(len(x) == n and set(x) <= set("ASGD") for x in fr["states"])
        assert all(len(x) == n and x.isdigit() for x in fr["loads"])
        assert all(len(v) == len(se["t"]) for v in se.values())
        assert len(s["events"]) <= 400
        assert all(set(e) == {"t", "kind", "text"} for e in s["events"])
        assert isinstance(s["summary"], dict) and s["summary"]["cage"] == s["cage"]
        assert s["config"]["seed"] == s["seed"] == 1
        assert isinstance(s["title"], str) and isinstance(s["blurb"], str)
        assert "{" not in s["blurb"]


def test_export_unserved_shows_total_death(exported):
    """kill-all: sends offered while every node is dead are in ``unserved`` (not in ``sent``),
    so the live ratio dd / (ds + unserved) reads 0 during the outage instead of skipping it."""
    d = _load(exported)
    for s in d["scenarios"]:
        se, summ = s["series"], s["summary"]
        assert sum(se["unserved"]) == summ["skipped_sends"]
        if summ["skipped_sends"]:  # only between the total kill and the respawn
            k, rto = summ["kill_at"], summ["rto_journal_formula_s"]
            assert all(
                k <= t < k + rto + 1 for t, u in zip(se["t"], se["unserved"], strict=True) if u
            )
    ka = next(s for s in d["scenarios"] if s["id"] == "kill-all")
    se = ka["series"]
    out = [i for i, u in enumerate(se["unserved"]) if u]
    assert out, "the total-death outage must show up as unserved demand"
    live = [
        se["deliverable_delivered"][i] / (se["deliverable_sent"][i] + se["unserved"][i])
        for i in out
    ]
    assert all(r < 1 for r in live)
    # whole seconds of total death: nothing sent, so the old send-only ratio had nothing to show
    assert any(se["sent"][i] == 0 and r == 0 for i, r in zip(out, live, strict=True))


def test_export_experiment_blocks(exported):
    e = _load(exported)["experiments"]
    assert e["topology"][0]["partition_probability"]["1"] == 0.0
    for v in ("naive", "damped", "off"):
        m = e["vsepr"]["variants"][v]["state_changes_per_min"]
        assert {"mean", "min", "max"} <= set(m)
    assert set(e["recovery"]["cases"]) == {"kill50", "kill60", "kill100"}
    assert {"t", "ratio"} <= set(e["recovery"]["cases"]["kill50"]["series"])
    row = e["hell"]["rows"][0]
    for k in (
        "routing",
        "send_rate",
        "link_loss",
        "deliverable_ratio",
        "tx_per_delivered",
        "duplicates_per_delivered",
        "out_of_order_per_delivered",
        "congestion_drops",
    ):
        assert k in row
    assert {"active_fraction", "share_to_asleep"} <= set(e["offline"]["rows"][0])
    assert {"churn_rate", "deliverable_ratio", "stale_view_drops", "state_changes_per_min"} <= set(
        e["churn"]["rows"][0]
    )


def test_export_is_byte_identical(exported, tmp_path):
    again = write_web_data(tmp_path, quick=True, plan=TINY)
    assert again.read_bytes() == exported.read_bytes()


def test_export_from_reports_matches_recompute(tmp_path):
    from bmfp.experiments import run_suite

    run_suite(tmp_path / "rep", TINY, plots=False)
    a = build_data(quick=True, plan=TINY)
    b = build_data(quick=True, from_reports=tmp_path / "rep")
    assert a["experiments"] == b["experiments"] and a["findings"] == b["findings"]


def test_render_is_compact_ascii():
    txt = render({"a": [1, 2], "b": "\u00d7"})
    assert txt == 'window.BMFP_DATA = {"a":[1,2],"b":"\\u00d7"};\n'


# --------------------------------------------------------------------------- CLI
runner = CliRunner()


def test_cli_run_json():
    r = runner.invoke(app, ["run", "--duration", "20", "--seed", "2", "--json"])
    assert r.exit_code == 0, r.output
    s = json.loads(r.output)
    assert s["sent"] == s["delivered"] + s["drops_total"] and s["seed"] == 2


def test_cli_run_text_with_set_and_kill(tmp_path):
    out = tmp_path / "run.json"
    r = runner.invoke(
        app,
        [
            "run",
            "--duration",
            "40",
            "--kill-at",
            "20",
            "--kill-fraction",
            "1.0",
            "--set",
            "vsepr=damped",
            "--set",
            "detect_delay=2",
            "--out",
            str(out),
        ],
    )
    assert r.exit_code == 0, r.output
    assert "path meiosis" in r.output and "vsepr=damped" in r.output
    data = json.loads(out.read_text())
    assert data["config"]["detect_delay"] == 2.0 and "series" in data


def test_cli_rejects_bad_set():
    r = runner.invoke(app, ["run", "--duration", "5", "--set", "warp=9"])
    assert r.exit_code != 0
    with pytest.raises(typer.BadParameter):
        _parse_set(["no_equals"])
    assert _parse_set(["path_rotation=false", "kill_at=none", "k_paths=2"]) == {
        "path_rotation": False,
        "kill_at": None,
        "k_paths": 2,
    }


def test_cli_experiments_and_export_quick(tmp_path):
    r = runner.invoke(
        app, ["experiments", "--quick", "--no-plots", "--out", str(tmp_path / "r"), "--seeds", "1"]
    )
    assert r.exit_code == 0, r.output
    assert (tmp_path / "r" / "bmfp_results.md").exists()
    assert "[confirmed]" in r.output
    r = runner.invoke(
        app,
        [
            "export-web",
            "--out",
            str(tmp_path / "d"),
            "--from-reports",
            str(tmp_path / "r"),
            "--quick",
        ],
    )
    assert r.exit_code == 0, r.output
    assert (tmp_path / "d" / "bmfp-data.js").read_text().startswith(PREFIX)


# --------------------------------------------------------------------------- README
def test_readme_command_splices_generated_blocks(tmp_path):
    from bmfp.experiments import run_suite
    from bmfp.readme import BLOCKS

    rep = tmp_path / "rep"
    run_suite(rep, TINY, plots=False)
    readme = tmp_path / "README.md"
    readme.write_text(
        "# x\n\nhand-written\n\n"
        + "\n\n".join(
            f"<!-- generated:{b} -->\nOLD-BLOCK-TEXT\n<!-- /generated:{b} -->" for b in BLOCKS
        )
        + "\n\ntail\n"
    )
    args = ["readme", "--reports", str(rep), "--readme", str(readme)]
    assert runner.invoke(app, [*args, "--check"]).exit_code == 1
    r = runner.invoke(app, args)
    assert r.exit_code == 0, r.output
    txt = readme.read_text()
    assert "OLD-BLOCK-TEXT" not in txt and "hand-written" in txt and txt.endswith("tail\n")
    assert "| Parameter | Default | Source |" in txt and "### E1 · Topology" in txt
    findings = json.loads((rep / "findings.json").read_text())
    assert f"{len(findings)} findings:" in txt
    assert all(f["measured"] in txt for f in findings)
    assert runner.invoke(app, [*args, "--check"]).exit_code == 0


def test_published_readme_matches_published_reports():
    """README.md quotes reports/ verbatim: regenerate with `bmfp readme` after experiments."""
    from pathlib import Path

    from bmfp.readme import render_blocks, splice

    root = Path(__file__).resolve().parents[1]
    reports = root / "reports"
    if not (reports / "findings.json").exists():
        pytest.skip("no published reports/ (run `bmfp experiments --out reports/`)")
    text = (root / "README.md").read_text()
    assert splice(text, render_blocks(reports)) == text
