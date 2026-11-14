# Road capacity: implemented rules and Hyderabad audit

The capacity-input audit is the first traffic follow-up. It does not tune demand,
weights or road parameters to obtain a particular city ranking.

## What changed

`traffic_capacity.py` supplies versioned, deterministic road-capacity inference.
The existing `_road_capacities` interface delegates to it, and the normal pipeline
exports its audit in `summary.json.traffic.capacity_audit`, `report.txt`,
`traffic_arcs.csv` and the directed GIS layer. Supplied capacity CSVs still supply
their explicit values; they do not acquire inferred or measured provenance.

- On a two-way road, explicit `lanes:forward` / `lanes:backward` follow the OSM
  way direction using unambiguous OSMnx `reversed` metadata. Node IDs, compass
  direction and oriented geometry are not substitutes for original way order.
- With a consistent total and opposite-direction count, infer the remainder,
  excluding reported shared lanes. Without directional counts, label an equal
  split as an assumption. One-way total counts are not halved.
- A one-way road with only one positive directional count can use that count;
  its assumption is recorded. This avoids assuming that OSMnx's normalized
  one-way flag preserves the original `oneway=-1` tag.
- Shared centre lanes are not counted as independent through lanes in both
  directions. Shared single-lane conflicts are not simulated. An explicitly
  zero directional lane count on a retained arc requires corrected access/direction
  or an explicit capacity override; it is not silently assigned positive capacity.
  A road with only explicitly shared lanes likewise requires an override rather
  than receiving two independent full-capacity directions.
- Use available directional width without halving it again. Otherwise width
  divided by the configured lane width is an explicitly approximate lane count.
  Kerb-to-kerb width may include parking/cycle space. `maxwidth` is vehicle
  clearance and is never used as carriageway width.
- Complete numeric/unit parsing rejects prose, ranges and separators such as
  `2;3`. Convert metric and feet/inches widths. Simplified lists use the minimum
  valid cross-section only when all entries parse; invalid/contradictory metadata
  and ambiguous direction are exposed rather than guessed.
- OSM XML imports now retain directional lane and width fields. Existing GraphML
  archives cannot recover tags omitted during their original extraction.

Every inferred arc includes raw capacity tags, the chosen rule, direction,
assumptions, invalid fields and model version. The configured 1,000 PCU/hour/lane,
3.5 m/lane and one default lane/direction remain assumptions, not Hyderabad
calibration. This step does not introduce road-condition or traffic observations.

## Actual supplied networks

These counts refer to the retained, cleaned study networks, not all roads in the
larger original raw downloads. Reciprocal arcs count separately.

| Area | Directed arcs | Lane-based | Width-based | Default | Default share | Directional lane/width tags |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Gachibowli | 1,305 | 127 | 2 | 1,176 | 90.115% | 0 |
| Old Hyderabad | 8,435 | 19 | 0 | 8,416 | 99.775% | 0 |

Neither raw archive contains `lanes:forward`, `lanes:backward`, `lanes:both_ways`,
`width:forward` or `width:backward`. No new download or fabricated attributes were
substituted. Improving the parser therefore does not improve the archival tag
coverage. The exposed capacity assumptions still require later sensitivity checks.

Intact traffic was reassigned using identical original OD matrices, speed rules,
BPR coefficients and convergence targets. Both replays converged. Capacities,
free-flow times, assigned volumes and congested times matched the checkpoint
exactly on every arc. Thus this step does not change the published composite
inputs; flood/reliability/composite calculations were not rerun or overwritten.

## Reproduce and inspect

```powershell
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe examples/traffic/audit_capacities.py
```

Requires the original prepared configs in `data/final_study`, their road/OD
inputs, and the checkpoint arc exports. Default output is a fresh
`results/traffic_capacity_audit`; use `--output <fresh-directory>` for a repeat.
Each city exports audited arcs, OD, compatible capacity values, a summary and
input/code hash manifest. `comparison.csv` and `README.md` summarize both cities.
Earlier complete studies are preserved.

Future runs of `prepare_final_study.py` infer capacities from the original roads
instead of copying the earlier pilot's values. Generated study configs use the
normal road-attribute mode so their own pipeline outputs retain audit metadata.
The preparer also exports a values-only capacity CSV for optional explicit reuse.

## Method references

- [OSM lanes](https://wiki.openstreetmap.org/wiki/Key:lanes): total versus directional counts and shared lanes.
- [OSM width](https://wiki.openstreetmap.org/wiki/Key:width): units, carriageway width, parking and distinction from vehicle clearance.
- [OSMnx graph source](https://github.com/gboeing/osmnx/blob/main/osmnx/graph.py): reciprocal `reversed` metadata and one-way normalization.

These sources justify interpreting tags. They do not validate local capacity
coefficients, independent directional treatment of narrow shared roads, or
predicted Hyderabad traffic.
