# GeoResilience

GeoResilience analyzes road network structure and resilience. Tickets 01–03 provide input,
cleaning, physical road links, exact centrality metrics, and auditable outputs. Later analysis tickets are
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
| `network.gpkg` | Projected `nodes` and physical-link `edges` layers; degree and centrality metrics |
| `summary.json` | Input, CRS, download time, applied type, boundary, cleaning counts and metrics |
| `report.txt` | ASCII network summary, cleaning table, component losses, warnings, degree histogram |
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
