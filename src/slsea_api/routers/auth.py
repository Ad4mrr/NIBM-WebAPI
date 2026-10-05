"""Issue short-lived JWTs for seeded SLSEA users and installations."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select

from slsea_api.config import get_settings
from slsea_api.database import get_db
from slsea_api.errors import ApiError
from slsea_api.models import SolarInstallation, User
from slsea_api.schemas import ErrorResponse, TokenOut
from slsea_api.security import create_access_token, verify_secret

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/token",
    response_model=TokenOut,
    responses={401: {"model": ErrorResponse}},
    summary="Exchange user or installation credentials for a JWT",
)
def create_token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    response: Response,
    db=Depends(get_db),
) -> TokenOut:
    """Authenticate by user email first, then by installation meter ID.

    This small token endpoint is for coursework demonstration. The API still
    uses normal bearer tokens; a full OAuth authorization server is out of scope.
    """

    user = db.scalar(select(User).where(func.lower(User.email) == form.username.lower()))
    if user and user.is_active and verify_secret(form.password, user.password_hash):
        scopes = ["analyst:read"]
        if user.role == "admin":
            scopes.append("catalog:write")
        token = create_access_token(
            subject=f"user:{user.id}",
            actor_type="user",
            scopes=scopes,
            role=user.role,
            province_id=user.province_id,
            district_id=user.district_id,
        )
    else:
        installation = db.scalar(
            select(SolarInstallation).where(SolarInstallation.meter_id == form.username)
        )
        if (
            installation is None
            or installation.status != "active"
            or not verify_secret(form.password, installation.device_secret_hash)
        ):
            raise ApiError(
                401,
                "invalid_credentials",
                "The username or secret is incorrect",
                headers={"WWW-Authenticate": "Bearer"},
            )
        scopes = ["installation:write"]
        token = create_access_token(
            subject=f"installation:{installation.id}",
            actor_type="installation",
            scopes=scopes,
            installation_id=installation.id,
        )

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return TokenOut(
        access_token=token,
        expires_in=get_settings().access_token_minutes * 60,
        scope=" ".join(scopes),
    )
