# 2026 임베디드SW경진대회 소스코드 제출 체크리스트

## 1. Final Repository Identity

- Repository name: `2026ESWContest_free_AEGIS`
- Default branch: `main`
- Final URL: `https://github.com/tigerjueun/2026ESWContest_free_AEGIS`
- Final submission visibility: **Public**

팀 내부 검토 기간에는 Private + Collaborator를 사용할 수 있지만, **대회 제출 전에 반드시 Public으로 전환**하고 로그아웃/시크릿 창에서 접근을 확인한다.

## 2. Canonical System Claim

- Full system: **2 Raspberry Pi / 4 Camera**
- Full runtime: direct ZMQ/JPEG over mutually reachable IPv4 LAN → `:5555`
- Full profile: `640×360 @ 30 FPS, Q70`
- Calibration: `1280×720 @ 20 FPS, Q76`
- Simplified demo: `1 RPi / 2 Camera / RAW TCP :5560 / 20 FPS / Q60`
- Latest turret field recalibration: **20 points per turret**
- Current field-tuned downward tilt compensation: **PT1 0.80° / PT2 0.80°**

README·PPT·영상에서 Full 4CH와 Simplified 2CH를 혼용하지 않는다. 유선 LAN은 대회/장시간 운용의 권장 medium이며, protocol claim은 direct ZMQ/JPEG over IPv4 LAN으로 유지한다.

## 3. Submission Checklist

- [ ] repository 이름이 최종 형식인가
- [ ] 제출 직전 visibility가 Public인가
- [ ] 시크릿 창에서 README·코드·이미지가 열리는가
- [ ] `main`이 최종 제출 버전인가
- [ ] `START_HERE_KO.md` clone URL이 최종 주소인가
- [ ] `git lfs pull` 후 `.pt` / `.npz` 원본이 내려오는가
- [ ] `demo_preflight.ps1 -Mode full4ch`가 통과하는가
- [ ] RPi #1이 logical camera 0/1을 송신하는가
- [ ] RPi #2가 logical camera 2/3을 송신하는가
- [ ] RPi #1/#2가 실제 Fusion PC IPv4의 TCP 5555에 도달 가능한가
- [ ] README에 Full 4CH / 2CH Demo mode 차이가 명시되었는가
- [ ] latest `config_turret.py`와 `6_turret_server.py`가 final field tune과 일치하는가
- [ ] `calib_data.json`과 `turret_calibration_overrides.json`이 **같은 최신 20-point calibration session**에서 생성된 파일인가
- [ ] PyTorch/torchvision/Pillow 설치 절차가 문서화되었는가
- [ ] 외부 데이터 source ledger와 이용조건을 내부 확인했는가
- [ ] 개인정보·API Key·비밀번호·실제 Wi-Fi credential·개인 로컬 경로가 없는가
- [ ] PPT/홈페이지/중우 공유 링크가 동일한 최종 URL인가

## 4. Fresh Clone Verification

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify_release_clone.ps1 -KeepClone
```

Fresh clone에서 Python 환경을 설치한 뒤:

```powershell
cd runtime\fusion_pc
powershell -ExecutionPolicy Bypass -File .\demo_preflight.ps1 -Mode full4ch
```

가능하면 실제 제출 직전 한 번은 fresh clone에서 다음까지 확인한다.

```text
Full 4CH sender files present
→ 4-camera calibration assets resolve through Git LFS
→ Fusion imports/compiles
→ latest turret calibration artifacts present
→ README/doc links render
```

## 5. Freeze Policy

제출 URL 입력 후에는 다음을 하지 않는다.

- repository rename
- Private 전환
- default branch 변경
- 핵심 코드·README 삭제
- force push로 제출 history 재작성

필요한 수정은 같은 URL과 `main`을 유지하는 일반 commit으로만 추가한다.
