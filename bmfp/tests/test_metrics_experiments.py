import json

import pytest

from bmfp.experiments import (
    QUICK,
    Plan,
    agg,
    e1_topology,
    make_findings,
    min_cds_exact,
    results_markdown,
    run_suite,
    value_or_list,
)
from bmfp.metrics import FINE_PER_S, bin_ratios, clean, percentile, ratio, recovery_metrics
from bmfp.topology import cage

REQUIRED_PROBLEMS = {
    "Offline delivery",
    "The gateway is a server",
    "Waking a phone needs push",
    "Hell mode is ambiguous",
    "VSEPR will oscillate",
    "Captains are not elected yet",
    "RTO arithmetic",
    "Group token rekeying",
    "What the number in C20 counts",
    "No single failed checkpoint can cut the ball in half",
}
VERDICTS = {"confirmed", "refuted", "partly", "not simulated"}
CLAIMS = {"topology-cut", "valid-active-sets", "vsepr-flattening"}


# --------------------------------------------------------------------------- metrics
def _fine(seconds, per_s_ds, per_s_dd):
    ds, dd = [], []
    for s in range(seconds):
        for _ in range(FINE_PER_S):
            ds.append(per_s_ds(s))
            dd.append(per_s_dd(s))
    return ds, dd


def test_recovery_perfect_service_recovers_immediately():
    ds, dd = _fine(200, lambda s: 2, lambda s: 2)
    r = recovery_metrics(ds, dd, kill_at=100.0, duration=200.0)
    assert r["baseline_ratio"] == 1.0 and r["rto_service_s"] == 0.0
    assert r["min_ratio_after_kill"] == 1.0 and r["ratio_dip"] == 0.0


def test_recovery_outage_measured_from_failure_instant():
    ds, dd = _fine(200, lambda s: 2, lambda s: 0 if 100 <= s < 104 else 2)
    r = recovery_metrics(ds, dd, kill_at=100.0, duration=200.0)
    # a 4 s outage reads exactly 4 s: no window that starts inside it can qualify
    assert r["rto_service_s"] == pytest.approx(4.0)
    # the worst 5 s window holds the 4 s outage plus 1 s of service
    assert r["min_ratio_after_kill"] == pytest.approx(0.2)
    assert r["ratio_dip"] == pytest.approx(0.8)


def _steps(n_steps, fn):
    """0.1 s bins: fn(i) -> (offered, served) for step i."""
    off, srv = [], []
    for i in range(n_steps):
        o, v = fn(i)
        off.append(o)
        srv.append(v)
    return off, srv


def test_recovery_not_before_service_exists_after_a_quiet_gap():
    # outage 100.0-103.5, then no traffic at all until 104.0 (the old forward window starting
    # at 103.5 saw no failures and reported 3.5 s), service from 104.0
    def fn(i):
        t = i / FINE_PER_S
        if 100 <= t < 103.5 - 1e-9:
            return 2, 0
        if 103.5 - 1e-9 <= t < 104 - 1e-9:
            return 0, 0
        return 2, 2

    off, srv = _steps(2000, fn)
    r = recovery_metrics(off, srv, kill_at=100.0, duration=200.0)
    assert r["rto_service_s"] == pytest.approx(4.0)


def test_recovery_first_second_must_meet_threshold():
    # one lucky delivery at 104.0, then 0.4 s of failures, then full service from 104.5:
    # the 5 s windows from 104.0 pass at 95%, but the first second does not
    def fn(i):
        t = round(i / FINE_PER_S, 1)
        if 100 <= t < 104:
            return 10, 0
        if t == 104.0:
            return 1, 1
        if 104.0 < t < 104.5:
            return 3, 0
        return 10, 10

    off, srv = _steps(2000, fn)
    r = recovery_metrics(off, srv, kill_at=100.0, duration=200.0)
    assert r["rto_service_s"] == pytest.approx(4.5)


def test_recovery_snaps_to_first_arrival_inside_the_step():
    ds, dd = _fine(200, lambda s: 2, lambda s: 0 if 100 <= s < 104 else 2)
    first = [None] * len(ds)
    first[1040] = 104.07
    r = recovery_metrics(ds, dd, kill_at=100.0, duration=200.0, first_served=first)
    assert r["rto_service_s"] == pytest.approx(4.07)


def test_recovery_never_returns_none():
    ds, dd = _fine(150, lambda s: 2, lambda s: 2 if s < 100 else 1)
    r = recovery_metrics(ds, dd, kill_at=100.0, duration=150.0)
    assert r["rto_service_s"] is None
    assert r["min_ratio_after_kill"] == pytest.approx(0.5)


def test_recovery_requires_hold_of_ten_bins():
    # good for 5 s, bad again for 3 s, then good: recovery is the second return
    def dd(s):
        if 100 <= s < 102 or 107 <= s < 110:
            return 0
        return 2

    ds, d = _fine(200, lambda s: 2, dd)
    r = recovery_metrics(ds, d, kill_at=100.0, duration=200.0)
    assert r["rto_service_s"] > 9.0


def test_recovery_without_baseline_traffic():
    ds, dd = _fine(150, lambda s: 0, lambda s: 0)
    r = recovery_metrics(ds, dd, kill_at=100.0, duration=150.0)
    assert r["baseline_ratio"] is None and r["rto_service_s"] is None


def test_bin_ratios_ratio_percentile():
    assert bin_ratios([0, 2, 4], [0, 1, 4]) == [None, 0.5, 1.0]
    assert ratio(1, 0) is None and ratio(1, 4) == 0.25
    assert percentile([], 0.9) is None
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.95) == 10


def test_clean_rounds_and_sanitises():
    out = clean({"a": 1 / 3, "b": float("nan"), "c": (1.0, float("inf")), 4: [True, None]})
    assert out == {"a": 0.333333, "b": None, "c": [1.0, None], "4": [True, None]}
    json.dumps(out, allow_nan=False)


# --------------------------------------------------------------------------- experiments
def test_agg_and_value_or_list():
    assert agg([1, 2, 3]) == {"mean": 2.0, "min": 1.0, "max": 3.0, "n": 3}
    assert agg([None, 4]) == {"mean": 4.0, "min": 4.0, "max": 4.0, "n": 1}
    assert agg([None]) == {"mean": None, "min": None, "max": None, "n": 0}
    assert value_or_list([True, True]) is True
    assert value_or_list(["a", "b"]) == ["a", "b"]


def test_min_cds_exact_c12():
    g = cage("C12")
    assert min_cds_exact(g.adj, 5, 8) == 6


def test_e1_rows_have_spec_fields():
    rows = e1_topology(Plan(e1_trials=200, e1_exact_cds_max_n=12))
    assert [r["cage"] for r in rows] == ["C12", "C20", "C24", "C60"]
    for r in rows:
        for k in ("n", "links", "degree", "diameter", "min_vertex_cut", "faces"):
            assert k in r
        assert set(r["partition_probability"]) == {"1", "2", "3", "4", "5", "6"}
        assert r["partition_probability"]["1"] == r["partition_probability"]["2"] == 0.0
        assert r["cds_greedy"] >= r["cds_lower_bound"]


def test_findings_with_no_data_still_honest_about_scope():
    fs = make_findings({})
    ids = {f["id"] for f in fs}
    assert {"gateway-server", "push-wake", "group-rekeying"} <= ids
    assert all(f["verdict"] == "not simulated" for f in fs)


def test_vsepr_finding_partly_when_vsepr_never_fires():
    zero = {"mean": 0.0, "min": 0.0, "max": 0.0, "n": 5}
    variants = {
        v: {
            k: zero
            for k in ("demotions", "vsepr_flaps", "active_fraction_start", "active_fraction_end")
        }
        for v in ("naive", "damped", "off")
    }
    fs = make_findings({"vsepr": {"variants": variants}})
    f = next(f for f in fs if f["id"] == "vsepr-oscillation")
    assert f["verdict"] == "partly"


@pytest.fixture(scope="module")
def quick_suite(tmp_path_factory):
    out = tmp_path_factory.mktemp("reports")
    return out, run_suite(out, QUICK, plots=True)


def test_quick_suite_writes_every_report(quick_suite):
    out, _ = quick_suite
    for name in (
        "e1_topology",
        "e2_vsepr",
        "e3_recovery",
        "e4_hell",
        "e5_offline",
        "e6_churn",
        "e7_sensitivity",
    ):
        assert (out / f"{name}.json").exists()
        assert (out / f"{name}.png").stat().st_size > 1000
    md = (out / "bmfp_results.md").read_text()
    assert "## Findings" in md and "## E3" in md and "| `detect_delay` | 3.0 | JOURNAL" in md


def test_quick_suite_findings_cover_every_open_problem(quick_suite):
    _, res = quick_suite
    fs = res["findings"]
    # a problem stated as its outcome keeps the journal's own name in journal_ref
    named = " | ".join(f"{f['problem']} | {f['journal_ref']}" for f in fs)
    assert all(p in named for p in REQUIRED_PROBLEMS), [
        p for p in REQUIRED_PROBLEMS if p not in named
    ]
    assert len({f["id"] for f in fs}) == len(fs)
    for f in fs:
        assert list(f) == [
            "id",
            "problem",
            "kind",
            "journal_ref",
            "verdict",
            "measured",
            "next_step",
        ]
        assert f["verdict"] in VERDICTS
        assert f["kind"] == ("claim" if f["id"] in CLAIMS else "problem")
        assert f["measured"] and f["next_step"]


def test_findings_numbers_come_from_data(quick_suite):
    _, res = quick_suite
    f = next(f for f in res["findings"] if f["id"] == "c20-count")
    c20 = next(r for r in res["topology"] if r["cage"] == "C20")
    assert f"{c20['n']} nodes, {c20['links']} links" in f["measured"]
    d = next(f for f in res["findings"] if f["id"] == "death-threshold")
    assert d["verdict"] == "confirmed"  # killing exactly half never fires the rule


def test_recovery_cases_and_series(quick_suite):
    _, res = quick_suite
    rec = res["recovery"]
    cases = rec["cases"]
    assert set(cases) == {"kill50", "kill60", "kill100"}
    assert cases["kill50"]["path"] == "none" and cases["kill100"]["path"] == "meiosis"
    s = cases["kill60"]["series"]
    assert len(s["t"]) == len(s["ratio"]) == len(s["offered"]) == len(s["served"])
    # total death plots as 0 (unserved demand), not as a gap
    k = int(rec["kill_at"])
    s100 = cases["kill100"]["series"]
    assert [s100["ratio"][b] for b in (k + 1, k + 2, k + 3)] == [0.0, 0.0, 0.0]
    for c in cases.values():  # quick runs can end before kill50 recovers (None)
        if c["rto_service_s"]["min"] is not None:
            assert c["rto_service_s"]["min"] >= c["detect_time_s"]["min"]
    assert (
        cases["kill100"]["rto_service_s"]["min"] >= cases["kill100"]["refill_after_kill_s"]["min"]
    )


def test_e3_marks_input_rows(quick_suite):
    out, _ = quick_suite
    md = (out / "bmfp_results.md").read_text()
    assert "| detect_time_s *(input" in md
    assert "| rto_journal_formula_s *(inputs" in md
    assert "| refill_after_kill_s *(inputs" in md
    assert "| rto_service_s |" in md  # a measurement: no label


def test_e2_reports_absolute_loads(quick_suite):
    _, res = quick_suite
    for v in ("naive", "damped", "off"):
        m = res["vsepr"]["variants"][v]
        assert m["mean_peak_relay_load"]["mean"] >= m["mean_avg_relay_load"]["mean"] > 0


def _variants(**vals):
    """Synthetic E2 variants: vals[name] = (ratio, peak, avg, active_mean)."""
    one = lambda x: {"mean": x, "min": x, "max": x, "n": 1}  # noqa: E731
    out = {}
    for name, (r, p, a, f) in vals.items():
        out[name] = {
            "mean_max_avg_load_ratio": one(r),
            "mean_peak_relay_load": one(p),
            "mean_avg_relay_load": one(a),
            "active_fraction_mean": one(f),
            "demotions": one(5.0),
            "vsepr_flaps": one(1.0),
        }
    return out


@pytest.mark.parametrize(
    "naive,damped,verdict",
    [
        # the peak falls only because there are more relays: not balancing
        ((2.5, 5.0, 2.0, 0.8), (2.1, 8.5, 4.0, 0.5), "refuted"),
        ((1.5, 5.0, 3.3, 0.5), (1.6, 6.0, 3.8, 0.5), "confirmed"),  # both balance
        ((1.8, 5.0, 2.8, 0.8), (2.1, 8.5, 4.0, 0.5), "partly"),  # naive's ratio improves only
        ((2.5, 9.0, 3.6, 0.8), (2.1, 8.5, 4.0, 0.5), "refuted"),  # nothing improves
    ],
)
def test_flattening_verdict_separates_balancing_from_adding_relays(naive, damped, verdict):
    vs = _variants(naive=naive, damped=damped, off=(2.1, 8.6, 4.1, 0.5))
    fs = make_findings({"vsepr": {"variants": vs}})
    f = next(f for f in fs if f["id"] == "vsepr-flattening")
    assert f["verdict"] == verdict
    assert "hot spot" not in f["measured"]  # no untested causal claim


def test_findings_format_counts_from_data_not_by_hand(quick_suite):
    _, res = quick_suite
    alt = json.loads(json.dumps(res))
    alt["recovery"]["n"] = 99
    alt["recovery"]["cases"]["kill60"]["killed"] = {"mean": 77.0, "min": 77.0, "max": 77.0}
    fs = {f["id"]: f for f in make_findings(alt)}
    assert "of 99" in fs["death-threshold"]["measured"]
    assert "when 77 died" in fs["death-threshold"]["measured"]
    assert "77 of 99" in fs["rto-arithmetic"]["measured"]
    c20 = next(r for r in res["topology"] if r["cage"] == "C20")
    assert f"11 to {c20['n']} users" in fs["c20-count"]["next_step"]
    cut = min(r["min_vertex_cut"] for r in res["topology"])
    assert f"any {cut - 1} node failures" in fs["topology-cut"]["next_step"]


def test_topology_finding_flags_monte_carlo_estimates(quick_suite):
    _, res = quick_suite
    c60 = next(r for r in res["topology"] if r["cage"] == "C60")
    f = next(f for f in res["findings"] if f["id"] == "topology-cut")
    assert c60["partition_exact"][2]  # C(60, 3) is enumerated: quoted without "about"
    assert c60["partition_probability"]["3"] == pytest.approx(60 / 34220, abs=1e-6)
    assert "0.18% of 3-node" in f["measured"]
    assert not c60["partition_exact"][5]  # C(60, 6) is sampled, and says so
    assert "about" in f["measured"] and "Monte Carlo" in f["measured"]


def test_hell_finding_quotes_the_living_cell_first(quick_suite):
    _, res = quick_suite
    f = next(f for f in res["findings"] if f["id"] == "hell-ambiguity")
    assert f["measured"].startswith("In the living cell")
    assert f["measured"].index("living cell") < f["measured"].index("static")


def test_results_markdown_is_deterministic(quick_suite):
    _, res = quick_suite
    assert results_markdown(res) == results_markdown(json.loads(json.dumps(res)))
