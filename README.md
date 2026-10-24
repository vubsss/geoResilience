# GeoResilience

GeoResilience analyses a local road network and a WorldPop population-count raster. A run reports structural and population-weighted resilience measures together, with their definitions, evaluated coverage and input assumptions.

## Install and run

From this repository, with Python 3.10 or newer:

```sh
python -m pip install -e .
georesilience run input/hyderabad --out results/hyderabad
```

Prepare a directory containing exactly one road file and one population raster:

```text
input/hyderabad/
  roads.osm          # .osm, .osm.xml or .graphml
  population.tif     # .tif or .tiff; georeferenced, one band, people per cell
  boundary.geojson   # optional; boundary.gpkg is also recognised
```

Basenames of the road and raster are arbitrary. Missing or multiple matches are errors. OSM PBF and arbitrary road-line vector files are unsupported. XML supports `drive` filtering (default) or `all` to retain supplied road classes. GraphML road classes/access tags are used as supplied, and the manifest records that no network filter was applied. Both inputs are simplified, projected to metres, optionally consolidated, and reduced to the largest strongly connected component; cleaning losses are recorded.

A supplied boundary takes precedence over the derived population crop. Without a boundary, the crop is the retained graph extent expanded by `--snap-max-m`. Valid count cells are assigned to their nearest retained node within that distance; unallocated counts within the selected crop are reported. The raster must overlap the study area and declare a CRS. WorldPop counts are modelled population estimates.

No YAML configuration is needed. Run `georesilience run --help` for all options.

## Main options

| Option | Default / meaning |
| --- | --- |
| `--out PATH` | Result directory; must be outside the input directory |
| `--overwrite`, `--no-figures`, `--boundary PATH` | Replace recognised result files; disable figures; supply a boundary |
| `--network-type drive` | Filtering for OSM XML; GraphML retains its supplied network |
| `--consolidation-m 15`, `--no-consolidation` | Intersection consolidation distance in metres, or disable it |
| `--snap-max-m 500` | Maximum raster-cell-to-node allocation distance in metres |
| `--failure-probs PATH`, `--require-complete-failures` | Explicit probability file; optionally require every link to have a value |
| `--p0 0.01`, repeatable `--p0-sweep NAME=P0` | Per-km event probability proxy; optional named sensitivity scenarios |
| `--connectivity-samples 10000`, `--travel-time-samples 1000` | Independent Monte Carlo event counts |
| `--time-threshold 0.5`, `--od-pairs PATH` | Permit time up to 1.5 × baseline; optional pair table |
| `--time-model free-flow`, `--time-attribute NAME`, `--speed HIGHWAY=KPH` | Resolve times from supplied speed information, or use `edge-attribute`; repeat `--speed` as needed |
| `--criticality-coverage screened` | Candidate removals by default; `all` evaluates every link and node and may be expensive |
| `--attack-fraction 0.20`, `--attack-steps 50`, `--attack-order adaptive` | Targeted physical-link attack; `static` also available |
| `--half-distance-km 2.0` | Hansen exponential-decay half distance; cutoff is five times this distance |
| `--seed 42`, `--jobs auto`, `--max-memory-gb auto` | Reproducible sampling and resource limits |

Existing nonempty output requires `--overwrite`. Overwrite removes recognised generated files and preserves unknown user files. Input and CSV validation occurs before results are replaced.

## Failure probabilities

Generate a template using the same network and cleaning settings as the analysis:

```sh
georesilience failures-template input/hyderabad --out link_failures.csv
# Fill p_fail values, then run:
georesilience run input/hyderabad --out results/hyderabad --failure-probs link_failures.csv
```

The template columns are:

```text
link_uid,osm_way_ids,u,v,length_m,name,highway,p_fail
```

`link_uid` identifies one cleaned physical link. Descriptive columns help with editing; probabilities are keyed by `link_uid`. Keep the generated fingerprint metadata with the template. The fingerprint binds it to the input and cleaning settings; regenerate the template after changing either. Multiple physical links may share an OSM way ID.

A probability is finite and between 0 and 1, for **one event or scenario**. Blanks mean missing. Duplicate or unknown IDs and fingerprint mismatches are errors. Without strict completeness, missing values use the length proxy:

```text
p_fail = 1 - (1 - p0) ** (length_m / 1000)
```

The report shows user/proxy coverage by link count and length. `--require-complete-failures` rejects missing values. Scenarios assume independent physical-link failures; these probabilities are not annual rates. For example, `--p0-sweep mild=0.001 --p0-sweep severe=0.05` repeats the same reliability measures under named scenarios, using common per-link failure uniforms. User-supplied link probabilities remain fixed while the proxy changes.

## Measures

All weighted results use `_pop`. A weighted result and its structural counterpart use the same retained network, removals and sampled failure scenarios. Population pair weights `P_i * P_j` represent resident-to-resident demand, not observed trips. Undefined results are `null` with a reason, including all population-weighted measures when total population is zero.

| Scope | Reported measures |
| --- | --- |
| Node | Length-weighted betweenness, information centrality, Hansen accessibility and articulation flag; information and Hansen have population variants |
| Physical link | Length-weighted edge betweenness, bridge flag, detour ratio and no-alternative flag |
| Link removal | Efficiency drop, network Hansen accessibility drop and disconnected-pair fraction, each with a population variant |
| Node removal | Information centrality is the efficiency drop; accessibility drop and disconnected-pair fraction also have population variants |
| Network | Bridge redundancy; median finite detour ratio and no-alternative share; targeted link-attack AUC; normalised Hansen accessibility; mutual-pair connectivity reliability; travel-time reliability |

Node and edge betweenness use a length-weighted undirected graph. Routing consequences use the directed retained road graph. Removing a physical link removes all its associated arcs. Removing a node isolates it while preserving the original ordered pair universe and denominators: pairs involving that node count as lost.

Structural Hansen at node `i` is `sum(exp(-beta*d_ij)) / (N-1)`, where `j != i`, `beta = ln(2)/half_distance`, and unreachable destinations or distances beyond the cutoff contribute zero. Its population form weights each destination by `P_j / sum(P_k, k != i)`. Network Hansen averages origins equally or by `P_i`, respectively. Both are in `[0,1]` when defined. Removal drops retain the original populations and normalisations.

Bridge redundancy is `1 - bridge_count / non_self_loop_link_count`. Links without an alternative have `detour_none=true` and a null ratio; the network reports their share alongside the median finite ratio.

Targeted attack follows one edge-betweenness removal order. The curves show node and population shares in the same largest strongly connected component; AUC is the raw trapezoidal area of the exported curve, to `floor(attack_fraction * link_count)` removals. Adaptive order is recomputed after each link; `attack_steps` limits reported points. If that horizon removes no links, AUC is unavailable with a reason. Screened removal scores include an evaluated flag and candidate counts; unevaluated scores are null.

Connectivity reliability is the expected share of distinct ordered pairs that remain mutually reachable. Travel-time reliability is the expected share satisfying `damaged_time <= (1 + threshold) * baseline_time`. Both report structural and population weighting with conservative 95% Hoeffding confidence bounds over independent scenario fractions. All original origins are evaluated; worker count does not change seeded results. Free-flow time requires resolvable OSM speeds or explicit `--speed` values; edge-attribute mode requires supplied time data. Missing resolvable speed information gives null travel-time reliability with a reason. Explicit edge-attribute costs must exist and be finite, positive seconds. Travel times model supplied conditions rather than congestion or observed journey times.

An optional OD CSV uses WGS84 columns `label,origin_lon,origin_lat,dest_lon,dest_lat`. It adds a pair-level table and does not change the network-wide denominator.

## Results and reproducibility

```text
results/hyderabad/
  network.gpkg          # nodes and physical links
  summary.json          # unweighted and population_weighted network results
  attack_curve.csv      # shared attack order, both component-share curves
  report.txt            # definitions, results, coverage and assumptions
  run_manifest.json     # consumed-input hashes and resolved settings
  od_reliability.csv    # only with --od-pairs
  figures/              # unless --no-figures
```

The manifest records input hashes, resolved defaults and units, software versions, random seed, cleaning options, population boundary method/bounds, candidate coverage, probabilities and speed assumptions. Reproduce a run with the same consumed files and recorded settings/software; Monte Carlo samples are seeded independently of worker count. Compare hashes before reusing a probability template or comparing runs. The Python API `georesilience.pipeline.replay_manifest(manifest_path, new_output)` verifies consumed-file hashes and reruns recorded settings. Custom Python time providers must be supplied again. The memory flag budgets shortest-path and simulation workspace; graph/geometry and output storage are additional.

For the offline test suite:

```sh
python -m pytest -q
```

Install test dependencies with `python -m pip install -e ".[test]"`. The suite is entirely offline. A checked-in synthetic example is available at [tests/fixtures](tests/fixtures/README.md). See [DESIGN.md](DESIGN.md) for calculation contracts.
