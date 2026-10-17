# MeshGuard (MVP)

Weakly supervised anomaly detection for **unlabeled** IoT sensor streams on a ring mesh.
Pipeline: simulator -> 6 labeling functions -> Dawid-Skene label model -> failure-domain
isolation -> calibration -> selective prediction. No LLM, no external API, no real mesh stack.

## Run it

```bash
pip install -e ".[dev]"
meshguard run --seed 42 --sensors 20 --steps 500 --out reports/   # one full run + reports
meshguard sweep --out reports/sweep.md                            # the table below (seeds 42-46)
meshguard export-web --out ../docs/data                           # data file for the portfolio site
pytest -q && ruff check .                                         # tests + lint
```

`run` writes `metrics.json`, `reliability_before.png`, `reliability_after.png`,
`coverage_risk.png`, `votes_sample.csv` and prints a summary including every negative result.

## What the code does

| Module | Role |
|---|---|
| `simulator.py` | Ring of N sensors, T steps; normal / drifting / stuck / dead regimes, >=2 faulty nodes, benign spikes and dropouts on healthy nodes. Ground truth is returned separately from readings. Deterministic per seed. |
| `labeling.py` | 6 LFs (+1 anomaly / -1 normal / 0 abstain): rate of change, range check, silence, 3-sigma on mesh-median residual, neighbour correlation, stuck value. |
| `dawid_skene.py` | Hand-written EM in NumPy; per-LF 2x3 confusion matrices (abstain is informative); optional per-vote weights. |
| `calibration.py` | ECE, reliability curve/diagram, temperature scaling (NLL), isotonic (scikit-learn PAV). |
| `selective.py` | Coverage-risk curve, threshold for `max_risk=0.05`, AURC. |
| `isolation.py` | Zones of 5 sensors; quarantine an (LF, zone) after accuracy < 0.55 for K=3 windows of 25 steps; down-weight sensors whose votes disagree with pseudo-labels. |
| `pipeline.py`, `cli.py` | Orchestration, metrics, negative-result flags, reports. |

## What is tested

Run `pytest -q` for the current count. Coverage by area: simulator determinism and regime
behaviour; each LF on hand-built inputs plus a contract test on simulated data; Dawid-Skene
**accuracy recovery within +/-0.05** on synthetic votes (several seeds, priors, abstain rates,
asymmetric confusion); ECE near 0 when calibrated and > 0.05 when miscalibrated, temperature
scaling reducing ECE; risk -> 0 as coverage -> 0; quarantine firing on an injected rogue LF
(synthetic and end-to-end); CLI producing all report files and reproducible `metrics.json`.

## What is NOT tested / not claimed

- No multi-seed isolation study; the sweep below is five seeds of one simulator configuration.
- The simulator is the only data. Nothing here says the LFs or thresholds transfer to real sensors.
- Calibration and the selective threshold use a small **labelled dev split** (30% of 25-step
  time blocks, all nodes of a block together). "Unlabeled" therefore applies to the label
  model, not to calibration. Adjacent steps are autocorrelated, so the dev/eval split can leak.
- Isolation pseudo-labels come from a batch Dawid-Skene fit, so quarantine is causal in time
  but the analysis is offline. A quarantine, once triggered, is latched.
- The 3-sigma LF uses whole-stream statistics (offline).
- LFs are not independent, which violates a Dawid-Skene assumption; estimated LF accuracy is
  only checked loosely against ground truth on simulated runs.
- Rogue-LF scenario: one fixed injection (`range_check` inverted in zone 0 from step 100).

## Results

All numbers are on held-out eval blocks. Regenerate with `meshguard sweep` (seeds 42-46).
MV = majority vote, DS = Dawid-Skene, iso = isolation (quarantine + sensor down-weighting).

| seed | MV AUPRC | DS AUPRC | DS+iso AUPRC | MV F1 | DS F1 | DS+iso F1 | ECE raw | ECE temp | ECE iso | rogue quarantined |
|---|---|---|---|---|---|---|---|---|---|---|
| 42 | 0.965 | 0.951 | 0.941 | 0.814 | 0.943 | 0.864 | 0.0158 | 0.0293 | 0.0175 | True |
| 43 | 0.948 | 0.945 | 0.944 | 0.869 | 0.920 | 0.886 | 0.0212 | 0.0204 | 0.0083 | True |
| 44 | 0.933 | 0.933 | 0.935 | 0.803 | 0.910 | 0.869 | 0.0257 | 0.0173 | 0.0085 | True |
| 45 | 0.918 | 0.927 | 0.924 | 0.802 | 0.888 | 0.818 | 0.0281 | 0.0280 | 0.0222 | True |
| 46 | 0.899 | 0.897 | 0.897 | 0.751 | 0.774 | 0.774 | 0.0263 | 0.0216 | 0.0195 | True |

### Negative and mixed results (see `flags` in `metrics.json` for any seed)

- **Dawid-Skene vs majority vote:** better F1 on every seed, but AUPRC is not better in general
  (seed 42: lower; seeds 43, 44, 46: tied within 0.003; only seed 45 is higher).
- **Isolation on clean data hurts F1** on seeds 42-45 and is neutral on 46. The sensor
  down-weighting step is the cause: quarantine alone left seed 42's F1 unchanged. A truly
  faulty sensor disagrees with some LFs, so it gets down-weighted.
- **Isolation with an injected rogue LF:** the rogue is quarantined on all five seeds (on seed 42
  from step 175), but eval F1 on seed 42 dropped (see `rogue_scenario` in `metrics.json`).
  AUPRC rose there. Run `meshguard run --seed 42` to see both.
- **Temperature scaling does not reliably reduce ECE** here (seed 42 got worse; 44 and 46 improved;
  43 and 45 changed by less than 0.001). Isotonic improved ECE on seeds 43-46 but not 42. Raw ECE
  is already about 0.02 and the dev split is small, so there is little room to show a gain.
- **Selective prediction at `max_risk=0.05` is almost vacuous:** full-coverage risk is already
  below 5%, so the threshold accepts nearly everything. `metrics.json` also reports `max_risk=0.01`.

## What next

1. Drop or redesign sensor down-weighting; keep quarantine and compare on many seeds.
2. Multi-seed isolation study with varied rogue LFs/zones and false-quarantine rates.
3. Model LF correlations (or use a different label model) and check accuracy recovery on correlated votes.
4. Calibrate without ground truth, or quantify how small the dev set can be.
5. Replace the simulator with recorded sensor data.
