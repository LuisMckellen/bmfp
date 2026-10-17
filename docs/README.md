# docs/ — the BMFP portfolio site

A single static page that replays the BMFP simulator's runs and shows the MeshGuard results.
No build step, no framework, no external JavaScript. GitHub Pages serves this folder as is.

Every measured number on the page is read from two data files. The page's own text quotes
only the journal's design targets (on the ladder, labelled as targets) and the definitions of
the measures (for example, the 5 s window behind the live delivery ratio). Sentences around the
numbers, such as each finding's wording, are written into the code that formats them:

| File | Global | Written by |
|---|---|---|
| `data/bmfp-data.js` | `window.BMFP_DATA` | `bmfp export-web --out docs/data` |
| `data/meshguard-data.js` | `window.MESHGUARD_DATA` | `meshguard export-web --out docs/data` |

## View it locally

Open `docs/index.html` in a browser. The data files load with plain `<script src>` tags, so
`file://` works. Or serve the folder:

```bash
python -m http.server -d docs 8000   # then open http://localhost:8000
```

## Regenerate the data

From the repository root:

```bash
pip install -e bmfp -e meshguard
bmfp experiments --out reports/        # optional: tables, plots and findings in reports/
bmfp export-web --out docs/data        # writes docs/data/bmfp-data.js
meshguard export-web --out docs/data   # writes docs/data/meshguard-data.js
```

Both exports are deterministic: the same commands write byte-identical files.

## Turn on GitHub Pages

Settings → Pages → Build and deployment → Source: **Deploy from a branch** → Branch: `main`,
folder: `/docs` → Save. The empty `.nojekyll` file tells Pages to serve the files unchanged.

## Files

| Path | What it is |
|---|---|
| `index.html` | The page: markup, copy, and one inline `<style>` whose `:root` block is the token plan (palette, type, layout). |
| `cage.js` | The 3D ball-and-stick cage on `<canvas>`: manual perspective projection, depth-sorted drawing, drag, touch and arrow-key rotation, theme-aware colours. |
| `charts.js` | A small SVG chart kit: line charts and dot-and-whisker plots, each with a hover and keyboard tooltip and a table-view twin. |
| `app.js` | Reads the two globals and renders every section. A missing key renders as "—"; it never throws. |
| `data/` | The two generated data files. |
| `dev/fixture-bmfp-data.js` | Placeholder data with the export's shape and made-up values (every text starts with `FIXTURE`). Used only when `data/bmfp-data.js` is missing. |
| `dev/make-fixture.cjs` | Rebuilds the fixture: `node docs/dev/make-fixture.cjs docs`. |
| `dev/palette-validation.txt` | Validator output for the node-state and chart palettes, light and dark. |
| `tests/smoke.cjs` | Playwright smoke test (below). |

### When the simulator data is missing

`app.js` checks for `window.BMFP_DATA` after the data scripts run. If it is undefined, it loads
`dev/fixture-bmfp-data.js` and shows a notice at the top of the page saying the numbers are
placeholders. With the real file present the fixture is never loaded.

## Smoke test

```bash
PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers NODE_PATH=/opt/node22/lib/node_modules node docs/tests/smoke.cjs
```

It opens `index.html` over `file://` at 1280×900 and 400×860, in light and dark, and checks:
no console or page errors; every section heading is present; no horizontal page scroll (with
every drawer open); switching scenarios changes the state counts; scrubbing changes the time
label and Space starts playback; every chart has a table view that opens; a live chart shows a
tooltip on hover; and the fixture notice appears only when the fixture is in use. It also
guards the fixes from the design review: focus stays in the event log during playback; Space on
a live chart plays and pauses without scrolling; chart ids stay the same across scenario
switches and replaced charts are released; no ladder tile claims a test for a "not simulated"
finding; the E2 chart plots the VSEPR-only change rate; E3 shades seconds with nothing to plot;
event text names node ids as nodes; the settings drawer files only the journal's own kill share
as a journal input and never shows a bare "none"; every header link can be reached at phone
width; and no chart text runs outside its chart. Screenshots
go to `$SHOT_DIR` (default `/tmp/claude-0/shots`). Set `PLAYWRIGHT_BROWSERS_PATH` to wherever
Playwright's Chromium lives, or leave it unset if Playwright can find it.

Behind an HTTPS proxy (`HTTPS_PROXY` set), the test fetches Google Fonts through `curl` so the
screenshots use the real typefaces. Font failures are reported as notes, not test failures.

## Design notes

- Light theme is engineering paper; dark theme is a blackboard. Type: Unbounded for display,
  Atkinson Hyperlegible for text, IBM Plex Mono for data.
- Node states are model-kit colours, and each also has its own shape so colour never carries
  state alone: ACTIVE is a filled ball, STANDBY a ring, GHOST a faint hollow circle, DEAD a
  cross. Stems carry a light centre dot, captains a small pennant, and a halo shows the relay
  load that second.
- Charts follow one y-axis per chart, 2 px lines, hairline solid gridlines, a legend for two or
  more series, chart text in text colours (never series colours), a hover and keyboard tooltip,
  and a table view.
- Everything respects `prefers-reduced-motion`: no auto-rotation and no autoplay.
