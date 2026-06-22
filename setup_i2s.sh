#!/usr/bin/env bash
# Dual INMP441 (I2S MEMS) wiring for Raspberry Pi — googlevoicehat-soundcard overlay
#
#  Mic 1 (voice)          Mic 2 (noise ref)         Raspberry Pi
#  ─────────────          ─────────────────         ────────────
#  VDD  ──────────────────────────────────────────  3.3V  (pin 1 or 17)
#  GND  ──────────────────────────────────────────  GND   (pin 6, 9, 14, …)
#  SCK  ──────────────────────────────────────────  GPIO18 (pin 12)  BCLK
#  WS   ──────────────────────────────────────────  GPIO19 (pin 35)  LRCLK
#  SD   ──┬──────────────────────────────────────  GPIO20 (pin 38)  DIN
#         └─ (both mics' SD tied together)
#  L/R  ── GND  (left channel)                     Mic 1 only
#  L/R  ── 3.3V (right channel)                    Mic 2 only
#
# Boot config (/boot/firmware/config.txt):
#   dtparam=i2s=on
#   dtoverlay=googlevoicehat-soundcard
#
# After wiring + reboot:
#   ./detect_mics.sh
#   .venv/bin/python calibrate.py
#   .venv/bin/python dual_mic_filter.py --output-wav voice.wav

set -euo pipefail
cd "$(dirname "$0")"

echo "I2S MEMS setup status:"
grep -iE 'i2s|googlevoice' /boot/firmware/config.txt || true
echo
./detect_mics.sh
