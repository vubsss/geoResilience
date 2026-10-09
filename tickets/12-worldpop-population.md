# 12 — WorldPop population (Tier 2)

**What to build:** given a study boundary, the tool obtains WorldPop population (from a local GeoTIFF or a cached automatic download), assigns it to graph nodes, and adds **population-weighted** versions of accessibility, reliability and link criticality. "Trips cut" becomes "people cut off". Without population, everything still runs with uniform weights.

**Blocked by:** 05, 09, 11

**Status:** ready-for-agent

## Behaviour

### Config additions
```yaml
population:
  worldpop: null        # null (off) | auto | path/to/file.tif
  iso3: IND             # used when worldpop: auto
  year: 2020
  product: constrained_100m
  cache_dir: ~/.cache/georesilience/worldpop
  snap_max_m: 500
```

### Acquisition
- `path`: use the file as given; record its path and SHA-256.
- `auto`:
  - Query the WorldPop REST catalogue (`https://hub.worldpop.org/rest/data/pop/<alias>?iso3=<ISO3>`) for the **constrained 100 m** dataset, and pick the entry for `year`.
  - **At implementation time, verify the current dataset alias** for constrained 100 m in the catalogue (WorldPop has published several constrained series). Hard-code the verified alias in one constant, with a comment giving the verification date.
  - Download with a streaming request into `cache_dir`, and verify the size against the catalogue's metadata if provided. If the cached file exists, skip the download.
  - Record the dataset alias, the URL, the year and the file SHA-256 in `run_config.yaml`.
- A requested year that doesn't exist → error listing the available years.
- `population` requires a **study boundary** (02). If the input has none (graphml / osm_xml), error: "population needs input.source place | polygon | bbox".

### Allocation
- Clip the raster with the study boundary: `rasterio.mask`, with the boundary reprojected to the raster CRS (EPSG:4326). Treat nodata as 0.
- Cell centres with population > 0 → projected to the graph CRS → assigned to the nearest analysis node (`scipy.spatial.cKDTree`).
- Cells with snap distance > `snap_max_m` are **unallocated**. Report their total population and their share of the total.
- Node `population` = the sum of the assigned cells.

### Wiring W = population into existing metrics (no new algorithms)
- 05: re-run the damage pass for candidate links and analytic bridges with W, writing `eff_drop_pop` and `disc_pair_frac_pop`.
  - In the weighted efficiency, pair weight = `W_i W_j`.
  - Reuse the affected-source sets; run both weightings **in the same pass**, so there is no second traversal.
- 09: in the same Monte Carlo pass, also accumulate
  - `conn_reliability_pop` (weighted pair fraction),
  - `expected_pop_cut_off` = E[Σ population outside the largest SCC].
- 11: `hansen_a_pop`, `vuln_pop`, `access_drop_pop` and `access_rank_pop`. These use the same affected-source sets, with A computed for both weightings in the same pass.
- The uniform-weight columns stay. `_pop` columns are added next to them.

### Outputs
- `nodes` layer: `population`, plus the `_pop` columns above.
- `edges` layer: the `_pop` columns above.
- `summary.json.population`: total allocated, unallocated (and %), year, alias, `snap_max_m`.
- `summary.json`: the `_pop` headline metrics next to the uniform ones.
- `report.txt` "Population" section, including the line "WorldPop is a modelled estimate, not a census". The Accessibility and Reliability sections show both versions. The critical-link table adds `people_disconnected` = `disc_pair_frac_pop` expressed in persons where meaningful: for analytic bridges, the population of the small side.
- Figure: a population-per-node map.

## Acceptance criteria
- [ ] Allocation test: a synthetic 3×3 GeoTIFF written in-test, with a known node layout:
  - each cell goes to the expected nearest node;
  - one far cell is unallocated and reported.
- [ ] Clipping test: cells outside the boundary contribute 0.
- [ ] `auto` download is tested under `@pytest.mark.network` with a small country (e.g. `MDV`) and caching is verified (the second run makes no request). There is an offline test of catalogue-response parsing with a recorded JSON fixture.
- [ ] Weighted metrics with all-ones W equal the unweighted metrics exactly.
- [ ] Weighted reliability matches exact enumeration on a ≤ 15-link fixture with non-uniform W.
- [ ] A clear error appears when no study boundary exists.
- [ ] Outputs (columns, summary, report, figure) are present.
