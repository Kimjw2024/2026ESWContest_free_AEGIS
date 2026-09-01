#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEMO_LAUNCHER="$REPO_ROOT/scripts/rpi_start_demo_2ch.sh"

if [[ $# -ne 1 ]]; then
    echo "Usage: bash runtime/raspberry_pi/demo_sender03.sh <FUSION_PC_IP>" >&2
    exit 2
fi

if [[ ! -f "$DEMO_LAUNCHER" ]]; then
    echo "ERROR: demo launcher not found: $DEMO_LAUNCHER" >&2
    exit 1
fi

echo "NOTICE: demo_sender03.sh is a compatibility wrapper."
echo "        Delegating to scripts/rpi_start_demo_2ch.sh (logical camera 0/1)."

exec bash "$DEMO_LAUNCHER" "$1"
