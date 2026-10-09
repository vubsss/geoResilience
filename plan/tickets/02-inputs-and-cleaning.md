# 02 — All inputs + full cleaning

**What to build:** the user can point the tool at a place name, a boundary polygon, a bbox, a `.osm` XML file or a `.graphml`. They get a cleaned `drive` network (simplified, intersections consolidated, largest component), and the report shows exactly what cleaning did. The documentation clearly lists what is supported, what is planned and what is not supported.

**Blocked by:** 01

**Status:** ready-for-agent

## Behaviour

### Config additions
```yaml
input:
  source: place | polygon | bbox | osm_xml | graphml
  place: "Hyderabad, India"        # source: place
  path: boundary.geojson           # source: polygon (GeoJSON/GPKG) | osm_xml | graphml
  bbox: [west, south, east, north] # source: bbox, WGS84
network:
  type: drive                      # any osmnx network_type
  custom_filter: null              # overpass filter string; overrides type when set
cleaning:
  consolidate: true
  tolerance_m: 15
```

### Loading
- **Before any load**, extend `ox.settings.useful_tags_way` with `motor_vehicle`, `motorcar`, `hgv`, `access`, `service`, `area`, `lanes`, `surface` and `maxspeed`. Later tickets and deferred HMV work need these tags.
- `place` → `ox.graph_from_place(place, network_type=…, custom_filter=…)`. The geocoded boundary polygon is kept as the **study boundary** (`ox.geocode_to_gdf`).
- `polygon` → read with geopandas, union all features, reproject to EPSG:4326, then `ox.graph_from_polygon`. The polygon is the study boundary.
- `bbox` → `ox.graph_from_bbox(bbox=(west, south, east, north), …)`. Use the osmnx 2.x argument order. The bbox polygon is the study boundary.
- `osm_xml` → `ox.graph_from_xml(path, simplify=True, retain_all=True)`. The network-type filter cannot be applied at download time, so:
  - For `network.type == drive`: drop edges whose tags fail the drive rules. Replicate osmnx's published `drive` filter:
    - exclude `highway` ∈ {abandoned, bridleway, bus_guideway, construction, corridor, cycleway, elevator, escalator, footway, no, path, pedestrian, planned, platform, proposed, raceway, razed, service, steps, track};
    - exclude `area=yes`;
    - exclude `access=private`;
    - exclude `motor_vehicle=no` and `motorcar=no`.

    Then remove isolated nodes.
  - For any other type: keep everything, record `network.type_applied: "as-provided"`, and log a warning.
- `graphml` → as in 01. Record `network.type_applied: "as-provided"`.
- `summary.json.meta` gains `osm_download_utc` (download sources only), `network_type_applied` and `study_boundary_wkt` (null if none).

### Cleaning (in this order, after projecting)
1. Simplify (already done by the loaders; graphml handled as in 01).
2. If `cleaning.consolidate` is set: `ox.consolidate_intersections(G, tolerance=tolerance_m, rebuild_graph=True, dead_ends=True, reconnect_edges=True)`.
   - `dead_ends=True` is required so cul-de-sacs survive: they become bridges in 04.
   - **Verify** that the degree-1 node count before and after consolidation differs by less than 5%. If it doesn't, raise an error, because it means dead ends are being dropped.
3. Keep the **largest strongly connected component** with `ox.truncate.largest_component(G, strongly=True)`. Both the undirected and directed analysis graphs use this one node set.
4. Rebuild the link table (01) on the cleaned graph.

### Cleaning report
`summary.json.cleaning` holds the node, link and total-length (km) counts after each step: raw, simplified, consolidated and final. It also holds the dropped components: their count, nodes dropped, and length dropped in km and as a percentage of total length.

`report.txt` gets a "Cleaning" section with that table. If more than 5% of the length was dropped, add a warning line: "check boundary clipping / one-way slivers".

The report also states the **boundary-effect warning** permanently: "clipped boundaries create artificial dead-ends; buffered download is planned".

### Documentation
The README gets a section **"Supported inputs"**:
- **Supported:** place, polygon, bbox, `.osm` XML, `.graphml`.
- **Planned:** `.osm.pbf`.
- **Not supported:** road-line Shapefile/GeoJSON/GPKG, with the reason ("splitting lines at intersections merges flyovers/underpasses into false junctions").

It also documents the `drive` filter rules applied to XML, and the meaning of the cleaning steps, with the before/after ASCII sketches from the design discussion.

## Acceptance criteria
- [ ] Each of the five sources works. `place`, `polygon` and `bbox` are tested under `@pytest.mark.network` on a small area (≈ 1 km², e.g. a bbox in central Hyderabad). `osm_xml` and `graphml` are tested offline with fixture files generated in-test.
- [ ] The drive-filter test: an XML fixture containing a footway, a service road, an `access=private` residential road and a normal residential road keeps only the normal residential road.
- [ ] The consolidation test: a fixture of a dual-carriageway crossing (4 nodes about 10 m apart forming a junction, plus 4 approach roads) becomes 1 junction node of degree 4 at tolerance 15 m, and stays 4 nodes with `consolidate: false`.
- [ ] The dead-end guard raises on a fixture where dead ends would be lost. If osmnx behaviour makes that fixture impossible, document this in the test and assert that the guard is wired in.
- [ ] The cleaning table appears in `summary.json` and `report.txt`, and the counts there are consistent with the final GPKG.
- [ ] The README "Supported inputs" section exists with all three lists.
