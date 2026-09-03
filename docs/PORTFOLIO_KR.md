# AEGIS — 개인 포트폴리오 정리

> 이 문서는 공동 프로젝트 AEGIS를 개인 포트폴리오 관점에서 정리한 안내 문서입니다. 프로젝트의 원본 코드·문서·커밋 이력은 유지하고, 팀의 기여와 출처를 명확히 기록합니다.

## 프로젝트 개요

AEGIS는 공항 주변의 조류 충돌(Bird-Strike) 위험을 감지하고 대응하기 위한 AI·다중 카메라·3D 비전·팬틸트 제어 통합 시스템입니다. 두 대의 Raspberry Pi에서 4개 카메라 영상을 수집하고, Fusion PC에서 새 검출과 다중 baseline stereo 3D 위치 추정을 수행한 뒤, 위험 판단 콘솔과 이중 pan-tilt 터렛으로 결과를 전달합니다.

이 저장소는 [원본 공동 프로젝트 저장소](https://github.com/tigerjueun/2026ESWContest_free_AEGIS)를 기반으로 한 개인 GitHub 포트폴리오용 public mirror입니다. 원본 저장소의 소유권이나 팀 전체의 기여를 대체하지 않습니다.

## 나의 담당 영역

원본 `TEAM.md`에 기록된 역할을 기준으로 정리했습니다.

| 구성원 | 담당 영역 | 주요 기여 |
| --- | --- | --- |
| 김중우 | **SYSTEM · 3D VISION · CONTROL** | 시스템·하드웨어 구성, 2-Raspberry Pi / 4CH 영상 입력과 통신, 카메라 보정과 3D 비전, 터렛·제어, 전체 통합 |
| 박주은 | **AI · DATASET · DECISION** | 데이터셋 정제, YOLO·ResNet 학습, 분류·위험 판단 게이트, AI Decision Console, 정량 근거와 GitHub 릴리스 |
| 공동 | **INTEGRATION · EVALUATION · SUBMISSION** | 전체 시스템 통합, 평가, 대회 제출 |

### 개인 기여를 설명하는 핵심 문장

저는 AEGIS의 시스템 통합과 카메라 입력·통신 경로를 구성하고, 여러 카메라의 보정 결과를 이용한 3D 위치 추정 및 터렛 제어가 하나의 runtime 흐름으로 연결되도록 구현·검증했습니다. AI 모듈은 팀의 AI 담당 영역과 결합하여 최종 시연 시스템으로 통합했습니다.

## 시스템 흐름

```text
4 cameras
  └─ Raspberry Pi #1 (cam0, cam1) + Raspberry Pi #2 (cam2, cam3)
       └─ Fusion PC
            ├─ HSV / YOLO bird detection
            ├─ 6 stereo-pair triangulation
            ├─ multi-baseline 3D localization
            └─ temporal tracking / hold
                 ├─ :5556 → dual pan-tilt turret tracking
                 └─ :5557 → AI Decision Console / risk response
```

주요 runtime 계약은 다음과 같습니다.

- Full 4CH runtime은 두 Raspberry Pi의 영상을 직접 ZMQ/JPEG로 Fusion PC에 전달하며 기본 수신 포트는 `:5555`입니다.
- 추정된 3D target은 터렛 경로 `:5556`으로 전달되고, AI Decision Console은 별도의 `:5557` 경로를 사용합니다.
- 4개 카메라에서 `01`, `02`, `03`, `12`, `13`, `23`의 6개 stereo pair를 구성합니다.
- 단순화된 2CH demo 모드와 4CH calibration 모드는 원본 [runtime 문서](RUNTIME_MODES.md)에 구분되어 있습니다.

상세한 데이터 계약과 실행 순서는 [시스템 구조](ARCHITECTURE.md), [통신 프로토콜](PROTOCOLS.md), [실행 가이드](RUNBOOK.md)를 참고합니다.

## 기술적 결과

아래 수치는 원본 저장소의 문서와 결과표에 기록된 오프라인·검증 데이터입니다. 실제 현장 성능이나 모든 환경에서의 보장을 의미하지 않습니다.

### Camera calibration / 3D vision

- 카메라: IMX219 4대, 6개 stereo pair
- Checkerboard square size: `25 mm`
- 단일 카메라 calibration RMS: `0.154–0.181 px`
- Stereo calibration RMS: `0.217–0.289 px`
- 여러 baseline에서의 triangulation과 temporal filtering을 사용하여 검출 결과를 3D target으로 변환

캘리브레이션 산출물과 검증 조건은 [카메라 보정 문서](CAMERA_CALIBRATION.md)와 [강건성 검증 문서](VALIDATION_AND_ROBUSTNESS.md)에 분리해 두었습니다.

### Bird AI / decision support

- 8개 조류 그룹: crow, duck, egret, gull, pigeon, raptor, sparrow, swallow
- Custom YOLOv8s offline: precision `96.4%`, recall `93.5%`, mAP@0.5 `97.5%`, mAP@0.5:0.95 `70.9%`
- ResNet-18 classification: test accuracy `94.76%`, macro-F1 `94.56%`
- YOLO는 후보 영역 검출, ResNet-18은 crop 분류, temporal voting과 risk gate는 runtime 의사결정에 사용

평가 분할과 산출 방법은 [AI 결과](AI_RESULTS.md), 전체 파이프라인은 [AI 파이프라인](AI_PIPELINE.md)에서 확인할 수 있습니다.

## 저장소에서 먼저 볼 자료

| 목적 | 문서 |
| --- | --- |
| 전체 프로젝트를 빠르게 이해 | [`START_HERE_KO.md`](../START_HERE_KO.md) |
| 개인 역할과 출처 확인 | [`TEAM.md`](../TEAM.md), 이 문서 |
| 시스템 구성과 데이터 흐름 | [`ARCHITECTURE.md`](ARCHITECTURE.md), [`OPERATION_FLOW.md`](OPERATION_FLOW.md) |
| 실제 실행 전 확인 | [`RUNBOOK.md`](RUNBOOK.md), [`SAFETY_AND_LIMITATIONS.md`](SAFETY_AND_LIMITATIONS.md) |
| 성능 수치의 근거 | [`METRICS.md`](METRICS.md), [`VALIDATION_AND_ROBUSTNESS.md`](VALIDATION_AND_ROBUSTNESS.md) |
| 카메라·터렛 보정 | [`CAMERA_CALIBRATION.md`](CAMERA_CALIBRATION.md), [`TURRET_CALIBRATION.md`](TURRET_CALIBRATION.md) |
| AI와 데이터셋 | [`AI_PIPELINE.md`](AI_PIPELINE.md), [`AI_RESULTS.md`](AI_RESULTS.md), [`DATASET.md`](DATASET.md) |

## 실행 및 재현 범위

이 저장소는 코드와 문서, Git LFS로 관리되는 모델·캘리브레이션 산출물을 포함한 통합 프로젝트 기록입니다. 전체 시스템을 재현하려면 Raspberry Pi 2대, 4개 카메라, Fusion PC, 터렛·제어 보드, 네트워크 설정과 각 장치의 calibration이 필요합니다.

실행 전에는 반드시 [START_HERE_KO.md](../START_HERE_KO.md)와 [RUNBOOK.md](RUNBOOK.md)를 읽어야 합니다. 프로그램을 실행하는 것만으로 실제 관절·터렛 명령이 안전하게 검증되는 것은 아니며, 하드웨어 연결·포트·보정 상태는 별도로 확인해야 합니다.

원본 학습 데이터 전체와 제3자 라이브러리의 권리는 이 저장소에 자동으로 포함되지 않습니다. 원본 [제3자 고지](../THIRD_PARTY_NOTICES.md)를 확인하고, Ultralytics 및 각 모델의 라이선스 조건을 재배포·상업 이용 전에 다시 검토해야 합니다.

## 출처와 감사의 글

- Original upstream: [tigerjueun/2026ESWContest_free_AEGIS](https://github.com/tigerjueun/2026ESWContest_free_AEGIS)
- 공동 프로젝트: 김중우 · 박주은
- 대회 맥락: 2026 임베디드SW경진대회 자유공모 부문

이 포트폴리오 mirror의 목적은 공동 프로젝트를 개인 포트폴리오에서 설명하기 쉽게 정리하는 것입니다. 원본 저장소의 README, 팀 역할 문서, 기술 문서와 결과표를 함께 확인하면 구현 범위와 기여 경계를 정확히 이해할 수 있습니다.
