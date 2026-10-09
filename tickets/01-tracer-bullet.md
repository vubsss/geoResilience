# 01 — Tracer bullet: config → graph → degree → outputs

**What to build:** a user writes a minimal YAML config pointing at a `.graphml` file, runs `georesilience run --config my.yaml`, and gets an output folder with all five artefact types filled in for the simplest metric (degree). This sets up the package, config system, link model, output writers and test harness that every later ticket extends.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

## Behaviour

### CLI
- `georesilience run --config PATH [--out DIR]`. `--out` overrides `output.dir`.
- Exit code is 0 on success and non-zero on config or validation errors. The error message names the offending key.
- `georesilience --version` prints the package version.

### Config (pydantic v2 model)
- **Unknown keys are an error**, so typos fail loudly.
- Every section has defaults. The **resolved** config, with defaults filled in, is what gets written to `run_config.yaml`.
- Sections introduced in this ticket:

```yaml
input:
  source: graphml          # this ticket: graphml only; 02 adds place | polygon | bbox | osm_xml
  path: data/city.graphml
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

- Later tickets add their own sections (`network`, `cleaning`, `criticality`, `robustness`, `reliability`, `travel_time`, `accessibility`, `population`, `zones`, `composite`). Design the model so that adding a section is local: one sub-model per section.

### Pipeline (this ticket's version)
1. Load the graphml with `ox.load_graphml`.
2. If the graph's `simplified` graph attribute is not true, run `ox.simplify_graph`.
3. Project with `ox.project_graph`.
4. Build the **link table** (see README conventions). Compute the link's `osm_way_ids`:
   - Union of the `osmid` attribute across the link's directed edges. `osmid` may be an int or a list, so normalise it to a sorted list of ints.
5. Build the undirected analysis graph. Compute:
   - `degree` = number of distinct neighbours (self-loops excluded).
   - `degree_centrality` = degree / (N − 1), per Crucitti.

### Outputs (folder `output.dir`; refuse to run if the folder exists and is non-empty, unless `--overwrite`)

`network.gpkg`
- Layer `nodes`: `node_id`, `x`, `y`, `degree`, `degree_centrality`, geometry (point).
- Layer `edges`: one row per **link** with `link_id`, `u`, `v`, `osm_way_ids` (comma-separated string), `name`, `highway`, `length_m`, `oneway` (true if one directed edge), `is_self_loop`, geometry (the edge's geometry if present, else the straight line).
  - List-valued OSM attributes are joined with `;`.

`summary.json`
- `meta`: package version, UTC timestamp, input description, CRS EPSG code, node count, link count, directed edge count.
- `metrics.degree`: mean, max, and the histogram as a {degree: count} map.

`report.txt`
- A header with the run metadata.
- Section "Network" with counts.
- Section "Degree" with the histogram as text.

`run_config.yaml`
- The resolved config, plus a `versions` block (python, osmnx, networkx, scipy, networkit, numpy).

`figures/degree_hist.png`
- A degree histogram (only if `output.figures`).

## Acceptance criteria
- [ ] `pip install -e .` provides the `georesilience` command.
- [ ] A config with an unknown key fails with a message naming the key.
- [ ] An end-to-end test builds a tiny graphml fixture **in the test** and runs the CLI on it, then asserts that all five artefacts exist and that `summary.json` counts match. The fixture is a 3×3 grid of two-way streets, 100 m spacing, plus one one-way street and one self-loop.
- [ ] Link-model tests:
  - A two-way street becomes 1 link with 2 directed edges.
  - A one-way street becomes 1 link with `oneway = true`.
  - Two distinct parallel ways between the same nodes become 2 links.
  - A self-loop becomes a link flagged `is_self_loop` that is excluded from degree.
- [ ] Degree on the 3×3 grid: corners 2, edges 3, centre 4.
- [ ] `run_config.yaml` can be fed back to `georesilience run` and reproduces an identical `summary.json`, apart from the timestamp.
- [ ] The README states the supported input as "graphml (more in 02)".
