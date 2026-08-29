# Baseline Provenance & 2026 Competition Improvements

2026 공통 규정은 기존 소프트웨어를 개선한 작품의 경우 **기존 소프트웨어의 출처, 개선점, 추가 사항**을 개발완료보고서에 상세히 기술하도록 요구한다. AEGIS는 장기간 단계적으로 고도화된 프로젝트이므로 아래처럼 개발 이력을 구분한다.

## 1. 이전 단계 Baseline

초기 AEGIS prototype은 다음 기능을 중심으로 구성되었다.

- Raspberry Pi + IMX219 multi-camera input
- HSV 기반 2D target detection baseline
- camera calibration / stereo triangulation
- 3D coordinate estimation
- basic track smoothing / prediction
- Arduino pan-tilt turret control

이 baseline은 **기하·통신·제어 End-to-End feasibility 검증**을 위한 단계였다.

## 2. 2026 임베디드SW경진대회 준비 과정의 주요 고도화

### AI / Dataset

- 8개 조류군 class-wise dataset 구축 및 정제
- image/label pairing audit, contamination review, hard-negative/background 수집
- custom YOLOv8s bird detector 학습·평가
- ResNet-18 8-class classifier 학습·평가
- confidence / margin / crop-quality gate
- track-level temporal voting과 `UNKNOWN` fallback

### 3D Vision / Calibration

- camera 0–3 single calibration 정량 검증
- `01 / 02 / 03 / 12 / 13 / 23` 6개 stereo-pair calibration
- multi-baseline depth sensitivity 분석
- calibration/runtime coordinate rescaling
- robust multi-pair fusion과 tracking 안정화

### Turret / Control

- real-mechanism inverse kinematics
- pivot / arm / laser offset 반영
- pan/tilt trim, axis tilt/lean 보정
- PT1·PT2 실측 target–servo sample 기반 turret calibration
- servo smoothing, hold, distance/safety gate

### Runtime / Decision

- wired/RAW-TCP/latest-first transport 경로
- AI Decision Console
- species/group + XYZ + motion + tracking evidence 기반 explainable Risk Score
- recommended response 출력
- 고정형 turret 외 mobile acoustic prototype 확장

### Validation / Submission

- YOLO/ResNet final-run evidence 정리
- calibration RMS / depth sensitivity / turret residual 정량화
- runtime source, training code, calibration data, firmware, models를 GitHub release 구조로 정리
- 역할·한계·claim 범위를 문서화

## 3. 외부 오픈소스와 자작 부분 구분

AEGIS는 OpenCV, PyTorch, Ultralytics, ZeroMQ, PySide6 등 공개 라이브러리를 활용한다. 이들 프레임워크 자체를 자작 기술로 주장하지 않는다.

Team AEGIS의 주요 자체 개발 범위는 다음과 같다.

- 4-camera system integration
- 6-pair calibration workflow and deployment
- multi-pair 3D fusion / tracking integration
- camera-to-turret coordinate integration and calibration
- dataset curation / audit pipeline
- YOLO/ResNet application pipeline and runtime gating
- Risk/Decision Console integration
- embedded communication and response-system integration

세부 오픈소스 표기는 [`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)를 따른다.
