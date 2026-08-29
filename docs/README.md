# AEGIS Technical Documentation

AEGIS의 대회용 상세 문서는 기술 Domain과 정량 Evidence별로 분리되어 있다.

## Start Here

| 문서 | 내용 |
|---|---|
| [REPOSITORY_STRUCTURE.md](REPOSITORY_STRUCTURE.md) | 전체 파일 트리, 핵심 파일 책임, canonical/runtime copy, evidence path |
| [OPERATION_FLOW.md](OPERATION_FLOW.md) | Boot부터 detection·3D·AI·Risk·Turret까지 운용 상태와 안전 전이 |
| [RUNBOOK.md](RUNBOOK.md) | 설치, 실행 순서, firewall, network, COM, preflight |

## Competition / Submission

| 문서 | 내용 |
|---|---|
| [CONTEST_SUBMISSION.md](CONTEST_SUBMISSION.md) | 2026 임베디드SW경진대회 GitHub 이름·Public·URL 유지·제출 전 체크리스트 |
| [PROVENANCE_AND_IMPROVEMENTS.md](PROVENANCE_AND_IMPROVEMENTS.md) | 기존 HSV/3D baseline과 2026 대회 준비 과정의 개선·추가 사항 구분 |
| [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) | OpenCV·PyTorch·Ultralytics·PySide6 등 외부 의존성 및 라이선스 주의사항 |

## Core Design

| 문서 | 내용 |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | End-to-End pipeline, module interface, 3D tracking and response architecture |
| [HARDWARE_AND_CAD.md](HARDWARE_AND_CAD.md) | A/B 감시 개념, CAD·기구 reference, 카메라·터렛 배치 |
| [CAMERA_CALIBRATION.md](CAMERA_CALIBRATION.md) | 4 intrinsics, 6 stereo pair, 품질 gate, triangulation 기준 |
| [TURRET_CALIBRATION.md](TURRET_CALIBRATION.md) | inverse kinematics, laser offset, 22-point 실측 보정, override |
| [AI_PIPELINE.md](AI_PIPELINE.md) | dataset, YOLO, ResNet, quality gate, temporal vote, risk/response pipeline |

## AI Evidence

| 문서 | 내용 |
|---|---|
| [AI_RESULTS.md](AI_RESULTS.md) | YOLO/ResNet 수치, 학습곡선, confidence curve, confusion matrix, class별 Precision/Recall/F1, Risk weight |
| [DATASET.md](DATASET.md) | 원천 규모, class-wise count, contamination audit, split |
| [`results/README.md`](../results/README.md) | 최종 선택 run의 raw graph·CSV·JSON evidence index |

## Operation & System Evidence

| 문서 | 내용 |
|---|---|
| [PROTOCOLS.md](PROTOCOLS.md) | RPi packet, ZMQ/RAW TCP, ports, Arduino command |
| [VALIDATION_AND_ROBUSTNESS.md](VALIDATION_AND_ROBUSTNESS.md) | 장애요인, 계층별 해결, tracking·safety preset |
| [METRICS.md](METRICS.md) | calibration, depth sensitivity, turret, YOLO, ResNet 정량 결과와 claim 범위 |
| [SAFETY_AND_LIMITATIONS.md](SAFETY_AND_LIMITATIONS.md) | laser·actuation 안전, 데이터·모델·현장 한계 |

## Team

- [TEAM.md](../TEAM.md): **김중우 — SYSTEM · 3D VISION · CONTROL / 박주은 — AI · DATASET · DECISION / 공동 수행 — 통합·검증·제출**
- 박주은 AI 역할에는 dataset audit, YOLO/ResNet 학습·평가, Runtime gate, temporal voting, Risk/Response, AI Console 검증, 그래프·표·GitHub evidence release가 포함된다.
