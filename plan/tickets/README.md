# Tickets — GeoResilience Tiers 1–2

Source of truth: `../DESIGN.md`. Each ticket is a vertical slice: when it is done, `georesilience run --config <yaml>` produces new, verifiable output (GeoPackage columns, `summary.json` keys, `report.txt` sections, figures) backed by tests.

Work the **frontier**: pick any ticket whose blockers are all done.

Further validation ideas for all tickets are in
[Additional testing recommendations](../TEST_RECOMMENDATIONS.md). Completion status and results
from tests actually run are tracked in [TICKET_UPDATES.md](../../TICKET_UPDATES.md).

## Dependency graph

```
01 ─┬─ 02 ─┬────────────── 08 ── 09 ─┬─ 10
    │      │                         │
    └─ 03 ─┴─ 04 ── 05 ─┬─ 11 ───────┴─ 12 ── 13
           │            │
           └─ 06 ───────┴─ 07 ── 15
                                         14 ← 05, 06, 07, 09, 11
                                         16 ← 14
```

| #  | Ticket                                              | Blocked by         |
| -- | --------------------------------------------------- | ------------------ |
| 01 | Tracer bullet: config → graph → degree → outputs | —                 |
| 02 | All inputs + full cleaning                          | 01                 |
| 03 | Exact path-based centralities                       | 01                 |
| 04 | Screening and candidate sets                        | 02, 03             |
| 05 | Single-link criticality + information centrality    | 04                 |
| 06 | Attack vs failure curves                            | 03                 |
| 07 | Distribution classification                         | 03, 05, 06         |
| 08 | Failure probabilities                               | 02                 |
| 09 | Connectivity reliability                            | 08                 |
| 10 | Travel-time reliability                             | 09                 |
| 11 | Hansen accessibility (uniform masses)               | 05                 |
| 12 | WorldPop population                                 | 05, 09, 11         |
| 13 | Zone aggregation                                    | 12                 |
| 14 | Scorecard and final report                          | 05, 06, 07, 09, 11 |
| 15 | Crucitti replication                                | 07                 |
| 16 | Ada runbook                                         | 14                 |

## Conventions (apply to every ticket)

These are decided. Do not re-litigate them in individual tickets.

### Stack

- Python ≥ 3.10, packaged with `pyproject.toml`, import name `georesilience`, console script `georesilience`.
- Core dependencies: `osmnx` 2.x, `networkx`, `numpy`, `scipy`, `geopandas`, `pyogrio`, `shapely` 2.x, `networkit` (parallel betweenness), `powerlaw`, `rasterio`, `pyyaml`, `pydantic` v2 (config validation), `matplotlib`, `joblib`, `psutil`, `requests`.
- CLI uses `argparse` (no extra CLI framework).
- Tests use `pytest`. Network access in tests is forbidden except in tests marked `@pytest.mark.network` (skipped by default).

### Units and CRS

- All analysis happens in a **projected metric CRS**: the local UTM zone chosen by `ox.project_graph`. Lengths are in metres, β is in 1/metres.
- Output GeoPackages use the same projected CRS. `summary.json` records the EPSG code.
- User-facing coordinate inputs (bbox, OD pairs) are WGS84 lon/lat.

### Graph objects (created in 01/02, used everywhere)

- **Cleaned graph:** the osmnx `MultiDiGraph` after cleaning (ticket 02). This is the only graph ever loaded from disk or OSM.
- **Link:** a *physical road segment*, which is the unit of closure and failure. A link groups the directed edges that share the same unordered endpoint pair **and** the same OSM way-ID set **and** the same length (rounded to 0.1 m). A two-way road is one link with two directed edges; a one-way road is one link with one directed edge. Each link has an integer `link_id` that is stable within a run. **Removing a link removes all of its directed edges.**
- **Self-loop links** (u == v) are kept in the edges layer with `is_self_loop = true` and excluded from every analysis.
- **Undirected analysis graph:** one undirected edge per unordered node pair. Its weight is the minimum length among the links between that pair. Used for centralities and classification (`analysis.directed_centrality: false`).
- **Directed analysis graph:** a sparse CSR matrix over all active directed edges, with parallel edges collapsed to the minimum length. It is rebuilt from the active-edge mask whenever links are removed (O(m)). Used for removal experiments, reliability and accessibility (`analysis.directed_removal: true`).
- **Node weights W:** every metric that aggregates over nodes or pairs takes an optional weight vector, defaulting to all ones. Ticket 12 supplies population. Never hard-code uniform weights.

### Reproducibility and parallelism

- A single `analysis.seed` (default 42) feeds a `numpy.random.SeedSequence`. Each stochastic component spawns its own child sequence in a fixed order. Parallel workers get spawned child seeds, so **results are identical for any `n_jobs`**.
- Parallel workers: `analysis.n_jobs` (default: `SLURM_CPUS_PER_TASK` if set, else `os.cpu_count()`). networkit threads are set to the same value.
- Memory budget: `analysis.max_memory_gb` (default `auto` = 50% of available RAM via `psutil`). Every all-pairs computation respects it (see 03).

### Outputs

- Output column names are `snake_case`. A population-weighted variant of a column gets the suffix `_pop`.
- Missing or not-computed values are written as NaN (empty in GPKG). They are never 0.
- Every ticket that adds a metric also adds:
  - its columns to `network.gpkg`,
  - its keys to `summary.json`,
  - a section to `report.txt`,
  - its parameters to the resolved `run_config.yaml`,
  - tests.
- `report.txt` is plain ASCII, wrapped at 100 columns, with sections in pipeline order.
- Long stages log progress lines with timestamps to stderr. On Ada these end up in the SLURM output file, so flush every print.

### Validation layers (DESIGN §9)

- **Layer 1:** known-answer graphs, built in code, small, exact assertions.
- **Layer 2:** cross-check against slow NetworkX or brute-force references on about 200-node random spatial graphs. Generate these graphs from a random geometric graph with Euclidean edge lengths × U(1.0, 1.3) so they are road-like and have no ties.
- **Layer 3:** ticket 15.
