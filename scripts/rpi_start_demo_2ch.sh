#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FUSION_PC_IP="${1:?Usage: bash scripts/rpi_start_demo_2ch.sh <FUSION_PC_IP>}"

echo "============================================================"
echo " AEGIS SIMPLIFIED 2CH DEMO"
echo " logical IDs : 0 / 1"
echo " profile     : 640x360 @ 20 FPS / JPEG Q60"
echo " transport   : RAW TCP -> ${FUSION_PC_IP}:5560"
echo "============================================================"

exec python3 "$ROOT_DIR/runtime/raspberry_pi/sender_TCP_5560.py" \
  --profile runtime \
  --laptop-ip "$FUSION_PC_IP" \
  --port 5560 \
  --width 640 \
  --height 360 \
  --fps 20 \
  --jpeg-quality 60 \
  --rotation 180 \
  --left-logical-id 0 \
  --right-logical-id 1 \
  --stats-interval 2
