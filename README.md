# GeoResilience

GeoResilience analyzes road network structure and resilience. Tickets 01–04 provide input,
cleaning, physical road links, exact centrality metrics, redundancy screening, and auditable outputs. Later analysis tickets are
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
| `summary.json` | Input, CRS, download time, applied type, boundary, cleaning counts and metrics |
| `report.txt` | ASCII network summary, cleaning, degree, centralities, redundancy and top-road tables |
| `run_config.yaml` | Resolved defaults and package versions; reusable as a run config |
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
joblib worker. A whole distance matrix is never cached. One chunk is the minimum even if the
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
| edges: `is_criticality_candidate` | Selected for full link-failure recomputation in later tickets |
| edges: `is_analytic_bridge` | Selected for analytic bridge handling instead of full recomputation |
| nodes: `is_articulation` | Removing this junction disconnects the undirected network |
| nodes: `artic_max_cut` | Surviving nodes outside the largest component after removing the junction |
| nodes: `is_info_candidate` | Selected for later information-centrality recomputation |

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
Candidate selection prepares tickets 05 and 11; damage and information-centrality scores are not
computed yet. The efficiency convention documented for ticket 03 remains unchanged.

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
