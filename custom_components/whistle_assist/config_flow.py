# SPDX-License-Identifier: Apache-2.0
"""Config flow for Whistle Assist."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_CONFIDENCE_THRESHOLD,
    CONF_LANGUAGE,
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_LANGUAGE,
    DOMAIN,
)

LANGUAGE_OPTIONS = {
    "auto": "Automatic language detection",
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "nl": "Dutch",
    "pl": "Polish",
}


class CactusAssistConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up Whistle Assist."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Configure the model and confidence threshold."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Whistle Assist",
                data={
                    CONF_LANGUAGE: user_input[CONF_LANGUAGE],
                    CONF_CONFIDENCE_THRESHOLD: user_input[CONF_CONFIDENCE_THRESHOLD],
                },
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_LANGUAGE, default=DEFAULT_LANGUAGE): vol.In(LANGUAGE_OPTIONS),
                vol.Required(
                    CONF_CONFIDENCE_THRESHOLD,
                    default=DEFAULT_CONFIDENCE_THRESHOLD,
                ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return CactusAssistOptionsFlow(config_entry)


class CactusAssistOptionsFlow(config_entries.OptionsFlow):
    """Options for Whistle Assist."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Update language and confidence threshold."""
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_LANGUAGE,
                    default=current.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
                ): vol.In(LANGUAGE_OPTIONS),
                vol.Required(
                    CONF_CONFIDENCE_THRESHOLD,
                    default=current.get(
                        CONF_CONFIDENCE_THRESHOLD, DEFAULT_CONFIDENCE_THRESHOLD
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
