# Raspberry Pi Camera Senders

## Canonical Full 4CH

| Edge Node | Physical CSI | Logical Camera | Sender |
|---|---|---|---|
| Raspberry Pi #1 | camera 0 / 1 | img0 / img1 | `sender_FIXED_2.py` |
| Raspberry Pi #2 | camera 0 / 1 | img2 / img3 | `sender2_FIXED_2.py` |

Runtime:

```bash
bash scripts/rpi_start_sender.sh rpi1 <FUSION_PC_IP> runtime
bash scripts/rpi_start_sender.sh rpi2 <FUSION_PC_IP> runtime
```

Profile:

```text
640×360 @ 30 FPS
JPEG Q70
direct ZMQ/JPEG → Fusion PC :5555
```

Calibration:

```bash
bash scripts/rpi_start_sender.sh rpi1 <FUSION_PC_IP> calibration
bash scripts/rpi_start_sender.sh rpi2 <FUSION_PC_IP> calibration
```

Profile:

```text
1280×720 @ 20 FPS
JPEG Q76
```

## Simplified 2CH Demo

```bash
bash scripts/rpi_start_demo_2ch.sh <FUSION_PC_IP>
```

- sender: `sender_TCP_5560.py`
- logical camera: 0 / 1
- profile: 640×360 @ 20 FPS, Q60
- transport: RAW TCP `:5560`
- Fusion PC requires `tcp_zmq_bridge.py`

This demo path does not replace the canonical 2-RPi / 4-camera system.
