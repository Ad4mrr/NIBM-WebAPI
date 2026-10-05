"""Operational and analytical generation-reading resources."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request, Response, status
from sqlalchemy import asc, desc, func, select

from slsea_api.conditional import (
    check_not_modified,
    content_etag,
    set_validator_headers,
)
from slsea_api.dependencies import (
    DbSession,
    InstallationPrincipal,
    ReadPrincipal,
    district_scope_clause,
    require_own_installation,
)
from slsea_api.errors import ApiError
from slsea_api.models import (
    District,
    GenerationReading,
    GridSubstation,
    SolarInstallation,
    utc_now,
)
from slsea_api.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, page_metadata
from slsea_api.schemas import (
    COMMON_ERROR_RESPONSES,
    DataEnvelope,
    DistrictGenerationSummaryOut,
    DistrictOut,
    GenerationReadingCreate,
    GenerationReadingOut,
    GridSubstationOut,
    HierarchyOut,
    InstallationOut,
    InstallationOverviewOut,
    PaginatedResponse,
    ProvinceOut,
    RecentSummaryOut,
)

from .catalog import one_or_not_found, visible_district_query, visible_installation_query
from .common import commit_or_conflict, prepare_collection_response

router = APIRouter(tags=["Generation readings"], responses=COMMON_ERROR_RESPONSES)


def normalize_utc(value: datetime) -> datetime:
    """SQLite can return a naive value even for a timezone-aware column."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def validate_time_window(recorded_from: datetime | None, recorded_to: datetime | None) -> None:
    for field, value in (("recorded_from", recorded_from), ("recorded_to", recorded_to)):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ApiError(
                400,
                "invalid_time_filter",
                "Time filters must include a timezone offset",
                [{"field": field, "issue": "Add Z or an explicit UTC offset"}],
            )
    if recorded_from and recorded_to and recorded_from >= recorded_to:
        raise ApiError(
            400,
            "invalid_time_window",
            "recorded_from must be earlier than recorded_to",
        )


def apply_reading_filters(
    query,
    *,
    recorded_from: datetime | None,
    recorded_to: datetime | None,
    province_id: int | None = None,
    district_id: int | None = None,
    grid_substation_id: int | None = None,
    installation_id: int | None = None,
):
    if recorded_from:
        query = query.where(GenerationReading.recorded_at >= recorded_from)
    if recorded_to:
        query = query.where(GenerationReading.recorded_at < recorded_to)
    if province_id:
        query = query.where(District.province_id == province_id)
    if district_id:
        query = query.where(District.id == district_id)
    if grid_substation_id:
        query = query.where(GridSubstation.id == grid_substation_id)
    if installation_id:
        query = query.where(SolarInstallation.id == installation_id)
    return query


def paginated_readings(
    *,
    query,
    request: Request,
    response: Response,
    db: DbSession,
    page: int,
    page_size: int,
    sort: Literal["recorded_at", "-recorded_at"],
) -> Any:
    total_items = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    ordering = (
        (asc(GenerationReading.recorded_at), asc(GenerationReading.id))
        if sort == "recorded_at"
        else (desc(GenerationReading.recorded_at), desc(GenerationReading.id))
    )
    readings = list(
        db.scalars(
            query.order_by(*ordering).offset((page - 1) * page_size).limit(page_size)
        )
    )
    output = [GenerationReadingOut.model_validate(item) for item in readings]
    page_info, links = page_metadata(
        request,
        page=page,
        page_size=page_size,
        total_items=total_items,
    )
    result = PaginatedResponse[GenerationReadingOut](
        items=output,
        page=page_info,
        links=links,
    )
    if cached := prepare_collection_response(
        request,
        response,
        serialized=result.model_dump(mode="json"),
        resources=readings,
    ):
        return cached
    return result


@router.get(
    "/installations/{installation_id}/readings",
    response_model=PaginatedResponse[GenerationReadingOut],
)
def list_installation_readings(
    installation_id: int,
    request: Request,
    response: Response,
    db: DbSession,
    principal: ReadPrincipal,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    recorded_from: datetime | None = None,
    recorded_to: datetime | None = None,
    sort: Literal["recorded_at", "-recorded_at"] = "-recorded_at",
) -> Any:
    validate_time_window(recorded_from, recorded_to)
    one_or_not_found(
        db,
        visible_installation_query(principal).where(SolarInstallation.id == installation_id),
        "Installation",
    )
    query = (
        select(GenerationReading)
        .join(GenerationReading.installation)
        .join(SolarInstallation.grid_substation)
        .join(GridSubstation.district)
        .where(GenerationReading.installation_id == installation_id)
        .where(district_scope_clause(principal))
    )
    query = apply_reading_filters(
        query, recorded_from=recorded_from, recorded_to=recorded_to
    )
    return paginated_readings(
        query=query,
        request=request,
        response=response,
        db=db,
        page=page,
        page_size=page_size,
        sort=sort,
    )


@router.post(
    "/installations/{installation_id}/readings",
    response_model=DataEnvelope[GenerationReadingOut],
    status_code=status.HTTP_201_CREATED,
)
def create_reading(
    installation_id: int,
    body: GenerationReadingCreate,
    response: Response,
    db: DbSession,
    principal: InstallationPrincipal,
) -> DataEnvelope[GenerationReadingOut]:
    require_own_installation(principal, installation_id)
    one_or_not_found(
        db,
        select(SolarInstallation).where(
            SolarInstallation.id == installation_id,
            SolarInstallation.status == "active",
        ),
        "Installation",
    )
    reading = GenerationReading(installation_id=installation_id, **body.model_dump())
    db.add(reading)
    commit_or_conflict(db, "A reading already exists for this installation and timestamp")
    db.refresh(reading)

    output = GenerationReadingOut.model_validate(reading)
    etag = content_etag(output.model_dump(mode="json"))
    set_validator_headers(response, etag=etag, last_modified=reading.received_at)
    response.headers[
        "Location"
    ] = f"/api/v1/installations/{installation_id}/readings/{reading.id}"
    return DataEnvelope(data=output)


@router.get(
    "/installations/{installation_id}/readings/{reading_id}",
    response_model=DataEnvelope[GenerationReadingOut],
)
def get_reading(
    installation_id: int,
    reading_id: int,
    request: Request,
    response: Response,
    db: DbSession,
    principal: ReadPrincipal,
) -> Any:
    reading = one_or_not_found(
        db,
        select(GenerationReading)
        .join(GenerationReading.installation)
        .join(SolarInstallation.grid_substation)
        .join(GridSubstation.district)
        .where(
            GenerationReading.id == reading_id,
            GenerationReading.installation_id == installation_id,
            district_scope_clause(principal),
        ),
        "Generation reading",
    )
    output = GenerationReadingOut.model_validate(reading)
    etag = content_etag(output.model_dump(mode="json"))
    if cached := check_not_modified(
        request, etag=etag, last_modified=reading.received_at
    ):
        return cached
    set_validator_headers(response, etag=etag, last_modified=reading.received_at)
    return DataEnvelope(data=output)


@router.api_route(
    "/installations/{installation_id}/readings/{reading_id}",
    methods=["PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
def reject_reading_mutation(installation_id: int, reading_id: int) -> None:
    # The history is append-only: correcting data means appending an auditable
    # replacement in a future design, never changing the submitted measurement.
    raise ApiError(
        405,
        "reading_is_immutable",
        "Generation readings are append-only and cannot be changed or deleted",
        headers={"Allow": "GET"},
    )


@router.get("/readings", response_model=PaginatedResponse[GenerationReadingOut])
def list_regional_readings(
    request: Request,
    response: Response,
    db: DbSession,
    principal: ReadPrincipal,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    recorded_from: datetime | None = None,
    recorded_to: datetime | None = None,
    sort: Literal["recorded_at", "-recorded_at"] = "-recorded_at",
    province_id: int | None = Query(default=None, gt=0),
    district_id: int | None = Query(default=None, gt=0),
    grid_substation_id: int | None = Query(default=None, gt=0),
    installation_id: int | None = Query(default=None, gt=0),
) -> Any:
    """Analytical collection for time and jurisdiction filters across sites."""

    validate_time_window(recorded_from, recorded_to)
    query = (
        select(GenerationReading)
        .join(GenerationReading.installation)
        .join(SolarInstallation.grid_substation)
        .join(GridSubstation.district)
        .where(district_scope_clause(principal))
    )
    query = apply_reading_filters(
        query,
        recorded_from=recorded_from,
        recorded_to=recorded_to,
        province_id=province_id,
        district_id=district_id,
        grid_substation_id=grid_substation_id,
        installation_id=installation_id,
    )
    return paginated_readings(
        query=query,
        request=request,
        response=response,
        db=db,
        page=page,
        page_size=page_size,
        sort=sort,
    )


@router.get(
    "/installations/{installation_id}/last-known-reading",
    response_model=DataEnvelope[GenerationReadingOut],
)
def get_last_known_reading(
    installation_id: int,
    request: Request,
    response: Response,
    db: DbSession,
    principal: ReadPrincipal,
) -> Any:
    one_or_not_found(
        db,
        visible_installation_query(principal).where(SolarInstallation.id == installation_id),
        "Installation",
    )
    reading = one_or_not_found(
        db,
        select(GenerationReading)
        .where(GenerationReading.installation_id == installation_id)
        .order_by(desc(GenerationReading.recorded_at), desc(GenerationReading.id))
        .limit(1),
        "Last-known reading",
    )
    output = GenerationReadingOut.model_validate(reading)
    etag = content_etag(output.model_dump(mode="json"))
    if cached := check_not_modified(
        request, etag=etag, last_modified=reading.received_at
    ):
        return cached
    set_validator_headers(response, etag=etag, last_modified=reading.received_at)
    return DataEnvelope(data=output)


@router.get(
    "/installations/{installation_id}/overview",
    response_model=DataEnvelope[InstallationOverviewOut],
)
def get_installation_overview(
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
    last_reading = db.scalar(
        select(GenerationReading)
        .where(GenerationReading.installation_id == installation_id)
        .order_by(desc(GenerationReading.recorded_at), desc(GenerationReading.id))
        .limit(1)
    )
    start = normalize_utc(last_reading.recorded_at) - timedelta(hours=24) if last_reading else None
    recent = []
    if last_reading:
        recent = list(
            db.scalars(
                select(GenerationReading)
                .where(
                    GenerationReading.installation_id == installation_id,
                    GenerationReading.recorded_at >= start,
                    GenerationReading.recorded_at <= last_reading.recorded_at,
                )
                .order_by(GenerationReading.recorded_at)
            )
        )
    energy = Decimal("0")
    if len(recent) >= 2:
        energy = max(
            Decimal("0"),
            recent[-1].cumulative_energy_kwh - recent[0].cumulative_energy_kwh,
        )
    summary = RecentSummaryOut(
        recorded_from=recent[0].recorded_at if recent else None,
        recorded_to=recent[-1].recorded_at if recent else None,
        reading_count=len(recent),
        energy_generated_kwh=energy,
        peak_power_kw=max((item.power_kw for item in recent), default=Decimal("0")),
    )
    output = InstallationOverviewOut(
        installation=InstallationOut.model_validate(installation),
        hierarchy=HierarchyOut(
            province=ProvinceOut.model_validate(
                installation.grid_substation.district.province
            ),
            district=DistrictOut.model_validate(installation.grid_substation.district),
            grid_substation=GridSubstationOut.model_validate(
                installation.grid_substation
            ),
        ),
        last_known_reading=(
            GenerationReadingOut.model_validate(last_reading) if last_reading else None
        ),
        recent_summary=summary,
    )
    changed_at = last_reading.received_at if last_reading else installation.updated_at
    etag = content_etag(output.model_dump(mode="json"))
    if cached := check_not_modified(request, etag=etag, last_modified=changed_at):
        return cached
    set_validator_headers(response, etag=etag, last_modified=changed_at)
    return DataEnvelope(data=output)


@router.get(
    "/districts/{district_id}/generation-summary",
    response_model=DataEnvelope[DistrictGenerationSummaryOut],
)
def get_district_generation_summary(
    district_id: int,
    request: Request,
    response: Response,
    db: DbSession,
    principal: ReadPrincipal,
    as_of: datetime | None = None,
) -> Any:
    district = one_or_not_found(
        db,
        visible_district_query(principal).where(District.id == district_id),
        "District",
    )
    as_of = as_of or utc_now()
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ApiError(400, "invalid_as_of", "as_of must include a timezone offset")
    as_of = as_of.astimezone(UTC)

    installations = list(
        db.scalars(
            select(SolarInstallation)
            .join(SolarInstallation.grid_substation)
            .where(
                GridSubstation.district_id == district_id,
                SolarInstallation.status == "active",
            )
            .order_by(SolarInstallation.id)
        )
    )
    colombo = ZoneInfo("Asia/Colombo")
    local_as_of = as_of.astimezone(colombo)
    local_midnight = local_as_of.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_utc = local_midnight.astimezone(UTC)

    current_power = Decimal("0")
    today_energy = Decimal("0")
    reporting = 0
    latest_rows: list[GenerationReading] = []
    for installation in installations:
        latest = db.scalar(
            select(GenerationReading)
            .where(
                GenerationReading.installation_id == installation.id,
                GenerationReading.recorded_at <= as_of,
            )
            .order_by(desc(GenerationReading.recorded_at), desc(GenerationReading.id))
            .limit(1)
        )
        if latest is None:
            continue
        latest_rows.append(latest)
        if as_of - normalize_utc(latest.recorded_at) <= timedelta(minutes=30):
            current_power += latest.power_kw
            reporting += 1

        baseline = db.scalar(
            select(GenerationReading)
            .where(
                GenerationReading.installation_id == installation.id,
                GenerationReading.recorded_at >= midnight_utc,
                GenerationReading.recorded_at <= as_of,
            )
            .order_by(asc(GenerationReading.recorded_at), asc(GenerationReading.id))
            .limit(1)
        )
        if baseline:
            # Cumulative meter values are differenced per installation; adding the
            # raw meter totals would seriously overstate today's generation.
            today_energy += max(
                Decimal("0"),
                latest.cumulative_energy_kwh - baseline.cumulative_energy_kwh,
            )

    output = DistrictGenerationSummaryOut(
        district_id=district.id,
        district_name=district.name,
        as_of=as_of,
        timezone="Asia/Colombo",
        current_power_kw=current_power,
        today_energy_kwh=today_energy,
        reporting_installations=reporting,
        stale_installations=len(installations) - reporting,
    )
    changed_at = max(
        (row.received_at for row in latest_rows),
        default=district.updated_at,
    )
    etag = content_etag(output.model_dump(mode="json"))
    if cached := check_not_modified(request, etag=etag, last_modified=changed_at):
        return cached
    set_validator_headers(response, etag=etag, last_modified=changed_at)
    return DataEnvelope(data=output)
