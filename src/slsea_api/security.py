"""Password/device-secret hashing and JWT access-token helpers."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

import jwt

from .config import get_settings

ActorType = Literal["user", "installation"]

_HASH_PREFIX = "pbkdf2_sha256"
_SALT_BYTES = 16
_DIGEST_BYTES = 32


class TokenValidationError(ValueError):
    """Raised when a JWT is invalid, expired, or has an unexpected claim shape."""


def _encode_bytes(value: bytes) -> str:
    """Encode binary hash data without unnecessary Base64 padding."""

    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_bytes(value: str) -> bytes:
    """Decode the URL-safe Base64 format used in stored password hashes."""

    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def hash_secret(secret: str) -> str:
    """Hash a password or installation secret with salted PBKDF2-HMAC-SHA256.

    The stored string contains the algorithm, work factor, random salt, and digest.
    It never contains the original secret.
    """

    if not secret:
        raise ValueError("Secret must not be empty")

    iterations = get_settings().pbkdf2_iterations
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        salt,
        iterations,
        dklen=_DIGEST_BYTES,
    )
    return f"{_HASH_PREFIX}${iterations}${_encode_bytes(salt)}${_encode_bytes(digest)}"


def verify_secret(secret: str, encoded: str) -> bool:
    """Verify a password/device secret without leaking timing information."""

    if not secret or not encoded:
        return False

    try:
        algorithm, raw_iterations, raw_salt, raw_digest = encoded.split("$", 3)
        iterations = int(raw_iterations)
        salt = _decode_bytes(raw_salt)
        expected_digest = _decode_bytes(raw_digest)
    except (ValueError, TypeError, binascii.Error):
        return False

    if algorithm != _HASH_PREFIX or iterations <= 0 or iterations > 10_000_000:
        return False
    if len(salt) < 8 or len(expected_digest) != _DIGEST_BYTES:
        return False

    candidate_digest = hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        salt,
        iterations,
        dklen=len(expected_digest),
    )
    return hmac.compare_digest(candidate_digest, expected_digest)


def _build_jurisdiction(
    role: str | None,
    province_id: int | None,
    district_id: int | None,
    jurisdiction_level: str | None,
    jurisdiction_id: int | None,
) -> dict[str, str | int | None]:
    """Build the small jurisdiction object copied into a user token."""

    level = jurisdiction_level or role
    identifier = jurisdiction_id

    if role in {"national", "admin"}:
        level = "national"
        identifier = None
    elif role == "province":
        level = "province"
        identifier = province_id if jurisdiction_id is None else jurisdiction_id
    elif role == "district":
        level = "district"
        identifier = district_id if jurisdiction_id is None else jurisdiction_id

    if level not in {"national", "province", "district"}:
        raise ValueError("A user token requires a valid jurisdiction level")
    if level in {"province", "district"} and identifier is None:
        raise ValueError("A regional user token requires a jurisdiction id")
    if level == "national" and identifier is not None:
        raise ValueError("A national jurisdiction must not have an id")

    return {"level": level, "id": identifier}


def create_access_token(
    subject: str | int,
    actor_type: ActorType,
    scopes: Sequence[str],
    *,
    installation_id: int | None = None,
    role: str | None = None,
    province_id: int | None = None,
    district_id: int | None = None,
    jurisdiction_level: str | None = None,
    jurisdiction_id: int | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Issue a signed access token for an SLSEA user or one installation.

    ``scopes`` authorizes an operation class. The installation/jurisdiction claim
    then restricts which rows that actor may access.
    """

    settings = get_settings()
    normalized_scopes = sorted({scope.strip() for scope in scopes if scope.strip()})
    if not normalized_scopes:
        raise ValueError("At least one scope is required")

    now = datetime.now(UTC)
    lifetime = expires_delta or timedelta(minutes=settings.access_token_minutes)
    if lifetime <= timedelta(0):
        raise ValueError("Token lifetime must be positive")

    claims: dict[str, Any] = {
        "sub": str(subject),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "nbf": now,
        "exp": now + lifetime,
        "jti": str(uuid4()),
        "actor_type": actor_type,
        "scopes": normalized_scopes,
        # The conventional space-delimited form is useful to Swagger/OAuth clients.
        "scope": " ".join(normalized_scopes),
    }

    if actor_type == "installation":
        if installation_id is None or installation_id <= 0:
            raise ValueError("An installation token requires installation_id")
        claims["installation_id"] = installation_id
    elif actor_type == "user":
        if role not in {"national", "province", "district", "admin"}:
            raise ValueError("A user token requires a valid role")
        claims["role"] = role
        claims["jurisdiction"] = _build_jurisdiction(
            role,
            province_id,
            district_id,
            jurisdiction_level,
            jurisdiction_id,
        )
        if province_id is not None:
            claims["province_id"] = province_id
        if district_id is not None:
            claims["district_id"] = district_id
    else:
        raise ValueError("actor_type must be 'user' or 'installation'")

    return jwt.encode(
        claims,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify a JWT and return normalized claims suitable for authorization."""

    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={
                "require": [
                    "sub",
                    "iss",
                    "aud",
                    "iat",
                    "nbf",
                    "exp",
                    "jti",
                    "actor_type",
                    "scopes",
                ]
            },
        )
    except jwt.PyJWTError as exc:
        # The API layer can translate this stable exception into a 401 response.
        raise TokenValidationError("Invalid or expired access token") from exc

    actor_type = claims.get("actor_type")
    raw_scopes = claims.get("scopes")
    if actor_type not in {"user", "installation"}:
        raise TokenValidationError("Token has an invalid actor_type")
    if not isinstance(raw_scopes, list) or not all(
        isinstance(scope, str) and scope for scope in raw_scopes
    ):
        raise TokenValidationError("Token has invalid scopes")

    claims["scopes"] = sorted(set(raw_scopes))

    if actor_type == "installation":
        installation_id = claims.get("installation_id")
        if not isinstance(installation_id, int) or installation_id <= 0:
            raise TokenValidationError("Installation token is not bound to an installation")
    else:
        role = claims.get("role")
        jurisdiction = claims.get("jurisdiction")
        if role not in {"national", "province", "district", "admin"}:
            raise TokenValidationError("User token has an invalid role")
        if not isinstance(jurisdiction, dict):
            raise TokenValidationError("User token has no jurisdiction")
        try:
            _build_jurisdiction(
                role,
                claims.get("province_id"),
                claims.get("district_id"),
                jurisdiction.get("level"),
                jurisdiction.get("id"),
            )
        except ValueError as exc:
            raise TokenValidationError("User token has an invalid jurisdiction") from exc

    return claims
