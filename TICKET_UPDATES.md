# Ticket implementation status

- [x] **01 — Tracer bullet: config → graph → degree → outputs** — implemented. See [ticket](plan/tickets/01-tracer-bullet.md).
- [x] **02 — All inputs + full cleaning** — completed, tested and manually verified by you.
- [x] **03 — Exact path-based centralities** — completed, tested and manually verified by you.
- [x] **04 — Screening and candidates** — completed, tested and manually verified by you.
- [x] **05 — Single-link criticality + information centrality** — completed, tested and manually verified by you.
- [x] **06 — Attack vs failure curves** — completed, tested and manually verified by you, including ER and scale-free examples.
- [x] **07 — Distribution classification** — completed, tested and manually verified by you, including five ER + five scale-free cases; inconclusive-label interpretation documented.
- [x] **08 — Failure probabilities** — completed, tested and manually verified by you, including exact answers and three spatial scenarios; report interpretation documented.
- [x] **09 — Connectivity reliability** — completed for now at your request; implementation and tests verified. Includes three exact-answer fixtures and three 200-node spatial scenarios; AP3 scope corrections and further testing recommendations documented.
- [x] **10 — Travel-time reliability** — completed, tested and manually verified by you. Includes replaceable time models, exact route examples and a sparse spatial network; further validation recommendations documented.
- [x] **11 — Hansen accessibility (uniform masses)** — completed, tested and manually verified by you on 12 October 2026, using the plan's exponential distance-decay definition.
- [x] **12 — WorldPop population** — completed, tested and accepted by you after manual review on 13 October 2026. Includes real Malé roads/WorldPop and 100 m/500 m snap comparison. Full offline suite: 300 passed, 5 skipped.
- [x] **13 — Zone aggregation** — implemented and automatically verified on 13 October 2026; manual review pending. Includes deterministic spatial assignment, population aggregates, zone exports/report/map and offline demos.
- [ ] **14 — Scorecard and final report** — not started.
- [ ] **15 — Crucitti comparison** — implemented, tested and manually reviewed, including modern OSM sensitivity/inspection and the authors' published historical graphs. Historical data: 2/4 information and 3/4 betweenness matches under both conventions; MISMATCH. Planned-city classification discrepancy remains open.
- [ ] **16 — Ada runbook** — not started.

Additional validation ideas for every ticket are tracked separately in
[plan/TEST_RECOMMENDATIONS.md](plan/TEST_RECOMMENDATIONS.md). They are follow-up recommendations,
not completed experiments or blockers to the completion recorded here.

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
Tickets 04–10 are documented below; tickets 11–16 have not been started.

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

Ticket **05** was implemented on **10 October 2026** and is **completed, tested and manually verified
by you**, as confirmed on **10 October 2026**. Tickets 02, 03 and 04 remain completed and manually verified.
Tickets 06–10 are documented below; tickets 11–16 have not been started.

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
  You confirmed that you checked the results on **10 October 2026**. Ticket 05 is complete.

## Ticket 06 — Attack vs failure curves

Ticket **06** was implemented on **10 October 2026** and is **completed, tested and manually
verified by you**, as confirmed on **10 October 2026**, including the ER and scale-free examples.
Your confirmation of Ticket 05's results has been recorded above.
Tickets 07–10 are documented below; tickets 11–16 have not been started.

### Changes

- Added validated `robustness` settings for link/node removal, step count, removal horizon,
  adaptive/static attacks, node attack metric, failure-run count and efficiency source count.
  Seeds must be nonnegative. Resolved defaults are included in `run_config.yaml`.
- Added `src/georesilience/robustness.py`. Link attacks use exact length-weighted directed
  NetworKit edge betweenness; the physical-road score is the maximum of its directed arc scores.
  Node attacks use directed weighted betweenness or undirected distinct-neighbour degree.
  Removing a physical road closes all its directions; removing a node closes all incident roads.
- Adaptive attacks recompute scores before each nonempty batch. Static attacks rank only once.
  Equal scores use ascending link IDs or original node order; numerical ties use `1e-12` tolerance.
  Parallel roads remain available after a shorter road closes, with equal-length choices handled
  consistently with Ticket 03. Self-loops are excluded from the link-removal population.
- Added independent random-failure permutations using spawned seeds. The efficiency sample is
  fixed across steps, attack/failure runs and element types. Each experiment starts from the same
  original graph. Original N is retained in every denominator; components are not recleaned.
- Tracked largest strong/weak component fractions and relative efficiency at each step. Removed
  nodes are excluded from component sizes but stay in the efficiency denominator with zero
  contributions. Efficiency uses chunked shortest paths and the configured workers/memory budget.
  Using at least N sources makes efficiency exact; smaller samples give an estimate.
- Added `robustness_curves.csv`, robustness summary/AUCs, first observed `S_scc < 0.5`, failure means
  and 5th–95th percentile bands, and a report section with link results first and labelled headline.
  Added `robustness_scc.png` and `robustness_efficiency.png`, each with one panel per enabled element.
  Reused the prior progress logger via `progress.py`, including heartbeats and estimated time.
- Added a reproducible generator, `examples/create_ticket06_demo.py`, and separate ER/scale-free
  YAML configs. Generated GraphML, input GeoPackages, model illustration and manifest live in
  gitignored `data/ticket06-demo/`; results remain gitignored. Scripts/configs are tracked source.
- Added nine test cases covering known graphs, independent NetworkX references, reproducibility,
  static/adaptive differences, weighted library inputs, zero-efficiency cases, validation,
  output generation/overwrite, and both example generators. Updated README with configuration,
  interpretation, example commands and expected results.

### Conventions and paper context

**Integer batches:** Ticket 06's literal per-step rounding can remove nothing throughout a small
graph experiment. The implementation instead uses `floor(f_max * total)` as the integer budget
and rounded cumulative counts to spread that budget across `steps`. Actual `f` is recorded in
CSV; steps with zero new removals repeat the previous observation. No removal exceeds `f_max`.
When the final actual fraction is below the requested horizon, AUC holds the final value constant
to requested `f_max`, then divides trapezoidal area by `f_max`. Summary parameters record batch
sizes, removed count and actual horizon. Tiny graphs can legitimately have a zero-removal budget.

**Efficiency:** the convention remains **mean reciprocal shortest-path length `1/d`**, as in
Tickets 03/05. It differs from AP2's spatial `d_E/d`. Here `E_rel` divides the fixed-source estimate
by its own baseline, so it is dimensionless. Sampled sources that are removed remain in the
denominator. A zero baseline produces empty CSV `E_rel` cells, null efficiency AUCs and an
explanation on the efficiency plot. Optional library weights use `W_i * W_j`; the CLI is uniform.

**Direction and scope:** Ticket 06 always uses directed travel, independently of Ticket 05's
`analysis.directed_removal` flag. Its removal population is the full cleaned network, independently
of the earlier `criticality` candidate limits. Output `network.gpkg` remains the baseline network;
the cumulative experiments are curves, not separate per-step GeoPackage layers.

The model comparison is inspired by the supplied
[Albert, Jeong & Barabási paper](papers/AP1-error_and_attack_tolerance_of_complex_networks.pdf).
The example configs use its degree-based node targeting. The generated Barabási–Albert graph
is a finite preferential-attachment example, not a fitted classification of empirical roads.
These connectivity/efficiency curves do not reproduce the paper's diameter experiment.

### Two supplied examples

Both defaults have **500 nodes**, seed 42, about six neighbours per node, equal 1,000 m road
lengths and bidirectional travel. Their schematic spring-layout coordinates are in EPSG:32644;
drawn geometry length differs from the supplied analysis length. Crossings are only junctions
when the roads share a graph node. Consolidation is disabled and inputs are marked simplified.

| Example | Model | Physical roads | Mean degree | Maximum degree |
| --- | --- | --- | --- | --- |
| ER | `G(500, 6/499)`, sampled until connected | 1,541 | 6.164 | 18 |
| Scale-free | Barabási–Albert, `n=500, m=3` | 1,491 | 5.964 | 65 |

ER is explicitly conditioned on connectedness so cleaning does not discard requested nodes.
The manifest records generation seeds, parameters and sampling attempts. Both configs use
50 steps, `f_max=0.20`, adaptive degree-based node attacks, betweenness-based link attacks,
10 random-failure runs and all 500 efficiency sources. Earlier Ticket 05 candidate limits are
reduced for faster runs; Ticket 06 still examines all roads and nodes.

### Run and manually verify

From the repository root with your Python environment activated. The existing implementation
environment can be activated using `source /tmp/georesilience-ticket02-venv/bin/activate` while
it remains available. Otherwise use the README installation instructions.

```sh
python examples/create_ticket06_demo.py
georesilience run --config examples/ticket06-er.yaml --overwrite
georesilience run --config examples/ticket06-scale-free.yaml --overwrite
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_robustness.py
```

1. Open `data/ticket06-demo/models.png`: compare the relatively even ER degrees with the BA hubs.
   Inspect `manifest.json`. In QGIS, load `er-input.gpkg` and `scale-free-input.gpkg` from this folder.
   Each has **500 nodes**; its edges layer contains **two directed edges per physical road**.
   Output `results/ticket06-*/network.gpkg` edges count physical roads once.
2. Read the **Robustness** section at the end of both reports. Links should appear first with
   the headline label. Compare `summary.json.metrics.robustness`, including AUCs, the sample size,
   exact-efficiency flag, actual horizon and per-step removals.
3. Open each `robustness_curves.csv` in a spreadsheet. Expect **1,122 data rows** plus the header:
   2 elements × (1 attack + 10 failures) × 51 observations. Attack is run 0; failures are runs 1–10.
   All step-0 rows have `f=0`, `S_scc=S_wcc=E_rel=1`. Each experiment's fractions increase and the
   measured quantities cannot increase except for floating-point roundoff. Since roads are
   bidirectional in these examples, `S_scc` and `S_wcc` agree.
4. Open `figures/robustness_scc.png` and `figures/robustness_efficiency.png` in both result folders.
   Red is the targeted attack; blue is the random-failure mean with a 5th–95th percentile band.
   Both have link and node panels. The scale-free example's node-attack efficiency curve should
   fall much faster than its random-failure curve. The band is variation across the 10 runs,
   not a confidence interval for the mean.
5. Compare the reference results below. AUC means retained performance over the whole 0–20%
   experiment, so higher is better; it is not the endpoint value. `f_half_attack` is null for all
   four attack curves here: none falls strictly below 0.5 within the configured horizon.
6. For a static comparison, copy one YAML, set `robustness.adaptive: false`, and run with
   `--out results/ticket06-static --overwrite`. For a strategy comparison, instead change
   `node_attack_metric: betweenness`. The algorithm tests contain a fixture proving the static
   and adaptive second choices differ; the graphs need not differ at every removal step.
7. Rerun a config with the same seed and compare CSVs for identical curves. A copy with
   `analysis.n_jobs: 1` should also agree; runtimes/timestamps can differ. A changed seed should
   change random-failure curves. To examine sampling, set `efficiency_sources: 100`: the summary
   then says `efficiency_exact: false` and records the fixed 100 original sample IDs.

To use **1,000 nodes**, run `python examples/create_ticket06_demo.py --nodes 1000`, then rerun both
configs. This replaces the generated inputs, so the 500-node reference values no longer apply.
Set `efficiency_sources: 1000` in config copies for exact all-source efficiency at that size;
the supplied 500-source setting becomes an estimate.

### Verified reference results (500 nodes, seed 42)

| Graph / removed element | Attack AUC(S) | Mean failure AUC(S) | Attack AUC(E) | Mean failure AUC(E) | Final attack S |
| --- | --- | --- | --- | --- | --- |
| ER / links | 0.946790 | 0.996625 | 0.866839 | 0.944828 | 0.888 |
| ER / nodes | 0.896460 | 0.897952 | 0.697513 | 0.785091 | 0.782 |
| Scale-free / links | 1.000000 | 0.999410 | 0.895183 | 0.956400 | 1.000 |
| Scale-free / nodes | 0.835500 | 0.899190 | 0.427121 | 0.790109 | 0.550 |

Node removals end at **100/500 = 20%**. Link removals end at **308/1,541 ≈ 19.987%** for ER and
**298/1,491 ≈ 19.9866%** for BA. All efficiency calculations here use every original source.
The BA graph remains connected after its link attack despite losing efficiency: component size
alone does not capture longer surviving routes. The relative response to attacks depends on the
strategy and metric; these finite examples do not establish universal model superiority.

### Verification results

- Full offline suite: **64 passed, 4 skipped** in **216.53 seconds**. The skips are the three live
  OSM tests and the existing 60,000-node benchmark; neither was rerun for this ticket.
- New tests passed, including two **200-node** random spatial fixtures checked against independent
  NetworkX directed efficiency and component calculations at **every attack/failure step**, with
  efficiency agreement within `1e-9`. Initial directed node betweenness also matches NetworkX.
- Known-graph checks cover star hub first with component size `1/N`, a ring remaining connected
  after one road closure, parallel backup availability, one-way reachability, complete node removal,
  weighted efficiency and zero baselines. Static/adaptive second choices differ on the path fixture.
- Fixed-seed curves/removal histories match exactly across **1 and 2 jobs**, including forced small
  chunks. Tests also cover stable streams when element selection/order or failure-run count changes.
- Both complete 500-node CLI examples finished successfully and wrote CSV, summary, report,
  resolved config, GeoPackage and all figures. Robustness computation took about **25 seconds per
  example** in this environment; hardware and concurrent workloads affect this time.
- **ER and scale-free test coverage:** `test_er_and_scale_free_generator` in
  `tests/test_robustness.py` generates both models with **200 nodes** and checks node/edge counts,
  strong connectivity, simplified GraphML, equal 1,000 m analysis lengths, input GeoPackage
  exports, model plot, ER probability and BA road count. The separate **500-node** end-to-end
  examples use `examples/ticket06-er.yaml` and `examples/ticket06-scale-free.yaml`, with results
  in `results/ticket06-er/` and `results/ticket06-scale-free/`. You confirmed manual verification
  of these results on **10 October 2026**; their graph statistics and AUCs are recorded above.
- Input topology/degree plots and output robustness plots were visually inspected. Verification
  used Python **3.13.3**, NetworKit **11.2.2**, SciPy **1.18.1** and the existing temporary environment.
  After improving the model plot's log-axis labels, the generator regression test passed again
  and both 500-node input examples were regenerated with unchanged topology. Both result CSVs
  were independently checked for row counts, baseline values and monotonicity. `git diff --check` passed.
  You confirmed that you manually checked the results on **10 October 2026**. Ticket 06 is complete.

## Ticket 07 — Distribution classification

Ticket **07** was implemented on **10 October 2026** and is **completed and manually verified
by you**, as confirmed on **11 October 2026**. Verification includes the requested
**five ER + five scale-free graph benchmark** and review of its inconclusive labels.
Tickets 08–10 and 15 are documented below; tickets 11–14 and 16 have not been implemented.

### Changes

- Added `src/georesilience/classification.py` with independent fitting, ordered verdict rules,
  network-label logic, report generation and classification plots. The classifier consumes the
  existing degree, centrality and robustness results without recomputing shortest paths.
- Fit degree, closeness, straightness, betweenness and computed information values. Only positive
  finite observations enter fits; zeros, nonfinite values and negatives are counted separately.
  Fewer than 50 positives, fewer than three distinct values, failed fits or nonfinite likelihood
  comparisons give inconclusive evidence with a reason. Undefined results are JSON null.
- Added package-selected power-law `xmin`, exact discrete fitting for degree, normalized likelihood
  comparisons against exponential/lognormal tails, and fixed-zero-location exponential/half-normal
  body MLEs. Applied the ticket's ordered p-value, AIC and minimum-tail thresholds. Recorded
  alpha, xmin, n_tail, likelihood ratios/p-values, body scales/AICs, tail KS, reasons and warnings.
- Used full-information verdicts for network labels. Candidate-only information is explicitly
  excluded and the ticket's betweenness fallback is used. Degree, closeness, straightness and the
  robustness gap do not influence the production label. Added secondary betweenness consistency.
- Added the node failure-minus-attack connectivity AUC gap as supporting evidence, with a sentence
  interpreting its sign and no invented threshold for a large gap. Missing node curves give null.
- Added root-level `summary.json.classification`, a **Network class** report section and ten
  figures: `classification_<distribution>_loglog.png` and `classification_<distribution>_logy.png`.
  Empirical CCDFs are normalized over positives; tail overlays are scaled by the observed tail
  fraction. Existing Ticket 03 figures are preserved. Overwrite removes stale classification
  figures and `output.figures: false` suppresses them. Added fitting runtime and powerlaw version.
- Added **independent degree evidence**, using common-support discrete Poisson and bounded
  power-law references, plus agreement with the centrality label. This diagnostic is additional
  research evidence and never changes the ticket's network label.
- Added `examples/run_ticket07_benchmark.py`, reusing the Ticket 06 input generator. It generates
  ten inputs/configs, runs their analyses and writes comparison CSV/JSON/report files with counts
  of agreement, disagreement and inconclusive cases. It supports generation-only, aggregation-only,
  custom sizes/seeds/jobs, figure selection and controlled overwrite. Generated Ticket 07 inputs
  and configs are gitignored; the script is source.
- Added `tests/test_classification.py`: known-distribution tests, independent body-MLE/AIC checks,
  rule-boundary/priority tests, label/fallback/consistency branches, exclusions, unit invariance,
  degree-model likelihood checks, numerical failure handling, complete output/figure checks and
  a small ER/BA benchmark integration test. The full ten-graph study is run explicitly rather
  than repeated by every pytest invocation. Updated README with behavior and manual commands.

### Numerical and scientific conventions

**Fit conditioning:** continuous observations are fitted in median units, restoring scales and
xmin to original units afterward. Likelihood ratios and AIC differences are invariant to this
change of units. Degree stays integer-valued and is never rescaled. Powerlaw 2.0 defaults to an
alpha upper bound of 3; the implementation explicitly permits **alpha > 1 without an upper cap**.
This matters: several light tails and the BA information fits have estimates above 3. Degree
uses `estimate_discrete=False`. Numerical warnings are retained in each distribution's JSON.

**Relative evidence:** likelihood-ratio p-values compare alternatives, not absolute fit quality.
The Gaussian verdict is the ticket's name for a **half-normal** reference with location zero.
For example, the known uniform control receives this verdict because half-normal fits better
than exponential under the prescribed rules; this does not establish a Gaussian data generator.
No bootstrap goodness-of-fit test was added. Centrality values on a graph are dependent, so
nominal p-values are diagnostic. The report explicitly states these limits.

**Labels and consistency:** JSON uses `scale-free`, `exponential` or `inconclusive`. Fallback
labels carry `label_basis: betweenness_fallback` and are described as inferred in the report.
For full information, opposing recognized exponential/Gaussian betweenness patterns are
inconsistent; an inconclusive or power-law betweenness verdict gives `n/a`. Full-information
inconclusiveness does not trigger fallback. Distribution `reason` carries the insufficient-sample
explanation separately from the machine-readable `verdict: inconclusive`.

**Independent degree comparison:** both references use the same positive degree observations,
conditioned on common support `observed minimum ... N-1`. Both have one estimated parameter.
`delta_aic = AIC_Poisson - AIC_power_law`; >10 gives `power_law_like`, <-10 gives `poisson_like`,
otherwise inconclusive. Power-law optimization uses exponent bounds 0–20 and returns inconclusive
if the upper boundary is reached. Poisson is a sparse-ER reference, not an exact model of ER
conditioned on connectedness. These are relative two-model comparisons; no AIC from the body
is compared with an AIC fitted to a different tail subset. The ticket's own degree-tail verdict
is also retained as a separate field.

**Paper context:** [AP2](papers/AP2-centrality_measures_in_urban_networks.pdf) distinguishes city
samples using information centrality and discusses geographic constraints on primal junction
degree. [AP1](papers/AP1-error_and_attack_tolerance_of_complex_networks.pdf) supplies the degree-based
ER/scale-free model comparison. ER/BA generator families do not automatically describe planned
or self-organized cities. Their agreement with Ticket 07 is a research observation.
Efficiency remains **mean(1/d)**, differing from AP2's spatial **mean(d_E/d)**. The fitted alpha is
a density exponent; the ideal continuous power-law CCDF exponent is alpha minus one. It should
not be directly equated with AP2's plotted CCDF exponents.

### Ten-graph benchmark design

- **Models:** five ER `G(500, 6/499)` graphs sampled until connected, and five BA graphs with
  `n=500, m=3`; seeds **42, 43, 44, 45, 46**, with separate spawned topology streams per model.
- **Roads:** bidirectional, equal 1,000 m analysis length; schematic EPSG:32644 spring layouts.
  Crossing lines are junctions only where graph nodes are shared. Consolidation is disabled.
- **Coverage:** every node receives information centrality (`exact_info_max_nodes: 500`). Earlier
  road-candidate limits stay at 25 each; no candidate-only information is used for the comparison.
- **Supporting robustness:** node removals only, 20 steps, `f_max=0.20`, adaptive degree attacks,
  ten random failures, all 500 efficiency sources. All ten cases share these settings. This
  deliberately avoids link-attack work that is unused by Ticket 07's supporting-evidence rule.
- **Efficiency:** graphs run sequentially, each using two analysis workers and a 0.25 GiB block
  budget. First-seed ER/BA cases render all figures; other cases keep full numeric outputs.
  The complete ten-case experiment finished in about **four minutes** on this machine. Fitting
  the five distributions took approximately **one second per graph**; full information took
  about **11 seconds per graph**. These times depend on hardware and concurrent workloads.

### Run and manually verify

From the repository root with your Python environment activated. The existing environment is
`/tmp/georesilience-ticket02-venv`; otherwise follow the README installation steps.

```sh
python examples/run_ticket07_benchmark.py --overwrite
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_classification.py
```

1. Start with `results/ticket07-benchmark/report.txt` and `comparison.csv`. Expect **ten cases**,
   five per model, with **500 nodes** each and information coverage **all**. Compare the centrality
   label with the independent degree verdict and the separate generator-agreement column.
2. Open `comparison.json`: inspect aggregate agreement/disagreement/inconclusive counts, the
   fraction with conclusive comparisons, and agreement among those conclusive cases. Do not
   present conditional agreement as overall classification accuracy.
3. For one case, inspect `er-seed42/summary.json` or `scale-free-seed42/summary.json`. Classification
   is at the root (`classification`), while robustness remains `metrics.robustness`. Inspect all
   five distributions' fit statistics, counts, reasons, numerical warnings, label basis,
   independent degree model parameters/support/AICs, and `degree_agreement`.
4. Read the **Network class** section at the end of each case's report. An information Gaussian
   verdict produces an inconclusive network label, even when degree evidence clearly favors ER.
   Check the supporting AUC gap against that case's node robustness values.
5. Open the ten `classification_*.png` files in each first-seed case's `figures/` folder. Log-log
   figures show fitted power-law tails and xmin; log-y figures show exponential and half-normal
   body fits. A model can be relatively preferred while visibly differing from the empirical
   curve. The other eight cases skip plotting by default; `--figures all` enables every figure.
6. View `data/ticket07-demo/seed42/models.png`, its generation manifest and input GeoPackages in
   QGIS. Each seed folder contains the two model inputs, directed input layers and reusable
   `er.yaml` / `scale-free.yaml` configs. Output GeoPackages retain the baseline physical network.
7. To rerun one case independently:

   ```sh
   georesilience run --config data/ticket07-demo/seed42/er.yaml --out results/ticket07-er-check --overwrite
   ```

8. To test fallback, copy a generated YAML, set `criticality.exact_info_max_nodes: 0` and
   `criticality.k_nodes: 25`, then run to a separate folder. Expect coverage `candidates`, basis
   `betweenness_fallback`, and the explicit candidate-information exclusion sentence in the report.
   Candidate information fits remain descriptive. Do not include this modified case in the
   full-information ten-case comparison.
9. To regenerate inputs only, use `python examples/run_ticket07_benchmark.py --generate-only`.
   To rebuild aggregate files from completed outputs without rerunning analysis:

   ```sh
   python examples/run_ticket07_benchmark.py --summarize-only
   ```

10. For a larger follow-up, pass `--nodes 1000 --out results/ticket07-1000 --overwrite`. The runner
    updates all-node information coverage and exact efficiency sampling to match the new size.
    Keep seed/threshold choices fixed before examining results; do not tune them to force matches.

### Verified benchmark findings (500 nodes)

| Model | Seed | Roads | Info verdict | Info tail count | Ticket network label | Degree evidence | Degree comparison |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ER | 42 | 1,541 | gaussian | 258 | inconclusive | poisson_like | inconclusive |
| ER | 43 | 1,530 | gaussian | 130 | inconclusive | poisson_like | inconclusive |
| ER | 44 | 1,540 | gaussian | 295 | inconclusive | poisson_like | inconclusive |
| ER | 45 | 1,512 | gaussian | 270 | inconclusive | poisson_like | inconclusive |
| ER | 46 | 1,503 | gaussian | 181 | inconclusive | poisson_like | inconclusive |
| BA | 42 | 1,491 | power_law | 467 | scale-free | power_law_like | agreement |
| BA | 43 | 1,491 | gaussian | 33 | inconclusive | power_law_like | inconclusive |
| BA | 44 | 1,491 | power_law | 416 | scale-free | power_law_like | agreement |
| BA | 45 | 1,491 | gaussian | 32 | inconclusive | power_law_like | inconclusive |
| BA | 46 | 1,491 | power_law | 66 | scale-free | power_law_like | agreement |

The degree comparison favors the corresponding reference family in **all ten cases**. The
centrality rule gives **three agreements, zero disagreements and seven inconclusive comparisons**:
only **30%** of cases yield conclusive comparisons. Agreement among those three is 100%, but this
is **not 100% classification accuracy**. No ER case receives an exponential network label under
this rule. BA seeds 43 and 45 have selected information tails with fewer than the required
50 observations; their body verdict is Gaussian, which maps to an inconclusive network label.

The node AUC gaps are about **0.0008–0.0054 for ER** and **0.0580–0.0871 for BA**, supporting
stronger attack/failure separation for these BA samples. The gap does not override inconclusive
centrality verdicts. These findings were recorded without changing the ticket thresholds or seeds.

### Meaning of inconclusive labels and benchmark limitations

An **inconclusive network label** is an abstention under the ticket's decision rule. It can follow
a successful fit: full-information `power_law` maps to `scale-free`, `exponential` maps to
`exponential`, and either `gaussian` or an inconclusive distribution verdict maps to an
`inconclusive` network label. Here, `gaussian` means the nonnegative **half-normal** body reference
is preferred under the ordered rules; it does not establish a Gaussian data generator.

All seven inconclusive benchmark cases have a **Gaussian information-distribution verdict**.
Every case computed information centrality for all **500 nodes**, and all ten information fits
have `fit_error: null`. These labels therefore do not indicate missing information values or a
recorded fit failure. Numerical warnings are retained separately in the case summaries.

- **Five ER cases:** the half-normal body is preferred over exponential. The rule does not map
  this information verdict to either network family. Poisson-like ER degree structure does not
  imply an exponential information-centrality distribution.
- **BA seeds 43 and 45:** the selected tails contain **33 and 32 observations**, below the required
  **50**. Their power-law-versus-exponential comparison p-values are approximately **0.224 and
  0.259**, also failing the required **p < 0.1**. Both checks fail; small tails are not the only
  reason the power-law rule is unmet. The half-normal body then wins under the ordered rules.
  The fitted tail contains only values at or above the selected `xmin`, so a 500-node graph does
  not necessarily provide 50 tail observations.
- **BA seeds 42, 44 and 46:** the power-law conditions pass, producing `scale-free` labels.

The implementation follows the specified rule, but the experiment demonstrates **limited
coverage and no reliable general separation of ER and BA degree families by this centrality
criterion**: only **3/10 cases (30%)** receive conclusive labels. Their agreement does not establish
100% classifier accuracy or absolute goodness of fit. Successful software tests verify the
implemented calculations and branches; they do not validate the scientific hypothesis.

Preserve and report these abstentions. A follow-up with **1,000 nodes and the same seeds and
thresholds**, chosen before inspecting results, could investigate finite-sample effects. Larger
graphs may help with thin BA tails, but do not guarantee exponential information distributions
for ER graphs or agreement between degree and centrality classifications. This follow-up has
**not been run**. Do not lower thresholds or relabel Gaussian information as exponential to force
agreement. Completion of Ticket 07 records implementation and manual verification, including
these observed limitations.

### Verification results

- Final full offline suite: **90 passed, 4 skipped** in **247.86 seconds**. This includes **26 new
  classification cases**. The skips are the existing three live OSM integration tests and the
  60,000-node benchmark; neither was rerun for this ticket.
- Fixed-seed **5,000-sample** controls produced power-law, exponential and half-normal verdicts
  as required; uniform was not classified as power law. Independent closed-form body MLEs/AICs
  agree with the implementation. Small samples, zero/constant/missing values, unit invariance,
  exact threshold boundaries, numerical failures and every label/fallback branch are covered.
  Unavailable likelihood comparisons cannot count as evidence for a power law.
- Degree diagnostic tests independently reconstruct both discrete log likelihoods on the common
  support. Small ER/BA end-to-end tests verify full coverage, saved configs, comparison outputs,
  reaggregation without analysis, nonempty-output refusal and figure cleanup during overwrite.
- The full ten-graph 500-node experiment completed successfully with every information value
  computed and all 500 efficiency sources used. All comparison fields, case outputs and
  representative classification figures were produced; representative fit plots were inspected.
- An independent artifact audit checked all ten JSONs for finite numbers, GeoPackage node counts
  and complete information values, finite likelihood comparisons, exactly **231 node-curve rows
  per case**, correct AUC-gap arithmetic, ten comparison rows and ten classification figures per
  representative case. Aggregate files were rebuilt successfully from completed outputs.
- `git diff --check` passed. Verification used Python **3.13.3**, powerlaw **2.0.0**, SciPy
  **1.18.1** and the existing temporary environment. You confirmed completion after reviewing
  the generated outputs and the inconclusive-label explanation on **11 October 2026**.
  Ticket 07 is complete; Ticket 08 is documented below.

## Ticket 08 — Failure probabilities

Ticket **08** was implemented on **11 October 2026** and is **completed and manually verified
by you**, as confirmed on **11 October 2026**. Verification covers the ticket's exact-answer and
spatial examples. Tickets 09–10 are documented below; tickets 11–16 have not been started.

### Changes

- Added validated `reliability.p_fail_csv`, `p0` and `p0_sweep` configuration. Probabilities must
  be finite and in `[0,1]`; the resolved sweep is sorted, deduplicated and includes the primary p0.
- Added `src/georesilience/failure_probabilities.py` for template export, CSV validation,
  any-part-fails combination, primary assignment, reusable sweep calculations and coverage reports.
- Added `georesilience template --config ... --out ...` with loading/cleaning only and explicit
  overwrite control. The library exporter returns commented CSV text and optionally writes a file.
- Templates contain one row per distinct way ID on non-self-loop physical links, with names,
  highway tags, equal-share length, containing-link count and an empty probability. Reciprocal
  directions count once; repeated ways and parallel roads are accounted for.
- CSV imports accept comments and ignore optional metadata columns. IDs are parsed as integers
  without float conversion. Invalid probabilities, duplicate/malformed IDs and missing columns
  stop the run; offending data-record numbers are reported. Unknown IDs and blanks generate
  warnings, capped at 20 messages with total/omitted counts. CSV validation precedes expensive
  centrality computation.
  Pandas is declared explicitly as a dependency for its comment-aware CSV reader; it was already
  installed through the existing GeoPandas dependency.
- Assigned primary `p_fail` and `p_fail_source` to exported physical links and every constituent
  directed edge. Self-loop values are null and excluded from coverage. Missing way IDs use the
  full proxy. A supplied probability of zero is covered data.
- Added root `summary.json.reliability`, a **Failure probabilities** report section and resolved
  settings. Coverage includes per-source link/length percentages and effective supplied/proxy
  length shares. The low-user-coverage warning includes uncovered shares of mixed links.
- Added `examples/create_ticket08_demo.py`: a three-node/five-road exact example and three
  scenarios on the same seeded **200-node spatial graph**, with QGIS input copies, unfilled
  templates, supplied CSVs, configs, manifests and independent expected-result CSVs. Generated
  files are gitignored. No road-class risk table or hazard preset was introduced.
- Added `tests/test_failure_probabilities.py` covering exact answers, numerical endpoints/tiny
  probabilities, validation, warning limits, template round-trip, shared/multiple ways, parallel
  and one-way roads, self-loops, absent IDs, coverage thresholds, independent spatial references,
  CLI cleaning-only behavior, early failure and saved-output integration. Updated README.

### Conventions and scope

`p_fail` is a **per-event closure probability**, not an annual rate. A supplied way's probability
is reused on each containing physical link. The ticket's any-part-fails rule combines supplied
way survival probabilities with the length proxy for uncovered shares; it assumes independent
parts. With no supplied values, `p_link = 1 - (1-p0)^length_km`. The implementation uses
`log1p`/`expm1` to preserve tiny values and handles exact 0/1 explicitly.

Simplification loses original per-way lengths, so both template lengths and mixed-link shares
use the ticket's **equal-share approximation**. The source-category table assigns the whole link
to user/mixed/proxy. Effective user/proxy percentages instead split mixed-link length. The
additional proxy warning triggers at **0 < effective user length coverage < 50%**, matching the
interpretation discussed before implementation. At exactly 50% or zero it is omitted; the table
always reports coverage. Self-loops never enter these denominators.

CSV error/warning row numbers mean **one-based data rows after the header**, excluding comments
and empty lines. Blank values are missing; zero is supplied. Unknown rows are still validated,
and an unknown blank row contributes both an unmatched-ID and blank-value warning.

This stage assigns probabilities; it does not draw closures or estimate connectivity. Ticket 06
removal experiments retain their existing fraction-based behavior. Tickets 09 and 10 use
`probabilities_at_p0(links, user_probabilities, p0)` for each sweep value. Synthetic probabilities
test implementation correctness, not real-world hazard calibration.

### Run and manually verify

Run from the repository root with your environment activated. The existing verification
environment is `/tmp/georesilience-ticket02-venv` if still available.

```sh
python examples/create_ticket08_demo.py
georesilience template --config data/ticket08-demo/exact.yaml --out data/ticket08-demo/check-template.csv --overwrite
georesilience run --config data/ticket08-demo/exact.yaml --overwrite
georesilience run --config data/ticket08-demo/spatial-proxy.yaml --overwrite
georesilience run --config data/ticket08-demo/spatial-user.yaml --overwrite
georesilience run --config data/ticket08-demo/spatial-mixed.yaml --overwrite
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_failure_probabilities.py
```

1. Open `results/ticket08-exact/network.gpkg`, layer `edges`, in QGIS. Expect **3 nodes / 5 physical
   roads**, including two separate one-way parallel roads. Match rows by `name`:

   | Name | Source | Expected probability |
   | --- | --- | --- |
   | 2 km proxy | proxy | `0.0199` |
   | 3 km mixed | mixed | `1 - 0.9 * 0.99^1.5`, about `0.113466` |
   | Single supplied way | user | `0.1` |
   | Two supplied ways | user | `0.19` |
   | Different supplied probabilities | user | `0.37` |

2. Inspect `check-template.csv`: expect eight way rows, empty `p_fail`, per-event and equal-share
   header comments, and total shared lengths **10,000 m**. Ways 201/202 each receive 1,500 m.
   Fill every row with 0.1, point a copy of the YAML to it, and rerun to a separate output folder:
   all links should become `user`, and links containing two distinct OSM ways should have
   probability 0.19.
3. Compare the three `results/ticket08-spatial-*/report.txt` files. They analyze the **same graph**,
   with proxy-only, fully supplied and partial coverage. The partial scenario deliberately has
   blank rows and one unmatched ID. Inspect total/shown/omitted warnings and the proxy warning.
4. Compare each GeoPackage's edges by **name** with the matching
   `data/ticket08-demo/<scenario>-expected.csv`. Way-ID sets can repeat across different roads;
   they are not unique comparison keys. Input GeoPackages are `exact-input.gpkg` and
   `spatial-input.gpkg`; crossings are junctions only at shared graph nodes.
5. Inspect `summary.json.reliability.coverage.by_source` alongside effective
   `user_length_pct` / `proxy_length_pct`. Category length percentages sum to 100%, and effective
   shares sum to 100%, but mixed-link length contributes to both effective shares.
6. Check resolved `run_config.yaml`: all four examples specify sweep `[0.001, 0.05]`, which becomes
   `[0.001, 0.01, 0.05]` after including the primary. Supplied links' probabilities are invariant
   to p0; proxy/mixed probabilities increase with p0. Use a copied YAML and a separate output
   directory to try another primary value.
7. In a copied CSV, try `p_fail=1.2`, a word, or a duplicate ID. Expect a row-specific error.
   Leave a value blank to get a warning and proxy treatment. Template export itself should work
   even if the config's probability CSV is missing, because it only loads and cleans the network.

The generator accepts `--nodes` and `--seed`. Defaults use a connected random geometric graph,
seed 42, with lengths `Euclidean metres * U(1.0,1.3)`. All scenarios disable consolidation and
figures and keep earlier analysis work small; full input/template/probability artifacts remain.

### Verified example findings

The default spatial input has **200 nodes / 1,046 physical links**. All three spatial outputs
retain that same graph; only the supplied probability coverage changes.

| Scenario | User links | Mixed links | Proxy links | Effective user length | Effective proxy length |
| --- | --- | --- | --- | --- | --- |
| Exact (3 nodes) | 3 | 1 | 1 | 65.00% | 35.00% |
| Spatial proxy | 0 | 0 | 1,046 | 0.00% | 100.00% |
| Spatial user | 1,046 | 0 | 0 | 100.00% | 0.00% |
| Spatial mixed | 233 | 175 | 638 | 31.41% | 68.59% |

All four CLI runs completed. Each saved probability/source was checked against its independent
reference CSV by road name; the largest absolute probability difference was **1.67e-16**.
The exact example reproduces all five expected answers above. Its blank way 202 produces one
CSV warning. The spatial mixed case produces **291 CSV warnings** (290 blanks and one unmatched
ID), with **20 shown / 271 omitted**, and the additional line
`WARNING: 68.6% of network length uses the length proxy`.

### Report interpretation and manual completion

You confirmed that Ticket 08 is manually verified on **11 October 2026**, after reviewing the
results and their interpretation. The README now includes
[How to read the Failure probabilities report](README.md#how-to-read-the-failure-probabilities-report):

- Explains that the source table measures supplied/proxy **coverage**, while individual
  per-event closure probabilities are stored in `edges.p_fail`.
- Defines user/mixed/proxy, physical links versus directed edges and OSM-way CSV rows, and
  shows the mixed example's counts, kilometres and percentage arithmetic.
- Derives effective coverage **31.41% user / 68.59% proxy** from the mixed-link shares and
  explains why this produces the **68.6% proxy-length warning**.
- Explains the primary p0, sweep use, supplied zero versus blank values and the demo's
  **291 CSV warnings (20 shown / 271 omitted)**.
- Gives three spatial-road calculations for manual checking in QGIS, reference-CSV comparisons
  by road name and the distinction between calculation correctness and hazard calibration.
- Explains why earlier centrality and Ticket 06 robustness sections agree across the three
  spatial scenarios; Ticket 09 consumes the probabilities for connectivity estimates.

### Verification results

- Final targeted Ticket 08 suite: **53 passed** in **1.99 seconds**. Includes independent
  probability checks on **three 200-node spatial graphs** (seeds 7, 42, 84), across five p0 values,
  and four small end-to-end scenario runs. Tests cover template cleaning/simplification, finite
  probabilities, 50% warning
  boundaries, warning truncation, large exact IDs and primary-sweep inclusion.
  Malformed extra CSV cells are rejected instead of allowing implicit index inference to shift
  probabilities onto different way IDs.
- Artifact checks confirmed node/link counts, finite probabilities in `[0,1]`, source labels,
  category/effective percentage totals, valid finite JSON and ASCII reports wrapped to 100 columns.
  The actual template CLI also exported eight exact-example way rows totaling 10,000 m.
- Full offline regression suite: **142 passed, 4 skipped** in **257.23 seconds**. The skips are
  the existing three live OSM tests and opt-in 60,000-node benchmark. After this suite started,
  one additional malformed-CSV guard test was added; the final targeted run above verifies all
  **53 Ticket 08 cases**, including the strengthened parser and end-to-end outputs.
- `git diff --check` passed. Verification used Python **3.13.3** and the existing temporary
  environment. All four default CLI examples and the template export completed successfully.
- You confirmed manual verification on **11 October 2026**. Ticket 08 is complete;
  Ticket 09 is documented below.

## Ticket 09 — Connectivity reliability

Ticket **09** was implemented on **11 October 2026** and is **completed for now at your request**,
as confirmed on **11 October 2026**. Additional validation remains separate follow-up work in
[plan/TEST_RECOMMENDATIONS.md](plan/TEST_RECOMMENDATIONS.md#09--connectivity-reliability-priority-follow-up).
Tickets 01–08 retain their completed status. Ticket 10 is documented below; tickets 11–16 have not been started.

### Changes

- Added `src/georesilience/connectivity.py`: independent physical-road closure sampling, binary
  directed CSR topology, strong components, mutual-pair scores, deterministic main-SCC membership,
  conditional link importance and directed OD reachability. Parallel roads supply separate arcs;
  both directions of one physical road close together. Self-loops are excluded.
- Added `reliability.samples` (default 10,000), `od_pairs_csv`, `min_down_count` (30) and
  `min_up_count` (30). Existing configs receive these defaults and now run the connectivity stage.
  Sampling is independent of the direction switches for centrality/removal analyses.
- Added reusable comment-aware OD CSV validation and projected KD-tree snapping, with deterministic
  nearest-node ties, finite WGS84 validation and >500 m warnings. CSV errors fail before expensive
  analysis. Directed BFS is shared by OD rows with a common origin; same-SCC pairs need no BFS.
- Added normal 95% network intervals, Wilson node/OD intervals and Welch t link-importance
  intervals. Unavailable estimates are JSON null / empty GeoPackage numeric values with explicit
  status. Up/down counts remain available. The library supports optional nonnegative node weights;
  CLI analyses use uniform weights. A zero distinct-pair denominator remains undefined.
- Added reproducible 256-sample seeded batches, ordered parallel accumulation, common random
  uniforms across p0 values and reuse of identical probability vectors. Workers are limited by
  workload and the working-array memory budget. Summaries retain seeds/batch details and runtime
  metadata. No full failure history or all-pairs distance matrix is retained.
- Integrated node/link fields into `network.gpkg`, root `summary.json.reliability` while preserving
  Ticket 08 coverage/warnings, the new report section, `od_reliability.csv` and
  `figures/connectivity_nodes_map.png`. Overwrite removes stale OD CSVs and the map.
- Added `examples/create_ticket09_demo.py`: three small exact-answer cases and three scenarios on
  the same seeded 200-node spatial graph. Includes input GeoPackages, GraphMLs, probability
  templates/CSVs, OD CSVs, YAMLs, a manifest and independent exact-reference JSONs. Generated data
  are ignored by Git; the generator and tests are tracked.
- Added `tests/test_connectivity.py` and README instructions explaining definitions, report fields,
  assumptions, confidence intervals, example results and manual checks.

### Approved deviations from the original plan and AP3 alignment

The original [Ticket 09](plan/tickets/09-connectivity-reliability.md) is retained as the planning
baseline. The following changes implement the recommendation you approved after the AP3 review:

1. **Scientific attribution:** this is an **AP3-inspired connectivity analysis**, not a direct
   implementation of AP3's main method. [AP3](papers/AP3-vulnerability_analysis.pdf), printed page
   269, describes surviving-path connectivity reliability; its principal analysis on pages 270–274
   concerns accessibility-loss vulnerability. The SCC score, membership, importance and sampling
   design are project choices. Later accessibility work is closer to AP3's central contribution.
2. **Network meaning:** the SCC formula counts **mutually reachable distinct node pairs**, not
   every possible directed trip or the share of actual trips served. The formula is preserved;
   its interpretation is corrected. True one-way reachability is assessed separately for OD pairs.
   Uniform node-pair weights do not introduce observed demand data.
3. **Node meaning and corrected acceptance example:** `p_connected` retains its planned field
   name but is explicitly labeled **main-SCC membership**. A selected singleton counts. With two
   nodes, one two-way road and closure probability 0.5, deterministic minimum-ID ties give
   memberships **1.0 and 0.5**, with average **0.75**. The original claim of 0.75 per node conflicts
   with that tie rule. Tests use the corrected per-node expectations; network reliability stays 0.5.
4. **Importance guard in both states:** added `min_up_count`, `rel_up_count` and status fields.
   Always-failing roads have no up observations, just as never-failing roads have no down
   observations. Neither permits a conditional difference. Both thresholds and samples require
   at least two observations for variance estimation; defaults remain 30 and 10,000 respectively.
5. **Complete interval outputs:** added individual node interval fields and Welch importance
   interval fields to fulfill the ticket's broad promise of CIs for all reported estimates.
   The original detailed output list only named network/OD intervals and maximum node half-width.
   Negative importance estimates are retained as sampling noise rather than silently clamped.
6. **Failure assumptions and CI limits:** independent physical-link failures are an explicit
   baseline assumption, including roads sharing an OSM way. This does not model common hazards.
   CIs quantify Monte Carlo uncertainty conditional on supplied/proxy probabilities, excluding
   calibration/model uncertainty. Normal/Welch approximations can miss rare events when every
   observed score is equal. These limits are stated in the README and generated report.
7. **Whole-network connectivity:** the planned output omission is preserved, but the explanation
   is metric scope. We do not claim whole-network-connected probability is universally near zero
   at city scale; topology, size and failure probabilities determine it.
8. **Sweep efficiency:** common uniforms across p0 values make comparisons less noisy and sampled
   mutual connectivity monotone. Identical probability vectors share computation, so fully supplied
   networks have flat sweeps without redundant sampling. Only the primary produces node/link/OD
   outputs, as planned. The memory estimate covers working arrays, not total process memory.

### Run and manually verify

Run from the repository root with your environment activated. The existing verification
environment is `/tmp/georesilience-ticket02-venv` if still available.

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

Inspect **Connectivity reliability** near the end of each `results/ticket09-*/report.txt`.

- **Half:** network near 0.5 with its default-seed CI containing 0.5; memberships 1 and near 0.5;
  importance exactly 1; OD probabilities equal the network score. Compare `half-expected.json`.
- **Directed:** OD forward exactly 1, reverse near 0.5; mutual score near 0.5. The always-up road
  has null importance with `insufficient_down`. Fully supplied probabilities give a flat sweep.
- **Bridge:** compare against `bridge-expected.json`, which independently enumerates all 128
  failure states. The bridge should dominate conditional importance. Match roads by `name` or
  `link_id`; estimates should be close, with individual rather than simultaneous CIs.
- **Spatial proxy/user/mixed:** same 200-node graph, different coverage. Inspect sweep monotonicity,
  coverage warnings, zero/one controls and importance count/status guards. High reliability is
  expected for this redundant graph; an observed score of one is not proof of zero failure risk.
- In QGIS compare the matching `*-input.gpkg` with output `network.gpkg`. Node membership fields
  and CIs should lie in [0,1]. For each non-loop road, up plus down counts equal the samples.
  Inspect the new map in the small-case and spatial-mixed `figures/` folders.
- Copy a config to compare `analysis.n_jobs: 1` and `4` using separate output folders. Numerical
  connectivity results must agree; runtime/worker metadata can differ. Move an OD coordinate far
  away in a copied CSV to check snapping warnings.

See [README report interpretation](README.md#how-to-read-the-connectivity-reliability-report)
for the meanings of the three different probabilities, importance and intervals. Generator
options are `--nodes`, `--seed`, `--samples` and `--out`.

### Verified default example findings

All six CLI runs used **seed 42 / 10,000 samples**. Each small example's exact network value is
inside its reported 95% CI; every available small-example exact importance is also inside its
individual importance interval for this seed.

| Scenario | Nodes / roads | Network estimate | 95% CI | Exact network value |
| --- | --- | --- | --- | --- |
| Half | 2 / 1 | 0.491800 | [0.482001, 0.501599] | 0.500000 |
| Directed | 2 / 2 | 0.498000 | [0.488200, 0.507800] | 0.500000 |
| Bridge | 6 / 7 | 0.814280 | [0.808851, 0.819709] | 0.81532443625 |
| Spatial proxy | 200 / 1,046 | 1.000000 | [1.000000, 1.000000] | not enumerated |
| Spatial user | 200 / 1,046 | 0.999848 | [0.999823, 0.999873] | not enumerated |
| Spatial mixed | 200 / 1,046 | 1.000000 | [1.000000, 1.000000] | not enumerated |

The half memberships are **1.0000 / 0.4918**, average **0.7459**; link importance is exactly 1.
The directed OD values are **1.0000 forward / 0.4980 reverse**. The bridge's importance is
**0.596561**, against exact **0.5961063375**; internal-road exact importances are approximately
0.02609–0.03307. Maximum absolute membership errors against enumeration are **0.0082**, **0.0020**
and **0.0018553** for half/directed/bridge respectively.

Spatial proxy/mixed estimates at the highest p0 (0.05) are **0.999998 / 0.999996**. Fully supplied
spatial results are invariant to p0. All spatial OD rows observed reachability 1; their Wilson
intervals still allow a small unobserved failure probability. Available importance counts are
**860 proxy**, **1,044 user** and **926 mixed**, out of 1,046 roads. The remaining proxy/mixed
roads have insufficient down observations. User controls contain one `insufficient_down` road
(p=0) and one `insufficient_up` road (p=1). The near-unity spatial results test redundancy and
guards; the exact fixtures establish nontrivial connectivity and direction correctness.

### Verification results

- Targeted Ticket 09 suite: **33 passed** in **16.55 seconds**. Covers exact enumeration of
  directed, parallel and weighted graphs; corrected two-node values; p=0/p=1 and rare-state guards;
  hand-calculated Wilson/Welch intervals; 99% network CI coverage in at least 95 of 100 seeded
  repetitions; actual one/four-worker equality; budget-constrained worker selection; shared-uniform
  monotonicity; stable sample prefixes; OD validation/snapping/ties/warning truncation/BFS reuse;
  pipeline fields, finite JSON, figure/OD cleanup, early CSV errors and all six generated scenarios.
- All six default CLI examples completed. Independent artifact checks validated node/road counts,
  finite JSON/probabilities, CI ordering/bounds, importance availability versus status, up/down
  totals and ASCII reports wrapped to 100 columns. Exact small-network memberships/importances
  were independently compared. The spatial-mixed membership map was visually inspected.
- Full offline regression suite: **176 passed, 4 skipped** in **283.66 seconds**. The skips are
  the existing three live OSM tests and the opt-in 60,000-node benchmark. All earlier ticket
  regression tests passed with the new default connectivity stage enabled.
- `git diff --check` passed. Verification used Python **3.13.3** in the existing temporary
  environment. No new dependency was required.
- You requested completion for now on **11 October 2026**, after discussing report generation
  and the strengths/limits of the current tests. Additional sparse-bottleneck, repeated-coverage,
  convergence and real-road experiments are documented as proposed follow-ups, not tests already
  performed. No new experiments were run for this documentation update. Ticket 10 is documented below.

## Current ticket: 10 — Travel-time reliability

Ticket **10** was implemented on **11 October 2026** and is **completed and manually verified
by you**, as confirmed on **11 October 2026**.
Tickets 01–09 retain their completed status. Tickets 11–16 have not been started.

### Changes

- Added validated `travel_time` configuration: enabled, samples (1,000), sampled origins (200),
  relative tolerance tau (0.5), optional highway-class speeds, time-model selection and supplied
  time attribute. Tau must be finite/nonnegative, speeds finite/positive and samples at least two.
- Added `src/georesilience/time_models.py`, separating cost assignment from routing. The default
  model uses `3.6 * length_m / speed_kph` seconds and OSMnx speed imputation. Numeric km/h, mph,
  lane/list values and OSMnx-supported implicit codes are normalized; unsupported tags are missing.
  The isolated implicit-code adapter follows the installed OSMnx 2.x parser and has explicit tests.
- Added source/length coverage: tagged, user-table, observed class mean and network class mean.
  Physical-road length is apportioned across directed edges, avoiding reciprocal double counting
  while accounting for asymmetric tags. Self-loops are excluded from both inference and coverage.
  With no usable non-loop speed tags and no table, the default stage skips with a clear reason.
- Added `src/georesilience/travel_time.py`: reproducible origin selection, a separate seeded
  closure stream, directed minimum-time parallel arcs, baseline/damaged shortest paths, per-sample
  threshold evaluation and bounded-memory aggregation. Extra OD origins are included without
  changing the network origin sample. All arcs of a failed physical road disappear together.
- Added network and sampled-origin estimates with normal 95% intervals across sample fractions;
  OD estimates use Wilson intervals. Node `p_tt_ok` and its interval fields are null for unsampled
  origins. Self-pairs are excluded; same-node OD succeeds with zero baseline. Baseline-unreachable
  pairs always fail and are counted. No-positive-distinct-pair cases remain undefined.
- Added bounded-memory travel-time-factor percentiles and bin bounds. Ratios pool reachable
  distinct journeys, including late journeys, with an exact no-detour bin. Disconnected journeys
  fail reliability but do not enter ratios. Histogram-range limits/counts are explicit.
- Integrated root `summary.json.travel_time`, report output, node fields and merged OD CSV fields
  (`p_tt_ok`, separately named time CI fields, `tt0_min`). Existing Ticket 09 fields are preserved.
  Disabled/skipped stages and overwrite remove stale time results without losing connectivity.
- Added `examples/create_ticket10_demo.py`, seven scenarios with input GeoPackages, GraphMLs,
  probability/OD CSVs, YAMLs, exact small-case expectations and a manifest. Generated data are
  gitignored; source and tests are tracked. Added `tests/test_travel_time.py` and README guidance.

### Time-function flexibility and clarifications to the original plan

The original [Ticket 10](plan/tickets/10-travel-time-reliability.md) remains the planning baseline.

1. **Your requested extension:** routing accepts supplied directed-edge seconds through a
   `PreparedTimeModel`, rather than embedding distance/speed arithmetic in the failure loop.
   YAML `time_model: edge_attribute` uses any named seconds attribute. Python callers can supply
   `run(config, time_model=provider)` where `prepare(graph, config)` returns costs and metadata.
   An optional scenario evaluator receives the global sample index and failed physical-link IDs,
   enabling different static cost snapshots per sample. A custom delay model is tested explicitly.
2. **Model reproducibility:** custom Python-provider runs save `time_model: custom` in resolved
   YAML and require the provider again on rerun. They cannot silently revert to distance/speed.
   Model name, assumptions and supplied parameters are recorded in the summary. YAML edge-attribute
   runs need only their config and input data. Models must return finite positive seconds; the
   engine supports additive costs, not full traffic assignment or turn/departure-time routing.
3. **Threshold interpretation:** tau is user-controlled, with the planned default 0.5. It expresses
   acceptable relative delay, not an absolute deadline or a literature-derived universal cutoff.
   Equality counts as success, with a tiny tolerance for equivalent floating-point path sums.
4. **Pair/origin definitions:** self-pairs are excluded from network denominators and ratio
   distributions, avoiding zero/zero ratios. Same-node OD remains explicitly successful. Origins
   are sampled without replacement and capped at node count. Only sampled origins get node scores;
   extra OD origins do not alter the network estimate. These details were underspecified originally.
5. **Intervals and uncertainty:** added origin interval fields and separately named OD time CIs.
   Network/origin intervals use independent sample fractions, rather than treating destinations
   within a draw as independent Bernoulli trials. Intervals condition on selected origins, the
   time model and failure probabilities; they exclude origin-selection and calibration uncertainty.
   Constant observed scores retain the documented normal-interval rare-event limitation.
6. **Memory and quantiles:** baselines are calculated once and shared as a temporary disk-backed
   array; damaged shortest paths are chunked. Baseline disk bytes and estimated working arrays are
   reported separately. Histogram percentiles are approximate and include bin bounds; no ratio
   history is stored. Underflow/overflow percentiles are unavailable rather than falsely precise.
7. **Scope:** the free-flow model is a speed-limit/imputation proxy with no congestion. Supplied
   times may contain explicitly modelled factors, but no traffic model is claimed. The stage uses
   primary p0 only; its fixed indexed seed stream is separate from Ticket 09, as planned. No new
   figure is required by Ticket 10; sampled nodes can be styled directly in QGIS.

### Run and manually verify

From the repository root, with your environment activated (the existing temporary environment
is `/tmp/georesilience-ticket02-venv` if still available):

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

Read **Travel-time reliability** in each `results/ticket10-*/report.txt`. Compare the small
examples with `data/ticket10-demo/expected.json`, then inspect merged `od_reliability.csv` and
`network.gpkg` node fields in QGIS. Input copies are `data/ticket10-demo/*-input.gpkg`.

- Tight: 1-minute baseline, 3-minute always-available alternative, tau=0.5. Reliability should be
  near 0.5, even though the destination stays reachable. Same-node OD equals one.
- Boundary/relaxed: tau=2 and 2.5 accept the slow alternative; reliability equals one.
- Skip: no speeds/table; expect `skipped: no speed data`, null node scores and no time CSV fields.
- Speed table: residential=30 km/h gives 2-minute baseline and reliability near 0.5.
- Attribute: supplied times add signal delays without speed tags. Baseline is 75 seconds
  (1.25 minutes), alternative 210 seconds, reliability near 0.5. This exercises another time function.
- Sparse: 200 nodes / 361 roads, two grids joined by one vulnerable road. Inspect delay/failure
  variation, actual origin count and nulls at unsampled nodes; this avoids the saturated Ticket 09
  dense-spatial examples. These are hypothetical probabilities, not calibrated hazards.
- Copy a YAML and change tau with inputs/seed fixed: success must not decrease as tau increases.
  Compare one/four workers and constrained memory in separate outputs; numerical results agree.

The [README](README.md#travel-time-reliability-ticket-10) explains the time-model API, coverage,
report interpretation, approximate percentiles and confidence-interval limits. Generator options
are `--nodes` (even, at least 20), `--samples`, `--seed` and `--out`.

### Verified default example findings

All seven CLI examples completed with seed 42, **1,000 time samples** and **2,000 connectivity
samples**. Connectivity and time draws intentionally differ.

| Example | Time model / tau | Network time reliability | 95% CI | Forward baseline |
| --- | --- | --- | --- | --- |
| Tight | free_flow / 0.5 | 0.505000 | [0.473996, 0.536004] | 1 minute |
| Boundary | free_flow / 2 | 1.000000 | [1.000000, 1.000000] | 1 minute |
| Relaxed | free_flow / 2.5 | 1.000000 | [1.000000, 1.000000] | 1 minute |
| Skip | free_flow / 0.5 | skipped: no speed data | not computed | not computed |
| Speed table | free_flow / 0.5 | 0.505000 | [0.473996, 0.536004] | 2 minutes |
| Attribute | edge_attribute / 0.5 | 0.505000 | [0.473996, 0.536004] | 1.25 minutes |
| Sparse | free_flow / 0.25 | 0.824866 | [0.810780, 0.838952] | 6.449772 minutes across bridge |

The sparse input has 361 physical roads / 722 directed edges: internal-road p=0.08 and joining
bridge p=0.30. It selects **24 origins**, routes **26 including OD**, and leaves other node time
scores null. Across-bridge forward/reverse OD reliability is **0.704**, nearby OD **0.928**.
Reachable-journey factor p50/p90/p99 is approximately **1 / 1.087980 / 1.514174**. The small
free-flow alternative has true factor 3, reported **2.992776** with bin bounds containing 3;
the custom-time alternative has true factor 2.8, reported **2.797547** with bounds containing 2.8.

### Verification results

- Final targeted Ticket 10 suite: **45 passed** in **21.53 seconds**. Covers exact fast/slow
  thresholds and equality; every failure state against independent NetworkX directed/parallel
  shortest paths; multi-node MC versus exact enumeration; 99% network CI coverage across 100
  predefined seeds; one/four-worker and chunk-budget equality; stable sample prefixes and tau
  monotonicity; OD-origin independence; speed units, lists, inference, coverage, self-loops and
  skip/table behavior; static attributes and scenario-time callbacks; provider validation/units;
  histogram bounds/extremes; empty/singleton/all-closed cases; config validation, pipeline merge,
  custom-model saved-config guards, overwrite cleanup and all seven generated scenarios.
- The combined Ticket 09/10 suite passed **77 tests** before the final contract/edge-case
  additions; the final targeted run above verifies the expanded 45 Ticket 10 cases.
- Independent artifact checks across all seven defaults verified finite JSON, node counts,
  sampled/null fields, CI ordering/bounds, source percentages, merged connectivity/time OD fields,
  skip behavior and ASCII reports wrapped to 100 columns. Existing probability and connectivity
  outputs remain available in every case.
- Full offline regression suite: **221 passed, 4 skipped** in **300.80 seconds**. The skips are
  the existing three live OSM tests and opt-in 60,000-node benchmark. The final targeted run also
  verifies the self-loop speed-inference guard added while regression testing was running.
- `git diff --check` and local documentation-file link validation passed. Verification used
  Python **3.13.3** in the existing temporary environment; no new dependency was required.
- You confirmed manual verification on **11 October 2026**, after reviewing the generated
  results and discussing the example names, Dijkstra time routing and the sparse report's
  `tt_reliability` value. Ticket 10 is complete; Ticket 11 has not been started.

### Additional validation follow-ups

[plan/TEST_RECOMMENDATIONS.md](plan/TEST_RECOMMENDATIONS.md#10--travel-time-reliability) now marks
the existing threshold/direction/self-pair and speed-handling recommendations as covered by
the implemented tests. Further work remains proposed: origin-sampling sensitivity, broader
interval coverage including rare failures, histogram-tail accuracy, custom-provider behavior
across workers, real-road/time-model comparisons and larger memory/disk benchmarks. These do
not block completion and have not been run for this documentation update. Existing automated
results above are preserved; no new software tests were necessary for this documentation change.

## Ticket 15 — Four-city Crucitti comparison

Ticket **15** was implemented on **11 October 2026**, ahead of Ticket 11 at your request.
It is **implemented, automatically verified and manually reviewed**. The planned-city
classification discrepancy remains open; manual review does not change the benchmark result.
The predefined four-city experiment ran successfully, but **both comparisons returned MISMATCH**.
Ticket 11 remains deferred while the Hansen/AP3 definition is considered.

### Changes

- Added `georesilience validate crucitti --out DIR`, with `--download-only`, `--offline`,
  `--inputs`, `--overwrite`, `--jobs`, `--max-memory-gb`, `--consolidation-m` and `--no-figures`.
- Added `src/georesilience/crucitti.py`: projected-square construction, frozen downloads,
  paired exact information calculations, classification, independent comparison counts,
  reports, CSV/JSON, GeoPackages and cumulative-distribution plots.
- Downloaded the four predefined **1609 m × 1609 m** OSM `all` samples. Preserved raw GraphML,
  boundary GeoJSON, provenance/checksums and a derived QGIS input copy under
  `results/ticket15-crucitti/inputs/<city>/`. Reruns verify saved GraphML/boundary hashes and
  reuse them; `--overwrite` refreshes analysis results, never source snapshots.
- The focused workflow reuses existing centrality and fitting functions. It skips link damage,
  robustness, failure probabilities, connectivity and time reliability. Every cleaned node gets
  information centrality under both conventions; no candidate-only fallback is permitted.
- Added scoped cleaning options that ignore one-way restrictions before simplification and
  select the largest undirected connected component. Ordinary analysis defaults are preserved.
- Each city writes `network.gpkg` (`nodes`, `edges`), `centralities.csv`, `summary.json` and
  `report.txt`. Node fields include `information_inverse`, `information_spatial`, betweenness,
  closeness, straightness and degree. The aggregate writes `crucitti_report.txt`, `comparison.json`,
  eight-row `comparison.csv`, `run_config.json` and two combined CCDF figures.
- Added `tests/test_crucitti.py` and README commands, report interpretation and limitations.
  Updated the ticket specification's refinement notes and the testing-recommendations backlog.
  Generated inputs/results remain gitignored; implementation, tests and documentation are source.

### Deviations and scientific conventions

The AP2 review identified definition differences, documented before implementation and retained
explicitly rather than changing Tickets 03/05/07:

1. **Two comparisons.** `framework_inverse_distance` retains existing `mean(1/d)` information
   and Ticket 07 classification. `ap2_spatial` uses AP2's `mean(d_E/d)` information, plus
   an exponential-versus-Rayleigh body comparison for betweenness. Both information efficiencies
   share each removal's Dijkstra blocks. Remove all incident edges, retain original N and
   coordinates, exclude self-pairs and give unreachable pairs zero contribution.
2. **Gaussian cumulative curve.** AP2 Fig. 3's `exp(-C²/(2σ²))` is a Rayleigh survival function;
   Ticket 07's half-normal body has a different survival function. The reference diagnostic uses
   zero-location MLEs and our 10-AIC-unit threshold. Information uses existing modern tail rules.
   These fitting procedures do not reproduce AP2's original estimation methodology; no bootstrap
   goodness-of-fit test was added. Production classification is unchanged.
3. **Exponent convention.** AP2's gamma describes its CCDF; our alpha describes a fitted density.
   Report both, using the ideal continuous relationship gamma = alpha - 1. Historical exponents
   are context, not pass targets.
4. **Fixed consolidation.** Keep the ticket's default 15 m tolerance. In validation only, the
   ordinary >=5% dead-end-change guard becomes a recorded warning. This allows the predefined
   experiment to complete without automatically changing tolerance. The observed changes below
   are substantial and materially limit interpretation. Ordinary `run` keeps its strict guard.
5. **Scope.** AP2 Ahmedabad had 2,870 nodes, so the original ticket's estimated upper size of
   about 2,000 was not reliable. Modern sample counts differ further. No original georeferenced
   AP2 windows were supplied; the ticket's approximate centres are kept fixed. A modern OSM
   comparison is not a historical numerical replication or proof of a universal city taxonomy.
6. **Statuses.** Each convention independently requires >=3/4 information matches AND >=3/4
   betweenness matches. This is a project criterion, not AP2's own test. The report heading/root
   JSON status refer to the framework result. MISMATCH exits 0; operational failures exit nonzero.
   Inconclusive fits are abstentions and never count as matches. An inconclusive network label
   can also result from a Gaussian information fit, because only power-law/exponential information
   shapes map to network labels. An interrupted analysis removes stale aggregate reports.

### Actual four-city findings

Inputs were retrieved on **11 October 2026** with OSMnx **2.1.1**, using the ticket's centres
unchanged. These timestamps describe retrieval; OSMnx response caching can affect the underlying
data vintage. Primary settings: **15 m consolidation, 2 workers, 1 GiB configured working budget**.

| City | Cleaned nodes / physical links | Framework information | AP2-reference information | Betweenness (both comparisons) |
| --- | --- | --- | --- | --- |
| Ahmedabad | 436 / 624 | gaussian | gaussian | exponential |
| Cairo | 547 / 860 | exponential | power_law | exponential |
| Los Angeles | 441 / 1,332 | gaussian | gaussian | exponential |
| Richmond, CA | 343 / 607 | power_law | power_law | exponential |

- **Framework:** information **0/4**, betweenness **2/4** → **MISMATCH**.
- **AP2 reference:** information **1/4**, betweenness **2/4** → **MISMATCH**.
- No distribution verdict was inconclusive in this run. Ahmedabad and Los Angeles nevertheless
  have inconclusive network labels because their information verdict is Gaussian.
- AP2-reference Cairo's fitted density alpha is approximately **3.11583**, corresponding to
  ideal CCDF gamma **2.11583**. This does not reproduce the paper's reported gamma 2.63.
- Following the geometry correction documented below, exact information calculations took
  approximately **6.15 s** (Ahmedabad), **11.60 s** (Cairo), **5.05 s** (Los Angeles), **4.14 s**
  (Richmond). The corrected offline analysis completed in about **40 seconds**, excluding downloads.
- Consolidation changed dead ends from **198→125 (36.9%)**, **680→196 (71.2%)**,
  **412→148 (64.1%)**, and **205→91 (55.6%)**, respectively. Inspect raw versus cleaned maps.
  No settings were changed to improve agreement. The separate no-consolidation experiment and
  window/street-type audit are documented below. The mismatch does not by itself identify which of
  sample location, modern data, network filtering, preprocessing or fitting caused disagreement.

### Verification and manual commands

- Full offline regression: **239 passed, 4 skipped** in **305.40 seconds**, including the initial
  18 Ticket 15 cases. Skips are the existing three live OSM tests and the opt-in large benchmark.
  Final targeted regression: **38 passed, 3 skipped** in **18.29 seconds**, covering all **19**
  Ticket 15 tests plus existing input/cleaning and CLI tests. This includes the additional
  undefined-efficiency/disconnected-baseline case and final provenance/CSV checks, with no warnings.
- Known-answer path: lengths 3 and 4 at a right angle give inverse efficiency **61/252** and
  AP2 spatial efficiency **19/21**; endpoint losses differ while centre isolation gives 1 in both.
  Seeded random graphs agree with independent NetworkX shortest paths to **1e-12**. Tests cover
  fixed-N disconnections, unit scaling, chunk/worker settings, zero spatial efficiency, one-way
  components, explicit cleaning warnings, input tampering/settings mismatch, offline reuse,
  report/count logic, QGIS/CSV/JSON outputs, overwrite cleanup and interrupted aggregate cleanup.
- On all four actual outputs, independently rebuilt graphs from exported GeoPackages and checked
  both baseline efficiencies and **three node removals per city** against NetworkX Floyd–Warshall
  recomputation. Scores agree within **1e-10**. Verified raw/cleaned layer counts, finite scores,
  complete information coverage, CSV match counts and JSON agreement. Both CCDF plots were
  visually inspected. Numerical tests passing does not make the empirical classification match.
- `git diff --check` and local documentation-file link validation passed. Verification used
  Python **3.13.3** in the existing temporary environment; no new dependency was required.

With your environment activated, from the repository root:

```sh
# Existing frozen inputs are ready; this reruns the four primary analyses.
georesilience validate crucitti --out results/ticket15-crucitti --offline --overwrite --jobs 2

PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_crucitti.py

# Separate sensitivity study; keep the primary experiment intact.
# Add --overwrite to rerun an existing sensitivity output directory.
georesilience validate crucitti --out results/ticket15-no-consolidation \
  --inputs results/ticket15-crucitti/inputs --offline --consolidation-m 0 --jobs 2
```

Read `results/ticket15-crucitti/crucitti_report.txt`, then each city's `report.txt` for cleaning
warnings and fit reasons. Compare node values in `centralities.csv` and `network.gpkg` with the
two figure panels. QGIS can open both `inputs/<city>/input.gpkg` and `<city>/network.gpkg` directly.
Further sensitivity and historical-data recommendations remain in
[plan/TEST_RECOMMENDATIONS.md](plan/TEST_RECOMMENDATIONS.md#15--crucitti-comparison).

### Geometry correction discovered during mismatch review — 11 October 2026

When you asked why the study mismatched, an audit found a bug introduced in Ticket 15's
undirected preprocessing. `MultiGraph.to_directed()` copies a road's geometry to both arcs
without reversing its coordinates. OSMnx consolidation assumes geometry runs from u to v
when attaching junction centroids. Wrong-way copies therefore acquired artificial backtracking
and unequal lengths; physical-link grouping could count the two directions separately.

- Corrected geometry orientation immediately after undirected conversion and before
  simplification/consolidation. Added `cleaning.arc_geometries_reoriented` for auditability.
- Added two regression cases, with and without prior simplification. Before the fix, a toy
  junction merge incorrectly produced eight physical links; after the fix it produces the
  expected four, total length **310 m**, aligned endpoints and equal reciprocal arc lengths.
- Preserved the previous outputs in `results/ticket15-crucitti-before-geometry-fix/`, labelled
  `SUPERSEDED.txt`. Recomputed all four cities in the original output directory, using the
  **same frozen input checksums, centres, 15 m tolerance and fitting rules**. The table above
  now contains corrected physical-link counts and exponents.
- Corrected total road lengths are **60.553 km**, **92.098 km**, **153.764 km**, **67.639 km**
  for Ahmedabad, Cairo, Los Angeles and Richmond. Previous values were **72.392**, **138.515**,
  **248.386**, **102.669 km**. Node counts and dead-end-change warnings are unchanged.
- **Classification verdicts and both match counts are unchanged.** Cairo and Richmond scores
  changed; Ahmedabad and Los Angeles analysis weights agree to numerical precision because
  the minimum-parallel-edge analysis had already selected the correctly oriented counterpart.
  This was a real bug, but fixing it does not explain away the remaining scientific mismatch.
- Post-fix targeted regression: **40 passed, 3 skipped** in **18.61 s**, including all **21**
  Ticket 15 cases and existing input/cleaning/CLI cases. The earlier 239-test full-suite result
  predates this correction. All four corrected outputs were independently checked for aligned
  non-loop edge endpoints, paired physical roads, both baseline efficiencies and three node
  removals per city using Floyd–Warshall. The earlier shortest-path tests had confirmed arithmetic
  on the constructed graphs; they had not checked that preprocessing preserved road geometry.

Remaining explanations require controlled experiments rather than a single claimed cause:
approximate modern windows versus historical samples, the `all` filter's street/path coverage,
substantial intersection consolidation, and modern fitting rules. For example, corrected
Richmond's AP2-reference information verdict selects a power-law **tail of 96/343 nodes**
(`p_exp ≈ 0.02185`), while its full-body exponential fit beats half-normal (`delta_aic ≈ -41.08`).
The ordered Ticket 07 rules give the qualifying tail priority; that is not a claim that the
entire distribution is power-law or that Richmond is historically self-organised. A predefined
no-consolidation study and mapped sample-window review are documented in the follow-up below.

### Consolidation sensitivity and sample inspection — 11 October 2026

At your request, compared the corrected 15 m experiment with consolidation disabled, preserving
the four frozen inputs, centres, `all` filter, two workers, 1 GiB budget and classification rules.
The additional output directory is `results/ticket15-no-consolidation/`; primary outputs remain
in `results/ticket15-crucitti/`. This is an additional diagnostic study, not a retuned primary run.

| City | Nodes: 15 m → 0 m | Links: 15 m → 0 m | Framework information: 15 m → 0 m | AP2-reference information: 15 m → 0 m |
| --- | --- | --- | --- | --- |
| Ahmedabad | 436 → 726 | 624 → 935 | gaussian → gaussian | gaussian → gaussian |
| Cairo | 547 → 2,166 | 860 → 2,676 | exponential → exponential | power_law → power_law |
| Los Angeles | 441 → 2,957 | 1,332 → 4,723 | gaussian → power_law | gaussian → power_law |
| Richmond, CA | 343 → 955 | 607 → 1,378 | power_law → gaussian | power_law → gaussian |

- Both settings returned **MISMATCH** with unchanged match counts: framework information **0/4**,
  AP2-reference information **1/4**, betweenness **2/4** in each comparison. Every betweenness
  verdict remains exponential. No distribution verdict is inconclusive; Gaussian information
  still yields an inconclusive network label under the existing mapping.
- Los Angeles' new AP2-reference power-law tail contains **98/2,957 nodes** (`p_exp≈0.02443`,
  alpha≈3.56065). Its full-body half-normal fit still wins over exponential (`delta_aic≈1023.54`),
  but the classifier's qualifying-tail rule has priority. This is not a whole-distribution or
  historical self-organisation claim. Framework tail: **854/2,957**, alpha≈5.32317.
- Richmond's no-consolidation information candidate loses significantly to lognormal
  (AP2-reference `p_ln≈0.00724`), so its power-law verdict is rejected; the body favours half-normal.
  Cairo retains its AP2-reference power-law verdict, with tail **130/2,166**, density alpha≈3.49122,
  ideal CCDF gamma≈2.49122. None of these changes establishes absolute goodness of fit.
- Exact information times were **24.00 s**, **441.95 s**, **1,478.87 s**, **49.76 s**, respectively;
  the complete zero-consolidation run took about **34 minutes**, using the same two workers and
  1 GiB configured budget. Full information coverage: **6,804/6,804 nodes** across the four cities.
- The fixed comparison shows sensitivity to consolidation but does **not** resolve the mismatch
  or isolate the effects of street representation, approximate historical windows and fitting rules.

Added [examples/inspect_ticket15_samples.py](examples/inspect_ticket15_samples.py), which works
offline on these existing results. It checks run settings, input hashes, boundary hashes,
classifier rules/thresholds, full information coverage and exported layer counts. It produces
`results/ticket15-inspection/report.txt`, street/access/service CSVs, sample-boundary metadata,
raw and cleaned maps, cluster metrics and a per-city QGIS GeoPackage. Opposite arcs are grouped
as physical segments; mixed tags count once. Raw segment counts are not intersection counts.

Verification: **49 passed, 3 skipped in 25.89 s**, including all 21 existing Ticket 15 cases,
9 new inspection cases and existing cleaning/CLI tests. The integration test checks offline
operation, output layers/maps, source byte preservation, output/source directory separation,
and tampering refusal; scientific bookkeeping tests cover reciprocal/mixed road counting,
missing tags, zero length, controlled configurations and cluster extents.
On all four actual zero-consolidation GeoPackages, independently rebuilt minimum-parallel-edge
undirected graphs and recomputed both baseline efficiencies and **three node isolations per city**
using NetworkX all-pairs Dijkstra. Scores agree within **1e-10**; all non-loop geometry endpoints
align within **1e-6 m**, CSV values agree, and all information scores are finite and covered.
The detailed check record is `results/ticket15-inspection/numerical_verification.json`.
Both runs use identical frozen GraphML hashes; boundary hashes were also verified. Primary
analysis outputs were preserved. The diagnostic maps were visually inspected; documentation
links and whitespace checks passed. Numerical correctness does not imply empirical agreement.

Street/window findings:

| City | Raw length in path/cycle categories | Raw length in service roads | Largest retained 15 m cluster | Cluster diameter | Maximum displacement across clusters |
| --- | --- | --- | --- | --- | --- |
| Ahmedabad | 1.12% | 5.47% | 22 junctions | 173.5 m | 89.3 m |
| Cairo | 6.19% | 11.35% | 280 junctions | 668.7 m | 368.5 m |
| Los Angeles | 57.82% | 14.27% | 77 junctions | 400.7 m | 211.2 m |
| Richmond, CA | 17.49% | 21.21% | 47 junctions | 196.7 m | 132.5 m |

- Path/cycle means footway, pedestrian, path, steps, cycleway and corridor. Categories are
  descriptive, not access permissions. OSMnx's `all` filter does not exclude private ways:
  explicitly private access accounts for 1.82%, 0.87%, 4.59%, 1.96% of raw length, respectively.
  Most access tags are unspecified. These figures precede largest-component selection.
- Los Angeles visibly includes many parallel path lines around its grid. Frozen GraphML does
  not retain footway/sidewalk subtype tags, so this audit cannot fully distinguish independent
  walking streets from sidewalk detail. AP2 includes pedestrian networks: excluding all walking
  streets or switching blindly to a vehicle filter would not establish equivalent representation.
- The 15 m parameter is an OSMnx **buffer radius**. Connected overlapping buffers merge
  transitively, so cluster diameter/displacement can greatly exceed 15 m. Cairo's large spoke
  pattern is a consequence of this consolidation, distinct from the already-corrected reverse
  geometry bug. Rebuilding the baseline reproduced its saved junction positions within 1e-6 m.
- The maps show irregular patterns in Ahmedabad/Cairo and grids in Los Angeles/Richmond;
  all sample coordinates, UTM extents and 1609 m scales are exported. Historical windows
  remain ungeoreferenced. AP2 Table 1 counts are supplied for context, not acceptance targets.
- **Location review:** an initial concern from Jacobs' Virginia index was superseded by more
  direct evidence: the same authors' [companion paper, §3.1/Figure 1](https://www.udsu-strath.com/wp-content/uploads/2010/06/PA2006_09.pdf)
  explicitly labels Richmond, CA. Do not infer a wrong-city error from the index alone or replace
  California with Virginia. Exact historical window matching still requires georeferencing.

Manual inspection after generating the diagnostics:

```sh
python examples/inspect_ticket15_samples.py \
  --comparison results/ticket15-no-consolidation --out results/ticket15-inspection

PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_crucitti.py tests/test_crucitti_inspection.py
```

Read the diagnostic report and CSV, then open `raw_windows.png`, `topology_comparison.png`
and `centrality_comparison.png` (overlaid positive-score CCDFs; zeros excluded).
In QGIS, open `results/ticket15-inspection/<city>.gpkg`: categorise `raw_edges` by `highway`,
toggle `edges_15m` / `edges_0m` and their nodes, and label `clusters_15m` by `merged_junctions`
or `max_displacement_m`. All layers include a square `boundary`; optionally add the OpenStreetMap
XYZ basemap for geographic context. Do not join the two node layers by ID: consolidation changes
junction identities and populations. Classifier agreement alone cannot select a valid window,
filter or tolerance. Further location, filtering and fit diagnostics remain in
[plan/TEST_RECOMMENDATIONS.md](plan/TEST_RECOMMENDATIONS.md#15--crucitti-comparison).

### Published historical networks follow-up — 11 October 2026

At your request, searched for the original graph data and found the authors'
[textbook dataset page](https://www.complex-networks.net/datasets.html#chap8) and
[cities.zip release](https://www.complex-networks.net/datasets/cities.zip). Its README explicitly
references Crucitti, Latora and Porta, Physical Review E **73**, 036125 (2006), and Latora,
Nicosia and Russo's 2017 textbook, requesting citations to both. The archive contains 20 cities,
including the 18 in AP2. This supersedes the earlier assumption that only maps or modern
reconstructions could be obtained. The archive does not contain the original GIS project,
curved road shapes, geographic registration or original statistical fitting software.

The four validation cities match AP2's N/K exactly and the companion Chaos paper's rounded
road-length means/standard deviations. The verified archive SHA-256 is
`29552883de03463dbf5c2b2df69c1583d30014f83477c355fd7cd7eb1e9c3c61`.
Author provenance plus these checks supports correspondence to the paper, without claiming
bit-for-bit identity with an unavailable 2006 working directory.

Changes:

- Added `python -m georesilience.published_cities --archive FILE --out DIR`, an offline,
  checksum-pinned runner for the published four-city data. It refuses nonempty outputs,
  copies the archive and relevant original files, and records file hashes, versions and
  input-validation results. The previous OSM experiments remain untouched.
- Cross-check `.net` connectivity against every endpoint/length-table row, with multiplicity,
  coordinate consistency, integer identifiers, finite values, positive lengths and published
  counts/length statistics. There are 199/68 repeated source edge labels in Ahmedabad/Cairo;
  use file-row identities without dropping any roads. Preserve 12/3/1/2 parallel pairs,
  respectively; metric shortest paths select the shorter parallel road.
- Extracted `analyse_graph` from the existing modern-city runner, sharing centralities,
  both exact information conventions, classification and exports without applying cleaning
  to published graphs. The modern entry point keeps its existing behaviour. Figure titles
  and source notes identify published data correctly. Undirected graph exports mark roads
  as two-way.
- All original nodes, coordinates and metric lengths are retained. No OSM downloads,
  simplification, reprojection, consolidation, coordinate rescaling or component selection
  enter this historical-data experiment. The approximately 1,560 m local coordinate span and
  small coordinate/length rounding discrepancies remain as supplied.
- Added eight offline regression cases for ingestion, malformed data, repeated labels,
  parallel-road retention/minimum distances, archive integrity, overwrite refusal, local CRS,
  full four-city output generation and hand-calculated inverse/spatial efficiencies.
  The relevant regression suite passed: **57 passed, 3 skipped** (26.35 seconds).
- Added source citations, commands, interpretation and QGIS instructions to README; updated
  Ticket 15's plan and the additional testing recommendations. The published-data run is a
  documented extension of the modern OSM plan, with the fitting rules and pass criteria unchanged.

Manual rerun, with your project environment activated:

```sh
python -m georesilience.published_cities \
  --archive results/ticket15-published/inputs/cities.zip \
  --out results/ticket15-published-rerun --jobs 2 --max-memory-gb 1
```

Read `results/ticket15-published/crucitti_report.txt`, `comparison.csv` and per-city reports;
inspect the CCDF plots and source-validation manifest. Open each city's GeoPackage in a
separate QGIS project: local engineering coordinates do not align with an OSM basemap.
The displayed straight endpoint chords can differ from the authors' `length_m` values;
Dijkstra uses those original metric lengths. The inherited `osm_way_ids` export field holds
source-table row identities in this adapter. Original labels remain in the saved text files.
You subsequently reviewed the published-data rerun manually; see the review note below.
Ticket 11 remains deferred.

Published-data results (all **5,303 nodes** evaluated, two workers, 1 GB budget; about 22 minutes):

| City | N / roads | Expected information | Obtained information (both conventions) | Expected betweenness | Framework / AP2-reference betweenness |
| --- | --- | --- | --- | --- | --- |
| Ahmedabad | 2870 / 4387 | power_law | power_law | exponential | exponential / exponential |
| Cairo | 1496 / 2255 | power_law | power_law | exponential | exponential / exponential |
| Los Angeles | 240 / 340 | exponential | gaussian | gaussian | gaussian / gaussian |
| Richmond | 697 / 1086 | exponential | gaussian | gaussian | inconclusive / exponential |

Both comparisons return **MISMATCH: information 2/4, betweenness 3/4**. This improves upon
the modern OSM experiments (framework information 0/4; reference information 1/4;
betweenness 2/4), but the project criterion requires at least 3/4 in **each** centrality.
The planned cities' `gaussian` information verdict means the existing half-normal body wins
under Ticket 07's rules; their network labels therefore abstain as `inconclusive`.

The AP2 spatial information fit gives density alpha **3.7342** / CCDF gamma **2.7342** for
Ahmedabad (paper gamma ≈2.74), and alpha **3.6663** / gamma **2.6663** for Cairo (paper ≈2.63).
These are contextual comparisons, not exact-exponent pass targets. Additional numerical
diagnostics give spatial-information Gini **0.227938** for Cairo and **0.192814** for Richmond,
matching the paper's rounded **0.23** and **0.19**. The inverse-distance Ginis are instead
0.210320 and 0.201384. This supports the paper's spatial convention for historical comparisons
without changing the production convention.

Independent verification:

- All 18 AP2 cities' N/K match the archive; `archive_inventory.json` records the checks.
  The extra two archive graphs are Irvine1/Irvine2, outside the four-city analysis.
- NetworkX all-pairs weighted Dijkstra directly on the original endpoint tables reproduces
  both baseline efficiencies and three node isolations per city, retaining original N/coordinates.
  Maximum information-score error is **3.30e-15**; maximum baseline error **1.56e-15**.
  `independent_references.json` and `numerical_verification.json` preserve the comparisons.
- Both planned cities' full weighted betweenness vectors match independent NetworkX Brandes
  calculations within **2.78e-17**; see `betweenness_verification.json`.
- Every exported node coordinate and road length matches the source table exactly; straight
  endpoint geometries align with nodes (maximum error 0 m). Archive/extracted file hashes
  remain unchanged, and each city retains all published nodes and roads.
- The long-running analysis loaded the exporter before the undirected display-flag fix;
  its four output edge layers were updated to mark `oneway=false`. Geometry, lengths, nodes
  and centralities were verified unchanged. Future runs use the corrected exporter directly;
  this one-time output correction is recorded in `run_config.json`.

Remaining disagreement must be investigated as a statistical/implementation comparison,
not attributed to modern OSM windows, street types or consolidation. Our information body
fits fix location at zero and compare full positive samples; AP2 describes cumulative curve
fits without supplying its fitting code. A relative half-normal preference does not prove
an absolute Gaussian fit. Predefined support/offset, fitting-range and goodness-of-fit checks
are recommended next; no classifier thresholds or distributions were changed to force agreement.

### Manual review of the published-data rerun — 11 October 2026

You confirmed reviewing `results/ticket15-published-rerun/` manually and observed that
Ahmedabad/Cairo receive the expected scale-free labels while Los Angeles/Richmond receive
`inconclusive`. The rerun reproduces the earlier distribution verdicts and match counts.

For both planned cities, information coverage is complete (240/240 and 697/697 nodes), with
no fitting error. Their information-distribution verdict is `gaussian`, meaning the existing
half-normal body model wins under the project rules. The final network decision accepts only
`power_law → scale-free` and `exponential → exponential` when full information is available;
`gaussian` therefore maps to `inconclusive`. This is a network-label abstention, rather than
a missing-data or unfinished-calculation result. Los Angeles has the expected Gaussian-shaped
betweenness, but betweenness is a consistency check and does not override full information.
Richmond's betweenness remains inconclusive in the framework and exponential in the AP2 reference.

Manual review is recorded. The benchmark remains MISMATCH, and the planned-city classification
discrepancy remains open. Investigate the already-recommended support/offset, fitting-range and
goodness-of-fit diagnostics on the saved centrality CSVs before changing the classifier; these
checks do not require repeating exact shortest-path/node-isolation calculations. No analysis
code, thresholds or result files were changed during this review update.

## Ticket 11 — Hansen accessibility (uniform masses)

Implemented on **12 October 2026**, after you requested using **the definition in the plan
itself**. This resumes Ticket 11 and supersedes the earlier deferral notes. The ticket is
**completed, tested and manually verified by you**, as confirmed on **12 October 2026**.
Ticket 15's scientific mismatch and Ticket 12's population work retain their existing status.

### Definition and documented clarifications

- Used exactly the plan's `A_i = sum(W_j * exp(-beta*d_ij))` for destinations j other than i
  with outbound directed distance `d_ij <= R`; beta=`ln(2)/(half_distance_km*1000)` and
  R=`half_distance_km*1000*cutoff_factor`. Uniform unit destination masses give structural
  accessibility. The network total is an unweighted sum over origins. Radius truncation
  is part of the definition and the boundary is inclusive.
- The earlier AP3 wording in the ticket is clarified: this is the plan's explicit exponential
  variant, with no claim of equivalence to the alternative expression in Taylor et al.
  No mathematical substitution was made. Road speeds and `analysis.directed_removal` do not
  change this stage's directed distance definition.
- Single-link vulnerability is exact over evaluated links. Default coverage is screening
  candidates plus analytic bridges; `all_links: true` evaluates all non-self-loop physical
  links. Unevaluated roads receive missing scores, not zero loss.
- The planned k=2 search evaluates only pairs from each node's top three single-link closures.
  Each selected pair is computed exactly, but this is not the global worst pair over all roads,
  even with `all_links: true`. The acceptance wording now states that scope explicitly.
- Retained zero-effect closures in top-three lists, because joint effects can be nonzero.
  Ties retain smaller link IDs. With no evaluated links, single vulnerability is undefined;
  with fewer than two, pair vulnerability is undefined. A=0 is separately flagged
  `isolated_in_R` and has undefined relative loss.
- The original Ada/laptop city-scale cost statements are documented as planning assumptions,
  rather than guarantees established by these small examples.

### Changes

- Added `AccessibilityConfig` with validated finite positive half-distance/cutoff, k=1 or 2
  and candidate/all-link selection; defaults match the plan.
- Added `src/georesilience/accessibility.py`: chunked truncated baseline Dijkstra,
  reversed-endpoint affected-source selection, exact source-only closure recomputation and
  exact forward/reverse small-side bridge contribution losses. No dense node-by-link matrix
  is retained; top-three state grows linearly with node count. The stage checks its working
  memory allowance and caps its worker count accordingly.
- Added an optional destination-weight vector to the computation API for Ticket 12, tested
  with unequal and zero masses. Current pipeline weights remain one; population ingestion
  and population-specific exports are still Ticket 12.
- Integrated accessibility into the normal run, resolved YAML, GeoPackage, summary, text report,
  runtime/computation metadata and three map figures. Outputs include node `hansen_a`, `vuln`,
  `vuln_link_id`, `isolated_in_R`, plus `vuln_k2` when requested; edge `access_drop` and
  `access_rank`. Extra audit fields are `access_top3_link_ids`, `vuln_k2_link_ids` and
  `access_method`. Overwrite cleanup removes stale pair fields and figures.
- Updated the connectivity report's scope sentence to point to the now-implemented separate
  Hansen analysis, replacing its previous future-stage wording.
- Added `examples/create_ticket11_demo.py`, generating seven offline scenarios, QGIS input
  copies, YAML configs, known answers and a seeded spatial manifest. Generated data/results
  remain ignored; the reproducible generator is tracked.
- Updated README with formula, configuration, report interpretation, limitations and manual
  checks. Updated the Ticket 11 specification and
  [additional testing backlog](plan/TEST_RECOMMENDATIONS.md#11--hansen-accessibility).

### Validation performed

- Focused suite: **22 passed in 5.43 seconds**:

  ```sh
  python -m pytest -q tests/test_accessibility.py
  ```

  Checks hand-computed half-distance scores and unequal masses; directed outbound routing;
  inside/exact/outside radius; zero scores and undefined results; memory/config validation;
  parallel roads, loops and zero-effect pair synergy. Five seeded nine-node directed spatial
  cases compare every single-link source loss to independent NetworkX full recomputation
  within 1e-9 and compare node/global losses and selected pair maxima. Directed/undirected
  path fixtures compare analytic bridges against full recomputation with unequal masses and
  truncated radii. Integration checks cover exports, maps, reusable configs and overwrites.
- Full ordinary offline suite: **281 passed, 4 skipped in 317.63 seconds**. The skips are the
  opt-in slow case and three live-network cases; they were not run for this implementation.

  ```sh
  python -m pytest -q
  ```

- After the connectivity report's wording update, the combined accessibility/connectivity
  regression suite passed: **55 passed in 21.95 seconds**. Refreshed all seven example output
  folders so their reports contain that final wording; the mathematical implementation did
  not change after the full-suite run.

  ```sh
  python -m pytest -q tests/test_accessibility.py tests/test_connectivity.py
  ```

- Generated and ran all seven examples, then independently compared the five small examples'
  exported node/edge values with `expected.json` (absolute tolerance 1e-12, maximum observed
  error 2.22e-16). The hand-check corrected the path fixture's expected global link loss to
  **0.6**: intact total A=2.5, post-closure total A=1, so loss=(2.5−1)/2.5. The computed result
  was already correct. The two parallel short roads each have zero single loss, but their
  joint closure gives vulnerability **0.875**, as required.
- The seed-42 spatial graph has **100 nodes and 475 roads**, with Euclidean lengths times
  sampled tortuosity in [1, 1.3]. Candidate-only/all-link runs evaluated **16 / 475 links** at
  half-distance **0.3 km**, R=**1.5 km**. Both have total A **252.11478679894805**. Mean
  vulnerability is **0.06190473582165984 / 0.18854403236432712**; all-link vulnerability is
  nondecreasing at every node and strictly larger at **81 nodes**. Verification evidence is
  saved in `results/ticket11-verification.json`. Inspected the cutoff vulnerability and spatial
  accessibility maps, including the undefined-node marker.
- These tests verify the planned formula and shortcuts; they do not establish behavioural
  validity, all-pairs optimality of k=2, or city-scale runtime/memory guarantees. Further
  sensitivity, exhaustive-pair-gap and larger frozen-network checks are in the backlog.

### Manual run and expected checks

With the project environment activated:

```sh
python examples/create_ticket11_demo.py
georesilience run --config data/ticket11-demo/two-node.yaml --overwrite
georesilience run --config data/ticket11-demo/path-k2.yaml --overwrite
georesilience run --config data/ticket11-demo/cutoff.yaml --overwrite
georesilience run --config data/ticket11-demo/parallel-k2.yaml --overwrite
georesilience run --config data/ticket11-demo/directed.yaml --overwrite
georesilience run --config data/ticket11-demo/spatial-candidates.yaml --overwrite
georesilience run --config data/ticket11-demo/spatial-all.yaml --overwrite
```

The output folders already exist from validation. Inspect **Accessibility** in each
`results/ticket11-*/report.txt`, then its `network.gpkg` node/edge attributes and three new
figures. For a quick first check, `two-node` has A=0.5 at both nodes and vulnerability=1.
`path-k2` has A=[0.75, 1, 0.75], single vulnerability=[1, 0.5, 1], pair vulnerability=[1, 1, 1]
and edge loss=0.6 for both roads. More known answers and QGIS instructions are in the
[README Ticket 11 section](README.md#hansen-accessibility-ticket-11) and generated
`data/ticket11-demo/expected.json`.

### Manual verification — 12 October 2026

You confirmed that you verified the Ticket 11 results. The checklist now marks the ticket
completed. Individual accessibility scores are stored in the GeoPackage `nodes` layer's
`hansen_a` field; `report.txt` prints total and mean accessibility rather than the complete
vector. For `path-k2`, sorting by node IDs 0, 1 and 2 gives **[0.75, 1.00, 0.75]**.

README now makes this output location explicit. The additional sensitivity, global-pair-gap
and larger-network experiments remain follow-up recommendations, not completion blockers.
No analysis code, result files or test outcomes changed during this documentation update.

## Ticket 12 — WorldPop population

Implemented and tested on **12 October 2026**. **Completed on 13 October 2026**, at your
request following manual review of the results.

### Changes and decisions

- Added validated optional `population` settings, local GeoTIFF hashes, and streamed automatic
  WorldPop acquisition. Verified `cic2020_100m` against the live REST catalogue and Maldives
  country response on 12 October 2026. This chooses the original constrained 2020 count series;
  other series are not silently substituted. Unavailable years list the available years.
- Automatic downloads validate available exact byte counts, validate the raster, and atomically
  publish the completed file and metadata. Cache hits verify SHA-256 and make no HTTP requests.
  `run_config.yaml.population_provenance` records the file/hash and automatic dataset metadata.
- Boundary clipping, nodata handling, CRS transformation and nearest-node allocation use
  rasterio, pyproj and cKDTree. Cells beyond the snap limit remain unallocated. The summary and
  report expose their count and percentage. Local raster CRSs may differ from WGS84.
- Added joint uniform/population reducers for criticality baselines, full removals and analytic
  bridges, and Hansen baselines/removals. Both weightings share affected sources and traversals.
  Reliability computes both pair fractions from each existing SCC decomposition in the same
  Monte Carlo pass, and accumulates population outside the main SCC.
- Applied the recommendations you approved: the main SCC remains largest **by node count**
  with the existing ID tie break; population does not redefine it. With `k: 2`, population
  vulnerability uses its own top three closures and exports `vuln_k2_pop` and winning link IDs.
  Pair traversals are shared when both weightings select the same pair. Hansen keeps ticket
  11's destination-only weighting and uniform aggregation over origins.
- Exported the population and weighted columns beside their uniform counterparts, weighted
  summary headlines and probability sweep, both report versions, the Population section and
  `population_map.png`. `people_disconnected` is the smaller node-count side's population for
  analytic bridges, and is undefined for other closures. Pair fractions are not person counts.
- Undefined weighted ratios remain NaN/null with zero pair mass or zero accessibility.
  Absolute population counts stay meaningful. Disabling population preserves uniform outputs;
  overwrite removes stale optional maps and columns.

### Validation actually run

- Final focused suite: **42 passed, 1 skipped in 20.38 seconds**:

  ```sh
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 MPLCONFIGDIR=/tmp/georesilience-matplotlib \
    .venv/bin/python -m pytest -q tests/test_population.py tests/test_accessibility.py \
    tests/test_centralities.py::test_outputs_and_overwrite_removes_old_figures
  ```

  The skip is the opt-in network test. This includes 19 population tests: synthetic 3×3
  rasters in geographic/projected CRSs; far cells, clipping, nodata, zero values, stable ties;
  recorded catalogue parsing, invalid years/config, streaming/cache/hash/size failure checks;
  exact all-ones equivalence; weighted accessibility and damage against independent NetworkX;
  exhaustive connectivity failure states on a five-link fixture plus a 20,000-sample check;
  zero mass; one/two-worker reproducibility with actual two-worker execution and small
  routing chunks; full output/provenance/config/overwrite checks; and a seeded **200-node**
  spatial graph with weighted baselines and evaluated removals matching NetworkX within 1e-9.
- Live WorldPop test: **1 passed in 145.52 seconds**. Downloaded the Maldives constrained
  raster, checked its georeferencing and alias, then prohibited HTTP requests and acquired it
  again successfully from cache:

  ```sh
  python -m pytest -q --network tests/test_population.py -m network
  ```

- The full ordinary offline run reported **297 passed, 5 skipped, 1 failed in 324.97 seconds**.
  The failure was an existing default-output test: adding an optional population map to the
  standard figure list made the test expect it with population disabled. Fixed this by keeping
  optional population figures separate while including them in overwrite cleanup. The failing
  test passed in the final focused suite above. All criticality/connectivity regressions passed
  in the full run; it was not repeated after the focused fixes and two additional population
  tests. The skipped cases were opt-in network/slow tests.
- Generated both offline examples on the final code, independently checked the exported
  population vectors and Hansen scores against exact sums of powers of 1/2, and checked every
  all-ones criticality/accessibility column for exact equality with its uniform version.
  Inspected the population map and checked adjacent column ordering. `git diff --check` passed.
- The installed Shapely/affine versions emit deprecation warnings for their older transformation
  interfaces; the checks pass. These tests establish formula/allocation agreement, not census
  accuracy or city-scale performance guarantees.

### Review artifacts

Run `python examples/create_ticket12_demo.py` to regenerate both controlled examples. Only
OSM download is replaced with a frozen synthetic bbox graph; real boundary handling,
projection, cleaning, allocation and analyses run. The generated YAMLs run against live OSM
if invoked directly through the CLI, so that is a different graph from the controlled demo.

- `results/ticket12-unequal-k2/report.txt`: 45 synthetic people inside the boundary, **36
  allocated and 9 unallocated (20%)**. Uniform total A is **11.9375**; population total A is
  **53.90625**. Population reliability is **0.9316263163919414**, and expected population cut
  off is **1.9755859375** under the configured length-proxy failure probabilities.
- `results/ticket12-ones-k2/report.txt`: 8 allocated and 1 unallocated. Both total A values
  are **11.9375**, and both connectivity scores are **0.9247000558035714**.
- Both folders include `network.gpkg`, `summary.json`, `run_config.yaml` and figures; shared
  headline verification is in `results/ticket12-verification.json`.

The demo rasters contain synthetic counts. The live acquisition test uses actual WorldPop.
See [README](README.md#worldpop-population-ticket-12) for configuration and metric definitions.

### Additional real-data validation — 12 October 2026

At your request, added and ran `examples/validate_ticket12_real.py` on actual roads and
population in central Malé, Maldives. This supplements the synthetic known-answer tests.
You subsequently accepted the results and requested completion on 13 October 2026.

- Fixed WGS84 bbox `[73.500, 4.167, 73.521, 4.181]`. Frozen OSM source has 1,160 nodes and
  2,059 directed edges before cleaning. Simplification, projection and largest-SCC selection
  retain **591 nodes, 1,239 directed edges and 951 physical roads**; three nodes and about
  0.950496 km of roads (1.7783%) are dropped by component selection. Consolidation is disabled.
- Overpass was unavailable (connection refusal, HTTP errors/timeouts). Downloaded the actual
  XML extract from the main OpenStreetMap map API, retained tagged highways, applied the
  project's XML drive filter and clipped shape nodes to the fixed bbox. This documented
  acquisition change affects the download/boundary method, not the population formulas.
  Included cleaned street types are primary, primary_link, secondary, tertiary, residential
  and living_street. Raw XML, filtered GraphML, boundary, raster and source metadata are frozen
  under `results/ticket12-male/inputs/`; the manifest records SHA-256 hashes and download date.
- Downloaded the actual WorldPop Maldives **constrained 2020** raster (`cic2020_100m`, dataset
  49827) through the production acquisition code. Both analyses then use its validated cache
  entry. The runner prohibits all HTTP requests in `--offline` mode and reuses the same
  cleaned graph for both limits; no synthetic graph is substituted.
- Both runs use seed 42, two workers, a 0.5 GB configured budget, half-distance 0.3 km,
  R=1.5 km, k=2 and candidate-only closure coverage (**206 evaluated roads**). Connectivity
  uses 1,024 samples with p0=0.01 and sweep [0, 0.01, 0.05]; other analysis settings are small
  and travel time is disabled. Population snap limit is the only experimental change.

| Snap limit | Boundary population | Allocated | Unallocated | Unallocated share |
| --- | ---: | ---: | ---: | ---: |
| 100 m | 190,423.954834 | 183,190.237518 | 7,233.717316 | 3.798743% |
| 500 m | 190,423.954834 | 190,423.954834 | 0 | 0% |

- The window contains **272 positive population cells**. At 100 m, 21 remain unallocated.
  Nearest-node distances range from **3.589063 m to 234.127477 m**, explaining why 500 m
  allocates all cells. The larger limit changes the population represented by weighted
  metrics; it does not change the intact road network or establish an optimal snap limit.
- The independent reference selects cell centres inside the boundary without production
  `rasterio.mask`, then searches every retained node by Euclidean distance without the
  production KD-tree. Every node's allocation matches exactly, and allocated plus unallocated
  equals clipped positive population within 1e-7. Independent NetworkX truncated Dijkstra
  checks weighted baseline Hansen scores at 20 predefined node IDs in each case. The maximum
  absolute error is **6.55e-11**, below the 1e-7 threshold. These are baseline spot checks;
  weighted closure correctness remains covered by the existing independent synthetic tests.
- Confirmed allocation is nondecreasing at every node. Uniform accessibility/vulnerability,
  information, centralities, link damage/ranks, failure counts/importance and connectivity
  agree between cases (numeric tolerance 1e-12; connectivity equality is exact).
- Weighted total accessibility is **17,525,741.479871143 / 18,085,466.95752499** for 100/500 m;
  uniform total accessibility is **57,747.10299351109** in both. Population-weighted
  connectivity is **0.9993913476433743 / 0.9994074146757825**, and expected allocated population
  outside the largest SCC is **55.87229099869728 / 56.53193402290344** persons under the
  configured independent length-proxy failure model. These reflect different allocated masses.
- Exported `allocation-overlay.png`, `population-clipped.tif`, `allocation-audit.gpkg`
  (`cells`, `snap_lines`, `boundary`), a 20-cell `sample-cells.csv`, `verification.json` and
  `validation_report.txt`, plus full analysis outputs under `snap-100m/` and `snap-500m/`.
  Inspected the overlay and its geographic alignment, shared colour scales and unallocated
  coastal cells. QGIS instructions are now in README.
- Reran the complete ordinary offline suite on the final population implementation:
  **300 passed, 5 skipped, 33 deprecation warnings in 327.14 seconds**. This supersedes the
  earlier full-run failure noted above; no production fix was needed during this validation.
  The five skips remain opt-in network/slow cases.

Reproduce with the project environment activated:

```sh
# Download/freeze once; the existing saved inputs make this step unnecessary for your review.
python examples/validate_ticket12_real.py --download-only --osm-api
python examples/validate_ticket12_real.py --offline --overwrite

# Full ordinary regression suite (ROS/plugin isolation as in the earlier tests):
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

Open `results/ticket12-male/validation_report.txt` first, then compare the two case reports.
In QGIS overlay the clipped raster, boundary, analysis roads/nodes and sampled cell-to-node
lines. README explains the fields and filtering. Generated inputs/results remain ignored;
the reproducible validation runner is tracked. New recommendations are recorded in
[plan/TEST_RECOMMENDATIONS.md](plan/TEST_RECOMMENDATIONS.md#12--population-weighting).

This is a partial-city integration and snap-sensitivity experiment with current downloaded
roads and modelled 2020 population. It does not validate census accuracy, city-scale resource
limits, nearest-junction allocation as observed travel demand or globally optimal k=2 pairs.

### Completion following manual review — 13 October 2026

You requested that Ticket 12 be marked completed after reviewing the results and discussing
the Malé reports. The checklist and ticket status now record completion, including the
synthetic examples and real OSM/WorldPop validation with both snap limits. README and the
testing backlog have been updated to match.

Additional geographic, parameter-sensitivity, detailed QGIS and performance checks remain
optional follow-up recommendations. Completion does not claim that every recommended
experiment has been performed. No analysis code, results or test outcomes changed in this
documentation update.


## Current Ticket 13 — Zone aggregation

Implemented on **13 October 2026** within the mid-evaluation scope. Automatic checks are
complete for Ticket 13; **manual review has not yet been recorded**. Ticket 14 remains not started.

### Implementation

- Added optional `zones.path`, required `id_field` and optional `name_field`. GeoJSON/GPKG
  polygons are reprojected to the graph's metre CRS. Missing fields/CRS/files, empty/invalid
  geometry, duplicate/null/blank IDs and positive-area overlaps fail before expensive analysis
  or deletion of existing outputs. Shared borders are valid.
- Assignment is inclusive point-in-polygon for nodes and the actual geometry half-length point
  for roads, including multipart/curved roads. Shared-border ties use canonical zone-ID order;
  numeric IDs sort numerically. Holes, unassigned features and empty zones are supported.
- Aggregation consumes finished node/physical-link layers and never changes routing, closure
  candidates, random samples or network metrics. Non-loop physical roads count once; loops
  receive assignments but are excluded from road totals, densities and top-link counts.
- Exported every specified zone metric, road density, assigned/unassigned reconciliation,
  contributing-score/population coverage and deterministic vulnerability ranks. Resident-weighted
  structural `vuln` is distinct from destination-weighted `vuln_pop`. Missing metrics and
  zero-denominator quantities remain null; zero-population zones are unranked when population
  weighting is active. Expected population cut off is undefined if a positive-population node
  lacks its connectivity membership probability.
- Added `zones.gpkg`, `zone_id` in network layers, `summary.json.zones`, top/bottom-ten report
  tables, resolved config and optional `zones_vulnerability_map.png`. Turning zones/figures off
  with overwrite removes stale zone artifacts. README documents definitions, coverage, midpoint
  approximation and the cited Hyderabad road-density sanity comparison.

### Validation

- **21 zone tests passed** in `tests/test_zones.py`: independent scalar arithmetic,
  population-off/on, missing scores, zero/empty zones, CRS reprojection, GeoJSON/GPKG roundtrip,
  shared borders, holes, multipolygons, overlaps/invalid inputs, stable IDs/ties, curved/multipart
  midpoint assignment, parallel roads, loop exclusions, unassigned totals and top/bottom ten.
- End-to-end tests compare every non-zone node/link field and network summary with zones off/on;
  population-weighted and uniform results stay identical. Zone expected population cut off
  sums to the network value. Long/non-ASCII names preserve JSON/GPKG names and produce an ASCII
  report at most 100 columns wide. Invalid-zone overwrite preserves existing results.
- `examples/create_ticket13_demo.py` completed both controlled nine-node runs. West/East have
  6/3 nodes, 1.0/0.2 road km and, in the population case, 27/18 residents. A third empty zone
  has zero inventory and an undefined rank. Manifest: `data/ticket13-demo/manifest.json`;
  outputs: `results/ticket13-demo/{uniform,population}/`. Both choropleths were visually inspected.
  Independent exported-layer reconciliation is recorded in `results/ticket13-demo/verification.json`;
  zone expected population cut off sums exactly to the demo network value (0.01953125).
- Actual CLI run completed using `data/ticket13-demo/uniform.yaml`, writing
  `results/ticket13-cli/`. The population demo substitutes bbox acquisition only; its YAML alone
  downloads actual roads, so reproduce its controlled grid via the demo script.
- The first full regression run found an existing Windows travel-time cleanup issue:
  **318 passed, 1 failed, 5 skipped**. A retained memory mapping masked a scenario-model validation
  error with a file-lock error. The mapping now closes in a context manager on success/error,
  without changing calculations. All **45 existing travel-time tests** and **2 new controlled
  baseline/sample failure cleanup checks** passed. Final full offline regression rerun:
  **323 passed, 5 skipped** in 607.89 seconds. Skips are the opt-in network/performance tests;
  remaining warnings are dependency deprecations and the deliberately missing-CRS fixture.

For manual review, use README's Ticket 13 instructions and inspect both demo GeoPackages,
report tables and maps. These synthetic examples establish software behavior, not actual ward
population accuracy or observed hazard vulnerability. Larger real-ward performance remains an
optional follow-up; no claim of city-scale performance is made.
