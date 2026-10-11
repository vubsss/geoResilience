# GeoResilience

GeoResilience analyzes road network structure and resilience. Tickets 01–10 provide input,
cleaning, physical road links, exact centralities, redundancy screening, single-road damage,
information centrality, cumulative attack/failure experiments, distribution classification,
per-event road failure probabilities, Monte Carlo connectivity and travel-time reliability,
and auditable outputs. Ticket 15 adds a four-city qualitative comparison with AP2, including
an explicit reference using the paper's spatial efficiency. Later analysis tickets are
tracked in [TICKET_UPDATES.md](TICKET_UPDATES.md).

Install with Python 3.10 or newer:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e . pytest
```

## Supported inputs

- **Supported:** place name, boundary polygon (GeoJSON/GPKG), WGS84 bbox, `.osm` XML, `.graphml`.
- **Planned:** `.osm.pbf`.
- **Not supported:** road-line Shapefile/GeoJSON/GPKG, because splitting lines at intersections
  merges flyovers/underpasses into false junctions. Boundary polygons in GeoJSON/GPKG are supported;
  these define the download area rather than supplying road geometry.

Choose one `input` block:

```yaml
input:
  source: place
  place: "Piedmont, California, USA"
```

```yaml
input:
  source: polygon
  path: data/ticket02-demo/boundary.geojson
```

```yaml
input:
  source: bbox
  bbox: [78.469, 17.399, 78.479, 17.409] # west, south, east, north (longitude/latitude)
```

```yaml
input:
  source: osm_xml
  path: data/ticket02-demo/roads.osm
```

```yaml
input:
  source: graphml
  path: data/ticket02-demo/junction.graphml
```

Place, polygon and bbox require an internet connection to OSM services. A place name must
resolve to a polygon boundary; a point-only neighbourhood name needs a bbox or polygon instead.
You can use a mapped administrative area such as "Hyderabad, India" for a larger study. Polygon features are
unioned and reprojected to WGS84; they must declare a CRS. The study boundary is saved as WGS84
WKT in `summary.json.meta.study_boundary_wkt`. It is null for XML and GraphML. Relative paths
are resolved from the working directory where you run the command.

Add these optional sections (shown with defaults) to the selected input block:

```yaml
network:
  type: drive
  custom_filter: null
cleaning:
  consolidate: true
  tolerance_m: 15
analysis:
  seed: 42
  n_jobs: auto
  max_memory_gb: auto
  directed_centrality: false
  directed_removal: true
criticality:
  k_betweenness: 250
  k_detour: 250
  k_nodes: 300
  exact_info_max_nodes: 5000
  bridge_analytic_max_side: 2000
  all: false
robustness:
  removal: [links, nodes]
  steps: 50
  f_max: 0.20
  adaptive: true
  node_attack_metric: betweenness
  failure_runs: 10
  efficiency_sources: 500
reliability:
  p_fail_csv: null
  p0: 0.01
  p0_sweep: [0.001, 0.01, 0.05]
  samples: 10000
  od_pairs_csv: null
  min_down_count: 30
  min_up_count: 30
travel_time:
  enabled: true
  samples: 1000
  n_origins: 200
  tau: 0.5
  highway_speeds_kph: null
  time_model: free_flow
  time_attribute: travel_time_s
output:
  dir: results/
  figures: true
```

Download sources accept OSMnx types `drive`, `drive_service`, `walk`, `bike`, `all`, and
`all_public`. An Overpass `network.custom_filter` overrides the type's road filter for downloads.
GraphML keeps its supplied roads and directionality: `network_type_applied` is `as-provided`.
XML types other than `drive` also keep supplied roads, record `as-provided`, and log a warning.
Custom Overpass filters cannot be applied locally to XML or GraphML and produce a warning.

For **XML with `network.type: drive`**, exclude roads with:

- `highway` in `abandoned`, `bridleway`, `bus_guideway`, `construction`, `corridor`, `cycleway`,
  `elevator`, `escalator`, `footway`, `no`, `path`, `pedestrian`, `planned`, `platform`, `proposed`,
  `raceway`, `razed`, `service`, `steps`, or `track`;
- `area=yes` or `access=private`;
- `motor_vehicle=no` or `motorcar=no`.

Isolated nodes are removed after this filter. Restrictions are applied before simplification so
forbidden roads cannot be combined with legal ones. Missing access tags do not imply a restriction.
The pipeline retains additional access, vehicle, service, lane, surface and speed tags internally
for later tickets. These filter rules follow the ticket's OSMnx `drive` definition; see the
[OSMnx source](https://github.com/gboeing/osmnx/blob/main/osmnx/_overpass.py).

## Cleaning and outputs

1. **Simplify** removes intermediate shape nodes and preserves summed road lengths and geometry.
   An already simplified GraphML is used as supplied.

   ```text
   before: A --- o --- o --- B   (o = intermediate road shape node)
   after:  A ------------- B   (one link, same route geometry and length)
   ```

2. **Project** to a local metric UTM CRS before consolidating intersections.
3. **Consolidate** merges nearby, connected junction nodes using the tolerance in metres.
   OSMnx buffers each node by this radius, so overlapping buffers can merge nodes up to twice the
   tolerance apart; connected clusters can span farther. Set `consolidate: false` to disable it.

   ```text
   before:       N                    after:       N
                 |                                |
            W -- a -- b                      W -- J -- E
                 |    |                           |
                 d -- c -- E                      S
                      |
                      S
            (a,b,c,d = one divided-road intersection)
   ```

   Dead ends are included in reconstruction. The run raises an error if the number of nodes with
   exactly one distinct neighbour changes by 5% or more during consolidation. Short cul-de-sacs
   inside a junction cluster can trigger this guard; reduce `tolerance_m` or disable consolidation
   and inspect the network. The guard runs before component removal.
4. **Largest strongly connected component** retains the largest node set where directed travel
   is possible between every pair. The degree graph uses this same node set. One-way slivers and
   disconnected roads can be removed; their component count, nodes and physical road length are
   reported. More than 5% length loss adds `check boundary clipping / one-way slivers`.

   ```text
   before: A <--> B <--> C       X <--> Y       C ---> Z
   after:  A <--> B <--> C       (smaller component and one-way tail removed)
   ```

Clipped boundaries create artificial dead-ends; buffered download is planned. This warning always
appears in the report.

Run `georesilience run --config my.yaml`. Use `--out another-results` to override `output.dir`.
Non-empty output folders require `--overwrite`. The command writes:

| File | Contents |
| --- | --- |
| `network.gpkg` | Projected `nodes` and physical-link `edges` layers; degree, centrality and redundancy metrics |
| `summary.json` | Input, CRS, cleaning counts, metrics and root-level `classification` evidence |
| `report.txt` | ASCII network summary, cleaning, degree, centralities, redundancy and top-road tables |
| `run_config.yaml` | Resolved defaults and package versions; reusable as a run config |
| `robustness_curves.csv` | Per-step cumulative attack and random-failure measurements |
| `figures/degree_hist.png` | Degree histogram, unless `output.figures: false` |

`summary.json.cleaning` records `raw`, `simplified`, `consolidated`, and `final` counts
(`node_count`, `link_count`, `total_length_km`); XML also records `filtered`. Length counts each
physical link once rather than double-counting reciprocal directions. Loaders request unsimplified
graphs so the raw stage can actually be measured, then simplify explicitly; XML filtering also
happens between these stages. For already simplified GraphML, `raw` means the supplied graph.
Component loss percentages use the consolidated graph's length as the denominator. Consolidation
can shorten junction interiors and extend approach geometry, separately from component losses.

## Run and test ticket 02

From the repository root with the environment activated:

```sh
python examples/create_ticket02_demo.py
georesilience run --config examples/ticket02-graphml.yaml --overwrite
georesilience run --config examples/ticket02-xml.yaml --overwrite
cat results/ticket02-graphml/report.txt
cat results/ticket02-xml/report.txt
python -m pytest
```

Expected GraphML results: raw **8 nodes, 8 links**; consolidated/final **5 nodes, 4 links**;
four dead ends before and after; one junction of degree 4. Open `network.gpkg` in QGIS to inspect
both layers. Set `cleaning.consolidate: false` in a copy of the config and run it with
`--out results/ticket02-unconsolidated`; expect **8 nodes, 8 links**.

Expected XML results: raw **4 links**; filtered/final **1 residential link**, OSM way ID **103**,
with **2 nodes**. Footway, service and private residential roads are removed.

For a real small Hyderabad download and opt-in network tests:

```sh
georesilience run --config examples/ticket02-bbox.yaml
python -m pytest --network -m network
```

The network tests cover place (Piedmont, about 4 km²), polygon and bbox (about 1 km² in Hyderabad). They are skipped by default; ordinary in-process
tests reject HTTP requests. Real downloads depend on Nominatim/Overpass availability. If the real
area triggers the dead-end guard, inspect it and reduce the tolerance or disable consolidation.
Use `--overwrite` to rerun an example into its existing output folder.

If your shell loads ROS or other unrelated pytest plugins, isolate the test command:

```sh
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest
```

## Exact centralities (ticket 03)

Every run now computes centralities on the cleaned **undirected** graph, using lengths in metres.
Both travel directions count as one connection. For parallel links between the same two nodes,
analysis uses the shortest link; an equal-length tie goes to the lowest `link_id`. Longer links
and unselected ties have edge betweenness 0. Self-loop links remain in the GPKG with null edge
betweenness and do not enter any centrality calculation.

| Measure | Meaning | Units |
| --- | --- | --- |
| `closeness` | `(N - 1) / sum(shortest-path distances to other nodes)` | 1/metres |
| `straightness` | Mean of straight-line distance / shortest-path distance to other nodes | Dimensionless |
| `betweenness` | Fraction of other ordered node pairs' shortest paths passing through a node | Dimensionless |
| `edge_betweenness` | Fraction of unordered node pairs' shortest paths using the selected link | Dimensionless |
| `global_efficiency` | Mean of `1 / shortest-path distance` over ordered distinct node pairs | 1/metres |

Tied shortest paths split betweenness equally. Node betweenness excludes the two endpoints;
edge betweenness includes them. Unreachable pairs contribute zero to efficiency and straightness.
Ordinary closeness is zero if a target is unreachable; the production pipeline retains a strongly
connected component before these calculations. Single-node centralities and efficiency are zero.
Finite, positive lengths are required on non-self-loop links. Straightness is calculated from the
supplied lengths without clipping values; meaningful physical lengths should be at least their
endpoint straight-line distance.

Closeness, straightness and node betweenness follow the supplied
[Crucitti, Latora & Porta paper](papers/AP2-centrality_measures_in_urban_networks.pdf), page 2.
**Efficiency follows Ticket 03:** reciprocal path length `1/d`, rather than the paper's spatial
efficiency `d_E/d`. Its value therefore depends on the distance unit and is not constrained to 0–1.
This distinction is intentional and follows the ticket's explicit formula.

The `nodes` GPKG layer adds `closeness`, `straightness` and `betweenness`; `edges` adds
`edge_betweenness`. `summary.json.metrics` adds mean, median, p90 and maximum for each measure,
`global_efficiency`, and `runtime_seconds` for graph preparation, shortest paths, betweenness and
total centrality computation. Runtime values will vary between repeated runs. `report.txt` adds
these statistics and the top 20 links by edge betweenness, including road names and OSM way IDs.

With `output.figures: true`, `figures/` also contains:

- `closeness_ccdf.png`, `straightness_ccdf.png`, `betweenness_ccdf.png`: empirical complementary
  cumulative distributions, showing the fraction of nodes with value at least x, on a log-y axis.
- `edge_betweenness_map.png`: grey road base with a viridis overlay, and thicker strokes for
  higher edge-betweenness quantiles.

### Memory and parallel execution

```yaml
analysis:
  n_jobs: 4
  max_memory_gb: 2
  directed_centrality: false
```

`n_jobs: auto` uses `SLURM_CPUS_PER_TASK` when set, otherwise the CPU count.
`max_memory_gb: auto` uses half the currently available RAM; numeric budgets use GiB (1024³ bytes).
Effective settings are recorded in `summary.json.computation` and resolved in `run_config.yaml`.
The summary also records exact budget bytes, the permitted chunk rows and the number of chunks.

The shortest-path engine reserves three float64 blocks per worker and uses
`max(1, floor(budget_bytes / (N * 8 * 3 * n_jobs)))` rows per chunk. It computes shortest paths,
straightness and efficiency contributions together, then returns only reduced values from each
joblib worker. Ticket 03 does not cache a whole distance matrix; Ticket 05 optionally caches its
removal baseline, as described below. One chunk is the minimum even if the
configured budget is smaller than one row's workspace; Python, graph and worker overhead are
additional to the block budget. NetworKit computes exact weighted node and edge betweenness with
`n_jobs` threads. A single-chunk shortest-path calculation avoids launching worker processes.

The reusable `ShortestPathEngine.reduce(sources, reducer, directed=False, limit=...)` supports
source subsets, cutoffs and directed CSR graphs for later tickets. Reducers receive a distance
block and its source indices; they may mutate the block and must return reduced results.
`engine.fits_in_memory(N, dtype)` checks whether one dense N×N array would fit. The centrality
reducer and efficiency aggregator accept optional nonnegative node weights for later population
work; the current CLI uses uniform weights. `analysis.directed_centrality: true` raises
`NotImplementedError` in the library and a clear nonzero CLI error because directed centralities
are deferred.

### Run and test ticket 03

```sh
python examples/create_ticket03_demo.py
georesilience run --config examples/ticket03-star.yaml --overwrite
georesilience run --config examples/ticket03-grid.yaml --overwrite
georesilience run --config examples/ticket03-path.yaml --overwrite
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest
```

All demo roads are 100 m long. Expected values:

| Demo | Manual check |
| --- | --- |
| Star | Hub betweenness **1**, leaves **0**; every link's edge betweenness **0.4** |
| Star | Hub closeness **0.01**, leaf closeness **4/700 ≈ 0.00571429**; efficiency **0.007** |
| Grid | Centre closeness **8/1200 ≈ 0.00666667** |
| Collinear path | Straightness **1** at all five nodes |

The generator also exports `star-input.gpkg`, `grid-input.gpkg` and `path-input.gpkg` under
`data/ticket03-demo/` for QGIS. Open the corresponding `results/ticket03-*/network.gpkg` output,
inspect both attribute tables, and use **Graduated** symbology on `betweenness` for nodes or
`edge_betweenness` for links. In the star, all roads have equal edge betweenness, so equal colours
and widths are expected. Inspect the PNGs and the report's top-links table as well.

The expensive benchmark is skipped by default. To run the 60,000-node perturbed grid with
8 jobs and a 2 GiB block budget:

```sh
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest --slow -m slow -s
```

It measures centrality computation and the combined parent/worker peak RSS, asserting less than
10 minutes and at most budget + 1 GiB. Input-fixture generation is outside the timed interval;
file export and plotting are tested separately. Runtime is hardware-dependent. Live source tests
remain opt-in with `--network`.

## Redundancy and candidates (ticket 04)

Every run now screens the cleaned network for road and junction failures. An **undirected bridge**
is a physical road whose removal disconnects the network even when travel directions are ignored.
Parallel physical roads remain separate alternatives. A **directed bridge** has an undirected
alternative but loses at least one required endpoint-to-endpoint travel direction after closure.
This can happen because the alternative route contains one-way roads.

For each non-loop physical road, detour screening removes all its directed edges, searches the
remaining directed multigraph, and divides the alternative route length by the road's original
length. Two-way roads use the worse of the two directions; one-way roads use their existing
direction. Known undirected bridges have no alternative and need no search. Other searches use
masked graph views and bidirectional Dijkstra, with joblib workers controlled by `analysis.n_jobs`.
Each worker receives the graph once and processes batches of links. Graph and process memory are
additional to the shortest-path block budget documented above.

| Output field | Meaning |
| --- | --- |
| edges: `is_bridge` | Removing this physical road disconnects the undirected network |
| edges: `cut_side_nodes`, `cut_side_frac` | Smaller bridge side's node count and count / N; zero for non-bridges |
| edges: `detour_ratio` | Alternative directed length / original length; null when no alternative exists |
| edges: `detour_none` | True when a required alternative route does not exist |
| edges: `is_directed_bridge` | No directed alternative, despite not being an undirected bridge |
| edges: `candidate_reason` | Semicolon-separated selection reasons, possibly empty |
| edges: `is_criticality_candidate` | Selected for full link-failure recomputation |
| edges: `is_analytic_bridge` | Selected for analytic bridge handling instead of full recomputation |
| nodes: `is_articulation` | Removing this junction disconnects the undirected network |
| nodes: `artic_max_cut` | Surviving nodes outside the largest component after removing the junction |
| nodes: `is_info_candidate` | Selected for information-centrality recomputation |

These cut counts measure **graph nodes**, not population. For example, removing a four-leaf star's
hub leaves four isolated nodes: one is the largest remaining component, so `artic_max_cut=3`.
Self-loops are excluded: numeric edge screening values are null, flags are false and reasons empty.
Their null detour does not mean an unsuccessful search (`detour_none=false`). A finite detour ratio
can be below 1 if the road being closed is longer than another available road.

Candidate selection uses the `criticality` defaults shown above:

- Bridges with smaller-side count at most `bridge_analytic_max_side` receive `analytic_bridge`.
  Larger bridges receive `large_bridge` and enter the full-recompute set.
- Non-bridge links enter the full-recompute set if selected by the top `k_betweenness` edge scores,
  the top `k_detour` detour ratios, or `directed_bridge`. Missing alternatives rank first for
  detours; equal detours use descending edge betweenness. Final ties use ascending `link_id`.
- All nodes are candidates when `N <= exact_info_max_nodes`. Otherwise select the top `k_nodes`
  node betweenness scores plus the top 50 articulations by severity. Node ties use cleaned graph
  node order. Counts can overlap, so union sizes need not equal sums of selection counts.
- `all: true` selects all nodes and all non-loop links except analytic bridges for full
  recomputation. Ranking reasons are retained; a road included only by `all` can have an empty
  reason. Use the explicit candidate flags to identify membership.

`summary.json.metrics.redundancy` contains bridge count/fraction and physical-length fraction,
finite detour median/p90/p99, no-alternative and directed-bridge counts, articulation count/fraction,
candidate-set sizes and overlapping counts by reason. If no finite detours exist, their quantiles
are JSON null. Screening runtimes join `metrics.runtime_seconds`. The report adds a **Redundancy**
section and top 20 bridges by cut-side size and non-bridges by detour, with names and OSM way IDs.
`figures/redundancy_map.png` shows bridges in red, directed bridges in orange and other links in grey.
Candidate selection feeds Ticket 05's damage/information calculations and prepares Ticket 11.
The efficiency convention documented for ticket 03 remains unchanged.

### Run and inspect ticket 04

From the repository root in your activated environment:

```sh
python examples/create_ticket04_demo.py
georesilience run --config examples/ticket04-path.yaml --overwrite
georesilience run --config examples/ticket04-ring.yaml --overwrite
georesilience run --config examples/ticket04-directed-ring.yaml --overwrite
georesilience run --config examples/ticket04-parallel.yaml --overwrite
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

| Demo | Expected screening result |
| --- | --- |
| Path: 6 nodes, 5 roads of 100 m | All bridges; cut-side sizes along the path **1, 2, 3, 2, 1**; all lack alternatives |
| Path candidates | Threshold 2 gives **4 analytic bridges**, **1 full-recompute link** (middle bridge), all 6 nodes |
| Two-way ring: 6 nodes, 6 roads of 100 m | No bridges/articulations; every detour **5** (500 m alternative) |
| Ring candidates | With both top-k limits 2 and tied scores, **2 full-recompute links**, all 6 nodes |
| Directed ring: same ring, only 0→1 on segment 0–1 | **0 undirected bridges, 5 directed bridges**; segment 0–1 has detour **5** |
| Parallel roads: 2 nodes, roads of 100 and 150 m | No bridges; detours **1.5** and **2/3**, respectively |

In the directed ring, closing any of the other five two-way roads leaves an alternative that
requires the missing **1→0** direction. Closing the one-way road itself still allows **0→1** via
the other five roads. Thus the orange roads are the other five segments.

Open each `results/ticket04-*/network.gpkg` in QGIS, select both layers and inspect their attribute
tables. Use **Categorized** symbology on `is_bridge` or `is_directed_bridge`, or open the redundancy
PNG directly. For path cut sizes, sort roads spatially along the path or use their endpoint columns.
Check `candidate_reason`, both edge candidate flags, and `is_info_candidate` against the table.
The input GeoPackages under `data/ticket04-demo/*-input.gpkg` open directly in QGIS; their edges
represent directed travel edges, so bidirectional roads appear twice at the same location.
The curved 150 m backup road is drawn separately from the straight 100 m parallel road.

To test `all: true`, copy the ring config, set both top-k limits to 0 and add `all: true` under
`criticality`, then run into a new folder. Expect all 6 roads and nodes selected, with empty road
reasons. Set `exact_info_max_nodes: 0`, `k_nodes: 2`, `all: false` to exercise node screening on the
ring: exactly 2 nodes are selected because there are no articulations. The generated examples
disable consolidation and declare GraphML simplified to preserve their known graph topology.

## Road damage and information centrality (ticket 05)

Every run now closes each candidate physical road independently and measures the resulting
damage. All directed edges of that road are removed together. Analytic bridges are also evaluated;
roads outside these sets and self-loops retain null scores. Closing the shortest parallel road
allows a longer surviving road to take over. No new configuration section is needed: the
`criticality` settings above select roads and junctions.

Road failures use directed travel by default (`analysis.directed_removal: true`). Setting this
flag to false explicitly runs undirected road closures instead; the summary and report state the
mode. The baseline directed efficiency is saved as `metrics.criticality.baseline_efficiency` and
can differ from Ticket 03's undirected `metrics.global_efficiency`.

| New output field | Definition |
| --- | --- |
| edges: `eff_drop` | `(E - E_after) / E`, using mean reciprocal shortest-path length |
| edges: `disc_pair_frac` | Previously reachable ordered pairs made unreachable / `N * (N - 1)` |
| edges: `extra_km_total` | Sum of additional distance for pairs reachable before **and** after, in km |
| edges: `affected_pairs` | Number of still-reachable ordered pairs whose distance increased |
| edges: `extra_m_mean_affected` | Extra metres per such pair; null if there are none |
| edges: `damage_method` | `full` for affected-source recomputation, `analytic` for analytic bridges; null if unevaluated |
| edges: `crit_rank` | 1 = highest efficiency drop; ties use higher disconnected-pair fraction, then lower `link_id` |
| nodes: `information` | Relative undirected efficiency loss after removing every edge incident to this node |

All denominators retain the original N. Unreachable pairs contribute zero efficiency.
Disconnected trips do **not** enter the extra-distance metrics: bridge closures therefore have
zero extra distance and zero affected pairs, despite positive efficiency and connectivity damage.
Ordered pairs count A→B and B→A separately. These are structural trip-pair measures, using every
pair equally rather than observed traffic demand. An unevaluated score is null, not evidence of
zero damage. If baseline efficiency is zero, relative efficiency loss and information are undefined
and remain null; such links have no rank.

Information centrality always uses the undirected minimum-length graph. Junction deactivation
isolates the node and keeps it in the node set; it does not delete the node or renormalize N.
`metrics.information.coverage` is `all` when every node was evaluated, otherwise `candidates`.
Non-candidate nodes have null `information`. Its baseline efficiency and finite statistics are
recorded alongside the candidate count.

The node-deactivation operation and relative-loss form follow page 2 of
[AP2](papers/AP2-centrality_measures_in_urban_networks.pdf), but **the efficiency convention differs**:
this project uses inverse-distance efficiency `mean(1/d)`, in 1/metres, as specified in Tickets 03/05.
AP2's spatial efficiency is `mean(d_E/d)`, dimensionless. Information scores here must not be
presented as numerical replications of AP2's spatial-efficiency scores.

### Exact shortcuts, caching and resource use

The reusable `ActiveEdgeGraph` retains every directed arc's physical-road membership. It sorts
arcs once, then rebuilds minimum-parallel-edge CSR graphs in O(m) from an active-edge mask for
closures or junction isolation. The remaining road set is collapsed **after** removal.

`AffectedSourceRecompute.affected_sources(link_id)` obtains endpoint distance columns by running
Dijkstra on the reversed baseline graph. A source is included if `d(i,u) + L` equals `d(i,v)`
with relative tolerance `1e-9`, for any removed direction. Tied paths may select extra sources;
recomputing them remains exact. Only selected rows are recomputed, in memory-bounded chunks.
The API also accepts a distance cutoff and generic reducers for Ticket 11.

Small-side bridges lose precisely their cross-cut pairs. With uniform weights their disconnected
fraction is `2 * |S| * (N - |S|) / (N * (N - 1))`. Forward and reversed distances from S give the
lost efficiency contributions; inside-side distances are unchanged. Cached distances are reused
when available. Junction information uses full chunked all-pairs recomputation, with source chunks
parallelized through `analysis.n_jobs`; the link shortcut is not applied to junctions.

The optional float64 baseline cache is enabled automatically only when the N×N matrix **plus**
at least one eight-block working chunk per configured worker fit `analysis.max_memory_gb`.
It uses a temporary memory-mapped file to share distances with workers without repeatedly copying
the matrix. Temporary disk space is checked; insufficient space falls back to recomputed baseline
rows. The temporary file is deleted when the calculation completes or raises an error.
`summary.json.computation` records cache mode/bytes, remaining working budget and the total affected
sources used for full-method closures. Temporary paths are not written into reusable configs.

Removal and information chunks conservatively allow eight float64 blocks per worker, so their
row limit is `max(1, floor(working_budget / (N * 8 * 8 * n_jobs)))`. Graphs, process overhead and
the minimum one-row workspace are additional to the block budget, as in Ticket 03.
The library accepts optional finite nonnegative node weights: efficiency and disconnected-pair
fractions use `W_i * W_j`, normalized over distinct pairs. Only uniform-weight columns are exported
in Ticket 05; population input and `_pop` exports are deferred to Ticket 12.

`metrics.criticality` records evaluated counts by method, the top 20 ranked roads, and totals over
independent single-road closures. These totals may count a trip repeatedly across different
experiments; they do not describe simultaneous road closures. The report adds **Critical links**
and **Information centrality** sections. `figures/critical_links_map.png` overlays up to 50 ranked
roads on a grey network, coloured by efficiency loss. Timestamped progress includes completed
links/nodes and estimated remaining time, with heartbeats during long calculations.

### Run and inspect ticket 05

From the repository root in your activated environment:

```sh
python examples/create_ticket05_demo.py
georesilience run --config examples/ticket05-ring.yaml --overwrite
georesilience run --config examples/ticket05-path.yaml --overwrite
georesilience run --config examples/ticket05-star.yaml --overwrite
georesilience run --config examples/ticket05-parallel.yaml --overwrite
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

All roads are 100 m except the 150 m parallel backup. All roads and nodes are selected; bridges
still use analytic handling under `all: true`.

| Demo | Expected result |
| --- | --- |
| Four-road ring | Every road: `eff_drop=2/15`, `disc_pair_frac=0`, `extra_km_total=0.4`, `affected_pairs=2`, mean extra 200 m |
| Ring nodes | Every node: `information=0.5` |
| Four-node path | Middle road: `eff_drop=7/13`, `disc_pair_frac=2/3`, `crit_rank=1` |
| Path roads | All three analytic; extra distance and affected count zero; mean affected distance null |
| Five-node star | Hub: `information=1`; leaves: `information=5/14` |
| Parallel roads | Closing 100 m road: `eff_drop=1/3`, extra 0.1 km, 2 affected pairs, mean extra 50 m |
| Parallel roads | Closing 150 m road: efficiency drop 0, extra distance 0, no affected pairs |

Open each `results/ticket05-*/network.gpkg` in QGIS and inspect `edges` and `nodes`. Use **Graduated**
symbology on `eff_drop` for roads or `information` for junctions. Compare the report's ranking with
`crit_rank`, inspect the critical-road PNG, and open `data/ticket05-demo/*-input.gpkg` for the inputs.
Equal damage scores in the symmetric ring and star are expected.

For candidate-only output, copy the ring YAML and set `all: false`, `k_betweenness: 1`,
`k_detour: 0`, `exact_info_max_nodes: 0`, and `k_nodes: 1`. Run to another output directory:
exactly one road and one junction receive scores; other scores are empty. To force baseline-row
recomputation, set `analysis.max_memory_gb: 0.0000001` in a demo copy; its computation metadata should
say `criticality_baseline: recomputed` and metric values should agree with the cached run.
This tiny budget deliberately invokes the documented minimum-row exception.
To check analytic handling against the full method, copy the path config and set
`bridge_analytic_max_side: 0`; the three roads switch to `damage_method=full` with matching damage.
Cost grows with the candidate count: complete information and every-road failure runs on large
city networks are expensive. Start with the default candidate limits before choosing `all: true`.

## Cumulative attacks and random failures (ticket 06)

Every run also removes roads or junctions cumulatively and compares targeted attacks with random
failures. Each experiment starts from the cleaned network. These experiments use the **directed**
travel graph, including when Ticket 05's `analysis.directed_removal` is false. The network is not
trimmed to its largest component again after removals.

```yaml
robustness:
  removal: [links, nodes]       # either one, or both
  steps: 50
  f_max: 0.20
  adaptive: true
  node_attack_metric: betweenness  # or degree
  failure_runs: 10
  efficiency_sources: 500
```

Link attacks rank active physical roads by exact length-weighted directed edge betweenness,
using the larger score of a two-way road's directions. Closing a road removes both directions.
Parallel roads remain separate closure candidates: the shortest active road supplies an analysis
arc; equal lengths select the lowest `link_id`. Other parallel roads have score zero until they
supply a shortest arc. Self-loops are excluded from road removals.

Node attacks use exact directed weighted node betweenness by default. Choosing `degree` counts
distinct neighbours while ignoring travel direction. Removing a junction closes all incident
roads. Adaptive attacks recompute scores before every batch with positive removals; static
attacks (`adaptive: false`) use the initial ranking throughout. Ties use ascending road ID or
original node order, with numerical score ties grouped at tolerance `1e-12`.

Random failures use seeded permutations without replacement. Separate `SeedSequence` streams
for sampling, link failures and node failures make results reproducible with `analysis.seed`.
Changing thread count preserves curves; runtime and report timestamps can differ. Increasing
the failure-run count preserves existing runs, and disabling one element preserves the other's
permutations. The sample of efficiency sources stays fixed across every step and experiment.

| CSV column | Meaning |
| --- | --- |
| `element`, `mode` | `links` or `nodes`; `attack` or `failure` |
| `run`, `step` | Attack run 0; failure runs 1 through `failure_runs`; step 0 is the baseline |
| `f` | Number removed / original number of that element |
| `S_scc`, `S_wcc` | Largest strong/weak component size / original N |
| `E_rel` | Fixed-source efficiency estimate / its baseline estimate |

Removed nodes do not count in component sizes. They remain in the efficiency denominator,
contributing zero as either source or target. With uniform weights, efficiency is
`sum(1/d_sj) / (sample_size * (N - 1))` over the sampled original sources and all other original
nodes. Unreachable pairs contribute zero. The implementation uses chunked shortest paths with
the existing memory budget and workers. If `efficiency_sources >= N`, it uses all sources and
efficiency is exact. A zero baseline makes `E_rel` undefined: CSV cells are empty, summary AUCs
are null, and the efficiency plot explains this.

**Efficiency convention:** this remains Ticket 03's inverse-distance `mean(1/d)`, rather than
AP2's spatial `mean(d_E/d)`. `E_rel` is dimensionless and independent of the distance unit.
These curves compare network topology and reachability; they do not reproduce AP1's diameter
metric or establish a fitted power-law distribution.

**Integer removal convention:** the budget is `floor(f_max * total)`, spread across the requested
steps using rounded cumulative counts. A step can remove zero elements on a small graph; its
measurements repeat. This avoids both exceeding `f_max` and rounding every small batch to zero.
CSV fractions record actual removals. If the last fraction is below `f_max`, AUC holds the final
value constant over that small remaining interval. AUC is the trapezoidal area divided by
requested `f_max`; larger values mean more retained connectivity or efficiency. The summary
records the actual horizon, removal count and per-step batch sizes.

`summary.json.metrics.robustness` contains per-element attack AUCs, mean failure AUCs, mean and
5th–95th percentile failure bands, parameters, sample node IDs, and `f_half_attack` (the first
observed fraction where `S_scc < 0.5`, otherwise null). Links are flagged as the headline.
The report includes the AUC table and final targeted-removal percentages.
`figures/robustness_scc.png` and `figures/robustness_efficiency.png` each have a panel per enabled
element, showing the attack, failure mean and failure percentile band. The band describes the
simulated runs, not a confidence interval for a population mean. `output.figures: false` suppresses
these figures along with the earlier figures. Progress logs include an estimated remaining time.

### Run the ER and scale-free examples

From the repository root in your activated environment:

```sh
python examples/create_ticket06_demo.py
georesilience run --config examples/ticket06-er.yaml --overwrite
georesilience run --config examples/ticket06-scale-free.yaml --overwrite
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_robustness.py
```

The generator creates two **500-node** graphs with similar mean degree:

| Model, seed 42 | Physical roads | Mean degree | Maximum degree |
| --- | --- | --- | --- |
| Erdős–Rényi `G(n,p)`, `p=6/(n-1)`, resampled until connected | 1,541 | 6.164 | 18 |
| Barabási–Albert preferential attachment, `m=3` | 1,491 | 5.964 | 65 |

All roads are bidirectional and have equal 1,000 m analysis lengths, so shortest-path rankings
depend on topology. Coordinates are a schematic spring layout in EPSG:32644; geometry length
differs from analysis length. Crossings are not junctions unless they share a graph node.
The graphs are synthetic examples, and the finite BA sample is not a statistical classification
of a real road network. ER sampling is explicitly conditioned on connectedness so cleaning keeps
all 500 nodes. This is inspired by the model comparison in
[Albert, Jeong & Barabási](papers/AP1-error_and_attack_tolerance_of_complex_networks.pdf).

Both configs use adaptive **degree-based node attacks**, betweenness-based link attacks,
50 steps, 20% maximum removal, 10 failure runs and all 500 efficiency sources. Ticket 05's
candidate limits are reduced to keep the earlier independent-removal stage quick; Ticket 06
still considers **all** roads and junctions.

Inspect `data/ticket06-demo/models.png` and `manifest.json` for the input topology and generation
parameters. For QGIS, open `er-input.gpkg` or `scale-free-input.gpkg` in that folder; each has nodes
and directed edges (two overlapping edges per physical road). Corresponding output GeoPackages
are in `results/ticket06-er/` and `results/ticket06-scale-free/` and retain the baseline network.
Attack steps are recorded in CSV curves rather than exported as separate map layers.

Each results folder has **1,122 CSV data rows**: 2 elements × 11 experiments × 51 observations.
All baseline rows have `S_scc=S_wcc=E_rel=1`. Expected node-attack endpoints for these seeds:

| Model | Fraction of nodes removed | Final `S_scc` | Attack AUC(E) | Mean failure AUC(E) |
| --- | --- | --- | --- | --- |
| ER | 0.20 | 0.782 | 0.697513 | 0.785091 |
| Scale-free | 0.20 | 0.550 | 0.427121 | 0.790109 |

The BA example's hubs make targeted node removal more damaging to efficiency, while random
node-failure AUCs are similar here. Neither node attack reaches `S_scc < 0.5` within this horizon,
so `f_half_attack` is null. Link attacks give final `S_scc=0.888` for ER and `1.0` for BA;
the BA network stays connected while losing efficiency. These are finite-example results,
not a guarantee that one model dominates the other for every attack strategy or metric.

To generate 1,000 nodes instead, use `python examples/create_ticket06_demo.py --nodes 1000`,
then rerun the same configs. Their 500-source efficiency becomes an estimate; increase
`robustness.efficiency_sources` to 1000 in config copies to use all sources. This replaces the
generated demo inputs, and the 500-node reference values above no longer apply.
For a static comparison, copy a config, set `adaptive: false`, and run it into a separate folder
with `--out`. To compare node strategies, similarly set `node_attack_metric: betweenness`.

## Distribution classification (ticket 07)

Every run fits degree, closeness, straightness, betweenness and computed information-centrality
values. No new configuration section is needed. `summary.json.classification` contains the
distribution evidence and the network decision; the report adds **Network class**.

Only positive finite values enter fits. Counts of excluded zeros, nonfinite values and negatives
are recorded separately. Fewer than 50 positive values, fewer than three distinct values, or a
failed tail fit give an inconclusive verdict with a reason. Missing information values do not
enter its distribution. Fits on a candidate set remain descriptive.

The per-distribution rules follow Ticket 07, in order:

1. Fit a power-law tail with package-selected `xmin`, comparing against exponential and lognormal
   tails. Select `power_law` when it significantly beats exponential at `p < 0.1`, lognormal does
   not significantly beat it, and at least 50 observations are in the tail.
2. Fit exponential and half-normal bodies with location fixed at zero. `delta_aic` is exponential
   AIC minus half-normal AIC. Values greater than 10 give `gaussian` (the ticket's half-normal
   shorthand); values below -10 give `exponential`. A significantly preferred exponential tail
   also gives `exponential`, after the earlier rules.
3. Otherwise return `inconclusive`.

| Information coverage | Evidence | Network label |
| --- | --- | --- |
| All nodes | Information `power_law` | `scale-free` |
| All nodes | Information `exponential` | `exponential` |
| All nodes | Information Gaussian/inconclusive | `inconclusive` |
| Candidates only | Betweenness `exponential` | `scale-free`, inferred from betweenness |
| Candidates only | Betweenness `gaussian` | `exponential`, inferred from betweenness |
| Candidates only | Other betweenness verdict | `inconclusive` |

JSON labels remain `scale-free`, `exponential` or `inconclusive`; `label_basis` distinguishes
`information` from `betweenness_fallback`. The report explicitly states when candidate information
is excluded. For full information, exponential betweenness supports the self-organized pattern;
Gaussian betweenness supports the planned pattern. Opposing recognized patterns are inconsistent;
other secondary verdicts are `n/a`. There is no betweenness fallback when full information itself
is inconclusive. Degree, closeness, straightness and the robustness gap never determine this label.

The supporting node gap is failure AUC(S) minus attack AUC(S). Its sentence explains the sign,
without inventing a threshold for a "large" gap. Links-only robustness leaves the gap null.

For each distribution the summary records `alpha`, `xmin`, `n_tail`, `R_exp`, `p_exp`, `R_ln`,
`p_ln`, `delta_aic`, body scales/AICs, tail KS distance, sample counts, verdict/reason and numerical
warnings. Continuous values are fitted in median units to improve conditioning, then scales and
`xmin` are restored to original units. Degree is fitted discretely without rescaling, using exact
discrete fitting. The power-law exponent range is explicitly `alpha > 1` with no upper cap:
installed powerlaw 2.0 otherwise caps it at 3, which would constrain the light tails in this study.
The package version and rule thresholds are recorded. `metrics.runtime_seconds.classification`
measures fitting, independently of plotting.

With figures enabled, ten PNGs are added: `classification_<distribution>_loglog.png` shows the
empirical positive-value CCDF and fitted power-law tail; `classification_<distribution>_logy.png`
shows the empirical CCDF and exponential/half-normal body fits. Tail curves are multiplied by
the observed tail fraction so they share the empirical normalization. Fits can be shown even
when they do not win the verdict. Existing Ticket 03 CCDFs remain available.

### Independent degree comparison

`classification.degree_evidence` compares a discrete Poisson reference and a bounded discrete
power-law reference on the **same positive degree observations and common support**
`observed minimum ... N-1`. Both are normalized on that support and have one fitted parameter.
`delta_aic = AIC_Poisson - AIC_power_law`: above 10 is `power_law_like`, below -10 is `poisson_like`,
otherwise inconclusive. Parameter estimates, support and AICs are recorded. Power-law optimization
uses exponent bounds 0–20; reaching the upper boundary gives inconclusive evidence.

This comparison is separate from the ticket's degree-tail fit and its continuous body descriptors.
Neither degree result feeds back into the network label. `degree_agreement` maps `poisson_like`
to the exponential reference family and `power_law_like` to scale-free, recording agreement,
disagreement or an inconclusive comparison. The Poisson reference approximates sparse ER degree
structure; it is not a simple exponential fit to all ER degrees.

### Run the ten-graph benchmark

From the repository root in your activated environment:

```sh
python examples/run_ticket07_benchmark.py --overwrite
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_classification.py
```

Defaults generate **five ER and five Barabási–Albert graphs**, **500 nodes each**, using seeds
**42, 43, 44, 45, 46**. The generator reuses Ticket 06's topology recipe: ER `p=6/(N-1)` conditioned
on connectedness, BA `m=3`, bidirectional roads of equal 1,000 m analysis length, and schematic
coordinates. Generation seeds, ER sampling attempts and model parameters are recorded.

Full information centrality is enabled with `criticality.exact_info_max_nodes: 500`. Independent
road-damage candidate limits stay small. Supporting robustness uses **nodes only**, **20 steps**,
**20% removal**, adaptive degree attacks, **10 failures** and all 500 efficiency sources. These
settings are shared by all ten cases; the Ticket 06 reference curves used 50 steps and both
element types, so their gap values should not be substituted here.

The first ER/BA pair gets all figures by default. Other cases retain full numeric outputs while
avoiding repeated plot rendering. Use `--figures all` or `--figures none` to change this.
Inputs, QGIS copies, model illustrations and reusable per-case YAMLs are generated under
`data/ticket07-demo/seed42/` through `seed46/`. Each seed folder has `er.graphml`,
`scale-free.graphml`, corresponding `*-input.gpkg`, `models.png`, `manifest.json`, `er.yaml` and
`scale-free.yaml`. These generated files are gitignored; the benchmark script is source.

Results live under `results/ticket07-benchmark/`:

- `comparison.csv`: ten rows with graph statistics, centrality verdicts, labels, degree evidence,
  agreement with degree and generator family, and the node attack/failure gap.
- `comparison.json`: the rows, aggregate counts, conclusive fraction and agreement among conclusive
  comparisons, with the benchmark parameters and generation metadata.
- `report.txt`: the complete comparison table and interpretation.
- `benchmark_manifest.json`: identifies the current cases, their configs and generation settings.
- `er-seed42/`, `scale-free-seed42/`, etc.: ordinary pipeline outputs for each case. Representative
  folders also contain all classification and robustness plots.

Useful commands:

```sh
# Generate inputs and configs without running analyses:
python examples/run_ticket07_benchmark.py --generate-only
# Rerun one generated case into a separate folder:
georesilience run --config data/ticket07-demo/seed42/er.yaml --out results/ticket07-er-check --overwrite
# Rebuild aggregate files from completed case outputs, without recomputation:
python examples/run_ticket07_benchmark.py --summarize-only
# Use a different study size or seed set (reference values will change):
python examples/run_ticket07_benchmark.py --nodes 1000 --seeds 42 43 44 45 46 --out results/ticket07-1000 --overwrite
```

The ordinary automated suite checks fitting and branch logic plus small end-to-end fixtures.
The full ten-case experiment runs explicitly through the script; it is not repeated on every
pytest invocation. Benchmark disagreements do not fail software tests or change thresholds.

For the documented 500-node seeds, degree evidence favors Poisson for all five ER graphs and
power law for all five BA graphs. Ticket 07 labels BA seeds **42, 44 and 46** scale-free; the other
**seven cases are inconclusive**, including every ER case. Thus there are **3 agreements,
0 disagreements and 7 inconclusive comparisons**, with a **30% conclusion rate**. Agreement
among the three conclusive cases is 100%; this is not 100% classification accuracy. Detailed
per-case findings are recorded in [TICKET_UPDATES.md](TICKET_UPDATES.md).

An inconclusive network label can follow successful fitting. All seven such cases above have
an information verdict of `gaussian` (the half-normal reference), which the ticket does not map
to either network family. Information was computed for every node and no information fit error
was recorded. BA seeds **43 and 45** have only **33 and 32** selected tail observations, below
the required 50, and their power-law-versus-exponential p-values (**0.224 and 0.259**) also fail
the required `p < 0.1`. For ER, Poisson-like degrees do not imply exponential information
centrality. These outcomes expose limited coverage of the specified criterion, even when the
software applies it correctly. Larger samples may help thin tails but do not guarantee agreement;
retain inconclusive results rather than adjusting thresholds to force matches.

### Interpretation and paper limits

[AP2](papers/AP2-centrality_measures_in_urban_networks.pdf) distinguishes city samples through
information centrality, and notes geographic constraints on primal junction degree. Synthetic
ER/BA models do not automatically represent planned/self-organized cities. Comparing their
degree evidence with Ticket 07's label is an additional empirical experiment.

The project still uses inverse-distance efficiency `mean(1/d)` rather than AP2's spatial
`mean(d_E/d)`. Reported `alpha` is the fitted **density** exponent; an ideal continuous power-law
CCDF has exponent `alpha - 1`. It should not be directly equated with AP2's plotted CCDF exponents.

These verdicts are **relative model evidence under the ticket's rules**. AIC and likelihood-ratio
comparisons do not establish absolute goodness of fit. The uniform control can receive `gaussian`
because half-normal fits better than exponential, despite its known uniform generator. A bootstrap
goodness-of-fit analysis is not implemented. Centrality observations share a graph and are
dependent, so nominal p-values require caution. Numerical fitting warnings remain in the JSON.
Inconclusive outcomes are counted separately rather than presented as errors or silently dropped.
The benchmark reports agreement, not general classification accuracy for cities.

## Failure probabilities (ticket 08)

Every run assigns each non-self-loop **physical link** a `p_fail`: the probability it is closed
during **one event/scenario**, not an annual failure rate. CSV values are user-supplied scenario
inputs; the fallback is a length proxy. **No road-class failure table is shipped.** Earthquake
and flood hazard presets are future work. Synthetic demo probabilities are not calibrated risks.

### Export, fill and import a template

```sh
georesilience template --config my.yaml --out p_fail_template.csv
```

This runs loading and cleaning only, without centralities or removal experiments, and writes
one row per distinct OSM way ID on a non-self-loop physical link. It refuses an existing file
unless `--overwrite` is supplied. Export with the same input and cleaning settings as your run.
The Python function `georesilience.failure_probabilities.export_edge_template(G)` returns
commented CSV text for a cleaned graph; its optional second argument writes that text to a path.

Columns are `osm_way_id,name,highway,length_m,n_links,p_fail`. Fill `p_fail` with probabilities
in `[0,1]`, or leave it blank for the proxy. Zero is an explicit supplied probability. Only
`osm_way_id` and `p_fail` are required when importing; metadata columns are ignored. OSM way
IDs are parsed as integers without conversion through floating point. CSV comments use `#`.

`length_m` sums each containing physical link's length divided by its number of distinct ways;
`n_links` counts containing physical links, including separate parallel roads. Reciprocal edges
count once. **This is an equal-share approximation:** simplification does not retain original
per-way lengths. A way shared by several links has one template row and its supplied probability
is reused on each containing link. Links without OSM way IDs use the full length proxy.

Point your YAML at the filled CSV, then run the usual analysis:

```yaml
reliability:
  p_fail_csv: p_fail_template.csv
  p0: 0.01
  p0_sweep: [0.001, 0.01, 0.05]
```

```sh
georesilience run --config my.yaml --overwrite
```

Paths are relative to the working directory. Invalid/nonfinite probabilities, values outside
`[0,1]`, malformed IDs and duplicate IDs stop the run before centrality computation. Messages
identify **one-based data rows** after the CSV header; comment and empty lines do not count.
Unknown IDs and blank probabilities generate warnings; unknown values are excluded and blanks
use the proxy. Reports and summaries retain up to 20 CSV warning messages plus total/omitted
counts. An unknown row with a blank value contributes both warnings.

### Combination and sensitivity

For distinct ways `W`, supplied ways `C`, uncovered fraction `s = (|W|-|C|)/|W|`, and length `L`
in kilometres:

```text
p_link = 1 - product(1 - p_w for w in C) * (1 - p0) ** (L * s)
```

This is the ticket's **any-part-fails** combination, assuming independent part failures.
Without supplied values, it becomes `1 - (1-p0)**L`. All supplied ways give source `user`, none
give `proxy`, and partial coverage gives `mixed`. Both directions of a physical link share the
same probability and constitute a single closure unit. Self-loops receive null probability and
source and are excluded from templates and coverage. Tiny probabilities are computed using
`log1p`/`expm1` to avoid cancellation, with explicit handling of probabilities 0 and 1.

The primary `p0` supplies exported probabilities. The sweep is sorted, deduplicated and always
includes that primary value; every entry must be finite and in `[0,1]`. No failure simulations
are performed by this assignment stage. Ticket 09 consumes these probabilities for connectivity;
Ticket 10 uses them for travel-time reliability. Ticket 06's existing
fraction-based removal experiments retain their own definition.
`probabilities_at_p0(links, user_probabilities, p0)` returns probabilities keyed by non-self-loop
`link_id`, so later stages can reuse the inputs for each sweep without reloading the CSV.

### Outputs and coverage

- `network.gpkg`, `edges`: `p_fail`, `p_fail_source` for the primary `p0`.
- `summary.json.reliability.coverage`: `by_source` counts, kilometres, link percentages and length
  percentages for user/mixed/proxy; total non-self-loop links/length; unmatched-ID count; `p0`
  and `p0_sweep`.
- `user_length_km/pct` and `proxy_length_km/pct` measure effective supplied/uncovered length,
  splitting mixed links equally among their ways. The source table instead counts each entire
  link in one category. These two views are deliberately distinct.
- `summary.json.reliability.warnings`: total, shown messages, omitted count and blank-value count.
- `report.txt`: **Failure probabilities** section, source table, effective coverage and warnings.
  If effective user-length coverage is nonzero but below 50%, the proxy-length warning includes
  uncovered shares of mixed roads. At zero coverage the table shows full proxy use; at exactly
  50% the additional warning is omitted, following the ticket threshold.
- `run_config.yaml`: resolved reliability settings, including the primary value in the sweep.

### How to read the Failure probabilities report

Start with the **Failure probabilities** section of `report.txt`. Its percentages describe
**input-data coverage**. Individual road closure probabilities are in the GeoPackage's `edges`
layer as `p_fail`; multiply a value by 100 to express its per-event probability as a percentage.
For example, `p_fail = 0.098746882` means about **9.87% per event**. The source label `user`
means a probability was supplied in the CSV; it does not establish that it was measured or
calibrated. A supplied zero is valid user coverage, while a blank falls back to the proxy.

**Network and source counts:** the three default spatial cases contain the same **200 nodes,
1,046 physical links and approximately 537.221 km**. Their 2,092 directed edges represent
two directions for each physical road. Failure coverage counts those roads once. In the mixed
case, the table reads:

| Source | Interpretation | Links | Links (%) | Length (km) | Length (%) |
| --- | --- | --- | --- | --- | --- |
| user | All ways in the link have supplied probabilities | 233 | 22.28 | 122.285 | 22.76 |
| mixed | Some ways are supplied; the remainder use the proxy | 175 | 16.73 | 92.924 | 17.30 |
| proxy | No ways have supplied probabilities | 638 | 60.99 | 322.011 | 59.94 |

`Links (%)` divides each source's count by 1,046; `Length (%)` divides its total physical length
by the network length. For example, `233 / 1046 * 100 = 22.28%`. Source counts and lengths should
sum to the non-self-loop network totals, and both percentage columns should sum to about 100%.
Displayed values are rounded, so small differences in sums are expected.

**Effective user/proxy length:** the source table assigns each entire mixed link to the `mixed`
category. Effective coverage splits that link between supplied and uncovered shares. In this
particular demo, every mixed link has two ways with one supplied, giving:

```text
Effective user length %  = 22.76 + 17.30 / 2 = 31.41%
Effective proxy length % = 59.94 + 17.30 / 2 = 68.59%
```

The half-share applies to this demo; in general, use each link's fraction of supplied ways.
The line `WARNING: 68.6% of network length uses the length proxy` highlights reliance on the
proxy because effective supplied coverage is nonzero but below 50%. It does not describe the
percentage of roads expected to fail. The proxy-only control shows 100% proxy coverage and the
fully supplied control shows 100% user coverage.

**Primary p0 and sweep:** `p0 = 0.01` assigns the proxy a 1% per-event closure probability for
a 1 km link. A 2 km proxy link gets `1 - 0.99^2 = 0.0199`, or **1.99%**. Exported probabilities
use this primary value. The sweep lists alternative probability assumptions. The Ticket 08
section describes their assignment; the Ticket 09 section now reports their connectivity estimates.

**CSV warnings:** the mixed demo deliberately contains 290 blank probability rows and one
unmatched way ID: **291 warnings, 20 shown and 271 omitted**. Blank values use the proxy, and
the unmatched ID is ignored. These counts refer to CSV rows/OSM ways, while the source table
counts physical links; one way may occur in several links and one link may contain several ways.
Omitted way IDs also use the proxy, but generate no blank-row warning because they have no CSV row.

**Checking individual roads:** open `results/ticket08-spatial-mixed/network.gpkg`, layer `edges`,
in QGIS and locate these rows by `name`. Use the supplied values from
`data/ticket08-demo/spatial-mixed-probabilities.csv` and lengths in metres:

| Road | Calculation at primary p0 | Expected p_fail |
| --- | --- | --- |
| Spatial road 2 | Proxy: `1 - 0.99^(284.525636/1000)` | 0.002855494 |
| Spatial road 0 | One supplied zero; half uncovered: `1 - 0.99^(282.314549/2000)` | 0.001417672 |
| Spatial road 6 | Two supplied values: `1 - (1-0.086638623)*(1-0.013256812)` | 0.098746882 |

The table rounds inputs and outputs. For a complete comparison, match roads by `name` with
`data/ticket08-demo/<scenario>-expected.csv`, which calculates direct survival products
independently of the production calculation. All 1,046 probability/source pairs in each spatial
output were checked against these references. The small exact example below gives additional
answers that can be checked by hand. These checks establish calculation correctness; synthetic
probabilities and the proxy are not calibrated against observed road closures.

Earlier centrality and Ticket 06 robustness sections are expected to agree across these three
scenarios because they analyze the same graph and retain the same settings. Ticket 08 assigns
probabilities; Ticket 09 uses them to estimate connectivity reliability.

### Manual examples

From the repository root with your environment activated:

```sh
python examples/create_ticket08_demo.py
georesilience run --config data/ticket08-demo/exact.yaml --overwrite
georesilience run --config data/ticket08-demo/spatial-proxy.yaml --overwrite
georesilience run --config data/ticket08-demo/spatial-user.yaml --overwrite
georesilience run --config data/ticket08-demo/spatial-mixed.yaml --overwrite
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_failure_probabilities.py
```

The small exact example has three nodes and five physical roads. In its output edges table:

| Road name | Source | Expected `p_fail` |
| --- | --- | --- |
| 2 km proxy | proxy | `1 - 0.99^2 = 0.0199` |
| 3 km mixed | mixed | `1 - 0.9 * 0.99^1.5`, about `0.113466` |
| Single supplied way | user | `0.1` |
| Two supplied ways | user | `1 - 0.9^2 = 0.19` (one-way, two OSM ways) |
| Different supplied probabilities | user | `1 - 0.9 * 0.7 = 0.37` |

The other three runs use the **same 200-node connected random geometric graph**, seed 42,
with Euclidean lengths multiplied by `U(1.0,1.3)`. The generator samples until connected and
records its chosen topology seed. Some way IDs span multiple links, and some links contain
multiple ways. The proxy scenario has no CSV; the user scenario supplies every way, including
explicit 0/1 controls; the mixed scenario supplies every third way, leaves another third blank
and omits the remainder, plus one intentionally unmatched ID.

Open each `results/ticket08-*/report.txt` and inspect its output GeoPackage in QGIS. Input copies
are `data/ticket08-demo/exact-input.gpkg` and `spatial-input.gpkg`; line crossings are junctions
only where graph nodes are shared. Compare edges by **road name** with the generated
`<scenario>-expected.csv`, which uses independent direct survival products. Way-ID sets can
repeat on different roads, so they are not unique comparison keys. The manifest records graph
settings and exact answers. To inspect template export separately:

```sh
georesilience template --config data/ticket08-demo/spatial-mixed.yaml --out data/ticket08-demo/check-template.csv --overwrite
```

All four scenarios disable consolidation and figures. They keep earlier candidate and robustness
work small because this ticket tests probability assignment. Generated inputs/configs/reference
CSVs are ignored by Git; the generator and tests are tracked. Use `--nodes` and `--seed` on the
generator to choose a different spatial case.

## Connectivity reliability (Ticket 09)

Each analysis run now samples independent physical-road closures using Ticket 08 probabilities.
All directed edges of a failed physical link disappear together; parallel roads remain separate
failure units. Self-loops are excluded. This analysis always respects road direction, independently
of the centrality and removal direction settings. It operates on the **cleaned network**, whose
baseline is the retained largest strongly connected component.

This is an **AP3-inspired connectivity analysis**, not a replication of AP3's main experiment.
[AP3](papers/AP3-vulnerability_analysis.pdf), printed page 269, discusses connectivity reliability
as surviving paths; its principal method on pages 270–274 concerns accessibility losses.
Independent closures, the SCC score, node membership, conditional importance and these Monte Carlo
intervals are framework choices. Spatially correlated hazards and correlations between physical
roads sharing an OSM way are outside this model. Synthetic probabilities validate calculations,
not real-world road risks. The approved corrections to the original ticket are listed in
[TICKET_UPDATES.md](TICKET_UPDATES.md#ticket-09--connectivity-reliability).

### Configure sampling and OD pairs

```yaml
reliability:
  p_fail_csv: data/road-probabilities.csv  # optional; otherwise use the length proxy
  p0: 0.01
  p0_sweep: [0.001, 0.01, 0.05]
  samples: 10000
  od_pairs_csv: data/od-pairs.csv          # optional
  min_down_count: 30
  min_up_count: 30
```

`samples` must be at least two. Both count thresholds default to 30 and must be at least two
to support sample-variance estimation. Higher sample counts reduce Monte Carlo uncertainty and
make rare closures more likely to meet the importance threshold. Existing configs receive these
defaults, so earlier example runs also produce connectivity results now.

An OD file uses WGS84 **longitude before latitude**, with a unique nonempty label per row:

```csv
label,origin_lon,origin_lat,dest_lon,dest_lat
hospital,81.000,17.180,81.010,17.185
```

Endpoints snap to the nearest cleaned node in projected metres. Snap distances over 500 m produce
warnings, capped at 20 displayed messages with total/omitted counts. Tied nearest nodes use the
smallest node ID. Invalid labels or coordinates stop the run before centrality computation.
An origin and destination snapped to the same node are reachable with probability one.

### How to read the Connectivity reliability report

The report measures three different properties:

| Output | Meaning | What it does not establish |
| --- | --- | --- |
| `conn_reliability` | Expected fraction of distinct node pairs mutually reachable in each sampled graph | Share of actual journeys served; one-way reachability |
| `p_connected` | Probability a node belongs to the selected largest SCC | Probability of reaching a hospital or any other specified destination |
| OD `p_od` | Probability the named destination is reachable from its origin, following direction | Travel time or acceptable journey duration |

For each sample, an SCC is a strongly connected component: every node can reach every other node
in that component. With `N` nodes, the network score is:

```text
sum(component_size * (component_size - 1)) / (N * (N - 1))
```

The score excludes self-pairs, lies between zero and one and counts every distinct ordered pair
equally. The run reports its sample mean and approximate normal 95% confidence interval. Uniform
potential node pairs are not observed travel demand. The library also accepts nonnegative node
weights and uses products of those weights for pairs; the CLI currently uses uniform weights.
With no positive-weight distinct pairs, the network score and its interval are null, rather than
inventing a value for an undefined denominator.

The **p0 sweep** changes only the length-proxy assumptions. Supplied probabilities stay fixed.
The table reports the network score and interval at each p0; its change sentence uses percentage
points. Node, link and OD results use the primary p0. All sweep values use the same random uniforms,
which reduces comparison noise and ensures sampled mutual connectivity cannot increase as p0
increases. Fully supplied networks consequently have a flat sweep.

The **node section** reports mean membership, the tenth percentile across nodes, the maximum
Wilson interval half-width and the 20 lowest membership values. Largest SCC means largest **node
count**. Ties select the component with the smallest minimum node ID; numeric IDs sort numerically.
A singleton can be selected. For two nodes `0` and `1` joined by one two-way road with closure
probability 0.5, the exact answers are network **0.5**, membership **1.0 for node 0** and **0.5 for
node 1**. Their average is **0.75**; both nodes do not individually have membership 0.75 under
this deterministic rule. This corrects the original ticket's acceptance example.

**Link importance** is `mean(network score | road up) - mean(network score | road down)`.
An importance of 0.2 means a 20 percentage point conditional difference in mutual connectivity.
Under the independent-failure model this is a Birnbaum-style sensitivity, rather than the road's
closure probability or an estimate of annual loss. The report lists the top 20 available estimates
with Welch t 95% intervals and counts. All edges store `rel_up_count`, `rel_down_count` and status.
There must be enough observations **in both states**; never-failing, always-failing and rarely
observed states can leave the importance and interval null. Check `rel_importance_status` for
`insufficient_down`, `insufficient_up`, `self_loop` or `undefined_pair_universe`. An unavailable
importance is not zero. Small negative estimates can arise from sampling noise; inspect the CI.

**OD results** use actual directed reachability, with Wilson 95% intervals. A surviving road from
A to B can give OD A→B = 1 while B→A = 0 and mutual network score = 0. Forward/reverse OD rows
on the bidirectional spatial demos match because each road's two directions fail together.

Every CI describes **Monte Carlo sampling uncertainty conditional on the assumed probabilities**.
It excludes uncertainty in the length proxy, hazard calibration and independence assumptions.
Normal/Welch intervals are approximate; a constant observed network score can yield a zero-width
interval despite an unobserved rare disconnection. Whole-network-connected probability is outside
this metric's scope; it is not universally near zero. None of these results measures accessibility
loss or travel-time reliability, which belong to later tickets.

### Outputs and reproducibility

- `network.gpkg`, nodes: `p_connected`, `p_connected_ci_low`, `p_connected_ci_high`.
- `network.gpkg`, edges: existing `p_fail`/source, plus `rel_importance`, its `_ci_low`/`_ci_high`,
  `rel_up_count`, `rel_down_count`, `rel_importance_status`.
- `od_reliability.csv` when nonempty OD pairs are supplied: input coordinates, snapped node IDs,
  snap distances in metres, `p_od`, `ci_low`, `ci_high`.
- `summary.json.reliability`: preserves Ticket 08 coverage/warnings and adds network CI, sweep,
  node/link summaries, OD rows, sampling settings and metric definitions.
- `figures/connectivity_nodes_map.png` when figures are enabled, colored by main-SCC membership.

Seeded batches contain 256 samples each, with child seeds assigned by batch index and accumulated
in that order. Numerical connectivity estimates, intervals, counts and rankings are identical
for the same inputs/seed with one or four workers; runtimes and worker metadata can differ.
Increasing samples preserves the existing sample prefix. Identical probability vectors share
their network calculation. Tiny jobs use one worker to avoid process startup costs. Memory limits
reduce the worker count or reject an insufficient working-array budget; the estimate excludes
Python interpreter/process overhead. No all-pairs distance matrix or full failure-state history
is retained. Overwrite removes stale OD CSVs and the new map when they are no longer requested.

### Run and manually verify Ticket 09

From the repository root, with your environment activated:

```sh
python examples/create_ticket09_demo.py
georesilience run --config data/ticket09-demo/half.yaml --overwrite
georesilience run --config data/ticket09-demo/directed.yaml --overwrite
georesilience run --config data/ticket09-demo/bridge.yaml --overwrite
georesilience run --config data/ticket09-demo/spatial-proxy.yaml --overwrite
georesilience run --config data/ticket09-demo/spatial-user.yaml --overwrite
georesilience run --config data/ticket09-demo/spatial-mixed.yaml --overwrite
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_connectivity.py
```

Defaults use seed 42 and 10,000 samples. The spatial input has **200 nodes / 1,046 physical links**;
all three spatial scenarios use that same input with proxy-only, full-user and mixed coverage.
The generator accepts `--nodes`, `--seed`, `--samples`, `--out`. Generated data are gitignored;
the generator and tests are tracked. Figures are enabled for the three small cases and spatial
mixed; earlier analysis settings are kept small to focus this experiment on connectivity.

1. Open `results/ticket09-half/report.txt`, at **Connectivity reliability**. Expect network near
   0.5, its 95% CI containing 0.5 for the default seed, node 0 membership exactly 1, node 1 near
   0.5, and link importance exactly 1. Both OD directions match the network estimate. Compare
   the exact values in `data/ticket09-demo/half-expected.json`.
2. In `results/ticket09-directed/od_reliability.csv`, forward is exactly 1 and reverse near 0.5.
   The network is near 0.5. The always-up forward road has unavailable importance, status
   `insufficient_down`. Its p0 sweep is flat because every road has a supplied probability.
3. The bridge case joins two triangles with one road. Compare its network, memberships, OD values
   and link importances with `bridge-expected.json`, computed independently by enumerating all
   **128** failure states. Monte Carlo values should be close; individual 95% intervals are not
   guaranteed to cover every exact answer simultaneously. Match links by `name` or `link_id`.
4. Compare the spatial reports. Proxy/mixed network reliability should decrease or stay constant
   with increasing p0; fully supplied results stay flat. Most redundant roads can have importance
   near zero. Do not require an arbitrary ranking between the three coverage scenarios.
5. In QGIS open the corresponding `data/ticket09-demo/*-input.gpkg` and output `network.gpkg`.
   Check node membership/CI fields and link probabilities, counts and statuses. Every non-loop
   road has `rel_up_count + rel_down_count = 10000`. The supplied spatial case deliberately has
   probability-zero and probability-one controls; their importance must be unavailable.
   Geometric crossings connect only where the input graph has shared nodes.
6. To test reproducibility, copy a YAML, set `analysis.n_jobs` to 1 and then 4, and write to two
   output folders. Compare connectivity estimates and exported numerical fields. To test OD
   snapping, move an endpoint far from the graph and check its snap-distance warning.

Small exact references establish calculation correctness. The larger spatial cases check
coverage, redundancy, probability extremes and reproducibility; they do not provide ground-truth
hazard predictions. Automated tests additionally enumerate directed/parallel/weighted states and
check 99% network CI coverage over 100 fixed seeds, without tuning the probabilities or seeds.

The default runs produced network estimates **0.4918** (half), **0.4980** (directed) and **0.81428**
(bridge, exact **0.81532443625**). Each exact value is inside its reported 95% CI. Spatial primary
estimates were **1.0 proxy**, **0.999848 user** and **1.0 mixed**: this redundant graph rarely
disconnects under these probabilities. The observed 1.0 values do not establish zero failure risk.
Detailed counts and findings are in [TICKET_UPDATES.md](TICKET_UPDATES.md#verified-default-example-findings).

## Travel-time reliability (Ticket 10)

Ticket 10 is completed and manually verified by you as of **11 October 2026**. Implementation
details and test evidence are in [TICKET_UPDATES.md](TICKET_UPDATES.md#current-ticket-10--travel-time-reliability);
additional validation remains tracked in [plan/TEST_RECOMMENDATIONS.md](plan/TEST_RECOMMENDATIONS.md#10--travel-time-reliability).

This stage asks whether directed journeys remain within a **user-chosen relative delay** after
road closures. It uses the same physical-road probability model as Ticket 09, at the primary p0,
with a separate reproducible random stream. It is a framework extension, not an AP3 replication
or a traffic simulation. The default model uses **free-flow speeds; no traffic (Tier 4)**.

```yaml
travel_time:
  enabled: true
  samples: 1000
  n_origins: 200
  tau: 0.5
  highway_speeds_kph: null   # optional, e.g. {residential: 30, primary: 50}
  time_model: free_flow
```

`tau` is finite and nonnegative. A journey succeeds only when reachable and its time is
`<= (1 + tau) * baseline_time`, including equality within floating-point tolerance. With a
20-minute baseline and `tau: 0.5`, up to 30 minutes is acceptable. The default 50% tolerance is
a configurable assumption, not a threshold inferred from the input or established by AP3.
Absolute deadlines and different tolerances for individual OD pairs are future options.
`samples` must be at least two; `n_origins` at least one. `enabled: false` disables the stage.

### Distance, speeds and replaceable time models

The default `free_flow` model calculates seconds as `3.6 * length_m / speed_kph`. Speed tags support
numeric km/h, explicit km/h or mph, lane values separated by `|`, simplified lists and implicit
codes supported by the installed OSMnx 2.x parser. Lists/lane speeds are averaged after unit
conversion; this is a simplification, not reconstruction of original segment travel times.
Unsupported/unusable tags count as missing data. No existing arbitrary `speed_kph` attribute is
silently treated as a calibrated speed source.

OSMnx fills missing speeds using a user-supplied highway-class table where provided, otherwise
observed class means. Classes with no values use the mean of available class/table speeds.
The provider records `tagged`, `user_table`, `class_mean` and `network_class_mean` length coverage.
Each physical road's length is split across its directed edges for this calculation, so differing
directional tags contribute partial coverage and reciprocal roads are not counted twice.
Self-loops are excluded. Tagged speed limits are a free-flow proxy, not observed journey speeds.

With **no usable non-loop speed tags and no speed table**, the default stage returns
`skipped: no speed data`; the rest of the pipeline still succeeds. This affects older synthetic
examples that have distances but no speeds. No default speed table is invented.

Time assignment is separate from routing in `src/georesilience/time_models.py`. To incorporate
other factors now using precomputed **directed-edge seconds**, use:

```yaml
travel_time:
  time_model: edge_attribute
  time_attribute: modelled_time_s
  tau: 0.5
```

Every non-loop directed edge must have a finite, strictly positive value in that attribute.
It may already include distance, signals, road condition or other explicitly modelled factors.
This mode does not require speed tags. The Ticket 10 attribute example uses
`modelled_time_s = 3.6 * length_m / 60 + signal_delay_s`; its delay values are synthetic.

Python callers can provide a model implementing `prepare(graph, config)`:

```python
from georesilience.config import load_config
from georesilience.pipeline import run
from georesilience.time_models import PreparedTimeModel

class SignalDelayModel:
    def prepare(self, graph, config):
        seconds = {
            (u, v, key): data["length"] / 10 + float(data.get("signal_delay_s", 0))
            for u, v, key, data in graph.edges(keys=True, data=True) if u != v
        }
        return PreparedTimeModel(seconds, {
            "status": "computed", "time_model": "distance_plus_signal_delay",
            "time_function": "length_m / 10 + signal_delay_s",
            "assumptions": "illustrative 10 m/s speed plus supplied signal delays",
            "parameters": {"speed_mps": 10},
        })

run(load_config("my.yaml"), overwrite=True, time_model=SignalDelayModel())
```

For scenario-specific costs, `PreparedTimeModel` also accepts a `scenario_times(context)` callable
returning the same edge-to-seconds mapping. `TimeContext.sample_index` is `None` for the baseline;
otherwise it gives the global sample index and `closed_link_ids` identifies failed physical roads.
The model is called for every sample, including those with no closures. It should be deterministic,
serializable for worker processes and return positive finite seconds for every non-loop arc.
Model identity, assumptions and supplied metadata are saved in `summary.json.travel_time`.

Saved configs from Python-provider runs use `time_model: custom`; rerunning them requires passing
the provider again. A CLI rerun refuses to silently substitute the default formula. Supplied
edge-attribute runs are reproducible from YAML and their input data alone.

This interface supports **additive edge costs and static cost snapshots per scenario**. Actual
traffic assignment, turn-dependent costs and departure-time-dependent routing need additional
routing/model work; a hook alone does not implement them.

### How to read the Travel-time reliability report

The report states status, time model/function, `tau`, samples, selected origins and speed coverage.
Up to `n_origins` distinct nodes are selected uniformly without replacement, capped at network
size. Every other node is a destination. Extra OD origins are routed too, but do not change the
network sample. The report/JSON records the actual origin count and IDs.

- **`tt_reliability`:** mean successful fraction of sampled-origin/distinct-destination pairs,
  with a normal 95% interval across failure samples. A value of 0.8 means 80% of those potential
  directed journeys met the chosen delay criterion on average; it is not observed demand coverage.
- **Node `p_tt_ok`:** destination-success fraction averaged across samples for that origin.
  Only selected origins have values; other nodes are null even when routed for an OD. Node CIs
  use per-sample destination fractions, not an independence assumption for all destinations.
- **OD `p_tt_ok`:** probability that the specific directed journey meets its threshold, with a
  Wilson interval. `tt0_min` is its intact-network baseline in minutes. These fields join Ticket
  09's reachability fields in `od_reliability.csv`, with separately named time interval fields.
- **Travel-time factors:** pooled damaged/baseline ratios over reachable distinct journeys from
  sampled origins, including journeys exceeding the tolerance. Disconnected journeys are excluded
  from ratios but fail reliability. Thus factor percentiles alone do not measure connectivity.

Self-pairs are excluded from network scores and ratios. Same-node OD pairs succeed with baseline
zero. Baseline-unreachable journeys always fail and are counted separately; they normally do not
occur in the pipeline's cleaned largest-SCC baseline. With no distinct node pairs, the network
estimate is undefined. Directionality always follows the cleaned directed graph.

Factor percentiles use bounded-memory logarithmic histograms with an exact bin for ratio one.
The report gives approximate values and their bin bounds. For example, a true factor 3 may print
approximately 2.992776, with bounds [2.982699, 3.002888]. Percentiles falling below 1e-6 or above
1e6 are unavailable, with underflow/overflow counts reported. These are bin ranges, not CIs.

CIs cover **closure sampling conditional on fixed origins, probabilities and the time model**.
They exclude origin-selection, speed/model and hazard-calibration uncertainty. Normal intervals
can have zero observed width when every sampled score agrees, despite an unobserved rare failure.
Ticket 09's mutual-pair network score and this directed time score measure different properties;
their Monte Carlo samples also differ. Interpret each using its own definition and interval.

Outputs are `summary.json.travel_time`, the report section, sampled-node `p_tt_ok` and
`p_tt_ok_ci_low/high` in `network.gpkg`, and time fields in the existing OD CSV when computed.
Skipped/disabled stages leave node fields null and omit time fields from the OD CSV; overwrite
clears previously computed time results. No new figure is specified by this ticket; use QGIS
to style sampled-node values.

Intact travel times are calculated once and shared through a temporary disk-backed baseline,
then removed at completion. Damaged paths are processed in bounded origin chunks. Fixed indexed
batches make results independent of worker count and chunk size; increasing samples preserves
the closure prefix. The memory estimate covers working arrays, excluding interpreter/process
overhead and OS file-cache behavior. Baseline disk use is reported separately. No per-sample
distance matrices or individual travel-time-ratio histories are retained.

### Run and manually verify Ticket 10

From the repository root with your environment activated:

```sh
python examples/create_ticket10_demo.py
georesilience run --config data/ticket10-demo/tight.yaml --overwrite
georesilience run --config data/ticket10-demo/boundary.yaml --overwrite
georesilience run --config data/ticket10-demo/relaxed.yaml --overwrite
georesilience run --config data/ticket10-demo/skip.yaml --overwrite
georesilience run --config data/ticket10-demo/speed-table.yaml --overwrite
georesilience run --config data/ticket10-demo/attribute.yaml --overwrite
georesilience run --config data/ticket10-demo/sparse.yaml --overwrite
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_travel_time.py
```

Inspect **Travel-time reliability** near the end of each `results/ticket10-*/report.txt`, then
`od_reliability.csv` and the node fields in `network.gpkg`. Small-case exact expectations are in
`data/ticket10-demo/expected.json`. Defaults use seed 42 and 1,000 time samples:

| Example | Check | Default result |
| --- | --- | --- |
| Tight | Fast route takes 1 minute, always-available alternative 3; tau=0.5 | 0.505, exact 0.5 |
| Boundary | tau=2 accepts the 3-minute alternative at equality | 1.0, exact 1 |
| Relaxed | tau=2.5 also accepts the alternative | 1.0, exact 1 |
| Skip | No speeds/table | `skipped: no speed data` |
| Speed table | Missing speeds filled with residential=30 km/h | Baseline 2 minutes; reliability 0.505 |
| Attribute | Supplied times include signal delays, without speed tags | Baseline 1.25 minutes; reliability 0.505 |
| Sparse | Two grids joined by a vulnerable road; tau=0.25 | About 0.824866; no exact large-graph reference |

The sparse example has **200 nodes / 361 physical roads**, internal failure probability 0.08 and
joining-road probability 0.30. It produces both route failures and delays: across-bridge OD
success is **0.704**, nearby OD **0.928**. Only 24 sampled nodes have `p_tt_ok` values; two extra
OD origins are routed. All small-case same-node OD probabilities are exactly one.

Input copies for QGIS are `data/ticket10-demo/*-input.gpkg`. All examples keep earlier work small
and disable figures. The generator accepts `--nodes` (even, at least 20), `--samples`, `--seed`
and `--out`. Generated data/results are ignored; generator and tests are tracked. Try copied
configs with different `tau` values and output directories: with fixed inputs and seed,
reliability must stay constant or increase as the tolerance increases. For further validation,
see [plan/TEST_RECOMMENDATIONS.md](plan/TEST_RECOMMENDATIONS.md#10--travel-time-reliability).

## Crucitti city comparison (Ticket 15)

The [published historical dataset](#published-historical-ap2-networks) is now available as a
separate offline comparison. The modern OSM experiments below remain useful sensitivity
studies; they are preserved alongside the published-data run.

This experiment compares approximately one-square-mile samples of Ahmedabad, Cairo,
Los Angeles and Richmond, California, with [AP2](papers/AP2-centrality_measures_in_urban_networks.pdf),
particularly its Figure 3. It uses the fixed centres in
[Ticket 15](plan/tickets/15-crucitti-replication.md), projected 1609 m squares, and OSMnx's
`all` network filter. These are approximate modern samples, not the original historical windows.
The proposed centres are recorded as coordinates, rather than asserted to reproduce AP2's maps.

**Location review:** the same authors' [companion paper, §3.1 and Figure 1](https://www.udsu-strath.com/wp-content/uploads/2010/06/PA2006_09.pdf)
explicitly labels Richmond, CA. Jacobs' book index refers to Richmond, Virginia, which initially
raised a concern; that alone does not justify replacing the city with Virginia. Retain the
predefined California sample and verify the exact historical window from the authors' maps.

From the repository root with your environment activated, optionally download and inspect first:

```sh
georesilience validate crucitti --out results/ticket15-crucitti --download-only
```

Each `inputs/<city>/` directory contains the unsimplified `raw.graphml`, WGS84 `boundary.geojson`,
`manifest.json` with download time, software versions and SHA-256 checksums, and a derived
`input.gpkg` for QGIS (layers `nodes`, `edges`, `boundary`). The GeoPackage is an inspection copy;
analysis reads GraphML, not edits to this copy. Frozen GraphML and boundary checksums are verified
on reuse. Inputs are never refreshed by `--overwrite`; use a new `--inputs` directory for a new
download. OSMnx may satisfy requests from its response cache; the recorded download time is the
retrieval time, not a guaranteed date of the underlying OSM edits.

Run the complete experiment using the saved inputs:

```sh
georesilience validate crucitti --out results/ticket15-crucitti --offline --jobs 2 --max-memory-gb 1
```

You may omit `--offline` and `--download-only` to download missing inputs and analyse in one command.
The four-city live run is manual, outside the default test suite. Information centrality is exact
for **every** cleaned node; large samples can be expensive. There is no candidate-only fallback.
AP2's Ahmedabad sample had 2,870 nodes, and modern OSM sample sizes need not match the paper.
Timestamped progress and per-city information runtimes help assess cost.

The focused workflow reuses cleaning, centralities and classification without running link damage,
attack/failure or reliability experiments. One-way restrictions are ignored **before** simplification
and largest-component selection, matching AP2's undirected analysis. Default intersection consolidation
is 15 m. In this experiment only, a dead-end change of at least 5% is reported as a warning rather
than stopping the run: the predefined tolerance is held fixed instead of being adjusted to get a
preferred result. Inspect these warnings before interpreting a city comparison. Ordinary `run`
retains its existing strict cleaning guard and directed component behavior.

A geometry-direction bug in the initial Ticket 15 implementation was corrected on 11 October
2026. Reverse arcs now have geometry aligned to their endpoints before consolidation. The initial
bug inflated some road lengths and physical-link counts. All four outputs were regenerated from
the same frozen inputs; classification verdicts and match counts were unchanged. Earlier outputs
are preserved and labelled superseded in `results/ticket15-crucitti-before-geometry-fix/`.
The corrected study still returns MISMATCH: framework information 0/4, AP2-reference information
1/4, and betweenness 2/4 in both. See TICKET_UPDATES for the audit and regression checks.

### Understand the two comparisons

`crucitti_report.txt` and `comparison.json` report these separately:

| Comparison | Information centrality | Betweenness fitting |
| --- | --- | --- |
| `framework_inverse_distance` | Existing `mean(1/d)` efficiency, in 1/metres | Existing Ticket 07 rules, including the half-normal body labelled `gaussian` |
| `ap2_spatial` | AP2's dimensionless `mean(d_E/d)` spatial efficiency | Exponential versus AP2's Gaussian-shaped cumulative curve, using a separate Rayleigh body fit |

For both information calculations, deactivate a node's incident edges, retain all original nodes
and coordinates, and calculate `(E_before - E_after)/E_before`. Self-pairs are excluded;
unreachable pairs contribute zero; the denominator stays `N*(N-1)`. Both efficiencies share
each removal's Dijkstra blocks, so the additional convention does not duplicate shortest-path runs.

AP2's Gaussian-shaped cumulative curve `exp(-x*x/(2*sigma*sigma))` is a Rayleigh survival function,
which differs from the half-normal survival function used by Ticket 07. The reference comparison
uses positive finite observations, zero-location exponential/Rayleigh MLEs, and the project's
10-AIC-unit evidence threshold. Fewer than 50 positives or fewer than three distinct positives
give an inconclusive result. Information uses Ticket 07's modern power-law tail rules in both
comparisons. These statistical decisions are **not a reconstruction of the paper's original fitting
procedure**, and no bootstrap goodness-of-fit test is performed. Ticket 07 itself is unchanged.

Expected information / betweenness shapes are `power_law` / `exponential` for Ahmedabad and Cairo,
and `exponential` / `gaussian` for Los Angeles and Richmond. Each comparison gets its own status:
**PASS** requires at least 3/4 information matches **and independently** 3/4 betweenness matches.
This threshold belongs to our project, not to AP2. The report's first line and root JSON `status`
describe the **framework** comparison; check the separate AP2-reference status too.
`MISMATCH` is a research finding and exits successfully (code 0). Download, input or calculation
errors exit nonzero and do not create a new completed aggregate report. Inconclusive verdicts
are counted explicitly and do not count as matches; they do not mean the computation failed.
The network label can also be `inconclusive` when information has a `gaussian` verdict:
the project only maps power-law and exponential information shapes to a network class.

`alpha_density` is the fitted information density exponent. AP2's 2.74 (Ahmedabad) and 2.63 (Cairo)
are **CCDF** exponents; the ideal continuous relationship is `gamma_ccdf = alpha_density - 1`.
Exponents are context, not exact pass targets, and are shown in the comparison table only for
power-law verdicts. Modern street data, approximate boundaries, preprocessing and fitting choices
can all change the observed shapes. Neither PASS nor MISMATCH proves a universal city classification.

### Inspect and rerun Ticket 15

- Read `crucitti_report.txt` for the two expected-versus-obtained tables, separate match counts
  and inconclusive counts. `comparison.csv` has eight rows: four cities × two conventions.
- Each `<city>/report.txt` includes cleaning counts, warnings, full coverage, both baseline
  efficiencies, verdict reasons and information runtime. Its `summary.json` includes complete
  fit evidence and the frozen input manifest.
- Open `<city>/network.gpkg` in QGIS. Nodes have `betweenness`, `information_inverse` and
  `information_spatial`, plus other centralities; edges include length and edge betweenness.
  Compare the topology with `inputs/<city>/input.gpkg` to see simplification and consolidation.
  `centralities.csv` supplies the same node values for independent inspection.
- Open `figures/information_ccdf.png` for the four cities under each convention, and
  `figures/betweenness_ccdf.png` for semilog curves against betweenness and betweenness squared.
  An exponential cumulative curve is straight in the former; AP2's Gaussian-shaped curve is
  straight in the latter. Plots condition on positive scores; dropped zeros are counted in JSON.
- A particularly important exact test is the three-node right-angle path with road lengths
  3 and 4: inverse efficiency `61/252`, spatial efficiency `19/21`; endpoint information losses
  differ between conventions, while isolating the middle node gives loss 1 in both.

```sh
# Rerun the same frozen experiment; aggregate outputs and figures are replaced.
georesilience validate crucitti --out results/ticket15-crucitti --offline --overwrite --jobs 2

# Separate, predefined sensitivity experiment; original inputs and results are preserved.
georesilience validate crucitti --out results/ticket15-no-consolidation \
  --inputs results/ticket15-crucitti/inputs --offline --consolidation-m 0 --jobs 2

PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_crucitti.py
```

`--consolidation-m 0` disables consolidation; positive values set a fixed tolerance. Keep sensitivity
results separate and do not select settings based on agreement. `--no-figures` suppresses plots.
Further validation recommendations are tracked in
[plan/TEST_RECOMMENDATIONS.md](plan/TEST_RECOMMENDATIONS.md#15--crucitti-comparison).

### Street types and consolidation sensitivity

The offline inspection script compares the corrected 15 m run with a separately completed
zero-consolidation run, using the same frozen inputs. It checks that other run settings and
input hashes match, verifies full information coverage, and leaves source results untouched.

The completed comparison returned **MISMATCH at both settings**, with unchanged match counts:
framework information **0/4**, AP2-reference information **1/4**, betweenness **2/4** in both.
Individual information verdicts nevertheless changed:

| City | Nodes: 15 m → 0 m | AP2-reference information: 15 m → 0 m |
| --- | --- | --- |
| Ahmedabad | 436 → 726 | gaussian → gaussian |
| Cairo | 547 → 2,166 | power_law → power_law |
| Los Angeles | 441 → 2,957 | gaussian → power_law |
| Richmond, CA | 343 → 955 | power_law → gaussian |

Framework information changes the same way in Los Angeles/Richmond; Cairo remains exponential
under that convention. Betweenness remains exponential in every city under both comparisons.
The zero-consolidation experiment took approximately **34 minutes** with two workers and a
1 GiB configured budget on the verification environment; exact all-node information dominated.

Los Angeles' new AP2-reference power-law verdict concerns a tail of **98/2,957 nodes**, despite
the full-body half-normal fit beating exponential. Ticket 07's ordered rules give a qualifying
tail priority. Richmond's new power-law candidate loses to lognormal and is rejected; its body
favours half-normal. These verdicts show preprocessing sensitivity, not historical city classes.
The comparison does not establish consolidation as the sole cause of disagreement.

Regenerate the inspection artifacts after both runs have finished:

```sh
python examples/inspect_ticket15_samples.py \
  --comparison results/ticket15-no-consolidation --out results/ticket15-inspection

# Inspection of the baseline alone is also supported: omit --comparison.
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_crucitti.py tests/test_crucitti_inspection.py
```

Inspect `results/ticket15-inspection/`:

- `report.txt` and `consolidation_comparison.csv`: graph size, length, degree, boundary leaves,
  both information conventions and distribution verdicts for each setting. Compare distributions;
  consolidated node IDs and junction populations differ between runs.
- `raw_windows.png`: street types in the four frozen 1609 m squares, with centres, north and scale.
  `topology_comparison.png` shows cleaned networks side by side at exactly the same extent.
- `centrality_comparison.png`: overlaid positive-score CCDFs for both information conventions
  and betweenness in each city, labelled by verdict (betweenness uses the AP2-reference fit).
  Different node populations and normalisations also affect score magnitudes; inspect shape as
  well as horizontal shifts. Zeros are excluded from these conditional curves, as in the primary plots.
- `street_types.csv`: count and length shares for raw inputs and both cleaned outputs.
  Raw counts are **unsimplified physical segments**, not counts of streets or intersections.
  Opposite arcs are grouped; a mixed highway tag contributes once to its combined class.
- `raw_access.csv` and `raw_service.csv`: retained access and service subtype tags.
  An unspecified tag means unknown. Highway categories alone do not determine legal access.
- `windows.json`: sample bounds, coordinate systems, verified input hashes and inspection statistics.
  `audit_manifest.json` records source-run settings, summary/boundary hashes and the script hash.
  `consolidation_clusters.csv`: original junction IDs, cluster diameter and displacement.
- `<city>.gpkg`: QGIS layers `raw_edges`, `raw_nodes`, `boundary`, `clusters_15m`,
  `edges_15m`, `nodes_15m`, `edges_0m`, `nodes_0m`. Categorise raw edges by `highway` or `category`;
  label/sort cluster points by `merged_junctions` or `max_displacement_m`. Toggle the two cleaned
  layers to inspect changes. For geographic context, add QGIS's OpenStreetMap XYZ basemap and
  compare the square with AP2 Figure 2; the historical windows have not been georeferenced.

The street audit found the following shares of **raw physical network length**:

| City | Path/cycle categories | Service roads | Largest retained 15 m cluster: junctions / diameter |
| --- | --- | --- | --- |
| Ahmedabad | 1.12% | 5.47% | 22 / 173.5 m |
| Cairo | 6.19% | 11.35% | 280 / 668.7 m |
| Los Angeles | 57.82% | 14.27% | 77 / 400.7 m |
| Richmond, CA | 17.49% | 21.21% | 47 / 196.7 m |

Path/cycle categories here mean `footway`, `pedestrian`, `path`, `steps`, `cycleway` and `corridor`.
OSMnx's `all` filter also includes explicitly private-access ways in these snapshots. Frozen
GraphML does not retain `footway`/`sidewalk` subtype tags, so sidewalk duplicates cannot be fully
separated from other paths using these files. This matters particularly for Los Angeles, where
parallel path lines are visible around the grid. It does **not** justify discarding all walking
streets: AP2 also discusses pedestrian networks, notably Venice.

The 15 m tolerance is a **node buffer radius**, not a maximum merge diameter or displacement.
Connected overlaps can merge transitively, collapsing a much larger area into one centroid.
The Cairo map's large spoke-like cluster is one such case. No-consolidation isolates the effect
of this preprocessing choice; street-type effects require a separate, predefined filtering study.
Window inspection shows irregular street patterns in Ahmedabad/Cairo and grids in Los Angeles/
Richmond, but appearance does not establish a distributional verdict or verify a historical window.

### Published historical AP2 networks

The authors' [textbook dataset page](https://www.complex-networks.net/datasets.html#chap8)
provides [cities.zip](https://www.complex-networks.net/datasets/cities.zip). Its README cites
Crucitti, Latora and Porta, *Centrality measures in spatial networks of urban streets*,
Physical Review E **73**, 036125 (2006), and Latora, Nicosia and Russo,
*Complex Networks: Principles, Methods and Applications* (2017). Cite both when using the data,
as requested by the archive. It contains 20 graphs, including AP2's 18 cities; we analyse the
same four cities as the modern OSM comparison.

These four graphs match AP2's node/edge counts exactly. Their road-length means and standard
deviations match Table I of the authors' [companion Chaos paper](https://www.udsu-strath.com/wp-content/uploads/2010/06/PA2006_06new1.pdf)
to its published precision:

| City | Nodes | Roads | Mean length (m) | Standard deviation (m) |
| --- | ---: | ---: | ---: | ---: |
| Ahmedabad | 2,870 | 4,387 | 27.59 | 17.03 |
| Cairo | 1,496 | 2,255 | 37.47 | 25.42 |
| Los Angeles | 240 | 340 | 113.87 | 64.86 |
| Richmond | 697 | 1,086 | 57.65 | 45.49 |

This is the authors' published graph release. It was released with the 2017 textbook;
the original GIS project, curved road shapes, geographic registration and original fitting
software are not included. Provenance/counts/length statistics support its correspondence
to AP2, without claiming bit-for-bit identity with an unavailable 2006 working directory.

From the repository root with your project environment activated:

```sh
mkdir -p results/ticket15-published-download
curl -fL https://www.complex-networks.net/datasets/cities.zip \
  -o results/ticket15-published-download/cities.zip

python -m georesilience.published_cities \
  --archive results/ticket15-published-download/cities.zip \
  --out results/ticket15-published-rerun --jobs 2 --max-memory-gb 1
```

For an offline rerun, use `results/ticket15-published/inputs/cities.zip` instead of downloading.
The output directory must be new or empty. The pinned archive SHA-256 is
`29552883de03463dbf5c2b2df69c1583d30014f83477c355fd7cd7eb1e9c3c61`;
an altered archive is refused. Exact information centrality visits every node and can take
tens of minutes. The existing modern OSM outputs are preserved.

The loader cross-checks `.net` connectivity against `_edge_info.txt` coordinates/lengths,
including multiplicity, finite values, positive lengths, consistent node positions, paper
counts and length statistics. Source edge labels repeat in Ahmedabad/Cairo, so file-row
identities preserve all roads. Analysis uses **no cleaning, reprojection, rescaling,
consolidation or component selection**. Shortest paths use the shortest parallel road,
consistently with the existing centrality implementation. Coordinates keep the source's
approximately 1,560 m span, rather than being stretched to the modern 1,609 m square;
small coordinate/road-length rounding differences are retained.

Read `results/ticket15-published/crucitti_report.txt` and `comparison.csv` for independent
framework inverse-distance and AP2 spatial comparisons. Each city has `report.txt`,
`summary.json`, `centralities.csv` and `network.gpkg`. `figures/` contains combined information
and betweenness CCDFs. `inputs/` preserves the archive, extracted four-city text files,
citation README, file hashes and validation findings.

Information still uses Ticket 07's statistical rules; AP2 reference betweenness compares
exponential with Rayleigh, whose survival curve has the paper's Gaussian shape. A residual
mismatch on the published graphs concerns calculation/statistical differences rather than
the modern OSM window, filter or consolidation. Relative AIC/likelihood evidence alone is
not a goodness-of-fit test. Do not retune thresholds to force historical agreement.

The completed published-data run returned **MISMATCH under both conventions: information 2/4,
betweenness 3/4**. Ahmedabad/Cairo information is `power_law`; Los Angeles/Richmond information
is `gaussian` under the project's half-normal body rule, rather than AP2's `exponential`.
Reference betweenness matches Ahmedabad, Cairo and Los Angeles; Richmond is `exponential`.
Framework Richmond betweenness abstains. Both planned-city network labels are `inconclusive`.
The unchanged information body models fix location at zero and fit full positive samples;
this differs from reconstructing the paper's cumulative curve fits. Support/offset and fitting
range deserve investigation before changing the classifier.

There is useful numerical agreement: AP2 spatial information gives CCDF exponents **2.734**
for Ahmedabad and **2.666** for Cairo (paper ≈2.74/2.63). Cairo/Richmond spatial-information
Gini values **0.22794/0.19281** round to the paper's **0.23/0.19**. Independent NetworkX
calculations on the original tables match both baseline efficiencies and three isolated-node
scores per city within 3.30e-15; planned-city betweenness matches within 2.78e-17. Read
`numerical_verification.json`, `independent_references.json`, `betweenness_verification.json`
and `archive_inventory.json` alongside the reports. These verify data/calculations separately
from the statistical labels. Full information coverage is 5,303 nodes, taking about 22 minutes
on the two-worker run; timing varies by machine.

For QGIS, open one city's `network.gpkg` in a **separate project** and add `nodes` and `edges`.
They use an engineering CRS for local metre coordinates, with no known geographic registration;
do not overlay them on OSM. Different cities have overlapping local coordinate ranges.
Displayed edges are straight endpoint chords; `length_m` is the authors' road length used
by Dijkstra. QGIS `$length` measures the chord and can differ. In this adapter the inherited
`osm_way_ids` field contains source-table row identities, not OSM identifiers. Original
`edge_num` labels remain in the saved tables. All roads are analysed as undirected.

Offline regression tests:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_published_cities.py tests/test_crucitti.py tests/test_crucitti_inspection.py
```
