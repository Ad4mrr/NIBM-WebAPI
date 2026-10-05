"""SLSEA real-time and historical solar-generation API package."""

from .models import (
    Base,
    District,
    GenerationReading,
    GridSubstation,
    Province,
    SolarInstallation,
    User,
)

__version__ = "0.1.0"

__all__ = [
    "Base",
    "District",
    "GenerationReading",
    "GridSubstation",
    "Province",
    "SolarInstallation",
    "User",
    "__version__",
]
