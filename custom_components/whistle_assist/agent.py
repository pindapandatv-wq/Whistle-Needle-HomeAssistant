# SPDX-License-Identifier: Apache-2.0
"""Needle tool orchestration and guarded Home Assistant service calls."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import tempfile
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_CONFIDENCE_THRESHOLD,
    DEFAULT_CONFIDENCE_THRESHOLD,
    READABLE_DOMAINS,
)

_LOGGER = logging.getLogger(__name__)
EXPOSED_ASSISTANT = "conversation"


def _param(
    type_name: str,
    description: str,
    *,
    required: bool = False,
    enum: list[str] | None = None,
    minimum: int | float | None = None,
    maximum: int | float | None = None,
) -> dict[str, Any]:
    """Make a Needle parameter definition."""
    result: dict[str, Any] = {"type": type_name, "description": description}
    if required:
        result["required"] = True
    if enum is not None:
        result["enum"] = enum
    if minimum is not None:
        result["minimum"] = minimum
    if maximum is not None:
        result["maximum"] = maximum
    return result


def _tool(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """Convert concise parameter declarations to Needle's JSON Schema shape."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter_name, declaration in parameters.items():
        property_schema = dict(declaration)
        if property_schema.pop("required", False):
            required.append(parameter_name)
        properties[parameter_name] = property_schema

    parameter_schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        parameter_schema["required"] = required

    return {
        "name": name,
        "description": description,
        "parameters": parameter_schema,
    }


def _ids(records: dict[str, dict[str, Any]], domains: set[str] | tuple[str, ...] | list[str]) -> list[str]:
    return sorted(eid for eid, record in records.items() if record["domain"] in domains)


def _named_targets(records: dict[str, dict[str, Any]], ids: list[str]) -> str:
    """Describe entity IDs in language a small tool-calling model can match."""
    labels = []
    # Keep the schema compact on installations with many entities. The enum
    # still includes every entity; this is only the explanatory name list.
    for entity_id in ids[:140]:
        rec = records[entity_id]
        label = f"{rec['name']} [{entity_id}]"
        if rec.get("area"):
            label += f" in {rec['area']}"
        labels.append(label)
    if len(ids) > 140:
        labels.append(f"and {len(ids) - 140} additional entity IDs (available in the enum)")
    return "; ".join(labels) if labels else "none"


def build_tool_schemas(records: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Build tightly scoped function tools from currently exposed entities."""
    schemas: list[dict[str, Any]] = []
    all_ids = sorted(records)
    if all_ids:
        schemas.append(
            _tool(
                "get_entity_state",
                "Read the current state of one exposed Home Assistant entity. Use this to answer status, temperature, humidity, open/closed, battery, or similar questions. Select an entity by its ID; names and areas: "
                + _named_targets(records, all_ids),
                {
                    "entity_id": _param(
                        "string", "Entity ID to inspect.", required=True, enum=all_ids
                    )
                },
            )
        )

    lights = _ids(records, ["light"])
    if lights:
        light_areas = sorted({records[entity_id]["area"] for entity_id in lights if records[entity_id].get("area")})
        area_choices = [*light_areas, "all exposed lights"]
        schemas.append(
            _tool(
                "control_lights_in_area",
                "Control every exposed light in one Home Assistant area, or all exposed lights if the user says all/everywhere. Only entities exposed to the conversation assistant are affected. Available areas: "
                + "; ".join(light_areas or ["no named areas; all exposed lights is still available"]),
                {
                    "area": _param("string", "Choose the exact area name, or 'all exposed lights' for all exposed lights.", required=True, enum=area_choices),
                    "action": _param("string", "Requested light action.", required=True, enum=["turn_on", "turn_off", "toggle"]),
                    "brightness_pct": _param("integer", "Optional brightness percentage for turn_on.", minimum=1, maximum=100),
                },
            )
        )
        schemas.append(
            _tool(
                "control_light",
                "Control a light. Choose turn_on, turn_off, or toggle. Optional brightness_pct is 1-100; optional color_temp_kelvin sets white colour temperature. Available lights: "
                + _named_targets(records, lights),
                {
                    "entity_id": _param("string", "Target light entity ID.", required=True, enum=lights),
                    "action": _param("string", "Requested light action.", required=True, enum=["turn_on", "turn_off", "toggle"]),
                    "brightness_pct": _param("integer", "Optional brightness percentage for turn_on.", minimum=1, maximum=100),
                    "color_temp_kelvin": _param("integer", "Optional white color temperature in kelvin.", minimum=1500, maximum=10000),
                },
            )
        )

    switches = _ids(records, ["switch", "input_boolean"])
    if switches:
        schemas.append(
            _tool(
                "control_switch",
                "Turn an exposed switch or input boolean on, off, or toggle it. Available entities: "
                + _named_targets(records, switches),
                {
                    "entity_id": _param("string", "Target switch entity ID.", required=True, enum=switches),
                    "action": _param("string", "Requested switch action.", required=True, enum=["turn_on", "turn_off", "toggle"]),
                },
            )
        )

    covers = _ids(records, ["cover"])
    if covers:
        schemas.append(
            _tool(
                "control_cover",
                "Open, close, stop, or set the position of an exposed cover, blind, or shutter. position_pct is 0-100. Available covers: "
                + _named_targets(records, covers),
                {
                    "entity_id": _param("string", "Target cover entity ID.", required=True, enum=covers),
                    "action": _param("string", "Requested cover action.", required=True, enum=["open_cover", "close_cover", "stop_cover", "set_cover_position"]),
                    "position_pct": _param("integer", "Required for set_cover_position; 0 is closed and 100 is open.", minimum=0, maximum=100),
                },
            )
        )

    climates = _ids(records, ["climate"])
    if climates:
        modes = sorted({str(mode) for entity_id in climates for mode in records[entity_id].get("hvac_modes", [])})
        schemas.append(
            _tool(
                "control_climate",
                "Control a thermostat or climate entity: turn_on, turn_off, set_temperature, or set_hvac_mode. A selected HVAC mode must be supported by the chosen entity. Available thermostats: "
                + _named_targets(records, climates),
                {
                    "entity_id": _param("string", "Target climate entity ID.", required=True, enum=climates),
                    "action": _param("string", "Requested climate action.", required=True, enum=["turn_on", "turn_off", "set_temperature", "set_hvac_mode"]),
                    "temperature": _param("number", "Target temperature in the unit used by this thermostat."),
                    "hvac_mode": _param("string", "HVAC mode, such as heat, cool, auto, or off.", enum=modes or None),
                },
            )
        )

    fans = _ids(records, ["fan"])
    if fans:
        schemas.append(
            _tool(
                "control_fan",
                "Turn a fan on/off/toggle or set its percentage speed. percentage is 0-100. Available fans: "
                + _named_targets(records, fans),
                {
                    "entity_id": _param("string", "Target fan entity ID.", required=True, enum=fans),
                    "action": _param("string", "Requested fan action.", required=True, enum=["turn_on", "turn_off", "toggle", "set_percentage"]),
                    "percentage": _param("integer", "Required for set_percentage.", minimum=0, maximum=100),
                },
            )
        )

    players = _ids(records, ["media_player"])
    if players:
        schemas.append(
            _tool(
                "control_media_player",
                "Control an exposed media player: turn on/off, play, pause, stop, set volume, or mute. volume_level is 0.0-1.0. Available media players: "
                + _named_targets(records, players),
                {
                    "entity_id": _param("string", "Target media player entity ID.", required=True, enum=players),
                    "action": _param("string", "Requested media action.", required=True, enum=["turn_on", "turn_off", "media_play", "media_pause", "media_stop", "volume_set", "volume_mute"]),
                    "volume_level": _param("number", "Volume from 0.0 to 1.0 for volume_set.", minimum=0.0, maximum=1.0),
                    "is_volume_muted": _param("boolean", "Set true to mute or false to unmute for volume_mute."),
                },
            )
        )

    vacuums = _ids(records, ["vacuum"])
    if vacuums:
        schemas.append(
            _tool(
                "control_vacuum",
                "Control an exposed robot vacuum: start, pause, stop, return_to_base, or locate. Available vacuums: "
                + _named_targets(records, vacuums),
                {
                    "entity_id": _param("string", "Target vacuum entity ID.", required=True, enum=vacuums),
                    "action": _param("string", "Requested vacuum action.", required=True, enum=["start", "pause", "stop", "return_to_base", "locate"]),
                },
            )
        )

    humidifiers = _ids(records, ["humidifier"])
    if humidifiers:
        modes = sorted({str(mode) for eid in humidifiers for mode in records[eid].get("modes", [])})
        schemas.append(
            _tool(
                "control_humidifier",
                "Control an exposed humidifier: turn_on/off, set_humidity (0-100 percent), or set_mode. Available humidifiers: "
                + _named_targets(records, humidifiers),
                {
                    "entity_id": _param("string", "Target humidifier entity ID.", required=True, enum=humidifiers),
                    "action": _param("string", "Requested humidifier action.", required=True, enum=["turn_on", "turn_off", "set_humidity", "set_mode"]),
                    "humidity": _param("integer", "Target relative humidity percentage.", minimum=0, maximum=100),
                    "mode": _param("string", "A mode supported by this humidifier.", enum=modes or None),
                },
            )
        )

    heaters = _ids(records, ["water_heater"])
    if heaters:
        modes = sorted({str(mode) for eid in heaters for mode in records[eid].get("operation_list", [])})
        schemas.append(
            _tool(
                "control_water_heater",
                "Control an exposed water heater: turn_on/off, set_temperature, or set_operation_mode. Available water heaters: "
                + _named_targets(records, heaters),
                {
                    "entity_id": _param("string", "Target water heater entity ID.", required=True, enum=heaters),
                    "action": _param("string", "Requested water-heater action.", required=True, enum=["turn_on", "turn_off", "set_temperature", "set_operation_mode"]),
                    "temperature": _param("number", "Target temperature."),
                    "operation_mode": _param("string", "A supported water-heater operation mode.", enum=modes or None),
                },
            )
        )

    numeric = _ids(records, ["input_number", "number"])
    if numeric:
        schemas.append(
            _tool(
                "set_numeric_helper",
                "Set an exposed input_number or number entity to a numeric value. Available numeric entities: "
                + _named_targets(records, numeric),
                {
                    "entity_id": _param("string", "Target numeric entity ID.", required=True, enum=numeric),
                    "value": _param("number", "The numeric value to set.", required=True),
                },
            )
        )

    selects = _ids(records, ["input_select", "select"])
    if selects:
        schemas.append(
            _tool(
                "set_option_helper",
                "Select an option for an exposed input_select or select entity. The option must be one of the target entity's current options. Available entities: "
                + _named_targets(records, selects),
                {
                    "entity_id": _param("string", "Target select entity ID.", required=True, enum=selects),
                    "option": _param("string", "Exact option to select.", required=True),
                },
            )
        )

    texts = _ids(records, ["input_text"])
    if texts:
        schemas.append(
            _tool(
                "set_text_helper",
                "Set the value of an exposed input_text helper. Available text entities: "
                + _named_targets(records, texts),
                {
                    "entity_id": _param("string", "Target input_text entity ID.", required=True, enum=texts),
                    "value": _param("string", "Text to store.", required=True),
                },
            )
        )

    scenes = _ids(records, ["scene"])
    if scenes:
        schemas.append(
            _tool(
                "activate_scene",
                "Activate an exposed Home Assistant scene. Available scenes: " + _named_targets(records, scenes),
                {"entity_id": _param("string", "Scene to activate.", required=True, enum=scenes)},
            )
        )

    scripts = _ids(records, ["script"])
    if scripts:
        schemas.append(
            _tool(
                "run_script",
                "Run an exposed Home Assistant script. Scripts can trigger complex automations; this action always requires an explicit confirmation. Available scripts: "
                + _named_targets(records, scripts),
                {"entity_id": _param("string", "Script entity to run.", required=True, enum=scripts)},
            )
        )
    return schemas


class WhistleAssistManager:
    """Lazy model manager shared by the conversation and STT platforms."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._agent: Any | None = None
        self._schema_signature: str | None = None
        self._model_lock = asyncio.Lock()
        self._pending: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    @property
    def language(self) -> str:
        return str(self.entry.options.get("language", self.entry.data.get("language", "auto")))

    @property
    def confidence_threshold(self) -> float:
        value = self.entry.options.get(
            CONF_CONFIDENCE_THRESHOLD,
            self.entry.data.get(CONF_CONFIDENCE_THRESHOLD, DEFAULT_CONFIDENCE_THRESHOLD),
        )
        try:
            return min(1.0, max(0.0, float(value)))
        except (TypeError, ValueError):
            return DEFAULT_CONFIDENCE_THRESHOLD

    def _area_for(self, entity_id: str, registry_entry: Any) -> str | None:
        area_id = getattr(registry_entry, "area_id", None) if registry_entry else None
        if not area_id and registry_entry and registry_entry.device_id:
            device = dr.async_get(self.hass).async_get(registry_entry.device_id)
            area_id = device.area_id if device else None
        if not area_id:
            return None
        area = ar.async_get(self.hass).async_get_area(area_id)
        return area.name if area else None

    def exposed_records(self) -> dict[str, dict[str, Any]]:
        """Return only live entities exposed to Home Assistant Assist."""
        try:
            from homeassistant.components.homeassistant.exposed_entities import (
                async_should_expose,
            )
        except ImportError:
            _LOGGER.error("Home Assistant exposed-entity API is unavailable")
            return {}

        entity_registry = er.async_get(self.hass)
        records: dict[str, dict[str, Any]] = {}
        for state in self.hass.states.async_all():
            domain = state.entity_id.split(".", 1)[0]
            if domain not in READABLE_DOMAINS:
                continue
            try:
                if not async_should_expose(self.hass, EXPOSED_ASSISTANT, state.entity_id):
                    continue
            except (KeyError, HomeAssistantError):
                continue
            registry_entry = entity_registry.async_get(state.entity_id)
            attrs = state.attributes
            records[state.entity_id] = {
                "entity_id": state.entity_id,
                "domain": domain,
                "name": str(attrs.get("friendly_name", state.entity_id)),
                "area": self._area_for(state.entity_id, registry_entry),
                "state": state.state,
                "attributes": dict(attrs),
                "hvac_modes": list(attrs.get("hvac_modes", [])),
                "modes": list(attrs.get("available_modes", attrs.get("modes", []))),
                "operation_list": list(attrs.get("operation_list", [])),
            }
        return records

    async def _get_agent(self, schemas: list[dict[str, Any]]) -> Any:
        """Create or reuse a Needle agent when the exposed tool set changes."""
        signature = json.dumps(schemas, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if self._agent is None or signature != self._schema_signature:
            def create_agent():
                import needle

                return needle.Needle(tools=schemas)

            self._agent = await self.hass.async_add_executor_job(create_agent)
            self._schema_signature = signature
        else:
            await self.hass.async_add_executor_job(self._agent.reset)
        return self._agent

    async def interpret(self, text: str, session_id: str) -> str:
        """Interpret text, optionally ask for confirmation, then run safe tools."""
        text = text.strip()
        if not text:
            return "I didn't hear a command. Please try again."

        async with self._model_lock:
            now = time.monotonic()
            pending = self._pending.get(session_id)
            if pending and pending[0] < now:
                self._pending.pop(session_id, None)
                pending = None

            lowered = text.casefold().strip(" .!?,")
            if pending and lowered in {"yes", "confirm", "confirmed", "do it", "go ahead", "execute", "ja", "bevestig", "voer uit", "ok", "okay"}:
                self._pending.pop(session_id, None)
                records = self.exposed_records()
                results = []
                for call in pending[1]:
                    results.append(await self._execute_call(call, records))
                    records = self.exposed_records()
                return " ".join(results) if results else "Nothing was executed."
            if pending and lowered in {"no", "cancel", "stop", "nee", "annuleer", "cancel it"}:
                self._pending.pop(session_id, None)
                return "Cancelled. No device actions were executed."
            if pending:
                # A new request is not confirmation of the previous one.
                self._pending.pop(session_id, None)

            records = self.exposed_records()
            schemas = build_tool_schemas(records)
            if not schemas:
                return (
                    "No entities exposed to Home Assistant Assist were found. Expose the devices you want to control in Home Assistant's voice-assistant entity settings, then try again."
                )

            try:
                agent = await self._get_agent(schemas)
                response = await self.hass.async_add_executor_job(agent.complete, text)
                if not isinstance(response, dict):
                    _LOGGER.error("Needle returned an invalid response type: %s", type(response).__name__)
                    return "Whistle Assist received an invalid response from Needle. Check the Home Assistant log."
            except Exception as err:  # model/runtime errors should not break Assist
                _LOGGER.exception("Needle inference failed")
                return f"Whistle Assist couldn't load or run the local Needle model: {err.__class__.__name__}. Check the Home Assistant log."

            calls = response.get("function_calls") or []
            suppressed = response.get("suppressed_calls") or []
            if not calls:
                if suppressed:
                    return "I wasn't confident enough to choose a Home Assistant action. Please repeat the request with the room or device name."
                return "I couldn't map that request to a supported action or an exposed Home Assistant entity."

            confidence = response.get("confidence")
            mutating_calls = [call for call in calls if call.get("name") != "get_entity_state"]
            need_confirmation = bool(mutating_calls) and (
                confidence is None
                or not isinstance(confidence, (int, float))
                or float(confidence) < self.confidence_threshold
                or any(call.get("name") == "run_script" for call in mutating_calls)
            )
            if need_confirmation:
                summaries = [self._describe_call(call, records) for call in calls]
                self._pending[session_id] = (time.monotonic() + 60.0, copy.deepcopy(calls))
                if isinstance(confidence, (int, float)):
                    score = f"confidence {float(confidence):.0%}"
                else:
                    score = "confidence unavailable"
                return (
                    "I have not changed anything. I interpreted that as: "
                    + "; ".join(summaries)
                    + f" ({score}). Say 'confirm' within 60 seconds to execute, or 'cancel' to discard."
                )

            results = []
            for call in calls:
                results.append(await self._execute_call(call, records))
                records = self.exposed_records()
            return " ".join(results) if results else "No action was executed."

    def _describe_call(self, call: dict[str, Any], records: dict[str, dict[str, Any]]) -> str:
        """Create a human-readable summary for the confirmation prompt."""
        name = call.get("name", "unknown action")
        args = call.get("arguments") or {}
        entity_id = args.get("entity_id", "")
        if name == "control_lights_in_area":
            label = f"lights in {args.get('area', 'the selected area')}"
        else:
            label = records.get(entity_id, {}).get("name", entity_id or "unknown entity")
        action = args.get("action", name)
        details = []
        for key in ("brightness_pct", "color_temp_kelvin", "position_pct", "temperature", "hvac_mode", "percentage", "volume_level", "humidity", "mode", "operation_mode", "value", "option"):
            if key in args:
                details.append(f"{key.replace('_', ' ')} {args[key]}")
        suffix = f" ({', '.join(details)})" if details else ""
        return f"{action} {label}{suffix}"

    def _is_exposed(self, entity_id: str, records: dict[str, dict[str, Any]]) -> bool:
        return entity_id in records

    async def _execute_call(self, call: dict[str, Any], records: dict[str, dict[str, Any]]) -> str:
        """Validate and execute exactly one whitelisted tool call."""
        name = call.get("name")
        args = call.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                return "I couldn't understand the device-action arguments. Nothing was changed."
        if not isinstance(args, dict):
            return "The requested action had invalid arguments. Nothing was changed."

        if name == "get_entity_state":
            entity_id = args.get("entity_id")
            state = self.hass.states.get(entity_id) if isinstance(entity_id, str) else None
            if not state or not self._is_exposed(entity_id, records):
                return "That entity is no longer available to Assist."
            return self._format_state(state)

        if name == "control_lights_in_area":
            area = args.get("area")
            action = args.get("action")
            if not isinstance(area, str) or action not in {"turn_on", "turn_off", "toggle"}:
                return "I refused an invalid area-light action. No change was made."
            targets = [
                entity_id for entity_id, record in records.items()
                if record["domain"] == "light"
                and (area == "all exposed lights" or record.get("area") == area)
            ]
            if not targets:
                return f"No exposed lights were found for {area}. No change was made."
            service_data: dict[str, Any] = {"entity_id": targets}
            if action == "turn_on" and "brightness_pct" in args:
                try:
                    service_data["brightness_pct"] = self._bounded_number(args["brightness_pct"], 1, 100)
                except (ValueError, TypeError):
                    return "The requested brightness percentage was invalid. Nothing was changed."
            if not self.hass.services.has_service("light", action):
                return "Home Assistant does not currently provide that light service. No change was made."
            try:
                await self.hass.services.async_call("light", action, service_data, blocking=True)
            except (HomeAssistantError, ServiceNotFound):
                _LOGGER.exception("Home Assistant rejected an area light action")
                return "Home Assistant could not complete the area-light action."
            if area == "all exposed lights":
                return f"{action.replace('_', ' ')} completed for {len(targets)} exposed lights."
            return f"{action.replace('_', ' ')} completed for {len(targets)} exposed lights in {area}."

        entity_id = args.get("entity_id")
        if not isinstance(entity_id, str) or not self._is_exposed(entity_id, records):
            return "I refused an action because the target is not currently exposed to Assist. No change was made."
        state = self.hass.states.get(entity_id)
        if state is None:
            return f"{entity_id} is no longer available."
        domain = entity_id.split(".", 1)[0]
        action = args.get("action")
        service_domain = domain
        service: str | None = None
        service_data: dict[str, Any] = {"entity_id": entity_id}

        try:
            if name == "control_light" and domain == "light" and action in {"turn_on", "turn_off", "toggle"}:
                service = action
                if action == "turn_on":
                    if "brightness_pct" in args:
                        service_data["brightness_pct"] = self._bounded_number(args["brightness_pct"], 1, 100)
                    if "color_temp_kelvin" in args:
                        color_temp = self._bounded_number(args["color_temp_kelvin"], 1500, 10000)
                        if not state.attributes.get("max_color_temp_kelvin") and "color_temp" not in state.attributes.get("supported_color_modes", []):
                            return f"{state.attributes.get('friendly_name', entity_id)} does not expose white color temperature control. Nothing was changed."
                        device_min = state.attributes.get("min_color_temp_kelvin", 1500)
                        device_max = state.attributes.get("max_color_temp_kelvin", 10000)
                        if color_temp < device_min or color_temp > device_max:
                            return f"That color temperature is outside the supported range for {state.attributes.get('friendly_name', entity_id)}. Nothing was changed."
                        service_data["color_temp_kelvin"] = color_temp
            elif name == "control_switch" and domain in {"switch", "input_boolean"} and action in {"turn_on", "turn_off", "toggle"}:
                service = action
            elif name == "control_cover" and domain == "cover" and action in {"open_cover", "close_cover", "stop_cover", "set_cover_position"}:
                service = action
                if action == "set_cover_position":
                    if "position_pct" not in args:
                        return "A position percentage is required. Nothing was changed."
                    service_data["position"] = self._bounded_number(args["position_pct"], 0, 100)
            elif name == "control_climate" and domain == "climate" and action in {"turn_on", "turn_off", "set_temperature", "set_hvac_mode"}:
                service = action
                if action == "set_temperature":
                    if "temperature" not in args:
                        return "A target temperature is required. Nothing was changed."
                    service_data["temperature"] = self._bounded_number(args["temperature"], -50, 100)
                if action == "set_hvac_mode":
                    mode = args.get("hvac_mode")
                    if not isinstance(mode, str) or mode not in state.attributes.get("hvac_modes", []):
                        return f"That HVAC mode is not supported by {state.attributes.get('friendly_name', entity_id)}. Nothing was changed."
                    service_data["hvac_mode"] = mode
            elif name == "control_fan" and domain == "fan" and action in {"turn_on", "turn_off", "toggle", "set_percentage"}:
                service = action
                if action == "set_percentage":
                    if "percentage" not in args:
                        return "A fan percentage is required. Nothing was changed."
                    service_data["percentage"] = self._bounded_number(args["percentage"], 0, 100)
            elif name == "control_media_player" and domain == "media_player" and action in {"turn_on", "turn_off", "media_play", "media_pause", "media_stop", "volume_set", "volume_mute"}:
                service = action
                if action == "volume_set":
                    if "volume_level" not in args:
                        return "A volume level is required. Nothing was changed."
                    service_data["volume_level"] = self._bounded_number(args["volume_level"], 0, 1)
                if action == "volume_mute":
                    if not isinstance(args.get("is_volume_muted"), bool):
                        return "Specify whether to mute or unmute. Nothing was changed."
                    service_data["is_volume_muted"] = args["is_volume_muted"]
            elif name == "control_vacuum" and domain == "vacuum" and action in {"start", "pause", "stop", "return_to_base", "locate"}:
                service = action
            elif name == "control_humidifier" and domain == "humidifier" and action in {"turn_on", "turn_off", "set_humidity", "set_mode"}:
                service = action
                if action == "set_humidity":
                    if "humidity" not in args:
                        return "A target humidity is required. Nothing was changed."
                    service_data["humidity"] = self._bounded_number(args["humidity"], 0, 100)
                if action == "set_mode":
                    mode = args.get("mode")
                    supported = state.attributes.get("available_modes", state.attributes.get("modes", []))
                    if not isinstance(mode, str) or (supported and mode not in supported):
                        return "That humidifier mode is not supported. Nothing was changed."
                    service_data["mode"] = mode
            elif name == "control_water_heater" and domain == "water_heater" and action in {"turn_on", "turn_off", "set_temperature", "set_operation_mode"}:
                service = action
                if action == "set_temperature":
                    if "temperature" not in args:
                        return "A target temperature is required. Nothing was changed."
                    service_data["temperature"] = self._bounded_number(args["temperature"], -10, 100)
                if action == "set_operation_mode":
                    mode = args.get("operation_mode")
                    supported = state.attributes.get("operation_list", [])
                    if not isinstance(mode, str) or (supported and mode not in supported):
                        return "That water-heater operation mode is not supported. Nothing was changed."
                    service_data["operation_mode"] = mode
            elif name == "set_numeric_helper" and domain in {"input_number", "number"}:
                service = "set_value"
                numeric_value = self._bounded_number(args.get("value"), -1_000_000, 1_000_000)
                entity_min = state.attributes.get("min")
                entity_max = state.attributes.get("max")
                if entity_min is not None and numeric_value < entity_min:
                    return f"That value is below the minimum for {state.attributes.get('friendly_name', entity_id)}. Nothing was changed."
                if entity_max is not None and numeric_value > entity_max:
                    return f"That value is above the maximum for {state.attributes.get('friendly_name', entity_id)}. Nothing was changed."
                service_data["value"] = numeric_value
            elif name == "set_option_helper" and domain in {"input_select", "select"}:
                option = args.get("option")
                if not isinstance(option, str):
                    return "A select option is required. Nothing was changed."
                options = state.attributes.get("options", [])
                if option not in options:
                    return f"'{option}' is not an available option for {state.attributes.get('friendly_name', entity_id)}. Nothing was changed."
                service = "select_option"
                service_data["option"] = option
            elif name == "set_text_helper" and domain == "input_text":
                value = args.get("value")
                if not isinstance(value, str):
                    return "Text value is required. Nothing was changed."
                if len(value) > 255:
                    return "That text is too long for a helper value. Nothing was changed."
                service = "set_value"
                service_data["value"] = value
            elif name == "activate_scene" and domain == "scene":
                service_domain, service = "scene", "turn_on"
            elif name == "run_script" and domain == "script":
                service_domain, service = "script", "turn_on"
            else:
                return "I refused an unsupported entity/action combination. No change was made."

            if not service or not self.hass.services.has_service(service_domain, service):
                return f"Home Assistant does not currently provide the service for {entity_id}. No change was made."
            await self.hass.services.async_call(service_domain, service, service_data, blocking=True)
            friendly_name = state.attributes.get("friendly_name", entity_id)
            return self._success_message(name, action, friendly_name, args)
        except (ValueError, TypeError) as err:
            _LOGGER.debug("Invalid Needle arguments for %s: %s", name, err)
            return "The requested value was invalid. Nothing was changed."
        except (HomeAssistantError, ServiceNotFound):
            _LOGGER.exception("Home Assistant rejected Whistle Assist action %s", name)
            return f"Home Assistant could not complete the requested action for {state.attributes.get('friendly_name', entity_id)}."
        except Exception:
            _LOGGER.exception("Unexpected error executing Whistle Assist tool %s", name)
            return f"An unexpected error occurred while controlling {state.attributes.get('friendly_name', entity_id)}."

    @staticmethod
    def _bounded_number(value: Any, minimum: float, maximum: float) -> float:
        """Require a finite numeric value within allowed bounds."""
        import math

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("expected number")
        number = float(value)
        if not math.isfinite(number) or number < minimum or number > maximum:
            raise ValueError("out of bounds")
        return int(number) if number.is_integer() else number

    @staticmethod
    def _format_state(state: State) -> str:
        """Summarize a state and the attributes most useful for a voice reply."""
        attrs = state.attributes
        name = attrs.get("friendly_name", state.entity_id)
        domain = state.entity_id.split(".", 1)[0]
        value = state.state
        device_class = attrs.get("device_class")
        if domain == "binary_sensor":
            if value == "on":
                value = {
                    "door": "open", "garage_door": "open", "opening": "open",
                    "window": "open", "motion": "detected", "presence": "detected",
                    "occupancy": "detected", "moisture": "wet", "problem": "detected",
                }.get(device_class, "on")
            elif value == "off":
                value = {
                    "door": "closed", "garage_door": "closed", "opening": "closed",
                    "window": "closed", "motion": "not detected", "presence": "not detected",
                    "occupancy": "not detected", "moisture": "dry", "problem": "not detected",
                }.get(device_class, "off")
        pieces = [f"{name} is {value}"]
        unit = attrs.get("unit_of_measurement")
        if unit and domain in {"sensor", "number", "input_number"}:
            pieces[-1] += f" {unit}"
        for key, label in (
            ("current_temperature", "current temperature"),
            ("temperature", "target temperature"),
            ("current_humidity", "current humidity"),
            ("humidity", "target humidity"),
            ("hvac_action", "HVAC action"),
            ("battery_level", "battery"),
            ("percentage", "fan speed"),
            ("volume_level", "volume"),
            ("source", "source"),
        ):
            val = attrs.get(key)
            if val is not None:
                pieces.append(f"{label} {val}")
        if domain == "light" and attrs.get("brightness") is not None:
            pieces.append(f"brightness about {round(float(attrs['brightness']) / 255 * 100)} percent")
        return ". ".join(pieces) + "."

    @staticmethod
    def _success_message(tool_name: str, action: str | None, friendly_name: str, args: dict[str, Any]) -> str:
        """Produce a terse response after the HA service call returns."""
        if tool_name == "get_entity_state":
            return f"Checked {friendly_name}."
        if tool_name == "control_light" and action == "turn_on" and "brightness_pct" in args:
            return f"Turned on {friendly_name} at {args['brightness_pct']} percent brightness."
        if tool_name == "control_cover" and action == "set_cover_position" and "position_pct" in args:
            return f"Set {friendly_name} to {args['position_pct']} percent open."
        if tool_name == "control_climate" and action == "set_temperature" and "temperature" in args:
            return f"Set {friendly_name} to {args['temperature']} degrees."
        if tool_name == "control_humidifier" and action == "set_humidity" and "humidity" in args:
            return f"Set {friendly_name} to {args['humidity']} percent humidity."
        if tool_name == "control_water_heater" and action == "set_temperature" and "temperature" in args:
            return f"Set {friendly_name} to {args['temperature']} degrees."
        if tool_name == "set_numeric_helper":
            return f"Set {friendly_name} to {args.get('value')}."
        if tool_name == "set_option_helper":
            return f"Set {friendly_name} to {args.get('option')}."
        if tool_name == "set_text_helper":
            return f"Updated {friendly_name}."
        if tool_name == "activate_scene":
            return f"Activated {friendly_name}."
        if tool_name == "run_script":
            return f"Ran {friendly_name}."
        friendly_action = {
            "turn_on": "Turned on", "turn_off": "Turned off", "toggle": "Toggled",
            "open_cover": "Opened", "close_cover": "Closed", "stop_cover": "Stopped",
            "set_hvac_mode": "Changed the mode of", "set_percentage": "Changed the speed of",
            "media_play": "Started playback on", "media_pause": "Paused", "media_stop": "Stopped playback on",
            "volume_set": "Changed the volume on", "volume_mute": "Updated mute on",
            "start": "Started", "pause": "Paused", "stop": "Stopped", "return_to_base": "Sent back to base",
            "locate": "Requested location from", "set_mode": "Changed the mode of", "set_operation_mode": "Changed the operation mode of",
        }.get(str(action), "Controlled")
        suffix = ""
        if action == "set_hvac_mode" and args.get("hvac_mode"):
            suffix = f" to {args['hvac_mode']} mode"
        elif action == "set_mode" and args.get("mode"):
            suffix = f" to {args['mode']} mode"
        elif action == "set_operation_mode" and args.get("operation_mode"):
            suffix = f" to {args['operation_mode']} mode"
        return f"{friendly_action} {friendly_name}{suffix}."


def _transcribe_file(audio: bytes, language: str | None) -> dict[str, Any]:
    """Run Whistle in a worker thread against a temporary WAV file."""
    import needle

    with tempfile.NamedTemporaryFile(prefix="cactus_whistle_", suffix=".wav") as wav_file:
        wav_file.write(audio)
        wav_file.flush()
        if language:
            return needle.transcribe(wav_file.name, language=language)
        return needle.transcribe(wav_file.name)


async def async_transcribe(hass: HomeAssistant, audio: bytes, language: str | None) -> str:
    """Transcribe bytes without blocking Home Assistant's event loop."""
    result = await hass.async_add_executor_job(_transcribe_file, audio, language)
    text = result.get("text", "") if isinstance(result, dict) else ""
    return str(text).strip()
