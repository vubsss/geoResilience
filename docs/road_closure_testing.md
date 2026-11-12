# Road-closure software testing

These checks verify implementation behavior using synthetic inputs. They do not measure predictive accuracy against observed floods or closures. Outputs remain uncalibrated scenario estimates with `calibration_status=assumed`; the scientific basis and parameter assumptions are documented in [road_closure_research.md](road_closure_research.md).

Install the package and test dependencies in your development environment:

```sh
pip install -e '.[test,closure-simulation]'
```

For a reproducible solver environment, follow the locked Python 3.12 setup in [road_closure_pipeline.md](road_closure_pipeline.md), then install pytest separately.

## Functional checks

```sh
python -m pytest tests/test_road_closures.py -q
```

The tests cover uniform probabilities across unequal road lengths and self-loops; preservation of network geometry, CRS, identifiers, attributes and nodes; original probability provenance; dry versus unknown depth; one fallback contribution per partially supported road; carriageway elevation handling; bounded spatial and temporal rainfall recovery; rainfall accumulation and climatological units; terrain gap limits; connected water-surface reconstruction; categorical parameters; transactional publication and solver failure; sensitivity scenarios; and fingerprint-bound CSV replay through the existing analysis interface.

## Real solver checks

Docker must be available, with the image pinned in `environments/sfincs-image.txt`. Enable these tests explicitly:

```sh
GEORESILIENCE_TEST_SFINCS=1 python -m pytest tests/integration/test_closure_sfincs.py -q
```

The cases use synthetic terrain and a cleaned-compatible network. They exercise event rainfall, average rainfall, assumed rainfall, partial station/terrain reconstruction, and a dry event. They check solver completion, forcing accumulation, maximum-depth export, supported and unsupported roads, contributing-area provenance, and sensitivity variants. Roads-only enrichment is checked without invoking the solver.

## Inspectable demonstration outputs

Generate the five demonstration scenarios in a fresh output directory:

```sh
python examples/closure/demo.py --out results/closure_demo
```

Each scenario writes `network_with_closure.gpkg`, `closure_manifest.json`, and `coverage_report.txt`. Simulated cases also write maximum-depth rasters, resolved forcing, and support artifacts. These are synthetic software demonstrations, not empirical validation results.
