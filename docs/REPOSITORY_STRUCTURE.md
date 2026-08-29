# AEGIS Repository Structure & File Responsibilities

이 문서는 대회 심사위원과 후속 개발자가 **어떤 파일부터 읽고, 각 파일이 어떤 책임을 갖는지** 빠르게 찾을 수 있도록 정리한 file-level map이다.

---

## 1. Quick Navigation

| 목적 | 먼저 볼 위치 |
|---|---|
| 프로젝트를 3분 안에 파악 | [`README.md`](../README.md) |
| Windows Fusion PC 실행 | [`START_HERE_KO.md`](../START_HERE_KO.md), [`docs/RUNBOOK.md`](RUNBOOK.md) |
| 전체 데이터 흐름 이해 | [`docs/ARCHITECTURE.md`](ARCHITECTURE.md), [`docs/OPERATION_FLOW.md`](OPERATION_FLOW.md) |
| Camera calibration 검증 | [`docs/CAMERA_CALIBRATION.md`](CAMERA_CALIBRATION.md), `calibration/` |
| Turret calibration 검증 | [`docs/TURRET_CALIBRATION.md`](TURRET_CALIBRATION.md), `runtime/fusion_pc/calib_data.json` |
| AI 학습·결과 확인 | [`docs/AI_PIPELINE.md`](AI_PIPELINE.md), [`docs/AI_RESULTS.md`](AI_RESULTS.md), `training/`, `results/` |
| 팀 역할 확인 | [`TEAM.md`](../TEAM.md) |
| 외부 라이브러리·모델 출처 | [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) |

---

## 2. Detailed Tree

```text
2026ESWContest_free_AEGIS/
│
├─ README.md                         # 심사용 프로젝트 개요·차별성·정량결과
├─ START_HERE_KO.md                  # 최소 실행 절차
├─ TEAM.md                           # 김중우 / 박주은 / 공동 수행 역할
├─ THIRD_PARTY_NOTICES.md            # 외부 라이브러리·모델·라이선스 고지
├─ .gitattributes                    # PT·NPZ 등 Git LFS tracking
├─ .gitignore                        # cache·개인설정·backup 제외
│
├─ runtime/
│  ├─ README.md                      # Runtime 구성 개요
│  ├─ fusion_pc/
│  │  ├─ 5_final_fusion.py           # Python 3.11 확인 후 async core 실행하는 entry point
│  │  ├─ 5_final_fusion_async.py     # 4CH 수신·2D 검출·stereo 3D·tracking·dashboard publish
│  │  ├─ tcp_zmq_bridge.py           # RAW TCP :5560 → local ZMQ :5555 bridge
│  │  ├─ ai_decision_dashboard.py    # Species·XYZ·Risk·Response 통합 PySide6 UI
│  │  ├─ aegis_species_classifier.py # ResNet-18 inference·quality gate·5-of-7 voting
│  │  ├─ aegis_decision_engine.py    # Explainable Risk Score / recommended response
│  │  ├─ 6_turret_server.py          # XYZ→IK→safe angle→serial control
│  │  ├─ calibration_turret.py       # PT1/PT2 실측 sample 기반 turret fitting
│  │  ├─ servo_zero_trim.py          # servo center·zero trim 보조 도구
│  │  ├─ config_turret.py            # geometry·network·AI·tracking·safety runtime config
│  │  ├─ calib_data.json             # PT1/PT2 22-point target-angle samples
│  │  ├─ turret_calibration_overrides.json
│  │  │                               # 최종 position·trim·axis·z_scale override
│  │  ├─ demo_preflight.ps1          # 필수파일·syntax preflight
│  │  ├─ demo_start_windows.ps1      # Windows multi-terminal startup helper
│  │  ├─ requirements.txt            # Windows Runtime dependency
│  │  ├─ data/
│  │  │  ├─ intrinsics_0.npz ... intrinsics_3.npz
│  │  │  └─ calib_01.npz ... calib_23.npz
│  │  ├─ models/
│  │  │  ├─ yolo26n.pt
│  │  │  └─ custom/aegis_bird_resnet18_v2.pt
│  │  └─ tools/
│  │     ├─ 1_single_calib.py
│  │     ├─ 2_stereo_calib.py
│  │     ├─ 2_stereo_calib_optimize_subset.py
│  │     ├─ 3_capture_tool.py
│  │     ├─ 4_check_calibration_results.py
│  │     ├─ 4_run_calibration_pipeline.py
│  │     ├─ 5_benchmark_yolo.py
│  │     ├─ calibration_utils.py
│  │     ├─ common.py
│  │     └─ runtime_validation.py
│  │
│  └─ raspberry_pi/
│     ├─ sender_TCP_5560.py           # 현재 1-RPi RAW-TCP runtime sender
│     ├─ sender_FIXED_2.py            # RPi #1 / logical camera 0·1 sender
│     ├─ sender2_FIXED_2.py           # RPi #2 / logical camera 2·3 sender
│     ├─ demo_sender03.sh             # Pi demo launch helper
│     └─ config_turret.example.py     # Pi-side public configuration example
│
├─ firmware/
│  └─ arduino_uno/
│     ├─ turret_uno.ino               # Dual Pan-Tilt latest-command parser·watchdog
│     └─ README.md
│
├─ training/
│  ├─ prepare_aegis_bird_data.py      # 원천 image-label pair 정리·split 구성
│  ├─ audit_yolo_missing_birds_v2.py  # missing-label / 오염 후보 audit
│  ├─ build_clean_yolo_v2.py          # manual rule 반영 clean YOLO dataset 생성
│  ├─ inspect_prepared_samples.py     # prepared sample visual inspection
│  ├─ train_yolo.py                   # custom YOLO training entry
│  ├─ train_resnet_v3_stable.py       # 최종 ResNet-18 training entry
│  ├─ audit_rules.json                # 수동 제외·검수 규칙
│  └─ README.md
│
├─ models/
│  ├─ README.md
│  ├─ detector/yolo/yolo26n.pt        # live detector
│  ├─ classifier/resnet/
│  │  └─ aegis_bird_resnet18_v2.pt    # live 8-class classifier
│  └─ research/
│     └─ aegis_bird_yolov8s_best.pt   # held-out offline research detector
│
├─ calibration/
│  ├─ README.md
│  ├─ intrinsics/
│  │  └─ intrinsics_0.npz ... intrinsics_3.npz
│  └─ stereo_pairs/
│     └─ calib_01.npz ... calib_23.npz
│
├─ results/
│  ├─ README.md
│  ├─ yolo/
│  │  ├─ training_curves.png
│  │  ├─ confusion_matrix.png
│  │  ├─ confusion_matrix_normalized.png
│  │  ├─ box_f1_curve.png
│  │  ├─ box_precision_curve.png
│  │  ├─ box_recall_curve.png
│  │  ├─ labels.jpg
│  │  └─ results.csv
│  └─ resnet/
│     ├─ confusion_matrix.png
│     ├─ history.csv
│     └─ test_summary.json
│
├─ assets/
│  ├─ ASSET_MANIFEST.json             # 공개 이미지의 Master source provenance
│  ├─ system/                         # 전체 시스템·HSV baseline
│  ├─ hardware/                       # CAD·calibration rig·RC-Car prototype
│  ├─ dataset/                        # class-wise review·dataset management
│  └─ ai_console/                     # species/Risk UI evidence
│
├─ docs/
│  ├─ README.md                       # 기술문서 인덱스
│  ├─ ARCHITECTURE.md                 # 전체 module / interface architecture
│  ├─ OPERATION_FLOW.md               # end-to-end 운용 상태·안전 전이
│  ├─ REPOSITORY_STRUCTURE.md         # 이 문서
│  ├─ HARDWARE_AND_CAD.md             # A/B 감시안·기구 reference
│  ├─ CAMERA_CALIBRATION.md           # 4 intrinsics·6 stereo pair
│  ├─ TURRET_CALIBRATION.md           # IK·22-point fitting·override
│  ├─ AI_PIPELINE.md                  # dataset→YOLO→ResNet→Risk
│  ├─ AI_RESULTS.md                   # 그래프·표·class-level metrics
│  ├─ DATASET.md                      # dataset 규모·audit·split
│  ├─ PROTOCOLS.md                    # TCP/ZMQ/Serial packet·port
│  ├─ VALIDATION_AND_ROBUSTNESS.md    # 장애요인·해결·safety preset
│  ├─ METRICS.md                      # 측정조건과 주장 범위
│  ├─ RUNBOOK.md                      # 설치·실행·firewall·COM
│  ├─ SAFETY_AND_LIMITATIONS.md       # laser·field·model 한계
│  ├─ PROVENANCE_AND_IMPROVEMENTS.md # 기존 prototype과 대회 고도화 차이
│  └─ CONTEST_SUBMISSION.md           # 제출 전 GitHub checklist
│
└─ scripts/
   ├─ run_fusion.bat                  # Windows Fusion launch
   ├─ run_turret_server.bat           # Windows Turret server launch
   ├─ rpi_start_sender.sh             # Pi sender launch
   └─ README.md
```

---

## 3. Canonical Files vs Runtime Copies

대회 repo에는 심사 증빙과 즉시 실행을 모두 만족하기 위해 일부 파일이 의도적으로 두 위치에 존재한다.

| Canonical release location | Runtime-local copy | 이유 |
|---|---|---|
| `models/detector/yolo/yolo26n.pt` | `runtime/fusion_pc/models/yolo26n.pt` | 모델 역할을 명확히 공개하면서 Runtime 상대경로를 유지 |
| `models/classifier/resnet/...pt` | `runtime/fusion_pc/models/custom/...pt` | classifier evidence와 실행 portability 동시 확보 |
| `calibration/intrinsics/*.npz` | `runtime/fusion_pc/data/intrinsics_*.npz` | Calibration 결과 인덱스와 실제 Runtime load path 동시 확보 |
| `calibration/stereo_pairs/*.npz` | `runtime/fusion_pc/data/calib_*.npz` | 6-pair evidence와 즉시 실행 가능 구조 동시 확보 |

이 중 model/NPZ 파일은 Git LFS로 관리한다. `.npz`가 GitHub 웹에서 약 129–130 byte로 보일 수 있는 것은 실제 파일이 아닌 **LFS pointer**이기 때문이다. Clone 후 `git lfs pull`을 실행하면 원본 binary가 내려온다.

---

## 4. Configuration Ownership

| File | 수정 대상 | 주의사항 |
|---|---|---|
| `config_turret.py` | IP, COM, threshold, stream, safety | 공개 기본 IP는 documentation range이며 현장 IP로 변경 |
| `turret_calibration_overrides.json` | turret position·trim·axis·z_scale | 기구 이동 시 재측정 없이 복사 사용 금지 |
| `calib_data.json` | 실측 target-angle sample | 최종 fitting 근거이므로 임의 편집 금지 |
| `calibration/*.npz` | camera intrinsic/extrinsic | camera 위치·focus·baseline 변경 시 재생성 |
| `training/audit_rules.json` | dataset exclusion rule | 학습 재현 시 source dataset version과 함께 사용 |

---

## 5. Main Execution Order

```text
Raspberry Pi sender
→ tcp_zmq_bridge.py
→ 5_final_fusion.py
→ ai_decision_dashboard.py
→ 6_turret_server.py
→ Arduino turret_uno.ino
```

- Pi가 직접 ZMQ로 보내는 구성에서는 bridge를 생략할 수 있다.
- RAW-TCP runtime을 사용할 때는 bridge가 먼저 `:5560`을 listen해야 한다.
- Fusion은 `:5555`, Turret result는 `:5556`, Dashboard는 `:5557/:5558`을 사용한다.

---

## 6. Judge-Facing Evidence Path

심사 주장과 원본 evidence의 연결은 다음과 같다.

| 주장 | 문서 | Raw evidence |
|---|---|---|
| Camera RMS / depth sensitivity | `docs/METRICS.md` | `calibration/*.npz`, calibration setup image |
| YOLO P/R/mAP | `docs/AI_RESULTS.md` | `results/yolo/results.csv`, curves, confusion matrix |
| ResNet Accuracy/Macro-F1 | `docs/AI_RESULTS.md` | `results/resnet/test_summary.json`, `history.csv` |
| Turret 보정 | `docs/TURRET_CALIBRATION.md` | `calib_data.json`, override JSON, control code |
| Dataset curation | `docs/DATASET.md` | training audit code, rules, review images |
| 역할 분담 | `TEAM.md` | domain별 code/document path |

---

## 7. Files Not Included

공개 제출본에는 다음을 포함하지 않는다.

- 13GB 원천 dataset 전체
- 수십만 개의 intermediate/backup file
- 개인정보가 포함된 참가신청서·동의서
- 로컬 절대경로·Wi-Fi credential
- `.bak`, `.WORKING`, patch script, cache, raw log
- 제출과 무관한 과거 scaffold와 중복 experiment dump

원본 전체는 별도의 `AEGIS_MASTER_FINAL` archive에 보존하고, 공개 GitHub에는 **재현 가능한 핵심 코드·설정·모델·정량 evidence**만 유지한다.
