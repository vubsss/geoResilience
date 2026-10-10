# Ticket implementation status

- [x] **01 — Tracer bullet: config → graph → degree → outputs** — implemented. See [ticket](plan/tickets/01-tracer-bullet.md).
- [ ] **02 — All inputs + full cleaning** — not started.
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
