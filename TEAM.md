# Team AEGIS — 역할 및 공동 수행 범위

본 문서는 2026 임베디드SW경진대회 개발완료보고서 20페이지의 Domain 구분을 그대로 따른다.

| 구성원 | 담당 Domain |
|---|---|
| **김중우** | **SYSTEM · 3D VISION · CONTROL** |
| **박주은** | **AI · DATASET · DECISION** |
| **공동 수행** | **INTEGRATION · EVALUATION · SUBMISSION** |

역할표는 각 Domain의 **주 책임**을 나타낸다. 실제 End-to-End 시스템은 모듈 간 interface와 반복 통합 시험이 필수이므로, 전체 동작 검증·오류 분석·전시 준비·제출은 공동 수행으로 관리한다.

---

## 김중우 — SYSTEM · 3D VISION · CONTROL

### 01. 시스템 · 하드웨어

- 전체 시스템 구조와 감시 시나리오 설계
- 3D CAD, 카메라 거치대, 터렛 거치대, 베이스 제작·배치
- 카메라 4대와 Dual Pan-Tilt 터렛 조립
- 활주로·저지대 감시 A안과 상부 영공 감시 B안 구성
- 카메라 인접 baseline `149 / 151 / 149 mm`와 outer baseline 약 `449 mm` 실측
- 터렛 피벗·암·레이저 offset 등 기구 reference 치수 정리

### 02. 영상 입력 · 통신

- 4CH Camera 입력 구조 구성
- Raspberry Pi dual-camera sender 및 logical camera ID 관리
- ZMQ/JPEG와 유선 Ethernet 기반 영상 전송
- calibration용 `1280×720 / 20 FPS / JPEG Q76`과 runtime용 `640×360 / 30 FPS / JPEG Q70` profile 분리
- low HWM, latest-frame 우선, timestamp/sync window를 이용한 지연 누적 억제
- 2-RPi / 4CH packet 구조와 Fusion 입력 interface 구성

### 03. 캘리브레이션 · 3D Vision

- Camera 0–3 Single calibration
- `01 / 02 / 03 / 12 / 13 / 23` 6개 Stereo Pair calibration
- checkerboard image 수집, corner detection, RMS·유효 pair 품질 검증
- rectification, triangulation, pair별 좌표 변환과 multi-pair fusion
- calibration `1280×720` 좌표와 runtime `640×360` 좌표 재스케일
- 필수 연결 pair `01 / 12 / 23`과 redundancy pair `02 / 03 / 13` 운용
- Track3D 입력 구조, pair reliability, timestamp consistency 검증

### 04. 터렛 · 예측 제어

- 터렛 inverse kinematics와 camera-to-turret 좌표계 변환
- pivot height, arm length, laser optical offset 반영
- pan/tilt trim, axis_tilt, axis_lean 보정
- LPF/Kalman, velocity estimation, predictive lead, track hold
- servo smoothing, pan/tilt safety limit, laser distance gate
- PT1·PT2 각각 22개 실측 target–servo sample 수집 및 parameter fitting
- `turret_calibration_overrides.json` 생성·검증과 dual-laser convergence 확인

### 05. 시스템 통합

- Fusion UI와 모듈 interface 연결
- Camera/RPi → Fusion → Turret → Arduino 실행 파이프라인 구성
- 실증 환경 구성 및 시스템 단위 동작 확인
- 기구·통신·3D·제어 계층의 오류 분리와 수정
- 프레임 지연·3D 좌표 튐·조준 잔차의 원인 분석 및 안정화

---

## 박주은 — AI · DATASET · DECISION

### 01. 조류 데이터셋 구축 · 정제 · 품질 관리

- 8개 조류군별 원천 이미지·라벨 수집 및 class-wise 폴더 구조 관리
- 원천 작업 아카이브 약 **13 GB / 156,416 files / 33 folders / 약 40K candidate images** 관리
- image/label pairing, 중복·저해상도·흐림·비조류·오라벨·invalid box 검수
- missing-label audit와 manual exclusion rule 구성
- 클래스별 유효 paired source **13,170 images** 정리
- Raspberry Pi 실환경 background/hard-negative **518 images** 통합
- detector와 classifier 목적에 맞춘 train/validation/test 구성
- final prepared YOLO v2 **12,819 images**와 held-out test split 관리
- class-wise candidate review, contamination evidence, audit script와 결과 문서화

### 02. YOLO 조류 검출 · Runtime/Research 모델 분리

- bird bbox/center 검출 구조 설계
- 3D Fusion 입력을 위한 `Detection2D` center 표준화
- live detector인 YOLO26n bird class와 custom YOLOv8s 연구 모델의 역할 분리
- Custom YOLOv8s 학습 pipeline, checkpoint, final selected run 관리
- 작은 bbox, 거리, 배경 변화에 따른 오검출·누락 분석
- 공항·야외 배경 hard-negative mining 전략 수립
- Held-Out Offline Test 정량 평가 및 결과 검수

| Custom YOLOv8s Metric | Result |
|---|---:|
| Precision | **96.4%** |
| Recall | **93.5%** |
| mAP@0.5 | **97.5%** |
| mAP@0.5:0.95 | **70.9%** |

- training curve, confusion matrix, normalized confusion matrix, F1/P/R confidence curve 추출·정리
- Raspberry Pi field domain-shift false positive 분석과 field fine-tuning roadmap 정리

### 03. ResNet-18 8-class 조류군 분류

- YOLO bbox crop 기반 ResNet-18 classifier 학습·평가
- `crow / duck / egret / gull / pigeon / raptor / sparrow / swallow` class 구성
- crop size, Top-1 confidence, Top1–Top2 margin quality gate 설계
- 기준 미달 시 `UNKNOWN` 처리
- track-level recent 7 frame 중 5 vote temporal voting 적용
- 분류 실패 시에도 3D tracking이 중단되지 않도록 비동기·독립 구조 적용
- class-wise Precision/Recall/F1, confusion matrix와 취약 class 분석

| ResNet-18 Metric | Result |
|---|---:|
| Test Accuracy | **94.76%** |
| Test Macro-F1 | **94.56%** |
| Best Validation Accuracy | **95.52%** |
| Best Validation Macro-F1 | **95.20%** |

- Raptor recall 저하, Crow precision, Sparrow F1 등 class-level 결과 해석
- final weight, class map, Runtime gate와 inference code 패키징

### 04. 위험도 · 대응 로직

- 거리, 상대고도, 접근 상태, 조류군, track state, Fusion threat evidence를 결합한 Risk Score 설계
- Risk Score `0–100`과 `LOW / MEDIUM / HIGH / CRITICAL` 단계화
- 조류군별 prototype priority와 `UNKNOWN` fallback 정의
- 접근·교차·이탈 motion state 분석
- 터렛 추적·음향 대응·모니터링 recommended response rule 구성
- 분류 신뢰도가 낮을 때 과도한 물리 대응을 막는 보수적 fallback 설계
- Risk 결과를 AI Decision Console과 response layer에 연결

### 05. AI 결과 검증 · Runtime 통합 · Evidence/Release

- AI Decision Console 구성·검증
- live crop, raw/stable class, confidence, Top1–Top2 margin, temporal vote 시각화
- XYZ, forward range, relative altitude, motion, risk, response 정보 연계
- YOLO/ResNet inference를 Fusion Runtime에 연결하고 classification failure 시 tracking continuity 확인
- AI 오검출·분류 불안정·field domain shift 사례 분석
- YOLO·ResNet 최종 수치, 그래프, confusion matrix, class별 표 작성
- 모델 weight, result CSV/JSON, dataset evidence, 실행 문서를 GitHub 공개 구조로 정리
- Git LFS 모델 관리, README·AI 문서·정량 claim 범위 정리
- 임소경 보고서·PPT에서 AI 수치를 live field accuracy로 과장하지 않도록 표기 원칙 검수
- Custom YOLO 연구 결과와 안정 Runtime model policy를 구분해 재현 가능한 release 구성

### 박주은 AI 산출물 인덱스

```text
training/prepare_aegis_bird_data.py
training/audit_yolo_missing_birds_v2.py
training/build_clean_yolo_v2.py
training/train_yolo.py
training/train_resnet_v3_stable.py
training/audit_rules.json

runtime/fusion_pc/aegis_species_classifier.py
runtime/fusion_pc/aegis_decision_engine.py
runtime/fusion_pc/ai_decision_dashboard.py

results/yolo/*
results/resnet/*
docs/AI_PIPELINE.md
docs/AI_RESULTS.md
docs/DATASET.md
```

---

## 공동 수행 — INTEGRATION · EVALUATION · SUBMISSION

- 개발 배경·문제 정의와 최종 시스템 시나리오 정리
- 전체 모듈 통합 시험
- 정량 성능 검증과 결과 해석
- 시나리오 반복 실험
- 프레임 지연·좌표 튐·조준 오차·AI 오검출 원인 분석
- 하드웨어 조립·전시·안전 점검
- RC-Car Acoustic Response Extension Prototype 구성·사진·확장 시나리오 정리
- 최종 보고서, 시연 영상, 발표 자료, 질의응답 준비
- 제출 링크, GitHub 공개 범위, 개인정보·절대경로·대용량 데이터 점검

---

## 역할 구분 원칙

- 위 표는 PPT 20페이지의 Domain ownership을 유지한다.
- 개별 모듈의 주 담당과 End-to-End 통합 기여는 구분한다.
- AI 수치·그래프·표의 세부 근거는 [`docs/AI_RESULTS.md`](docs/AI_RESULTS.md)에 정리한다.
- 통합 시험·오류 분석·대회 제출은 양 팀원이 공동 수행한다.
