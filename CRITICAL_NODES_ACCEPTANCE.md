# Critical nodes and 2SFCA acceptance record

Date: 2026-11-06 (Asia/Kolkata). Branch: `feature/critical-nodes-2sfca`.
All nine implementation tickets and nine testing tickets are complete, each in a
separate commit. [CRITICAL_NODES_PROGRESS.md](CRITICAL_NODES_PROGRESS.md) records
per-ticket scope and verification; [README.md](README.md) provides runnable usage.

## Regression and numerical checks

The complete offline suite passed: **349 passed**, 117 warnings, 12.64 seconds
on the final run. Warnings are Shapely/affine deprecations and an intentional
missing-CRS fixture warning; no failures or network access. The project virtual
environment lacked pytest, so its Python interpreter loaded the system pytest
package while retaining the project's GIS dependencies. No dependency files or
user environment configuration were modified. Normal setup is
`python -m pip install -e ".[test]"`, followed by `python -m pytest -q`.

Coverage includes strict CSV/config/CLI contracts, leading-zero IDs, projected
inclusive stable snapping, separate co-located identities, count/unit invariance,
independent directed path and 2SFCA oracles, exact cutoff boundaries, closure
competition, conservation, fixed denominators, missing/zero states, screened/all
coverage, worker-independent shared failure draws and unchanged legacy outputs.

The user refinement is verified independently:
`node_importance_i = population_importance * P_i/sum(P) + w_i/sum(w)`.
Population-only nodes receive importance; zero-population facility nodes retain
service importance. Missing rasters in service-enabled runs use uniform node
demand; a supplied all-zero raster remains zero. Both components, their units,
coefficient and demand basis are exported. Combined importance has its own attack
curve/AUC, while standard service accessibility still targets real facilities.

## Reference review

Rendered and visually inspected `papers/VNB1-sfca.pdf`, PDF page 8 / printed
page 872. Equations (3)/(4) use supply divided by catchment population, then sum
ratios over facilities within the resident's catchment. Thresholds are inclusive.
The independent oracle reproduces the page's unit-supply demand examples 8 and 4
and overlap accessibility 1/8 + 1/4 = 3/8. Transpose routing preserves the same
resident-to-facility direction on directed roads. Applying this to supplied
school/hospital capacities, closure shortfall, uniform fallback and combined node
importance are documented project choices rather than paper claims. Standard
2SFCA has no within-catchment decay and no clipping of raw scores.

## Documented examples and output inspection

Executed both README commands against the checked-in synthetic fixtures:

- Weights-only: `/tmp/georesilience-service-weights`; unknown capacity remains
  null and 2SFCA is explicitly unavailable.
- Capacity-aware: `/tmp/georesilience-service-sfca`; three string IDs remain
  `001`, `002`, `003`, attached to retained nodes `0`, `8`, `0`. Demand totals
  45, school capacity totals 200 synthetic seats and hospital capacity totals 12
  synthetic staffed beds. All nodes' baseline indices are respectively 200/45
  and 12/45; their raw values are preserved. Provenance remains declared synthetic.
- Figure-enabled check: `/tmp/georesilience-service-visual`. Visually inspected
  all six service figures and the four-view attack curve. Titles, units and
  legends are legible. Fixed constant-field colourbar normalization by setting
  explicit zero-based bounds and wrapping long titles. Regenerated and reviewed
  all six maps after the fix; the full suite passed afterwards.

Inspected report.txt categories, units, capacity sources, means and separate
node/link shortfall rankings; GIS node/link fields, WGS84 original facility
geometry, mappings, demand and ratios; manifest settings/provenance and added
attack columns. Automated tests verify XML and GraphML, uniform fallback,
replay equality, facility checksum rejection, input collisions, changes both
during computation and staging, and enabled-to-disabled overwrite cleanup while
preserving unknown user files. No-service schema/file-set tests pass unchanged.

## Moderate resource workload

Reproduce with `python -m tests.helpers.service_benchmark` after installing the
project. The helper uses local synthetic inputs and includes serial/parallel
agreement, conservation, chunk-count and no-N-by-N-query assertions.

| Setting/result | Measured value |
| --- | --- |
| Original nodes / directed arcs | 4,000 / 8,000 |
| Facilities | 240 (120 schools, 120 hospitals) |
| Cutoffs | 2 minutes school, 3 minutes hospital |
| Workers / workspace budget | 2 / 8 MiB |
| Warm 2SFCA runtime | 0.0927 seconds |
| Passes | 4 (two per category) |
| Sources / chunks per pass | 120 / 18 |
| Maximum distance block | 7 × 4,000 = 224,000 bytes per task |
| Baseline / peak sum process-tree RSS | 407.453 / 409.266 MiB |
| Baseline / peak sum process-tree USS | 287.918 / 289.258 MiB |
| Peak above baseline RSS / USS | 1.812 / 1.340 MiB |
| Conservation residuals | school 0; hospital 0 |
| Serial / parallel indices | equal within rtol=atol=1e-12 |

Memory sampling sums the parent and all recursive worker processes every 10 ms,
after warming both loky workers. USS avoids double-counting shared physical pages;
RSS is also reported as a conservative process sum. Baseline/peak include graph,
output, interpreter and allocator storage, so their difference is an observed
increment rather than an exact isolation or hard proof of the workspace cap.
Instrumented routing recorded 7-row bounded blocks and 18 chunks on every pass;
no dense N-by-N query or retained resident-by-facility matrix was used. One full
float64 N-by-N matrix alone would be 128,000,000 bytes. Runtime excludes graph/CSV
preparation, worker startup, local closure sweeps and Monte Carlo simulation and
is not a city-scale end-to-end performance claim.

## Remaining study limitations

Real runs still need local facility locations, capacities, units, sources/years,
justified importance coefficients/catchments and defensible speed/time data.
Total-population school demand is a proxy; boundary edge effects are uncorrected.
Screened candidates can miss the most critical closure; all-mode is complete.
Age-specific demand, external POI/capacity acquisition, enhanced 2SFCA and full
2SFCA recalculation at every attack/Monte Carlo step remain explicitly deferred.
Graph, geometry and outputs are outside the routing workspace budget.

The pre-existing `.gitignore` changes and untracked supplied PDF were preserved
outside ticket commits. No publishing or external data acquisition was performed.
