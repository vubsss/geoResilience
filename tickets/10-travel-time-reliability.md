# 10 — Travel-time reliability

**What to build:** the probability that trips stay within an acceptable travel time when links fail at random, using free-flow speeds from OSM. It is estimated on a sampled set of origins (and on user OD pairs), so it runs on a laptop.

**Blocked by:** 09

**Status:** ready-for-agent

## Behaviour

### Config additions
```yaml
travel_time:
  enabled: true
  samples: 1000
  n_origins: 200
  tau: 0.5                    # success if tt <= (1 + tau) * tt0
  highway_speeds_kph: null    # optional {highway_class: kph} used to fill missing maxspeed
```

### Speeds
- Use `ox.routing.add_edge_speeds(G, hwy_speeds=highway_speeds_kph)`, then `ox.routing.add_edge_travel_times(G)`.
- **Skip rule:** if no edge in the graph has a parsed `maxspeed` **and** `highway_speeds_kph` is null, skip this whole stage. Write `travel_time.status = "skipped: no speed data"` to the summary and the report. Do not invent speeds.
- Record `maxspeed_coverage`: the % of length with a tagged maxspeed, vs filled by the osmnx class mean or the user table.

### Monte Carlo
- Origins: `n_origins` nodes drawn uniformly (seeded) from the analysis node set. Destinations: all nodes.
- Baseline `tt0`: Dijkstra on travel time from each origin, run once.
- Per sample:
  - draw link failures exactly as 09 does, with the **same seeding scheme** but a separate child sequence;
  - compute travel-time Dijkstra from the origins on the damaged directed graph;
  - a pair succeeds if reachable and `tt ≤ (1 + tau)·tt0`.
- User OD pairs (reuse 09's snapping) are evaluated the same way in the same samples.

### Estimates
- `tt_reliability` = mean over samples of the fraction of (origin, destination) pairs that succeed, with a 95% CI.
- Per origin node, `p_tt_ok`: the fraction of samples × destinations that succeed.
- The detour-factor distribution `tt/tt0` over reachable pairs, pooled across samples: p50, p90 and p99, using reservoir sampling or a histogram to bound memory.
- OD: `p_tt_ok` per pair, with a Wilson CI.

### Outputs
- `nodes` layer: `p_tt_ok` (origins only; NaN elsewhere).
- `od_reliability.csv` gains `p_tt_ok`, `tt0_min`.
- `summary.json.travel_time`: status, `tt_reliability` + CI, detour-factor percentiles, tau, samples, n_origins, `maxspeed_coverage`.
- `report.txt` "Travel-time reliability" section: these values, plus an explicit line "free-flow speeds; no traffic (Tier 4)".

## Acceptance criteria
- [ ] Layer 1: a fixture with two parallel routes A→B (fast route with p = 0.5, slow route with p = 0, slow route tt = 3 × fast route): with tau = 0.5, `p_tt_ok` → 0.5. With tau = 2.5 → 1.
- [ ] Skip rule: a graph with no maxspeed and no table → stage skipped, and the run still succeeds.
- [ ] A user speed table is applied to classes that have no maxspeed.
- [ ] Same seed → identical results for different `n_jobs`.
- [ ] Outputs (column, CSV fields, summary, report) are present.
