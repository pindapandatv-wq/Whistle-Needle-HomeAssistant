# Whistle + Needle for Home Assistant (Whistle Assist)

[![Hassfest](https://github.com/pindapandatv-wq/Whistle-Needle-HomeAssistant/actions/workflows/validate.yaml/badge.svg)](https://github.com/pindapandatv-wq/Whistle-Needle-HomeAssistant/actions/workflows/validate.yaml)

An experimental Home Assistant custom integration connecting Cactus Compute's local Whistle speech recognition and Needle tool-calling model to Home Assistant Assist.

- **Whistle speech-to-text entity:** `Whistle`, selectable in an Assist pipeline.
- **Conversation agent:** `Whistle Assist`, which maps natural-language requests to a fixed set of Home Assistant tools.
- **Entity-aware:** discovers live entities exposed to Home Assistant's `conversation` assistant, with friendly names and area context.
- **Constrained control:** uses explicit per-domain action schemas and validates targets and values again before making Home Assistant service calls. It does not expose an arbitrary service-call tool.
- **Local inference:** speech recognition and tool selection run locally after model weights are available. First use may download model assets through the upstream Cactus package.
- **Privacy default:** Needle telemetry is opted out by default with `NEEDLE_TELEMETRY=0` and `DO_NOT_TRACK=1` unless either variable is explicitly configured by the Home Assistant operator. See [Telemetry](#telemetry).

> **Experimental software.** This integration has not been verified against a live Home Assistant installation as part of this repository preparation. Review the security notes, back up Home Assistant, and test on a non-critical installation before allowing voice-driven device control.

## Features

| Domain | Supported operations |
| --- | --- |
| Lights | On/off/toggle, brightness, white colour temperature, area-based light control |
| Switches and input booleans | On/off/toggle |
| Covers | Open/close/stop/set position |
| Climate | On/off, target temperature, supported HVAC mode |
| Fans | On/off/toggle/set percentage |
| Media players | On/off, play/pause/stop, volume, mute |
| Vacuums | Start/pause/stop/return to base/locate |
| Humidifiers and water heaters | Supported on/off, temperature, humidity and mode actions |
| Helpers | Set numeric, select and text helper values |
| Scenes and scripts | Activate scene; scripts always require a separate confirmation |
| Read-only status | State and selected attributes for exposed sensors, binary sensors, and other supported entities |

Locks, alarm panels, sirens, buttons, automations, and other potentially sensitive or unsupported entities are not given actuation tools in this version. If an entity is not exposed to the `conversation` assistant in Home Assistant, it is not available to Whistle Assist.

## Installation

### HACS custom repository

This repository is not automatically included in the HACS default catalog. Once published to GitHub:

1. Open **HACS → Integrations → ⋮ → Custom repositories**.
2. Add `https://github.com/pindapandatv-wq/Whistle-Needle-HomeAssistant` and choose **Integration**.
3. Install **Whistle Assist**, then restart Home Assistant.

### Manual installation

1. Back up your Home Assistant configuration.
2. Copy `custom_components/whistle_assist/` from this repository into `<config>/custom_components/whistle_assist/`.
3. Restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration**, and add **Whistle Assist**.
5. Set a language (or automatic detection) and the confidence threshold in the integration configuration.
6. Go to **Settings → Voice assistants** and select `Whistle` as the speech-to-text engine and `Whistle Assist` as the conversation agent. Choose a text-to-speech engine separately if you want spoken output.
7. In Home Assistant's voice-assistant entity exposure settings, expose only the entities that you intend Whistle Assist to read/control.

The Home Assistant manifest pins `cactus-needle==3.2.8`. Home Assistant should install that Python dependency during setup; it is not bundled into the repository ZIP.

## Models and network access

Model weights are not included in this repository. The upstream `cactus-needle` package fetches and caches the relevant model assets as needed. Allow outbound network access on first use and make sure the Home Assistant host has enough disk space. Later requests should reuse the cached models. Exact paths, cache lifecycle, and architecture support are controlled by the upstream package and can change by version.

### Telemetry

Upstream Needle documentation says anonymous usage telemetry is enabled by default and documents `NEEDLE_TELEMETRY=0` or `DO_NOT_TRACK=1` to opt out. When neither `NEEDLE_TELEMETRY` nor `DO_NOT_TRACK` is already set in the Home Assistant process environment, this integration sets `NEEDLE_TELEMETRY=0` and `DO_NOT_TRACK=1` before importing/using Needle. If either variable is already configured, the integration respects that explicit environment configuration. These are process-wide environment variables, not per-integration settings. Review the upstream documentation before changing them.

No transcript, device state or command is intentionally sent by this adapter to a remote conversation service. The upstream package's own network/model-download/telemetry behavior is separate; see its documentation and license notices.

## Safety and known limitations

- Expose entities deliberately. The agent only considers entities exposed to Home Assistant Assist and re-checks exposure before execution.
- The tool definitions use an explicit action allowlist. Argument values, domains, current options/modes, and numeric ranges are validated before a service call.
- Low-confidence or unavailable-confidence mutating requests require a separate confirmation. Script execution always requires confirmation. Pending confirmations expire after 60 seconds.
- A successful service call means Home Assistant accepted the request; it does not prove the physical device completed the action.
- Needle is optimized for structured tool calling, not general-purpose conversation. It can fail to map ambiguous requests; say the room and device name.
- This build advertises 16 kHz mono PCM/WAV input. Whistle's advertised languages are English, German, French, Spanish, Italian, Dutch, and Polish.
- API compatibility depends on the Home Assistant version and `cactus-needle` runtime. Test the STT and conversation pipeline after upgrades.

**Do not use voice control as the only safety mechanism** for locks, access control, fire/security systems, heaters, or any other hazardous equipment.

## Development and checks

Run the repository checks locally:

```sh
python scripts/validate_repo.py
python -m compileall -q custom_components/whistle_assist
```

GitHub Actions runs the local contract checks, Home Assistant Hassfest validation, and HACS integration validation on pushes and pull requests. These checks validate repository structure and metadata; they are not a substitute for testing with a live Home Assistant instance and actual devices.

## Attribution and licensing

This integration is an independent community project; it is not an official Home Assistant or Cactus Compute release. It depends on `cactus-needle==3.2.8`; the upstream Python package declares Apache-2.0. The dependency is installed separately by Home Assistant; neither its source nor model weights are vendored in this repository. Model files fetched at runtime are not redistributed or relicensed by this project, and their applicable terms must be checked upstream before you redistribute those files. See [`NOTICE`](NOTICE) for references and the recommended Needle 3 citation, and [`LICENSE`](LICENSE) for this repository's license.

- Whistle overview: <https://cactuscompute.com/blog/whistle>
- Cactus Needle source, documentation, license, and release history: <https://github.com/cactus-compute/needle>
- Exact PyPI dependency release: <https://pypi.org/project/cactus-needle/3.2.8/>
- Home Assistant custom integration manifest: <https://developers.home-assistant.io/docs/creating_integration_manifest>
- HACS publishing requirements: <https://hacs.xyz/docs/publish/start/>

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for development checks and change expectations. Please report integration bugs through the repository's GitHub Issues page once published.
