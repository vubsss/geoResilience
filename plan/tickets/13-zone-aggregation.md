# 13 — Zone aggregation

**What to build:** the user supplies zone polygons (e.g. GHMC wards) and gets per-zone results in `zones.gpkg`: which ward is most vulnerable, per capita and in absolute terms. Zones are used **only for aggregation**. They never change the analysis.

**Blocked by:** 12

**Status:** ready-for-agent

## Behaviour

### Config additions
```yaml
zones:
  path: null            # GeoJSON/GPKG polygons
  id_field: null        # required when path is set
  name_field: null      # optional
```

### Assignment
- Reproject the zones to the graph CRS.
- Nodes → zone by point-in-polygon. Nodes outside every zone → `zone_id` = null, counted in the report.
- Links → zone by the **midpoint of the link geometry**.
- Overlapping zones → error, listing the overlapping IDs (wards must form a partition).

### Per-zone metrics (one row per zone; NaN where the source metric wasn't computed)
- `n_nodes`, `road_km`, `population` (sum; NaN if 12 was off), `road_km_per_1000_pop`.
- `bridge_km_frac`: bridge length / road length.
- `mean_p_connected`, `pop_weighted_p_connected`.
- `mean_hansen_a`, `mean_hansen_a_pop`.
- `mean_vuln`, `pop_weighted_vuln`, `p90_vuln`.
- `expected_pop_cut_off`: the sum over the zone's nodes of population × (1 − p_connected).
- `n_top50_critical_links`: links in the zone that are among the top 50 by `crit_rank`.
- `n_top50_access_links`: the same, by `access_rank`.
- `rank_vulnerability`: zones ranked by `pop_weighted_vuln` if population is present, else by `mean_vuln`. 1 = most vulnerable.

### Outputs
- `zones.gpkg`, layer `zones`: the zone geometry, `zone_id`, `zone_name` and the metrics above.
- `nodes` and `edges` layers gain `zone_id`.
- `summary.json.zones`: zone count, unassigned nodes, and the top 10 zones by `rank_vulnerability`.
- `report.txt` "Zones" section: the top 10 and bottom 10 zones with key metrics.
- Figure: a choropleth of `rank_vulnerability` (or `pop_weighted_vuln`).
- The ward road density (`road_km` / zone area in km²) is included as a column. The README mentions the sanity check against the 7–47 km/km² range in Samal et al. (2025) for Hyderabad.

## Acceptance criteria
- [ ] Fixture: 2 square zones over a small grid graph. Node and link counts, `road_km` and population sums per zone match hand computation.
- [ ] Overlapping zones raise an error. A missing `id_field` raises an error.
- [ ] Nodes outside all zones are counted and reported, and the run does not crash.
- [ ] Running without zones produces no `zones.gpkg` and no `zone_id` columns.
- [ ] Outputs (gpkg, summary, report, figure) are present.
