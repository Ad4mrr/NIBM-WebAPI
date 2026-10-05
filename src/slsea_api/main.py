"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from slsea_api.config import get_settings
from slsea_api.database import SessionLocal, init_db
from slsea_api.errors import ApiError, RequestPolicyMiddleware, install_exception_handlers
from slsea_api.routers import auth, catalog, readings
from slsea_api.schemas import DataEnvelope, HealthOut


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # create_all keeps first-time local and hosted setup simple for this project.
    # A long-lived production service should move later changes to migrations.
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        summary="Operational and historical rooftop-solar generation data",
        description=(
            "A Richardson Maturity Model Level 2 REST API for the Sri Lanka "
            "Sustainable Energy Authority coursework case study."
        ),
        lifespan=lifespan,
    )
    install_exception_handlers(app)
    app.add_middleware(RequestPolicyMiddleware)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "If-Match", "If-None-Match"],
        )

    api = APIRouter(prefix=settings.api_prefix)
    api.include_router(auth.router)
    api.include_router(catalog.router)
    api.include_router(readings.router)

    @api.get("/health/live", response_model=DataEnvelope[HealthOut], tags=["Health"])
    def live() -> DataEnvelope[HealthOut]:
        return DataEnvelope(data=HealthOut(status="ok"))

    @api.get("/health/ready", response_model=DataEnvelope[HealthOut], tags=["Health"])
    def ready() -> DataEnvelope[HealthOut]:
        try:
            with SessionLocal() as db:
                db.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise ApiError(503, "database_unavailable", "The database is not ready") from exc
        return DataEnvelope(data=HealthOut(status="ok"))

    app.include_router(api)

    @app.get("/", include_in_schema=False)
    def open_swagger() -> RedirectResponse:
        """Make the local root URL convenient for students using a browser."""

        return RedirectResponse(url="/docs")

    return app


app = create_app()
