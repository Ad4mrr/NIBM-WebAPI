"""Create a realistic, deterministic demonstration dataset."""

from __future__ import annotations

import argparse
import math
import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from slsea_api.database import SessionLocal, init_db
from slsea_api.models import (
    District,
    GenerationReading,
    GridSubstation,
    Province,
    SolarInstallation,
    User,
)
from slsea_api.security import hash_secret

# All nine provinces and all 25 districts are included. The short codes make
# generated meter and substation identifiers readable in Swagger responses.
SRI_LANKA_GEOGRAPHY = [
    ("WP", "Western", [("COL", "Colombo"), ("GAM", "Gampaha"), ("KAL", "Kalutara")]),
    ("CP", "Central", [("KAN", "Kandy"), ("MAT", "Matale"), ("NUE", "Nuwara Eliya")]),
    ("SP", "Southern", [("GAL", "Galle"), ("MTR", "Matara"), ("HAM", "Hambantota")]),
    (
        "NP",
        "Northern",
        [
            ("JAF", "Jaffna"),
            ("KIL", "Kilinochchi"),
            ("MAN", "Mannar"),
            ("MUL", "Mullaitivu"),
            ("VAV", "Vavuniya"),
        ],
    ),
    ("EP", "Eastern", [("AMP", "Ampara"), ("BAT", "Batticaloa"), ("TRI", "Trincomalee")]),
    ("NWP", "North Western", [("KUR", "Kurunegala"), ("PUT", "Puttalam")]),
    ("NCP", "North Central", [("ANU", "Anuradhapura"), ("POL", "Polonnaruwa")]),
    ("UP", "Uva", [("BAD", "Badulla"), ("MON", "Monaragala")]),
    ("SGP", "Sabaragamuwa", [("RAT", "Ratnapura"), ("KEG", "Kegalle")]),
]

DISTRICT_COORDINATES = {
    "COL": (6.9271, 79.8612),
    "GAM": (7.0873, 80.0144),
    "KAL": (6.5854, 79.9607),
    "KAN": (7.2906, 80.6337),
    "MAT": (7.4675, 80.6234),
    "NUE": (6.9497, 80.7891),
    "GAL": (6.0329, 80.2168),
    "MTR": (5.9549, 80.5550),
    "HAM": (6.1241, 81.1185),
    "JAF": (9.6615, 80.0255),
    "KIL": (9.3803, 80.3770),
    "MAN": (8.9810, 79.9044),
    "MUL": (9.2671, 80.8142),
    "VAV": (8.7514, 80.4971),
    "AMP": (7.2912, 81.6724),
    "BAT": (7.7170, 81.7000),
    "TRI": (8.5874, 81.2152),
    "KUR": (7.4863, 80.3623),
    "PUT": (8.0408, 79.8394),
    "ANU": (8.3114, 80.4037),
    "POL": (7.9403, 81.0188),
    "BAD": (6.9934, 81.0550),
    "MON": (6.8728, 81.3507),
    "RAT": (6.6828, 80.3992),
    "KEG": (7.2513, 80.3464),
}


def rounded_now(interval_minutes: int) -> datetime:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    return now.replace(minute=(now.minute // interval_minutes) * interval_minutes)


def reset_seed_tables(db: Session) -> None:
    """Delete seed data in foreign-key order; only called for explicit --reset."""

    for model in (GenerationReading, User, SolarInstallation, GridSubstation, District, Province):
        db.execute(delete(model))
    db.commit()


def seed_catalog(db: Session) -> tuple[list[District], list[SolarInstallation]]:
    districts: list[District] = []
    substations: list[GridSubstation] = []
    installations: list[SolarInstallation] = []

    for province_code, province_name, province_districts in SRI_LANKA_GEOGRAPHY:
        province = Province(code=province_code, name=province_name)
        db.add(province)
        db.flush()
        for district_code, district_name in province_districts:
            district = District(
                province_id=province.id,
                code=district_code,
                name=district_name,
            )
            db.add(district)
            db.flush()
            districts.append(district)

            # One substation per district gives 25 substations, exceeding the
            # brief's minimum while ensuring every district path contains data.
            latitude, longitude = DISTRICT_COORDINATES[district_code]
            substation = GridSubstation(
                district_id=district.id,
                code=f"GS-{district_code}",
                name=f"{district_name} Grid Substation",
                latitude=Decimal(str(latitude)),
                longitude=Decimal(str(longitude)),
                capacity_mw=Decimal("12.500"),
            )
            db.add(substation)
            db.flush()
            substations.append(substation)

            for local_number in range(1, 9):
                meter_id = f"SL-{district_code}-{local_number:03d}"
                installation = SolarInstallation(
                    grid_substation_id=substation.id,
                    meter_id=meter_id,
                    name=f"{district_name} Solar Site {local_number}",
                    address=f"Site {local_number}, {district_name}, Sri Lanka",
                    installed_capacity_kw=Decimal(str(3 + (local_number % 6) * 0.75)),
                    commissioned_on=date(2024, (local_number % 12) + 1, min(local_number + 5, 28)),
                    status="active",
                    # Each meter gets a predictable demo secret so the student can
                    # authenticate any installation during the viva.
                    device_secret_hash=hash_secret(f"SolarDevice!{meter_id}"),
                )
                db.add(installation)
                installations.append(installation)

    db.flush()
    return districts, installations


def seed_users(db: Session, districts: list[District]) -> None:
    western = db.scalar(select(Province).where(Province.code == "WP"))
    colombo = next(item for item in districts if item.code == "COL")
    analyst_password = hash_secret("AnalystCoursework!2026")
    db.add_all(
        [
            User(
                email="national.analyst@slsea.demo",
                full_name="National Solar Analyst",
                role="national",
                password_hash=analyst_password,
            ),
            User(
                email="western.analyst@slsea.demo",
                full_name="Western Province Analyst",
                role="province",
                province_id=western.id,
                password_hash=hash_secret("AnalystCoursework!2026"),
            ),
            User(
                email="colombo.analyst@slsea.demo",
                full_name="Colombo District Analyst",
                role="district",
                district_id=colombo.id,
                password_hash=hash_secret("AnalystCoursework!2026"),
            ),
            User(
                email="catalog.admin@slsea.demo",
                full_name="SLSEA Catalog Administrator",
                role="admin",
                password_hash=hash_secret("AdminCoursework!2026"),
            ),
        ]
    )


def reading_rows(
    installations: list[SolarInstallation],
    *,
    days: int,
    interval_minutes: int,
) -> list[dict[str, Any]]:
    rng = random.Random(6007)
    end_at = rounded_now(interval_minutes)
    steps = days * 24 * 60 // interval_minutes
    start_at = end_at - timedelta(minutes=(steps - 1) * interval_minutes)
    interval_hours = Decimal(interval_minutes) / Decimal(60)
    colombo = ZoneInfo("Asia/Colombo")
    rows: list[dict[str, Any]] = []

    for installation_number, installation in enumerate(installations, start=1):
        cumulative = Decimal(1000 + installation_number * 25)
        capacity = float(installation.installed_capacity_kw)
        for step in range(steps):
            recorded_at = start_at + timedelta(minutes=step * interval_minutes)
            local_time = recorded_at.astimezone(colombo)
            hour = local_time.hour + local_time.minute / 60

            # A sine curve is zero at 06:00/18:00 and peaks around noon.
            if 6 <= hour <= 18:
                daylight = math.sin(math.pi * (hour - 6) / 12)
                cloud_factor = 0.78 + rng.random() * 0.22
                power = max(0.0, capacity * daylight * cloud_factor)
            else:
                power = 0.0

            power_value = Decimal(str(round(power, 3)))
            cumulative += power_value * interval_hours
            voltage = Decimal(str(round(230 + rng.uniform(-4.5, 4.5), 3)))
            rows.append(
                {
                    "installation_id": installation.id,
                    "recorded_at": recorded_at,
                    "received_at": recorded_at + timedelta(seconds=10 + installation_number % 40),
                    "power_kw": power_value,
                    "cumulative_energy_kwh": cumulative.quantize(Decimal("0.001")),
                    "voltage_v": voltage,
                }
            )
    return rows


def seed_database(
    *, days: int = 7, interval_minutes: int = 15, reset: bool = False
) -> dict[str, int]:
    if days < 1:
        raise ValueError("days must be at least 1")
    if interval_minutes < 5 or 60 % interval_minutes:
        raise ValueError("interval_minutes must divide 60 and be at least 5")

    init_db()
    with SessionLocal() as db:
        if reset:
            reset_seed_tables(db)
        existing = db.scalar(select(func.count(Province.id))) or 0
        if existing:
            return database_counts(db)

        districts, installations = seed_catalog(db)
        seed_users(db, districts)
        db.commit()

        rows = reading_rows(
            installations,
            days=days,
            interval_minutes=interval_minutes,
        )
        # Chunking avoids one huge SQL statement while remaining much faster than
        # adding 134,400 ORM objects one at a time.
        for offset in range(0, len(rows), 5000):
            db.execute(insert(GenerationReading), rows[offset : offset + 5000])
            db.commit()
        return database_counts(db)


def database_counts(db: Session) -> dict[str, int]:
    return {
        "provinces": db.scalar(select(func.count(Province.id))) or 0,
        "districts": db.scalar(select(func.count(District.id))) or 0,
        "grid_substations": db.scalar(select(func.count(GridSubstation.id))) or 0,
        "installations": db.scalar(select(func.count(SolarInstallation.id))) or 0,
        "readings": db.scalar(select(func.count(GenerationReading.id))) or 0,
        "users": db.scalar(select(func.count(User.id))) or 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the SLSEA coursework database")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--interval-minutes", type=int, default=15)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing API data before seeding",
    )
    args = parser.parse_args()
    counts = seed_database(
        days=args.days,
        interval_minutes=args.interval_minutes,
        reset=args.reset,
    )
    print("Seed complete:", counts)
    print("National analyst: national.analyst@slsea.demo / AnalystCoursework!2026")
    print("District analyst: colombo.analyst@slsea.demo / AnalystCoursework!2026")
    print("Catalog admin: catalog.admin@slsea.demo / AdminCoursework!2026")
    print("Example device: SL-COL-001 / SolarDevice!SL-COL-001")


if __name__ == "__main__":
    main()
