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
5. Run `scripts/capture_vigi_events.py`, configure the NVR event server to point at it, and collect sample motion/alarm/device events.
6. Decide whether to build the event receiver as part of the integration or as a companion webhook service.

## Fleet Dispatch Candidates

### Endpoint Validation Agent

Run the endpoint probe, inspect response schemas, and update the catalog with model/firmware support notes.

### Event Receiver Agent

Implement an HTTP/HTTPS endpoint that accepts VIGI multipart event pushes, parses JSON plus optional JPEG parts, and maps event type/subtype IDs to Home Assistant events and binary sensors.

### Home Assistant Quality Agent

Add `strings.json`, options flow, diagnostics redaction improvements, services for event server registration, and entity tests.

### Alarm Research Agent

Look for newer/private VIGI documentation or firmware endpoints that expose alarm arm/disarm/activate/deactivate. Do not add controls until both state and reversible commands are verified.
