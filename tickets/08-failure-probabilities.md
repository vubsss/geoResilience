# 08 — Failure probabilities

**What to build:** each link gets a per-event failure probability `p_fail`. The user can export a template of OSM way IDs, fill in probabilities, and feed it back. Anything they don't provide falls back to a length-based proxy. The report states exactly how much of the network is covered by real values and how much by the proxy.

**Blocked by:** 02

**Status:** ready-for-agent

## Behaviour

### Config additions
```yaml
reliability:
  p_fail_csv: null          # path to the filled template
  p0: 0.01                  # proxy: per-km per-event failure probability
  p0_sweep: [0.001, 0.01, 0.05]
```

### Template export
- CLI: `georesilience template --config my.yaml --out p_fail_template.csv`. This runs loading and cleaning only, then writes the CSV.
- Library function: `export_edge_template(G)`.
- Columns: `osm_way_id`, `name`, `highway`, `length_m`, `n_links`, `p_fail` (empty).
  - One row per distinct OSM way ID found in any non-self-loop link.
  - `length_m`: the sum, over links containing the way, of link length ÷ number of ways in that link. Simplification loses per-way lengths, so this equal-share approximation is stated in the CSV header comment and in the docs.
- The first line of the file is a `#` comment explaining the meaning:
  > p_fail = probability the road is closed during ONE event/scenario (not an annual rate), in [0,1]; leave blank to use the length proxy.

### Import and validation
- `p_fail_csv` is read with `comment='#'`. Only `osm_way_id` and `p_fail` are required; other columns are ignored.
- Errors (stop the run, naming the offending rows):
  - `p_fail` outside [0, 1];
  - non-numeric values;
  - duplicate `osm_way_id`.
- Warnings, listed in the report and capped at 20 shown plus a total count:
  - IDs not present in the network;
  - blank `p_fail` values (treated as missing).

### Combination per link (the "any part fails" rule)
For a link with ways {w}:
- Covered ways C have user values `p_w`.
- The uncovered share is `s = |uncovered ways| / |ways|`.
- `p_link = 1 − Π_{w∈C}(1 − p_w) · (1 − p0)^(length_km · s)`.
- With no user data: `p_link = 1 − (1 − p0)^(length_km)`.
- `p_fail_source` = `user` (s = 0) | `proxy` (no covered ways) | `mixed`.
- A link's `p_fail` applies to all of its directed edges together: a closed road is closed in both directions.

### p0 sweep
- The library returns `p_link` for a given p0, so 09 and 10 can run each sweep value.
- The **primary** p0 is `reliability.p0`; its values go into the GPKG.
- If `reliability.p0` is not in the sweep, it is added.

### Outputs
- `edges` layer: `p_fail`, `p_fail_source`.
- `summary.json.reliability.coverage`:
  - `% links` and `% length` that are user / mixed / proxy;
  - `user_ids_unmatched` count;
  - p0, sweep.
- `report.txt` "Failure probabilities" section with the coverage table. If user coverage of length is below 50% but non-zero, add the line: "WARNING: X% of network length uses the length proxy".
- The README documents the template workflow, the per-event meaning, the combination rule, and the statement that **no road-class failure table is shipped**. Hazard presets (earthquake / flood) are future work.

## Acceptance criteria
- [ ] Template round-trip: export, fill every row with 0.1, import → every link has `p_fail_source = user`, and a one-way link made of 2 ways gets `1 − 0.9² = 0.19`.
- [ ] Proxy: a 2 km link with p0 = 0.01 gets `1 − 0.99²`.
- [ ] Mixed: a link with 2 ways, 1 covered with 0.1, 3 km long, p0 = 0.01 gets `1 − 0.9 · 0.99^1.5`.
- [ ] Validation: out-of-range values, duplicates and non-numeric values each raise with the row reported. Unknown IDs and blank values each produce warnings.
- [ ] Coverage numbers are correct on a fixture, and the warning line triggers at < 50%.
- [ ] Outputs and README section are present.
