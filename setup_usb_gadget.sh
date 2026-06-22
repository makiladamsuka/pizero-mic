#!/usr/bin/env bash
# Configure Pi Zero 2 W as a USB microphone (g_audio gadget) for voice recognition.
#
# After setup + reboot, plug the Pi's micro-USB data port into your computer.
# The PC will see a USB microphone; filtered audio is streamed automatically
# if the usb-voice-mic service is enabled.

set -euo pipefail

MIC_DIR="$(cd "$(dirname "$0")" && pwd)"
BOOT_DIR="/boot/firmware"
CONFIG="$BOOT_DIR/config.txt"
CMDLINE="$BOOT_DIR/cmdline.txt"

if [[ $EUID -ne 0 ]]; then
    echo "Run as root: sudo $0"
    exit 1
fi

echo "=== 1. Enable USB gadget (peripheral) mode ==="
# dwc2 must live under [all] — Pi Zero 2 W ignores [cm4]/[cm5]-only overlays.
if grep -A20 '^\[all\]' "$CONFIG" | grep -q 'dtoverlay=dwc2'; then
    if ! grep -A20 '^\[all\]' "$CONFIG" | grep -q 'dr_mode=peripheral'; then
        sed -i '/^\[all\]/,/^\[/ s/dtoverlay=dwc2\(.*\)/dtoverlay=dwc2,dr_mode=peripheral/' "$CONFIG"
        echo "Updated [all] dwc2 overlay to peripheral mode."
    else
        echo "[all] dwc2 peripheral overlay already configured."
    fi
else
    sed -i '/^\[all\]/a dtoverlay=dwc2,dr_mode=peripheral' "$CONFIG"
    echo "Added dtoverlay=dwc2,dr_mode=peripheral under [all] in config.txt."
fi

echo
echo "=== 2. Load dwc2 at boot; defer g_audio until UDC is ready ==="
echo 'dwc2' > /etc/modules-load.d/dwc2.conf
echo "Wrote /etc/modules-load.d/dwc2.conf"

# modules-load= in cmdline.txt is ignored on current Pi OS kernels.
sed -i 's/ modules-load=dwc2,g_audio//g' "$CMDLINE"
rm -f /etc/modules-load.d/g_audio.conf

echo
echo "=== 3. Configure USB microphone (48 kHz mono) ==="
cat > /etc/modprobe.d/g_audio.conf <<'EOF'
# Capture = what the host PC records (microphone). 48 kHz mono suits voice recognition.
options g_audio \
    iManufacturer="Raspberry Pi" \
    iProduct="Dual MEMS Voice Mic" \
    c_chmask=0x1 c_srate=48000 c_ssize=2 \
    p_chmask=0x1 p_srate=48000 p_ssize=2
EOF
echo "Wrote /etc/modprobe.d/g_audio.conf"

echo
echo "=== 4. Install systemd services ==="
cp "$MIC_DIR/g-audio-gadget.service" /etc/systemd/system/g-audio-gadget.service
cp "$MIC_DIR/usb-voice-mic.service" /etc/systemd/system/usb-voice-mic.service

systemctl daemon-reload
systemctl enable g-audio-gadget.service
systemctl enable usb-voice-mic.service
echo "Enabled g-audio-gadget.service and usb-voice-mic.service."

echo
echo "=== 5. Calibrate noise cancellation (optional) ==="
if [[ -x "$MIC_DIR/.venv/bin/python" ]]; then
    sudo -u methoonema "$MIC_DIR/.venv/bin/python" "$MIC_DIR/calibrate.py" --device 0 --save || true
else
    echo "Skip: venv not found. Run calibrate.py manually after reboot."
fi

echo
echo "=== Done ==="
echo "Reboot now:  sudo reboot"
echo
echo "After reboot:"
echo "  1. Plug Pi micro-USB DATA port into your computer (not just power)."
echo "  2. On your PC, select 'Dual MEMS Voice Mic' as the input device."
echo "  3. Service status:  systemctl status usb-voice-mic"
echo "  4. Manual test:     cd ~/mic && .venv/bin/python usb_voice_mic.py"
