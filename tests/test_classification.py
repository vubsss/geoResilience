import json
import math
import subprocess
import sys
from pathlib import Path

import networkx as nx
import numpy as np
import osmnx as ox
import pytest
from scipy.special import gammaln, logsumexp

from georesilience.classification import (CLASSIFICATION_FIGURES, DISTRIBUTIONS, agreement, classify_network,
                                         degree_evidence, distribution_verdict, fit_distribution, network_decision)
from georesilience.config import RunConfig, load_config
from georesilience.pipeline import run


@pytest.fixture(scope="module")
def synthetic_fits():
    rng = np.random.default_rng(42)
    samples = {"pareto": 1 + rng.pareto(1.5, 5000),  # density exponent 2.5, not Pareto shape 2.5
               "exponential": rng.exponential(1, 5000),
               "halfnormal": abs(rng.normal(size=5000)), "uniform": rng.uniform(.4, .6, 5000)}
    return {name: (x, fit_distribution(x)) for name, x in samples.items()}


@pytest.mark.parametrize("name,expected", [("pareto", "power_law"), ("exponential", "exponential"),
                                           ("halfnormal", "gaussian"), ("uniform", "gaussian")])
def test_5000_sample_reference_distributions(synthetic_fits, name, expected):
    x, fitted = synthetic_fits[name]
    assert fitted["verdict"] == expected
    assert fitted["positive_count"] == 5000
    assert fitted["zeros_dropped"] == 0
    assert fitted["alpha"] is not None and fitted["xmin"] > 0
    # Independent closed-form MLE body statistics.
    exp_scale, half_scale = x.mean(), math.sqrt(np.mean(x*x))
    exp_ll = -len(x) * math.log(exp_scale) - x.sum() / exp_scale
    half_ll = len(x) * (.5 * math.log(2 / math.pi) - math.log(half_scale)) - np.sum(x*x) / (2 * half_scale**2)
    assert fitted["delta_aic"] == pytest.approx(2 * (half_ll - exp_ll))
    assert fitted["exponential_scale"] == pytest.approx(exp_scale)
    assert fitted["halfnormal_scale"] == pytest.approx(half_scale)
    if name == "pareto":
        assert fitted["alpha"] == pytest.approx(2.5, abs=.1)
        assert fitted["n_tail"] >= 50
    json.dumps(fitted, allow_nan=False)


def test_missing_zero_small_constant_and_scale_invariance():
    fitted = fit_distribution([0] * 3 + [math.nan, math.inf, -math.inf, -1] + list(range(1, 31)))
    assert fitted["verdict"] == "inconclusive" and fitted["reason"] == "too few values"
    assert fitted["zeros_dropped"] == 3 and fitted["nonfinite_dropped"] == 3
    assert fitted["negatives_dropped"] == 1 and fitted["positive_count"] == 30
    assert fit_distribution(np.zeros(60))["verdict"] == "inconclusive"
    assert "distinct" in fit_distribution(np.ones(60))["reason"]
    x = np.random.default_rng(17).exponential(size=200)
    before, after = fit_distribution(x), fit_distribution(x * 1e-6)
    assert before["verdict"] == after["verdict"]
    for key in ("alpha", "R_exp", "p_exp", "R_ln", "p_ln", "delta_aic"):
        assert after[key] == pytest.approx(before[key], rel=1e-5, abs=1e-5)
    assert after["xmin"] == pytest.approx(before["xmin"] * 1e-6)


@pytest.mark.parametrize("changes,expected", [
    ({}, "power_law"), ({"positive_count": 49}, "inconclusive"),
    ({"n_tail": 49}, "inconclusive"), ({"p_exp": .1}, "inconclusive"),
    ({"R_exp": 0}, "inconclusive"), ({"R_ln": -2, "p_ln": .05}, "inconclusive"),
    ({"R_ln": -2, "p_ln": .1}, "power_law"),
    ({"R_ln": None}, "inconclusive"), ({"p_ln": None}, "inconclusive"),
    ({"R_exp": -2}, "exponential"), ({"R_exp": -2, "delta_aic": 11}, "gaussian"),
    ({"p_exp": .5, "delta_aic": -11}, "exponential"),
    ({"p_exp": .5, "delta_aic": 11}, "gaussian"),
    ({"p_exp": .5, "delta_aic": 10}, "inconclusive"),
    ({"p_exp": .5, "delta_aic": -10}, "inconclusive"),
])
def test_order_and_exact_threshold_boundaries(changes, expected):
    result = {"positive_count": 50, "n_tail": 50, "R_exp": 2, "p_exp": .05,
              "R_ln": 0, "p_ln": .5, "delta_aic": 0, **changes}
    assert distribution_verdict(result)[0] == expected


def test_nonfinite_tail_comparison_is_inconclusive(monkeypatch):
    class FailedComparison:
        xmin = .5

        @property
        def power_law(self):
            return type("Tail", (), {"alpha": 2.5, "D": .01})()

        def distribution_compare(self, *args, **kwargs):
            return math.nan, math.nan

    monkeypatch.setattr("georesilience.classification.powerlaw.Fit", lambda *args, **kwargs: FailedComparison())
    result = fit_distribution(np.linspace(.1, 10, 60))
    assert result["verdict"] == "inconclusive"
    assert "nonfinite likelihood comparison" in result["reason"]
    json.dumps(result, allow_nan=False)


def test_every_network_label_and_consistency_branch():
    verdicts = ("power_law", "exponential", "gaussian", "inconclusive")
    for info in verdicts:
        for betweenness in verdicts:
            distributions = {"information": {"verdict": info}, "betweenness": {"verdict": betweenness}}
            full = network_decision(distributions, "all")
            expected = {"power_law": "scale-free", "exponential": "exponential"}.get(info, "inconclusive")
            assert full["network_label"] == expected and full["label_basis"] == "information"
            secondary = {"scale-free": "exponential", "exponential": "gaussian"}.get(expected)
            consistent = ("consistent" if betweenness == secondary else "inconsistent"
                          ) if secondary and betweenness in ("exponential", "gaussian") else "n/a"
            assert full["consistency"] == consistent
            fallback = network_decision(distributions, "candidates")
            assert fallback["network_label"] == {"exponential": "scale-free", "gaussian": "exponential"}.get(
                betweenness, "inconclusive")
            assert fallback["label_basis"] == "betweenness_fallback" and fallback["consistency"] == "n/a"
    with pytest.raises(ValueError, match="coverage"):
        network_decision(distributions, "unknown")
    assert agreement("scale-free", "power_law_like") == "agreement"
    assert agreement("exponential", "poisson_like") == "agreement"
    assert agreement("scale-free", "poisson_like") == "disagreement"
    assert agreement("inconclusive", "poisson_like") == "inconclusive"
    assert agreement("scale-free", "inconclusive") == "inconclusive"


def test_independent_discrete_degree_evidence_on_common_support():
    for simple, expected in ((nx.fast_gnp_random_graph(500, 6/499, seed=42), "poisson_like"),
                             (nx.barabasi_albert_graph(500, 3, seed=42), "power_law_like")):
        x = np.array([degree for _, degree in simple.degree()])
        fit = degree_evidence(x, 500)
        assert fit["verdict"] == expected
        x = x[x > 0]
        k = np.arange(fit["support_min"], 500)
        log_p = k * math.log(fit["poisson_lambda"]) - gammaln(k + 1)
        log_q = -fit["power_law_alpha"] * np.log(k)
        indices = x - fit["support_min"]
        ll_p = np.sum((log_p - logsumexp(log_p))[indices])
        ll_q = np.sum((log_q - logsumexp(log_q))[indices])
        assert fit["delta_aic"] == pytest.approx(2 * (ll_q - ll_p))
        assert fit["aic_poisson"] - fit["aic_power_law"] == pytest.approx(fit["delta_aic"])
    assert degree_evidence(np.ones(60), 60)["verdict"] == "inconclusive"
    with pytest.raises(ValueError, match="integer"):
        degree_evidence(np.tile([1., 2., 3.5], 20), 60)


def test_coverage_missing_information_and_supporting_evidence_do_not_leak(monkeypatch):
    # Mock only fitting: decision behavior is tested independently of random
    # distribution draws, and verifies exactly which values reach the fitter.
    def fitted(values, *, discrete=False):
        array = np.asarray(values)
        return {"verdict": "exponential" if len(array) == 60 else "power_law",
                "positive_count": int(np.count_nonzero(np.isfinite(array) & (array > 0)))}
    monkeypatch.setattr("georesilience.classification.fit_distribution", fitted)
    values = {name: np.arange(1, 61, dtype=float) for name in DISTRIBUTIONS}
    values["degree"] = np.tile([1, 2, 3], 20)
    values["information"] = np.r_[np.ones(10), np.full(50, np.nan)]
    result = classify_network(values, {"coverage": "candidates"}, {"nodes": {"auc_failure_S": .9, "auc_attack_S": .7}})
    assert result.summary["network_label"] == "scale-free"
    assert result.summary["label_basis"] == "betweenness_fallback"
    assert result.summary["distributions"]["information"]["positive_count"] == 10
    assert result.summary["attack_failure_gap"] == pytest.approx(.2)
    for curves in ({}, {"nodes": {"auc_failure_S": .7, "auc_attack_S": .9}},
                   {"nodes": {"auc_failure_S": .9, "auc_attack_S": .9}}):
        other = classify_network(values, {"coverage": "candidates"}, curves)
        assert other.summary["network_label"] == result.summary["network_label"]
    assert classify_network(values, {"coverage": "all"}, {}).summary["network_label"] == "exponential"


def small_graph(path):
    simple = nx.barabasi_albert_graph(60, 2, seed=4)
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    for node in simple:
        graph.add_node(node, x=float(500000 + 10 * node), y=float(1900000 + 10 * (node % 7)))
    for way, (u, v) in enumerate(simple.edges, 1):
        for a, b in ((u, v), (v, u)):
            graph.add_edge(a, b, length=1000., osmid=way, highway="residential")
    ox.save_graphml(graph, path)


def test_pipeline_outputs_figures_resolved_config_and_fallback(tmp_path):
    source = tmp_path / "graph.graphml"
    small_graph(source)
    config = RunConfig(input={"path": source}, cleaning={"consolidate": False},
                       analysis={"n_jobs": 1, "max_memory_gb": .1},
                       criticality={"k_betweenness": 0, "k_detour": 0, "exact_info_max_nodes": 60},
                       robustness={"removal": ["nodes"], "steps": 2, "failure_runs": 2},
                       output={"dir": tmp_path / "out"})
    summary = run(config)
    classification = summary["classification"]
    assert classification["label_basis"] == "information" and classification["information_coverage"] == "all"
    assert set(classification["distributions"]) == set(DISTRIBUTIONS)
    json.dumps(classification, allow_nan=False)
    report = (config.output.dir / "report.txt").read_text()
    assert "Network class" in report and "excluded from the network label" in report
    assert max(map(len, report.splitlines())) <= 100 and report.isascii()
    for filename in CLASSIFICATION_FIGURES:
        assert (config.output.dir / "figures" / filename).stat().st_size > 1000
    resolved = load_config(config.output.dir / "run_config.yaml")
    assert resolved == config
    assert "powerlaw" in (config.output.dir / "run_config.yaml").read_text()
    resolved.criticality.exact_info_max_nodes = 0
    resolved.criticality.k_nodes = 3
    resolved.output.figures = False
    changed = run(resolved, overwrite=True)["classification"]
    assert changed["label_basis"] == "betweenness_fallback"
    assert changed["distributions"]["information"]["nonfinite_dropped"] == 57
    assert "information centrality computed on the candidate set only; excluded from classification" in (
        config.output.dir / "report.txt").read_text()
    assert not (config.output.dir / "figures").exists()


def test_benchmark_runner_and_reaggregation(tmp_path):
    root = tmp_path / "benchmark"
    command = [sys.executable, "examples/run_ticket07_benchmark.py", "--nodes", "60", "--seeds", "7",
               "--figures", "none", "--n-jobs", "1", "--data-dir", str(tmp_path / "data"), "--out", str(root)]
    completed = subprocess.run(command, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    comparison = json.loads((root / "comparison.json").read_text())
    assert len(comparison["cases"]) == 2
    assert {row["model"] for row in comparison["cases"]} == {"er", "scale-free"}
    assert all(row["information_coverage"] == "all" and row["nodes"] == 60 for row in comparison["cases"])
    assert all(row["label_basis"] == "information" for row in comparison["cases"])
    original = (root / "comparison.csv").read_bytes()
    repeat = subprocess.run([sys.executable, "examples/run_ticket07_benchmark.py", "--summarize-only", "--out", str(root)],
                            capture_output=True, text=True)
    assert repeat.returncode == 0, repeat.stderr
    assert (root / "comparison.csv").read_bytes() == original
    refused = subprocess.run(command, capture_output=True, text=True)
    assert refused.returncode != 0 and "nonempty" in refused.stderr
    manifest = json.loads((root / "benchmark_manifest.json").read_text())
    assert len(manifest["cases"]) == 2
    for case in manifest["cases"]:
        config = load_config(Path(case["config"]))
        assert config.criticality.exact_info_max_nodes == 60 and config.robustness.removal == ["nodes"]
