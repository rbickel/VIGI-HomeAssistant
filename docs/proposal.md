# VIGI NVR Home Assistant Integration Proposal

## Goal

Build a Home Assistant custom integration for TP-Link VIGI NVR OpenAPI. The first implementation exposes the API surface that is documented in the VIGI NVR Open API PDF and safe to model in Home Assistant: channels, device health, disk status, PoE status/control, audio mute controls, event server configuration visibility, and RTSP stream URLs.

## Current Finding On Alarm Control

The provided PDF does not document direct alarm arm, disarm, activate, or deactivate endpoints.

The alarm-related pieces it does document are observational/event-oriented:

- Event push configuration via `GET /openapi/event_server`, `POST /openapi/event_server/new_server`, and `POST /openapi/event_server/delete_server`.
- Event payload fields `alarm_output` and `alarm_input`.
- Event subtype `Alarm signal` under channel events.
- Device exception subtype `Alarm input`.

Because there is no documented arm/disarm command, this implementation intentionally does not register `alarm_control_panel`. Adding one now would create controls that do not map to verified NVR behavior. The event receiver is implemented so alarm-related pushes can be observed, while a second endpoint discovery pass can still look for newer/private VIGI alarm command APIs.

## Implemented Scope

### API Client

`custom_components/vigi_nvr/api.py` implements the documented endpoints:

- Token acquisition and refresh using the TP-Link SHA-256 Digest flow.
- Channel management: `GET /openapi/added_devices`.
- Video: resolution and bitrate get/set methods.
- Time: timing mode and NTP get/set methods.
- Audio: input/output sound get/set methods.
- Disk and SMART endpoints.
- PoE info, link mode, status, and link status endpoints.
- Event server get/add/delete endpoints.
- Recording calendar/search endpoints.
- System control endpoint.
- Documented RTSP live/replay URL helpers.

### Home Assistant Entities

Current platforms are `sensor`, `binary_sensor`, and `switch`.

Sensors:

- NVR channel count, disk count, event server count.
- Timing mode and NTP server.
- PoE total power and used power.
- Disk status, free space, and total space.
- Channel IP, MAC, audio volumes, stream resolutions, stream bitrates, and RTSP URLs.
- Event webhook URL, latest pushed event summary, and latest event received timestamp.

Binary sensors:

- Channel online state.
- PoE port linked state.
- Event server configured state.
- Latest pushed event alarm-related state.

Events:

- Incoming Home Assistant webhook pushes fire `vigi_nvr_event` on the event bus with parsed JSON/multipart event data, labels, source IP, and config entry ID.

Switches:

- Channel audio output mute.
- Channel audio input mute.
- Channel audio input noise cancelling.
- PoE port enable switch.

## Proposed Next Work

1. Run `scripts/discover_vigi_openapi.py` with credentials to probe the documented read-only endpoints on the actual NVR and save `docs/discovery/endpoint-probes.md`.
2. Install the custom component into a Home Assistant dev instance and add the integration through the config flow.
3. Verify which optional endpoints this NVR model supports. The coordinator already tolerates unsupported endpoints.
4. Configure the NVR event server to point at the Home Assistant `Event webhook URL` sensor attributes, then trigger motion/alarm/device events.
5. Convert repeated VIGI event messages into richer Home Assistant event entities/binary sensors for motion, human/vehicle, alarm signal, alarm input, video loss, and disk/device exceptions.
6. If a separate VIGI alarm-control endpoint is found, add `alarm_control_panel` only after confirming read state plus reversible commands.

## Fleet Split

The remaining work can be divided cleanly:

- Agent A: Home Assistant entity polish, config flow translations, diagnostics, and options flow.
- Agent B: Event receiver implementation and multipart parser for VIGI event push messages.
- Agent C: Endpoint validation against the physical NVR and model-specific capability notes.
- Agent D: Tests with mocked VIGI responses for auth, coordinator polling, and entity state.
