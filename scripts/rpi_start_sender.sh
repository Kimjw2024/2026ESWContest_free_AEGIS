#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/rpi_start_sender.sh <rpi1|rpi2> <FUSION_PC_IP> [runtime|calibration]

Examples:
  bash scripts/rpi_start_sender.sh rpi1 <FUSION_PC_IP> runtime
  bash scripts/rpi_start_sender.sh rpi2 <FUSION_PC_IP> runtime
  bash scripts/rpi_start_sender.sh rpi1 <FUSION_PC_IP> calibration
  bash scripts/rpi_start_sender.sh rpi2 <FUSION_PC_IP> calibration

Canonical topology:
  rpi1 -> logical camera 0 / 1
  rpi2 -> logical camera 2 / 3
  direct ZMQ/JPEG -> Fusion PC port 5555
EOF
}

if [[ $# -lt 2 || $# -gt 3 ]]; then
  usage
  exit 2
fi

ROLE="$1"
FUSION_PC_IP="$2"
PROFILE="${3:-runtime}"

if [[ "$PROFILE" != "runtime" && "$PROFILE" != "calibration" ]]; then
  echo "ERROR: profile must be 'runtime' or 'calibration'." >&2
  exit 2
fi

case "$ROLE" in
  rpi1)
    SENDER="$ROOT_DIR/runtime/raspberry_pi/sender_FIXED_2.py"
    LEFT_ID=0
    RIGHT_ID=1
    ;;
  rpi2)
    SENDER="$ROOT_DIR/runtime/raspberry_pi/sender2_FIXED_2.py"
    LEFT_ID=2
    RIGHT_ID=3
    ;;
  *)
    echo "ERROR: role must be 'rpi1' or 'rpi2'." >&2
    usage
    exit 2
    ;;
esac

if [[ ! -f "$SENDER" ]]; then
  echo "ERROR: sender not found: $SENDER" >&2
  exit 1
fi

echo "============================================================"
echo " AEGIS FULL 4CH SENDER"
echo " role        : $ROLE"
echo " logical IDs : $LEFT_ID / $RIGHT_ID"
echo " profile     : $PROFILE"
echo " Fusion PC   : $FUSION_PC_IP:5555"
echo "============================================================"

exec python3 "$SENDER" \
  --profile "$PROFILE" \
  --laptop-ip "$FUSION_PC_IP" \
  --port 5555 \
  --left-logical-id "$LEFT_ID" \
  --right-logical-id "$RIGHT_ID" \
  --stats-interval 2
