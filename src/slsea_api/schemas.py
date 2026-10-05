"""Request and response shapes used by the API.

The schemas live in one file on purpose. For a coursework-sized project this makes
them easier to find and explain than a large tree of tiny schema modules.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ApiModel(BaseModel):
    """Base model with the same settings for every API schema."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ErrorItem(ApiModel):
    field: str | None = None
    issue: str


class ErrorResponse(ApiModel):
    code: str
    message: str
    details: list[ErrorItem] = Field(default_factory=list)
    request_id: str


COMMON_ERROR_RESPONSES = {
    304: {"description": "Cached representation is still current; empty body"},
    400: {"model": ErrorResponse, "description": "Invalid request"},
    401: {"model": ErrorResponse, "description": "Missing or invalid access token"},
    403: {"model": ErrorResponse, "description": "Scope or jurisdiction denied"},
    404: {"model": ErrorResponse, "description": "Resource not found"},
    406: {"model": ErrorResponse, "description": "Only JSON is available"},
    409: {"model": ErrorResponse, "description": "Uniqueness or relationship conflict"},
    412: {"model": ErrorResponse, "description": "If-Match precondition failed"},
    415: {"model": ErrorResponse, "description": "Request body is not JSON"},
}


T = TypeVar("T")


class DataEnvelope(ApiModel, Generic[T]):
    data: T


class PageInfo(ApiModel):
    number: int
    size: int
    total_items: int
    total_pages: int


class PageLinks(ApiModel):
    self: str
    next: str | None
    previous: str | None


class PaginatedResponse(ApiModel, Generic[T]):
    items: list[T]
    page: PageInfo
    links: PageLinks


class MutableResource(ApiModel):
    id: int
    created_at: datetime
    updated_at: datetime
    version: int


class ProvinceWrite(ApiModel):
    code: str = Field(min_length=2, max_length=10, pattern=r"^[A-Z0-9-]+$")
    name: str = Field(min_length=2, max_length=100)


class ProvincePatch(ApiModel):
    code: str | None = Field(default=None, min_length=2, max_length=10, pattern=r"^[A-Z0-9-]+$")
    name: str | None = Field(default=None, min_length=2, max_length=100)


class ProvinceOut(MutableResource):
    code: str
    name: str


class DistrictCreate(ApiModel):
    code: str = Field(min_length=2, max_length=10, pattern=r"^[A-Z0-9-]+$")
    name: str = Field(min_length=2, max_length=100)


class DistrictReplace(DistrictCreate):
    province_id: int = Field(gt=0)


class DistrictPatch(ApiModel):
    province_id: int | None = Field(default=None, gt=0)
    code: str | None = Field(default=None, min_length=2, max_length=10, pattern=r"^[A-Z0-9-]+$")
    name: str | None = Field(default=None, min_length=2, max_length=100)


class DistrictOut(MutableResource):
    province_id: int
    code: str
    name: str


class GridSubstationCreate(ApiModel):
    code: str = Field(min_length=2, max_length=30, pattern=r"^[A-Z0-9-]+$")
    name: str = Field(min_length=2, max_length=120)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    capacity_mw: Decimal | None = Field(default=None, gt=0)


class GridSubstationReplace(GridSubstationCreate):
    district_id: int = Field(gt=0)


class GridSubstationPatch(ApiModel):
    district_id: int | None = Field(default=None, gt=0)
    code: str | None = Field(default=None, min_length=2, max_length=30, pattern=r"^[A-Z0-9-]+$")
    name: str | None = Field(default=None, min_length=2, max_length=120)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    capacity_mw: Decimal | None = Field(default=None, gt=0)


class GridSubstationOut(MutableResource):
    district_id: int
    code: str
    name: str
    latitude: Decimal | None
    longitude: Decimal | None
    capacity_mw: Decimal | None


InstallationStatus = Literal["active", "inactive", "maintenance"]


class InstallationCreate(ApiModel):
    meter_id: str = Field(min_length=3, max_length=80)
    name: str = Field(min_length=2, max_length=120)
    address: str | None = Field(default=None, max_length=250)
    installed_capacity_kw: Decimal = Field(gt=0, le=1000)
    commissioned_on: date | None = None
    status: InstallationStatus = "active"
    device_secret: str = Field(min_length=12, max_length=200)


class InstallationReplace(InstallationCreate):
    grid_substation_id: int = Field(gt=0)


class InstallationPatch(ApiModel):
    grid_substation_id: int | None = Field(default=None, gt=0)
    meter_id: str | None = Field(default=None, min_length=3, max_length=80)
    name: str | None = Field(default=None, min_length=2, max_length=120)
    address: str | None = Field(default=None, max_length=250)
    installed_capacity_kw: Decimal | None = Field(default=None, gt=0, le=1000)
    commissioned_on: date | None = None
    status: InstallationStatus | None = None
    device_secret: str | None = Field(default=None, min_length=12, max_length=200)


class InstallationOut(MutableResource):
    grid_substation_id: int
    meter_id: str
    name: str
    address: str | None
    installed_capacity_kw: Decimal
    commissioned_on: date | None
    status: str


class GenerationReadingCreate(ApiModel):
    recorded_at: datetime
    power_kw: Decimal = Field(ge=0)
    cumulative_energy_kwh: Decimal = Field(ge=0)
    voltage_v: Decimal = Field(gt=0, le=1000)

    @field_validator("recorded_at")
    @classmethod
    def timestamp_must_include_timezone(cls, value: datetime) -> datetime:
        # Requiring an offset prevents an ambiguous local timestamp reaching the database.
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recorded_at must include a timezone offset")
        return value


class GenerationReadingOut(ApiModel):
    id: int
    installation_id: int
    recorded_at: datetime
    received_at: datetime
    power_kw: Decimal
    cumulative_energy_kwh: Decimal
    voltage_v: Decimal


class HierarchyOut(ApiModel):
    province: ProvinceOut
    district: DistrictOut
    grid_substation: GridSubstationOut


class RecentSummaryOut(ApiModel):
    recorded_from: datetime | None
    recorded_to: datetime | None
    reading_count: int
    energy_generated_kwh: Decimal
    peak_power_kw: Decimal


class InstallationOverviewOut(ApiModel):
    installation: InstallationOut
    hierarchy: HierarchyOut
    last_known_reading: GenerationReadingOut | None
    recent_summary: RecentSummaryOut


class DistrictGenerationSummaryOut(ApiModel):
    district_id: int
    district_name: str
    as_of: datetime
    timezone: str
    current_power_kw: Decimal
    today_energy_kwh: Decimal
    reporting_installations: int
    stale_installations: int


class TokenOut(ApiModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    scope: str


class HealthOut(ApiModel):
    status: Literal["ok", "unavailable"]


class ReadingQuery(ApiModel):
    recorded_from: datetime | None = None
    recorded_to: datetime | None = None
    sort: Literal["recorded_at", "-recorded_at"] = "-recorded_at"

    @model_validator(mode="after")
    def time_window_must_be_ordered(self) -> ReadingQuery:
        if self.recorded_from and self.recorded_to and self.recorded_from >= self.recorded_to:
            raise ValueError("recorded_from must be earlier than recorded_to")
        for value in (self.recorded_from, self.recorded_to):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("time filters must include a timezone offset")
        return self
