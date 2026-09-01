# AEGIS Repository Structure & File Responsibilities

This file maps the contest repository to the canonical **2-RPi / 4-Camera** system and the separate simplified demo path.

## 1. Quick Navigation

| Purpose | Start Here |
|---|---|
| 3-minute overview | [`README.md`](../README.md) |
| Runtime modes | [`RUNTIME_MODES.md`](RUNTIME_MODES.md) |
| Full 4CH deployment | [`START_HERE_KO.md`](../START_HERE_KO.md), [`RUNBOOK.md`](RUNBOOK.md) |
| End-to-End data flow | [`ARCHITECTURE.md`](ARCHITECTURE.md), [`OPERATION_FLOW.md`](OPERATION_FLOW.md) |
| Camera calibration | [`CAMERA_CALIBRATION.md`](CAMERA_CALIBRATION.md), `calibration/` |
| Turret calibration | [`TURRET_CALIBRATION.md`](TURRET_CALIBRATION.md), `runtime/fusion_pc/calib_data.json` |
| AI training/results | [`AI_PIPELINE.md`](AI_PIPELINE.md), [`AI_RESULTS.md`](AI_RESULTS.md) |
| Team ownership | [`TEAM.md`](../TEAM.md) |

## 2. Detailed Tree

```text
2026ESWContest_free_AEGIS/
│
├─ README.md                         # judge-facing overview and evidence
├─ START_HERE_KO.md                  # canonical 2-RPi / 4CH quick start
├─ TEAM.md                           # role ownership
├─ THIRD_PARTY_NOTICES.md            # dependency/model notices
├─ .gitattributes                    # Git LFS patterns
├─ .gitignore
│
├─ runtime/
│  ├─ README.md
│  ├─ fusion_pc/
│  │  ├─ 5_final_fusion.py           # Python entrypoint
│  │  ├─ 5_final_fusion_async.py     # 4CH receive·YOLO·3D·tracking core
│  │  ├─ tcp_zmq_bridge.py           # simplified 2CH RAW-TCP bridge only
│  │  ├─ ai_decision_dashboard.py    # :5557 read-only Decision Console
│  │  ├─ aegis_species_classifier.py # parallel ResNet gate and temporal vote
│  │  ├─ aegis_decision_engine.py    # parallel risk/recommendation support
│  │  ├─ 6_turret_server.py          # :5556 Track3D subscriber·IK·safety·serial
│  │  ├─ calibration_turret.py       # PT1/PT2 fitting
│  │  ├─ servo_zero_trim.py
│  │  ├─ config_turret.py
│  │  ├─ calib_data.json
│  │  ├─ turret_calibration_overrides.json
│  │  ├─ demo_preflight.ps1          # files·LFS·imports·syntax check
│  │  ├─ demo_start_windows.ps1      # full4ch / demo2ch launcher
│  │  ├─ requirements.txt
│  │  ├─ data/                        # runtime copy of 4 intrinsics + 6 pairs
│  │  ├─ models/                      # runtime YOLO / ResNet copies
│  │  └─ tools/                       # calibration and validation utilities
│  │
│  └─ raspberry_pi/
│     ├─ README.md
│     ├─ sender_FIXED_2.py            # RPi #1 / logical camera 0·1 / ZMQ
│     ├─ sender2_FIXED_2.py           # RPi #2 / logical camera 2·3 / ZMQ
│     ├─ sender_TCP_5560.py           # simplified 2CH RAW-TCP sender
│     ├─ demo_sender03.sh             # compatibility wrapper for simplified demo launch
│     └─ config_turret.example.py
│
├─ firmware/arduino_uno/
│  ├─ turret_uno.ino
│  └─ README.md
│
├─ training/
│  ├─ prepare_aegis_bird_data.py
│  ├─ audit_yolo_missing_birds_v2.py
│  ├─ build_clean_yolo_v2.py
│  ├─ inspect_prepared_samples.py
│  ├─ train_yolo.py
│  ├─ train_resnet_v3_stable.py
│  ├─ audit_rules.json
│  └─ README.md
│
├─ models/
│  ├─ detector/yolo/yolo26n.pt
│  ├─ classifier/resnet/aegis_bird_resnet18_v2.pt
│  └─ research/aegis_bird_yolov8s_best.pt
│
├─ calibration/
│  ├─ intrinsics/intrinsics_0.npz ... intrinsics_3.npz
│  └─ stereo_pairs/calib_01.npz ... calib_23.npz
│
├─ results/
│  ├─ yolo/                           # curves·confusion matrix·CSV
│  └─ resnet/                         # confusion matrix·history·JSON
│
├─ assets/
│  ├─ system/
│  ├─ hardware/
│  ├─ dataset/
│  └─ ai_console/
│
├─ docs/
│  ├─ RUNTIME_MODES.md                # canonical mode contract
│  ├─ RUNBOOK.md
│  ├─ ARCHITECTURE.md
│  ├─ OPERATION_FLOW.md
│  ├─ REPOSITORY_STRUCTURE.md
│  ├─ CAMERA_CALIBRATION.md
│  ├─ TURRET_CALIBRATION.md
│  ├─ AI_PIPELINE.md
│  ├─ AI_RESULTS.md
│  ├─ DATASET.md
│  ├─ PROTOCOLS.md
│  ├─ METRICS.md
│  └─ SAFETY_AND_LIMITATIONS.md
│
└─ scripts/
   ├─ rpi_start_sender.sh             # canonical rpi1/rpi2 launcher
   ├─ rpi_start_demo_2ch.sh           # simplified RAW-TCP demo launcher
   ├─ verify_release_clone.ps1        # fresh clone + Git LFS verification
   ├─ run_fusion.bat
   ├─ run_turret_server.bat
   └─ README.md
```

## 3. Runtime Mode Ownership

| Path | Role |
|---|---|
| `sender_FIXED_2.py` | Full 4CH RPi #1, logical camera 0/1 |
| `sender2_FIXED_2.py` | Full 4CH RPi #2, logical camera 2/3 |
| `sender_TCP_5560.py` | Simplified 2CH demo only |
| `tcp_zmq_bridge.py` | Simplified 2CH demo only |
| `demo_start_windows.ps1 -Mode full4ch` | starts Fusion/Console/Turret without bridge |
| `demo_start_windows.ps1 -Mode demo2ch` | starts bridge plus Fusion/Console/Turret |

## 4. Canonical Files vs Runtime Copies

| Canonical release location | Runtime-local copy | Reason |
|---|---|---|
| `models/detector/yolo/yolo26n.pt` | `runtime/fusion_pc/models/yolo26n.pt` | evidence index + portable relative path |
| `models/classifier/resnet/...pt` | `runtime/fusion_pc/models/custom/...pt` | classifier evidence + runtime load path |
| `calibration/intrinsics/*.npz` | `runtime/fusion_pc/data/intrinsics_*.npz` | result index + runtime load path |
| `calibration/stereo_pairs/*.npz` | `runtime/fusion_pc/data/calib_*.npz` | six-pair evidence + runtime load path |

Model/NPZ files use Git LFS. Pointer-sized files after clone mean `git lfs pull` has not completed.

## 5. Main Execution Order

Full 4CH:

```text
RPi #1 sender_FIXED_2.py ─┐
                          ├→ Fusion :5555 ─┬→ Track3D :5556 → Turret → Arduino
RPi #2 sender2_FIXED_2.py ─┘               └→ snapshot :5557 → ResNet/Risk → AI Console
```

두 출력은 병렬이다. AI Console의 위험도·권장 대응은 표시/의사결정 지원 정보이며 Turret 명령을 중계하거나 gate하지 않는다. Fusion의 `:5558` PULL endpoint는 외부 command input용으로 reserved되어 있지만, 현재 dashboard는 read-only이고 명령을 송신하지 않는다.

Simplified 2CH:

```text
sender_TCP_5560.py → TCP :5560 → tcp_zmq_bridge.py → Fusion :5555
```

## 6. Claim → Evidence

| Claim | Document | Raw Evidence |
|---|---|---|
| Full 2-RPi / 4CH topology | `RUNTIME_MODES.md`, `PROTOCOLS.md` | two sender files, Fusion code |
| Camera RMS / depth sensitivity | `METRICS.md` | calibration NPZ, setup image |
| YOLO P/R/mAP | `AI_RESULTS.md` | YOLO CSV/curves/confusion matrix |
| ResNet Accuracy/Macro-F1 | `AI_RESULTS.md` | test JSON/history/confusion matrix |
| Turret calibration | `TURRET_CALIBRATION.md` | calibration data, override, control code |
| Dataset curation | `DATASET.md` | audit code, rules, review images |
| Team ownership | `TEAM.md` | domain-specific files and documents |

## 7. Excluded From Public Release

- 13 GB raw dataset
- intermediate/backup dumps
- participant forms and personal information
- Wi-Fi credentials and local absolute paths
- `.bak`, `.WORKING`, patch scripts, caches and raw logs
- deprecated scaffold code

The Master Archive preserves the complete development history.
