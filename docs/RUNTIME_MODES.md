# AEGIS Runtime Modes

AEGIS는 **Full 4CH system**, **Simplified 2CH demo**, **4CH calibration**을 명확히 분리한다.  
대회 보고서와 전체 시스템 주장은 Full 4CH 구성을 기준으로 하며, 2CH demo는 축소 재현 경로다.

## 1. Mode Matrix

| Mode | Camera / Raspberry Pi | Transport | Profile | Main Purpose |
|---|---|---|---|---|
| **Full 4CH AEGIS Runtime** | 4 Camera / 2 RPi | direct ZMQ/JPEG → Fusion `:5555` | **640×360 @ 30 FPS, Q70** | 6-pair 3D·Tracking·AI·Turret 전체 시스템 |
| **Simplified 2CH Demo** | 2 Camera / 1 RPi | RAW TCP `:5560` → `tcp_zmq_bridge.py` → ZMQ `:5555` | **640×360 @ 20 FPS, Q60** | 축소 시연·백업·빠른 재현 |
| **4CH Calibration** | 4 Camera / 2 RPi | direct ZMQ/JPEG → Fusion `:5555` | **1280×720 @ 20 FPS, Q76** | 4 intrinsics와 6 stereo-pair capture |

## 2. Canonical Full 4CH Topology

```mermaid
flowchart LR
    C0["Camera 0"] --> R1["Raspberry Pi #1"]
    C1["Camera 1"] --> R1
    C2["Camera 2"] --> R2["Raspberry Pi #2"]
    C3["Camera 3"] --> R2

    R1 -->|"ZMQ/JPEG :5555 · img0/img1"| F["Fusion PC"]
    R2 -->|"ZMQ/JPEG :5555 · img2/img3"| F

    F --> D["YOLO / 6-Pair 3D / Tracking"]
    D --> A["ResNet / Risk / Decision Console"]
    D --> T["Turret Server / Arduino"]
```

- RPi #1: `sender_FIXED_2.py`, logical camera `0/1`
- RPi #2: `sender2_FIXED_2.py`, logical camera `2/3`
- Launcher: `scripts/rpi_start_sender.sh`
- Fusion PC full mode: `demo_start_windows.ps1 -Mode full4ch`
- `tcp_zmq_bridge.py`는 Full 4CH에서 사용하지 않는다.

## 3. Simplified 2CH Demo Topology

```mermaid
flowchart LR
    C0["Camera 0"] --> R["Raspberry Pi"]
    C1["Camera 1"] --> R
    R -->|"RAW TCP :5560"| B["tcp_zmq_bridge.py"]
    B -->|"local ZMQ :5555"| F["Fusion PC"]
```

- sender: `sender_TCP_5560.py`
- logical camera: `0/1`
- launcher: `scripts/rpi_start_demo_2ch.sh`
- Fusion PC demo mode: `demo_start_windows.ps1 -Mode demo2ch`
- 이 경로는 pair `01` 중심의 축소 데모이며 4CH simultaneous operation을 주장하는 근거로 사용하지 않는다.

## 4. Full 4CH Runtime Commands

Fusion PC:

```powershell
cd runtime\fusion_pc
powershell -ExecutionPolicy Bypass -File .\demo_preflight.ps1 -Mode full4ch
powershell -ExecutionPolicy Bypass -File .\demo_start_windows.ps1 -Mode full4ch
```

RPi #1:

```bash
bash scripts/rpi_start_sender.sh rpi1 <FUSION_PC_IP> runtime
```

RPi #2:

```bash
bash scripts/rpi_start_sender.sh rpi2 <FUSION_PC_IP> runtime
```

## 5. Calibration Commands

RPi #1:

```bash
bash scripts/rpi_start_sender.sh rpi1 <FUSION_PC_IP> calibration
```

RPi #2:

```bash
bash scripts/rpi_start_sender.sh rpi2 <FUSION_PC_IP> calibration
```

Calibration capture는 `1280×720 @ 20 FPS, Q76`을 유지한다. Runtime에서 640×360으로 낮추더라도 2D center를 calibration resolution으로 재스케일한 뒤 triangulation한다.

## 6. Documentation Rule

다음 표현을 섞지 않는다.

- **Full 4CH**: 2 RPi / 4 Camera / direct ZMQ/JPEG / 30 FPS / Q70
- **Simplified 2CH Demo**: 1 RPi / 2 Camera / RAW TCP bridge / 20 FPS / Q60
- **Calibration**: 2 RPi / 4 Camera / 1280×720 / 20 FPS / Q76

README, PPT, 시연영상, Q&A에서 “현재 기준 시스템”은 Full 4CH이며, 2CH demo는 명시적으로 축소 경로라고 표기한다.
