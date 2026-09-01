# AEGIS 빠른 시작

AEGIS의 **기준 구성은 Raspberry Pi 2대 / IMX219 4대 / 6 Stereo Pair**다.  
1-RPi / 2-Camera RAW-TCP 경로는 전체 4CH 시스템과 분리된 간소화 데모다.

## 1. 저장소 준비

```powershell
git clone https://github.com/tigerjueun/2026ESWContest_free_AEGIS.git
cd 2026ESWContest_free_AEGIS
git lfs install
git lfs pull
```

Private 검토 기간에는 저장소 초대를 수락한 GitHub 계정으로 인증해야 한다. 대회 제출 전에는 저장소를 Public으로 전환하고 로그아웃/시크릿 창에서 clone URL 접근을 확인한다.

## 2. 실행 모드

| Mode | Camera / Edge | Transport | Stream Profile | Purpose |
|---|---|---|---|---|
| **Full 4CH AEGIS Runtime** | 4 Camera / 2 RPi | direct ZMQ/JPEG over IPv4 LAN → `:5555` | **640×360 @ 30 FPS, Q70** | 기준 End-to-End 시스템 |
| **Simplified 2CH Demo** | 2 Camera / 1 RPi | RAW TCP `:5560` → local ZMQ `:5555` | **640×360 @ 20 FPS, Q60** | 축소 재현·백업 시연 |
| **4CH Calibration** | 4 Camera / 2 RPi | direct ZMQ/JPEG over IPv4 LAN → `:5555` | **1280×720 @ 20 FPS, Q76** | 4 intrinsics / 6 stereo-pair 보정 |

전체 시스템 성능·구조 설명은 **Full 4CH AEGIS Runtime**을 기준으로 한다.

## 3. Windows Fusion PC 설치

```powershell
cd runtime\fusion_pc
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

PyTorch와 torchvision은 PC의 CPU/CUDA 환경에 맞는 build를 먼저 설치한다.

```text
https://pytorch.org/get-started/locally/
```

설치 후:

```powershell
pip install -r requirements.txt
python -c "import torch, torchvision, PIL; print(torch.__version__)"
powershell -ExecutionPolicy Bypass -File .\demo_preflight.ps1 -Mode full4ch
```

## 4. Full 4CH Runtime 실행

### Fusion PC

활성화된 가상환경에서:

```powershell
powershell -ExecutionPolicy Bypass -File .\demo_start_windows.ps1 -Mode full4ch
```

수동 실행 시에는 **bridge를 실행하지 않는다.** 아래 3개 프로그램은 한 창에서 순서대로 실행하지 말고, **각각 별도의 새 PowerShell 창**에서 실행한다.

PowerShell #1 — Fusion:

```powershell
cd <REPO_ROOT>\runtime\fusion_pc
.\.venv\Scripts\python.exe .\5_final_fusion.py
```

PowerShell #2 — AI Decision Dashboard:

```powershell
cd <REPO_ROOT>\runtime\fusion_pc
.\.venv\Scripts\python.exe .\ai_decision_dashboard.py
```

PowerShell #3 — Dual Turret Server:

```powershell
cd <REPO_ROOT>\runtime\fusion_pc
.\.venv\Scripts\python.exe .\6_turret_server.py
```

파란 탁구공으로 촬영·검증할 때는 Fusion 창을 클릭해 키보드 포커스를 준 뒤 `T`를 눌러 화면의 **`Detect: HSV`** 표시를 확인한다. 이전 track이 남아 있거나 좌표가 비정상적으로 유지되면 Fusion 창에서 `R`을 눌러 track을 reset한다.

### Raspberry Pi #1 — logical camera 0 / 1

각 Pi에서 저장소 루트로 이동한 뒤:

```bash
bash scripts/rpi_start_sender.sh rpi1 <FUSION_PC_IP> runtime
```

### Raspberry Pi #2 — logical camera 2 / 3

```bash
bash scripts/rpi_start_sender.sh rpi2 <FUSION_PC_IP> runtime
```

두 sender는 Fusion PC의 ZMQ/JPEG input `tcp://<FUSION_PC_IP>:5555`로 직접 연결된다. 두 RPi와 Fusion PC는 서로 TCP 통신 가능한 같은 IPv4 LAN에 있어야 한다. 장시간 시연에는 유선을 권장하지만 동일 subnet Wi-Fi에서도 Full 4CH direct-ZMQ 경로를 사용할 수 있다.

## 5. 4CH Calibration Capture

Fusion PC의 calibration capture tool을 실행한 상태에서 두 Pi를 calibration profile로 시작한다.

```bash
# Raspberry Pi #1
bash scripts/rpi_start_sender.sh rpi1 <FUSION_PC_IP> calibration

# Raspberry Pi #2
bash scripts/rpi_start_sender.sh rpi2 <FUSION_PC_IP> calibration
```

Calibration profile은 `1280×720 @ 20 FPS, JPEG Q76`을 사용한다.

## 6. Turret Field Recalibration

카메라/터렛 기구가 움직였거나 레이저 정렬을 다시 잡아야 할 때:

1. 두 Pi sender와 Fusion은 유지한다.
2. Fusion을 **HSV**로 전환한다.
3. `6_turret_server.py`를 종료해 Arduino COM을 비운다.
4. 실행:

```powershell
cd runtime\fusion_pc
py -3.11 .\calibration_turret.py
```

최종 통합 리그에서는 파란 탁구공 HSV target을 사용해 PT1/PT2 각각 **20-point field recalibration**을 수행했다. 저장 후 `calib_data.json`과 `turret_calibration_overrides.json`은 같은 calibration session의 파일로 함께 관리한다.

현재 runtime은 top-to-bottom tilt servo hysteresis를 위해 PT1/PT2 각각 **0.80° downward compensation**을 추가로 적용한다.

## 7. Simplified 2CH Demo

2-camera 데모에서만 TCP→ZMQ bridge를 사용한다.

### Fusion PC

```powershell
powershell -ExecutionPolicy Bypass -File .\demo_start_windows.ps1 -Mode demo2ch
```

### Raspberry Pi

```bash
bash scripts/rpi_start_demo_2ch.sh <FUSION_PC_IP>
```

이 경로는 logical camera `0/1`, `640×360 @ 20 FPS, Q60`을 사용하며 Full 4CH 성능을 대체하지 않는다.

## 8. 환경별 필수 변경

- 현재 Fusion PC IPv4
- RPi #1/#2와 Fusion PC의 mutual TCP reachability
- Windows Firewall:
  - Full 4CH: TCP `5555` inbound
  - 2CH Demo: TCP `5560` inbound
- Arduino COM port와 baud `115200`
- 전시 기구와 일치하는 camera NPZ / `calib_data.json` / turret override
- 레이저·액추에이터 현장 안전 규칙

전체 절차와 장애 대응은 [`docs/RUNBOOK.md`](docs/RUNBOOK.md), mode 정의는 [`docs/RUNTIME_MODES.md`](docs/RUNTIME_MODES.md)를 참고한다.
