# Communication Protocols

## 1. Network Flow

| Direction | Transport | Channel | Purpose |
|---|---|---:|---|
| Raspberry Pi → Fusion PC | RAW TCP | `5560` | current dual JPEG frame packet stream |
| Bridge → Fusion | ZeroMQ | `5555` | Fusion camera packet contract |
| Fusion → Turret server | ZeroMQ | `5556` | tracked 3D target/result |
| Fusion → Decision Console | ZeroMQ PUB | `5557` | crop, class, XYZ, motion, evidence |
| Console → Runtime | ZeroMQ command | `5558` | UI/runtime command channel |
| Turret server → Arduino | USB Serial | machine-specific COM | PT1/PT2 pan, tilt, laser command |

## 2. Four-Channel Capture Topology

```text
Raspberry Pi #1
  sender_id = rpi1
  logical camera = img0 / img1

Raspberry Pi #2
  sender_id = rpi2
  logical camera = img2 / img3
```

Historical two-Pi sender files:

- `runtime/raspberry_pi/sender_FIXED_2.py` — logical camera 0–1
- `runtime/raspberry_pi/sender2_FIXED_2.py` — logical camera 2–3

Current single-Pi RAW-TCP path:

- `runtime/raspberry_pi/sender_TCP_5560.py`
- `runtime/fusion_pc/tcp_zmq_bridge.py`

## 3. Packet Fields

Conceptual packet structure:

```text
id · sender_id · capture_ts · seq · logical_camera_id · jpeg_payload
```

For a dual-camera sender, the packet preserves both images and their timing metadata. The bridge preserves logical camera IDs so pair construction is independent of physical receive order.

## 4. Capture Profiles

| Profile | Resolution | FPS | JPEG | Purpose |
|---|---:|---:|---:|---|
| Calibration | 1280×720 | 20 | Q76 | checkerboard corner accuracy and calibration capture |
| Runtime | 640×360 | 30 | Q70 | low-latency detection and tracking |

The sensor mode reference is `2304:1296` with 180° rotation in the current rig.

## 5. Latest-First Policy

AEGIS prioritizes the newest state over processing every queued frame.

- sender high-water mark: 1
- receiver high-water mark: 2
- stale frame age check
- pair timestamp window
- soft time-weighting outside the ideal window
- old serial command buffer clear before sending the newest command

This prevents a system that is technically processing all frames but physically aiming at the past.

## 6. Arduino Command

The UNO firmware receives a compact latest-command string carrying:

```text
PT1 pan · PT1 tilt · PT2 pan · PT2 tilt · laser1 · laser2
```

The firmware uses:

- non-blocking serial parser
- latest-command buffer
- command timeout/watchdog
- servo and logical laser output

The Windows server performs geometry, trim, smoothing and safety limits before transmission.

## 7. Deployment Rule

Repository defaults use documentation-safe placeholder network values. The operator must set:

- actual Fusion PC IPv4
- Windows firewall rule for TCP 5560
- actual Arduino COM port
- calibration file matching the physical rig

Machine-specific secrets and absolute local paths are not committed.
