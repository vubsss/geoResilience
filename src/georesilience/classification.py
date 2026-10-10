"""Ticket 07's centrality rules and an independent degree-model diagnostic.

Likelihood comparisons give relative model evidence, not absolute goodness of
fit. Degree evidence never enters the centrality-based network decision.
"""

import math
import warnings
from dataclasses import dataclass
from importlib.metadata import version
from time import perf_counter

import numpy as np
import powerlaw
from scipy import stats
from scipy.optimize import minimize_scalar
from scipy.special import gammaln, logsumexp

from .progress import StageProgress


DISTRIBUTIONS = ("degree", "closeness", "straightness", "betweenness", "information")
CLASSIFICATION_FIGURES = tuple(f"classification_{name}_{scale}.png"
                               for name in DISTRIBUTIONS for scale in ("loglog", "logy"))


def _finite(value):
    return float(value) if value is not None and math.isfinite(value) else None


def positive_values(values):
    values = np.asarray(values, dtype=float).ravel()
    return values[np.isfinite(values) & (values > 0)]


def distribution_verdict(result):
    """Apply the ticket's ordered thresholds without looking at graph family."""
    if result["positive_count"] < 50:
        return "inconclusive", "too few values"
    if result.get("fit_error"):
        return "inconclusive", result["fit_error"]
    r_exp, p_exp = result["R_exp"], result["p_exp"]
    r_ln, p_ln = result["R_ln"], result["p_ln"]
    significant_exp = p_exp is not None and p_exp < .1 and r_exp is not None
    lognormal_wins = r_ln is not None and p_ln is not None and r_ln < 0 and p_ln < .1
    if (significant_exp and r_exp > 0 and r_ln is not None and p_ln is not None
            and not lognormal_wins and result["n_tail"] >= 50):
        return "power_law", "tail beats exponential; no significant lognormal advantage; at least 50 tail values"
    delta = result["delta_aic"]
    if delta is not None and delta > 10:
        return "gaussian", "half-normal body preferred by more than 10 AIC units"
    if (delta is not None and delta < -10) or (significant_exp and r_exp < 0):
        return "exponential", "exponential body or tail preferred under Ticket 07 rules"
    return "inconclusive", "no rule passed"


def fit_distribution(values, *, discrete=False):
    raw = np.asarray(values, dtype=float).ravel()
    x = positive_values(raw)
    result = {key: None for key in ("alpha", "xmin", "R_exp", "p_exp", "R_ln", "p_ln",
                                    "delta_aic", "aic_exponential", "aic_halfnormal",
                                    "exponential_scale", "halfnormal_scale", "tail_ks")}
    result.update(total_count=len(raw), positive_count=len(x), n_tail=0,
                  zeros_dropped=int(np.count_nonzero(raw == 0)),
                  nonfinite_dropped=int(np.count_nonzero(~np.isfinite(raw))),
                  negatives_dropped=int(np.count_nonzero(np.isfinite(raw) & (raw < 0))),
                  discrete=discrete, warnings=[], fit_error=None)
    if len(x) >= 50:
        if len(np.unique(x)) < 3:
            result["fit_error"] = "fewer than three distinct positive values"
        else:
            # Fitting in median units improves small-centrality numerical
            # conditioning. It leaves likelihood ratios and AIC differences
            # unchanged; degree remains integer-valued and is never rescaled.
            unit = 1.0 if discrete else float(np.median(x))
            scaled = x / unit
            _, exp_scale = stats.expon.fit(scaled, floc=0)
            _, half_scale = stats.halfnorm.fit(scaled, floc=0)
            exp_ll = float(stats.expon.logpdf(scaled, loc=0, scale=exp_scale).sum())
            half_ll = float(stats.halfnorm.logpdf(scaled, loc=0, scale=half_scale).sum())
            # Each body has one fitted scale, with location fixed at zero.
            offset = 2 * len(x) * math.log(unit)
            result.update(exponential_scale=float(exp_scale * unit), halfnormal_scale=float(half_scale * unit),
                          aic_exponential=2 - 2 * exp_ll + offset,
                          aic_halfnormal=2 - 2 * half_ll + offset,
                          delta_aic=2 * (half_ll - exp_ll))
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                try:
                    # powerlaw 2.0 otherwise caps alpha at 3. Do not impose
                    # that restriction on light tails or alternative models.
                    fitted = powerlaw.Fit(scaled, discrete=discrete, estimate_discrete=False,
                                         parameter_ranges={"alpha": [1 + 1e-8, None]}, verbose=False)
                    xmin, alpha = float(fitted.xmin), float(fitted.power_law.alpha)
                    if not (math.isfinite(xmin) and math.isfinite(alpha) and alpha > 1):
                        raise ValueError("nonfinite or nonnormalizable power-law fit")
                    result.update(alpha=alpha, xmin=xmin * unit, n_tail=int(np.count_nonzero(scaled >= xmin)),
                                  tail_ks=_finite(fitted.power_law.D))
                    for other, suffix in (("exponential", "exp"), ("lognormal", "ln")):
                        r, p = fitted.distribution_compare("power_law", other, normalized_ratio=True)
                        result[f"R_{suffix}"], result[f"p_{suffix}"] = _finite(r), _finite(p)
                        if result[f"R_{suffix}"] is None or result[f"p_{suffix}"] is None:
                            raise ValueError(f"nonfinite likelihood comparison against {other}")
                except (ValueError, RuntimeError, FloatingPointError, OverflowError, ZeroDivisionError) as exc:
                    result["fit_error"] = f"tail fit failed: {exc}"
                result["warnings"] = sorted(set(str(item.message) for item in caught))
    result["verdict"], result["reason"] = distribution_verdict(result)
    return result


def network_decision(distributions, coverage):
    if coverage not in ("all", "candidates"):
        raise ValueError("information coverage must be all or candidates")
    betweenness = distributions["betweenness"]["verdict"]
    if coverage == "all":
        label = {"power_law": "scale-free", "exponential": "exponential"}.get(
            distributions["information"]["verdict"], "inconclusive")
        basis = "information"
        expected = {"scale-free": "exponential", "exponential": "gaussian"}.get(label)
        consistency = ("consistent" if betweenness == expected else "inconsistent"
                       ) if expected and betweenness in ("exponential", "gaussian") else "n/a"
    else:
        label = {"exponential": "scale-free", "gaussian": "exponential"}.get(betweenness, "inconclusive")
        basis, consistency = "betweenness_fallback", "n/a"
    return {"network_label": label, "label_basis": basis, "consistency": consistency}


def degree_evidence(values, node_count):
    """Compare two discrete references on exactly the same bounded support.

    Both one-parameter models are conditioned on observed minimum <= k <= N-1.
    This benchmark diagnostic is relative AIC evidence, not a goodness-of-fit
    test or proof of an asymptotic power law. No tail/body AICs are mixed.
    """
    x = positive_values(values)
    result = {"verdict": "inconclusive", "positive_count": len(x), "delta_aic": None,
              "poisson_lambda": None, "power_law_alpha": None,
              "aic_poisson": None, "aic_power_law": None,
              "support_min": int(x.min()) if len(x) else None, "support_max": node_count - 1,
              "method": "bounded discrete Poisson vs power law; common support; delta AIC = Poisson - power law"}
    if len(x) < 50 or len(np.unique(x)) < 3:
        result["reason"] = "too few values or fewer than three distinct degrees"
        return result
    if np.any(x != np.floor(x)) or np.any(x >= node_count):
        raise ValueError("degree evidence requires integer distinct-neighbour degrees below N")
    support = np.arange(int(x.min()), node_count, dtype=float)
    counts = np.bincount(x.astype(int), minlength=node_count)[int(x.min()):]
    log_k, factorial = np.log(support), gammaln(support + 1)

    def nll(raw_logpmf):
        return -float(np.dot(counts, raw_logpmf - logsumexp(raw_logpmf)))

    poisson = minimize_scalar(lambda log_lambda: nll(support * log_lambda - factorial),
                              bounds=(math.log(1e-8), math.log(max(node_count - 1, 1))), method="bounded")
    power = minimize_scalar(lambda alpha: nll(-alpha * log_k), bounds=(0, 20), method="bounded")
    if not (poisson.success and power.success):
        result["reason"] = "degree model optimizer failed"
        return result
    delta = 2 * (poisson.fun - power.fun)
    result.update(poisson_lambda=float(math.exp(poisson.x)), power_law_alpha=float(power.x),
                  aic_poisson=float(2 + 2 * poisson.fun), aic_power_law=float(2 + 2 * power.fun),
                  delta_aic=float(delta))
    if power.x > 19.99:
        result["reason"] = "power-law optimizer reached its numerical boundary"
    else:
        result["verdict"] = "power_law_like" if delta > 10 else "poisson_like" if delta < -10 else "inconclusive"
        result["reason"] = "relative AIC evidence only; not absolute goodness of fit"
    return result


def agreement(label, degree_verdict):
    expected = {"power_law_like": "scale-free", "poisson_like": "exponential"}.get(degree_verdict)
    if expected is None or label == "inconclusive":
        return "inconclusive"
    return "agreement" if label == expected else "disagreement"


@dataclass
class ClassificationResult:
    summary: dict
    values: dict
    runtime_seconds: dict


def classify_network(values, information_summary, robustness_summary):
    started = perf_counter()
    distributions = {}
    with StageProgress("Distribution fits", len(DISTRIBUTIONS)) as progress:
        for name in DISTRIBUTIONS:
            distributions[name] = fit_distribution(values[name], discrete=name == "degree")
            progress.advance()
    coverage = information_summary["coverage"]
    decision = network_decision(distributions, coverage)
    nodes = robustness_summary.get("nodes", {})
    attack, failure = nodes.get("auc_attack_S"), nodes.get("auc_failure_S")
    gap = _finite(failure - attack) if failure is not None and attack is not None else None
    if gap is None:
        evidence = "Node attack/failure gap unavailable; node robustness curves were not supplied."
    elif gap > 0:
        evidence = (f"Random failure retains more connectivity than targeted attack (AUC gap {gap:.6g}); "
                    "this supports the direction of Albert's signature, with no calibrated large-gap threshold.")
    elif gap < 0:
        evidence = f"Targeted attack retains more connectivity than random failure (AUC gap {gap:.6g}); no attack fragility signature."
    else:
        evidence = "Node attack and random failure have equal connectivity AUCs; no attack/failure separation."
    independent = degree_evidence(values["degree"], len(values["degree"]))
    summary = {"distributions": distributions, **decision, "information_coverage": coverage,
               "attack_failure_gap": gap, "supporting_evidence": evidence,
               "degree_evidence": independent,
               "degree_agreement": agreement(decision["network_label"], independent["verdict"]),
               "rule": "ticket07-v1", "powerlaw_version": version("powerlaw"),
               "efficiency_convention": information_summary.get("efficiency_convention", "inverse_distance"),
               "thresholds": {"minimum_positive": 50, "minimum_tail": 50, "p": .1, "delta_aic": 10},
               "limitations": "Relative fit evidence under Ticket 07 rules; no bootstrap goodness-of-fit test. "
                              "Centralities on one graph are dependent observations. Degree never determines the network label."}
    return ClassificationResult(summary, {name: positive_values(values[name]) for name in DISTRIBUTIONS},
                                {"classification": perf_counter() - started})


def classification_report(summary):
    lines = ["Network class", "Distribution       Positive  Zeros  Tail  Verdict",
             *[f"{name:<19}{data['positive_count']:>8}{data['zeros_dropped']:>7}{data['n_tail']:>6}  "
               f"{data['verdict']} ({data['reason']})" for name, data in summary["distributions"].items()],
             f"Network label: {summary['network_label']}", f"Label basis: {summary['label_basis']}",
             f"Consistency with secondary betweenness pattern: {summary['consistency']}"]
    if summary["label_basis"] == "betweenness_fallback":
        lines.extend(["information centrality computed on the candidate set only; excluded from classification",
                      "Network label inferred from betweenness; information fit is descriptive only."])
    lines.extend(["Degree is geographically constrained in primal road networks and excluded from the network label.",
                  "Synthetic ER/BA graphs need not have those geographic degree constraints.",
                  f"Independent degree evidence: {summary['degree_evidence']['verdict']}; "
                  f"agreement with centrality label: {summary['degree_agreement']}.",
                  summary["supporting_evidence"],
                  "Efficiency convention: mean(1/d), different from AP2 spatial mean(d_E/d).",
                  summary["limitations"]])
    return lines


def write_classification_figures(result, folder):
    import matplotlib.pyplot as plt
    from scipy.special import zeta

    folder.mkdir(exist_ok=True)
    for name in DISTRIBUTIONS:
        x = result.values[name]
        fit = result.summary["distributions"][name]
        unique, counts = np.unique(x, return_counts=True)
        empirical = (len(x) - np.r_[0, np.cumsum(counts[:-1])]) / len(x) if len(x) else np.array([])
        for scale in ("loglog", "logy"):
            fig, ax = plt.subplots(figsize=(6, 4))
            if len(x):
                ax.step(unique, empirical, where="pre", label="Empirical (positive values)")
                if scale == "loglog" and fit["xmin"] is not None:
                    xmin, alpha = fit["xmin"], fit["alpha"]
                    grid = (np.unique(x[x >= xmin]) if fit["discrete"] else np.geomspace(xmin, x.max(), 200))
                    survival = (zeta(alpha, grid) / zeta(alpha, xmin) if fit["discrete"]
                                else (grid / xmin) ** (1 - alpha))
                    ax.plot(grid, fit["n_tail"] / len(x) * survival, "--", label="Power-law tail fit")
                    ax.axvline(xmin, color="grey", linestyle=":", label="xmin")
                if scale == "logy" and fit["exponential_scale"] is not None:
                    grid = np.linspace(x.min(), x.max(), 200)
                    ax.plot(grid, stats.expon.sf(grid, scale=fit["exponential_scale"]), "--", label="Exponential body")
                    ax.plot(grid, stats.halfnorm.sf(grid, scale=fit["halfnormal_scale"]), "--", label="Half-normal body")
                if scale == "loglog":
                    ax.set_xscale("log")
                ax.set_yscale("log")
                ax.set_ylim(max(.5 / len(x), 1e-8), 1.05)
                ax.legend(fontsize="small")
            else:
                ax.text(.5, .5, "No positive finite values", ha="center", transform=ax.transAxes)
            ax.set(xlabel=name, ylabel="Fraction of positive values >= x",
                   title=f"{name.capitalize()}: {fit['verdict']} ({scale})")
            if fit["verdict"] == "inconclusive":
                ax.text(.02, .02, fit["reason"], fontsize=8, transform=ax.transAxes)
            ax.grid(alpha=.2)
            fig.tight_layout()
            fig.savefig(folder / f"classification_{name}_{scale}.png", dpi=150, bbox_inches="tight")
            plt.close(fig)
