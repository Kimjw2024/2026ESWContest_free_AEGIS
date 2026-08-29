# Runtime

AEGIS의 실제 시연·재현 기준 코드를 모은 디렉터리다.

## Canonical Full System

```text
Raspberry Pi #1 / Camera 0·1
Raspberry Pi #2 / Camera 2·3
        ↓ direct ZMQ/JPEG :5555
Fusion PC
```

- [`fusion_pc/`](fusion_pc/) — 4CH Fusion, AI Console, ResNet, Risk Engine, Turret server
- [`raspberry_pi/`](raspberry_pi/) — Full 4CH sender와 Simplified 2CH sender

## Runtime Modes

| Mode | Main sender | Fusion-side receiver |
|---|---|---|
| Full 4CH | `sender_FIXED_2.py` + `sender2_FIXED_2.py` | direct Fusion ZMQ `:5555` |
| Simplified 2CH | `sender_TCP_5560.py` | `tcp_zmq_bridge.py` |
| Calibration | full senders with `--profile calibration` | calibration capture tools |

전체 실행 순서는 [`../docs/RUNBOOK.md`](../docs/RUNBOOK.md), 정확한 mode 구분은 [`../docs/RUNTIME_MODES.md`](../docs/RUNTIME_MODES.md)를 따른다.
