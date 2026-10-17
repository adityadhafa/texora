"""``GET /hardware`` + ``POST /hardware/device`` — device report + override.

Devices are computed from torch availability (CUDA / MPS / CPU). The current selection is
persisted in the ``setting`` table via the ``db`` DAO and read back by the recognizer factory
on the next build. An override to a device not in the detected set is rejected with 422.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from texora_engine.db import get_setting, set_setting
from texora_engine.logging_config import get_logger
from texora_engine.security import require_token

logger = get_logger("api.hardware")

_DEVICE_SETTING_KEY = "device"


class HardwareResponse(BaseModel):
    """Detected devices + current selection."""

    devices: list[str] = Field(description="Detected device ids, e.g. ['cpu', 'cuda'].")
    selected: str = Field(description="Currently selected execution device.")


class DeviceRequest(BaseModel):
    """Device override request."""

    device: str = Field(description="One of the detected device ids.")


def _detect_devices() -> list[str]:
    """Return the available devices. CPU is always present and listed first."""

    devices = ["cpu"]
    try:
        import torch

        if torch.cuda.is_available():
            devices.append("cuda")
        if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            devices.append("mps")
    except Exception as exc:  # torch import/probe failure must not 500 the route
        logger.warning("device probe failed, defaulting to cpu: %s", exc)
    return devices


def _current_selection(request: Request, devices: list[str]) -> str:
    conn = request.app.state.db
    stored = get_setting(conn, _DEVICE_SETTING_KEY)
    if stored and stored in devices:
        return stored
    # Fall back to the configured default if it is valid, else cpu.
    configured: str = request.app.state.settings.device
    return configured if configured in devices else "cpu"


hardware_router = APIRouter(dependencies=[Depends(require_token)], tags=["hardware"])


@hardware_router.get("/hardware", response_model=HardwareResponse)
def get_hardware(request: Request) -> HardwareResponse:
    """Report detected devices and the current selection."""

    devices = _detect_devices()
    return HardwareResponse(devices=devices, selected=_current_selection(request, devices))


@hardware_router.post("/hardware/device", response_model=HardwareResponse)
def set_device(req: DeviceRequest, request: Request) -> HardwareResponse:
    """Override the execution device; persist it and return the updated state."""

    devices = _detect_devices()
    if req.device not in devices:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown device {req.device!r}; available: {devices}",
        )
    conn = request.app.state.db
    set_setting(conn, _DEVICE_SETTING_KEY, req.device)
    # Keep live settings + any cached recognizer in sync so the next build uses the device.
    request.app.state.settings = request.app.state.settings.model_copy(
        update={"device": req.device}
    )
    request.app.state.formula_recognizer = None
    logger.info("device override set to %s", req.device)
    return HardwareResponse(devices=devices, selected=req.device)
