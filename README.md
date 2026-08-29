<div align="center">

# AEGIS

### AI 기반 공항 Bird-Strike 예방·대응 시스템

**4-Camera Multi-Baseline 3D Vision · Bird AI · Tracking · Decision Support · Dual Pan-Tilt**

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)
![OpenCV](https://img.shields.io/badge/OpenCV-Stereo%203D-5C3EE8?style=flat-square&logo=opencv&logoColor=white)
![PyTorch](https://img.shields.io/badge/PyTorch-YOLO%20%2B%20ResNet--18-EE4C2C?style=flat-square&logo=pytorch&logoColor=white)
![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-Multi--Camera-A22846?style=flat-square&logo=raspberrypi&logoColor=white)
![Arduino](https://img.shields.io/badge/Arduino-Dual%20Pan--Tilt-00979D?style=flat-square&logo=arduino&logoColor=white)

![Cameras](https://img.shields.io/badge/Cameras-4%20x%20IMX219-455A64?style=flat-square)
![Stereo Pairs](https://img.shields.io/badge/Stereo%20Pairs-6-4C71F2?style=flat-square)
![YOLO mAP](https://img.shields.io/badge/YOLO%20mAP%400.5-97.5%25-00A98F?style=flat-square)
![ResNet Accuracy](https://img.shields.io/badge/ResNet--18%20Accuracy-94.76%25-EE4C2C?style=flat-square)
![Turret Calibration](https://img.shields.io/badge/Turret%20Calibration-22%20x%202%20points-6A5ACD?style=flat-square)

**2026 임베디드SW경진대회 자유공모 부문**

[빠른 실행](START_HERE_KO.md) · [시스템 구조](docs/ARCHITECTURE.md) · [운용 상태](docs/OPERATION_FLOW.md) · [파일 구조](docs/REPOSITORY_STRUCTURE.md) · [기구·CAD](docs/HARDWARE_AND_CAD.md) · [카메라 보정](docs/CAMERA_CALIBRATION.md) · [터렛 보정](docs/TURRET_CALIBRATION.md) · [AI 파이프라인](docs/AI_PIPELINE.md) · [AI 정량결과](docs/AI_RESULTS.md) · [팀 역할](TEAM.md)

<br>

<img src="assets/system/system_overview.png" alt="AEGIS integrated prototype" width="900">

</div>

---

## 1. 개발 배경과 목표

공항의 Bird-Strike 대응은 단순히 새를 검출하는 것만으로 끝나지 않는다. **어떤 조류가 어디에 있고, 어느 방향으로 이동하며, 현재 얼마나 위험한지 판단한 뒤 물리 대응 장치까지 연결**해야 한다.

AEGIS는 카메라 입력부터 조류 인식, 3차원 위치추정, 시계열 추적, 위험도 판단, 물리 대응까지 하나의 Embedded AI pipeline으로 통합한다.

> **Problem → Perception → Localization → Tracking → Decision → Response**

| 단계 | 구현 내용 |
|---|---|
| Perception | YOLO 기반 조류 검출 + ResNet-18 8개 조류군 분류 |
| Localization | 4대 카메라, 6개 Stereo Pair, 0.15 / 0.30 / 0.45 m Multi-Baseline 3D |
| Tracking | LPF · Kalman · velocity estimation · track hold |
| Decision | 조류군 · XYZ · 상대고도 · 접근 상태 · track evidence 기반 설명 가능한 위험도 |
| Response | Dual Pan-Tilt turret + Acoustic/RC-Car 확장 구조 |

### 구현 범위

| 기능 | 현재 상태 | 비고 |
|---|---|---|
| 4CH 영상 입력·통신 | **구현** | dual-RPi sender와 1-RPi RAW-TCP demo path 보존 |
| 4 intrinsics / 6 stereo-pair calibration | **구현·정량 검증** | NPZ와 RMS evidence 공개 |
| Multi-Baseline 3D / Tracking | **구현** | pair weighting, Kalman, velocity, hold |
| YOLO + ResNet-18 2-stage AI | **구현·평가** | live detector와 research detector 역할 분리 |
| AI Decision Console | **구현** | species·XYZ·motion·risk·response 표시 |
| Dual Pan-Tilt response | **구현·실측 보정** | PT1/PT2 각 22-point calibration |
| RC-Car Acoustic extension | **Prototype** | 자율 waypoint dispatch가 아닌 확장 가능성 검증 |

---

## 2. 전체 시스템 구조

```mermaid
flowchart LR
    A["IMX219 Camera x4"] --> B["Raspberry Pi Sender Nodes"]
    B --> C["Wired Ethernet / JPEG-ZMQ / RAW TCP"]
    C --> D["YOLO Bird Detection"]
    D --> E["6 Stereo-Pair Triangulation"]
    E --> F["Robust Multi-Baseline 3D Fusion"]
    F --> G["LPF / Kalman / Velocity / Track Hold"]
    D --> H["ResNet-18 8-Class Classification"]
    G --> I["Explainable Risk Assessment"]
    H --> I
    I --> J["AI Decision Console"]
    I --> K["Inverse Kinematics / Safety Gate"]
    K --> L["Arduino Dual Pan-Tilt"]
    I -.-> M["Mobile Acoustic Prototype"]
```

### 실제 운용 8단계

1. `demo_preflight.ps1`이 코드·모델·필수 calibration file을 점검한다.
2. Raspberry Pi가 camera frame을 capture·encode해 Fusion PC로 전송한다.
3. Fusion은 stale frame을 제외하고 최신 multi-camera packet을 구성한다.
4. YOLO가 각 view에서 bird bbox·center·confidence를 생성한다.
5. 유효 stereo pair가 triangulation을 수행하고 최대 6개 pair를 robust fusion한다.
6. Kalman/LPF/velocity/hold로 Track3D를 안정화하고 ResNet-18이 조류군을 분류한다.
7. Decision Engine이 distance·approach·altitude·species·track·threat를 결합한다.
8. Turret Server가 유효 XYZ를 inverse kinematics와 safety gate를 거쳐 Arduino로 전달한다.

<details>
<summary><b>Runtime 상태 흐름 펼쳐보기</b></summary>

```mermaid
stateDiagram-v2
    [*] --> PREFLIGHT
    PREFLIGHT --> WAIT_STREAM: validation passed
    PREFLIGHT --> FAULT: required resource missing
    WAIT_STREAM --> DETECT_2D: fresh packet
    WAIT_STREAM --> SAFE_IDLE: no stream / stale
    DETECT_2D --> WAIT_STEREO_LOCK: target only in 2D
    DETECT_2D --> TRACK_3D: valid stereo evidence
    WAIT_STEREO_LOCK --> TRACK_3D: pair lock
    TRACK_3D --> CLASSIFY: valid crop
    TRACK_3D --> ASSESS_RISK: UNKNOWN fallback
    CLASSIFY --> ASSESS_RISK: confidence + temporal vote
    ASSESS_RISK --> MONITOR: LOW / uncertain
    ASSESS_RISK --> RESPOND: MEDIUM · HIGH · CRITICAL
    RESPOND --> HOLD: short target loss
    HOLD --> TRACK_3D: reacquired
    HOLD --> SAFE_RETURN: drop timeout
    SAFE_RETURN --> WAIT_STREAM: laser OFF / home
```

세부 guard와 code mapping은 [OPERATION_FLOW.md](docs/OPERATION_FLOW.md)에 정리했다.

</details>

### 핵심 차별점

- **4-Camera / 6 Stereo Pair**를 모두 보정하는 Multi-Baseline 구조
- 조류 위치 검출과 조류군 분류를 분리한 **2-stage AI pipeline**
- 단발성 detection이 아닌 **시계열 tracking · velocity · hold**
- 3D 좌표를 실제 터렛 각도로 변환하는 **기구학 모델 + 실측 보정 파이프라인**
- Species · XYZ · Motion · Risk · Recommended Response를 통합한 **AI Decision Console**
- 고정형 터렛과 이동형 음향 플랫폼이 같은 response layer를 공유하는 확장 구조

---

## 3. Core Technology Stack & Runtime Environment

도구를 단순 나열하지 않고, 실제 End-to-End 시스템에서 각 기술이 담당하는 계층을 기준으로 구성했다.

| System Layer | Core Stack |
|---|---|
| **Edge & Control** | ![RPi5](https://img.shields.io/badge/Raspberry%20Pi-5-A22846?style=flat-square&logo=raspberrypi&logoColor=white) ![IMX219](https://img.shields.io/badge/IMX219-4%20Cameras-455A64?style=flat-square) ![Arduino UNO](https://img.shields.io/badge/Arduino-UNO-00979D?style=flat-square&logo=arduino&logoColor=white) ![PanTilt](https://img.shields.io/badge/Actuator-Dual%20Pan--Tilt-6A5ACD?style=flat-square) |
| **Vision & AI** | ![OpenCV](https://img.shields.io/badge/OpenCV-Stereo%203D-5C3EE8?style=flat-square&logo=opencv&logoColor=white) ![Ultralytics](https://img.shields.io/badge/Ultralytics-YOLO-111F68?style=flat-square&logo=ultralytics&logoColor=white) ![PyTorch](https://img.shields.io/badge/PyTorch-ResNet--18-EE4C2C?style=flat-square&logo=pytorch&logoColor=white) |
| **3D & Tracking** | ![Stereo](https://img.shields.io/badge/Stereo%20Pairs-6-4C71F2?style=flat-square) ![Baseline](https://img.shields.io/badge/3D-Multi--Baseline-7B61FF?style=flat-square) ![Tracking](https://img.shields.io/badge/Tracking-Kalman%20%2B%20LPF-5A67D8?style=flat-square) |
| **Communication** | ![Ethernet](https://img.shields.io/badge/Ethernet-Wired-00599C?style=flat-square) ![TCP](https://img.shields.io/badge/RAW%20TCP-5560-555555?style=flat-square) ![ZeroMQ](https://img.shields.io/badge/ZeroMQ-5555--5558-DF0000?style=flat-square&logo=zeromq&logoColor=white) ![Serial](https://img.shields.io/badge/Serial-115200-444444?style=flat-square) |
| **Runtime & Release** | ![Windows](https://img.shields.io/badge/Windows-Fusion%20PC-0078D4?style=flat-square&logo=windows11&logoColor=white) ![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white) ![PySide6](https://img.shields.io/badge/PySide6-Decision%20Console-41CD52?style=flat-square&logo=qt&logoColor=white) ![GitLFS](https://img.shields.io/badge/Git%20LFS-Models%20%26%20NPZ-F05032?style=flat-square&logo=git&logoColor=white) |

Fusion PC는 Windows/Python 3.11 기준이며, CUDA-capable GPU는 live inference 가속을 위한 권장사항이다. 외부 라이브러리·모델의 출처와 라이선스는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), 설치 목록은 [`runtime/fusion_pc/requirements.txt`](runtime/fusion_pc/requirements.txt)에 정리했다.

---

## 4. 기구·CAD 및 Camera Calibration

AEGIS는 한 가지 기구 배치만 제시하지 않고 운용 환경을 기준으로 두 가지 감시 개념을 구성했다.

- **A안:** 활주로·지평선·저지대 접근 관측
- **B안:** 상부 영공·높은 접근 경로 관측

| 항목 | 기준 치수 |
|---|---:|
| 전체 조립 reference | 약 320.7 × 314.7 × 99.1 mm |
| 기판 / 베이스 | 약 60 × 580 × 15 mm |
| 20° 카메라 거치대 | 약 28 × 17.1 × 76.4 mm |
| 터렛 거치대 | 약 119.6 × 111.7 × 99.1 mm |
| 인접 카메라 간격 | 149 / 151 / 149 mm |
| outer baseline | 약 449 mm |

<p align="center"><img src="assets/hardware/hardware_design.png" alt="CAD and A/B hardware concepts" width="900"></p>

### Multi-Camera Calibration

- Checkerboard square: **25.0 mm**
- Single calibration: camera 0–3 내부 파라미터
- Stereo calibration: `01`, `02`, `03`, `12`, `13`, `23`
- Calibration profile: **1280×720 · 20 FPS · JPEG Q76**
- Runtime profile: **640×360 · 30 FPS · JPEG Q70**
- 2D detection 좌표를 calibration 좌표계로 재스케일한 뒤 triangulation에 사용
- `01/12/23`은 4개 카메라를 연결하는 최소 chain, `02/03/13`은 추가 redundancy와 깊이 정밀도를 제공

| 평가 항목 | 결과 |
|---|---:|
| Single-camera RMS | **0.154–0.181 px** |
| Six stereo-pair RMS | **0.217–0.289 px** |
| Depth sensitivity P95 — 0.15 m | **95.3 mm** |
| Depth sensitivity P95 — 0.30 m | **49.2 mm** |
| Depth sensitivity P95 — 0.45 m | **33.1 mm** |
| 0.45 m vs 0.15 m sensitivity improvement | **65.3%** |

> Depth sensitivity는 `Z=2.2 m`, image-center perturbation `1 px` 조건의 시뮬레이션이며 실제 공항 현장 절대 거리 오차를 의미하지 않는다.

<p align="center"><img src="assets/hardware/calibration_setup.png" alt="4-camera calibration setup" width="900"></p>

상세 절차와 품질 gate는 [CAMERA_CALIBRATION.md](docs/CAMERA_CALIBRATION.md), 파일별 역할은 [REPOSITORY_STRUCTURE.md](docs/REPOSITORY_STRUCTURE.md)를 따른다.

---

## 5. 터렛 기구학·실측 보정·안전 제어

AEGIS는 화면 중심을 서보 각도로 단순 비례 변환하지 않는다. Camera가 산출한 3D target을 turret 좌표계로 옮긴 뒤 실제 기구의 pivot height·arm length·laser offset·installation tilt를 반영한다.

```text
pan  = 90° − atan2(x_rel − dx_laser, z_rel − dz_laser) + pan_trim

tilt = 90° + atan2(y_rel, dist_h)
       − asin(l_arm / dist_PT)
       + tilt_trim
```

`axis_tilt`와 `axis_lean`은 pan 방향에 따른 설치 기울기 잔차를 흡수한다. `calib_data.json`에는 **PT1·PT2 각각 22개 실측 3D target–servo angle sample**이 보존되어 있으며, `calibration_turret.py`가 geometry·trim·axis correction과 depth scale을 최적화한다.

| Parameter | PT1 | PT2 |
|---|---:|---:|
| `pos_global` | `[0.0758, 0, -0.0869]` m | `[0.3755, 0, -0.0918]` m |
| `h_pivot` | 0.1280 m | 0.1280 m |
| `l_arm` | 0.0410 m | 0.0410 m |
| `dz_laser` | 0.012 m | 0.012 m |
| `pan_trim` | +4.0° | +3.0° |
| `tilt_trim` | −5.8° | −1.6° |
| `axis_tilt` | −0.81° | +0.21° |
| `axis_lean` | +0.40° | −5.80° |

전체 depth correction은 `z_scale = 0.7611`로 저장된다. 기구를 이동하거나 camera baseline을 변경하면 재측정이 필요하다.

| 보정 전후 비교 | 결과 |
|---|---:|
| PT1 Pan MAE | **35.0% 감소** |
| PT1 Tilt MAE | **37.7% 감소** |

이 개선율은 개발완료보고서의 터렛 각도 보정 전후 비교이며 3D localization 정확도와 동일한 지표가 아니다.

### Runtime Safety Gate

- pan safe range: `20°–160°`
- tilt safe range: `45°–150°`
- maximum laser distance: `2.2 m`
- short target loss: laser OFF hold
- long target loss: gradual home return
- latest-command parser, spike clamp, watchdog, serial buffer freshness
- 현재 공개 release는 새 field timing calibration 전까지 predictive lead를 보수적으로 비활성화

상세 보정 절차와 버전 차이는 [TURRET_CALIBRATION.md](docs/TURRET_CALIBRATION.md)에 정리했다.

---

## 6. AI·데이터셋·위험 판단

### Dataset Curation

- 원천 아카이브: **약 13 GB · 156,416 files · 33 folders · 약 40K candidate images**
- class-wise 유효 paired source: **13,170 images**
- Raspberry Pi 실환경 background/negative: **518 images**
- final prepared YOLO v2: **12,819 images**
- YOLO held-out test: **1,325 images / 1,436 bird instances / 67 backgrounds**
- ResNet final test: **1,375 crops**

<p align="center"><img src="assets/dataset/dataset_candidate_review.png" alt="class-wise dataset review" width="900"></p>

### 2-Stage AI

```text
YOLO bird bbox / center
→ crop quality gate
→ ResNet-18 8-class classification
→ Top-1 confidence + Top1–Top2 margin
→ 5-of-7 temporal voting
→ Explainable Risk Assessment
```

Classes/groups:

```text
crow · duck · egret · gull · pigeon · raptor · sparrow · swallow
```

`raptor`는 단일 생물학적 종이 아니므로 **8-class bird classification / 8개 조류군 분류**라고 표현한다.

### Aggregate Metrics

| Model | Metric | Result |
|---|---|---:|
| Custom YOLOv8s | Precision / Recall | **96.4% / 93.5%** |
| Custom YOLOv8s | mAP@0.5 | **97.5%** |
| Custom YOLOv8s | mAP@0.5:0.95 | **70.9%** |
| ResNet-18 | Test Accuracy | **94.76%** |
| ResNet-18 | Test Macro-F1 | **94.56%** |
| ResNet-18 | Best Val Accuracy / Macro-F1 | **95.52% / 95.20%** |

Custom YOLO 수치는 **Held-Out Offline Test**이며 live field accuracy가 아니다. Raspberry Pi 실환경 domain shift를 고려해 안정 Runtime은 YOLO26n bird detection과 ResNet-18 classification을 결합한다.

| Custom YOLO Final Training Curves | ResNet-18 Final Confusion Matrix |
|---|---|
| ![](results/yolo/training_curves.png) | ![](results/resnet/confusion_matrix.png) |

| YOLO Normalized Confusion Matrix | YOLO F1–Confidence Curve |
|---|---|
| ![](results/yolo/confusion_matrix_normalized.png) | ![](results/yolo/box_f1_curve.png) |

### ResNet Class-level Highlights

| Class / Group | Precision | Recall | F1-score |
|---|---:|---:|---:|
| crow | 91.10% | 99.43% | 95.08% |
| egret | 94.82% | 97.34% | 96.06% |
| raptor | 94.44% | 87.74% | 90.97% |
| sparrow | 95.91% | 98.80% | 97.33% |
| **Macro average** | **94.66%** | **94.57%** | **94.56%** |

8개 전체 class, support, confidence curve와 결과 해석은 [AI_RESULTS.md](docs/AI_RESULTS.md)에 정리되어 있다.

### Runtime Classification Gate

| Gate | Value |
|---|---:|
| Minimum crop side | **48 px** |
| Top-1 confidence | **≥ 0.70** |
| Top1–Top2 margin | **≥ 0.15** |
| Temporal vote | **recent 7 중 5 votes** |
| Gate failure | `UNKNOWN` |

분류 실패가 3D tracking 자체를 중단시키지 않도록 설계했으며, 불확실한 조류군은 보수적인 monitoring/track response로 처리한다.

---

## 7. AI Decision Console·Risk·강건성

AI Console은 live bird crop과 함께 다음을 표시한다.

- species/group prediction, confidence, Top1–Top2 margin, stable vote
- X / Y / Z, forward range, relative altitude signal
- approaching / crossing / leaving motion state
- Risk Score 0–100, Risk Level, Recommended Response

| Pigeon Result | Crow Result |
|---|---|
| ![](assets/ai_console/pigeon_result.png) | ![](assets/ai_console/crow_result.png) |

현재 Decision Engine은 neural network가 아니라 **설명 가능한 operational rule set**이다.

| Factor | Weight |
|---|---:|
| DistanceRisk | 30 |
| ApproachState | 20 |
| RelativeAltitude | 10 |
| SpeciesPriority | 15 |
| TrackState | 10 |
| FusionThreat | 15 |
| **Total** | **100** |

결과는 공항 인증 자동 명령이 아니라 prototype 단계의 recommended response다.

### 계층별 장애 분석

| 문제 | 원인 | 대응 |
|---|---|---|
| 프레임 지연 | 비동기 큐 누적·송신기 시간차 | 유선 Ethernet, low HWM, latest-first, corrected timestamp, sync window |
| 3D 좌표 튐 | calibration·pair 품질 편차 | 고해상도 single/stereo 보정, pair gate, runtime 좌표 재스케일 |
| 터렛 조준 오차 | 설치 기울기·laser offset | pan/tilt trim, axis_tilt/lean, 실측 target 최적화 |
| 검출 불안정 | 작은 bbox·배경·label 오염 | HSV baseline, hard negative, class-wise audit, `UNKNOWN` gate |

핵심은 모든 오차를 한 번에 덮지 않고 **통신 → 기하 → 추적 → 제어 → AI** 계층별로 원인을 분리한 것이다.

---

## 8. 저장소 구조

```text
2026ESWContest_free_AEGIS/
├─ runtime/
│  ├─ fusion_pc/
│  │  ├─ 5_final_fusion.py           # Runtime entry point
│  │  ├─ 5_final_fusion_async.py     # Detection·3D·tracking core
│  │  ├─ tcp_zmq_bridge.py           # RAW TCP 5560 → local ZMQ 5555
│  │  ├─ ai_decision_dashboard.py    # Decision Console
│  │  ├─ aegis_species_classifier.py # ResNet·gate·temporal vote
│  │  ├─ aegis_decision_engine.py    # Risk / response
│  │  ├─ 6_turret_server.py          # IK·safety·serial
│  │  ├─ calibration_turret.py       # 22-point turret fitting
│  │  ├─ config_turret.py            # Runtime config
│  │  ├─ data/                        # Runtime calibration copy
│  │  ├─ models/                      # Runtime model copy
│  │  └─ tools/                       # Calibration / validation tools
│  └─ raspberry_pi/
│     ├─ sender_TCP_5560.py
│     ├─ sender_FIXED_2.py
│     └─ sender2_FIXED_2.py
├─ firmware/arduino_uno/              # Dual Pan-Tilt firmware
├─ training/                          # Dataset audit·YOLO·ResNet training
├─ models/                            # Canonical runtime/research weights
├─ calibration/                       # 4 intrinsics + 6 stereo pairs
├─ results/                           # Final graph·CSV·JSON evidence
├─ assets/                            # System·CAD·Dataset·Console images
├─ docs/                              # Architecture·Calibration·AI·Safety
├─ scripts/                           # Minimal launch helpers
├─ START_HERE_KO.md
├─ TEAM.md
└─ THIRD_PARTY_NOTICES.md
```

119개 공개 파일의 역할, 중복 model/NPZ의 이유, configuration ownership, evidence path는 [REPOSITORY_STRUCTURE.md](docs/REPOSITORY_STRUCTURE.md)에 상세히 정리했다.

### Claim → Evidence Traceability

| 주장 | 문서 | Raw Evidence |
|---|---|---|
| Camera RMS / depth sensitivity | [METRICS.md](docs/METRICS.md) | `calibration/*.npz`, calibration setup image |
| YOLO P/R/mAP | [AI_RESULTS.md](docs/AI_RESULTS.md) | `results/yolo/results.csv`, curves, confusion matrix |
| ResNet Accuracy/Macro-F1 | [AI_RESULTS.md](docs/AI_RESULTS.md) | `results/resnet/test_summary.json`, `history.csv` |
| Turret calibration | [TURRET_CALIBRATION.md](docs/TURRET_CALIBRATION.md) | `calib_data.json`, override JSON, control code |
| Dataset curation | [DATASET.md](docs/DATASET.md) | training audit code, rules, review images |
| Team ownership | [TEAM.md](TEAM.md) | domain별 code/document path |

---

## 9. 빠른 실행

```powershell
git lfs install
git lfs pull
cd runtime\fusion_pc
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
# PyTorch/torchvision은 PC 환경에 맞는 build를 먼저 설치
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\demo_preflight.ps1
```

실행 순서:

```powershell
py -3.11 .\tcp_zmq_bridge.py
py -3.11 .\5_final_fusion.py
py -3.11 .\ai_decision_dashboard.py
py -3.11 .\6_turret_server.py
```

Raspberry Pi:

```bash
./scripts/rpi_start_sender.sh <FUSION_PC_IP>
```

방화벽·IPv4·Arduino COM·모델 점검은 [RUNBOOK.md](docs/RUNBOOK.md), 최소 시작 절차는 [START_HERE_KO.md](START_HERE_KO.md)를 따른다.

---

## 10. 팀 역할

| 구성원 | 담당 Domain | 핵심 책임 |
|---|---|---|
| **김중우** | **SYSTEM · 3D VISION · CONTROL** | CAD·기구·4CH 입력·통신·Single/Stereo calibration·triangulation·multi-pair fusion·tracking·turret·통합 환경 |
| **박주은** | **AI · DATASET · DECISION** | 데이터 수집·정제·YOLO·ResNet·quality gate·temporal voting·risk/response·AI Console 검증·정량 evidence·GitHub release |
| **공동 수행** | **INTEGRATION · EVALUATION** | 통합 시험·정량 검증·시나리오 반복·오류 분석·최종 보고서·시연 영상·발표 준비 |

역할별 세부 책임과 실제 산출물 경로는 [TEAM.md](TEAM.md)에 정리했다.

---

## 11. 기술 문서·한계·향후 확장

| 문서 | 내용 |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | End-to-End module/interface architecture |
| [OPERATION_FLOW.md](docs/OPERATION_FLOW.md) | 실제 운용 상태와 안전 전이 |
| [REPOSITORY_STRUCTURE.md](docs/REPOSITORY_STRUCTURE.md) | file-level responsibility map |
| [CAMERA_CALIBRATION.md](docs/CAMERA_CALIBRATION.md) | 4 intrinsics·6 stereo pair·quality gate |
| [TURRET_CALIBRATION.md](docs/TURRET_CALIBRATION.md) | IK·22-point fitting·safety preset |
| [AI_PIPELINE.md](docs/AI_PIPELINE.md) | dataset→YOLO→ResNet→Risk |
| [AI_RESULTS.md](docs/AI_RESULTS.md) | 그래프·class-level metrics·Runtime gate |
| [VALIDATION_AND_ROBUSTNESS.md](docs/VALIDATION_AND_ROBUSTNESS.md) | 계층별 장애요인과 안정화 |
| [SAFETY_AND_LIMITATIONS.md](docs/SAFETY_AND_LIMITATIONS.md) | laser·field·model 한계 |

현재 한계와 확장 방향:

- 공항·야외 hard-negative mining 및 field fine-tuning
- 장거리·저조도·우천 환경 검증
- 외부 기준좌표를 이용한 절대고도·world coordinate 연동
- 조류학·공항운영 데이터 기반 species-risk weight 고도화
- 다중 고정형·이동형 endpoint를 연결하는 distributed response architecture
- 풍력발전·농가·국방 경계·무인 방호 시스템으로 확장

> AEGIS는 하나의 큰 기계가 아니라, **인지–3D 위치추정–추적–판단–대응을 연결하는 범용 Embedded AI architecture**를 목표로 한다.
