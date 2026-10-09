# 15 — Crucitti replication (validation layer 3)

**What to build:** a scripted validation that runs the pipeline on 1 square mile samples of cities used by Crucitti, Latora & Porta. It checks that our classification reproduces their **qualitative** pattern:
- self-organised cities: information centrality is a power law and betweenness is exponential;
- planned cities: information centrality is exponential and betweenness is Gaussian.

It writes its own report, which can be cited in the project write-up.

**Blocked by:** 07

**Status:** ready-for-agent

## Behaviour

### Samples
Each sample is a square 1609 m × 1609 m, centred on the point below. Build it as a projected square buffer around the point, then pass it as a `polygon` input. Crucitti's exact sample locations aren't published, so these are historic centres (self-organised) and downtown grids (planned):

| City | Class (paper) | Centre (lat, lon) |
|---|---|---|
| Ahmedabad | self-organised | 23.0225, 72.5880 (old walled city) |
| Cairo | self-organised | 30.0478, 31.2625 (historic Cairo, Khan el-Khalili) |
| Los Angeles | planned | 34.0480, −118.2520 (downtown grid) |
| Richmond, CA | planned | 37.9358, −122.3478 (downtown grid) |

Expected results from the paper:
- Ahmedabad and Cairo: betweenness `exponential`, information `power_law` (γ ≈ 2.74 and 2.63).
- LA and Richmond: betweenness `gaussian`, information `exponential`.

### Run settings
- `network.type: all`. Crucitti mapped all streets, and old-city lanes may not be tagged as drivable.
- Consolidation stays on (15 m).
- These graphs have a few hundred to about 2,000 nodes, so `exact_info_max_nodes` covers them and information is computed for **all** nodes.
- Only stages 01–07 are needed (centralities, information, classification). Reliability, accessibility and population are disabled.

### Interface
- A CLI subcommand `georesilience validate crucitti --out DIR`. It downloads, so it needs network access.
- `DIR/crucitti_report.txt` contains:
  - per city: N, links, the verdict per distribution, α for information (if power law), the network label;
  - the expected vs obtained table;
  - a match count.
- `DIR/figures/`: the information-centrality CCDF of the four cities on one log-log plot, as in the paper's Fig. 3c/d.
- The report always includes the caveat: "OSM 2026 ≠ 1990s street maps used in the paper; sample locations approximate; agreement is qualitative."

### Pass criterion
- **Pass** if ≥ 3 of the 4 cities match on the information-centrality verdict **and** ≥ 3 of 4 match on the betweenness verdict.
- Fail → the report shows the mismatches. This is a finding, not a crash: exit code 0, but the report is headed "MISMATCH".
- Not part of CI. It runs manually or under `@pytest.mark.network` + `@pytest.mark.slow`.

## Acceptance criteria
- [ ] The subcommand runs end to end, with network access, and produces the report and figure.
- [ ] An offline unit test checks the square-sample construction: a 1609 m side in projected metres, centred correctly.
- [ ] An offline unit test checks the report and the pass-criterion logic, using mocked verdicts.
- [ ] The README links the validation command and states what it does and doesn't show.
