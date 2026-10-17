"""``meshguard`` command line: ``run`` one seed, ``sweep`` seeds into a table, ``export-web``."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from .calibration import plot_reliability
from .pipeline import MAX_RISK, PipelineResult, run_pipeline
from .selective import plot_coverage_risk

app = typer.Typer(add_completion=False, no_args_is_help=True, help="MeshGuard MVP")


def _write_reports(res: PipelineResult, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    m = res.metrics
    ev, y = res.eval, res.labels
    plot_reliability(
        res.p_final[ev], y[ev], out / "reliability_before.png", "Before calibration (eval blocks)"
    )
    plot_reliability(
        res.p_calibrated[ev],
        y[ev],
        out / "reliability_after.png",
        "After temperature scaling (eval blocks)",
    )
    plot_coverage_risk(res.curves, out / "coverage_risk.png", MAX_RISK, res.selection)
    n_rows = 200
    frame = res.vote_matrix.to_frame()
    frame["p_anomaly"] = res.p_final
    frame["p_calibrated"] = res.p_calibrated
    frame["split"] = ["dev" if d else "eval" for d in res.dev]
    frame["truth_eval_only"] = y.astype(int)
    interesting = frame[(frame["truth_eval_only"] == 1)].head(n_rows // 2)
    rest = (
        frame[(frame["truth_eval_only"] == 0)]
        .iloc[:: max(1, len(frame) // n_rows)]
        .head(n_rows // 2)
    )
    interesting.merge(rest, how="outer").sort_values(["step", "node"]).to_csv(
        out / "votes_sample.csv", index=False
    )
    (out / "metrics.json").write_text(json.dumps(m, indent=2, default=str))


def format_summary(m: dict) -> str:
    st, cal, sel = m["stages_eval"], m["calibration"], m["selective"]
    cfg = m["config"]
    lines = [
        f"MeshGuard  seed={cfg['seed']} sensors={cfg['n_sensors']} steps={cfg['steps']}  "
        f"anomaly rate={m['anomaly_rate']:.3f}  eval rows={m['n_eval']}",
        "",
        f"{'stage (eval blocks)':34s} {'AUPRC':>7s} {'F1':>7s} {'Brier':>7s} {'ECE':>7s}",
    ]
    for name, r in st.items():
        lines.append(
            f"{name:34s} {r['auprc']:7.3f} {r['f1']:7.3f} {r['brier']:7.4f} {r['ece']:7.4f}"
        )
    lines += [
        "",
        f"calibration  T={cal['temperature']:.2f}  ECE before={cal['ece_before']:.4f}  "
        f"temperature={cal['ece_temperature']:.4f}  isotonic={cal['ece_isotonic']:.4f}",
        f"selective    max_risk={sel['max_risk']}: eval coverage={sel['eval_coverage']:.3f} "
        f"risk={sel['eval_risk']:.4f}  |  max_risk={sel['strict']['max_risk']}: "
        f"coverage={sel['strict']['eval_coverage']:.3f} risk={sel['strict']['eval_risk']:.4f}",
        f"isolation    clean-run quarantines: {m['isolation_clean']['quarantined'] or 'none'}",
    ]
    if "rogue_scenario" in m:
        r = m["rogue_scenario"]
        lines.append(
            f"rogue test   injected {r['injected']['lf_name']} in zone {r['injected']['zone']}: "
            f"quarantined={r['injected_rogue_quarantined']}  "
            f"F1 no-isolation={r['variants_eval']['no_isolation']['f1']:.3f} "
            f"isolation={r['variants_eval']['isolation']['f1']:.3f}"
        )
    lines.append("")
    lines += m["flags"] or ["no negative results flagged"]
    return "\n".join(lines)


@app.command()
def run(
    seed: int = typer.Option(42, help="Simulation seed"),
    sensors: int = typer.Option(20, help="Number of sensors on the ring"),
    steps: int = typer.Option(500, help="Time steps"),
    out: Path = typer.Option(Path("reports"), help="Output directory"),
) -> None:
    """Run the full pipeline once and write reports."""
    res = run_pipeline(seed=seed, n_sensors=sensors, steps=steps)
    _write_reports(res, out)
    typer.echo(format_summary(res.metrics))
    typer.echo(f"\nreports written to {out}/")


@app.command()
def sweep(
    seeds: list[int] = typer.Option([42, 43, 44, 45, 46], "--seed", help="Seeds (repeatable)"),
    sensors: int = typer.Option(20),
    steps: int = typer.Option(500),
    out: Path = typer.Option(Path("reports/sweep.md"), help="Markdown table output"),
) -> None:
    """Run several seeds and write a markdown results table (used by the README)."""
    header = (
        "| seed | MV AUPRC | DS AUPRC | DS+iso AUPRC | MV F1 | DS F1 | DS+iso F1 "
        "| ECE raw | ECE temp | ECE iso | rogue quarantined |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|"
    )
    rows = []
    for s in seeds:
        m = run_pipeline(seed=s, n_sensors=sensors, steps=steps).metrics
        st, c = m["stages_eval"], m["calibration"]
        rows.append(
            f"| {s} | {st['majority_vote']['auprc']:.3f} | {st['dawid_skene']['auprc']:.3f} "
            f"| {st['dawid_skene_isolation']['auprc']:.3f} | {st['majority_vote']['f1']:.3f} "
            f"| {st['dawid_skene']['f1']:.3f} | {st['dawid_skene_isolation']['f1']:.3f} "
            f"| {c['ece_before']:.4f} | {c['ece_temperature']:.4f} | {c['ece_isotonic']:.4f} "
            f"| {m['rogue_scenario']['injected_rogue_quarantined']} |"
        )
    table = "\n".join([header, *rows])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(table + "\n")
    typer.echo(table)


@app.command("export-web")
def export_web(
    out: Path = typer.Option(Path("docs/data"), help="Directory for meshguard-data.js"),
    seeds: list[int] = typer.Option([42, 43, 44, 45, 46], "--seed", help="Seeds (repeatable)"),
) -> None:
    """Write the website's data file (every MeshGuard number the site shows)."""
    from .export import write_site_data

    path = write_site_data(out, tuple(seeds))
    typer.echo(f"wrote {path} ({path.stat().st_size} bytes)")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
