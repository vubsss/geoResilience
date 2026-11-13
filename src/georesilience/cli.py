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
    parser.add_argument("input_dir", type=Path, help="directory with one road network and one count GeoTIFF (raster optional with --facilities)")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true", help="replace known generated files, preserving unknown files")
    parser.add_argument("--boundary", type=Path)
    parser.add_argument("--network-type", choices=("drive", "all"), default="drive", help="XML filter; GraphML is analysed as supplied")
    parser.add_argument("--consolidation-m", type=float, default=15)
    parser.add_argument("--no-consolidation", action="store_true")
    parser.add_argument("--snap-max-m", type=float, default=500)


def _service_settings(args):
    options = (args.service_mode, args.service_importance, args.service_catchment_minutes,
               args.service_unit, args.facility_snap_max_m, args.population_importance)
    if args.facilities is None:
        if any(value is not None for value in options):
            raise ValueError("service options require --facilities PATH")
        return None
    values = {"facilities_csv": args.facilities,
        "mode": "sfca" if args.service_mode == "2sfca" else "weights_only",
        "population_importance": 1 if args.population_importance is None else args.population_importance,
        "snap_max_m": 500 if args.facility_snap_max_m is None else args.facility_snap_max_m,
        "school": {}, "hospital": {}}
    for entries, option, field in ((args.service_importance, "--service-importance", "importance"),
            (args.service_catchment_minutes, "--service-catchment-minutes", "catchment_minutes")):
        for category, value in _assignments(entries, option).items():
            if category not in ("school", "hospital"):
                raise ValueError(f"{option}: category must be school or hospital: {category!r}")
            values[category][field] = value
    for entry in args.service_unit or []:
        category, separator, unit = entry.partition("=")
        if not separator or category not in ("school", "hospital") or not unit.strip() or "capacity_unit" in values[category]:
            raise ValueError("--service-unit requires unique school=UNIT or hospital=UNIT values")
        values[category]["capacity_unit"] = unit
    return values


def main(argv=None):
    parser = argparse.ArgumentParser(prog="georesilience", description="Analyse local roads and population counts together.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    analysis = commands.add_parser("run", help="analyse an input directory")
    _network_flags(analysis)
    template = commands.add_parser("failures-template", help="export fingerprint-bound physical-link probabilities")
    _network_flags(template)
    analysis.add_argument("--no-figures", action="store_true")
    analysis.add_argument("--population-importance", type=float, help="population-share coefficient in combined node importance (default: 1; requires --facilities)")
    analysis.add_argument("--facilities", type=Path, help="explicit WGS84 school/hospital CSV")
    analysis.add_argument("--service-mode", choices=("weights-only", "2sfca"), help="default: weights-only; 2sfca requires capacities and catchments")
    analysis.add_argument("--service-importance", action="append", metavar="TYPE=WEIGHT", help="nonnegative school/hospital importance; default 1 each")
    analysis.add_argument("--service-catchment-minutes", action="append", metavar="TYPE=MINUTES", help="explicit inclusive positive time threshold for each supplied 2sfca category")
    analysis.add_argument("--service-unit", action="append", metavar="TYPE=UNIT", help="optional expected capacity unit per category")
    analysis.add_argument("--facility-snap-max-m", type=float, help="inclusive facility snap limit in metres (default: 500)")
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
            consolidation_m=args.consolidation_m, consolidate=not args.no_consolidation, snap_max_m=args.snap_max_m,
            allow_missing_population=args.command == "run" and args.facilities is not None)
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
                accessibility={"half_distance_km": args.half_distance_km}, services=_service_settings(args))
            validated = RunConfig.model_validate(values)
            if validated.services is not None:
                from .service_inputs import load_facility_records
                load_facility_records(validated.services)
            run(validated, overwrite=args.overwrite)
    except (ValueError, OSError, RuntimeError, ParseError) as exc:
        print(f"georesilience: {exc}", file=sys.stderr, flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
