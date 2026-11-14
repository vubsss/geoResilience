"""Canonical local facility CSV contract, independent of graph preparation."""

import csv
import math
from dataclasses import dataclass

from .config import ServicesConfig

SERVICE_TYPES = ("school", "hospital")
LOCATION_COLUMNS = ("facility_id", "service_type", "longitude", "latitude")
CAPACITY_COLUMNS = ("capacity", "capacity_unit", "capacity_source")
OPTIONAL_COLUMNS = ("name", "capacity_year", "notes")


@dataclass(frozen=True)
class FacilityRecord:
    facility_id: str
    service_type: str
    longitude: float
    latitude: float
    capacity: float | None
    capacity_unit: str | None
    capacity_source: str | None
    name: str = ""
    capacity_year: str = ""
    notes: str = ""


def load_facility_records(config: ServicesConfig) -> list[FacilityRecord]:
    """Validate every row; unknown capacity stays None and IDs stay strings.

    Weights-only accepts location-only tables. Supplied numeric values are always
    validated; 2SFCA requires complete capacity provenance, including known zero.
    Catchments are required for each category actually present in a 2SFCA table.
    """
    records, errors, seen, units = [], [], set(), {}
    try:
        with config.facilities_csv.expanduser().open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream, strict=True)
            headers = reader.fieldnames or []
            if not headers or any(not field.strip() for field in headers) or len(set(headers)) != len(headers):
                raise ValueError("facilities_csv: headers must be nonempty and unique")
            required = LOCATION_COLUMNS + (CAPACITY_COLUMNS if config.mode == "sfca" else ())
            missing = set(required) - set(headers)
            if missing:
                raise ValueError("facilities_csv: missing columns: " + ", ".join(sorted(missing)))
            for number, raw in enumerate(reader, 2):
                label = f"facilities_csv row {number}"
                if None in raw or any(value is None for value in raw.values()):
                    errors.append(f"{label}: number of fields does not match header")
                    continue
                row = {key: value.strip() for key, value in raw.items()}
                identifier = row["facility_id"]
                label += f" ({identifier!r})"
                if not identifier or identifier in seen:
                    errors.append(f"{label}: facility_id must be nonempty and unique")
                seen.add(identifier)
                category = row["service_type"]
                if category not in SERVICE_TYPES:
                    errors.append(f"{label}: service_type must be school or hospital")
                    continue
                settings = getattr(config, category)
                if config.mode == "sfca" and settings.catchment_minutes is None:
                    errors.append(f"{label}: {category} requires explicit positive catchment_minutes for 2SFCA")
                try:
                    lon, lat = float(row["longitude"]), float(row["latitude"])
                    if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
                        raise ValueError
                except ValueError:
                    errors.append(f"{label}: coordinates must be finite WGS84 longitude/latitude in valid bounds")
                    continue
                capacity = None
                value = row.get("capacity", "")
                if value:
                    try:
                        capacity = float(value)
                        if not math.isfinite(capacity) or capacity < 0:
                            raise ValueError
                    except ValueError:
                        errors.append(f"{label}: capacity must be finite and nonnegative")
                        continue
                elif config.mode == "sfca":
                    errors.append(f"{label}: capacity is required for 2SFCA; unknown supply cannot be inferred")
                unit, source = row.get("capacity_unit", ""), row.get("capacity_source", "")
                if config.mode == "sfca" and (not unit or not source):
                    errors.append(f"{label}: capacity_unit and capacity_source are required for 2SFCA (including zero supply)")
                if unit:
                    expected = units.setdefault(category, settings.capacity_unit or unit)
                    if unit != expected:
                        errors.append(f"{label}: incompatible {category} capacity_unit {unit!r}; expected {expected!r}")
                records.append(FacilityRecord(identifier, category, lon, lat, capacity, unit or None,
                    source or None, **{field: row.get(field, "") for field in OPTIONAL_COLUMNS}))
    except csv.Error as exc:
        raise ValueError(f"facilities_csv: invalid CSV: {exc}") from exc
    if errors:
        raise ValueError("facility validation failed:\n" + "\n".join(errors))
    return sorted(records, key=lambda row: row.facility_id)
