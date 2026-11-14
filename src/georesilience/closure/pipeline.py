"""Transactional enrichment of immutable cleaned physical road features."""

import csv
import hashlib
import importlib.metadata
import json
import math
import shutil
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from pyproj import CRS

from ..failure_probabilities import FINGERPRINT_PREFIX, read_failure_csv
from .config import ClosureConfig
from .grids import (
    RasterSampler,
    TerrainUnavailable,
    line_cells,
    recover_raster,
    validate_raster,
)
from .probability import closure_probability
from .rainfall import validate_rainfall_inputs
from .sfincs import run_simulation

MODEL_VERSION = "flood-closure-1.0"


@dataclass(frozen=True)
class ClosureRunResult:
    network: Path
    manifest: Path
    coverage_report: Path
    probabilities_csv: Path | None
    road_count: int


def _hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _network(config):
    layers = dict(pyogrio.list_layers(config.roads))
    if config.layer not in layers:
        raise ValueError(f"roads layer {config.layer!r} is absent")
    roads = gpd.read_file(config.roads, layer=config.layer, engine="pyogrio")
    required = {"link_uid", "u", "v", "length_m"}
    if not required <= set(roads):
        raise ValueError("cleaned edges require link_uid,u,v,length_m")
    if roads.empty or roads.crs is None:
        raise ValueError("cleaned roads must be nonempty and have a CRS")
    if (
        roads.geometry.isna().any()
        or roads.geometry.is_empty.any()
        or not roads.geometry.is_valid.all()
    ):
        raise ValueError("cleaned road geometries must be nonempty and valid")
    if not roads.geometry.geom_type.isin(["LineString", "MultiLineString"]).all():
        raise ValueError("cleaned roads require line geometries")
    if (
        roads.link_uid.isna().any()
        or roads.link_uid.duplicated().any()
        or not roads.link_uid.map(
            lambda x: isinstance(x, str) and bool(x.strip())
        ).all()
    ):
        raise ValueError(
            "link_uid requires unique nonempty strings; physical links must not be duplicated"
        )
    if roads[["u", "v"]].isna().any().any():
        raise ValueError("road endpoints cannot be missing")
    lengths = pd.to_numeric(roads.length_m, errors="raise").to_numpy(float)
    if not np.isfinite(lengths).all() or (lengths <= 0).any():
        raise ValueError("length_m must be finite and positive")
    if {"input_p_fail", "input_p_fail_source"} & set(roads):
        raise ValueError(
            "conflicting provenance fields: input_p_fail/input_p_fail_source already present"
        )
    if config.road_elevation_attribute and config.road_elevation_attribute not in roads:
        raise ValueError("road_elevation_attribute does not exist")
    nodes = (
        gpd.read_file(config.roads, layer="nodes", engine="pyogrio")
        if "nodes" in layers
        else None
    )
    if nodes is not None and "node_id" in nodes:
        ids = set(nodes.node_id.astype(str))
        if not (set(roads.u.astype(str)) | set(roads.v.astype(str))) <= ids:
            raise ValueError("road endpoints are absent from the supplied nodes layer")
    metric = roads.crs
    if not CRS(metric).is_projected or any(
        abs(axis.unit_conversion_factor - 1) > 1e-9 for axis in CRS(metric).axis_info
    ):
        metric = roads.estimate_utm_crs()
    if metric is None:
        raise ValueError("cannot determine a metric CRS for the supplied network")
    return roads, nodes, CRS(metric)


def _template(config, roads):
    if config.failure_template is None:
        return None
    lines = config.failure_template.read_text(encoding="utf-8-sig").splitlines()
    fingerprints = [
        line[len(FINGERPRINT_PREFIX) :].strip()
        for line in lines
        if line.startswith(FINGERPRINT_PREFIX)
    ]
    if len(fingerprints) != 1 or not fingerprints[0]:
        raise ValueError(
            "failure template must contain one nonempty cleaning fingerprint"
        )
    reader = csv.DictReader(
        line for line in lines if line.strip() and not line.lstrip().startswith("#")
    )
    if not reader.fieldnames or not {"link_uid", "p_fail"} <= set(reader.fieldnames):
        raise ValueError("failure template requires link_uid,p_fail columns")
    records = list(reader)
    expected = set(roads.loc[roads.u.astype(str) != roads.v.astype(str), "link_uid"])
    ids = [row["link_uid"].strip() for row in records]
    if (
        len(ids) != len(set(ids))
        or set(ids) != expected
        or any(None in row or any(v is None for v in row.values()) for row in records)
    ):
        raise ValueError(
            "failure template link_uid set must exactly match non-self-loop cleaned edges"
        )
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError("failure template has duplicate columns")
    # The physical export does not encode a graph fingerprint. Also bind to its sibling manifest if available.
    sibling = config.roads.parent / "run_manifest.json"
    if sibling.exists():
        metadata = json.loads(sibling.read_text())
        original = metadata.get("input_cleaning_fingerprint")
        if original is not None and original != fingerprints[0]:
            raise ValueError(
                "failure template fingerprint differs from the cleaned network manifest"
            )
    return fingerprints[0], reader.fieldnames, records


def _structure(row):
    def affirmative(value):
        return str(value).strip().lower() not in (
            "",
            "no",
            "false",
            "0",
            "none",
            "nan",
            "<na>",
        )

    for field in ("bridge", "tunnel", "covered", "elevated"):
        if field in row and affirmative(row[field]):
            return True
    return bool("layer" in row and affirmative(row["layer"]))


def _elevation(row, config):
    if not config.road_elevation_attribute:
        return None
    value = row[config.road_elevation_attribute]
    if pd.isna(value):
        return None
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("road elevations must be finite metres or missing")
    return value


def _carriageway_depth(ground_depth, water_level, elevation, flags):
    if ground_depth is None or water_level is None:
        return None
    if ground_depth == 0 and elevation < water_level:
        # A dry surface cell has no observed water surface at terrain elevation.
        # It cannot establish whether a below-ground carriageway is flooded.
        flags.append("below_ground_carriageway_water_depth_unresolved")
        return None
    flags.append("carriageway_hydraulic_connectivity_assumed")
    return max(0.0, water_level - elevation)


def _extract(
    roads,
    metric,
    config,
    supplied=None,
    dem=None,
    reconstruction=None,
    simulated=None,
    water=None,
    sim_metadata=None,
    terrain_reconstruction=None,
    simulation_unavailable=None,
):
    result = []
    with ExitStack() as stack:
        samplers = {
            key: stack.enter_context(RasterSampler(path))
            for key, path in (
                ("supplied", supplied),
                ("dem", dem),
                ("reconstruction", reconstruction),
                ("simulated", simulated),
                ("water", water),
                ("terrain_reconstruction", terrain_reconstruction),
            )
            if path is not None
        }
        # Overlay supported cells from the finer supplied grid first; secondary simulation
        # is integrated on its own cell boundaries, never inferred from adjacent road probabilities.
        for _, row in roads.iterrows():
            flags, reconstruction_flags = [], []
            elevation = _elevation(row, config)
            structure = _structure(row)
            maximum = None
            supported = total = 0.0
            used = set()
            primary = samplers.get("supplied") or samplers.get("simulated")
            if (
                structure
                and elevation is None
                and not (supplied and config.depth_reference == "road")
            ):
                flags.append("structure_carriageway_elevation_unknown")
                primary = None
            elif elevation is not None:
                flags.append(
                    "road_elevation_constant_per_feature_same_vertical_datum_assumed"
                )
            if primary:
                for r, c, length, x, y in line_cells(
                    row.geometry,
                    roads.crs,
                    primary,
                    metric,
                    [samplers[k] for k in ("dem", "simulated") if k in samplers],
                ):
                    # Where a supplied grid and a simulation overlap, split the original
                    # line at both grids rather than classifying a long missing segment by midpoint.
                    value = primary.value(r, c)
                    source = "supplied" if supplied else "simulated"
                    if source == "supplied":
                        if value is not None:
                            if config.depth_reference == "water_surface":
                                ground = (
                                    elevation
                                    if elevation is not None
                                    else samplers["dem"].at_xy(x, y, primary.crs)
                                )
                                value = (
                                    None if ground is None else max(0.0, value - ground)
                                )
                            elif (
                                config.depth_reference == "ground"
                                and elevation is not None
                            ):
                                ground = (
                                    samplers["dem"].at_xy(x, y, primary.crs)
                                    if "dem" in samplers
                                    else None
                                )
                                value = _carriageway_depth(
                                    value,
                                    None if ground is None else value + ground,
                                    elevation,
                                    flags,
                                )
                            if (
                                value is not None
                                and "reconstruction" in samplers
                                and samplers["reconstruction"].value(r, c) == 1
                            ):
                                reconstruction_flags.append(
                                    "connected_flood_linear_recovery"
                                )
                                source = "reconstructed"
                            if (
                                value is not None
                                and "terrain_reconstruction" in samplers
                                and (
                                    elevation is not None
                                    or config.depth_reference == "water_surface"
                                )
                            ) and (
                                samplers["terrain_reconstruction"].at_xy(
                                    x, y, primary.crs
                                )
                                == 1
                            ):
                                reconstruction_flags.append(
                                    "linear_terrain_recovery_at_road"
                                )
                    elif elevation is not None:
                        level = samplers["water"].value(r, c)
                        value = _carriageway_depth(value, level, elevation, flags)
                    if (
                        value is None
                        and source in ("supplied", "reconstructed")
                        and "simulated" in samplers
                    ):
                        if elevation is None:
                            value = samplers["simulated"].at_xy(x, y, primary.crs)
                        else:
                            level = samplers["water"].at_xy(x, y, primary.crs)
                            ground_depth = samplers["simulated"].at_xy(
                                x, y, primary.crs
                            )
                            value = _carriageway_depth(
                                ground_depth, level, elevation, flags
                            )
                        source = "simulated"
                    total += length
                    if value is not None:
                        supported += length
                        maximum = value if maximum is None else max(maximum, value)
                        used.add(source)
            coverage = min(1.0, max(0.0, supported / total)) if total else 0.0
            if sim_metadata and "simulated" in used:
                for flag in sim_metadata["flags"]:
                    (
                        reconstruction_flags
                        if any(
                            k in flag
                            for k in (
                                "interpolat",
                                "extrapolat",
                                "recovery",
                                "reconstruction",
                            )
                        )
                        else flags
                    ).append(flag)
                rainfall_source = (
                    "mixed"
                    if used - {"simulated"}
                    else sim_metadata["rainfall"]["source"]
                )
            else:
                rainfall_source = "unavailable" if not used else "event"
            if supplied and used:
                flags.append("supplied_event_maximum_depth_assumed_metres")
            if not structure:
                flags.append("ground_level_road_assumed_unless_elevation_supplied")
            if coverage < 1:
                flags.append("unresolved_hazard_uniform_per_road")
                if simulation_unavailable:
                    flags.append("insufficient_terrain_for_simulation")
            uniform = config.uniform_probability
            explicit_existing = False
            if (
                config.use_existing_probabilities
                and "p_fail" in row
                and pd.notna(row.p_fail)
            ):
                uniform = float(row.p_fail)
                if not math.isfinite(uniform) or not 0 <= uniform <= 1:
                    raise ValueError(
                        "requested input probabilities must be finite and in [0,1]"
                    )
                explicit_existing = True
                flags.append("input_probability_explicitly_used_for_unresolved_hazard")
            probability, source = closure_probability(
                maximum, coverage, uniform, config.threshold_m, config.dispersion
            )
            if explicit_existing and source != "depth_fragility":
                source = "hybrid_input" if coverage else "input_probability"
            result.append(
                {
                    "p_fail": probability,
                    "p_fail_source": source,
                    "depth_source": "mixed"
                    if len(used) > 1
                    else next(iter(used), "unavailable"),
                    "max_depth_m": maximum,
                    "depth_coverage": coverage,
                    "rainfall_source": rainfall_source,
                    "reconstruction_flags": ";".join(sorted(set(reconstruction_flags))),
                    "scenario_id": config.scenario_id,
                    "calibration_status": "assumed",
                    "model_version": MODEL_VERSION,
                    "assumption_flags": ";".join(sorted(set(flags))),
                }
            )
    return pd.DataFrame(result, index=roads.index)


def _supplied(config, stage):
    depth = config.depth
    dem = config.dem
    mask = None
    counts = {}
    if dem and depth:
        target = stage / "recovered_dem.tif"
        counts["terrain_filled_cells"] = recover_raster(
            dem, target, stage / "terrain_reconstruction.tif"
        )
        dem = target
    if depth and config.flood_zones:
        target = stage / "recovered_depth.tif"
        mask = stage / "depth_reconstruction.tif"
        # Interpolating water level is preferable; raw depth recovery is limited to
        # explicit same-source wet hydraulic partitions with no intervening dry cell.
        counts["depth_filled_cells"] = recover_raster(
            depth,
            target,
            mask,
            zones_path=config.flood_zones,
            elevation_path=dem,
            water_surface=config.depth_reference == "water_surface",
        )
        counts["depth_reconstruction_method"] = (
            "water_surface_linear_minus_terrain" if dem else "connected_depth_linear"
        )
        depth = target
    return depth, dem, mask, counts


def _coverage_report(frame, metadata):
    lines = [
        "Flood-induced road closures for one event/scenario",
        "",
        f"Road features: {len(frame)}",
        "Probability sources: "
        + json.dumps(frame.p_fail_source.value_counts().to_dict()),
        f"Fully supported roads: {int((frame.depth_coverage >= 1 - 1e-9).sum())}",
        f"Partially supported roads: {int(((frame.depth_coverage > 0) & (frame.depth_coverage < 1 - 1e-9)).sum())}",
        "",
        "Probabilities are uncalibrated screening estimates, not annual probabilities.",
        "Uniform fallback is applied once per unresolved road, independent of road length.",
        "Depth coverage measures data completeness; it does not scale the fallback.",
        "The hybrid formula assumes independence of modeled and unresolved contributions.",
        "Velocity, scour, vehicle variation, and administrative closures are not modeled.",
    ]
    if metadata:
        lines.extend(
            [
                "",
                "Rainfall: " + json.dumps(metadata["rainfall"]),
                "Boundary: " + metadata["boundary"],
                "Simulation assumptions affecting contributing areas: "
                + ", ".join(metadata["flags"]),
            ]
        )
    return "\n".join(lines) + "\n"


def _write_csv(stage, template, roads, frame):
    if template is None:
        return
    fingerprint, columns, records = template
    values = dict(zip(roads.link_uid, frame.p_fail))
    with (stage / "failure_probabilities.csv").open("w", newline="", encoding="utf-8") as stream:
        stream.write(
            "# Closure probabilities per road per event; self-loops omitted.\n"
            + FINGERPRINT_PREFIX
            + fingerprint
            + "\n"
        )
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in records:
            row["p_fail"] = repr(values[row["link_uid"].strip()])
            writer.writerow(row)
    links = [
        {"link_uid": r.link_uid, "is_self_loop": str(r.u) == str(r.v)}
        for _, r in roads.iterrows()
    ]
    read_failure_csv(
        stage / "failure_probabilities.csv", links, fingerprint, require_complete=True
    )


def _sensitivity(config, roads, metric, stage, hazard, baseline):
    settings = config.sensitivity
    rows = []
    if not settings.enabled:
        return

    def append(name, frame):
        for uid, p in zip(roads.link_uid, frame.p_fail):
            rows.append({"scenario": name, "link_uid": uid, "p_fail": p})

    append("baseline", baseline)
    for threshold in settings.thresholds_m:
        c = config.model_copy(update={"threshold_m": threshold})
        append(f"threshold_{threshold:g}m", _extract(roads, metric, c, **hazard))
    for uniform in settings.uniform_probabilities:
        c = config.model_copy(update={"uniform_probability": uniform})
        append(f"uniform_{uniform:g}", _extract(roads, metric, c, **hazard))
    if hazard["simulated"] is not None:
        for multiplier in settings.rainfall_multipliers:
            name = f"rainfall_{multiplier:g}"
            depth, water, meta = run_simulation(
                config,
                metric,
                stage / "sensitivity" / name,
                rainfall_multiplier=multiplier,
            )
            append(
                name,
                _extract(
                    roads,
                    metric,
                    config,
                    **{
                        **hazard,
                        "simulated": depth,
                        "water": water,
                        "sim_metadata": meta,
                    },
                ),
            )
        if "default_CN_upstream_possible" in hazard["sim_metadata"]["flags"]:
            for cn in settings.assumed_curve_numbers:
                name = f"CN_{cn:g}"
                c = config.model_copy(
                    update={
                        "simulation": config.simulation.model_copy(
                            update={"curve_number": cn}
                        )
                    }
                )
                depth, water, meta = run_simulation(
                    c, metric, stage / "sensitivity" / name
                )
                append(
                    name,
                    _extract(
                        roads,
                        metric,
                        c,
                        **{
                            **hazard,
                            "simulated": depth,
                            "water": water,
                            "sim_metadata": meta,
                        },
                    ),
                )
    sensitivity = pd.DataFrame(rows)
    sensitivity.to_csv(stage / "sensitivity.csv", index=False)
    sensitivity.groupby("link_uid").p_fail.agg(
        sensitivity_min="min", sensitivity_max="max"
    ).to_csv(stage / "sensitivity_range.csv")
    (stage / "sensitivity.txt").write_text(
        "Parameter sensitivity scenarios, not confidence intervals. Rainfall/CN scenarios rerun SFINCS. CN sweeps apply where a uniform CN is assumed; rainfall/CN sweeps require a simulated hazard contribution. Supplied event depths retain precedence.\n"
    )


def enrich_road_closures(config: ClosureConfig) -> ClosureRunResult:
    """Preserve cleaned features and publish a complete, audited output directory."""
    config = ClosureConfig.model_validate(config)
    out = config.out.expanduser().resolve()
    inputs = config.input_paths()
    sibling = config.roads.parent / "run_manifest.json"
    if config.failure_template and sibling.is_file():
        inputs["network_manifest"] = sibling
    for key, path in inputs.items():
        if not path.is_file():
            raise ValueError(f"missing input {key}: {path}")
        if path.resolve() == out or out in path.resolve().parents:
            raise ValueError("output directory cannot contain a consumed input")
    if out.exists() and (
        not out.is_dir() or (any(out.iterdir()) and not config.overwrite)
    ):
        raise ValueError(
            "closure output exists; choose another directory or set overwrite"
        )
    if (
        out.exists()
        and any(out.iterdir())
        and not (out / "closure_manifest.json").is_file()
    ):
        raise ValueError(
            "refusing to overwrite an output directory not owned by the closure pipeline"
        )
    roads, nodes, metric = _network(config)
    template = _template(config, roads)
    validate_rainfall_inputs(config.rainfall)
    for name in (
        "dem",
        "depth",
        "flood_zones",
        "landcover",
        "soil_groups",
        "curve_number_map",
        "roughness_map",
    ):
        if path := getattr(config, name):
            validate_raster(
                path,
                nonnegative=name not in ("dem", "depth")
                or (name == "depth" and config.depth_reference != "water_surface"),
                categorical=name in ("flood_zones", "landcover", "soil_groups"),
                units="m" if name in ("dem", "depth") else None,
            )
    if config.domain:
        domain = gpd.read_file(config.domain)
        if (
            domain.empty
            or domain.crs is None
            or not domain.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all()
            or not domain.is_valid.all()
        ):
            raise ValueError("domain requires valid georeferenced polygons")
    hashes = {
        key: {"path": str(path.resolve()), "sha256": _hash(path)}
        for key, path in inputs.items()
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".closure-", dir=out.parent))
    try:
        supplied, dem, mask, recovery = _supplied(config, stage)
        simulation = None
        simulation_unavailable = None
        simulated = water = None
        # Supplied event depths take precedence; a physical simulation may supply
        # missing coverage. Unknown structures still require carriageway elevation.
        preliminary = _extract(
            roads, metric, config, supplied=supplied, dem=dem, reconstruction=mask
        )
        candidates = (
            preliminary.depth_coverage < 1 - 1e-9
        ) & ~preliminary.assumption_flags.str.contains(
            "structure_carriageway_elevation_unknown"
        )
        needs_simulation = False
        if config.dem and candidates.any():
            from shapely.geometry import box

            with RasterSampler(config.dem) as terrain:
                needs_simulation = (
                    roads.loc[candidates]
                    .to_crs(terrain.crs)
                    .intersects(box(*terrain.dataset.bounds))
                    .any()
                )
        if config.dem and (config.depth is None or needs_simulation):
            try:
                simulated, water, simulation = run_simulation(
                    config, metric, stage / "simulation"
                )
            except TerrainUnavailable as exc:
                # Only pre-solver physical coverage failures are recoverable.
                # Invalid inputs and solver failures must still abort publication.
                simulation_unavailable = str(exc)
            else:
                shutil.copyfile(simulated, stage / "maximum_depth.tif")
        terrain_mask = stage / "terrain_reconstruction.tif"
        hazard = {
            "supplied": supplied,
            "dem": dem,
            "reconstruction": mask,
            "simulated": simulated,
            "water": water,
            "sim_metadata": simulation,
            "terrain_reconstruction": terrain_mask if terrain_mask.exists() else None,
            "simulation_unavailable": simulation_unavailable,
        }
        frame = _extract(roads, metric, config, **hazard)
        enriched = roads.copy()
        for field in ("p_fail", "p_fail_source"):
            if field in enriched:
                enriched["input_" + field] = enriched[field]
        for field in frame:
            enriched[field] = frame[field]
        network = stage / "network_with_closure.gpkg"
        if nodes is not None:
            nodes.to_file(
                network, layer="nodes", driver="GPKG", engine="pyogrio", index=False
            )
        enriched.to_file(
            network, layer="edges", driver="GPKG", engine="pyogrio", index=False
        )
        # Verify identity after serialization, including self-loops, coordinate arrays and CRS.
        check = gpd.read_file(network, layer="edges", engine="pyogrio")
        if (
            not check[["link_uid", "u", "v"]].equals(roads[["link_uid", "u", "v"]])
            or check.crs != roads.crs
            or not np.array_equal(
                check.geometry.to_wkb().values, roads.geometry.to_wkb().values
            )
        ):
            raise RuntimeError(
                "export changed original link identity, geometry, or CRS"
            )
        if not np.isfinite(check.p_fail).all() or not check.p_fail.between(0, 1).all():
            raise RuntimeError("not every exported road has a valid probability")
        _write_csv(stage, template, roads, frame)
        _sensitivity(config, roads, metric, stage, hazard, frame)
        report = _coverage_report(frame, simulation)
        if simulation_unavailable:
            report += "\nSimulation unavailable: " + simulation_unavailable + "\n"
        (stage / "coverage_report.txt").write_text(report)
        for key, path in inputs.items():
            if _hash(path) != hashes[key]["sha256"]:
                raise RuntimeError(
                    "an input changed during processing; publication cancelled"
                )
        versions = {}
        for name in (
            "georesilience",
            "numpy",
            "scipy",
            "geopandas",
            "pandas",
            "rasterio",
            "pyproj",
            "shapely",
            "pyogrio",
            "xarray",
            "netCDF4",
            "pykrige",
        ):
            try:
                versions[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                versions[name] = None
        manifest = {
            "status": "complete",
            "model_version": MODEL_VERSION,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "scenario_id": config.scenario_id,
            "config": config.model_dump(mode="json"),
            "inputs": hashes,
            "versions": versions,
            "simulation": simulation,
            "simulation_unavailable": simulation_unavailable,
            "recovery": recovery,
            "validation": {
                "roads": len(roads),
                "nodes": None if nodes is None else len(nodes),
                "identity_geometry_crs_preserved": True,
                "all_probabilities_valid": True,
                "probability_sources": frame.p_fail_source.value_counts().to_dict(),
                "template_fingerprint": template[0] if template else None,
            },
            "probability_contract": "Phi(log(d/theta)/beta); hybrid=q+(1-q)*uniform once per road; no length fallback",
            "calibration_status": "assumed",
            "outputs": sorted(
                str(p.relative_to(stage)) for p in stage.rglob("*") if p.is_file()
            ),
        }
        manifest["implementation_sha256"] = {
            p.name: _hash(p) for p in Path(__file__).parent.glob("*.py")
        }
        manifest["recovery_contract"] = {
            "terrain": "enclosed source-grid holes <=3 cells per axis; linear",
            "depth": "enclosed connected wet partitions <=3 cells per axis; WSE-minus-DEM preferred",
            "support_distance": "metres to nearest original support; geographic terrain uses local geodesic scale",
            "rainfall_archive": "resolved_rainfall.npz retains interval edges, mm/hour, provenance codes, support distances",
        }
        (stage / "closure_manifest.json").write_text(
            json.dumps(manifest, indent=2, allow_nan=False) + "\n"
        )
        if out.exists():
            # Preserve unrelated files when replacing a prior successful run.
            old = (
                json.loads((out / "closure_manifest.json").read_text())
                if (out / "closure_manifest.json").exists()
                else {}
            )
            owned = set(old.get("outputs", [])) | {"closure_manifest.json"}
            for item in out.rglob("*"):
                relative = item.relative_to(out)
                if (
                    item.is_file()
                    and str(relative) not in owned
                    and not (stage / relative).exists()
                ):
                    (stage / relative).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, stage / relative)
            backup = Path(tempfile.mkdtemp(prefix=".closure-backup-", dir=out.parent))
            backup.rmdir()
            out.rename(backup)
            try:
                stage.rename(out)
            except BaseException:
                backup.rename(out)
                raise
            shutil.rmtree(backup)
        else:
            stage.rename(out)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return ClosureRunResult(
        out / "network_with_closure.gpkg",
        out / "closure_manifest.json",
        out / "coverage_report.txt",
        out / "failure_probabilities.csv" if template else None,
        len(roads),
    )
