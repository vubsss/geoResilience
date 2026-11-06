# GeoResilience design

GeoResilience is a local road-resilience CLI. Its inputs are one supported road network and one population-count GeoTIFF; a run produces structural and population-weighted measures from the same network and scenarios. This document defines the public calculation and data contracts.

## Inputs and preparation

`georesilience run INPUT_DIR --out OUTPUT_DIR` discovers exactly one `.osm`, `.osm.xml` or `.graphml` and exactly one `.tif` or `.tiff`. Ambiguous/missing inputs fail with candidate paths. OSM PBF is unsupported. XML filtering defaults to `drive`; GraphML is used as supplied and the manifest must distinguish a requested setting from an applied filter.

Cleaning simplifies road geometry, projects to metre coordinates, optionally consolidates intersections (15 m default), and retains the largest directed strongly connected component (ties use canonical node IDs). Record before/after counts and length. Use the retained graph for every metric and for population allocation.

An explicit boundary overrides a uniquely named `boundary.geojson` or `boundary.gpkg`. Without one, derive the crop from the retained graph extent expanded by the maximum snap distance (500 m default). Reject ambiguous boundaries, invalid raster CRS/band/count data and no overlap. Select valid count cells in the crop; assign each to its nearest retained node within the snap distance and retain unallocated-population accounting for the crop. Record boundary method, bounds, raster hash, count units and allocation coverage.

Validate files/options/probabilities before expensive computation or replacing results. Keep intermediate work in memory or a temporary directory. Results must lie outside the input directory. Existing nonempty output requires `--overwrite`, which replaces only recognised generated files and preserves unknown user files.

## Physical-link identity and failure data

A physical link groups its directed arcs; closing the link removes all those arcs. Reciprocal arcs with matching endpoints/way IDs/rounded lengths are paired one-to-one, preferring matching geometry and arc keys; a missing reverse geometry is compatible with its forward arc. Parallel roads remain distinct physical links. Generate deterministic `link_uid` values after cleaning from canonical link attributes, geometry and endpoints, with collision checks. IDs must be stable for identical input and cleaning settings; they need not survive changed cleaning.

The versioned fingerprint hashes road bytes, resolved network/cleaning options and OSMnx version. Each UID hashes this fingerprint plus canonical directed endpoints, arc keys, way IDs, lengths and geometry; collisions fail. Bind each generated template to this input/cleaning fingerprint in its `# georesilience_fingerprint=` CSV comment. `failures-template` applies the same network/cleaning options as `run` and writes `link_uid,osm_way_ids,u,v,length_m,name,highway,p_fail`. The strict parser uses `link_uid,p_fail`. Duplicate/unknown IDs, non-finite/out-of-range probabilities and fingerprint mismatch fail. Do not silently apply a template to another cleaned network. An OSM way ID may span several physical links.

Probability means independent physical-link closure during one event/scenario, not an annual rate. Blanks/uncovered links use `1 - (1-p0)^(length_m/1000)` unless complete user coverage is required. Default `p0=0.01`. Report user/proxy coverage by count and length. A p0 sweep is opt-in and repeats the same reliability measures under named probability scenarios.

## Shared pair universe

Let the retained graph have original node set `V`, size `N`, node populations `P_i`, and distinct ordered pairs `U={(i,j):i,j in V, i!=j}`. Structural pair weight is `1`; population weight is `P_i*P_j`. Let `W=sum_U w_ij`. Population weights are a resident-to-resident demand proxy, not measured trips.

Use the original `V`, populations, weights and denominators for every baseline and damaged graph. Removing a node isolates it and sets its paths to/from other nodes unreachable; do not shrink `U`. Unreachable paths contribute zero to efficiency, accessibility and reliability. A zero denominator is undefined with a reason, represented as JSON null, never zero. An all-zero population raster therefore has undefined population results while retaining structural results.

Length-weighted node/edge betweenness use the undirected analysis graph. Information centrality and removal/reliability calculations use the directed retained road graph; report directedness accurately. There is no population-weighted betweenness.

## Efficiency and accessibility

For positive finite shortest-path length `d_ij`, let `q_ij=1/d_ij`; otherwise `q_ij=0`. Network efficiency is `E=sum_U(w_ij*q_ij)/W`. Single-removal efficiency drop is `(E_baseline-E_damaged)/E_baseline`, undefined when baseline is zero. Node information centrality is exactly this drop after isolating that node, with structural and population variants; publish no duplicate node-efficiency column.

For half distance `h` (2 km default), `beta=ln(2)/h` and cutoff `R=5h`. Define `f(d)=exp(-beta*d)` for reachable `d<=R`, otherwise zero. Node Hansen is:

```text
A_i     = sum_(j != i) f(d_ij) / (N-1)
A_i_pop = sum_(j != i) P_j*f(d_ij) / sum_(j != i) P_j
```

Network structural Hansen is the equal-origin mean of `A_i`. Population Hansen is the population-origin mean of `A_i_pop`. Both are normalised to `[0,1]` when defined; exclude no original destination weight after removal. Accessibility drop compares the appropriate baseline and damaged network Hansen indices with the baseline origin weights and destination denominators fixed. A removed origin contributes zero.

Single-link and single-node consequences contain efficiency/information drop, network accessibility drop and disconnected-pair fraction, each in structural and population form. Pair disconnection uses the fixed original ordered pair universe; pairs involving a removed node are lost. A screened computation publishes the candidate method/counts and `evaluated=false` plus null scores for unevaluated features. `--criticality-coverage all` explicitly requests complete evaluation.

## Structural link measures and attack

Local link results are edge betweenness, bridge flag and detour ratio. A link with no alternative has `detour_none=true` and a null ratio. Network bridge redundancy is `1 - bridge_count/non_self_loop_link_count`. Detour redundancy reports both median finite detour ratio and the share of links with no alternative.

Targeted attack closes physical links in one length-weighted edge-betweenness order. Adaptive ordering is default; static ordering is explicit. Evaluate node share and population share in the **same** largest strongly connected component after each step. Integrate both curves against fraction of physical links removed for their AUCs. Default maximum fraction is 0.20 over at most 50 reported post-removal points. Adaptive ranking is recalculated after every physical-link closure, including closures between reported points. Use `floor(fraction * link_count)` as the integer horizon; AUC is the raw trapezoidal area of the exported curve, with no extrapolation. A zero-removal horizon has undefined AUC with a reason. Zero population makes the population curve/AUC undefined. Report the removal order, step counts and integration range.

## Reliability

Each sample independently closes physical links according to their event probabilities. Connectivity reliability is the expected fraction of `U` whose nodes remain in the same strongly connected component. Travel-time reliability is the expected fraction satisfying `t_damaged(i,j) <= (1+tau)*t_baseline(i,j)`; unreachable damaged pairs fail. Use the same pair definitions and failure samples for structural and population views. Default sample counts are 10,000 connectivity and 1,000 travel-time events; default `tau=0.5`.

Report conservative 95% Hoeffding bounds (`sqrt(log(40)/(2*samples))` half-width, clipped to `[0,1]`) over independent bounded scenario fractions, event counts, seed and failure model. Sample index `i` uses `SeedSequence([seed,i])`; both weighting views and named p0 scenarios share those per-link uniforms. Seed event sampling independently of worker partitioning so worker count does not change results. Missing/undefined denominators carry explicit null reasons. Optional WGS84 OD input (`label,origin_lon,origin_lat,dest_lon,dest_lat`) adds pair-level results without replacing the network pair universe.

Free-flow times use supplied OSM speed information or explicit highway speed overrides. Do not invent missing speeds. `edge-attribute` uses the requested time attribute. If usable times cannot be resolved, return unavailable travel-time reliability and explain why. Report the time model, units and speed provenance. Congestion, correlated hazards and observed trip demand are outside these models.

## Output and reproducibility

Write exactly `network.gpkg`, `summary.json`, `attack_curve.csv`, `report.txt` and `run_manifest.json`; optionally `od_reliability.csv` and retained-metric figures. Nodes/links may include IDs, name/class, geometry, failure probability/source, population and evaluation flags as provenance. Weighted score columns end in `_pop`. Summary network results use `unweighted` and `population_weighted` groups with nearby definitions/null reasons.

The manifest records checksums of every consumed file, resolved CLI values/defaults, units, software versions, seed, cleaning, graph directedness, boundary method/bounds, probability/speed assumptions and candidate counts. Reproduction requires identical consumed inputs and recorded options/software. Verify hashes and template fingerprints rather than inferring compatibility from filenames.

Public metrics without service input are limited to the retained measures above. Supporting IDs, population counts, probabilities, coverage and provenance are data fields.

## Optional critical-service contract

An explicit `--facilities PATH` enables a third service view. No facility file is
discovered implicitly. `--service-mode weights-only` is the default; `2sfca`
requires explicit positive `--service-catchment-minutes TYPE=MINUTES` for each
category present in the CSV, independently of its importance. Internal time units
are seconds. Importance defaults to one for each type, is finite/nonnegative,
and at least one type must have positive importance. The separate inclusive
`--facility-snap-max-m` defaults to 500 metres. Per-type expected units may be
declared with `--service-unit TYPE=UNIT`. These settings round-trip in RunConfig.

CSV location columns are `facility_id,service_type,longitude,latitude`. IDs are
unique nonblank strings (leading zeros preserved), types are `school`/`hospital`,
and coordinates are finite WGS84 lon/lat. Optional descriptive columns are
`name,capacity_year,notes`. In 2SFCA mode every row must also provide finite
nonnegative `capacity`, nonblank `capacity_unit` and `capacity_source`, including
known zero supply. Suggested units are `student_seats` and `staffed_beds`; users
may explicitly supply other units, consistent within each category. Mixed units
within a type, duplicate/blank headers and IDs, malformed rows and invalid
numbers fail with row diagnostics. Weights-only allows unknown capacity as null;
it never substitutes zero or invents capacity. Known numeric capacity is always
validated and incompatible declared units always fail.

Count importance is `w_i=sum_c alpha_c*n_i,c`, independent of capacity. Known
zero-capacity institutions still count toward importance. Service destination
metrics use fixed original `P_i*w_j`, including co-location; zero original mass
is unavailable. Seats and beds are never added. Demand for both categories is
allocated total population; school demand is an all-resident proxy. Retained
network/crop boundaries do not correct missing neighbouring demand or supply.
Attachment occurs after cleaning with stable node-ID ties, retaining every
facility and its provenance; out-of-range points fail rather than disappear.

Standard 2SFCA uses directed resident-to-facility static-time catchments,
inclusive thresholds and no decay: `D_j=sum_i P_i*1[t_ij<=T_c]`, `R_j=S_j/D_j`,
`A_i,c=sum_j R_j*1[t_ij<=T_c]`. Facilities with zero demand have null ratios and
contribute zero, with their supply reported separately. Absent types, zero total
population and missing time costs are unavailable with reasons. Supplied known
zero supply yields zero access for positive population. Raw indices are capacity
per resident (also displayed per 1,000); they are neither clipped nor combined
across units. Custom dynamic time providers are unsupported for enabled 2SFCA.
The method extends Luo and Wang (2003), equations (3)/(4), to supplied school and
hospital capacity; full scenario 2SFCA and age-specific demand are deferred.

## Verification

Use tiny deterministic XML/GraphML/raster fixtures and exact formula checks for directed closures, bridges, parallel roads, screened omissions, removed-node pairs, zero-population nodes and all-zero population. Test template round trips and mismatches, time availability, seeded worker independence, output schema, safe overwrite and an offline end-to-end run. The complete test suite forbids network access. Small deterministic checked-in inputs live under `tests/fixtures/tiny`; variant fixtures are generated under test temporary directories.
