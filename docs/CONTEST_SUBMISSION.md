# 2026 임베디드SW경진대회 소스코드 제출 체크리스트

이 문서는 **자유공모 부문 공식 안내**와 **2026 소스코드 제출 방법**에 맞춰 AEGIS GitHub 제출 상태를 고정하기 위한 체크리스트다.

## 필수 GitHub 설정

- Repository name: `2026ESWContest_free_AEGIS`
- Visibility: **Public**
- Default branch: `main`
- 제출 URL: `https://github.com/tigerjueun/2026ESWContest_free_AEGIS`
- 제출 후 심사가 끝날 때까지 Repository 주소를 변경하지 않는다.
- 수상 시 대회 종료 후에도 주소와 Public 상태를 유지한다.

## 제출 전 확인

- [ ] Repository 이름이 `2026ESWContest_free_AEGIS`인가
- [ ] Visibility가 Public인가
- [ ] 로그아웃/시크릿 창에서 README와 코드가 열리는가
- [ ] `main`이 최종 제출 버전인가
- [ ] README에 프로젝트 구조·실행법·정량 결과·팀 역할이 있는가
- [ ] 소스코드/모델/Calibration 파일 링크가 깨지지 않았는가
- [ ] 개인정보, API Key, 비밀번호, 로컬 사용자 경로가 공개본에 없는가
- [ ] 개발완료보고서의 GitHub URL이 최종 Repository 주소와 동일한가
- [ ] 홈페이지/구글폼의 소스코드 URL이 최종 Repository 주소와 동일한가

## AEGIS 공개 범위

### Runtime source

- `runtime/fusion_pc/`
  - Multi-camera Fusion
  - 3D triangulation / tracking
  - AI Decision Console
  - ResNet classifier
  - Risk/response engine
  - Turret server and calibration
- `runtime/raspberry_pi/`
  - camera sender / transport
- `firmware/arduino_uno/`
  - Dual Pan-Tilt Arduino firmware

### Training / evaluation source

- `training/`
  - dataset audit / preparation
  - custom YOLO training
  - ResNet-18 training
- `results/`
  - final YOLO/ResNet graphs, CSV, JSON
- `calibration/`
  - 4 camera intrinsics
  - 6 stereo-pair calibration files

### Documentation

- `README.md`
- `START_HERE_KO.md`
- `TEAM.md`
- `docs/`

## 제출 직후 고정 원칙

제출 URL을 홈페이지/보고서에 입력한 뒤에는 다음 작업을 하지 않는다.

- Repository rename
- Private 전환
- default branch 변경
- 제출 당시의 핵심 코드/README 삭제
- force push로 제출 commit history를 재작성

필요한 수정은 기존 URL과 `main`을 유지한 일반 commit으로만 추가한다.
