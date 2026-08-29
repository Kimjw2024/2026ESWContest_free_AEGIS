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

Private 검토 기간에는 저장소 초대를 수락한 GitHub 계정으로 인증해야 한다. 대회 제출 전에는 저장소를 Public으로 전환한다.

## 2. 실행 모드

| Mode | Camera / Edge | Transport | Stream Profile | Purpose |
|---|---|---|---|---|
| **Full 4CH AEGIS Runtime** | 4 Camera / 2 RPi | direct ZMQ/JPEG → `:5555` | **640×360 @ 30 FPS, Q70** | 기준 End-to-End 시스템 |
| **Simplified 2CH Demo** | 2 Camera / 1 RPi | RAW TCP `:5560` → local ZMQ `:5555` | **640×360 @ 20 FPS, Q60** | 축소 재현·백업 시연 |
| **4CH Calibration** | 4 Camera / 2 RPi | direct ZMQ/JPEG → `:5555` | **1280×720 @ 20 FPS, Q76** | 4 intrinsics / 6 stereo-pair 보정 |

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

수동 실행 시에는 **bridge를 실행하지 않는다.**

```powershell
python .\5_final_fusion.py
python .\ai_decision_dashboard.py
python .\6_turret_server.py
```

### Raspberry Pi #1 — logical camera 0 / 1

각 Pi에서 저장소 루트로 이동한 뒤:

```bash
bash scripts/rpi_start_sender.sh rpi1 <FUSION_PC_IP> runtime
```

### Raspberry Pi #2 — logical camera 2 / 3

```bash
bash scripts/rpi_start_sender.sh rpi2 <FUSION_PC_IP> runtime
```

두 sender는 Fusion PC의 ZMQ/JPEG input `tcp://<FUSION_PC_IP>:5555`로 직접 연결된다.

## 5. 4CH Calibration Capture

Fusion PC의 calibration capture tool을 실행한 상태에서 두 Pi를 calibration profile로 시작한다.

```bash
# Raspberry Pi #1
bash scripts/rpi_start_sender.sh rpi1 <FUSION_PC_IP> calibration

# Raspberry Pi #2
bash scripts/rpi_start_sender.sh rpi2 <FUSION_PC_IP> calibration
```

Calibration profile은 `1280×720 @ 20 FPS, JPEG Q76`을 사용한다.

## 6. Simplified 2CH Demo

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

## 7. 환경별 필수 변경

- Fusion PC의 유선 IPv4
- Windows Firewall:
  - Full 4CH: TCP `5555` inbound
  - 2CH Demo: TCP `5560` inbound
- Arduino COM port와 baud `115200`
- 전시 기구와 일치하는 camera NPZ / turret override
- 레이저·액추에이터 현장 안전 규칙

전체 절차와 장애 대응은 [`docs/RUNBOOK.md`](docs/RUNBOOK.md), mode 정의는 [`docs/RUNTIME_MODES.md`](docs/RUNTIME_MODES.md)를 참고한다.
