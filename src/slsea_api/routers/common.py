"""Shared route helpers kept small enough to understand at a glance."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from slsea_api.conditional import (
    check_not_modified,
    content_etag,
    set_validator_headers,
    version_etag,
)
from slsea_api.errors import ApiError


def commit_or_conflict(db: Session, message: str) -> None:
    """Turn database uniqueness/foreign-key failures into a safe HTTP 409."""

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, "data_conflict", message) from exc


def newest_change(resources: list[Any]) -> datetime:
    """Find the newest timestamp in a collection for Last-Modified."""

    values = [
        getattr(item, "updated_at", None) or getattr(item, "received_at", None)
        for item in resources
    ]
    return max(
        (value for value in values if value is not None),
        default=datetime(1970, 1, 1, tzinfo=UTC),
    )


def prepare_atomic_response(
    request: Request,
    response: Response,
    *,
    resource_name: str,
    resource: Any,
) -> Response | None:
    """Apply version validators and return 304 when the client cache is fresh."""

    etag = version_etag(resource_name, resource.id, resource.version)
    if cached := check_not_modified(
        request, etag=etag, last_modified=resource.updated_at
    ):
        return cached
    set_validator_headers(
        response, etag=etag, last_modified=resource.updated_at
    )
    return None


def prepare_collection_response(
    request: Request,
    response: Response,
    *,
    serialized: Any,
    resources: list[Any],
) -> Response | None:
    """Apply content validators to collection/composite representations."""

    etag = content_etag(serialized)
    changed_at = newest_change(resources)
    if cached := check_not_modified(request, etag=etag, last_modified=changed_at):
        return cached
    set_validator_headers(response, etag=etag, last_modified=changed_at)
    return None
