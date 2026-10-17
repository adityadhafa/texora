"""FastAPI routers for the Texora engine."""

from texora_engine.api.hardware import hardware_router
from texora_engine.api.models import models_router
from texora_engine.api.recognize import recognize_router
from texora_engine.api.routes import health_router, protected_router

__all__ = [
    "hardware_router",
    "health_router",
    "models_router",
    "protected_router",
    "recognize_router",
]
