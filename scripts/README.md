# Launch & Verification Scripts

## Full 4CH

```bash
bash scripts/rpi_start_sender.sh rpi1 <FUSION_PC_IP> runtime
bash scripts/rpi_start_sender.sh rpi2 <FUSION_PC_IP> runtime
```

- direct ZMQ/JPEG `:5555`
- 4 Camera / 2 RPi
- 640×360 @ 30 FPS, Q70

## Calibration

```bash
bash scripts/rpi_start_sender.sh rpi1 <FUSION_PC_IP> calibration
bash scripts/rpi_start_sender.sh rpi2 <FUSION_PC_IP> calibration
```

- 1280×720 @ 20 FPS, Q76

## Simplified 2CH Demo

```bash
bash scripts/rpi_start_demo_2ch.sh <FUSION_PC_IP>
```

- RAW TCP `:5560`
- 2 Camera / 1 RPi
- 640×360 @ 20 FPS, Q60

## Windows Helpers

- `run_fusion.bat` — Fusion entrypoint
- `run_turret_server.bat` — turret server
- `runtime/fusion_pc/demo_start_windows.ps1 -Mode full4ch`
- `runtime/fusion_pc/demo_start_windows.ps1 -Mode demo2ch`

## Release Verification

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify_release_clone.ps1 -KeepClone
```

This fresh-clone check verifies Git LFS model/calibration downloads before submission.

See [`../docs/RUNBOOK.md`](../docs/RUNBOOK.md).
