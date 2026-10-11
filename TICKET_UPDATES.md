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
- [ ] **10 — Travel-time reliability** — not started.
- [ ] **11 — Hansen accessibility (uniform masses)** — not started.
- [ ] **12 — WorldPop population** — not started.
- [ ] **13 — Zone aggregation** — not started.
- [ ] **14 — Scorecard and final report** — not started.
- [ ] **15 — Crucitti replication** — not started.
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
Tickets 04–09 are documented below; tickets 10–16 have not been started.

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
Tickets 06–09 are documented below; tickets 10–16 have not been started.

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
Tickets 07–09 are documented below; tickets 10–16 have not been started.

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
Tickets 08–09 are documented below; tickets 10–16 have not been started.

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
spatial examples. Ticket 09 is documented below; tickets 10–16 have not been started.

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
removal experiments retain their existing fraction-based behavior. Ticket 09 uses and Ticket 10 can reuse
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

## Current ticket: 09 — Connectivity reliability

Ticket **09** was implemented on **11 October 2026** and is **completed for now at your request**,
as confirmed on **11 October 2026**. Additional validation remains separate follow-up work in
[plan/TEST_RECOMMENDATIONS.md](plan/TEST_RECOMMENDATIONS.md#09--connectivity-reliability-priority-follow-up).
Tickets 01–08 retain their completed status. Tickets 10–16 have not been started.

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
  performed. No new experiments were run for this documentation update. Ticket 10 has not started.
