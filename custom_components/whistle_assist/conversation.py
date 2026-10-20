# SPDX-License-Identifier: Apache-2.0
"""Home Assistant Assist conversation agent powered by Needle."""

from __future__ import annotations

import logging
import uuid

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent

from .agent import WhistleAssistManager
from .const import DOMAIN, SUPPORTED_LANGUAGES

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    """Set up the Whistle Assist conversation entity."""
    manager: WhistleAssistManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WhistleAssistConversationEntity(manager, entry)])


class WhistleAssistConversationEntity(conversation.ConversationEntity):
    """Conversation entity that maps natural language to safe HA service calls."""

    _attr_name = "Whistle Assist"

    def __init__(self, manager: WhistleAssistManager, entry: ConfigEntry) -> None:
        self.manager = manager
        self._attr_unique_id = f"{entry.entry_id}_conversation"

    @property
    def supported_languages(self) -> list[str]:
        """Return languages supported by Whistle/Needle."""
        return SUPPORTED_LANGUAGES

    async def async_process(self, user_input: conversation.ConversationInput) -> conversation.ConversationResult:
        """Process a sentence and return the action result as spoken text."""
        session_id = str(user_input.conversation_id or uuid.uuid4())
        try:
            speech = await self.manager.interpret(user_input.text, session_id)
        except Exception:  # Defensive guard for the Assist pipeline
            _LOGGER.exception("Unexpected Whistle Assist conversation failure")
            speech = "Whistle Assist encountered an error. Check the Home Assistant log."

        response = intent.IntentResponse(language=user_input.language or "en")
        response.async_set_speech(speech)
        return conversation.ConversationResult(
            response=response,
            conversation_id=session_id,
        )
