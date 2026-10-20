# SPDX-License-Identifier: Apache-2.0
"""Constants for Whistle Assist."""

from typing import Final

DOMAIN: Final = "whistle_assist"
CONF_LANGUAGE: Final = "language"
CONF_CONFIDENCE_THRESHOLD: Final = "confidence_threshold"
DEFAULT_LANGUAGE: Final = "auto"
DEFAULT_CONFIDENCE_THRESHOLD: Final = 0.70
SUPPORTED_LANGUAGES: Final = ["en", "de", "fr", "es", "it", "nl", "pl"]

# Read-only status is available for exposed entities in these domains. Only the
# domains covered by the explicit tool definitions below can be controlled.
READABLE_DOMAINS: Final = {
    "light", "switch", "cover", "climate", "fan", "media_player", "scene",
    "script", "vacuum", "humidifier", "water_heater", "sensor", "binary_sensor",
    "person", "device_tracker", "weather", "lock", "alarm_control_panel",
    "input_boolean", "input_number", "input_select", "input_text", "number",
    "select", "siren", "button", "automation", "todo",
}
