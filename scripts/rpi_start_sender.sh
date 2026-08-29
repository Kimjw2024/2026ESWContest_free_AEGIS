#!/usr/bin/env bash
set -euo pipefail

FUSION_PC_IP="${1:?Usage: $0 <FUSION_PC_IP>}"

python3 runtime/raspberry_pi/sender_TCP_5560.py \
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
