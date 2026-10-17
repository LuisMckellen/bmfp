# BMFP

Code for the Bucket Minister Fullerene Protocol (BMFP): a simulator for its design, a
portfolio site that replays the simulator's runs, and a companion anomaly-detection project.

The design journal that this code tests lives in
[BMFP-DESIGN-JOURNAL](https://github.com/LuisMckellen/BMFP-DESIGN-JOURNAL).

![The BMFP site: a C60 cell replayed by the simulator](docs/assets/preview.png)

| Path | What it is |
|---|---|
| [`bmfp/`](bmfp/README.md) | Deterministic discrete-event simulator of one BMFP cell (C12, C20, C24, C60), with [`SPEC.md`](bmfp/SPEC.md), experiments and tests |
| [`docs/`](docs/README.md) | Static website (GitHub Pages: Settings → Pages → Deploy from branch → `main` / `/docs`) |
| [`meshguard/`](meshguard/README.md) | Weak-supervision anomaly detection for unlabeled IoT sensor streams |

```bash
pip install -e bmfp -e meshguard
bmfp experiments --out reports/            # simulator experiments
bmfp export-web --out docs/data            # regenerate the site's data
meshguard export-web --out docs/data
python -m http.server -d docs 8000
```

Every number on the site and in the READMEs is produced by a command in this repo. Written
with Claude Code (Anthropic) from the author's design and direction. MIT license.
