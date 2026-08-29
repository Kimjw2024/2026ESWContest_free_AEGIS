# Fusion PC Runtime

Windows Fusion PC에서 실행되는 AEGIS 최종 통합 코드다.

## Core Runtime

- `5_final_fusion.py` — main entrypoint
- `5_final_fusion_async.py` — receive, detect, rectify, six-pair 3D fusion, tracking
- `tcp_zmq_bridge.py` — Raspberry Pi RAW TCP `:5560` → Fusion ZMQ `:5555`
- `ai_decision_dashboard.py` — crop, species, XYZ, motion, risk and response UI
- `aegis_species_classifier.py` — ResNet-18 8-class inference, gate and temporal vote
- `aegis_decision_engine.py` — explainable risk/response decision support
- `6_turret_server.py` — Track3D target → inverse kinematics → Arduino command
- `config_turret.py` — runtime geometry, network, tracking and safety configuration

## Calibration & Control

- `calibration_turret.py` — interactive measured-target turret calibration
- `calib_data.json` — PT1/PT2 22-point measured calibration samples
- `turret_calibration_overrides.json` — authoritative final turret override
- `data/` — 4 intrinsics + 6 stereo-pair calibration NPZ
- `tools/` — camera calibration, benchmark and runtime validation utilities

Detailed documentation:

- [`../../docs/CAMERA_CALIBRATION.md`](../../docs/CAMERA_CALIBRATION.md)
- [`../../docs/TURRET_CALIBRATION.md`](../../docs/TURRET_CALIBRATION.md)
- [`../../docs/VALIDATION_AND_ROBUSTNESS.md`](../../docs/VALIDATION_AND_ROBUSTNESS.md)

## Models

- `models/yolo26n.pt` — live bird detector
- `models/custom/aegis_bird_resnet18_v2.pt` — 8-class classifier

## Execution

```powershell
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\demo_preflight.ps1
py -3.11 .\tcp_zmq_bridge.py
py -3.11 .\5_final_fusion.py
py -3.11 .\ai_decision_dashboard.py
py -3.11 .\6_turret_server.py
```

Machine-specific Fusion PC IPv4 and Arduino COM port must be adjusted locally.
