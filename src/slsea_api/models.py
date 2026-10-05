"""SQLAlchemy models for the solar-generation domain.

The meter is represented by ``SolarInstallation.meter_id`` rather than a separate
device table. Generation readings are immutable history, while catalog resources
carry timestamps and an optimistic-lock version number.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column, relationship


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for Python-side defaults."""

    return datetime.now(UTC)


# Stable constraint names make future Alembic migrations easier to read.
metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


class Base(DeclarativeBase):
    """Base class used by every ORM model."""

    metadata = metadata


class MutableResourceMixin:
    """Common audit fields for resources that API administrators can edit."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, object]:
        # SQLAlchemy increments this column and rejects stale concurrent updates.
        return {"version_id_col": cls.version}


class Province(MutableResourceMixin, Base):
    """Top-level SLSEA jurisdiction."""

    __tablename__ = "provinces"
    __table_args__ = (
        UniqueConstraint("code", name="province_code"),
        UniqueConstraint("name", name="province_name"),
        CheckConstraint("length(trim(code)) >= 2", name="province_code_not_blank"),
        CheckConstraint("length(trim(name)) >= 2", name="province_name_not_blank"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Deletes are deliberately not cascaded: removing a parent must never erase
    # historical generation data hidden below it.
    districts: Mapped[list[District]] = relationship(
        back_populates="province", cascade="save-update, merge", passive_deletes=True
    )
    users: Mapped[list[User]] = relationship(
        back_populates="province",
        foreign_keys="User.province_id",
        cascade="save-update, merge",
        passive_deletes=True,
    )


class District(MutableResourceMixin, Base):
    """A province-scoped jurisdiction containing grid substations."""

    __tablename__ = "districts"
    __table_args__ = (
        UniqueConstraint("code", name="district_code"),
        UniqueConstraint("province_id", "name", name="district_province_name"),
        CheckConstraint("length(trim(code)) >= 2", name="district_code_not_blank"),
        CheckConstraint("length(trim(name)) >= 2", name="district_name_not_blank"),
        Index("ix_districts_province_id", "province_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    province_id: Mapped[int] = mapped_column(
        ForeignKey("provinces.id", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    province: Mapped[Province] = relationship(back_populates="districts")
    grid_substations: Mapped[list[GridSubstation]] = relationship(
        back_populates="district", cascade="save-update, merge", passive_deletes=True
    )
    users: Mapped[list[User]] = relationship(
        back_populates="district",
        foreign_keys="User.district_id",
        cascade="save-update, merge",
        passive_deletes=True,
    )


class GridSubstation(MutableResourceMixin, Base):
    """Grid node to which solar installations are connected."""

    __tablename__ = "grid_substations"
    __table_args__ = (
        UniqueConstraint("code", name="grid_substation_code"),
        UniqueConstraint("district_id", "name", name="grid_substation_district_name"),
        CheckConstraint("length(trim(code)) >= 2", name="grid_substation_code_not_blank"),
        CheckConstraint("length(trim(name)) >= 2", name="grid_substation_name_not_blank"),
        CheckConstraint(
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
            name="grid_substation_latitude_range",
        ),
        CheckConstraint(
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
            name="grid_substation_longitude_range",
        ),
        CheckConstraint(
            "capacity_mw IS NULL OR capacity_mw > 0",
            name="grid_substation_capacity_positive",
        ),
        Index("ix_grid_substations_district_id", "district_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    district_id: Mapped[int] = mapped_column(
        ForeignKey("districts.id", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    capacity_mw: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)

    district: Mapped[District] = relationship(back_populates="grid_substations")
    installations: Mapped[list[SolarInstallation]] = relationship(
        back_populates="grid_substation",
        cascade="save-update, merge",
        passive_deletes=True,
    )


class SolarInstallation(MutableResourceMixin, Base):
    """Rooftop solar asset and the credential identity of its meter/inverter."""

    __tablename__ = "solar_installations"
    __table_args__ = (
        UniqueConstraint("meter_id", name="solar_installation_meter_id"),
        CheckConstraint("length(trim(meter_id)) >= 3", name="installation_meter_id_not_blank"),
        CheckConstraint("length(trim(name)) >= 2", name="installation_name_not_blank"),
        CheckConstraint(
            "installed_capacity_kw > 0 AND installed_capacity_kw <= 1000",
            name="installation_capacity_range",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive', 'maintenance')",
            name="installation_status_allowed",
        ),
        Index("ix_solar_installations_grid_substation_id", "grid_substation_id"),
        Index("ix_solar_installations_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    grid_substation_id: Mapped[int] = mapped_column(
        ForeignKey("grid_substations.id", ondelete="RESTRICT", onupdate="CASCADE"),
        nullable=False,
    )
    meter_id: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    installed_capacity_kw: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    commissioned_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    # Only the PBKDF2 representation is stored; the submitted secret is never kept.
    device_secret_hash: Mapped[str] = mapped_column(String(256), nullable=False)

    grid_substation: Mapped[GridSubstation] = relationship(back_populates="installations")
    readings: Mapped[list[GenerationReading]] = relationship(
        back_populates="installation",
        cascade="save-update, merge",
        passive_deletes=True,
        order_by="GenerationReading.recorded_at",
    )


class GenerationReading(Base):
    """Append-only timestamped generation measurement for one installation."""

    __tablename__ = "generation_readings"
    __table_args__ = (
        UniqueConstraint(
            "installation_id", "recorded_at", name="generation_reading_installation_time"
        ),
        CheckConstraint("power_kw >= 0", name="generation_reading_power_non_negative"),
        CheckConstraint(
            "cumulative_energy_kwh >= 0",
            name="generation_reading_energy_non_negative",
        ),
        CheckConstraint(
            "voltage_v > 0 AND voltage_v <= 1000",
            name="generation_reading_voltage_range",
        ),
        Index(
            "ix_generation_readings_installation_recorded_at",
            "installation_id",
            "recorded_at",
        ),
        Index("ix_generation_readings_recorded_at", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    installation_id: Mapped[int] = mapped_column(
        ForeignKey("solar_installations.id", ondelete="RESTRICT", onupdate="CASCADE"),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    power_kw: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    cumulative_energy_kwh: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    voltage_v: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)

    installation: Mapped[SolarInstallation] = relationship(back_populates="readings")


class User(MutableResourceMixin, Base):
    """SLSEA staff identity with a role-specific read jurisdiction."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="user_email"),
        CheckConstraint("length(trim(email)) >= 3", name="user_email_not_blank"),
        CheckConstraint("length(trim(full_name)) >= 2", name="user_full_name_not_blank"),
        CheckConstraint(
            "role IN ('national', 'province', 'district', 'admin')",
            name="user_role_allowed",
        ),
        # National analysts and admins see all regions. Province/district analysts
        # carry exactly one matching foreign key, which keeps authorization simple.
        CheckConstraint(
            "((role IN ('national', 'admin') AND province_id IS NULL "
            "AND district_id IS NULL) OR "
            "(role = 'province' AND province_id IS NOT NULL AND district_id IS NULL) OR "
            "(role = 'district' AND province_id IS NULL AND district_id IS NOT NULL))",
            name="user_role_matches_jurisdiction",
        ),
        Index("ix_users_role", "role"),
        Index("ix_users_province_id", "province_id"),
        Index("ix_users_district_id", "district_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    province_id: Mapped[int | None] = mapped_column(
        ForeignKey("provinces.id", ondelete="RESTRICT", onupdate="CASCADE"), nullable=True
    )
    district_id: Mapped[int | None] = mapped_column(
        ForeignKey("districts.id", ondelete="RESTRICT", onupdate="CASCADE"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    province: Mapped[Province | None] = relationship(
        back_populates="users", foreign_keys=[province_id]
    )
    district: Mapped[District | None] = relationship(
        back_populates="users", foreign_keys=[district_id]
    )

    @property
    def jurisdiction_level(self) -> str:
        """Return the jurisdiction name that should be copied into a JWT."""

        if self.role in {"national", "admin"}:
            return "national"
        return self.role

    @property
    def jurisdiction_id(self) -> int | None:
        """Return the province or district identifier for this user's role."""

        if self.role == "province":
            return self.province_id
        if self.role == "district":
            return self.district_id
        return None


@event.listens_for(GenerationReading, "before_update")
def prevent_reading_update(
    _mapper: object, _connection: object, _reading: GenerationReading
) -> None:
    """Reject accidental ORM updates to the append-only time series."""

    raise ValueError("GenerationReading rows are append-only and cannot be updated")


@event.listens_for(GenerationReading, "before_delete")
def prevent_reading_delete(
    _mapper: object, _connection: object, _reading: GenerationReading
) -> None:
    """Reject accidental ORM deletes from the append-only time series."""

    raise ValueError("GenerationReading rows are append-only and cannot be deleted")
