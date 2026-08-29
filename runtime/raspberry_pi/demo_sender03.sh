#!/usr/bin/env bash
set -e

if [ -z "$1" ]; then
    echo "Usage: ./demo_sender03.sh <LAPTOP_IP>"
    exit 1
fi

LAPTOP_IP="$1"

cd ~/aegis

echo "========================================="
echo " AEGIS DEMO SENDER - LOGICAL CAM 0 + 3"
echo " Laptop: $LAPTOP_IP"
echo "========================================="

pkill -f sender_TCP_5560.py 2>/dev/null || true
pkill -f sender_FIXED_2.py 2>/dev/null || true
pkill -9 rpicam-vid 2>/dev/null || true

sleep 1

exec python3 src/sender_TCP_5560.py \
    --profile runtime \
    --laptop-ip "$LAPTOP_IP" \
    --port 5560 \
    --fps 20 \
    --jpeg-quality 60 \
    --left-logical-id 0 \
    --right-logical-id 3 \
    --stats-interval 1
