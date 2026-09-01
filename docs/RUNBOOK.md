# AEGIS Deployment & Demo Runbook

## 1. Canonical System

AEGIS의 기준 구성은 다음과 같다.

```text
Raspberry Pi #1 + Camera 0/1
Raspberry Pi #2 + Camera 2/3
        ↓ direct ZMQ/JPEG :5555
Windows Fusion PC
        ↓ HSV / YOLO → 6 Stereo Pair → 3D Tracking
        ├→ :5556 → Turret Server → Arduino Dual Pan-Tilt
        └→ :5557 → AI Console → ResNet / Risk / Recommendation display
```

두 출력은 병렬이다. Turret Server는 AI Console을 거치지 않고 Fusion Track3D target/result를 `:5556`에서 직접 받는다. AI Console은 `:5557`을 구독하는 read-only 의사결정 지원 화면이며 현재 reserved `:5558` command input으로 명령을 보내지 않는다.

Mode별 차이는 [`RUNTIME_MODES.md`](RUNTIME_MODES.md)를 따른다.

## 2. Windows Fusion PC Installation

Recommended: **Python 3.11**.

```powershell
git clone https://github.com/tigerjueun/2026ESWContest_free_AEGIS.git
cd 2026ESWContest_free_AEGIS
git lfs install
git lfs pull

cd runtime\fusion_pc
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

PyTorch와 torchvision은 PC의 CPU/CUDA 환경에 맞는 build를 먼저 설치한다.

```text
https://pytorch.org/get-started/locally/
```

이후:

```powershell
pip install -r requirements.txt
python -c "import torch, torchvision, PIL; print(torch.__version__)"
powershell -ExecutionPolicy Bypass -File .\demo_preflight.ps1 -Mode full4ch
```

## 3. Machine-Specific Settings

Fusion PC IPv4:

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object {$_.AddressState -eq "Preferred"} |
  Select-Object InterfaceAlias,IPAddress
```

Arduino COM:

```powershell
Get-CimInstance Win32_SerialPort |
  Select-Object DeviceID,Description
```

Update locally:

- `runtime/fusion_pc/config_turret.py`
  - Fusion PC IP placeholder / environment override
  - Arduino COM
- `runtime/fusion_pc/turret_calibration_overrides.json`
  - current physical rig only
- `runtime/fusion_pc/calib_data.json`
  - must belong to the same latest turret-calibration session as the override
- calibration NPZ
  - current camera positions/focus/baseline only

### Network requirement

Full 4CH does not depend on a specific physical medium; it depends on **mutual IPv4 reachability** among the two RPi nodes and the Fusion PC.

- contest / long-running demo: **wired LAN recommended**
- integration / development: same-subnet Wi-Fi LAN is supported and has been validated with the final 2-RPi/4CH system
- guest networks with client isolation can block RPi → Fusion TCP even when Internet access works
- use the actual current Fusion PC IPv4 in both sender launch commands

A quick RPi-side TCP test is preferable to ICMP ping when Windows or the venue network blocks ping:

```bash
python3 - <<'PY'
import socket
host = "<FUSION_PC_IP>"
port = 5555
s = socket.socket()
s.settimeout(5)
try:
    s.connect((host, port))
    print("TCP 5555 SUCCESS", host, port)
except Exception as e:
    print("TCP 5555 FAIL", repr(e))
finally:
    s.close()
PY
```

## 4. Windows Firewall

Administrator PowerShell:

```powershell
# Full 4CH direct ZMQ/JPEG input
New-NetFirewallRule `
  -DisplayName "AEGIS Full 4CH ZMQ 5555" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 5555 `
  -Action Allow `
  -Profile Any

# Simplified 2CH RAW-TCP demo
New-NetFirewallRule `
  -DisplayName "AEGIS Demo TCP 5560" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 5560 `
  -Action Allow `
  -Profile Any
```

## 5. Full 4CH Runtime

### 5.1 Fusion PC

```powershell
cd runtime\fusion_pc
.\.venv\Scripts\Activate.ps1
powershell -ExecutionPolicy Bypass -File .\demo_start_windows.ps1 -Mode full4ch
```

Full 4CH는 다음 세 프로그램을 실행한다.

```text
5_final_fusion.py
ai_decision_dashboard.py
6_turret_server.py
```

`tcp_zmq_bridge.py`는 Full 4CH에서 실행하지 않는다.

`6_turret_server.py`와 `ai_decision_dashboard.py`는 직렬 연결이 아니다. 전자는 `:5556` Track3D packet, 후자는 `:5557` dashboard snapshot을 각각 독립적으로 구독한다.

### 5.2 Raspberry Pi #1

```bash
cd 2026ESWContest_free_AEGIS
bash scripts/rpi_start_sender.sh rpi1 <FUSION_PC_IP> runtime
```

Expected:

```text
sender_id = rpi1
physical CSI0/1 → logical camera 0/1
640×360 @ 30 FPS
JPEG Q70
ZMQ/JPEG → Fusion PC :5555
```

### 5.3 Raspberry Pi #2

```bash
cd 2026ESWContest_free_AEGIS
bash scripts/rpi_start_sender.sh rpi2 <FUSION_PC_IP> runtime
```

Expected:

```text
sender_id = rpi2
physical CSI0/1 → logical camera 2/3
640×360 @ 30 FPS
JPEG Q70
ZMQ/JPEG → Fusion PC :5555
```

### 5.4 Full 4CH Validation

Fusion UI에서 확인:

- `img0 / img1 / img2 / img3`
- sender IDs `rpi1 / rpi2`
- fresh timestamp and sequence
- required pairs `01 / 12 / 23`
- additional pairs `02 / 03 / 13`
- Track3D lock
- `:5556` turret target packet이 Fusion에서 직접 갱신됨
- `:5557` AI Console에서 ResNet stable vote와 risk/recommendation이 병렬 갱신됨
- Console을 종료해도 Fusion/Turret 제어 경로가 독립적으로 유지됨

Turret server에서 확인:

- Arduino serial connected, not simulation mode
- `lock / same_lock` state
- live laser keepalive
- no persistent spike-clamp events under normal motion
- top-to-bottom tilt tracking uses the current direction-aware backlash compensation

## 6. 4CH Camera Calibration

Fusion PC에서 capture/calibration tool을 준비한 뒤:

```bash
# RPi #1
bash scripts/rpi_start_sender.sh rpi1 <FUSION_PC_IP> calibration

# RPi #2
bash scripts/rpi_start_sender.sh rpi2 <FUSION_PC_IP> calibration
```

Expected profile:

```text
1280×720 @ 20 FPS
JPEG Q76
logical camera 0/1 and 2/3
```

Calibration sequence:

```text
4 single-camera intrinsics
→ 6 stereo pairs: 01 / 02 / 03 / 12 / 13 / 23
→ quality gate
→ runtime coordinate scaling validation
```

## 7. Turret Recalibration

Use this after a mechanical turret/camera relocation or when the current physical rig no longer matches the stored override.

1. Keep both RPi senders and Fusion running.
2. Switch Fusion to **HSV** for repeatable geometric targeting.
3. Stop `6_turret_server.py` so that `calibration_turret.py` has exclusive Arduino access.
4. Run:

```powershell
cd runtime\fusion_pc
py -3.11 .\calibration_turret.py
```

5. Latest field procedure: **20 target positions per turret**, spread across horizontal/vertical position and depth.
6. Current calibration/debug HSV target is the blue table-tennis ball configured in `config_turret.py`.
7. Save and visually verify the generated result.
8. Restart Fusion and turret server so the newly generated override is reloaded.
9. Commit `calib_data.json` and `turret_calibration_overrides.json` together.

The current runtime additionally applies field-tuned **0.80° downward tilt compensation to PT1 and PT2** to address repeatable top-to-bottom servo hysteresis. This is a runtime mechanical compensation layer, not a substitute for static multi-point calibration.

## 8. Simplified 2CH Demo

이 경로는 1-RPi / 2-Camera 축소 경로다.

### Fusion PC

```powershell
cd runtime\fusion_pc
.\.venv\Scripts\Activate.ps1
powershell -ExecutionPolicy Bypass -File .\demo_start_windows.ps1 -Mode demo2ch
```

The launcher starts:

```text
tcp_zmq_bridge.py
5_final_fusion.py
ai_decision_dashboard.py
6_turret_server.py
```

### Raspberry Pi

```bash
bash scripts/rpi_start_demo_2ch.sh <FUSION_PC_IP>
```

Expected:

```text
logical camera 0/1
640×360 @ 20 FPS
JPEG Q60
RAW TCP :5560 → bridge → ZMQ :5555
```

이 모드는 Full 4CH 구조와 정량 주장을 대체하지 않는다.

## 9. Ports

| Port | Direction | Purpose |
|---:|---|---|
| 5555 | RPi → Fusion | Full 4CH direct ZMQ/JPEG input; demo bridge local output |
| 5556 | Fusion → Turret | direct Track3D target/result control input |
| 5557 | Fusion → Console | frames/XYZ/motion/evidence for ResNet/risk display |
| 5558 | Reserved command client → Fusion | reserved input; current Console is read-only and does not send |
| 5560 | RPi → Bridge | Simplified 2CH RAW-TCP input |
| Serial 115200 | Turret server → Arduino | pan/tilt/laser command |

## 10. Preflight Checklist

- [ ] Repository clone URL is the final contest URL
- [ ] `git lfs pull` completed
- [ ] YOLO/ResNet `.pt` files are not pointer-sized
- [ ] 4 intrinsics and 6 stereo-pair `.npz` files are loaded
- [ ] PyTorch/torchvision/Pillow and `requirements.txt` modules import successfully
- [ ] Both Raspberry Pis detect physical CSI camera 0 and 1
- [ ] RPi #1 publishes logical camera 0/1
- [ ] RPi #2 publishes logical camera 2/3
- [ ] RPi nodes can reach Fusion TCP 5555 on the selected LAN
- [ ] Fusion PC firewall allows TCP 5555
- [ ] Arduino COM/baud and turret override match the current rig
- [ ] `calib_data.json` and `turret_calibration_overrides.json` are from the latest same calibration session
- [ ] camera/holder/baseline did not move after calibration
- [ ] laser output follows venue safety policy

## 11. Fresh Clone / Git LFS Verification

From an external folder or another PC:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify_release_clone.ps1 -KeepClone
```

Then install the Python environment in that fresh clone and run:

```powershell
cd runtime\fusion_pc
powershell -ExecutionPolicy Bypass -File .\demo_preflight.ps1 -Mode full4ch
```
