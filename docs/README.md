# AEGIS Technical Documentation

AEGIS의 대회용 상세 문서는 기술 Domain과 정량 Evidence별로 분리되어 있다.

## Start Here

| 문서 | 내용 |
|---|---|
| [RUNTIME_MODES.md](RUNTIME_MODES.md) | Full 4CH / Simplified 2CH / Calibration mode 구분 |
| [RUNBOOK.md](RUNBOOK.md) | 설치, 2-RPi/4CH 실행, firewall, COM, preflight |
| [OPERATION_FLOW.md](OPERATION_FLOW.md) | 입력부터 안전 복귀까지 운용 상태 |
| [REPOSITORY_STRUCTURE.md](REPOSITORY_STRUCTURE.md) | file-level responsibility map |

## Competition / Submission

| 문서 | 내용 |
|---|---|
| [CONTEST_SUBMISSION.md](CONTEST_SUBMISSION.md) | GitHub 이름·Public·URL 유지·fresh clone 체크 |
| [PROVENANCE_AND_IMPROVEMENTS.md](PROVENANCE_AND_IMPROVEMENTS.md) | 기존 HSV/3D baseline과 2026 고도화 구분 |
| [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) | 외부 의존성 및 라이선스 주의사항 |

## Core Design

| 문서 | 내용 |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 2-RPi / 4-Camera End-to-End architecture |
| [HARDWARE_AND_CAD.md](HARDWARE_AND_CAD.md) | A/B 감시 개념, CAD·기구 reference |
| [CAMERA_CALIBRATION.md](CAMERA_CALIBRATION.md) | 4 intrinsics, 6 stereo pair, quality gate |
| [TURRET_CALIBRATION.md](TURRET_CALIBRATION.md) | IK, laser offset, 22-point calibration |
| [PROTOCOLS.md](PROTOCOLS.md) | Full 4CH direct ZMQ와 2CH RAW-TCP demo |
| [VALIDATION_AND_ROBUSTNESS.md](VALIDATION_AND_ROBUSTNESS.md) | 장애요인, tracking·safety preset |

## AI & Dataset Evidence

| 문서 | 내용 |
|---|---|
| [AI_PIPELINE.md](AI_PIPELINE.md) | dataset, YOLO, ResNet, gate, vote, risk |
| [AI_RESULTS.md](AI_RESULTS.md) | graph, confusion matrix, class별 P/R/F1 |
| [DATASET.md](DATASET.md) | 규모, audit, split, source-provenance policy |
| [METRICS.md](METRICS.md) | 수치와 claim 범위 |
| [`results/README.md`](../results/README.md) | raw graph·CSV·JSON evidence index |

## Safety / Team

| 문서 | 내용 |
|---|---|
| [SAFETY_AND_LIMITATIONS.md](SAFETY_AND_LIMITATIONS.md) | laser·field·model 한계 |
| [TEAM.md](../TEAM.md) | 김중우 / 박주은 / 공동 수행 역할 |
