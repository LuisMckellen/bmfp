"""Splice the generated parts of ``README.md`` from a ``bmfp experiments`` output directory.

The README keeps its prose by hand; everything between a ``<!-- generated:NAME -->`` marker
and its ``<!-- /generated:NAME -->`` partner is rewritten from the reports, so no number in
it is typed by hand:

* ``summary``: verdict counts and one line per finding (``findings.json``);
* ``params``: the Config provenance table (``bmfp_results.md``);
* ``results``: the E1..E7 sections of ``bmfp_results.md``, one heading level down, each with
  its plot;
* ``findings``: one bullet per finding (``findings.json``).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .experiments import EXPERIMENTS

BLOCKS = ("summary", "params", "results", "findings")
VERDICT_ORDER = ("confirmed", "partly", "refuted", "not simulated")


def _sections(md: str) -> dict[str, str]:
    out = {}
    for chunk in re.split(r"^## ", md, flags=re.M)[1:]:
        title, _, body = chunk.partition("\n")
        out[title.strip()] = body.strip()
    return out


def _count_line(findings: list[dict]) -> str:
    kinds = Counter(f.get("kind", "finding") for f in findings)
    parts = []
    for kind, label in (("claim", "journal claims"), ("problem", "problems")):
        if not kinds.get(kind):
            continue
        c = Counter(f["verdict"] for f in findings if f.get("kind") == kind)
        bits = [f"{c[v]} {v}" for v in VERDICT_ORDER if c.get(v)]
        parts.append(f"{kinds[kind]} {label} ({', '.join(bits)})")
    return f"{len(findings)} findings: " + "; ".join(parts) + "."


def summary_block(findings: list[dict]) -> str:
    lines = [
        f"From [`reports/findings.json`](reports/findings.json): {_count_line(findings)} "
        "For a claim, *confirmed* means it holds; for a problem, that the problem is real.",
        "",
    ]
    for f in findings:
        lines.append(f"- {f['problem']} ({f.get('kind', 'finding')}): **{f['verdict']}**")
    return "\n".join(lines)


def params_block(md: str) -> str:
    for title, body in _sections(md).items():
        if title.startswith("Parameters"):
            return body
    raise KeyError("Parameters section missing from bmfp_results.md")


def results_block(md: str, reports: Path) -> str:
    plots = {fname.split("_")[0].upper(): f"{fname}.png" for fname, _ in EXPERIMENTS.values()}
    out = []
    for title, body in _sections(md).items():
        m = re.match(r"(E\d+) ·", title)
        if not m:
            continue
        out.append(f"### {title}")
        out.append("")
        png = plots.get(m.group(1))
        if png and (reports / png).exists():
            out.append(f"![{title}](reports/{png})")
            out.append("")
        out.append(body)
        out.append("")
    return "\n".join(out).strip()


def findings_block(findings: list[dict]) -> str:
    return "\n".join(
        f"- **{f['problem']}** ({f.get('kind', 'finding')}; {f['journal_ref']}): "
        f"**{f['verdict']}**. {f['measured']} *Next step:* {f['next_step']}"
        for f in findings
    )


def render_blocks(reports: Path | str) -> dict[str, str]:
    reports = Path(reports)
    md = (reports / "bmfp_results.md").read_text()
    findings = json.loads((reports / "findings.json").read_text())
    return {
        "summary": summary_block(findings),
        "params": params_block(md),
        "results": results_block(md, reports),
        "findings": findings_block(findings),
    }


def splice(text: str, blocks: dict[str, str]) -> str:
    """Replace every generated block in ``text``; each marker pair must exist exactly once."""
    for name, body in blocks.items():
        start, end = f"<!-- generated:{name} -->", f"<!-- /generated:{name} -->"
        if text.count(start) != 1 or text.count(end) != 1:
            raise ValueError(f"README needs exactly one {start} ... {end} pair")
        a = text.index(start) + len(start)
        b = text.index(end)
        if b < a:
            raise ValueError(f"{end} comes before {start}")
        text = text[:a] + "\n" + body.strip("\n") + "\n" + text[b:]
    return text


def update_readme(readme: Path | str, reports: Path | str, check: bool = False) -> bool:
    """Rewrite the generated blocks of ``readme``. Returns True if the file was (or, with
    ``check``, would be) changed."""
    readme = Path(readme)
    old = readme.read_text()
    new = splice(old, render_blocks(reports))
    if new != old and not check:
        readme.write_text(new)
    return new != old
