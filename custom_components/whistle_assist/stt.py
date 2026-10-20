# SPDX-License-Identifier: Apache-2.0
"""Home Assistant speech-to-text entity backed by Whistle."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable

from homeassistant.components.stt import (
    AudioBitRates,
    AudioChannels,
    AudioCodecs,
    AudioFormats,
    AudioSampleRates,
    SpeechMetadata,
    SpeechResult,
    SpeechResultState,
    SpeechToTextEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .agent import WhistleAssistManager, async_transcribe
from .const import DOMAIN, SUPPORTED_LANGUAGES

_LOGGER = logging.getLogger(__name__)
MAX_AUDIO_BYTES = 150 * 1024 * 1024


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    """Set up the Whistle STT entity."""
    manager: WhistleAssistManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WhistleSpeechToTextEntity(manager, entry)])


class WhistleSpeechToTextEntity(SpeechToTextEntity):
    """Transcribe 16 kHz mono WAV/PCM using Whistle locally."""

    _attr_name = "Whistle"

    def __init__(self, manager: WhistleAssistManager, entry: ConfigEntry) -> None:
        self.manager = manager
        self._attr_unique_id = f"{entry.entry_id}_stt"

    @property
    def supported_languages(self) -> list[str]:
        return SUPPORTED_LANGUAGES

    @property
    def supported_formats(self) -> list[AudioFormats]:
        return [AudioFormats.WAV]

    @property
    def supported_codecs(self) -> list[AudioCodecs]:
        return [AudioCodecs.PCM]

    @property
    def supported_bit_rates(self) -> list[AudioBitRates]:
        return [AudioBitRates.BITRATE_16]

    @property
    def supported_sample_rates(self) -> list[AudioSampleRates]:
        return [AudioSampleRates.SAMPLERATE_16000]

    @property
    def supported_channels(self) -> list[AudioChannels]:
        return [AudioChannels.CHANNEL_MONO]

    async def async_process_audio_stream(
        self, metadata: SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> SpeechResult:
        """Stream audio into memory and invoke Whistle off the event loop."""
        audio = bytearray()
        try:
            async for chunk in stream:
                audio.extend(chunk)
                if len(audio) > MAX_AUDIO_BYTES:
                    _LOGGER.error("Whistle input exceeded the %s MiB audio limit", MAX_AUDIO_BYTES // (1024 * 1024))
                    return SpeechResult(None, SpeechResultState.ERROR)

            if not audio:
                return SpeechResult(None, SpeechResultState.ERROR)

            configured_language = self.manager.language
            if configured_language != "auto":
                language = configured_language
            else:
                language = (metadata.language or "").lower().split("-", maxsplit=1)[0]
                if language not in SUPPORTED_LANGUAGES:
                    language = ""
            transcript = await async_transcribe(
                self.hass,
                bytes(audio),
                language or None,
                sample_rate=int(metadata.sample_rate),
                channels=int(metadata.channel),
                sample_width=int(metadata.bit_rate) // 8,
            )

            # Whistle intentionally returns an empty transcript for silence.
            return SpeechResult(
                transcript or None,
                SpeechResultState.SUCCESS,
            )
        except Exception:
            _LOGGER.exception("Whistle transcription failed")
            return SpeechResult(None, SpeechResultState.ERROR)
