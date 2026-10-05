"""CRUD tests for the mutable catalog resources."""


def test_full_catalog_crud_sequence(client, admin_headers):
    province = client.post(
        "/api/v1/provinces",
        headers=admin_headers,
        json={"code": "TST", "name": "Test Province"},
    )
    assert province.status_code == 201
    province_id = province.json()["data"]["id"]

    district = client.post(
        f"/api/v1/provinces/{province_id}/districts",
        headers=admin_headers,
        json={"code": "TSD", "name": "Test District"},
    )
    assert district.status_code == 201
    district_id = district.json()["data"]["id"]

    substation = client.post(
        f"/api/v1/districts/{district_id}/grid-substations",
        headers=admin_headers,
        json={"code": "GS-TST", "name": "Test Grid", "capacity_mw": 5},
    )
    assert substation.status_code == 201
    substation_id = substation.json()["data"]["id"]

    installation = client.post(
        f"/api/v1/grid-substations/{substation_id}/installations",
        headers=admin_headers,
        json={
            "meter_id": "SL-TST-001",
            "name": "Test Solar Site",
            "address": "Test address",
            "installed_capacity_kw": 4.5,
            "commissioned_on": "2026-01-01",
            "status": "active",
            "device_secret": "test-device-secret",
        },
    )
    assert installation.status_code == 201
    installation_id = installation.json()["data"]["id"]

    assert client.get(
        f"/api/v1/provinces/{province_id}/districts", headers=admin_headers
    ).json()["data"][0]["id"] == district_id
    assert client.get(
        f"/api/v1/districts/{district_id}/grid-substations", headers=admin_headers
    ).json()["data"][0]["id"] == substation_id
    assert client.get(
        f"/api/v1/grid-substations/{substation_id}/installations",
        headers=admin_headers,
    ).json()["data"][0]["id"] == installation_id

    replaced_province = client.put(
        f"/api/v1/provinces/{province_id}",
        headers=admin_headers,
        json={"code": "TS2", "name": "Replaced Province"},
    )
    assert replaced_province.json()["data"]["name"] == "Replaced Province"

    patched_district = client.patch(
        f"/api/v1/districts/{district_id}",
        headers=admin_headers,
        json={"name": "Patched District"},
    )
    assert patched_district.json()["data"]["name"] == "Patched District"

    replaced_substation = client.put(
        f"/api/v1/grid-substations/{substation_id}",
        headers=admin_headers,
        json={
            "district_id": district_id,
            "code": "GS-TS2",
            "name": "Replaced Grid",
            "capacity_mw": 6,
        },
    )
    assert replaced_substation.json()["data"]["name"] == "Replaced Grid"

    patched_installation = client.patch(
        f"/api/v1/installations/{installation_id}",
        headers=admin_headers,
        json={"status": "maintenance"},
    )
    assert patched_installation.json()["data"]["status"] == "maintenance"

    # The leaf-to-root delete order succeeds because these temporary resources
    # have no readings or children by the time each DELETE is sent.
    assert client.delete(
        f"/api/v1/installations/{installation_id}", headers=admin_headers
    ).status_code == 204
    assert client.delete(
        f"/api/v1/grid-substations/{substation_id}", headers=admin_headers
    ).status_code == 204
    assert client.delete(
        f"/api/v1/districts/{district_id}", headers=admin_headers
    ).status_code == 204
    assert client.delete(
        f"/api/v1/provinces/{province_id}", headers=admin_headers
    ).status_code == 204


def test_parent_with_children_returns_conflict(
    client, sample_data, admin_headers
):
    response = client.delete(
        f"/api/v1/provinces/{sample_data['province_a']}", headers=admin_headers
    )
    assert response.status_code == 409
    assert response.json()["code"] == "data_conflict"


def test_district_user_only_lists_own_province(client, district_headers):
    response = client.get("/api/v1/provinces", headers=district_headers)
    assert response.status_code == 200
    assert [item["code"] for item in response.json()["data"]] == ["WP"]


def test_if_modified_since_and_unsupported_media_type(
    client, national_headers, admin_headers
):
    first = client.get("/api/v1/provinces/1", headers=national_headers)
    cached = client.get(
        "/api/v1/provinces/1",
        headers={
            **national_headers,
            "If-Modified-Since": first.headers["last-modified"],
        },
    )
    assert cached.status_code == 304
    assert cached.content == b""

    wrong_media_type = client.post(
        "/api/v1/provinces",
        headers={**admin_headers, "Content-Type": "text/plain"},
        content="not json",
    )
    assert wrong_media_type.status_code == 415
    assert wrong_media_type.json()["code"] == "unsupported_media_type"
