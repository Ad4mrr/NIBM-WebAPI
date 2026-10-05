"""One predictable error format for every client error."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response


class ApiError(Exception):
    """An expected API problem that can be safely shown to a client."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []
        self.headers = headers or {}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid4()))


def error_response(request: Request, error: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        headers=error.headers,
        content={
            "code": error.code,
            "message": error.message,
            "details": error.details,
            "request_id": _request_id(request),
        },
    )


def install_exception_handlers(app: FastAPI) -> None:
    """Replace FastAPI's different client-error shapes with one contract."""

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in item["loc"]),
                "issue": item["msg"],
            }
            for item in exc.errors()
        ]
        return error_response(
            request,
            ApiError(400, "validation_error", "Request validation failed", details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_framework_http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code_by_status = {
            404: "not_found",
            405: "method_not_allowed",
        }
        return error_response(
            request,
            ApiError(
                exc.status_code,
                code_by_status.get(exc.status_code, "http_error"),
                str(exc.detail),
                headers=exc.headers,
            ),
        )


class RequestPolicyMiddleware(BaseHTTPMiddleware):
    """Add request IDs and enforce the JSON-only representation policy."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = request.headers.get("X-Request-ID", str(uuid4()))

        if request.url.path.startswith("/api/"):
            accept = request.headers.get("accept", "*/*").lower()
            accepts_json = any(
                value in accept for value in ("*/*", "application/json", "application/*")
            )
            if not accepts_json:
                response = error_response(
                    request,
                    ApiError(406, "not_acceptable", "This API only returns JSON"),
                )
                response.headers["Vary"] = "Accept"
                return response

            is_json_write = request.method in {"POST", "PUT", "PATCH"}
            is_token_request = request.url.path == "/api/v1/auth/token"
            if is_json_write and not is_token_request:
                content_type = request.headers.get("content-type", "").split(";", 1)[0]
                if content_type != "application/json":
                    return error_response(
                        request,
                        ApiError(
                            415,
                            "unsupported_media_type",
                            "Request body must use application/json",
                        ),
                    )

        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Vary", "Accept, Authorization")
        return response
