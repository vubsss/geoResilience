# GeoResilience

GeoResilience analyses a local road network and a WorldPop population-count raster, with optional schools/hospitals and capacity-aware accessibility. A run reports structural and population-weighted resilience measures together, with their definitions, evaluated coverage and input assumptions.

## Install and run

From this repository, with Python 3.10 or newer:

```sh
python -m pip install -e .
georesilience run input/hyderabad --out results/hyderabad
```

Prepare a directory containing exactly one road file and one population raster (the raster may be omitted in a service-enabled run):

```text
input/hyderabad/
  roads.osm          # .osm, .osm.xml or .graphml
  population.tif     # .tif or .tiff; georeferenced, one band, people per cell
  boundary.geojson   # optional; boundary.gpkg is also recognised
```

Basenames of the road and raster are arbitrary. Missing or multiple matches are errors, except that `--facilities` permits a missing raster and explicitly uses uniform node demand. OSM PBF and arbitrary road-line vector files are unsupported. XML supports `drive` filtering (default) or `all` to retain supplied road classes. GraphML road classes/access tags are used as supplied, and the manifest records that no network filter was applied. Both inputs are simplified, projected to metres, optionally consolidated, and reduced to the largest strongly connected component; cleaning losses are recorded.

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

The original population-weighted local results use `_pop`; service and combined-importance results have explicit names described below. A weighted result and its structural counterpart use the same retained network, removals and sampled failure scenarios. Population pair weights `P_i * P_j` represent resident-to-resident demand, not observed trips. Undefined results are `null` with a reason, including all population-weighted measures when total population is zero.

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

## Schools, hospitals and population-inclusive node importance

Retained road nodes come from the cleaned road graph. An explicit facility CSV
attaches each school/hospital to its nearest retained node after cleaning and
consolidation. Multiple facilities at a node remain separate. Points outside the
inclusive snap limit fail; there is no silent exclusion or re-snapping after
closure. Equal-distance ties use stable node IDs. Facility discovery and capacity
acquisition are outside the program.

| Service option | Default / meaning |
| --- | --- |
| `--facilities PATH` | Explicit local WGS84 CSV; enables service outputs |
| `--service-mode weights-only` | Counts/importance and service scenario views; capacity may be unknown |
| `--service-mode 2sfca` | Requires capacity, source, unit and explicit catchment for every supplied type |
| `--service-importance TYPE=WEIGHT` | Repeatable `school`/`hospital` coefficient; defaults 1 each; finite/nonnegative, at least one positive |
| `--population-importance 1` | Population-share coefficient in combined node importance; finite/nonnegative; 0 removes this component |
| `--service-catchment-minutes TYPE=MINUTES` | Repeatable positive finite inclusive travel-time threshold; no universal default |
| `--service-unit TYPE=UNIT` | Optional expected capacity unit per category; CSV rows must match |
| `--facility-snap-max-m 500` | Separate inclusive facility snap limit, metres; zero requires exact co-location |

Service-specific options require `--facilities`. Count importance is independent
of supplied capacity:

```text
service_weight_i = alpha_school * school_count_i + alpha_hospital * hospital_count_i
node_importance_i = population_importance * P_i / sum(P)
                    + service_weight_i / sum(service_weight)
```

Each zero-total component contributes zero. Normalization makes population and
service components comparable before addition. At the default coefficient, each
nonzero component has total mass 1; this is a transparent project choice, not an
empirical valuation. A populated node gains importance even without a facility;
a hospital at a zero-population node retains its service contribution. Exported
components let you inspect both contributions separately. School/hospital
coefficients control their relative institutional importance, not seats or beds.
Known zero-capacity institutions retain service points.

Population also weights resident-origin demand in service access, closure losses
and reliability: service pairs use original `P_i * service_weight_j`, including
co-located origin and destination. With a raster, `P_i` is allocated population.
Without a raster in a service-enabled run, `P_i=1` at every retained node, making
the population component uniform and supplying equal demand per node. Outputs
label this as **uniform node demand**, not resident counts. A supplied all-zero
raster remains zero population and produces unavailable population/2SFCA values;
it never triggers this fallback. Multiple rasters remain an error. No-service
runs still require one raster and retain their original output schemas.

### Facility data

Required location columns are `facility_id,service_type,longitude,latitude`.
Capacity-aware mode additionally requires `capacity,capacity_unit,capacity_source`
on every row, including known zero capacity. Optional descriptive columns are
`name,capacity_year,notes`.

```csv
facility_id,service_type,longitude,latitude,capacity,capacity_unit,capacity_source
001,school,78.4700,17.4000,120,student_seats,declared synthetic example
002,hospital,78.4710,17.4010,12,staffed_beds,declared synthetic example
```

IDs are unique nonblank strings; leading zeros are retained. Types are `school`
or `hospital`. Coordinates must be finite WGS84 longitude/latitude. Capacity is
finite/nonnegative. Blank capacity means unknown, allowed only in weights-only
mode; it is never guessed or converted to zero. Duplicate/blank headers or IDs,
malformed rows, invalid numeric values and incompatible units within a category
fail with diagnostics. Different types have independent units. Suggested units
are student seats and staffed beds; another consistent basis such as physician
FTE is allowed if explicitly declared. Beds are a proxy, not direct primary-care
capacity. Never add beds to seats or infer supply from facility existence.

### Standard 2SFCA and closure losses

For facility `j` in category `c`, with supplied capacity `S_j`, original demand
`P_i`, directed shortest resident-to-facility seconds `t_ij`, and cutoff `T_c`:

```text
D_j = sum_i P_i * 1[t_ij <= T_c]
R_j = S_j / D_j
A_i,c = sum_(j in category c) R_j * 1[t_ij <= T_c]
```

These are standard binary 2SFCA equations (3)/(4) in Luo and Wang (2003),
*Measures of spatial accessibility to health care in a GIS environment*,
DOI `10.1068/b29120`, printed page 872 (PDF page 8 in the local reference).
Using school seats or hospital beds is this project's extension of the paper's
physician supply. No decay is applied inside a catchment. Both passes use the
resident-to-facility direction, inclusive time thresholds and zero-time
co-location. Length and fastest-time parallel roads can differ. Static free-flow,
edge-attribute and static custom Python providers are supported; dynamic custom
providers fail explicitly for requested 2SFCA. Missing speeds yield unavailable
2SFCA, without a distance fallback. Count/length service views remain usable.

School and hospital indices stay separate, in capacity units per resident (or
per uniform node demand unit without population), also displayed per 1,000.
Raw scores may exceed one. Equal-node and population/demand-weighted means use
the same underlying demand index; the equal-node mean does not remove population
from facility competition. An absent type, missing times or zero population is
unavailable with a reason. Known all-zero capacity yields zero access for
positive demand. Zero-catchment-demand facilities have null ratios, contribute
zero access, and have their capacity reported separately.

Each evaluated closure recomputes both catchments and supply/demand ratios.
A node closure isolates the road node, disables its facilities and sets its
origin access to zero. A physical-link closure removes its arcs but preserves
co-located services. Original demand totals, supply locations and denominators
stay fixed. Some residents can gain access when competitors lose routes; thus
population mean access alone can miss serious redistribution:

```text
sum_i P_i * A_i,c = total remaining capacity with positive catchment demand
access_shortfall_c = sum_i P_i * max(A_baseline_i,c - A_damaged_i,c, 0)
                     / sum_i P_i * A_baseline_i,c
```

Access shortfall is the primary project-defined criticality measure, in `[0,1]`
when its baseline is positive; it counts losses without cancelling gains.
Newly unserved population/demand share uses the original demand denominator.
Signed mean changes are damaged minus baseline in the original category units.
The optional combined shortfall averages the dimensionless category losses using
normalized service importance. If any positively weighted type has an absent or
zero baseline, the combined score is unavailable; set an intentionally disabled
type's importance to zero rather than silently omitting it.

Screened candidates preserve existing structural candidates and add every
positive-service-weight node and its incident non-loop physical links. The same
expanded sets are evaluated for existing local metrics. Screened coverage can
miss the global most critical closure; `--criticality-coverage all` evaluates all
retained nodes and non-loop links. Unevaluated values remain null with reasons.
Population-plus-service importance is exported and adds its own attack curve;
it does not silently redefine the original betweenness-based attack order.

Service reliability reports directed resident-to-service reachable share and
travel-time reliability with fixed original `P_i*w_j` mass. Attack outputs add
service-points share and combined-node-importance share in the same node-selected
SCC and their raw AUCs. All views share existing failures, seeds, p0 sweeps and
removal order. These scenario views do not recompute 2SFCA for each event or step;
facilities do not fail independently of roads in these simulations.

### Reproducible synthetic examples

Weights-only, with unknown capacities permitted:

```sh
georesilience run tests/fixtures/tiny --out /tmp/georesilience-service-weights \
  --facilities tests/fixtures/tiny/facilities_weights_only.csv \
  --service-mode weights-only --population-importance 1 \
  --no-consolidation --jobs 2 --connectivity-samples 64 --travel-time-samples 64 --no-figures
```

Capacity-aware, using illustrative ten-minute catchments, not calibrated defaults:

```sh
georesilience run tests/fixtures/tiny --out /tmp/georesilience-service-sfca \
  --facilities tests/fixtures/tiny/facilities.csv --service-mode 2sfca \
  --service-catchment-minutes school=10 --service-catchment-minutes hospital=10 \
  --service-unit school=student_seats --service-unit hospital=staffed_beds \
  --service-importance school=1 --service-importance hospital=2 --population-importance 1 \
  --no-consolidation --jobs 2 --connectivity-samples 64 --travel-time-samples 64 --no-figures
```

Use a separate input directory containing only a copy of `roads.graphml` to try
the same command without a raster. It will record uniform node demand. Existing
outputs require `--overwrite`. All fixture capacities are synthetic, not study
measurements.

### Service outputs and study handoff

The text output is **`report.txt`**. Enabled summary/manifest schemas are version 2;
no-service schemas remain version 1. `summary.json.services` (subschema version 1)
contains `input` coverage/provenance, `weights`, `node_importance`, `demand`,
`service_weighted` baseline/attack/reliability measures,
`node_importance_weighted` attack AUC, separate `sfca.school`/`sfca.hospital`
summaries and `criticality` coverage/closure rankings. Each 2SFCA summary states
units, catchment, demand basis, means, zero-access share, positive-demand supply,
zero-demand supply and disabled supply, or an explicit unavailable reason.

`network.gpkg` gains a WGS84 `facilities` layer with original coordinates,
identity/provenance, retained `node_id`/`node_index`, projected coordinates,
`snap_m`, `available_capacity`, `catchment_demand`, `supply_demand_ratio` and
`ratio_reason`. Node fields include `school_count`, `hospital_count`, separate
`*_capacity` and `*_unknown_capacity_count`, `service_weight`, `node_importance`,
`importance_population_component`, `importance_service_component`, and
`school_sfca`/`hospital_sfca` with `*_sfca_per_1000` display values.

Both node and link layers contain per-type `*_access_shortfall`,
`*_newly_unserved_population_share`, damaged `*_population_mean`/`*_equal_node_mean`,
signed `*_population_mean_change`/`*_equal_node_mean_change`,
`service_combined_shortfall`, `service_evaluated` and serialized
`service_null_reasons`. The original `population` node field contains uniform
demand units in a fallback run; inspect the recorded demand basis before reading
it as residents. `attack_curve.csv` adds `service_share` and
`node_importance_share` only in enabled runs. Optional service figures are
`service_weight.png`, `node_importance.png`, `school_sfca.png`, `hospital_sfca.png`,
`school_criticality.png` and `hospital_criticality.png`; grey values are
unavailable/unevaluated. `--no-figures` suppresses them.

The manifest adds facility checksums, resolved units/catchments/coefficients,
capacity sources/years, attachment mappings and ratios, demand basis, coverage,
method version and static-time assumptions. Replay verifies consumed facility
bytes; changed inputs fail before replacing outputs. Overwriting an enabled run
with a disabled one removes stale generated service figures/layers and preserves
unrelated user files. Workspace is bounded by chunked reductions rather than a
retained all-resident-by-facility matrix; graph, geometry and output storage are
additional to the routing workspace budget.

Before a real study, supply actual facility locations, capacity units, capacity
sources/years and known-zero versus unknown values; justify service/population
importance and category catchments; validate speed/time inputs, retained-network
and demand allocation coverage; and inspect candidate scope. School demand uses
total population, not eligible school-age enrolment. Missing neighbouring demand
and supply at study boundaries are not corrected. Age-specific demand, capacity
acquisition, external POI discovery, enhanced/decayed 2SFCA and full repeated
2SFCA inside Monte Carlo/attack steps remain deferred.

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
