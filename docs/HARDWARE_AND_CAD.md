# Hardware, CAD & Monitoring Coverage

## 1. Design Goal

기구 설계의 목적은 단순 전시용 외형 제작이 아니라 다음 세 조건을 동시에 만족하는 것이다.

1. 카메라 baseline을 고정해 calibration geometry를 유지
2. 카메라·터렛·레이저의 좌표 reference를 반복 측정 가능하게 구성
3. 저지대와 상부 영공 접근을 서로 다른 배치로 검증

<p align="center"><img src="../assets/hardware/hardware_design.png" alt="CAD and A/B monitoring hardware" width="900"></p>

## 2. A / B Monitoring Concept

### A안 — 활주로·저지대 감시

- 활주로·지평선·저지대 접근 객체를 관측하는 배치
- 상대적으로 낮은 elevation 영역의 3D 위치와 접근 방향 검증
- 터렛·이동형 음향 response와 연결하기 쉬운 지상 중심 시나리오

### B안 — 상부 영공 감시

- 카메라 optical axis를 상부로 배치해 높은 접근 경로를 관측
- 고도·접근 경로 정보를 강조하는 시나리오
- 동일한 Fusion architecture를 다른 camera layout에 적용할 수 있는지 확인

A/B안은 서로 다른 제품이 아니라 **동일한 software pipeline을 다른 mechanical layout에 적용한 coverage concept**이다.

## 3. Mechanical Reference Dimensions

아래 수치는 임베디드SW경진대회 1차 개발완료보고서의 mechanical reference다.

| Item | Reference |
|---|---:|
| 전체 조립 reference | 약 320.7 × 314.7 × 99.1 mm |
| 기판 / 베이스 | 약 60 × 580 × 15 mm |
| Camera holder | 20°형 · 약 28 × 17.1 × 76.4 mm |
| Turret holder | 약 119.6 × 111.7 × 99.1 mm |

이 값은 CAD·제작 reference이며, 전시 설치 면적이나 포장 외형과 동일한 의미는 아니다.

## 4. Camera Layout

| Segment | Measured spacing |
|---|---:|
| Camera 0–1 | 149 mm |
| Camera 1–2 | 151 mm |
| Camera 2–3 | 149 mm |
| Camera 0–3 | 약 449 mm |

`config_turret.py`에는 인접 baseline이 `0.149 / 0.151 / 0.149 m`로 기록되어 있다. 실제 3D 계산은 이 reference 값이 아니라 각 stereo calibration NPZ의 translation vector `T`를 우선 사용한다.

## 5. Turret Mechanical Reference

- Dual Pan-Tilt turret
- Arduino UNO serial control
- pan/tilt servo: MG996R/MG995-class
- pivot height `h_pivot = 0.1280 m`
- tilt arm length `l_arm = 0.0410 m`
- laser Z offset `dz_laser = 0.012 m`

설치 후에는 CAD nominal 값만으로 조준하지 않고 [TURRET_CALIBRATION.md](TURRET_CALIBRATION.md)의 실측 보정 절차를 수행한다.

## 6. Mechanical Change Policy

다음 변경이 있으면 기존 calibration을 그대로 사용하지 않는다.

- 카메라 위치·각도·focus 변경
- baseline 또는 holder 교체
- turret base 위치 변경
- pan/tilt horn 재조립
- laser module 위치 변경
- 베이스 뒤틀림 또는 운반 후 체결 상태 변화

Camera geometry 변경은 camera calibration을, turret geometry 변경은 turret calibration을 다시 수행한다.
