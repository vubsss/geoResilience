# Running the road-closure pipeline

`georesilience closure` enriches an already-cleaned physical road network with flood-induced closure probabilities for one event. It accepts the repository's `network.gpkg` directly. Population data and graph reconstruction are unnecessary.

## Quick start

For roads alone:

```sh
georesilience closure --roads results/hyderabad/network.gpkg --out results/hyderabad_closure
```

Every feature, including a self-loop, receives **0.01**, independent of its length. A scenario JSON can override the per-road `uniform_probability`.

For event flooding:

```sh
georesilience closure --roads results/hyderabad/network.gpkg \
  --config examples/closure/scenario.json --out results/hyderabad_closure
```

Example configuration (paths are relative to the JSON file):

```json
{
  "scenario_id": "hyderabad_example_event",
  "dem": "../../data/dem.tif",
  "rainfall": {
    "series": "event_rainfall.csv",
    "duration_hours": 6
  },
  "simulation": {"recession_hours": 6},
  "uniform_probability": 0.01,
  "threshold_m": 0.30,
  "dispersion": 0.35
}
```

The checked-in rainfall CSV is a **synthetic format example**, not a Hyderabad observation. Replace it with your event data. Timestamped CSV/NetCDF event windows determine their actual duration. `duration_hours` controls total/average/assumed scenarios; total rasters need the intended duration.

The same operation is available in Python:

```python
from pathlib import Path
from georesilience.closure import ClosureConfig, enrich_road_closures

result = enrich_road_closures(ClosureConfig(
    roads=Path("results/hyderabad/network.gpkg"),
    out=Path("results/hyderabad_closure"),
    depth=Path("data/event_max_depth_m.tif"),
))
print(result.network, result.manifest)
```

A local, fully synthetic demonstration creates a cleaned-compatible fixture and runs all five acceptance scenarios:

```sh
python examples/closure/demo.py --out results/closure_demo
```

## Solver installation and lock

Road-only and supplied-depth enrichment use the base installation. DEM simulation requires the optional NetCDF/kriging dependencies and SFINCS. A Python 3.12 environment with all transitive dependencies and hashes is locked separately:

```sh
uv venv --python 3.12 .venv-closure
uv pip sync --python .venv-closure/bin/python environments/closure-py312.lock
uv pip install --python .venv-closure/bin/python --no-deps -e .
docker pull deltares/sfincs-cpu@sha256:4301bffc74f3cb3f334be5d21aa75dfe5742a16c9838942cdfc2f870859fb404
```

Activate `.venv-closure` before running the CLI. Alternatively install `pip install -e '.[closure-simulation]'` in your own environment. The lock is the reproducible Python 3.12 setup; other Python versions resolve separately. The digest pins the official CPU SFINCS v2.4.0 Galibier release. Docker must be installed and accessible; the solver container runs without network access. The tested transitive versions are also listed in `environments/closure-py312.constraints.txt`. A native equivalent executable can be set with `simulation.executable`. The adapter checks actual completion, terrain identity, maxima, and precipitation accumulation; an error aborts publication. Full diagnostics for successful runs remain under `simulation/`.

The native FEWS rainfall reader uses **whole minutes**. Durations/interval boundaries passed to this adapter must be whole minutes. The native numerical wet/dry threshold defaults to 1 mm; censored active cells are reported dry with a road/run assumption flag. Supplied raster NoData is always unresolved, never implicitly dry.

## Input contracts

| Input / JSON key | Contract |
| --- | --- |
| `roads`, `layer` | GeoPackage, default `edges`; override with `--layer` or JSON. Unique nonempty string `link_uid`, nonmissing `u,v`, positive finite `length_m`, valid LineString/MultiLineString geometry, declared CRS |
| `dem` | One-band north-up GeoTIFF, elevations in metres, declared NoData and CRS; bare-earth terrain with relevant hydraulic barriers |
| `depth` | One-band **maximum event depth**, metres; valid zero is dry, NoData is unknown; no return period inferred |
| `depth_reference` | `ground` (default), `road` (already carriageway depths), or `water_surface` (absolute maximum water level in the same vertical datum) |
| `road_elevation_attribute` | Optional edge field containing one constant road/deck elevation per feature in metres; missing values unresolved on tagged structures |
| `flood_zones` | Optional categorical raster of positive hydraulic partition IDs, supplied by an analyst: one connected wet body per ID, separating/excluding barriers and dry boundaries |
| `domain` | Optional georeferenced polygon layer defining hydrologic simulation extent, clipped to available DEM; never a road buffer by default |
| `landcover` | Optional WorldCover class raster; nearest-neighbour reprojection and small same-source gap recovery |
| `soil_groups` | Optional categorical raster: 1=A, 2=B, 3=C, 4=D; convert dual/other source codes first; absent/unknown values use C when deriving CN |
| `curve_number_map`, `roughness_map` | Optional one-band CN `(0,100]` and Manning `(0,0.5]` rasters, taking precedence over the class lookup where valid |
| `failure_template` | Optional fingerprint-bound CSV from `failures-template` for this exact cleaned network |

Road geometry, endpoints, CRS, attributes, and identifiers survive unchanged. The output road layer is always `edges`, even with an input layer override; `nodes` is retained when present. Other input layers are not copied. No simplification, splitting, consolidation, or cleaning is performed. Existing `p_fail,p_fail_source` become `input_p_fail,input_p_fail_source`. Existing fields with either provenance name are rejected to avoid ambiguity. This also prevents accidentally enriching the same derived output twice.

Bridge, elevated, covered, tunnel and nonzero-layer tags are treated conservatively. Without a supplied road-surface depth or road/deck elevation, affected features use the uniform fallback with `structure_carriageway_elevation_unknown`. Ground-depth conversion with a deck elevation also requires terrain. Untagged roads are assumed at ground level. A dry ground cell cannot establish flooding on a below-ground carriageway; that contribution remains unresolved. Hydraulic connectivity is an explicit assumption when projecting water levels to a carriageway. This cannot identify untagged structures or guarantee vertical-datum consistency.

Default operation ignores existing probabilities. Explicit `use_existing_probabilities: true` uses valid original `p_fail` values **only for the unresolved contribution**, overriding the uniform prior for those roads. This exceptional opt-in is labeled `input_probability`/`hybrid_input`; it can reintroduce old length-based priors if the supplied probabilities were length-based. Leave it false for the requested uniform behavior.

## Rainfall formats and precedence

Choose one event source. Missing event coverage is reconstructed where supported, then uses supplied average rainfall, then 100 mm over the event window. The assumed duration is six hours. Average intensity is multiplied by duration; a representative total is distributed uniformly across that duration. Neither average nor assumed forcing receives a return period.

### Uniform time-series CSV

```csv
start_utc,end_utc,rain_mm
2020-10-13T00:00:00Z,2020-10-13T01:00:00Z,12
2020-10-13T01:00:00Z,2020-10-13T02:00:00Z,18
```

Set `rainfall.series`. `rain_mm` is the **amount accumulated during the row's interval**. Timestamps must include UTC offsets. Blank amounts mean missing; zero means observed dry. Duplicate/overlapping intervals are errors. The event spans the first start to last end, so include blank leading/trailing intervals if they are part of the intended event. Only one isolated interior missing interval bounded by complete observations is linearly reconstructed in time; longer gaps use the fallback hierarchy. Rebinning conserves observed accumulation.

### Stations CSV

Add `station_id,x,y` to the same schema, with fixed unique locations. Set `rainfall.stations` and `rainfall.station_crs` (default EPSG:4326; x=longitude, y=latitude). Each station has its own nonoverlapping accumulation intervals. Screen gauge quality before ingestion; this implementation validates schemas/coordinates/timestamps/amounts but cannot detect every instrument bias.

Baseline reconstruction is bounded IDW, power 2, up to eight neighbours. With at least five distinct gauges, leave-one-location-out validation compares IDW with a uniform mean; with at least ten and a stable spherical variogram it also considers ordinary kriging. Choose the eligible lowest RMSE method, retain exact gauge observations, and use IDW for limited extrapolation. With fewer gauges, record insufficient validation. One gauge implies an explicit uniformity assumption within the support bound.

Defaults: nearest observation ≤10,000 m and extrapolation ≤2,000 m beyond the observation convex hull. Override `support_distance_m` and `extrapolation_distance_m`. Unsupported areas use average/assumed forcing. These bounds are project settings, not universal validity thresholds.

### Gridded forcing

`rainfall.raster` is an event-total GeoTIFF in mm with declared CRS/NoData and duration. `rainfall.netcdf` uses a variable named `rain_mm` (override `netcdf_variable`), dimensions `(time,y,x)`, units `mm` for interval amounts or `mm/hour` for rates, a `time_bounds(time,bounds)` variable with decoded UTC interval endpoints, regular cell-centre `x,y`, and global `crs` such as `EPSG:32644`. Incomplete grids use bounded IDW inside the same configured support/extrapolation limits; grid cells are not counted as independent gauges for cross-validation. Isolated missing NetCDF intervals can be interpolated between complete adjacent observations. Values beyond supported reconstruction are unresolved; missing amounts are not zero. Continuous rainfall is reprojected bilinearly; categorical maps use nearest neighbour.

### Average and assumed rainfall

```json
{"rainfall": {"average_value": 20, "average_units": "mm/hour", "duration_hours": 6}}
```

This creates 120 mm over six hours, labeled `representative`. `average_units: "mm"` is an event total. `mm/day` is an explicitly converted intensity. `mm/month` or `mm/year` require `climatology_event_total_mm`; an annual/monthly climatology can never silently become a short event. Omitting average/event forcing uses `assumed_total_mm: 100`, labeled `synthetic`. A six-hour recession follows rainfall unless overridden.

## Recovery and provenance

DEM holes are filled only when enclosed and no more than three source cells across either axis, using local linear interpolation. The three-cell limit is enforced before computational coarsening. Existing depressions/elevations are preserved. Large holes and terrain outside coverage remain absent. A supplied domain can reduce computational extent; default spacing is max(20 m, native DEM equivalent resolution). `simulation.resolution_m`, `max_cells` and `max_forcing_values` allow explicit resource overrides.

Flood gaps require `flood_zones` with an analyst-established connected wet partition and valid wet neighbours; small gaps only. With terrain, water level is reconstructed then converted back to depth. No observed footprint is expanded by proximity. If a DEM covers unresolved observed depths, SFINCS supplies missing coverage; supplied usable event depths remain authoritative. Simulation boundary cells remain unresolved rather than being mistaken for dry roads. Wider missing coverage receives uniform fallback.

A valid DEM with fewer than nine usable computational cells, or no interior cells after boundary preparation, cannot support a simulation. The run records `simulation_unavailable` and uses the uniform fallback for unresolved roads while retaining usable supplied depths. Malformed inputs, resource-limit errors, and failed solver runs still abort publication.

Model-wide flags are applied to roads using simulated depths whenever recovered terrain, interpolated/assumed rainfall, or defaults can affect contributing areas. A local pixel-only flag would understate uncertainty. Method details, input hashes, support masks, parameters, validation scores, and assumptions are retained in the manifest and associated raster/JSON artifacts. The `resolved_rainfall.npz` archive retains per-interval rates, codes and support distances; `*_reconstruction_support_m.tif` files retain recovery support distances. Geographic raster distances use local geodesic cell scale. No final probabilities are spatially interpolated.

## Outputs

```text
network_with_closure.gpkg  # edges + original nodes when present
closure_manifest.json     # complete status, hashes, config, versions, validation, artifacts
coverage_report.txt       # readable coverage and assumptions
maximum_depth.tif         # when simulation runs
simulation/               # terrain, parameter maps, rainfall, support, native inputs/outputs/logs
failure_probabilities.csv # only when a valid template is supplied
sensitivity.csv           # only when enabled
```

Edges receive `p_fail,p_fail_source,depth_source,max_depth_m,depth_coverage,rainfall_source,reconstruction_flags,scenario_id,calibration_status,model_version,assumption_flags`. Probability sources are `depth_fragility`, `hybrid_uniform`, and `uniform_default` under default operation. A mixed supplied/simulated/reconstructed hazard is labeled `mixed`. The scientific equations, citations and parameter evidence are in [road_closure_research.md](road_closure_research.md).

All inputs are checked/hashed and the output is built in a staging directory. Inputs changing during a run, invalid geometry/values, template mismatches, failed/truncated solver outputs, or export identity changes abort publication. A previous completed result survives a failed overwrite. `--overwrite` replaces a prior closure output and preserves unrelated files; it refuses an unrelated nonempty directory.

## Existing analysis integration

Generate the template from exactly the network/cleaning settings used for the cleaned export:

```sh
georesilience failures-template input/hyderabad --no-consolidation --out failures_template.csv
georesilience closure --roads results/hyderabad/network.gpkg --config scenario.json \
  --failure-template failures_template.csv --out results/hyderabad_closure
georesilience run input/hyderabad --no-consolidation --out results/hyderabad_reliability \
  --failure-probs results/hyderabad_closure/failure_probabilities.csv --require-complete-failures
```

Use the correct cleaning options rather than copying `--no-consolidation` if your original export consolidated roads. The template must have exactly the non-self-loop `link_uid` set. Its fingerprint is retained, and a sibling original `run_manifest.json` is checked when available. The existing analysis verifies the fingerprint and complete probabilities again. Self-loops are omitted **only from this CSV**, matching the existing parser; they remain enriched in the GeoPackage. Completeness enforcement prevents the old analysis from inserting length proxies.

## Sensitivity and software testing

Enable with `"sensitivity": {"enabled": true}`. Default scenarios vary rainfall ×0.8/1.2, assumed CN 70/95, threshold 0.20/0.50 m, and uniform prior 0.001/0.05. Override the corresponding lists (`rainfall_multipliers`, `assumed_curve_numbers`, `thresholds_m`, `uniform_probabilities`). Rainfall/CN scenarios rerun the physical model; CN variation applies only when CN is assumed. With supplied depths alone, only threshold/uniform variants apply; any simulated missing-depth contribution can also be varied while supplied usable depths retain precedence. `sensitivity_range.csv` reports scenario minima/maxima. These are **sensitivity scenarios, not confidence intervals**.

Run the offline suite with `python -m pytest`. Real solver acceptance tests are opt-in:

```sh
GEORESILIENCE_TEST_SFINCS=1 python -m pytest tests/integration/test_closure_sfincs.py
```

The synthetic tests verify software behavior for roads-only, event, average, assumed rainfall and partial reconstruction. They do not establish local predictive skill; outputs remain `calibration_status=assumed` until local calibration is implemented and independently validated.
