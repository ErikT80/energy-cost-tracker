"""Backup platform for Energy Cost Tracker."""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _runtimes(hass: HomeAssistant) -> list:
    """Return loaded Energy Cost Tracker runtimes."""
    return [
        value
        for value in hass.data.get(DOMAIN, {}).values()
        if hasattr(value, "async_prepare_backup")
    ]


async def async_pre_backup(hass: HomeAssistant) -> None:
    """Pause accounting and checkpoint the SQLite ledger before backup."""
    prepared = []
    try:
        for runtime in _runtimes(hass):
            await runtime.async_prepare_backup()
            prepared.append(runtime)
    except Exception:
        for runtime in reversed(prepared):
            try:
                await runtime.async_resume_after_backup()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Failed to resume Energy Cost Tracker after backup preparation error")
        raise


async def async_post_backup(hass: HomeAssistant) -> None:
    """Resume accounting after backup completes."""
    for runtime in _runtimes(hass):
        await runtime.async_resume_after_backup()
