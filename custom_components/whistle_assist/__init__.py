# SPDX-License-Identifier: Apache-2.0
"""Whistle Assist integration for Home Assistant."""

from __future__ import annotations

import os

# Needle enables anonymous usage telemetry by default. Respect either explicit
# operator setting; if neither is set, opt out by default for Home Assistant.
if "NEEDLE_TELEMETRY" not in os.environ and "DO_NOT_TRACK" not in os.environ:
    os.environ["NEEDLE_TELEMETRY"] = "0"
    os.environ["DO_NOT_TRACK"] = "1"

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .agent import WhistleAssistManager
from .const import DOMAIN

PLATFORMS: list[Platform] = [Platform.CONVERSATION, Platform.STT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Whistle Assist platforms."""
    manager = WhistleAssistManager(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = manager
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Whistle Assist platforms."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True
