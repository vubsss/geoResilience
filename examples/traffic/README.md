# Hyderabad traffic comparison pilot

The latest audit and deterministic-input workflow are documented in
`docs/traffic/traffic_audit.md`. Use the validation commands below for the updated
comparison. The original workflow is preserved for the earlier saved experiment;
its raw simplified-tag preparation can depend on list order.

This experiment uses the existing `georesilience` static traffic solver. It does
not change the CLI, production demand preparation, existing metrics or previous
results. It tests a possible change in the comparison between Gachibowli and Old
Hyderabad; a ranking reversal is not a condition for accepting the experiment.

Place `gachibowli.zip` and `old-hyderabad.zip` in the repository root. With the
project environment installed, run from that root in PowerShell:

```powershell
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe examples/traffic/run_pilot.py
```

The archives are extracted into ignored `data/traffic_comparison/`. Each path is
checked to remain inside that directory; different existing inputs are preserved
with an error. No Python files from the archives are executed.

Outputs go into ignored `results/traffic_comparison/`. To repeat an experiment,
select a new output directory; existing results are not overwritten:

```powershell
.venv/Scripts/python.exe examples/traffic/run_pilot.py --output results/traffic_comparison_repeat
```

## Fixed comparison rules

- Rebuild each directed graph with the current loader, consolidation disabled,
  and the largest strongly connected component retained, matching the old runs.
- Require exact matches with the archived population node identities and locations.
  Preserve the archived population allocation, including its coverage limitations.
- Use common, projected 500 m cells and population-weighted representative road
  nodes. The sensitivity case uses 750 m cells. Empty cells are absent.
- Use the existing constrained gravity adapter, with population supplying both
  origin and destination margins. This is an explicitly synthetic resident-based
  approximation; the actual production/attraction split remains future work.
- Generate interzonal demand at 0.05, 0.1 and 0.2 effective PCU/person/hour.
  Intrazonal trips, jobs, visitors and through trips are not estimated.
- Retain speed tags and use the same assumed fallback speed table by road class
  for both areas. Neither speed limits nor fallback speeds are observed travel times.
- Use the existing lane/width capacity parser with the same 1,000 PCU/hour/lane
  and one-lane-per-direction fallback. Test 500 PCU/hour/lane and a uniform
  1,000 PCU/hour/arc control. Missing tags do not establish actual road width.
- Use BPR with alpha 0.15, beta 4, gravity decay 0.08/minute, relative gap 0.001,
  and a maximum of 600 iterations. These are scenario settings, not local calibration.
- Apply a separate 10,000 PCU/hour total-demand control to both areas; their
  spatial OD distributions still differ. This does not control all other differences.

Cases are defined in `CASES` before traffic results are inspected. Both areas run
every case. No area-specific coefficient is adjusted to produce a desired ranking.

## Files to inspect

- `experiment.json`: assumptions, cases, versions, code hash and limitations.
- `comparison.csv`: all area/case summaries, convergence and conservation checks.
- `scenario_comparison.png`: delay and travel-time-index sensitivity comparisons.
- `base_vc_maps.png`: base-case maps on a common V/C colour scale.
- `<area>/input_audit.json`: graph/population hashes, cleaning and tag coverage.
- `<area>/<case>/zone_membership.csv` and `zone_masses.csv`: population aggregation.
- `<area>/<case>/input_od.csv`: solver input demand.
- `<area>/<case>/traffic_arcs.csv`: directed volume, capacity, congestion and seconds.
- `<area>/<case>/traffic_od.csv`: demand-weighted trip-cost evidence.
- `<area>/base/traffic.gpkg`: mapped directed arc outputs for GIS inspection.

Do not infer an overall resilience score from these traffic summaries. Existing
bridge, detour, centrality, attack and distance-Hansen metrics are not recalculated
or redefined. The archives contain older metric versions. This pilot compares
traffic costs; it does not certify an end-to-end run of every current metric.
The full pipeline additionally requires the original population GeoTIFF, which
is not included in these archives.

## Recalculate previous-tier metrics against the traffic costs

The separate metric experiment requires NetworKit (this run used 11.2.2), an
optional dependency that is already available in the project environment used
for these results. It does not add a requirement to the core pipeline.

Run these commands after the traffic pilot finishes:

```powershell
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe examples/traffic/run_metrics_comparison.py --stage baseline
.venv/Scripts/python.exe examples/traffic/run_metrics_comparison.py --stage attack
.venv/Scripts/python.exe examples/traffic/run_legacy_attack.py
.venv/Scripts/python.exe examples/traffic/run_metrics_comparison.py --stage reliability
.venv/Scripts/python.exe examples/traffic/run_metrics_comparison.py --stage local
.venv/Scripts/python.exe examples/traffic/summarize_metrics.py
```

Detailed outputs and the generated report are in `results/traffic_metrics/`.
Both current and mid-evaluation attack definitions are reported. Historical
distance attack results are checked against the archives. The composite uses
the user-confirmed 25% attack and 15% each for the other five indices.

Distance and time metrics are labelled separately. Time Hansen uses a declared
six-minute half-life with three/twelve-minute sensitivity. Physical roads,
populations and failure probabilities are preserved while routing costs change.
Local information/removal metrics use an explicitly exported common screening
set; their unevaluated values are blank, never interpreted as zero.

## Validate both simulations and reassign traffic after road failures

```powershell
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe examples/traffic/validate_traffic_service.py
.venv/Scripts/python.exe examples/traffic/summarize_traffic_validation.py --stage global
.venv/Scripts/python.exe examples/traffic/summarize_traffic_validation.py --stage report
```

The default output is `results/traffic_validation_v2/`. A repeat must use a fresh
`--output` path on the validator and the same path as `--root` on the summarizer.
The validator preserves existing outputs and refuses to overwrite a prior run.

This workflow audits the original saved BPR/flow equations, replays frozen solver
inputs, resolves ambiguous simplified tags deterministically, and runs fresh
assignments for both areas. It then reassigns surviving trip demand under 64
physical-road failure states, reporting unserved demand and convergence.

Both the original intact-congested reference and a separate fixed free-flow
service reference are reported, with predeclared 1.2/1.5/2.0 budget sensitivities.
The primary allowance remains the project's original 50%. These definitions are
kept separate; composite coefficients are not adjusted to obtain a ranking.

All-node betweenness/Hansen, efficiency, detours and the historical directed
attack protocol are refreshed against the new costs in `metrics/`. This does
not silently integrate changes into the production CLI. Earlier screened local
information/removal tables belong to the earlier saved experiment.
