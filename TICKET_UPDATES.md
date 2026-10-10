# Ticket implementation status

- [x] **01 — Tracer bullet: config → graph → degree → outputs** — implemented. See [ticket](plan/tickets/01-tracer-bullet.md).
- [x] **02 — All inputs + full cleaning** — completed, tested and manually verified by you.
- [x] **03 — Exact path-based centralities** — completed, tested and manually verified by you.
- [x] **04 — Screening and candidates** — completed, tested and manually verified by you.
- [x] **05 — Single-link criticality + information centrality** — implemented and automatically tested; awaiting your manual verification.
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
Tickets 06–16 have not been started. Tickets 04 and 05 are documented below.

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

## Ticket 04 — Screening and candidates

Ticket **04** was implemented on **10 October 2026** and is **completed, tested and manually
verified by you**, as confirmed on **10 October 2026**. Tickets 02 and 03 remain completed and manually verified.
Ticket 05's implementation is documented below.

### Changes

- Added validated `criticality` settings with all six ticket defaults; counts and thresholds must
  be nonnegative. Resolved configs include these settings and remain reusable.
- Added physical bridge detection that preserves parallel roads. Contracted the non-bridge
  components into a weighted bridge tree to compute exact smaller-side node counts in one traversal.
- Added articulation flags and exact severity from a weighted block-cut tree. Here `artic_max_cut`
  means **surviving nodes outside the largest remaining component** after junction removal. It
  excludes the removed junction and measures nodes, not population. A four-leaf star's hub has
  severity 3; a six-node path's severities are `0, 1, 2, 2, 1, 0`.
- Preserved each physical link's original directed edge identities internally. Directed detours
  mask all edges of that link and retain slower parallel alternatives. Two-way links use the worse
  direction; one-way links use their existing direction. Known bridges directly receive infinite
  detours; other links use bidirectional Dijkstra on filtered graph views.
- Parallelized detour batches with joblib, sharing each minimal directed graph once per worker.
  `analysis.n_jobs` controls workers, capped by the number of links needing searches. Graph/process
  overhead is additional to the shortest-path block memory budget.
- Added deterministic full-recompute link, analytic bridge, and node candidate sets for future
  tickets 05/11. Detour ties use edge betweenness then `link_id`; node ties use graph node order.
  Selection counts overlap and do not sum to the union size.
- Exported all requested edge/node fields, plus explicit `is_criticality_candidate` and
  `is_analytic_bridge` flags. These distinguish membership under `all: true`, where a road included
  only by that setting can have an empty `candidate_reason`. Analytic bridges remain excluded from
  full recomputation even in this mode.
- Exported absent alternatives as null `detour_ratio` plus `detour_none=true`. Self-loops receive
  null numeric screening values, false flags and empty reasons, and are excluded from summaries.
- Added `summary.json.metrics.redundancy`, screening stage runtimes, report statistics/top-road
  tables, and `figures/redundancy_map.png` (red bridges, orange directed bridges, grey other roads).
  Figure cleanup on overwrite covers the new map too. Empty finite-detour statistics use JSON null.
- Added four reproducible examples with GraphML and input GeoPackages for QGIS; generated inputs
  and results are ignored, while scripts and YAML configs are tracked as source.

The **efficiency convention remains unchanged**: Ticket 03 uses inverse-distance efficiency
`mean(1/d)` in 1/metres, while AP2 uses spatial efficiency `mean(d_E/d)`, dimensionless.
Ticket 04 computes neither damage nor information centrality; it selects candidates for those
later calculations. The existing convention note above still applies to tickets 05 and 11.

### Manual run and QGIS checks

From the repository root, activate your environment. While the temporary verification environment
is available, you can use:

```sh
source /tmp/georesilience-ticket02-venv/bin/activate
python examples/create_ticket04_demo.py
georesilience run --config examples/ticket04-path.yaml --overwrite
georesilience run --config examples/ticket04-ring.yaml --overwrite
georesilience run --config examples/ticket04-directed-ring.yaml --overwrite
georesilience run --config examples/ticket04-parallel.yaml --overwrite
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

For a fresh environment, follow the install commands in [README.md](README.md).
The demo graphs are declared simplified, with consolidation disabled, so their known topology
is preserved. All roads are 100 m except the 150 m backup road in the parallel example.

| Demo | Expected values |
| --- | --- |
| Path | 6 nodes / 5 bridges; cut-side counts along the path `1, 2, 3, 2, 1`; fractions counts / 6 |
| Path | All detours null with `detour_none=true`; bridge fraction and bridge length fraction both 1 |
| Path candidates | Threshold 2: 4 `analytic_bridge` roads and 1 `large_bridge` full-recompute road |
| Two-way ring | 6 nodes / 6 roads; no bridges or articulations; every detour 5; median/p90/p99 all 5 |
| Ring candidates | Top-k limits 2: 2 full-recompute roads, with both `betweenness;detour` reasons |
| Directed ring | No undirected bridges; 5 directed bridges; their detours null and `detour_none=true` |
| Directed ring | One-way road 0→1 has finite detour 5; with the example's top-k settings, 6 candidate roads |
| Parallel | 2 nodes / 2 physical roads, neither a bridge; detours 1.5 (100 m road) and 2/3 (150 m road) |
| All examples | All nodes have `is_info_candidate=true` under the default 5000-node threshold |

1. Read each `results/ticket04-*/report.txt` and `summary.json.metrics.redundancy`. Check the
   Redundancy section, candidate counts, and both top-20 road tables against the expected values.
2. Open the corresponding `network.gpkg` in QGIS and select both layers. In `edges`, inspect
   `is_bridge`, `cut_side_nodes`, `cut_side_frac`, `detour_ratio`, `detour_none`, `is_directed_bridge`,
   `candidate_reason`, `is_criticality_candidate`, and `is_analytic_bridge`.
   In `nodes`, inspect `is_articulation`, `artic_max_cut`, and `is_info_candidate`.
3. Open `figures/redundancy_map.png`: the path is red, the two-way ring and parallel roads grey,
   and five directed-ring segments orange. The remaining directed-ring segment is grey.
4. The original input copies `data/ticket04-demo/*-input.gpkg` open directly in QGIS. Each two-way
   physical road has two coincident directed input edges; the output combines them into one road.
   The 150 m backup road is curved so you can see it separately from the straight 100 m road.
5. Understand the directed-ring result: its one-way segment permits 0→1 but lacks 1→0. Closing
   any other road forces an alternative through that missing direction, so those five roads are
   directed bridges. Closing the one-way road still leaves 0→1 reachable around the other side.
6. To test complete selection, copy the ring YAML and set `criticality.k_betweenness: 0`,
   `criticality.k_detour: 0`, and `criticality.all: true`. Run to a new output directory using
   `--out results/ticket04-all`. Expect 6 road candidates and 6 node candidates, even though
   road reasons are empty. On the path, analytic bridges stay excluded from full recomputation.
7. To test node screening, use a ring config with `exact_info_max_nodes: 0`, `k_nodes: 2`,
   and `all: false`. Expect 2 node candidates. To rerun resolved settings, pass a run's
   `run_config.yaml` with `--out` pointing to a different directory.

### Verification results

- Tree and star bridge cuts/articulation severity, six-link ring detours, both one-way orientations,
  parallel alternatives, self-loop exclusions, selection thresholds, ties and `all` mode passed.
- Five **205-node random spatial graphs** (200 spatial nodes plus a five-node branch) matched
  independent copy-and-remove component counts and directed NetworkX Dijkstra detours. These
  fixtures include one-way edges, parallel roads, bridges and articulations. Finite ratios agreed
  within **1e-12**; no-alternative and directed-bridge flags matched exactly.
- Node removal severity matched brute force. A separate 80-node path verified the top-50
  articulation union with node-betweenness candidates. Serial and two-worker results agreed,
  including repeated worker-pool runs on different graphs.
- GeoPackage fields/nulls/flags, JSON without nonfinite values, resolved config round-tripping,
  ASCII report sections/tables, and the new PNG passed. All four example CLI runs succeeded.
- Ticket 04 tests: **11 passed**. Full regular suite: **47 passed, 4 skipped** in **167.08 s**.
  The skipped tests are the three opt-in live-network tests and the Ticket 03 slow benchmark;
  neither was rerun for this ticket. `git diff --check` passed. Verification used the existing
  Python **3.13.3** / OSMnx **2.1.1** environment.
- You confirmed that you manually checked the outputs on **10 October 2026**. Ticket 04 is complete.

## Ticket 05 — Single-link criticality + information centrality

**Current ticket: 05.** Implemented on **10 October 2026**; automated verification is complete.
**Your manual verification is pending.** Tickets 02, 03 and 04 remain completed and manually verified.
Tickets 06–16 have not been started.

### Changes

- Added exact independent closure experiments for every full-recompute candidate and analytic
  bridge selected in Ticket 04. Closing a physical road removes all of its directed edges.
- Added reusable `ActiveEdgeGraph` and `AffectedSourceRecompute` machinery for Ticket 11. Arcs
  are sorted once; each active-mask rebuild takes O(m), retaining the shortest **surviving**
  parallel edge. Junction isolation keeps original node indices and N.
- Added the exact affected-source shortcut using reversed endpoint Dijkstra runs and relative
  tolerance `1e-9`. Only those sources' changed distance rows are recomputed. Tied paths may
  select additional rows without changing the exact result. Cutoff and reducer APIs are available
  for later accessibility work.
- Added automatic float64 baseline caching when the matrix plus workspace fit the memory budget.
  A temporary memory map shares distances with workers without repeated matrix copies. The code
  checks temporary disk space and falls back to recomputation when needed. Temporary caches are
  cleaned on completion/error; cache mode/bytes and remaining workspace are recorded in summary
  computation metadata. No generated cache path enters the resolved YAML.
- Added analytic bridge damage from the cross-cut contributions, using forward/reversed paths
  from the smaller side or cached row/column views. No full modified-network run is needed.
- Added all seven edge fields: `eff_drop`, `disc_pair_frac`, `extra_km_total`, `affected_pairs`,
  `extra_m_mean_affected`, `damage_method`, and `crit_rank`. Rankings use descending efficiency
  loss, then disconnected-pair fraction, then ascending `link_id`.
- Added exact `information` for candidate nodes by removing every incident edge on the undirected
  analysis graph and recomputing all-pairs efficiency in chunks. N and its normalization remain
  unchanged. Source chunks are parallelized without nested per-node workers.
- Added optional node weights to library efficiency, disconnected-pair and information aggregates.
  Weighted pairs use `W_i * W_j` and the original distinct-pair weight sum. Only uniform-weight
  CLI columns are written here; population inputs/exports remain Ticket 12 work.
- Added criticality/information summary sections, counts by method, top 20 roads, independent
  closure totals, baseline efficiencies, coverage and stage runtimes. Added ASCII report sections,
  top-road details and `figures/critical_links_map.png` for up to 50 ranked roads. The new map uses
  explicit spatial bounds and an adaptive aspect ratio so collinear paths remain visible.
- Added timestamped link/node counts and estimated remaining time, plus heartbeat logs for long
  stages. Removal reducers conservatively budget eight float64 blocks per worker. Graph/process
  overhead and the minimum one-row exception remain additional to the block budget.
- Added four example inputs/configs and QGIS input GeoPackages. Generated inputs/results are
  ignored; generator scripts and example YAMLs are source files.

`damage_method=full` names the ticket's full-recompute category; its implementation uses the exact
affected-source shortcut. `analytic` identifies the separate bridge formula. Self-loops and
unevaluated roads retain null damage fields/method/rank; non-candidate nodes retain null information.
An evaluated road can legitimately have zero damage, as the longer parallel road example shows.

### Definitions and efficiency convention

- Link experiments use the **directed** graph by default. `analysis.directed_removal: false`
  explicitly selects undirected closure experiments; the report/summary state which mode was used.
  The directed baseline in `metrics.criticality.baseline_efficiency` can differ from Ticket 03's
  undirected `metrics.global_efficiency`. Information centrality always uses the undirected graph.
- Both efficiency and information follow the **inverse-distance** convention `mean(1/d)`, in
  1/metres. Page 2 of [AP2](papers/AP2-centrality_measures_in_urban_networks.pdf) confirms the
  junction-deactivation operation and relative-loss form, but uses **spatial efficiency**
  `mean(d_E/d)`, dimensionless. Ticket 05 follows the project's explicit efficiency formula;
  these information scores are not numerical replications of AP2's spatial-efficiency scores.
- Original N, weights and distinct-pair denominators are kept after every experiment. Unreachable
  pairs contribute zero efficiency. Junction deactivation isolates the node instead of deleting it.
- Extra distance counts only pairs reachable **before and after** the closure; `affected_pairs`
  counts the ones whose distance increased. Disconnected trips are excluded from both. A bridge
  therefore has zero extra distance/affected pairs and null `extra_m_mean_affected`.
- Ordered pairs count both A→B and B→A. These metrics use structural trip pairs rather than traffic
  demand. Relative losses are undefined/null when baseline efficiency is zero, and have no rank.
- Summary totals add independent single-road experiments, potentially counting the same trip in
  several experiments. They do not describe simultaneous closures.

### Manual run and QGIS checks

Run from the repository root in your environment. The existing temporary verification environment
can be activated while available:

```sh
source /tmp/georesilience-ticket02-venv/bin/activate
python examples/create_ticket05_demo.py
georesilience run --config examples/ticket05-ring.yaml --overwrite
georesilience run --config examples/ticket05-path.yaml --overwrite
georesilience run --config examples/ticket05-star.yaml --overwrite
georesilience run --config examples/ticket05-parallel.yaml --overwrite
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

For a fresh environment, follow [README.md](README.md). These fixtures are marked simplified and
disable consolidation. They use 100 m roads, plus a 150 m backup in the parallel example.
All nodes and roads are selected; `all: true` still leaves analytic bridges in the analytic set.

| Demo | Expected road/junction values |
| --- | --- |
| Ring: 4 nodes / 4 roads | Every road: `eff_drop=2/15 ≈ 0.1333333333`, disconnected fraction 0 |
| Ring | Extra 0.4 km over 2 ordered pairs, mean 200 m; method `full`; ranks use `link_id` order |
| Ring nodes | All four have `information=0.5` |
| Path: 4 nodes / 3 roads | Middle road: `eff_drop=7/13 ≈ 0.5384615385`, disconnected fraction `2/3`, rank 1 |
| Path | End roads: `eff_drop=11/26`, disconnected fraction 1/2; all roads use `analytic` |
| Path | Extra distance and affected count 0, mean affected distance empty |
| Star: 5 nodes / 4 roads | Hub `information=1`; leaves `information=5/14 ≈ 0.3571428571` |
| Star roads | Each has `eff_drop=5/14`, disconnected fraction 0.4, method `analytic` |
| Parallel: 2 nodes / 2 roads | Closing 100 m road: `eff_drop=1/3`, disconnected fraction 0, extra 0.1 km |
| Parallel | That closure affects 2 pairs, mean extra 50 m; closing 150 m road gives zero damage |
| All examples | Information coverage `all`; no self-loops; every road evaluated |

1. Open `results/ticket05-*/network.gpkg` in QGIS and select both layers. Inspect the seven new
   `edges` columns and `nodes.information`. Use **Graduated** symbology on `eff_drop` for roads
   or `information` for nodes. The path's middle road should rank first; the star's hub should
   have the largest information score.
2. Read `report.txt` sections **Critical links** and **Information centrality**. Compare the
   top-road table and `summary.json.metrics.criticality` with the GPKG. Check `counts_by_method`
   and `metrics.information.coverage`/`candidate_count`. All examples should report uniform weights.
3. Open `figures/critical_links_map.png`. Ring/star roads have tied losses, so equal colours are
   expected. The parallel example gives the shorter road higher damage than the curved backup.
4. Original input layers are in `data/ticket05-demo/*-input.gpkg`. Bidirectional roads have two
   directed input edges, grouped into one physical output road. Both parallel road geometries
   remain separate and visible.
5. To test partial coverage, copy the ring config and set `all: false`, `k_betweenness: 1`,
   `k_detour: 0`, `exact_info_max_nodes: 0`, and `k_nodes: 1` under `criticality`. Run using
   `--out results/ticket05-candidates`. Expect one scored road, one scored junction, and
   `coverage: candidates`; all other scores are empty.
6. To compare cache paths, copy a demo config and set `analysis.max_memory_gb: 0.0000001`.
   Run into a different folder. Expect `summary.json.computation.criticality_baseline: recomputed`
   and matching metric values. This intentionally tiny budget invokes the minimum-row exception;
   it is a correctness check rather than a recommended resource setting.
7. To compare analytic and full handling, copy the path YAML and set
   `criticality.bridge_analytic_max_side: 0`. Run to another folder. All three methods become
   `full`, with the same damage values. Resolved `run_config.yaml` files remain reusable.

### Verification results

- Hand answers passed: the four-road ring, middle path bridge, star hub/leaf information and
  shorter-versus-longer parallel-road closures. Both analytic and full path methods agree.
- Two **200-node directed random spatial fixtures** with one-way streets, bridges and parallel
  roads matched independent full all-source recomputations for **every physical road**, within
  **1e-9**. Analytic bridge damage matched those full recomputations too.
- Every junction's information centrality on both fixtures matched an independent brute-force
  NetworkX efficiency recomputation within **1e-9**.
- Cached/recomputed baseline paths, forced tiny chunks and one/two workers agreed within
  **1e-12**. Weighted hand answers, weighted analytic-versus-full paths, undirected-removal mode,
  invalid weights, zero-mass normalization and singleton undefined information were checked.
- Partial candidate nulls/coverage, GPKG columns, JSON without nonfinite values, report formatting,
  progress/ETA, figure creation/overwrite cleanup and temporary cache cleanup were checked.
- All four example CLI runs completed; their saved layers were checked against the table above.
- Final regular suite: **55 passed, 4 skipped** in **202.92 s**; this includes **8 Ticket 05 tests**.
  The skipped tests are the three opt-in live-network tests and the Ticket 03 slow benchmark;
  neither was rerun for this ticket. `git diff --check` passed. Verification used Python
  **3.13.3**, SciPy **1.18.1** and OSMnx **2.1.1** in the existing temporary environment.
  After the visual check prompted the collinear-map bounds fix, both affected output/figure
  regression tests passed again, and all four demo figure sets were regenerated.
  Your manual verification is pending.
