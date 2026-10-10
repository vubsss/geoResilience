# Ticket implementation status

- [x] **01 — Tracer bullet: config → graph → degree → outputs** — implemented. See [ticket](plan/tickets/01-tracer-bullet.md).
- [x] **02 — All inputs + full cleaning** — completed, tested and manually verified by you.
- [x] **03 — Exact path-based centralities** — completed, tested and manually verified by you.
- [ ] **04 — Screening and candidates** — not started.
- [ ] **05 — Single-link criticality + information centrality** — not started.
- [ ] **06 — Attack vs failure curves** — not started.
- [ ] **07 — Distribution classification** — not started.
- [ ] **08 — Failure probabilities** — not started.
- [ ] **09 — Connectivity reliability** — not started.
- [ ] **10 — Travel-time reliability** — not started.
- [ ] **11 — Hansen accessibility (uniform masses)** — not started.
- [ ] **12 — WorldPop population** — not started.
- [ ] **13 — Zone aggregation** — not started.
- [ ] **14 — Scorecard and final report** — not started.
- [ ] **15 — Crucitti replication** — not started.
- [ ] **16 — Ada runbook** — not started.

## Ticket 01 manual run

1. Install the package: `python -m pip install -e .`.
2. Create `my.yaml` as shown in [README.md](README.md), updating `input.path` to an existing OSMnx GraphML file.
3. Run `georesilience --version`, then `georesilience run --config my.yaml`.
4. Check `results/network.gpkg` (layers `nodes` and `edges`), `summary.json`, `report.txt`, `run_config.yaml`, and `figures/degree_hist.png`.
5. Try an invalid YAML key to confirm validation names it. Try the same run again to confirm a non-empty output folder is refused; use `--overwrite` to rerun.
6. To test the output override, run `georesilience run --config my.yaml --out another-results`.

## Ticket 02 — All inputs + full cleaning

Ticket **02** was implemented on **10 October 2026** and is **completed and manually verified
by you**, as confirmed on **10 October 2026**.

### Changes

- Added validated input configuration for place names, boundary polygons (GeoJSON/GPKG), WGS84
  bboxes, OSM XML and GraphML; added `network` and `cleaning` defaults.
- Added source adapters, access/vehicle tag retention, study-boundary WKT and download metadata.
  Point-only place names receive an actionable error directing you to a bbox/polygon.
  Downloads honor OSMnx network types and custom filters. GraphML is marked `as-provided`.
- Added the XML `drive` exclusions for non-drivable highways, private access, motor restrictions
  and area features; other XML network types stay `as-provided` with a warning.
- Added simplification, metric projection, optional intersection consolidation with dead ends,
  the strict degree-1 preservation guard, and largest strongly connected component selection.
- Reused physical-link grouping for cleaning statistics and final outputs. Reports show nodes,
  links and kilometres at each stage, component losses, the >5% clipping warning and the permanent
  boundary-effect warning. Both degree metrics and exported layers use the cleaned node set.
- Kept resolved configs reusable by ignoring their output-only `versions` block during loading.
- Added offline fixtures, opt-in live source tests, demo inputs/configs and supported-input docs
  with cleaning sketches. Ordinary tests reject HTTP requests; live tests require `--network`.

Implementation detail: loaders request `simplify=False`, then simplify explicitly. This allows
real raw/simplified statistics rather than labeling an already simplified graph "raw", and applies
XML filtering before tags are aggregated across road segments. The final graph is always simplified.
The extra XML `filtered` row makes its road exclusions visible separately from simplification.
The ASCII sketches in README illustrate the design; the plan files did not contain the referenced
before/after sketches.

### Manual verification

Run these commands **from the repository root**. If you already installed dependencies in an
active environment, skip setup. The verification environment created during implementation is
`/tmp/georesilience-ticket02-venv`; activate it with
`source /tmp/georesilience-ticket02-venv/bin/activate` while it remains available.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e . pytest
python examples/create_ticket02_demo.py
georesilience --version
georesilience run --config examples/ticket02-graphml.yaml --overwrite
georesilience run --config examples/ticket02-xml.yaml --overwrite
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest
```

1. Read `results/ticket02-graphml/report.txt`. Expect raw **8 nodes / 8 links**, final
   **5 nodes / 4 links**, **4 dead ends before and after**, and **0 dropped components**.
2. Open `results/ticket02-graphml/network.gpkg` in QGIS. The `nodes` layer should contain one
   central node with `degree=4`, plus four approach endpoints with `degree=1`. The `edges` layer
   should contain four physical links, in a projected metric CRS.
3. Change a copy of `examples/ticket02-graphml.yaml` to `cleaning.consolidate: false` and run
   `georesilience run --config your-copy.yaml --out results/ticket02-unconsolidated`.
   Expect **8 nodes / 8 links**, showing the original four junction nodes.
4. Read `results/ticket02-xml/report.txt` and inspect its GPKG: **4 raw links**, **1 filtered/final
   link**, **2 final nodes**, OSM way **103**. Footway, service and private residential roads vanish.
5. Inspect `summary.json.cleaning` alongside the table and the GPKG counts. XML/GraphML should
   have null `osm_download_utc` and `study_boundary_wkt`. GraphML should show `as-provided`;
   drive-filtered XML should show `drive`. Inspect `run_config.yaml` for resolved cleaning defaults.
6. For a live download, run `georesilience run --config examples/ticket02-bbox.yaml`.
   Its summary should include a UTC download timestamp and WGS84 study-boundary WKT.
   Place/polygon config snippets are in [README.md](README.md). A place must have a mapped polygon
   boundary; the place integration fixture uses Piedmont (about 4 km²), while polygon/bbox use
   a small Hyderabad area (about 1 km²).
7. Live source integration tests:
   `PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest --network -m network`. These need internet
   access and available OSM services. If the real area triggers the dead-end guard, reduce
   `cleaning.tolerance_m` or disable consolidation and inspect the area before proceeding.

Add `--overwrite` when rerunning into a non-empty results folder. To reuse resolved settings:

```sh
georesilience run --config results/ticket02-graphml/run_config.yaml --out results/ticket02-repeat
```

### Verification results

- Offline suite: **19 passed, 3 skipped** (the skipped tests require `--network`).
- Live OSM integration suite: **3 passed**, covering place, polygon and bbox. Place used Piedmont;
  polygon and bbox used the small Hyderabad boundary. The initial point-only Gun Foundry fixture
  was replaced, and an offline regression test now checks the actionable place-boundary error.
- Both documented demo CLI runs completed and wrote all five output artifact types.
  GraphML: **5 final nodes, 4 links, 4 dead ends preserved**. XML: **2 final nodes, 1 link**, way 103.
- `georesilience --version` returned `0.1.0`; `git diff --check` passed.
- Verification used Python **3.13.3** and OSMnx **2.1.1** in the temporary environment above.
  This machine's ROS environment auto-loads unrelated pytest plugins, so verification cleared
  `PYTHONPATH` and set `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. The same flags are in the manual commands.
- The generated demo inputs are in `data/ticket02-demo/`, and outputs are in
  `results/ticket02-graphml/` and `results/ticket02-xml/`. These generated files are gitignored;
  regenerate them with the example script when needed.

## Ticket 03 — Exact path-based centralities

Ticket **03** was implemented on **10 October 2026** and is **completed and manually verified
by you**, as confirmed on **10 October 2026**.
Tickets 04–16 have not been started.

### Changes

- Added exact metric **closeness, straightness, node betweenness and physical-link edge
  betweenness**, plus **global efficiency**, on the cleaned undirected node set.
- Added a minimum-length analysis graph shared by shortest paths and betweenness. For each
  endpoint pair, the shortest physical link supplies the analysis edge; equal-length ties use
  the lowest `link_id`. Unselected parallel links get 0; self-loops retain null edge betweenness
  and are excluded from analyses and statistics.
- Added the reusable CSR shortest-path engine with source subsets, reducers, directed/cutoff
  support, memory-based row chunks, joblib process workers, and a dense-matrix fit helper.
  Workers return reduced vectors rather than distance blocks. Closeness, straightness and
  inverse-distance contributions share one pass. Optional node weights are supported by the
  reducer/efficiency aggregator for later population work; the current CLI uses uniform weights.
- Added exact weighted NetworKit betweenness, with its raw ordered-pair counts normalized to the
  ticket definitions. NetworKit threads follow `analysis.n_jobs`. Positive finite non-loop
  lengths are validated before computation.
- Resolved resource settings from `SLURM_CPUS_PER_TASK`/CPU count and half of available RAM when
  `auto` is selected. Numeric memory values use GiB. Recorded effective settings, budget bytes,
  chunk rows and chunk count. Resolved configs retain reusable resource choices.
- Added the new GPKG columns, mean/median/p90/max summary statistics, stage runtimes, a report
  section and top 20 links table. Added three log-y empirical CCDFs and the edge-betweenness map.
  Overwriting a run with figures disabled removes this ticket's old figures as well.
- Added timestamped progress for shortest-path chunks and a heartbeat during long betweenness
  computations. `analysis.directed_centrality: true` raises `NotImplementedError` in the library
  and a clear CLI error before output files can be changed.
- Added known-answer demo graphs, matching input GeoPackages for QGIS, example configs, formula
  documentation, correctness/cross-reference tests and the opt-in 60,000-node benchmark.

### Formula check against the papers

Read page 2 of [AP2 — Centrality measures in urban networks](papers/AP2-centrality_measures_in_urban_networks.pdf).
Closeness, straightness and ordered-pair node betweenness match its definitions. **Global efficiency
follows the explicit Ticket 03 formula `mean(1/d)`**, measured in 1/metres. AP2 instead uses spatial
efficiency `mean(d_E/d)` in its information-centrality definition. This distinction is documented
in README; the ticket takes precedence as specified by the project design. No information
centrality calculation has been added in this ticket.

Convention note for later tickets: both means exclude self-pairs and use the denominator
`N * (N - 1)`; unreachable pairs contribute zero. Here `d` is shortest-path length and `d_E`
is straight-line distance between projected node coordinates. Ticket 03's efficiency has units
of **1/metres**, while AP2's spatial efficiency is **dimensionless**. They are different measures;
future information-centrality work and comparisons with AP2 must state which convention is used.

### Manual run and QGIS checks

From the repository root, activate your project environment. The existing temporary verification
environment can be used while available:

```sh
source /tmp/georesilience-ticket02-venv/bin/activate
python examples/create_ticket03_demo.py
georesilience run --config examples/ticket03-star.yaml --overwrite
georesilience run --config examples/ticket03-grid.yaml --overwrite
georesilience run --config examples/ticket03-path.yaml --overwrite
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest
```

For a fresh environment, follow the install instructions in [README.md](README.md).
The pytest flags isolate this machine's unrelated ROS plugins, as in ticket 02.

All three fixtures use **100 m roads**. Input GraphML fixtures are explicitly marked simplified
so that their known graph nodes survive loading. Consolidation is enabled, but their spacing
means no nodes are merged.

| Fixture | Expected result |
| --- | --- |
| Star, 5 nodes / 4 links | Hub `betweenness=1`; four leaves `betweenness=0` |
| Star | All four links `edge_betweenness=0.4` |
| Star | Hub `closeness=0.01`; leaf `closeness=4/700 ≈ 0.005714285714` |
| Star | Hub `straightness=1`; leaves approximately `0.853553390593` |
| Star | `summary.json.metrics.global_efficiency=0.007` |
| Grid, 9 nodes / 12 links | Centre (degree 4) `closeness=8/1200 ≈ 0.006666666667` |
| Collinear path, 5 nodes / 4 links | Every node `straightness=1` |

1. Open `results/ticket03-star/network.gpkg` in QGIS. Check the `nodes` attribute table for the
   three new columns and the `edges` table for `edge_betweenness`. Use **Graduated** symbology to
   colour nodes by `betweenness` or roads by `edge_betweenness`.
2. For original inputs, open `data/ticket03-demo/star-input.gpkg`, `grid-input.gpkg` or
   `path-input.gpkg`. Their edges include both travel directions, while output edges are physical
   links. Their geometry should match the respective outputs because no junctions merge here.
3. Inspect each run's `report.txt`, including "Centralities" and "Top 20 links by edge betweenness".
   Check `summary.json.metrics` and `summary.json.computation`. Runtimes can change on reruns.
4. Open `figures/closeness_ccdf.png`, `straightness_ccdf.png`, `betweenness_ccdf.png`, and
   `edge_betweenness_map.png`. Star links have equal importance, so their map colours/widths match.
5. For your own graph, reuse an existing ticket 02 config and select a new output folder with
   `--out results/my-centralities`. Existing ticket 02 inputs now gain the centrality columns.
6. To compare resource choices, copy a demo config and try `n_jobs: 4` with
   `max_memory_gb: 0.000001`, writing to a different output folder. Metric values should agree
   with the default example within floating-point tolerance; chunk counts/times may differ.

### Verification results

- Known answers: collinear path straightness, star betweenness, unit-grid centre closeness and
  two-node efficiency all passed.
- Five independent 200-node random spatial graphs matched NetworkX closeness, node and edge
  betweenness, and Floyd–Warshall efficiency within **1e-9**. Straightness was independently
  cross-checked as well. One versus four jobs and small versus large budgets agreed within
  **1e-12**.
- GPKG columns/null self-loops, JSON summaries, ASCII report/top links, all five figures,
  resolved settings, directed-flag errors and figure cleanup were verified.
- **60,000-node perturbed grid benchmark passed:** 8 jobs; **2 GiB** block budget;
  **260.03 seconds** total; **2.27 GiB** combined parent/worker peak RSS, below the **3 GiB** cap.
  Shortest paths took **61.24 s** and exact betweenness **198.53 s**. Fixture creation is excluded
  from timing; output writing/plotting are tested separately. Performance depends on hardware.
- The star, grid and path example CLI runs succeeded and produced the expected attribute values.
- Final regular suite: **36 passed, 4 skipped** (three live-network tests and the slow benchmark
  are opt-in). The benchmark was run separately and passed. `git diff --check` passed.
  Verification used Python **3.13.3**, SciPy **1.18.1** and NetworKit **11.2.2**.

The benchmark is skipped by default. To reproduce it (allow several minutes):

```sh
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest --slow -m slow -s
```
