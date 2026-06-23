# VIGI NVR Endpoint Catalog

Source: VIGI NVR Open API Document PDF provided in the workspace conversation.

## Authentication

| Method | Path | Purpose | Implemented |
| --- | --- | --- | --- |
| GET | `/openapi/token` | Obtain bearer token via SHA-256 Digest or refresh token | Yes |

## Control Endpoints

| Area | Method | Path | Purpose | Client | Entity |
| --- | --- | --- | --- | --- | --- |
| Channel | GET | `/openapi/added_devices` | List added camera channels | Yes | Yes |
| Video | GET | `/openapi/resolution` | Get channel stream resolution | Yes | Yes |
| Video | GET | `/openapi/valid_resolutions` | Get valid resolutions | Yes | No |
| Video | POST | `/openapi/resolution` | Set channel stream resolution | Yes | No |
| Video | GET | `/openapi/bitrate` | Get channel bitrate | Yes | Yes |
| Video | GET | `/openapi/bitrate_capability` | Get valid bitrate/quality values | Yes | No |
| Video | POST | `/openapi/bitrate` | Set channel bitrate | Yes | No |
| Time | GET | `/openapi/timing_mode` | Get timing mode | Yes | Yes |
| Time | PUT | `/openapi/timing_mode` | Set timing mode | Yes | No |
| Time | GET | `/openapi/ntp` | Get NTP configuration | Yes | Yes |
| Time | PUT | `/openapi/ntp` | Set NTP configuration | Yes | No |
| Audio | GET | `/openapi/audio/output/sound` | Get output sound info | Yes | Yes |
| Audio | GET | `/openapi/audio/input/sound` | Get input sound info | Yes | Yes |
| Audio | POST | `/openapi/audio/output/sound` | Set output sound info | Yes | Yes, mute |
| Audio | POST | `/openapi/audio/input/sound` | Set input sound info | Yes | Yes, mute/noise cancelling |
| Disk | GET | `/openapi/disks` | Get internal disk information | Yes | Yes |
| Disk | GET | `/openapi/esata_disks` | Get eSATA disk information | Yes | No |
| Disk | POST | `/openapi/smartctl_process` | Start/stop SMART process | Yes | No |
| Disk | GET | `/openapi/smartctl_process/capability` | Get SMART test capability | Yes | No |
| Disk | POST | `/openapi/smartctl_process/test` | Start SMART test | Yes | No |
| Disk | GET | `/openapi/smartctl_process/schedule` | Get SMART test schedule | Yes | No |
| Disk | GET | `/openapi/smartctl_process/attribute` | Get SMART attributes | Yes | No |
| PoE | GET | `/openapi/poe/info` | Get PoE port config | Yes | Yes |
| PoE | POST | `/openapi/poe/info` | Set PoE port config | Yes | Yes, enable |
| PoE | GET | `/openapi/poe/link_mode` | Get PoE link modes | Yes | No |
| PoE | POST | `/openapi/poe/link_mode` | Set PoE link mode | Yes | No |
| PoE | GET | `/openapi/poe/status` | Get PoE port/global power status | Yes | Yes |
| PoE | GET | `/openapi/poe/link_status` | Get compact PoE link status | Yes | Yes |
| Event | GET | `/openapi/event_server` | Get configured event push servers | Yes | Yes |
| Event | POST | `/openapi/event_server/new_server` | Add event push server | Yes | Planned service/options |
| Event | POST | `/openapi/event_server/delete_server` | Delete event push server | Yes | Planned service/options |
| Event push | POST | `/api/webhook/<id>` | Home Assistant receiver for VIGI `event_message` pushes | N/A | Yes |
| Recording | GET | `/openapi/record/days` | Get days with recordings | Yes | No |
| Recording | GET | `/openapi/record/search/free_process` | Get free search process ID | Yes | No |
| Recording | GET | `/openapi/record/search/results` | Get recording result ranges | Yes | No |
| System | POST | `/openapi/systemctl` | Reboot or reset | Yes | No |

## Stream Interface

| URL | Purpose | Implemented |
| --- | --- | --- |
| `rtsp://<IP>/live/<channel>/<stream>/avm` | Live stream URL | URL helper/sensor |
| `rtsp://<IP>/replay/<channel>/<stream>/avm?starttime=<starttime>&endtime=<endtime>` | Replay stream URL | URL helper |

## Alarm-Relevant Event Data

The PDF documents alarm-related event payload fields and event IDs, but not alarm command endpoints.

Event message keys include `alarm_output` and `alarm_input` when applicable.

Relevant event IDs:

- Type `1`, subtype `18`: Alarm signal.
- Type `2`, subtype `13`: Alarm input.
