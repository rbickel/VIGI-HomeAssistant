# VIGI NVR Home Assistant Integration

Custom Home Assistant integration project for TP-Link VIGI NVR devices with OpenAPI enabled.

The immediate goal is to integrate the documented VIGI NVR OpenAPI surface into Home Assistant and identify whether alarm control is actually exposed by the NVR firmware.

## Current Findings

- The NVR is reachable at `https://192.168.50.206:20443`.
- Generic web, CGI, ISAPI, Swagger, and ONVIF-style discovery paths returned `404` on the OpenAPI port.
- `/openapi`, `/openapi.json`, `/openapi.yaml`, `/openapi/server`, `/openapi/server/api/v1`, and `/openapi/server/api/v1/swagger.json` returned `401` before auth and `404` after auth, so the NVR does not appear to host an OpenAPI JSON/YAML document at those paths.
- The auth challenge is `Digest realm="TP-LINK NVR"` with `algorithm="SHA-256"` and `url="/openapi/token"`.
- TP-Link FAQ 4797 documents a two-step flow: SHA-256 Digest authentication to `/openapi/token`, then `Authorization: Bearer <decoded access_token>` for API calls.
- The provided VIGI NVR Open API PDF documents fixed REST endpoints under `/openapi/...` rather than a downloadable spec endpoint.
- The PDF documents event push and alarm-related event payload fields, but it does not document arm, disarm, activate, or deactivate alarm control endpoints.

## Discovery

The discovery script reads credentials from environment variables and does not persist credentials or tokens.

```powershell
$env:VIGI_HOST = "192.168.50.206"
$env:VIGI_PORT = "20443"
$env:VIGI_USERNAME = "admin"
$env:VIGI_PASSWORD = "<your-password>"
python scripts/discover_vigi_openapi.py
```

Outputs are written to `docs/discovery/`:

- `endpoint-probes.json`: authenticated read-only endpoint probe summaries.
- `endpoint-probes.md`: human-readable read-only endpoint status plus mutating endpoints intentionally not called.
- `summary.json` and `endpoints.md`: optional legacy outputs if `--spec-path` is used.

## Event Push Capture

The VIGI OpenAPI event protocol pushes to an HTTP or HTTPS event server. A standalone HTTP capture script is included so we can learn the exact payloads from your NVR before turning them into Home Assistant event entities.

```powershell
python scripts/capture_vigi_events.py --port 3001 --path /event_message
```

The script prints a suggested NVR event server value such as `HTTP <local-ip>:3001/event_message`. Configure that in the NVR event server settings with `picture_switch` on or off depending on whether you want image parts captured.

Captured requests are written under `docs/discovery/event-captures/` and include request headers, the raw body, parsed event JSON when available, optional image parts, and a `summary.json` with event type/subtype labels.

## Home Assistant Shape

The custom component lives in `custom_components/vigi_nvr/`. It includes a config flow, VIGI API client, coordinator, sensors, binary sensors, and switches.

Implemented platforms:

- `sensor`: channel count, disk count/status, timing/NTP, PoE power, channel metadata, stream metadata, audio volume, and RTSP URL helpers.
- `binary_sensor`: channel online state, PoE port linked state, and event server configured state.
- `switch`: audio input/output mute, audio input noise cancelling, and PoE port enable.

Not implemented yet:

- `alarm_control_panel`: blocked until a real arm/disarm endpoint is found and validated.
- `camera`: later phase; RTSP URLs are exposed as diagnostic sensors first.
- Event receiver entities: planned next step for VIGI event push messages.

See [docs/proposal.md](docs/proposal.md) for the implementation plan.
