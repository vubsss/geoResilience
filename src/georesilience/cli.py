"""Local road-network resilience commands."""

import argparse
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from xml.etree.ElementTree import ParseError

from . import __version__
from .config import RunConfig
from .inputs import directory_config


def _assignments(values, label):
    result = {}
    for item in values or []:
        try:
            key, value = item.split("=", 1)
            if not key.strip() or key in result:
                raise ValueError
            result[key] = float(value)
        except ValueError as exc:
            raise ValueError(f"{label} requires unique NAME=NUMBER values: {item!r}") from exc
    return result


def _network_flags(parser):
    parser.add_argument("input_dir", type=Path, help="directory with exactly one road network and one count GeoTIFF")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true", help="replace known generated files, preserving unknown files")
    parser.add_argument("--boundary", type=Path)
    parser.add_argument("--network-type", choices=("drive", "all"), default="drive", help="XML filter; GraphML is analysed as supplied")
    parser.add_argument("--consolidation-m", type=float, default=15)
    parser.add_argument("--no-consolidation", action="store_true")
    parser.add_argument("--snap-max-m", type=float, default=500)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="georesilience", description="Analyse local roads and population counts together.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    analysis = commands.add_parser("run", help="analyse an input directory")
    _network_flags(analysis)
    template = commands.add_parser("failures-template", help="export fingerprint-bound physical-link probabilities")
    _network_flags(template)
    analysis.add_argument("--no-figures", action="store_true")
    analysis.add_argument("--failure-probs", type=Path)
    analysis.add_argument("--p0", type=float, default=.01, help="per-km closure probability during one event (default: .01)")
    analysis.add_argument("--require-complete-failures", action="store_true")
    analysis.add_argument("--p0-sweep", action="append", metavar="NAME=P0", help="repeat reliability under a named probability scenario; repeatable")
    analysis.add_argument("--connectivity-samples", type=int, default=10000)
    analysis.add_argument("--travel-time-samples", type=int, default=1000)
    analysis.add_argument("--time-threshold", type=float, default=.5, help="damaged time <= (1 + threshold) * baseline time")
    analysis.add_argument("--od-pairs", type=Path)
    analysis.add_argument("--time-model", choices=("free-flow", "edge-attribute"), default="free-flow")
    analysis.add_argument("--time-attribute", default="travel_time_s", help="edge-attribute cost in seconds")
    analysis.add_argument("--speed", action="append", metavar="HIGHWAY=KPH")
    analysis.add_argument("--simulate-traffic", action="store_true", help="run Tier 4 assignment using node population by default, or supplied OD/zones")
    analysis.add_argument("--traffic-od", type=Path, help="CSV with origin,destination,demand_pcu_h node IDs")
    analysis.add_argument("--traffic-zones", type=Path, help="CSV with node,mass for synthetic gravity demand")
    analysis.add_argument("--traffic-demand-pcu-h", type=float)
    analysis.add_argument("--traffic-gravity-lambda-per-min", type=float, default=0.08)
    analysis.add_argument("--traffic-population-trip-rate-per-person-h", type=float, default=0.1,
        help="assumed motorized PCU trips per resident per hour for population-based demand")
    analysis.add_argument("--traffic-population-zone-limit", type=int, default=100,
        help="maximum population-weighted spatial zones used to bound OD assignment size")
    analysis.add_argument("--traffic-capacity-pcu-h", type=float, help="uniform directed-edge capacity assumption")
    analysis.add_argument("--traffic-capacities", type=Path, help="CSV with u,v,key,capacity_pcu_h")
    analysis.add_argument("--traffic-capacity-per-lane-pcu-h", type=float, default=1000,
        help="assumed capacity per effective lane when deriving from width/lanes (default: 1000)")
    analysis.add_argument("--traffic-default-lanes-per-direction", type=float, default=1,
        help="fallback effective lanes per direction when both width and lanes are untagged")
    analysis.add_argument("--traffic-lane-width-m", type=float, default=3.5,
        help="assumed lane width for inferring lanes from road width")
    analysis.add_argument("--traffic-edge-times", type=Path, help="CSV with u,v,key,travel_time_s; bypasses assignment")
    analysis.add_argument("--traffic-period", default="illustrative_one_hour")
    analysis.add_argument("--traffic-duration-h", type=float, default=1)
    analysis.add_argument("--traffic-vdf", choices=("bpr", "conical"), default="bpr")
    analysis.add_argument("--traffic-alpha", type=float, default=.15)
    analysis.add_argument("--traffic-beta", type=float, default=4)
    analysis.add_argument("--traffic-relative-gap", type=float, default=1e-4)
    analysis.add_argument("--traffic-max-iterations", type=int, default=200)
    analysis.add_argument("--traffic-closure-top-n", type=int, default=0)
    analysis.add_argument("--criticality-coverage", choices=("screened", "all"), default="screened")
    analysis.add_argument("--attack-fraction", type=float, default=.20)
    analysis.add_argument("--attack-steps", type=int, default=50)
    analysis.add_argument("--attack-order", choices=("adaptive", "static"), default="adaptive")
    analysis.add_argument("--half-distance-km", type=float, default=2)
    analysis.add_argument("--seed", type=int, default=42)
    analysis.add_argument("--jobs", default="auto", metavar="auto|N")
    analysis.add_argument("--max-memory-gb", default="auto", metavar="auto|N", help="shortest-path/simulation workspace budget; input graph storage is additional")
    args = parser.parse_args(argv)
    try:
        config = directory_config(args.input_dir, boundary=args.boundary, network_type=args.network_type,
            consolidation_m=args.consolidation_m, consolidate=not args.no_consolidation, snap_max_m=args.snap_max_m)
        if args.command == "failures-template":
            from .failure_probabilities import export_edge_template
            from .network import load_and_clean
            target = args.out.expanduser().resolve()
            consumed = {config.input.path.resolve(), Path(config.population.worldpop).resolve()}
            if config.input.boundary:
                consumed.add(config.input.boundary.resolve())
            if target in consumed:
                raise ValueError("template output cannot replace an input file")
            if target.exists() and (not target.is_file() or not args.overwrite):
                raise ValueError(f"template output exists: {target} (use --overwrite)")
            graph, _, _ = load_and_clean(config)
            content = export_edge_template(graph)
            target.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=target.parent, mode="w", encoding="utf-8", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
            try:
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        else:
            from .pipeline import run
            values = config.model_dump(mode="python")
            values.update(output={"dir": args.out, "figures": not args.no_figures},
                analysis={"seed": args.seed, "n_jobs": args.jobs if args.jobs == "auto" else int(args.jobs),
                    "max_memory_gb": args.max_memory_gb if args.max_memory_gb == "auto" else float(args.max_memory_gb)},
                criticality={"coverage": args.criticality_coverage},
                robustness={"fraction": args.attack_fraction, "steps": args.attack_steps, "order": args.attack_order},
                reliability={"p_fail_csv": args.failure_probs, "require_complete_failures": args.require_complete_failures,
                    "p0": args.p0, "p0_sweep": _assignments(args.p0_sweep, "--p0-sweep"),
                    "samples": args.connectivity_samples, "od_pairs_csv": args.od_pairs},
                travel_time={"samples": args.travel_time_samples, "tau": args.time_threshold,
                    "time_model": args.time_model.replace("-", "_"), "time_attribute": args.time_attribute,
                    "highway_speeds_kph": _assignments(args.speed, "--speed") if args.speed else None},
                traffic={"enabled": args.simulate_traffic, "source": "edge_times_csv" if args.traffic_edge_times else "assignment",
                    "period": args.traffic_period, "duration_h": args.traffic_duration_h,
                    "demand_source": "gravity" if args.traffic_zones else "od_csv" if args.traffic_od else "population",
                    "od_csv": args.traffic_od, "zone_mass_csv": args.traffic_zones,
                    "total_demand_pcu_h": args.traffic_demand_pcu_h,
                    "gravity_lambda_per_min": args.traffic_gravity_lambda_per_min,
                    "population_trip_rate_per_person_h": args.traffic_population_trip_rate_per_person_h,
                    "population_zone_limit": args.traffic_population_zone_limit,
                    "edge_times_csv": args.traffic_edge_times, "capacity_csv": args.traffic_capacities,
                    "capacity_pcu_h": args.traffic_capacity_pcu_h, "vdf": args.traffic_vdf,
                    "road_capacity_pcu_h_per_lane": args.traffic_capacity_per_lane_pcu_h,
                    "default_lanes_per_direction": args.traffic_default_lanes_per_direction,
                    "lane_width_m": args.traffic_lane_width_m,
                    "alpha": args.traffic_alpha, "beta": args.traffic_beta,
                    "relative_gap": args.traffic_relative_gap, "max_iterations": args.traffic_max_iterations,
                    "closure_top_n": args.traffic_closure_top_n},
                accessibility={"half_distance_km": args.half_distance_km})
            run(RunConfig.model_validate(values), overwrite=args.overwrite)
    except (ValueError, OSError, RuntimeError, ParseError) as exc:
        print(f"georesilience: {exc}", file=sys.stderr, flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
