# GeoResilience

GeoResilience analyzes road network structure and resilience. Tickets 01 and 02 provide input,
cleaning, physical road links, degree metrics, and auditable outputs. Later analysis tickets are
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
| `network.gpkg` | Projected `nodes` and physical-link `edges` layers; degree metrics on nodes |
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
