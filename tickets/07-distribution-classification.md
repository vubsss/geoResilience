# 07 — Distribution classification

**What to build:** each centrality distribution gets a statistically defensible shape verdict (power law, exponential, Gaussian or inconclusive), and the network as a whole gets the label from `tier1_2.md`: **scale-free**, **exponential**, or **inconclusive**. The label follows the evidence pattern in Crucitti et al., with the attack/failure curves reported as supporting evidence. The report shows *why* the label was given.

**Blocked by:** 03, 05, 06

**Status:** ready-for-agent

## Background (decided; from Crucitti, Latora & Porta, `AP2-…pdf` in the lit folder)
- **Degree** in road graphs is bounded (about 1–5), so it cannot be scale-free. Report its fit, but **never use it for the label**.
- **Betweenness** is single-scale in all cities:
  - *exponential* in self-organised cities (Ahmedabad, Cairo);
  - *Gaussian* (half-normal, centred at 0) in planned cities (Los Angeles, Richmond).
- **Information centrality** separates the classes:
  - *power law* in self-organised cities (γ ≈ 2.6–2.7; Venice 1.49);
  - *exponential* in planned cities.
- Closeness and straightness show similar shapes in both classes. Report them, but they don't influence the label.
- Therefore: **scale-free ↔ information centrality is a power law; exponential ↔ information centrality is exponential.** Betweenness is the secondary indicator.

## Behaviour

### Per-distribution fit
Applies to degree, closeness, straightness, betweenness and information. Use the positive values only, and report how many zeros were dropped. Information uses only nodes where it was computed.

1. **Tail test (Clauset–Shalizi–Newman):**
   - `powerlaw.Fit(x)`, with `discrete=True` only for degree; xmin is chosen by the package.
   - `R_exp, p_exp = fit.distribution_compare('power_law', 'exponential', normalized_ratio=True)`.
   - `R_ln, p_ln = …('power_law', 'lognormal')`.
   - Record α, xmin, `n_tail`.
2. **Body test:** on all positive x, fit `scipy.stats.expon(loc=0)` and `scipy.stats.halfnorm(loc=0)` by MLE. `ΔAIC = AIC_expon − AIC_halfnorm`.
3. **Verdict**, rules applied in order:
   - `power_law` if R_exp > 0 and p_exp < 0.1, and not (R_ln < 0 and p_ln < 0.1), and `n_tail ≥ 50`.
   - `gaussian` if ΔAIC > 10.
   - `exponential` if ΔAIC < −10, or (R_exp < 0 and p_exp < 0.1).
   - otherwise `inconclusive`.
   - Fewer than 50 positive values → `inconclusive (too few values)`.

### Network label
- **If information coverage is `all`** (05):
  - info verdict `power_law` → `scale-free`;
  - `exponential` → `exponential`;
  - otherwise `inconclusive`.
  - Consistency note: betweenness `exponential` supports scale-free (self-organised pattern); `gaussian` supports exponential (planned pattern). Report `consistent | inconsistent | n/a`.
- **If information coverage is `candidates`** (large graph), fall back to betweenness:
  - `exponential` → `scale-free (inferred from betweenness)`;
  - `gaussian` → `exponential (inferred from betweenness)`;
  - otherwise `inconclusive`.
  - The report must say: "information centrality computed on the candidate set only; excluded from classification".
- **Supporting evidence**, reported and not used in the rule, from 06 node curves:
  - `attack_failure_gap = auc_failure_S − auc_attack_S` for nodes.
  - Albert's signature of a scale-free network is a *large* gap: robust to failure, fragile under attack. Report the number and one interpretive sentence.

### Outputs
- `summary.json.classification`:
  - per distribution: α, xmin, n_tail, R_exp, p_exp, R_ln, p_ln, ΔAIC, verdict, zeros_dropped;
  - `network_label`, `label_basis` (`information` | `betweenness_fallback`), `consistency`, `attack_failure_gap`.
- `report.txt` "Network class" section: a table of verdicts, the label, the basis, the consistency, and the evidence sentence. Note that degree is bounded and excluded.
- Figures: for each distribution, the empirical CCDF (log-log) with the power-law tail fit, plus the CCDF (log-y) with the exponential and half-normal fits.

## Acceptance criteria
- [ ] Synthetic tests with a fixed seed and n = 5000:
  - Pareto(α = 2.5) samples → `power_law`.
  - Exponential samples → `exponential`.
  - |Normal| samples → `gaussian`.
  - Uniform(0.4, 0.6) → not `power_law`.
  - 30 samples → `inconclusive (too few values)`.
- [ ] Label-logic unit tests cover every branch, including the betweenness fallback and the consistency flag.
- [ ] Information values that are NaN are excluded, and the coverage flag is respected.
- [ ] Outputs (summary, report, figures) are present.
