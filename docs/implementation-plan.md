# Implementation Plan

## Completed In This Pass

1. Replaced speculative OpenAPI discovery with a PDF-backed endpoint model.
2. Implemented the SHA-256 Digest authentication flow plus bearer token refresh handling.
3. Implemented typed API methods for every endpoint listed in the PDF.
4. Added a polling coordinator that fetches safe read-only state and tolerates model-specific unsupported endpoints.
5. Added Home Assistant entities for channels, disks, audio, PoE, NTP/timing, event-server visibility, and RTSP URLs.
6. Removed the placeholder `alarm_control_panel` because no documented alarm arm/disarm endpoint exists.
7. Updated discovery tooling to probe documented read-only endpoints and record mutating endpoints without calling them.
8. Added a standalone HTTP event capture server for VIGI push messages.
9. Added a Home Assistant webhook receiver for VIGI `event_message` pushes, plus last-event sensors and `vigi_nvr_event` bus events.
10. Added live camera entities for documented VIGI RTSP stream 1 and stream 2 URLs.

## Next Validation Steps

1. Run endpoint probing against the NVR:

   ```powershell
   $env:VIGI_HOST = "192.168.50.206"
   $env:VIGI_PORT = "20443"
   $env:VIGI_USERNAME = "admin"
   python scripts/discover_vigi_openapi.py
   ```

2. Review `docs/discovery/endpoint-probes.md` to see which endpoints are supported by the device and firmware.
3. Install the custom component in a Home Assistant development instance.
4. Add the integration through the UI and verify the created entities.
5. Configure the NVR event server to point at the Home Assistant `Event webhook URL` sensor attributes and collect sample motion/alarm/device events.
6. Use `scripts/capture_vigi_events.py` only when raw payload files or image-part captures are needed outside Home Assistant.

## Fleet Dispatch Candidates

### Endpoint Validation Agent

Run the endpoint probe, inspect response schemas, and update the catalog with model/firmware support notes.

### Event Receiver Agent

Expand the implemented webhook receiver into richer event entities and per-channel binary sensors for motion, human/vehicle, alarm signal, alarm input, video loss, and disk/device exceptions.

### Home Assistant Quality Agent

Add `strings.json`, options flow, diagnostics redaction improvements, services for event server registration, and entity tests.

### Alarm Research Agent

Look for newer/private VIGI documentation or firmware endpoints that expose alarm arm/disarm/activate/deactivate. Do not add controls until both state and reversible commands are verified.
