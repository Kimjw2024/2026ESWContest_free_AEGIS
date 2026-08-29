# AEGIS 빠른 시작

## 1. 저장소 준비

```powershell
git clone https://github.com/tigerjueun/AEGIS.git
cd AEGIS
git lfs install
git lfs pull
```

## 2. Windows Fusion PC

```powershell
cd runtime\fusion_pc
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\demo_preflight.ps1
```

실행:

```powershell
py -3.11 .\tcp_zmq_bridge.py
py -3.11 .\5_final_fusion.py
py -3.11 .\ai_decision_dashboard.py
py -3.11 .\6_turret_server.py
```

## 3. Raspberry Pi

```bash
./scripts/rpi_start_sender.sh <FUSION_PC_IP>
```

## 4. 환경별 필수 변경

- Fusion PC IPv4
- Arduino COM port
- 전시 하드웨어와 일치하는 calibration/override
- Windows Firewall TCP 5560 inbound rule

전체 설명은 [`docs/RUNBOOK.md`](docs/RUNBOOK.md)를 참고하세요.
