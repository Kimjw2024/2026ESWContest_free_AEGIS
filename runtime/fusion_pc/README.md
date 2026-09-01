# Fusion PC Runtime

Windows Fusion PC에서 실행되는 AEGIS 최종 통합 코드다.

## 1. Canonical Full 4CH Mode

Full system input:

```text
RPi #1: logical camera 0/1
RPi #2: logical camera 2/3
direct ZMQ/JPEG → Fusion :5555
```

Full 4CH에서는 `tcp_zmq_bridge.py`를 실행하지 않는다. 두 Raspberry Pi는 같은 IPv4 LAN에서 Fusion PC의 `:5555`로 직접 송신한다. 실전 재현은 유선 LAN을 권장하지만, 동일한 direct-ZMQ 구조는 Wi-Fi LAN에서도 동작한다.

```powershell
powershell -ExecutionPolicy Bypass -File .\demo_preflight.ps1 -Mode full4ch
powershell -ExecutionPolicy Bypass -File .\demo_start_windows.ps1 -Mode full4ch
```

## 2. Simplified 2CH Demo

```text
1 RPi / camera 0/1
RAW TCP :5560
→ tcp_zmq_bridge.py
→ local ZMQ :5555
```

```powershell
powershell -ExecutionPolicy Bypass -File .\demo_preflight.ps1 -Mode demo2ch
powershell -ExecutionPolicy Bypass -File .\demo_start_windows.ps1 -Mode demo2ch
```

## 3. Core Runtime

- `5_final_fusion.py` — main entrypoint
- `5_final_fusion_async.py` — receive, HSV/YOLO detect, rectify, six-pair 3D fusion, tracking
- `tcp_zmq_bridge.py` — **2CH demo only**, RAW TCP `:5560` → local ZMQ `:5555`
- `ai_decision_dashboard.py` — crop, species, XYZ, motion, risk and response UI
- `aegis_species_classifier.py` — ResNet-18 8-class inference, gate and temporal vote
- `aegis_decision_engine.py` — explainable risk/response decision support
- `6_turret_server.py` — Track3D target → inverse kinematics → direction-aware backlash compensation → adaptive EMA → Arduino command
- `config_turret.py` — runtime geometry, network, HSV/YOLO, tracking and safety configuration

## 4. Installation

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Install a CPU/CUDA-compatible PyTorch and torchvision build:

```text
https://pytorch.org/get-started/locally/
```

Then:

```powershell
pip install -r requirements.txt
python -c "import torch, torchvision, PIL; print(torch.__version__)"
```

## 5. Current Integrated Rig Calibration & Control

- `calibration_turret.py` — Fusion 3D target + manual laser alignment calibration
- `calib_data.json` — latest PT1/PT2 measured calibration samples
- `turret_calibration_overrides.json` — **physical rig specific** authoritative geometry/trim/depth-scale override
- latest field recalibration procedure: **20 target positions per turret**, distributed across depth and image position
- HSV calibration/debug target: blue ball, `Target_1 = H[100,125], S[75,255], V[60,255]`
- runtime pan/tilt smoothing: base alpha `0.40`, max alpha `0.90`
- deadband: pan `0.08°`, tilt `0.10°`
- servo command interval: `0.020 s` (~50 Hz)
- spike clamp: `18°/frame`
- downward tilt backlash compensation: **PT1 `0.80°`, PT2 `0.80°`**
- upward compensation: `0.00°`
- downward tilt response multiplier: `1.18`

The downward compensation is a field-tuned correction for the observed servo hysteresis where a top-to-bottom motion stopped slightly above the target. Geometry calibration and this direction-dependent runtime correction are separate layers.

After any mechanical relocation, rerun `calibration_turret.py` and commit both the regenerated `calib_data.json` and `turret_calibration_overrides.json` together.

## 6. Camera Calibration

- `data/` — 4 intrinsics + 6 stereo-pair calibration NPZ
- `tools/` — camera calibration, benchmark and runtime validation utilities

## 7. Models

- `models/yolo26n.pt` — live bird detector
- `models/custom/aegis_bird_resnet18_v2.pt` — 8-class classifier

Detailed documentation:

- [`../../docs/RUNTIME_MODES.md`](../../docs/RUNTIME_MODES.md)
- [`../../docs/CAMERA_CALIBRATION.md`](../../docs/CAMERA_CALIBRATION.md)
- [`../../docs/TURRET_CALIBRATION.md`](../../docs/TURRET_CALIBRATION.md)
- [`../../docs/VALIDATION_AND_ROBUSTNESS.md`](../../docs/VALIDATION_AND_ROBUSTNESS.md)
