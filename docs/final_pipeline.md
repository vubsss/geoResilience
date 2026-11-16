# Integrated population, traffic, flood and facility workflow

The default headline is **population-weighted**. Bridge and detour redundancy
retain their road-based definitions. Ordinary Hansen, targeted-attack SCC share,
travel-time reliability and mutual connectivity use resident weights for the
headline. All weighting views remain in `summary.json` for inspection.

With facilities configured, set `analysis.default_view` to
`"node_importance_weighted"` to include the already calculated population-plus-
facility importance in every node-weighted graph index and the headline
composite. Hansen uses importance at both origins and destinations; efficiency,
removal consequences and reliability use original distinct-pair `I_i*I_j`
weights; attack tracks original importance retained in the same selected SCC.
Bridge and detour retain their structural definitions. This additional view is
calculated automatically in every service-enabled run; the setting selects
which view appears in headline charts and maps. The direct `run` command accepts
`--default-view node_importance_weighted` with `--facilities`.

Population affects both traffic demand and outcome aggregation. These answer
different questions: how many trips load the roads, and how many residents are
affected by the resulting service. Neither is observed travel demand by default.

Road-capacity interpretation and actual tag/default coverage are documented in
[the capacity audit](traffic/capacity_audit.md). Road-attribute mode exports the
chosen per-arc capacity rules and assumptions; inferred capacities are not
measured observations.

## Run one complete study

```sh
python -m pip install -e ".[test,accelerated,closure-simulation]"
python -m georesilience.cli study --config study.json
```

All paths in `study.json` are relative to that file. `run` accepts the validated
framework configuration. `flood_config` is optional and points to the teammate
closure module's scenario JSON. Output must be a fresh directory.

```json
{
  "run": {
    "input": {"source": "graphml", "path": "inputs/roads.graphml"},
    "population": {"worldpop": "inputs/population_counts.tif"},
    "analysis": {"default_view": "population_weighted", "n_jobs": 2},
    "traffic": {"enabled": true, "demand_source": "population", "reassign_failures": true},
    "travel_time": {"highway_speeds_kph": {"residential": 20, "primary": 50}},
    "accessibility": {"cost": "auto", "half_time_minutes": 6},
    "output": {"dir": "results/my_study", "figures": true}
  },
  "flood_config": "inputs/flood_scenario.json"
}
```

With no `flood_config`, `run.reliability.p_fail_csv` may supply fingerprint-bound
probabilities. Otherwise the established default is
`1 - (1 - p0) ** length_km`, with `p0 = 0.01`. This is a generic length proxy,
not an estimate derived from flooding. The closure module's unresolved-road
uniform fallback is a different assumption and is reported separately.

The existing `run`, `closure`, `failures-template` commands remain available.
The `study` command automates the handoff: clean physical roads, export their
failure template, invoke flood enrichment, validate its complete probability CSV,
then execute the entire analysis with those probabilities.

## Saved population counts

Use exactly one of `population.worldpop` and `population.node_counts`:

```json
"population": {"node_counts": "inputs/previous_network.gpkg"}
```

Saved counts must be in the `nodes` layer with `node_id`, `population`, a CRS,
and point geometry. Every cleaned node ID must match exactly, with no duplicates,
and projected coordinates must agree within 0.1 m. Counts must be finite and
nonnegative. No nearest-neighbour redistribution or fabricated raster is used.
Original raster allocation losses cannot be reconstructed from retained node
counts; the output states this limitation. A uniform-node fallback does not
produce a resident-weighted headline composite.

## Traffic and graph costs

`accessibility.cost = "auto"` uses seconds when traffic is enabled, otherwise
the established distance metrics. Set `"distance"` or `"time"` explicitly to
override. Time Hansen defaults to a six-minute half-life with the existing
five-half-life cutoff. Local betweenness, detours, information centrality and
attack ranking consume the declared intact costs. Physical road identity,
failure probabilities and physical lengths are never recomputed from seconds.
Directional time detours divide alternative seconds by the original time in
that same direction. Undirected betweenness uses the minimum physical road's
mean directional cost, preserving the existing minimum-road convention.

Simplified-path tag lists are resolved conservatively and deterministically in
a traffic-only graph copy: minimum valid lane/width/speed and slowest configured
highway class. This does not change physical-link IDs or the cleaning fingerprint.
Widths declared in feet are converted before selecting the minimum.

For assignment traffic, `traffic.reassign_failures` defaults to true. Each
sample removes all directed arcs of the failed physical roads, determines which
original OD trips remain reachable, and solves a new equilibrium for those
trips. Unreachable demand is explicitly unserved; it is not redistributed to
other destinations or removed from the reliability denominators. A failed
convergence aborts publication rather than averaging only successful states.
The provider caches a bounded number of edge-cost snapshots.

The failure experiment preserves the existing reliability question: event time
must be no more than 1.5 times the intact congested time by default. This measures
disruption tolerance, not everyday speed. Supplied edge-time CSVs have no OD or
capacity model to reassign; their failure routing therefore uses fixed times.

## Composite normalization and weights

The composite defaults to four equal categories: redundancy, robustness,
accessibility and reliability each receive 25%. Metrics within a category split
its weight equally, giving these six component coefficients:

| Component | Weight | Conversion into composite |
| --- | ---: | --- |
| Bridge redundancy | 0.125 | `1 - bridge_fraction` |
| Detour redundancy | 0.125 | inverse median finite detour ratio |
| Targeted-attack robustness | 0.25 | raw AUC divided by actual removal horizon |
| Ordinary Hansen accessibility | 0.25 | already normalized |
| Travel-time reliability | 0.125 | original pair success fraction |
| Mutual connectivity reliability | 0.125 | original mutually connected pair fraction |

Positive-weight undefined components make the composite unavailable. Missing
components are never assigned zero or silently removed and renormalized.
For graphs and cross-metric comparisons, read `summary.headline.components` or
`composite.csv`. The older metric-family fields deliberately retain their raw
contracts: `detour_redundancy.value` is the median ratio, and
`targeted_attack_robustness.value` is the raw AUC. These raw quantities are not
the normalized component values used in the composite.
Weights must be finite, nonnegative fractions summing to one. Use, for example:

```json
"composite": {
  "weights": {
    "bridge": 0.10,
    "detour": 0.15,
    "attack": 0.20,
    "accessibility": 0.20,
    "travel_time_reliability": 0.20,
    "connectivity_reliability": 0.15
  }
}
```

That example is an optional user choice; it is **not** the default. Omitting the
section uses the four equal category weights above. Explicit weights stored in
existing configurations/manifests remain authoritative for historical replay.
The traditional CLI also supports
repeatable `--composite-weight METRIC=FRACTION`, `--default-view`,
`--population-nodes`, `--metric-cost`, `--half-time-minutes` and
`--fixed-failure-traffic`.

The framework retains its production attack protocol: adaptive, undirected
centrality recomputed after every physical-road removal, canonical UID ties,
raw curve AUC integrated to the actual integer horizon. The composite explicitly
normalizes that raw area. **Earlier presentation scripts used directed centrality
in 20 batches. Their attack and composite values are not interchangeable with
production values, even when the six coefficients are identical.**

## Facility importance and capacity accessibility

The existing service configuration and 2SFCA definitions are unchanged. Schools
and hospitals retain their distinct capacity units; raw scores are not bounded
by one and are never added to the normalized composite.
Facility count importance contributes to the `node_importance_weighted`
composite through attack, Hansen and reliability. Resident traffic demand and
2SFCA supply/demand ratios continue to use population counts. Raw capacity
accessibility and its closure shortfalls remain separate measures.

When assignment reassignment and 2SFCA are both enabled, catchments and
supply-demand ratios are recomputed for each evaluated failure state using a
static snapshot of that state's new equilibrium. Resident-to-facility reachability
and time reliability are also retained. Category population means and zero-access
shares are exported in `traffic_failure_states.csv` and summarized under
`services.failure_sfca`. Node/link facility criticality remains a separate screened
single-removal analysis using the intact traffic costs; facilities are assumed to
remain operating except for access or explicitly isolated nodes.

## Outputs and replay

```text
study-output/
  study_config.json
  prepared/network.gpkg                 # when flood is requested
  prepared/failure_template.csv
  flood/network_with_closure.gpkg
  flood/failure_probabilities.csv
  flood/closure_manifest.json
  flood/coverage_report.txt
  analysis/network.gpkg                 # nodes, edges, traffic_arcs, facilities
  analysis/summary.json                 # headline, all weighting views, service capacities
  analysis/composite.csv                # normalized components, weights, contributions
  analysis/attack_curve.csv
  analysis/traffic_arcs.csv
  analysis/traffic_od.csv
  analysis/traffic_failure_states.csv
  analysis/report.txt
  analysis/run_manifest.json
  analysis/figures/
  workflow_complete.json
```

`georesilience.pipeline.replay_manifest` verifies consumed-file hashes and
repeats the recorded analysis, including built-in traffic reassignment. A custom
external Python provider still needs to be supplied again. Flood inputs and
simulation assumptions have their own closure manifest.

Generate matching comparison CSV/PNG/SVG files with
`georesilience.comparison.compare_runs({"Area label": ".../analysis", ...}, ".../comparison")`.
The equivalent CLI is:

```sh
python -m georesilience.cli compare \
  --run "Gachibowli=results/final_pipeline/gachibowli_flood/analysis" \
  --run "Old Hyderabad=results/final_pipeline/old-hyderabad_flood/analysis" \
  --out results/final_pipeline/comparison
```

The comparison rejects mismatched headline views, component weights or graph-cost
definitions rather than drawing an ambiguous common-scale chart.
Normalized components and composites use fixed 0-1 axes; facility capacity
measures are deliberately not mixed onto those axes.

## Hyderabad reproduction and scope

With the original archives already extracted and the uploaded datasets in place:

```sh
python examples/traffic/prepare_final_study.py
python -m georesilience.cli study --config data/final_study/gachibowli_flood.json
python -m georesilience.cli study --config data/final_study/old-hyderabad_flood.json
```

The preparer uses the original graph and verified saved resident counts, and
the audited synthetic OD/capacity inputs from the completed traffic pilot. It
filters uploaded facilities to those study rectangles and applies the existing
500 m snap rule, recording exclusions. The source Gachibowli facility footprint
is incomplete; each institution has one assumed capacity unit. School demand
uses the existing all-resident proxy. These are not observed beds or seats.

The example flood scenarios reuse the **real** maximum-depth raster previously
generated with the pinned SFINCS image, reported daily rainfall and actual DEM;
probabilities are extracted afresh by the production closure module. Remove
`depth` from a scenario to execute rainfall-to-depth SFINCS again. The model
requires a running Docker engine or configured native executable and the
closure-simulation extras. Windows omits the POSIX-only Docker user argument.

The full-size acceptance configurations use 64 Monte Carlo states and existing
screened removal coverage. Both are explicit in the manifests; these are scenario
estimates, not calibrated claims about actual road failures. Increase sample
counts for tighter sampling bounds. Missing drainage, external river forcing,
terrain resolution, runoff/fragility calibration, boundary effects, road-attribute
coverage and incomplete facility capacity data remain scientific limitations.
