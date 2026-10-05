"""High-value integration tests that map directly to the marking rubric."""

from __future__ import annotations

from datetime import datetime, timedelta


def test_health_and_openapi_are_public(client):
    assert client.get("/api/v1/health/live").status_code == 200
    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    assert "OAuth2PasswordBearer" in openapi.json()["components"]["securitySchemes"]


def test_invalid_login_uses_error_contract(client):
    response = client.post(
        "/api/v1/auth/token",
        data={"username": "nobody", "password": "wrong"},
    )
    assert response.status_code == 401
    assert set(response.json()) == {"code", "message", "details", "request_id"}


def test_district_user_cannot_see_another_district(
    client, sample_data, district_headers
):
    own = client.get(
        f"/api/v1/districts/{sample_data['district_a']}", headers=district_headers
    )
    other = client.get(
        f"/api/v1/districts/{sample_data['district_b']}", headers=district_headers
    )
    assert own.status_code == 200
    assert other.status_code == 404  # Conceals the out-of-scope resource.


def test_collection_conditional_get_has_empty_304(client, national_headers):
    first = client.get("/api/v1/provinces", headers=national_headers)
    assert first.status_code == 200
    assert first.headers["etag"]
    cached = client.get(
        "/api/v1/provinces",
        headers={**national_headers, "If-None-Match": first.headers["etag"]},
    )
    assert cached.status_code == 304
    assert cached.content == b""


def test_catalog_create_location_patch_and_stale_precondition(client, admin_headers):
    created = client.post(
        "/api/v1/provinces",
        headers=admin_headers,
        json={"code": "TMP", "name": "Temporary Province"},
    )
    assert created.status_code == 201
    assert created.headers["location"].endswith("/provinces/3")
    original_etag = created.headers["etag"]

    updated = client.patch(
        created.headers["location"],
        headers={**admin_headers, "If-Match": original_etag},
        json={"name": "Updated Province"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "Updated Province"
    assert updated.headers["etag"] != original_etag

    stale = client.patch(
        created.headers["location"],
        headers={**admin_headers, "If-Match": original_etag},
        json={"name": "Stale Write"},
    )
    assert stale.status_code == 412
    assert stale.json()["code"] == "precondition_failed"


def test_device_can_only_write_for_its_own_installation(
    client, sample_data, device_headers
):
    body = {
        "recorded_at": (sample_data["now"] + timedelta(minutes=1)).isoformat(),
        "power_kw": 2.4,
        "cumulative_energy_kwh": 101.2,
        "voltage_v": 230.1,
    }
    own = client.post(
        f"/api/v1/installations/{sample_data['installation_a']}/readings",
        headers=device_headers,
        json=body,
    )
    assert own.status_code == 201
    assert own.headers["location"].endswith(f"/readings/{own.json()['data']['id']}")

    other = client.post(
        f"/api/v1/installations/{sample_data['installation_b']}/readings",
        headers=device_headers,
        json=body,
    )
    assert other.status_code == 403
    assert other.json()["code"] == "installation_scope_violation"


def test_duplicate_reading_returns_conflict(client, sample_data, device_headers):
    body = {
        "recorded_at": (sample_data["now"] - timedelta(minutes=15)).isoformat(),
        "power_kw": 2,
        "cumulative_energy_kwh": 100,
        "voltage_v": 230,
    }
    response = client.post(
        f"/api/v1/installations/{sample_data['installation_a']}/readings",
        headers=device_headers,
        json=body,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "data_conflict"


def test_history_is_paginated_filtered_and_sorted(
    client, sample_data, national_headers
):
    response = client.get(
        "/api/v1/readings",
        params={
            "installation_id": sample_data["installation_a"],
            "page": 1,
            "page_size": 1,
            "sort": "recorded_at",
        },
        headers=national_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["page"]["total_items"] == 2
    assert body["links"]["next"] is not None
    assert len(body["items"]) == 1


def test_last_known_overview_and_district_summary(
    client, sample_data, national_headers
):
    installation_id = sample_data["installation_a"]
    last = client.get(
        f"/api/v1/installations/{installation_id}/last-known-reading",
        headers=national_headers,
    )
    overview = client.get(
        f"/api/v1/installations/{installation_id}/overview",
        headers=national_headers,
    )
    summary = client.get(
        f"/api/v1/districts/{sample_data['district_a']}/generation-summary",
        params={"as_of": sample_data["now"].isoformat()},
        headers=national_headers,
    )
    assert last.status_code == 200
    assert overview.status_code == 200
    assert overview.json()["data"]["hierarchy"]["district"]["name"] == "Colombo"
    assert summary.status_code == 200
    assert summary.json()["data"]["reporting_installations"] == 1


def test_readings_are_append_only(client, sample_data, national_headers):
    response = client.delete(
        f"/api/v1/installations/{sample_data['installation_a']}/readings/1",
        headers=national_headers,
    )
    assert response.status_code == 405
    assert response.headers["allow"] == "GET"
    assert response.json()["code"] == "reading_is_immutable"


def test_content_negotiation_and_validation_errors(client, national_headers):
    unacceptable = client.get(
        "/api/v1/provinces",
        headers={**national_headers, "Accept": "text/html"},
    )
    invalid_page = client.get(
        "/api/v1/readings?page_size=999",
        headers=national_headers,
    )
    assert unacceptable.status_code == 406
    assert unacceptable.json()["code"] == "not_acceptable"
    assert invalid_page.status_code == 400
    assert invalid_page.json()["code"] == "validation_error"


def test_naive_timestamp_is_rejected(client, sample_data, device_headers):
    response = client.post(
        f"/api/v1/installations/{sample_data['installation_a']}/readings",
        headers=device_headers,
        json={
            "recorded_at": datetime.now().replace(microsecond=0).isoformat(),
            "power_kw": 1,
            "cumulative_energy_kwh": 1,
            "voltage_v": 230,
        },
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"
