# Fusion PC Runtime

Windows Fusion PC에서 실행되는 AEGIS 최종 통합 코드다.

## 1. Canonical Full 4CH Mode

Full system input:

```text
RPi #1: logical camera 0/1
RPi #2: logical camera 2/3
direct ZMQ/JPEG → Fusion :5555
```

Full 4CH에서는 `tcp_zmq_bridge.py`를 실행하지 않는다.

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
- `5_final_fusion_async.py` — receive, detect, rectify, six-pair 3D fusion, tracking
- `tcp_zmq_bridge.py` — **2CH demo only**, RAW TCP `:5560` → local ZMQ `:5555`
- `ai_decision_dashboard.py` — crop, species, XYZ, motion, risk and response UI
- `aegis_species_classifier.py` — ResNet-18 8-class inference, gate and temporal vote
- `aegis_decision_engine.py` — explainable risk/response decision support
- `6_turret_server.py` — Track3D target → inverse kinematics → Arduino command
- `config_turret.py` — runtime geometry, network, tracking and safety configuration

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

## 5. Calibration & Control

- `calibration_turret.py` — interactive measured-target turret calibration
- `calib_data.json` — PT1/PT2 22-point measured calibration samples
- `turret_calibration_overrides.json` — authoritative final turret override
- `data/` — 4 intrinsics + 6 stereo-pair calibration NPZ
- `tools/` — camera calibration, benchmark and runtime validation utilities

## 6. Models

- `models/yolo26n.pt` — live bird detector
- `models/custom/aegis_bird_resnet18_v2.pt` — 8-class classifier

Detailed documentation:

- [`../../docs/RUNTIME_MODES.md`](../../docs/RUNTIME_MODES.md)
- [`../../docs/CAMERA_CALIBRATION.md`](../../docs/CAMERA_CALIBRATION.md)
- [`../../docs/TURRET_CALIBRATION.md`](../../docs/TURRET_CALIBRATION.md)
- [`../../docs/VALIDATION_AND_ROBUSTNESS.md`](../../docs/VALIDATION_AND_ROBUSTNESS.md)
