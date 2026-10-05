"""Small deterministic database used by API integration tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

# Settings must be present before importing the application modules.
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["PBKDF2_ITERATIONS"] = "100000"

from slsea_api.database import SessionLocal, engine  # noqa: E402
from slsea_api.main import app  # noqa: E402
from slsea_api.models import (  # noqa: E402
    Base,
    District,
    GenerationReading,
    GridSubstation,
    Province,
    SolarInstallation,
    User,
)
from slsea_api.security import hash_secret  # noqa: E402


@pytest.fixture()
def sample_data():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        province_a = Province(code="WP", name="Western")
        province_b = Province(code="SP", name="Southern")
        db.add_all([province_a, province_b])
        db.flush()
        district_a = District(province_id=province_a.id, code="COL", name="Colombo")
        district_b = District(province_id=province_b.id, code="GAL", name="Galle")
        db.add_all([district_a, district_b])
        db.flush()
        station_a = GridSubstation(
            district_id=district_a.id,
            code="GS-COL",
            name="Colombo Grid",
            capacity_mw=Decimal("10"),
        )
        station_b = GridSubstation(
            district_id=district_b.id,
            code="GS-GAL",
            name="Galle Grid",
            capacity_mw=Decimal("10"),
        )
        db.add_all([station_a, station_b])
        db.flush()
        installation_a = SolarInstallation(
            grid_substation_id=station_a.id,
            meter_id="SL-COL-001",
            name="Colombo Home",
            installed_capacity_kw=Decimal("5"),
            status="active",
            device_secret_hash=hash_secret("SolarDevice!SL-COL-001"),
        )
        installation_b = SolarInstallation(
            grid_substation_id=station_b.id,
            meter_id="SL-GAL-001",
            name="Galle Home",
            installed_capacity_kw=Decimal("5"),
            status="active",
            device_secret_hash=hash_secret("SolarDevice!SL-GAL-001"),
        )
        db.add_all([installation_a, installation_b])
        db.flush()
        now = datetime.now(UTC).replace(microsecond=0)
        db.add_all(
            [
                GenerationReading(
                    installation_id=installation_a.id,
                    recorded_at=now - timedelta(minutes=30),
                    received_at=now - timedelta(minutes=29),
                    power_kw=Decimal("2.0"),
                    cumulative_energy_kwh=Decimal("100.0"),
                    voltage_v=Decimal("230"),
                ),
                GenerationReading(
                    installation_id=installation_a.id,
                    recorded_at=now - timedelta(minutes=15),
                    received_at=now - timedelta(minutes=14),
                    power_kw=Decimal("3.0"),
                    cumulative_energy_kwh=Decimal("100.75"),
                    voltage_v=Decimal("231"),
                ),
                GenerationReading(
                    installation_id=installation_b.id,
                    recorded_at=now - timedelta(minutes=15),
                    received_at=now - timedelta(minutes=14),
                    power_kw=Decimal("4.0"),
                    cumulative_energy_kwh=Decimal("200.0"),
                    voltage_v=Decimal("229"),
                ),
            ]
        )
        db.add_all(
            [
                User(
                    email="national@test.local",
                    full_name="National Analyst",
                    role="national",
                    password_hash=hash_secret("national-password"),
                ),
                User(
                    email="colombo@test.local",
                    full_name="Colombo Analyst",
                    role="district",
                    district_id=district_a.id,
                    password_hash=hash_secret("district-password"),
                ),
                User(
                    email="admin@test.local",
                    full_name="Catalog Admin",
                    role="admin",
                    password_hash=hash_secret("admin-password"),
                ),
            ]
        )
        db.commit()
        ids = {
            "province_a": province_a.id,
            "province_b": province_b.id,
            "district_a": district_a.id,
            "district_b": district_b.id,
            "station_a": station_a.id,
            "station_b": station_b.id,
            "installation_a": installation_a.id,
            "installation_b": installation_b.id,
            "now": now,
        }
    yield ids
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client(sample_data):
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, username: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture()
def national_headers(client):
    token = login(client, "national@test.local", "national-password")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def district_headers(client):
    token = login(client, "colombo@test.local", "district-password")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_headers(client):
    token = login(client, "admin@test.local", "admin-password")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def device_headers(client):
    token = login(client, "SL-COL-001", "SolarDevice!SL-COL-001")
    return {"Authorization": f"Bearer {token}"}
