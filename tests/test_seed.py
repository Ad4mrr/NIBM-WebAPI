"""Checks for the required-scale seed generator's important calculations."""

from sqlalchemy import select

from slsea_api.database import SessionLocal
from slsea_api.models import SolarInstallation
from slsea_api.seed import database_counts, reading_rows, seed_database


def test_reading_generator_has_daylight_and_monotonic_energy(sample_data):
    with SessionLocal() as db:
        installations = list(
            db.scalars(select(SolarInstallation).order_by(SolarInstallation.id))
        )
        rows = reading_rows(installations, days=1, interval_minutes=60)

    assert len(rows) == 48  # 2 installations x 24 hourly readings
    first_installation = [
        row for row in rows if row["installation_id"] == sample_data["installation_a"]
    ]
    assert any(row["power_kw"] == 0 for row in first_installation)
    assert any(row["power_kw"] > 0 for row in first_installation)
    energies = [row["cumulative_energy_kwh"] for row in first_installation]
    assert energies == sorted(energies)


def test_seed_command_is_idempotent_when_data_exists(sample_data):
    counts = seed_database()
    assert counts == {
        "provinces": 2,
        "districts": 2,
        "grid_substations": 2,
        "installations": 2,
        "readings": 3,
        "users": 3,
    }
    with SessionLocal() as db:
        assert database_counts(db) == counts
