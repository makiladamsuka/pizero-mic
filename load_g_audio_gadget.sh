#!/usr/bin/env bash
# Load g_audio after the dwc2 USB device controller (UDC) is available.
set -euo pipefail

for _ in $(seq 1 30); do
    if compgen -G /sys/class/udc/* >/dev/null; then
        break
    fi
    sleep 1
done

if ! compgen -G /sys/class/udc/* >/dev/null; then
    echo "No USB device controller (UDC) found — is dtoverlay=dwc2,dr_mode=peripheral enabled?" >&2
    exit 1
fi

modprobe -r g_audio 2>/dev/null || true
modprobe g_audio
