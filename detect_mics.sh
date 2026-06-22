#!/usr/bin/env bash
# Quick check: are the Pi and ALSA seeing microphone hardware?

set -euo pipefail

echo "=== Raspberry Pi model ==="
tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo "unknown"
echo

echo "=== USB devices ==="
if lsusb | grep -qv "root hub"; then
    lsusb
else
    echo "No USB devices found (only root hub)."
    echo "If using USB mics: use a data-capable OTG adapter and ideally a powered USB hub."
fi
echo

echo "=== ALSA capture cards (arecord -l) ==="
if arecord -l 2>&1 | grep -q "card"; then
    arecord -l
else
    echo "No capture hardware detected."
fi
echo

echo "=== Loaded sound modules ==="
lsmod | grep -E '^snd' || echo "none"
echo

echo "=== Boot audio config (/boot/firmware/config.txt) ==="
grep -iE 'dtparam=audio|dtparam=i2s|dtparam=i2c|dtoverlay=.*audio|dtoverlay=.*i2s|dtoverlay=.*voice|dtoverlay=.*seeed|dtoverlay=.*google' /boot/firmware/config.txt 2>/dev/null || true
echo

echo "=== Python sounddevice view ==="
if [[ -x "$(dirname "$0")/.venv/bin/python" ]]; then
    "$(dirname "$0")/.venv/bin/python" "$(dirname "$0")/dual_mic_filter.py" --list-devices
else
    echo "Run from mic/ folder after creating .venv"
fi
echo

echo "=== USB gadget (g_audio) ==="
if ls /sys/class/udc/* >/dev/null 2>&1; then
    echo "UDC ready: $(ls /sys/class/udc/)"
else
    echo "No UDC — add dtoverlay=dwc2,dr_mode=peripheral under [all] in config.txt, then reboot."
fi
if lsmod | grep -q '^g_audio'; then
    echo "g_audio loaded — Pi can act as USB microphone when plugged into a PC."
    if [[ -x "$(dirname "$0")/.venv/bin/python" ]]; then
        "$(dirname "$0")/.venv/bin/python" "$(dirname "$0")/usb_voice_mic.py" --list-devices 2>/dev/null | tail -3 || true
    fi
else
    echo "g_audio not loaded. To use as USB mic: sudo ./setup_usb_gadget.sh && reboot"
fi
