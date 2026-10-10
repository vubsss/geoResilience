# GeoResilience

GeoResilience analyzes road network structure and resilience. Ticket 1 supports **graphml (more in 02)**.

Install in an environment with Python 3.10 or newer:

```sh
python -m pip install -e .
```

Create `my.yaml`:

```yaml
input:
  source: graphml
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

Run `georesilience run --config my.yaml`; add `--out results/` to override the configured output directory. Existing non-empty output folders require `--overwrite`. The run writes `network.gpkg`, `summary.json`, `report.txt`, `run_config.yaml`, and (when enabled) `figures/degree_hist.png`.

Run the offline test suite with `python -m pytest`.
