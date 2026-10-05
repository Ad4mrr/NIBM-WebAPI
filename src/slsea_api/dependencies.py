"""Authentication dependencies and jurisdiction-aware query helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Security
from fastapi.security import OAuth2PasswordBearer, SecurityScopes
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from slsea_api.config import get_settings
from slsea_api.database import get_db
from slsea_api.errors import ApiError
from slsea_api.models import District, SolarInstallation, User
from slsea_api.security import TokenValidationError, decode_access_token

SCOPES = {
    "analyst:read": "Read data inside the user's SLSEA jurisdiction",
    "catalog:write": "Create and manage geography and installation metadata",
    "installation:write": "Submit readings for the installation in the token",
}

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{get_settings().api_prefix}/auth/token",
    scopes=SCOPES,
)

DbSession = Annotated[Session, Depends(get_db)]


@dataclass(frozen=True)
class Principal:
    """Small, easy-to-inspect representation of the authenticated caller."""

    subject: str
    actor_type: str
    scopes: frozenset[str]
    role: str | None = None
    province_id: int | None = None
    district_id: int | None = None
    installation_id: int | None = None

    @property
    def is_national(self) -> bool:
        return self.role in {"national", "admin"}


def get_current_principal(
    security_scopes: SecurityScopes,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DbSession,
) -> Principal:
    """Validate a JWT, required scopes, and the actor's current database state."""

    authentication_header = {
        "WWW-Authenticate": f'Bearer scope="{security_scopes.scope_str}"'
    }
    try:
        claims = decode_access_token(token)
    except TokenValidationError as exc:
        raise ApiError(
            401,
            "invalid_token",
            "The access token is invalid or expired",
            headers=authentication_header,
        ) from exc

    token_scopes = frozenset(claims["scopes"])
    missing_scopes = set(security_scopes.scopes) - token_scopes
    if missing_scopes:
        raise ApiError(
            403,
            "insufficient_scope",
            "The token does not grant the required operation",
            [{"field": "scope", "issue": f"Missing: {', '.join(sorted(missing_scopes))}"}],
            headers=authentication_header,
        )

    actor_type = claims["actor_type"]
    if actor_type == "user":
        subject = str(claims["sub"])
        user_id = int(subject.removeprefix("user:"))
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            raise ApiError(401, "inactive_principal", "The user is not active")
        return Principal(
            subject=subject,
            actor_type="user",
            scopes=token_scopes,
            role=user.role,
            province_id=user.province_id,
            district_id=user.district_id,
        )

    subject = str(claims["sub"])
    installation_id = int(claims["installation_id"])
    installation = db.get(SolarInstallation, installation_id)
    if installation is None or installation.status != "active":
        raise ApiError(401, "inactive_principal", "The installation is not active")
    return Principal(
        subject=subject,
        actor_type="installation",
        scopes=token_scopes,
        installation_id=installation_id,
    )


ReadPrincipal = Annotated[
    Principal,
    Security(get_current_principal, scopes=["analyst:read"]),
]
CatalogPrincipal = Annotated[
    Principal,
    Security(get_current_principal, scopes=["catalog:write"]),
]
InstallationPrincipal = Annotated[
    Principal,
    Security(get_current_principal, scopes=["installation:write"]),
]


def district_scope_clause(principal: Principal) -> Any:
    """Return the SQL condition that limits a query already joined to District."""

    if principal.is_national:
        return True
    if principal.role == "province":
        return District.province_id == principal.province_id
    if principal.role == "district":
        return District.id == principal.district_id
    return False


def province_ids_query(principal: Principal) -> Select[tuple[int]]:
    """Subquery for provinces visible to a national, province, or district user."""

    query = select(District.province_id).distinct()
    if principal.is_national:
        return query
    if principal.role == "province":
        return query.where(District.province_id == principal.province_id)
    if principal.role == "district":
        return query.where(District.id == principal.district_id)
    return query.where(False)


def require_own_installation(principal: Principal, installation_id: int) -> None:
    """A meter token can only submit data to its own installation path."""

    if principal.installation_id != installation_id:
        raise ApiError(
            403,
            "installation_scope_violation",
            "This token cannot submit readings for another installation",
        )
