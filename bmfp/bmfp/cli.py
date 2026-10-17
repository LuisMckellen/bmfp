"""``bmfp`` command line: ``run`` one cell, ``experiments`` (E1..E7), ``export-web``,
``readme``."""

from __future__ import annotations

import json
import time
from dataclasses import fields
from pathlib import Path

import typer

from .experiments import FULL, QUICK, Plan, run_suite
from .export import write_web_data
from .metrics import clean
from .readme import update_readme
from .sim import Config, Simulation

app = typer.Typer(add_completion=False, no_args_is_help=True, help="BMFP cell simulator")

_FIELD_TYPES = {f.name: f.type for f in fields(Config)}


def _parse_set(items: list[str]) -> dict:
    out = {}
    for item in items:
        if "=" not in item:
            raise typer.BadParameter(f"--set expects key=value, got {item!r}")
        k, v = item.split("=", 1)
        k = k.strip().replace("-", "_")
        if k not in _FIELD_TYPES:
            raise typer.BadParameter(f"unknown Config field {k!r}")
        default = Config().__getattribute__(k)
        if v.lower() in ("none", "null"):
            out[k] = None
        elif isinstance(default, bool):
            out[k] = v.lower() in ("1", "true", "yes", "on")
        elif isinstance(default, int) and not isinstance(default, bool):
            out[k] = int(v)
        elif isinstance(default, float) or "float" in str(_FIELD_TYPES[k]):
            out[k] = float(v)
        else:
            out[k] = v
    return out


def format_summary(s: dict) -> str:
    def f(x, d=3):
        return "n/a" if x is None else (f"{x:.{d}f}" if isinstance(x, float) else str(x))

    lines = [
        f"BMFP {s['cage']}  seed={s['seed']}  duration={s['duration']:g}s  routing={s['routing']}"
        f"  vsepr={s['vsepr']}",
        f"sent {s['sent']}  delivered {s['delivered']}  delivery ratio {f(s['delivery_ratio'])}"
        f"  deliverable ratio {f(s['deliverable_ratio'])}",
        "drops  " + "  ".join(f"{k[6:]}={s[k]}" for k in s if k.startswith("drops_")),
        f"mean hops {f(s['mean_hops'], 2)}  tx/delivered {f(s['tx_per_delivered'], 2)}  "
        f"duplicates/delivered {f(s['duplicates_per_delivered'])}  "
        f"out-of-order/delivered {f(s['out_of_order_per_delivered'], 4)}",
        f"VSEPR demotions {s['demotions']}  promotions {s['promotions']}  flaps {s['flaps']} "
        f"(vsepr {s['vsepr_flaps']})  ACTIVE changes/min {f(s['state_changes_per_min'], 1)}  "
        f"ACTIVE {f(s['active_fraction_start'], 2)} -> {f(s['active_fraction_end'], 2)}",
    ]
    if s.get("kill_at") is not None:
        lines.append(
            f"kill at {s['kill_at']:g}s: killed {s['killed']}  death event {s['death_event']}  "
            f"path {s['path']}  rto_service {f(s['rto_service_s'], 1)}s  "
            f"journal formula {f(s['rto_journal_formula_s'], 1)}s  rpo {f(s['rpo_s'], 2)}s"
        )
    return "\n".join(lines)


@app.command()
def run(
    cage: str = typer.Option("C60", help="C12 | C20 | C24 | C60"),
    duration: float = typer.Option(600.0, help="simulated seconds"),
    seed: int = typer.Option(0),
    routing: str = typer.Option("chill", help="chill|duplicate|stripe|adaptive_*"),
    vsepr: str = typer.Option("naive", help="naive | damped | off"),
    send_rate: float = typer.Option(20.0, help="msgs/s for the cell (ASSUMPTION)"),
    link_loss: float = typer.Option(0.0),
    kill_at: float | None = typer.Option(None, help="scripted kill time (s)"),
    kill_fraction: float = typer.Option(0.5),
    churn_rate: float = typer.Option(0.0),
    set_: list[str] = typer.Option([], "--set", help="any Config field, key=value"),
    json_out: bool = typer.Option(False, "--json", help="print the summary as JSON"),
    out: Path | None = typer.Option(None, help="write the full RunResult JSON here"),
) -> None:
    """Run one simulation and print its summary."""
    kw = dict(
        cage=cage,
        duration=duration,
        seed=seed,
        routing=routing,
        vsepr=vsepr,
        send_rate=send_rate,
        link_loss=link_loss,
        kill_at=kill_at,
        kill_fraction=kill_fraction,
        churn_rate=churn_rate,
    )
    kw.update(_parse_set(set_))
    try:
        cfg = Config(**kw)
    except (ValueError, KeyError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    res = Simulation(cfg).run()
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(clean({"config": cfg.to_dict(), **res.to_dict()})))
    if json_out:
        typer.echo(json.dumps(clean(res.summary), indent=1))
    else:
        typer.echo(format_summary(res.summary))


@app.command()
def experiments(
    out: Path = typer.Option(Path("reports"), help="output directory"),
    quick: bool = typer.Option(False, help="tiny durations (smoke test only)"),
    plots: bool = typer.Option(True, help="write PNG plots"),
    seeds: str | None = typer.Option(None, help="comma-separated seeds (default 1,2,3,4,5)"),
) -> None:
    """Run E1..E7 and write reports/<id>.json, PNGs and bmfp_results.md."""
    plan: Plan = QUICK if quick else FULL
    if seeds:
        from dataclasses import replace

        plan = replace(plan, seeds=tuple(int(x) for x in seeds.split(",") if x.strip()))
    t0 = time.perf_counter()
    res = run_suite(out, plan, plots=plots, progress=lambda k: typer.echo(f"running {k} ..."))
    dt = time.perf_counter() - t0
    for f in res["findings"]:
        typer.echo(f"[{f['verdict']}] {f['problem']}")
    typer.echo(f"wrote {out}/bmfp_results.md in {dt:.1f} s")


@app.command("export-web")
def export_web(
    out: Path = typer.Option(Path("docs/data"), help="output directory"),
    quick: bool = typer.Option(False, help="tiny durations (smoke test only)"),
    from_reports: Path | None = typer.Option(
        None, help="reuse a `bmfp experiments` output dir instead of recomputing"
    ),
) -> None:
    """Write bmfp-data.js (window.BMFP_DATA) for the portfolio site."""
    path = write_web_data(out, quick=quick, from_reports=from_reports)
    typer.echo(f"wrote {path} ({path.stat().st_size} bytes)")


@app.command()
def readme(
    reports: Path = typer.Option(Path("reports"), help="a `bmfp experiments` output dir"),
    path: Path = typer.Option(Path("README.md"), "--readme", help="the README to update"),
    check: bool = typer.Option(False, help="only report whether the README is out of date"),
) -> None:
    """Rewrite the README's generated blocks (summary, parameters, results, findings)."""
    changed = update_readme(path, reports, check=check)
    if check:
        if changed:
            typer.echo(f"{path} is out of date with {reports}; run `bmfp readme`")
            raise typer.Exit(1)
        typer.echo(f"{path} matches {reports}")
    else:
        typer.echo(f"{'updated' if changed else 'unchanged'}: {path}")
