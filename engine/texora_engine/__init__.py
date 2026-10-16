"""Texora offline OCR engine sidecar.

M1 skeleton: a real FastAPI + Uvicorn service exposing an open health check and a
bearer-token-protected example route. No OCR/ML logic lives here yet.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
