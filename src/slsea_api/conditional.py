"""Helpers for HTTP validators (ETag, Last-Modified and preconditions)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime
from typing import Any

from fastapi import Request, Response

from slsea_api.errors import ApiError


def version_etag(resource: str, resource_id: int, version: int) -> str:
    """Stable validator for database rows that have a version column."""

    return f'"{resource}-{resource_id}-v{version}"'


def content_etag(value: Any) -> str:
    """Hash a composite or collection after converting it to canonical JSON."""

    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return f'"sha256-{hashlib.sha256(encoded).hexdigest()}"'


def http_date(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return format_datetime(value.astimezone(UTC), usegmt=True)


def check_not_modified(
    request: Request,
    *,
    etag: str,
    last_modified: datetime,
) -> Response | None:
    """Return a body-less 304 when the client's cached copy is current."""

    headers = {"ETag": etag, "Last-Modified": http_date(last_modified)}
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and etag in {tag.strip() for tag in if_none_match.split(",")}:
        return Response(status_code=304, headers=headers)

    # HTTP dates have one-second precision, so compare after dropping microseconds.
    if not if_none_match and (if_modified_since := request.headers.get("if-modified-since")):
        try:
            cached_at = parsedate_to_datetime(if_modified_since).astimezone(UTC)
            changed_at = last_modified
            if changed_at.tzinfo is None:
                changed_at = changed_at.replace(tzinfo=UTC)
            changed_at = changed_at.astimezone(UTC).replace(microsecond=0)
            if changed_at <= cached_at.replace(microsecond=0):
                return Response(status_code=304, headers=headers)
        except (TypeError, ValueError, OverflowError):
            pass  # Invalid dates are ignored as required by HTTP semantics.
    return None


def set_validator_headers(
    response: Response,
    *,
    etag: str,
    last_modified: datetime,
) -> None:
    response.headers["ETag"] = etag
    response.headers["Last-Modified"] = http_date(last_modified)
    response.headers["Cache-Control"] = "private, must-revalidate"


def require_matching_if_match(request: Request, current_etag: str) -> None:
    """Reject a stale optional If-Match precondition with HTTP 412."""

    supplied = request.headers.get("if-match")
    if supplied and supplied != "*" and current_etag not in {
        item.strip() for item in supplied.split(",")
    }:
        raise ApiError(
            412,
            "precondition_failed",
            "The resource changed after the client retrieved it",
            [{"field": "If-Match", "issue": "Retrieve the current resource and retry"}],
        )
