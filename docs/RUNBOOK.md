# Demo Runbook

## 1. Windows Fusion PC

Recommended: **Python 3.11**.

```powershell
git lfs install
git lfs pull
cd runtime\fusion_pc
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\demo_preflight.ps1
```

Machine-specific settings:

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object {$_.AddressState -eq "Preferred"} |
  Select-Object InterfaceAlias,IPAddress

Get-CimInstance Win32_SerialPort |
  Select-Object DeviceID,Description
```

Allow Raspberry Pi TCP input in Administrator PowerShell:

```powershell
New-NetFirewallRule `
  -DisplayName "AEGIS TCP 5560" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 5560 `
  -Action Allow `
  -Profile Any
```

Start in separate terminals:

```powershell
py -3.11 .\tcp_zmq_bridge.py
py -3.11 .\5_final_fusion.py
py -3.11 .\ai_decision_dashboard.py
py -3.11 .\6_turret_server.py
```

## 2. Raspberry Pi

```bash
python3 runtime/raspberry_pi/sender_TCP_5560.py \
  --profile runtime \
  --laptop-ip <FUSION_PC_IP> \
  --port 5560 \
  --width 640 \
  --height 360 \
  --fps 20 \
  --jpeg-quality 60 \
  --rotation 180 \
  --left-logical-id 0 \
  --right-logical-id 1 \
  --stats-interval 2
```

For the historical two-Pi / four-camera path, use `sender_FIXED_2.py` for logical cameras 0–1 and `sender2_FIXED_2.py` for 2–3.

## 3. Preflight

- [ ] Raspberry Pi detects the expected IMX219 cameras
- [ ] Pi can reach the Fusion PC IPv4
- [ ] bridge is listening before sender launch
- [ ] YOLO26n and ResNet-18 weights were pulled through Git LFS
- [ ] calibration rig geometry has not moved
- [ ] Arduino COM port and trim values are correct
- [ ] laser output follows the venue safety policy

## 4. Ports

| Port | Purpose |
|---:|---|
| 5560 | Raspberry Pi RAW TCP image stream |
| 5555 | Fusion video input after bridge |
| 5556 | Turret target/result |
| 5557 | Dashboard result PUB |
| 5558 | Dashboard command |
