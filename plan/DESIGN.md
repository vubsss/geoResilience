# GeoResilience — Design (Tiers 1–2)

> Implementation is broken into tickets in `tickets/`. Where a ticket is more specific than this document, the ticket wins.

An open, reproducible tool that takes an OpenStreetMap road network (and optionally WorldPop population) and reports how resilient it is to link and node loss. This document records the design decisions for Tiers 1–2, as specified in `tier1_2.md`.

**Guiding principle:** the graph is the only required input. Every additional data layer is optional and has a documented default, so a user with only a road network still gets a complete result. Adding data replaces a default and leaves the code unchanged.

---

## 1. Input

### 1.1 Supported sources

| Source | Status | Loader |
|---|---|---|
| Place name, polygon (GeoJSON/GPKG) or bbox (downloaded from OSM) | **Supported** | `ox.graph_from_place` / `graph_from_polygon` / `graph_from_bbox` |
| `.osm` XML file (Overpass Turbo / JOSM export) | **Supported** | `ox.graph_from_xml` |
| `.graphml` (previously saved graph) | **Supported** | `ox.load_graphml` |
| `.osm.pbf` (e.g. Geofabrik extract) | **Planned** | via `pyrosm`/`osmium` → osmnx format |
| Road lines as Shapefile / GeoJSON / GPKG | **Not supported** | Lines must be split at intersections first, which often merges flyovers and underpasses into false junctions. Users should provide one of the supported forms instead. |

All loaders produce one internal format: an osmnx-style graph with projected node coordinates (`x`, `y` in metres, local UTM) and edge `length`, plus `highway`, `maxspeed`, `oneway` and access tags where OSM has them.

### 1.2 Network type
- Default: `drive` (public motorable roads; excludes service roads and parking aisles).
- The user can choose any osmnx type (`drive_service`, `all`, …) or a custom filter.
- The network type is recorded in every output. Results from different network types are not comparable.

### 1.3 Study boundary and zones
- **Study boundary** (one polygon, or a place name geocoded by osmnx): defines the area analysed. It drives both the OSM download and the WorldPop clip.
- **Zones** (optional polygons, e.g. GHMC wards): used only to aggregate results per zone.

---

## 2. Preprocessing

1. **Simplify:** remove degree-2 interstitial nodes, so each edge runs between two real junctions. Total length is preserved and the geometry is kept as an attribute. This is always on. Without it, the degree distribution measures road curvature, and a "link closure" would remove a few metres of road.
2. **Consolidate intersections:** merge nodes within a tolerance (default **15 m**, adjustable, can be disabled), so a junction of divided roads mapped as 4–8 nodes becomes one node.
3. **Largest component:** analyse only the largest connected component (strongly connected for directed analyses). Report what was dropped (node count and % of network length).
4. Report node and edge counts **before and after each step**.

**Known limitation:** clipping to a boundary creates artificial dead-ends at the edge of the area. A buffered download (analyse inside the boundary, compute paths on boundary + 1–2 km) is planned.

### Directedness
| Analysis | Default graph | Reason |
|---|---|---|
| Centralities, distribution classification | Undirected | Matches Crucitti et al. and Albert et al. definitions |
| Closure tests, reliability, accessibility | Directed | One-way streets change detours and reachability |

Both are switchable with a `directed` flag.

---

## 3. Part 1: centrality and network class

### 3.1 Centralities (Crucitti, Latora & Porta)
Degree, closeness, betweenness, straightness and information centrality, all on metric (length) distances.

**Computation:**
- Closeness, straightness and efficiency contributions are computed together from **chunked all-pairs Dijkstra** (`scipy.sparse.csgraph.dijkstra`). Chunk size is set from available RAM: one chunk on Ada, many on a laptop. The same code runs on both.
- Betweenness (node and edge) is exact, using Brandes in C (`networkit`/`igraph`).
- **Information centrality** requires an all-pairs run per removed node, O(n²·m log n). It is computed for **every node when N ≤ 5,000** (or `all: true`), otherwise **exactly on the candidate nodes**: top-300 by betweenness ∪ the 50 most severe articulation points. With `all: true` on a city it is an Ada-scale batch job (days).

Measured on a 60k-node road-like graph: about 6 ms per Dijkstra source, i.e. about 6 core-minutes per full all-pairs run on a laptop (about 2× slower per core on Ada).

### 3.2 Distribution classification (Albert, Jeong & Barabási; Crucitti et al.)
- Clauset–Shalizi–Newman fitting (`powerlaw` package) for **each** centrality distribution, plus degree.
- Candidate fits: power law, exponential, lognormal, Gaussian. Fits are compared by log-likelihood ratio with p-values.
- "Inconclusive" is an allowed result.
- Degree is reported with a caveat: road-network degree is bounded (about 1–5), so it cannot be scale-free and is not informative on its own.
- **Network label** (follows Crucitti et al.: betweenness is never a power law; it is exponential in self-organised cities and Gaussian in planned ones, while information centrality is a power law in self-organised cities and exponential in planned ones):
  - **If information centrality covers all nodes:** information = power law → **scale-free**; exponential → **exponential**; otherwise **inconclusive**. Betweenness is reported as a consistency check.
  - **If it covers only the candidate set** (large graphs): fall back to betweenness. Exponential → scale-free (inferred); Gaussian → exponential (inferred). The report states that information centrality was excluded.
  - The attack-vs-failure gap (§4.2) is supporting evidence only.
  - Exact fit thresholds: ticket 07.

---

## 4. Removal experiments

### 4.1 A: single-link criticality
Removing each link and recomputing everything is too costly at city scale, so this works in two stages.

**Screen every link (cheap):**
- **Bridges and articulation points:** exact, O(m). A bridge's damage (the size of the part it cuts off) is computed directly, with no recompute.
- **Local detour ratio:** the shortest u→v path without edge (u,v), divided by the edge's length. One Dijkstra per link.
- **Edge betweenness.**

**Candidate set:**
- top-250 non-bridges by edge betweenness ∪ top-250 non-bridges by detour ratio ∪ directed bridges (non-bridges disconnected only because of one-way streets) → full recompute;
- bridges whose cut-off side has ≤ 2,000 nodes → analytic damage (no recompute);
- `all: true` → every link (Ada).

The full recompute only redoes rows for sources whose shortest paths use the link (an exact shortcut).

**Full recompute on candidates:** drop in global efficiency, fraction of node pairs disconnected, and extra distance. Population-weighted versions are used when population is present (§6).

Centrality alone is not enough, because a single access road to a neighbourhood has low betweenness but disconnects everything behind it. That is why bridges are always in the candidate set.

### 4.2 B: cumulative attack vs failure (Albert et al.)
- **Attack:** repeatedly remove the most central elements, in **50 steps of 0.4% each up to 20%**. Exact parallel betweenness (networkit) is recomputed before every step (adaptive, the default). A static-order flag is available.
- **Failure:** random removal, averaged over about 10 runs.
- **Both links and nodes:**
  - **Links are the headline result.** They match the Tier 1 framing; the attack ranking uses edge betweenness.
  - Nodes are used for the Albert-style classification evidence; the attack ranking uses node betweenness or degree.
- Tracked per step: the largest strongly (and weakly) connected component fraction, and efficiency estimated from 500 fixed sampled sources. Config `removal: [links, nodes]`.
- Summary: the area under each curve (robustness AUC) for attack and failure.

---

## 5. Part 2: reliability (Taylor, Sekhar & D'Este)

### 5.1 Link failure probabilities: pluggable
- **User-supplied:** a CSV keyed by OSM way ID:
  ```
  osm_way_id,p_fail
  123456789,0.08
  ```
  - `export_edge_template(G)` writes every way ID in the graph with its length and road class, for the user to fill in.
  - **Meaning of p:** the probability that the link is closed **during one event or scenario**. It is not an annual rate.
  - Validation: p must be in [0, 1]; unknown IDs trigger warnings.
- **Combining into one edge:** a simplified edge spans several OSM ways, and it fails if **any part** fails:
  `p_edge = 1 − Π(1 − pᵢ)`
- **Default proxy (no user data, or partial coverage):** length-scaled,
  `p = 1 − (1 − p₀)^(length / 1 km)`.
  A sensitivity sweep is run over p₀ ∈ {0.001, 0.01, 0.05}.
- **Coverage report:** the % of edges and the % of network length with user values vs the proxy.
- No built-in road-class failure table is shipped (it would contain invented numbers). Hazard presets are future work (§10).

### 5.2 Connectivity reliability
Monte Carlo: sample failure states, compute strongly connected components per sample (O(m)). Default 10,000 samples, fixed seed, 95% confidence intervals.

**Directed "connected":** a node pair counts as connected when both nodes are in the same strongly connected component (mutually reachable). This is conservative. OD-pair reliability checks true one-way reachability i→j with a BFS.

| Level | Output |
|---|---|
| Network | Expected fraction of node pairs (or population) still connected |
| Node | P(node stays in the main component) |
| Link | How often its failure caused a disconnection (importance) |
| OD pair | P(i and j connected), for user-chosen pairs |

"P(whole network connected)" is deliberately not reported: it is close to 0 at city scale and therefore uninformative.

### 5.3 Travel-time reliability
- Free-flow time = length ÷ speed. Speed comes from `maxspeed`, falling back to osmnx road-class defaults. This is labelled as requiring speed data.
- Monte Carlo on **user-chosen or sampled OD pairs** only (default 1,000 samples).
- Output: P(travel time ≤ (1 + τ) × normal time), with default τ = 0.5, plus the detour-factor distribution.

---

## 6. Part 3: accessibility, and Tier 2 population

### 6.1 Hansen accessibility (Taylor et al.)
`Aᵢ = Σⱼ Wⱼ · exp(−β · dᵢⱼ)`

- **Distance decay**, so no speed data is needed. β is set from a half-weight distance: default 2 km, β = ln2 / 2 km.
- Exponential decay is chosen over 1/d because Hansen with 1/d repeats efficiency/closeness from Part 1, while exponential decay measures *local* accessibility.
- **Graph only:** Wⱼ = 1, which gives purely structural accessibility.
- **Tier 2:** Wⱼ = population allocated to node j (§6.3). It is the same function.

### 6.2 Vulnerable nodes and critical links
- **Vulnerable node:** relative drop in Aᵢ when the k most damaging nearby links are removed (default k = 1; k = 2 optional).
- **Critical link:** drop in Σᵢ Aᵢ when the link is removed.
- The index is truncated at R = 5 × half-distance (weight 2⁻⁵ ≈ 3%). The truncation is part of the definition, so local recomputation is exact.
- Evaluated links: the **candidate set + analytic bridges** by default (shared with §4.1). For each removal, only sources within R whose shortest paths use the link are recomputed. Node vulnerability is the max drop over evaluated links.
- `all_links: true` evaluates every link. **Correction to the earlier plan:** this is *not* cheap at a 2 km half-distance, because R = 10 km covers much of the city per link. It is Ada-only at that scale, and laptop-feasible at a half-distance of about 1 km or less.

### 6.3 Population (WorldPop)
- **Source:** the user gives a GeoTIFF path; if none is given, it is **downloaded automatically** by country ISO3 and year, then cached.
- **Default product:** constrained 100 m (population only in built-up cells). The year is configurable and recorded.
- Clipped to the study boundary. Each cell's population goes to the **nearest graph node** (KD-tree); cells too far from any road are reported as unallocated.
- Population feeds the Hansen masses, population-weighted reliability ("expected population cut off") and population-weighted link criticality ("people disconnected").
- WorldPop is a modelled estimate, not a census; the docs state this.
- If zones are given, node and link results are aggregated per zone (e.g. per ward, per capita).

2SFCA is **not** part of Tiers 1–2. It needs facilities with capacity, so it belongs to Tier 3.

---

## 7. Interface and outputs

**Interface:** Python library plus a CLI, both driven by a YAML config. The same config runs on a laptop and on Ada (`sbatch` calls one command).

```
georesilience run --config hyderabad.yaml --out results/
```

**Output folder per run:**

| File | Contents |
|---|---|
| `network.gpkg` | `nodes` layer: centralities, population, Hansen A, vulnerability, P(stay connected). `edges` layer: edge betweenness, bridge flag, detour ratio, criticality, p_fail and its source (user or proxy), reliability importance |
| `zones.gpkg` | Per-zone aggregates (only if zones were given) |
| `summary.json` | Network-level results: fits and label, robustness AUCs, reliability, total accessibility, coverage |
| `report.txt` | Plain-text summary: input and cleaning statistics, class label with fit evidence, scorecard, top 20 critical links and vulnerable nodes (way IDs and street names), reliability with confidence intervals, data-coverage warnings |
| `run_config.yaml` | Every parameter, seed and data version (OSM download date, WorldPop year, tolerance, network type) |
| `figures/` | Distribution fits, attack/failure curves, maps of critical links and vulnerable nodes |

### Scorecard (no default composite)
| Dimension | Headline numbers |
|---|---|
| Structural robustness | Link attack AUC, link failure AUC |
| Redundancy | % of links that are bridges, median detour ratio |
| Connectivity reliability | Expected % of node pairs (or population) still connected |
| Accessibility vulnerability | Mean and 90th-percentile node accessibility loss |
| Network class | Scale-free / exponential / mixed / inconclusive |

A composite index is computed **only** when the user supplies weights in the YAML, and it is labelled "user-weighted". The literature shows that the choice of metric shapes the ranking, so we do not hide that behind default weights.

---

## 8. Defaults

| Parameter | Default |
|---|---|
| Network type | `drive` |
| Consolidation tolerance | 15 m |
| Candidate links | 250 by betweenness + 250 by detour + directed bridges; analytic bridges ≤ 2,000-node side |
| Candidate nodes (information) | all if N ≤ 5,000, else 300 by betweenness + 50 articulation points |
| Attack/failure steps | 50 steps, up to 20% removed; 500 efficiency sources |
| Random failure runs | 10 |
| Reliability Monte Carlo samples | 10,000 |
| Travel-time Monte Carlo samples | 1,000 |
| Travel-time slack τ | 0.5 |
| p₀ sensitivity | 0.001, 0.01, 0.05 |
| Hansen half-weight distance | 2 km |
| Accessibility removal k | 1 |
| WorldPop product | Constrained, 100 m |
| Random seed | Fixed, recorded |

---

## 9. Validation (pytest)

1. **Known-answer graphs:**
   - Tree: every link is a bridge.
   - Ring: detour ratios are known.
   - Straight line of nodes: straightness = 1.
   - Star: hub betweenness is known.
   - Single bridge with p = 0.5: reliability = 0.5.
2. **Reference cross-check:**
   - On about 200-node random spatial graphs, the fast implementations must match NetworkX's exact ones (closeness, betweenness, efficiency, brute-force information centrality).
   - Local cut-off Hansen must match a full recompute.
   - Monte Carlo reliability must match exact enumeration on graphs with ≤ 15 links.
3. **Paper replication (qualitative):** Crucitti et al.'s 1 square mile samples (e.g. Venice/Ahmedabad vs a Los Angeles/New York grid) from current OSM. Check the distribution *pattern*, not exact values (2006 maps ≠ today's OSM).

Layers 1–2 run in CI. Layer 3 is a scripted validation run.

---

## 10. Compute notes (Ada)

- Nodes: 40 vCPUs, about 120 GB usable per job (3 GB/CPU); `medium` QoS allows 4 jobs, each with a 4-day wall-clock limit; Gigabit interconnect, so the work is split across SLURM array jobs, not MPI.
- Ubuntu 18.04: use a conda environment in `/home`.
- GPUs are not used: RAPIDS/cuGraph does not support Pascal GPUs or this OS.
- At about 60k nodes, exact closeness/straightness/betweenness takes under a minute. Exhaustive information centrality (≈ 12k core-hours) and full per-link recompute (≈ 18k core-hours) are multi-day batches. This is why the candidate set exists and why `K = all` is optional.

---

## 11. Deferred and future work

**Deferred (Tiers 1–2 extensions):**
- `.osm.pbf` input
- Buffered boundary download
- HMV vs LMV subgraphs (filtered by road class and access tags)
- Added links ("what if we build this road")
- A run-vs-run comparison layer
- Hazard presets for p_fail: earthquake (El-Maissi et al. 2022 SVI; mostly not derivable from OSM) and flood (DEM / underpasses / ward flood risk)

**Tier 3, critical facilities:** hospital, school and fire-station layers with capacity. 2SFCA accessibility. Links weighted by their role in reaching facilities, plus facility-specific critical links.

**Tier 4, traffic:** gravity-model demand from WorldPop, static equilibrium assignment (AequilibraE, BPR), calibrated against Uber Movement where usable. Criticality measured as delay under load instead of distance alone.
