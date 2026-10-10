"""Generate and evaluate five ER and five BA graphs for Ticket 07.

Run from the repository root. Generator family and degree-model agreement are
research observations; they are never pass/fail requirements for the classifier.
"""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import yaml

from create_ticket06_demo import create_examples
from georesilience.config import RunConfig, load_config
from georesilience.pipeline import run


COLUMNS = ("model", "seed", "nodes", "links", "mean_degree", "max_degree", "information_coverage",
           "information_verdict", "information_alpha", "information_n_tail", "betweenness_verdict",
           "network_label", "label_basis", "consistency", "degree_verdict", "degree_delta_aic",
           "degree_tail_verdict", "degree_agreement", "generator_agreement", "attack_failure_gap")


def write_comparison(folder):
    manifest = json.loads((folder / "benchmark_manifest.json").read_text())
    rows = []
    for case in manifest["cases"]:
        summary = json.loads((folder / case["case_id"] / "summary.json").read_text())
        classification = summary["classification"]
        if summary["meta"]["node_count"] != manifest["nodes"] or classification["information_coverage"] != "all":
            raise ValueError(f"{case['case_id']}: expected every requested node and full information coverage")
        label = classification["network_label"]
        expected = "exponential" if case["model"] == "er" else "scale-free"
        info = classification["distributions"]["information"]
        rows.append({"model": case["model"], "seed": case["seed"], "nodes": summary["meta"]["node_count"],
                     "links": summary["meta"]["link_count"], "mean_degree": summary["metrics"]["degree"]["mean"],
                     "max_degree": summary["metrics"]["degree"]["max"],
                     "information_coverage": classification["information_coverage"],
                     "information_verdict": info["verdict"], "information_alpha": info["alpha"],
                     "information_n_tail": info["n_tail"],
                     "betweenness_verdict": classification["distributions"]["betweenness"]["verdict"],
                     "network_label": label, "label_basis": classification["label_basis"],
                     "consistency": classification["consistency"],
                     "degree_verdict": classification["degree_evidence"]["verdict"],
                     "degree_delta_aic": classification["degree_evidence"]["delta_aic"],
                     "degree_tail_verdict": classification["distributions"]["degree"]["verdict"],
                     "degree_agreement": classification["degree_agreement"],
                     "generator_agreement": ("inconclusive" if label == "inconclusive" else
                                             "agreement" if label == expected else "disagreement"),
                     "attack_failure_gap": classification["attack_failure_gap"]})
    with (folder / "comparison.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    totals = {}
    for comparison in ("degree_agreement", "generator_agreement"):
        counts = Counter(row[comparison] for row in rows)
        conclusive = counts["agreement"] + counts["disagreement"]
        totals[comparison] = {key: counts[key] for key in ("agreement", "disagreement", "inconclusive")}
        totals[comparison].update(conclusive_count=conclusive, total_count=len(rows),
                                  conclusion_fraction=conclusive / len(rows),
                                  agreement_fraction_of_conclusive=counts["agreement"] / conclusive if conclusive else None)
    result = {"cases": rows, "totals": totals, "parameters": manifest,
              "interpretation": "Cross-criterion agreement, not classification accuracy or proof about city morphology. "
                                "Degree evidence is relative common-support AIC; no absolute goodness-of-fit bootstrap."}
    (folder / "comparison.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    lines = ["Ticket 07: ER / BA classification benchmark",
             f"{len(rows)} graphs; {manifest['nodes']} nodes each; seeds {manifest['seeds']}",
             "Information coverage: all nodes in every case.",
             "Degree evidence: common-support discrete Poisson vs bounded power law; AIC difference > 10.",
             "The production network label follows information centrality, independently of degree.", "",
             "Model       Seed  Info verdict   Network label  Degree evidence  Degree agreement  Node AUC gap"]
    for row in rows:
        gap = f"{row['attack_failure_gap']:.6f}" if row["attack_failure_gap"] is not None else "N/A"
        lines.append(f"{row['model']:<12}{row['seed']:>4}  {row['information_verdict']:<15}"
                     f"{row['network_label']:<15}{row['degree_verdict']:<17}{row['degree_agreement']:<18}{gap}")
    for comparison, counts in totals.items():
        fraction = counts["agreement_fraction_of_conclusive"]
        lines.extend(["", f"{comparison}: {counts['agreement']} agreement, {counts['disagreement']} disagreement, "
                      f"{counts['inconclusive']} inconclusive; conclusions {counts['conclusive_count']}/{len(rows)}.",
                      f"Agreement among conclusive comparisons: {fraction:.1%}" if fraction is not None else
                      "Agreement among conclusive comparisons: unavailable."])
    lines.extend(["", result["interpretation"],
                  "ER generation is conditioned on connectedness; BA is a finite preferential-attachment sample.",
                  "Model families do not represent planned/self-organized cities automatically.",
                  "Efficiency convention: mean(1/d), different from AP2's spatial mean(d_E/d).",
                  "Do not tune thresholds or select seeds to improve agreement.",
                  "Each case has its own summary.json, report.txt, network.gpkg and robustness_curves.csv."])
    (folder / "report.txt").write_text("\n".join(lines) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", type=int, default=500)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44, 45, 46])
    parser.add_argument("--n-jobs", type=int, default=2)
    parser.add_argument("--data-dir", type=Path, default=Path("data/ticket07-demo"))
    parser.add_argument("--out", type=Path, default=Path("results/ticket07-benchmark"))
    parser.add_argument("--figures", choices=("representative", "all", "none"), default="representative")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--generate-only", action="store_true", help="Generate inputs/configs without analyses")
    parser.add_argument("--summarize-only", action="store_true", help="Rebuild comparison files from completed cases")
    args = parser.parse_args()
    if args.summarize_only:
        write_comparison(args.out)
        return
    if args.nodes < 50 or args.n_jobs < 1 or min(args.seeds) < 0 or len(set(args.seeds)) != len(args.seeds):
        parser.error("use at least 50 nodes, positive jobs, and distinct nonnegative seeds")
    if not args.generate_only and args.out.exists() and any(args.out.iterdir()) and not args.overwrite:
        parser.error("output is nonempty; use --overwrite")
    cases = []
    for seed in args.seeds:
        data_folder = args.data_dir / f"seed{seed}"
        models = create_examples(data_folder, n=args.nodes, seed=seed)
        for model in ("er", "scale-free"):
            case_id = f"{model}-seed{seed}"
            config = RunConfig(
                input={"path": (data_folder / f"{model}.graphml").resolve()}, cleaning={"consolidate": False},
                analysis={"seed": seed, "n_jobs": args.n_jobs, "max_memory_gb": .25},
                criticality={"k_betweenness": 25, "k_detour": 25, "k_nodes": 25,
                             "exact_info_max_nodes": args.nodes},
                robustness={"removal": ["nodes"], "steps": 20, "f_max": .2, "adaptive": True,
                            "node_attack_metric": "degree", "failure_runs": 10, "efficiency_sources": args.nodes},
                output={"dir": (args.out / case_id).resolve(), "figures": args.figures == "all" or
                        (args.figures == "representative" and seed == args.seeds[0])})
            config_path = data_folder / f"{model}.yaml"
            config_path.write_text(yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False))
            cases.append({"case_id": case_id, "model": model, "seed": seed,
                          "config": str(config_path.resolve()), "generator": models["graphs"][model]})
    if args.generate_only:
        print(f"Generated {len(cases)} inputs/configs under {args.data_dir}")
        return
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = {"nodes": args.nodes, "seeds": args.seeds, "n_jobs": args.n_jobs, "cases": cases,
                "figures": args.figures, "robustness": {"removal": ["nodes"], "steps": 20, "f_max": .2,
                    "adaptive": True, "node_attack_metric": "degree", "failure_runs": 10,
                    "efficiency_sources": args.nodes}}
    # Remove only stale aggregate files. Individual pipeline runs handle their
    # own artifacts; unrelated user files are never recursively deleted.
    for name in ("comparison.csv", "comparison.json", "report.txt"):
        (args.out / name).unlink(missing_ok=True)
    (args.out / "benchmark_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['case_id']}", flush=True)
        run(load_config(Path(case["config"])), overwrite=args.overwrite)
    result = write_comparison(args.out)
    print(json.dumps(result["totals"], indent=2))
    print(f"Comparison written to {args.out / 'comparison.csv'}")


if __name__ == "__main__":
    main()
