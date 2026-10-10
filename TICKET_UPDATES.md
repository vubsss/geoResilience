# Ticket implementation status

- [x] **01 — Tracer bullet: config → graph → degree → outputs** — implemented. See [ticket](plan/tickets/01-tracer-bullet.md).
- [x] **02 — All inputs + full cleaning** — implemented and tested; awaiting your manual review.
- [ ] **03 — Exact path-based centralities** — not started.
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

Current ticket: **02**, implemented on **10 October 2026**, awaiting your manual review.
Tickets 03–16 have not been started.

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
