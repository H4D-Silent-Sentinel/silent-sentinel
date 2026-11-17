# Jetson ↔ base interface (v1)

How the Visual-Tracker (Jetson Orin Nano: tracker + YOLO + VLM) plugs into the Silent Sentinel base.
Both directions are **one JSON object per UDP datagram** on the same network (Wi-Fi or Ethernet).
Reference encoder/decoder: `cuas/visual.py`. All angles in degrees, positions WGS-84, time = Unix seconds.

```
Jetson ──visual──▶ base  udp/47010
Jetson ◀───cue──── base  udp/47011   (sent to every Jetson the base has heard from, or --jetson <ip>)
```

## Jetson → base: `visual`

Send whenever the detector/tracker has something (1–10 Hz is plenty). Omit `tracks` entries when nothing is seen.

```json
{
  "v": 1, "type": "visual", "src": "chaser-1", "t": 1763400000.25,
  "sensor": {"lat": 40.80810, "lon": -73.96390, "alt_m": 35.0,
             "yaw_deg": 92.0, "pitch_deg": -5.0, "hfov_deg": 62.2, "vfov_deg": 48.8},
  "tracks": [
    {"id": 7, "bbox": [0.61, 0.40, 0.03, 0.02], "conf": 0.84, "class": "drone",
     "label": "DJI Mavic 3 (VLM)",
     "az_deg": 104.3, "el_deg": 3.1, "az_sigma_deg": 0.5,
     "range_m": 85.0, "range_sigma_m": 20.0}
  ]
}
```

| Field | Required | Notes |
|---|---|---|
| `src` | yes | Stable camera id. Fixed posts listed in the site file (e.g. `post-1`) may omit `sensor.lat/lon`. |
| `sensor.lat/lon/alt_m` | moving cameras | Chaser: its own GPS position at capture time. |
| `sensor.yaw_deg/pitch_deg/hfov_deg/vfov_deg` | if `az_deg` omitted | Camera boresight (true north, clockwise; pitch up +) and field of view. |
| `tracks[].bbox` | if `az_deg` omitted | `[x, y, w, h]` normalised 0–1, origin top-left. Base converts the box centre to az/el. |
| `tracks[].az_deg / el_deg` | preferred | True bearing/elevation to target if the Jetson already computes it. |
| `tracks[].az_sigma_deg` | no | Default 1.0. |
| `tracks[].range_m`, `range_sigma_m` | no | From the mil relation once the VLM knows the model's true size. With range the report becomes a position fix and can start a track (conf ≥ 0.6); without it, it's a bearing that sharpens an existing track. |
| `tracks[].label` | no | VLM classification text; shown on the map and in TAK. |

## Base → Jetson: `cue`

Sent for each **confirmed** track, at most once a second per track: where to point the camera / send the chaser.

```json
{"v": 1, "type": "cue", "t": 1763400001.0, "track_id": 3,
 "lat": 40.8081234, "lon": -73.9639876, "alt_m": 40.0, "sigma_m": 35.0,
 "vel_e": 4.1, "vel_n": -2.0, "f0_hz": 201.5, "confirmed": true,
 "sources": ["acoustic", "visual:post-1"]}
```

`sigma_m` is the 1-σ horizontal uncertainty: search a circle of ~2σ around the point, moving it by `vel_e/vel_n` (m/s) per second since `t`.

## Testing without the other side

- Base without a Jetson: `python -m cuas sim --site sites/example_intersection.json --map` (simulated camera post included).
- Jetson without the base: listen with `nc -ul 47011` for cues; send a hand-written `visual` message with
  `echo '<json>' | nc -u <base-ip> 47010`.
