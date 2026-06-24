#!/usr/bin/env bash
# Quick USB microphone gadget health check (run on the Pi).

set -euo pipefail
cd "$(dirname "$0")"

echo "=== USB gadget status ==="
if compgen -G /sys/class/udc/* >/dev/null; then
    UDC="$(basename "$(ls -d /sys/class/udc/* | head -1)")"
    echo "UDC:        $UDC"
    echo "State:      $(cat "/sys/class/udc/$UDC/state")"
    echo "Speed:      $(cat "/sys/class/udc/$UDC/current_speed")"
    echo "Function:   $(cat "/sys/class/udc/$UDC/function" 2>/dev/null || echo n/a)"
else
    echo "ERROR: No USB device controller. Add dtoverlay=dwc2,dr_mode=peripheral under [all] in config.txt."
fi

if lsmod | grep -q '^g_audio'; then
    echo "g_audio:    loaded ($(cat /sys/module/g_audio/parameters/iProduct 2>/dev/null || echo unknown))"
else
    echo "ERROR: g_audio not loaded. Run: sudo ./setup_usb_gadget.sh && sudo reboot"
fi

echo
echo "=== Services ==="
systemctl is-active g-audio-gadget.service usb-voice-mic.service 2>/dev/null || true

echo
echo "=== Audio routing (Pi -> PC mic) ==="
echo "I2S capture (MEMS mics):"
arecord -l 2>/dev/null | grep -E 'card|device' | head -6 || true
echo "USB gadget playback (feeds host microphone):"
aplay -l 2>/dev/null | grep -E 'UAC|card|device' | head -6 || true

echo
echo "=== Interpretation ==="
STATE="$(cat "/sys/class/udc/"*/state 2>/dev/null | head -1 || true)"
case "$STATE" in
    configured)
        echo "OK: A host computer has enumerated the Pi over USB."
        echo "    On your PC, look for input device: Dual MEMS Voice Mic"
        echo "    If missing on PC, try: unplug USB -> wait 5s -> replug (data cable, not charge-only)."
        ;;
    not\ attached|"")
        echo "Pi USB is NOT connected to a host (or cable has no data lines)."
        echo "Use a data-capable micro-USB cable into your computer's USB port."
        echo "Boot the Pi first, wait ~30s, then plug USB into the PC."
        ;;
    *)
        echo "USB state is '$STATE' — try replugging the cable after the Pi has fully booted."
        ;;
esac
