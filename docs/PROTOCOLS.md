# Communication Protocols

## 1. Runtime Modes

| Mode | Camera / RPi | Input Transport | Stream |
|---|---|---|---|
| **Full 4CH AEGIS Runtime** | 4 Camera / 2 RPi | direct ZMQ/JPEG over IPv4 LAN → `:5555` | 640×360 @ 30 FPS, Q70 |
| **Simplified 2CH Demo** | 2 Camera / 1 RPi | RAW TCP `:5560` → bridge → local ZMQ `:5555` | 640×360 @ 20 FPS, Q60 |
| **4CH Calibration** | 4 Camera / 2 RPi | direct ZMQ/JPEG over IPv4 LAN → `:5555` | 1280×720 @ 20 FPS, Q76 |

## 2. Full Four-Channel Topology

```text
Raspberry Pi #1
  sender_id = rpi1
  physical CSI0/1 → logical img0 / img1
  sender_FIXED_2.py
        \
         \ ZMQ/JPEG tcp://<FUSION_PC_IP>:5555
         /
Raspberry Pi #2
  sender_id = rpi2
  physical CSI0/1 → logical img2 / img3
  sender2_FIXED_2.py
```

Launcher:

```bash
bash scripts/rpi_start_sender.sh rpi1 <FUSION_PC_IP> runtime
bash scripts/rpi_start_sender.sh rpi2 <FUSION_PC_IP> runtime
```

The Fusion PC binds the video input endpoint. `tcp_zmq_bridge.py` is not part of the Full 4CH path. RPi #1, RPi #2 and the Fusion PC only require mutually reachable IPv4 connectivity; wired LAN is recommended for long demos, while same-subnet Wi-Fi LAN uses the same direct-ZMQ protocol.

## 3. Simplified Two-Channel Demo

```text
1 Raspberry Pi / logical img0 + img1
        ↓ RAW TCP :5560
tcp_zmq_bridge.py
        ↓ local ZMQ :5555
Fusion
```

Launcher:

```bash
bash scripts/rpi_start_demo_2ch.sh <FUSION_PC_IP>
```

This mode is a reduced reproduction path, not the canonical 4CH topology.

## 4. Conceptual Frame Packet

```text
id
sender_id
capture timestamp
sequence
profile
width / height
encoding / JPEG quality
logical image payloads
per-image timestamps
pair time difference
```

A dual-camera sender transmits both physical CSI frames in one logical packet. Logical camera IDs decouple camera identity from packet arrival order.

## 5. Latest-First Policy

AEGIS prioritizes the newest physical state.

- sender SNDHWM: low queue depth
- receiver RCVHWM: low queue depth
- non-blocking sender
- stale frame age check
- hard/soft pair synchronization windows
- old serial output buffer clear before latest command
- ZMQ `CONFLATE=1` at turret target subscriber

This avoids aiming at queued historical frames.

## 6. Port Map

| Direction | Transport | Channel | Purpose |
|---|---|---:|---|
| RPi #1/#2 → Fusion | ZMQ/JPEG | `5555` | Full 4CH camera packets |
| Demo RPi → Bridge | RAW TCP | `5560` | Simplified 2CH packets |
| Bridge → Fusion | local ZMQ | `5555` | Demo packet conversion |
| Fusion → Turret server | ZeroMQ PUB/SUB | `5556` | direct tracked 3D target/result control input |
| Fusion → Decision Console | ZeroMQ PUB/SUB | `5557` | dashboard frames, XYZ, motion, evidence for ResNet/risk display |
| Reserved command client → Fusion | ZeroMQ PUSH/PULL | `5558` | reserved command input; current dashboard is read-only and sends nothing |
| Turret server → Arduino | USB Serial | `115200` | PT1/PT2 pan, tilt, laser |

`5556` and `5557` are parallel Fusion outputs. The turret server subscribes directly to valid Track3D target/result packets on `5556`; it does not receive or wait for a Console risk decision. ResNet classification, explainable risk scoring and Recommended Response remain on the `5557` operator-support path. Fusion binds the `5558` command input when dashboard support is enabled, but the current dashboard does not publish commands.

## 7. Arduino Command

The UNO firmware receives:

```text
PT1 pan · PT1 tilt · PT2 pan · PT2 tilt · laser1 · laser2
```

The current PC-side turret controller applies the following layers before serialization:

```text
Fusion Track3D target/result from :5556
→ inverse kinematics
→ measured geometry/trim override
→ axis correction
→ direction-aware tilt backlash compensation
→ adaptive EMA + deadband
→ spike/safe-angle/distance gate
→ latest serial command
```

Current final field-tuned downward compensation is `0.80°` for PT1 and `0.80°` for PT2; upward compensation is zero.

Safety/robustness:

- non-blocking serial parser
- latest-command buffer
- command watchdog
- PC-side safe-angle clamp
- spike clamp and adaptive smoothing
- direction-aware servo hysteresis compensation
- target hold/drop handling
- laser keepalive and distance gate

## 8. Deployment Rules

The public repository uses documentation-safe placeholder network values. The operator must set:

- actual Fusion PC IPv4
- mutually reachable LAN for both RPi nodes and Fusion
- firewall TCP 5555 for Full 4CH
- firewall TCP 5560 for Simplified Demo
- actual Arduino COM port
- calibration/override matching the current rig

Credentials, private IP history and local absolute paths are not committed.
