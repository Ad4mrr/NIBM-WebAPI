"""Hierarchy and installation catalog resources.

The routes are intentionally explicit. Repetition here makes the REST method,
scope check, status code, and database action easy to trace during a viva.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from slsea_api.conditional import (
    require_matching_if_match,
    set_validator_headers,
    version_etag,
)
from slsea_api.dependencies import (
    CatalogPrincipal,
    DbSession,
    Principal,
    ReadPrincipal,
    district_scope_clause,
)
from slsea_api.errors import ApiError
from slsea_api.models import District, GridSubstation, Province, SolarInstallation
from slsea_api.schemas import (
    COMMON_ERROR_RESPONSES,
    DataEnvelope,
    DistrictCreate,
    DistrictOut,
    DistrictPatch,
    DistrictReplace,
    GridSubstationCreate,
    GridSubstationOut,
    GridSubstationPatch,
    GridSubstationReplace,
    InstallationCreate,
    InstallationOut,
    InstallationPatch,
    InstallationReplace,
    ProvinceOut,
    ProvincePatch,
    ProvinceWrite,
)
from slsea_api.security import hash_secret

from .common import (
    commit_or_conflict,
    prepare_atomic_response,
    prepare_collection_response,
)

router = APIRouter(tags=["Catalog"], responses=COMMON_ERROR_RESPONSES)


def visible_province_query(principal: Principal):
    query = select(Province)
    if principal.role == "province":
        query = query.where(Province.id == principal.province_id)
    elif principal.role == "district":
        query = query.where(
            Province.id.in_(
                select(District.province_id).where(District.id == principal.district_id)
            )
        )
    elif not principal.is_national:
        query = query.where(False)
    return query


def visible_district_query(principal: Principal):
    return select(District).where(district_scope_clause(principal))


def visible_substation_query(principal: Principal):
    return (
        select(GridSubstation)
        .join(GridSubstation.district)
        .where(district_scope_clause(principal))
    )


def visible_installation_query(principal: Principal):
    return (
        select(SolarInstallation)
        .join(SolarInstallation.grid_substation)
        .join(GridSubstation.district)
        .where(district_scope_clause(principal))
    )


def one_or_not_found(db: DbSession, query, resource_name: str):
    resource = db.scalar(query)
    if resource is None:
        # Returning 404 for an out-of-scope object avoids revealing that it exists.
        raise ApiError(404, "not_found", f"{resource_name} was not found")
    return resource


# ---------------------------------------------------------------------------
# Provinces
# ---------------------------------------------------------------------------


@router.get("/provinces", response_model=DataEnvelope[list[ProvinceOut]])
def list_provinces(
    request: Request,
    response: Response,
    db: DbSession,
    principal: ReadPrincipal,
) -> Any:
    provinces = list(db.scalars(visible_province_query(principal).order_by(Province.name)))
    output = [ProvinceOut.model_validate(item) for item in provinces]
    if cached := prepare_collection_response(
        request,
        response,
        serialized=[item.model_dump(mode="json") for item in output],
        resources=provinces,
    ):
        return cached
    return DataEnvelope(data=output)


@router.post(
    "/provinces",
    response_model=DataEnvelope[ProvinceOut],
    status_code=status.HTTP_201_CREATED,
)
def create_province(
    body: ProvinceWrite,
    response: Response,
    db: DbSession,
    _principal: CatalogPrincipal,
) -> DataEnvelope[ProvinceOut]:
    province = Province(**body.model_dump())
    db.add(province)
    commit_or_conflict(db, "Province code or name already exists")
    db.refresh(province)
    response.headers["Location"] = f"/api/v1/provinces/{province.id}"
    set_validator_headers(
        response,
        etag=version_etag("province", province.id, province.version),
        last_modified=province.updated_at,
    )
    return DataEnvelope(data=ProvinceOut.model_validate(province))


@router.get("/provinces/{province_id}", response_model=DataEnvelope[ProvinceOut])
def get_province(
    province_id: int,
    request: Request,
    response: Response,
    db: DbSession,
    principal: ReadPrincipal,
) -> Any:
    province = one_or_not_found(
        db,
        visible_province_query(principal).where(Province.id == province_id),
        "Province",
    )
    if cached := prepare_atomic_response(
        request, response, resource_name="province", resource=province
    ):
        return cached
    return DataEnvelope(data=ProvinceOut.model_validate(province))


@router.put("/provinces/{province_id}", response_model=DataEnvelope[ProvinceOut])
def replace_province(
    province_id: int,
    body: ProvinceWrite,
    request: Request,
    response: Response,
    db: DbSession,
    _principal: CatalogPrincipal,
) -> DataEnvelope[ProvinceOut]:
    province = one_or_not_found(db, select(Province).where(Province.id == province_id), "Province")
    require_matching_if_match(request, version_etag("province", province.id, province.version))
    province.code, province.name = body.code, body.name
    commit_or_conflict(db, "Province code or name already exists")
    db.refresh(province)
    prepare_atomic_response(request, response, resource_name="province", resource=province)
    return DataEnvelope(data=ProvinceOut.model_validate(province))


@router.patch("/provinces/{province_id}", response_model=DataEnvelope[ProvinceOut])
def update_province(
    province_id: int,
    body: ProvincePatch,
    request: Request,
    response: Response,
    db: DbSession,
    _principal: CatalogPrincipal,
) -> DataEnvelope[ProvinceOut]:
    province = one_or_not_found(db, select(Province).where(Province.id == province_id), "Province")
    require_matching_if_match(request, version_etag("province", province.id, province.version))
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(province, field, value)
    commit_or_conflict(db, "Province code or name already exists")
    db.refresh(province)
    prepare_atomic_response(request, response, resource_name="province", resource=province)
    return DataEnvelope(data=ProvinceOut.model_validate(province))


@router.delete("/provinces/{province_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_province(
    province_id: int,
    request: Request,
    db: DbSession,
    _principal: CatalogPrincipal,
) -> Response:
    province = one_or_not_found(db, select(Province).where(Province.id == province_id), "Province")
    require_matching_if_match(request, version_etag("province", province.id, province.version))
    db.delete(province)
    commit_or_conflict(db, "Province still contains districts and cannot be deleted")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Districts
# ---------------------------------------------------------------------------


@router.get(
    "/provinces/{province_id}/districts",
    response_model=DataEnvelope[list[DistrictOut]],
)
def list_districts(
    province_id: int,
    request: Request,
    response: Response,
    db: DbSession,
    principal: ReadPrincipal,
) -> Any:
    districts = list(
        db.scalars(
            visible_district_query(principal)
            .where(District.province_id == province_id)
            .order_by(District.name)
        )
    )
    if not districts:
        one_or_not_found(
            db,
            visible_province_query(principal).where(Province.id == province_id),
            "Province",
        )
    output = [DistrictOut.model_validate(item) for item in districts]
    if cached := prepare_collection_response(
        request,
        response,
        serialized=[item.model_dump(mode="json") for item in output],
        resources=districts,
    ):
        return cached
    return DataEnvelope(data=output)


@router.post(
    "/provinces/{province_id}/districts",
    response_model=DataEnvelope[DistrictOut],
    status_code=status.HTTP_201_CREATED,
)
def create_district(
    province_id: int,
    body: DistrictCreate,
    response: Response,
    db: DbSession,
    _principal: CatalogPrincipal,
) -> DataEnvelope[DistrictOut]:
    one_or_not_found(db, select(Province).where(Province.id == province_id), "Province")
    district = District(province_id=province_id, **body.model_dump())
    db.add(district)
    commit_or_conflict(db, "District code or name already exists")
    db.refresh(district)
    response.headers["Location"] = f"/api/v1/districts/{district.id}"
    set_validator_headers(
        response,
        etag=version_etag("district", district.id, district.version),
        last_modified=district.updated_at,
    )
    return DataEnvelope(data=DistrictOut.model_validate(district))


@router.get("/districts/{district_id}", response_model=DataEnvelope[DistrictOut])
def get_district(
    district_id: int,
    request: Request,
    response: Response,
    db: DbSession,
    principal: ReadPrincipal,
) -> Any:
    district = one_or_not_found(
        db,
        visible_district_query(principal).where(District.id == district_id),
        "District",
    )
    if cached := prepare_atomic_response(
        request, response, resource_name="district", resource=district
    ):
        return cached
    return DataEnvelope(data=DistrictOut.model_validate(district))


@router.put("/districts/{district_id}", response_model=DataEnvelope[DistrictOut])
def replace_district(
    district_id: int,
    body: DistrictReplace,
    request: Request,
    response: Response,
    db: DbSession,
    _principal: CatalogPrincipal,
) -> DataEnvelope[DistrictOut]:
    district = one_or_not_found(db, select(District).where(District.id == district_id), "District")
    require_matching_if_match(request, version_etag("district", district.id, district.version))
    one_or_not_found(db, select(Province).where(Province.id == body.province_id), "Province")
    for field, value in body.model_dump().items():
        setattr(district, field, value)
    commit_or_conflict(db, "District code or name already exists")
    db.refresh(district)
    prepare_atomic_response(request, response, resource_name="district", resource=district)
    return DataEnvelope(data=DistrictOut.model_validate(district))


@router.patch("/districts/{district_id}", response_model=DataEnvelope[DistrictOut])
def update_district(
    district_id: int,
    body: DistrictPatch,
    request: Request,
    response: Response,
    db: DbSession,
    _principal: CatalogPrincipal,
) -> DataEnvelope[DistrictOut]:
    district = one_or_not_found(db, select(District).where(District.id == district_id), "District")
    require_matching_if_match(request, version_etag("district", district.id, district.version))
    changes = body.model_dump(exclude_unset=True)
    if "province_id" in changes:
        one_or_not_found(
            db,
            select(Province).where(Province.id == changes["province_id"]),
            "Province",
        )
    for field, value in changes.items():
        setattr(district, field, value)
    commit_or_conflict(db, "District code or name already exists")
    db.refresh(district)
    prepare_atomic_response(request, response, resource_name="district", resource=district)
    return DataEnvelope(data=DistrictOut.model_validate(district))


@router.delete("/districts/{district_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_district(
    district_id: int,
    request: Request,
    db: DbSession,
    _principal: CatalogPrincipal,
) -> Response:
    district = one_or_not_found(db, select(District).where(District.id == district_id), "District")
    require_matching_if_match(request, version_etag("district", district.id, district.version))
    db.delete(district)
    commit_or_conflict(db, "District still contains grid substations and cannot be deleted")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Grid substations
# ---------------------------------------------------------------------------


@router.get(
    "/districts/{district_id}/grid-substations",
    response_model=DataEnvelope[list[GridSubstationOut]],
)
def list_grid_substations(
    district_id: int,
    request: Request,
    response: Response,
    db: DbSession,
    principal: ReadPrincipal,
) -> Any:
    substations = list(
        db.scalars(
            visible_substation_query(principal)
            .where(GridSubstation.district_id == district_id)
            .order_by(GridSubstation.name)
        )
    )
    if not substations:
        one_or_not_found(
            db,
            visible_district_query(principal).where(District.id == district_id),
            "District",
        )
    output = [GridSubstationOut.model_validate(item) for item in substations]
    if cached := prepare_collection_response(
        request,
        response,
        serialized=[item.model_dump(mode="json") for item in output],
        resources=substations,
    ):
        return cached
    return DataEnvelope(data=output)


@router.post(
    "/districts/{district_id}/grid-substations",
    response_model=DataEnvelope[GridSubstationOut],
    status_code=status.HTTP_201_CREATED,
)
def create_grid_substation(
    district_id: int,
    body: GridSubstationCreate,
    response: Response,
    db: DbSession,
    _principal: CatalogPrincipal,
) -> DataEnvelope[GridSubstationOut]:
    one_or_not_found(db, select(District).where(District.id == district_id), "District")
    substation = GridSubstation(district_id=district_id, **body.model_dump())
    db.add(substation)
    commit_or_conflict(db, "Grid substation code or name already exists")
    db.refresh(substation)
    response.headers["Location"] = f"/api/v1/grid-substations/{substation.id}"
    set_validator_headers(
        response,
        etag=version_etag("grid-substation", substation.id, substation.version),
        last_modified=substation.updated_at,
    )
    return DataEnvelope(data=GridSubstationOut.model_validate(substation))


@router.get(
    "/grid-substations/{substation_id}",
    response_model=DataEnvelope[GridSubstationOut],
)
def get_grid_substation(
    substation_id: int,
    request: Request,
    response: Response,
    db: DbSession,
    principal: ReadPrincipal,
) -> Any:
    substation = one_or_not_found(
        db,
        visible_substation_query(principal).where(GridSubstation.id == substation_id),
        "Grid substation",
    )
    if cached := prepare_atomic_response(
        request, response, resource_name="grid-substation", resource=substation
    ):
        return cached
    return DataEnvelope(data=GridSubstationOut.model_validate(substation))


@router.put(
    "/grid-substations/{substation_id}",
    response_model=DataEnvelope[GridSubstationOut],
)
def replace_grid_substation(
    substation_id: int,
    body: GridSubstationReplace,
    request: Request,
    response: Response,
    db: DbSession,
    _principal: CatalogPrincipal,
) -> DataEnvelope[GridSubstationOut]:
    substation = one_or_not_found(
        db, select(GridSubstation).where(GridSubstation.id == substation_id), "Grid substation"
    )
    require_matching_if_match(
        request, version_etag("grid-substation", substation.id, substation.version)
    )
    one_or_not_found(db, select(District).where(District.id == body.district_id), "District")
    for field, value in body.model_dump().items():
        setattr(substation, field, value)
    commit_or_conflict(db, "Grid substation code or name already exists")
    db.refresh(substation)
    prepare_atomic_response(
        request, response, resource_name="grid-substation", resource=substation
    )
    return DataEnvelope(data=GridSubstationOut.model_validate(substation))


@router.patch(
    "/grid-substations/{substation_id}",
    response_model=DataEnvelope[GridSubstationOut],
)
def update_grid_substation(
    substation_id: int,
    body: GridSubstationPatch,
    request: Request,
    response: Response,
    db: DbSession,
    _principal: CatalogPrincipal,
) -> DataEnvelope[GridSubstationOut]:
    substation = one_or_not_found(
        db, select(GridSubstation).where(GridSubstation.id == substation_id), "Grid substation"
    )
    require_matching_if_match(
        request, version_etag("grid-substation", substation.id, substation.version)
    )
    changes = body.model_dump(exclude_unset=True)
    if "district_id" in changes:
        one_or_not_found(
            db,
            select(District).where(District.id == changes["district_id"]),
            "District",
        )
    for field, value in changes.items():
        setattr(substation, field, value)
    commit_or_conflict(db, "Grid substation code or name already exists")
    db.refresh(substation)
    prepare_atomic_response(
        request, response, resource_name="grid-substation", resource=substation
    )
    return DataEnvelope(data=GridSubstationOut.model_validate(substation))


@router.delete(
    "/grid-substations/{substation_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_grid_substation(
    substation_id: int,
    request: Request,
    db: DbSession,
    _principal: CatalogPrincipal,
) -> Response:
    substation = one_or_not_found(
        db, select(GridSubstation).where(GridSubstation.id == substation_id), "Grid substation"
    )
    require_matching_if_match(
        request, version_etag("grid-substation", substation.id, substation.version)
    )
    db.delete(substation)
    commit_or_conflict(db, "Grid substation still contains installations and cannot be deleted")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Solar installations
# ---------------------------------------------------------------------------


@router.get(
    "/grid-substations/{substation_id}/installations",
    response_model=DataEnvelope[list[InstallationOut]],
)
def list_installations(
    substation_id: int,
    request: Request,
    response: Response,
    db: DbSession,
    principal: ReadPrincipal,
) -> Any:
    installations = list(
        db.scalars(
            visible_installation_query(principal)
            .where(SolarInstallation.grid_substation_id == substation_id)
            .order_by(SolarInstallation.meter_id)
        )
    )
    if not installations:
        one_or_not_found(
            db,
            visible_substation_query(principal).where(GridSubstation.id == substation_id),
            "Grid substation",
        )
    output = [InstallationOut.model_validate(item) for item in installations]
    if cached := prepare_collection_response(
        request,
        response,
        serialized=[item.model_dump(mode="json") for item in output],
        resources=installations,
    ):
        return cached
    return DataEnvelope(data=output)


@router.post(
    "/grid-substations/{substation_id}/installations",
    response_model=DataEnvelope[InstallationOut],
    status_code=status.HTTP_201_CREATED,
)
def create_installation(
    substation_id: int,
    body: InstallationCreate,
    response: Response,
    db: DbSession,
    _principal: CatalogPrincipal,
) -> DataEnvelope[InstallationOut]:
    one_or_not_found(
        db, select(GridSubstation).where(GridSubstation.id == substation_id), "Grid substation"
    )
    values = body.model_dump(exclude={"device_secret"})
    installation = SolarInstallation(
        grid_substation_id=substation_id,
        device_secret_hash=hash_secret(body.device_secret),
        **values,
    )
    db.add(installation)
    commit_or_conflict(db, "Installation meter ID already exists")
    db.refresh(installation)
    response.headers["Location"] = f"/api/v1/installations/{installation.id}"
    set_validator_headers(
        response,
        etag=version_etag("installation", installation.id, installation.version),
        last_modified=installation.updated_at,
    )
    return DataEnvelope(data=InstallationOut.model_validate(installation))


@router.get("/installations/{installation_id}", response_model=DataEnvelope[InstallationOut])
def get_installation(
    installation_id: int,
    request: Request,
    response: Response,
    db: DbSession,
    principal: ReadPrincipal,
) -> Any:
    installation = one_or_not_found(
        db,
        visible_installation_query(principal).where(SolarInstallation.id == installation_id),
        "Installation",
    )
    if cached := prepare_atomic_response(
        request, response, resource_name="installation", resource=installation
    ):
        return cached
    return DataEnvelope(data=InstallationOut.model_validate(installation))


@router.put("/installations/{installation_id}", response_model=DataEnvelope[InstallationOut])
def replace_installation(
    installation_id: int,
    body: InstallationReplace,
    request: Request,
    response: Response,
    db: DbSession,
    _principal: CatalogPrincipal,
) -> DataEnvelope[InstallationOut]:
    installation = one_or_not_found(
        db, select(SolarInstallation).where(SolarInstallation.id == installation_id), "Installation"
    )
    require_matching_if_match(
        request, version_etag("installation", installation.id, installation.version)
    )
    one_or_not_found(
        db,
        select(GridSubstation).where(GridSubstation.id == body.grid_substation_id),
        "Grid substation",
    )
    for field, value in body.model_dump(exclude={"device_secret"}).items():
        setattr(installation, field, value)
    installation.device_secret_hash = hash_secret(body.device_secret)
    commit_or_conflict(db, "Installation meter ID already exists")
    db.refresh(installation)
    prepare_atomic_response(
        request, response, resource_name="installation", resource=installation
    )
    return DataEnvelope(data=InstallationOut.model_validate(installation))


@router.patch("/installations/{installation_id}", response_model=DataEnvelope[InstallationOut])
def update_installation(
    installation_id: int,
    body: InstallationPatch,
    request: Request,
    response: Response,
    db: DbSession,
    _principal: CatalogPrincipal,
) -> DataEnvelope[InstallationOut]:
    installation = one_or_not_found(
        db, select(SolarInstallation).where(SolarInstallation.id == installation_id), "Installation"
    )
    require_matching_if_match(
        request, version_etag("installation", installation.id, installation.version)
    )
    changes = body.model_dump(exclude_unset=True)
    if "grid_substation_id" in changes:
        one_or_not_found(
            db,
            select(GridSubstation).where(GridSubstation.id == changes["grid_substation_id"]),
            "Grid substation",
        )
    if device_secret := changes.pop("device_secret", None):
        installation.device_secret_hash = hash_secret(device_secret)
    for field, value in changes.items():
        setattr(installation, field, value)
    commit_or_conflict(db, "Installation meter ID already exists")
    db.refresh(installation)
    prepare_atomic_response(
        request, response, resource_name="installation", resource=installation
    )
    return DataEnvelope(data=InstallationOut.model_validate(installation))


@router.delete("/installations/{installation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_installation(
    installation_id: int,
    request: Request,
    db: DbSession,
    _principal: CatalogPrincipal,
) -> Response:
    installation = one_or_not_found(
        db, select(SolarInstallation).where(SolarInstallation.id == installation_id), "Installation"
    )
    require_matching_if_match(
        request, version_etag("installation", installation.id, installation.version)
    )
    db.delete(installation)
    commit_or_conflict(db, "Installation has readings and cannot be deleted")
    return Response(status_code=204)
