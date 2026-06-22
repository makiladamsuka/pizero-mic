#!/usr/bin/env python3
"""
Stream noise-filtered dual-mic audio to the USB g_audio gadget.

The Pi Zero 2 W presents itself as a USB microphone to a connected PC.
Filtered audio from the I2S MEMS pair is written to the gadget playback
endpoint, which the host reads as microphone input (ideal for voice recognition).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

from dual_mic_filter import DualMicFilter, FilterConfig

MIC_DIR = Path(__file__).resolve().parent
CALIBRATION_FILE = MIC_DIR / "calibration.json"
GADGET_KEYWORDS = ("uac", "gadget", "g_audio", "usb audio gadget")


def find_gadget_playback() -> int | None:
    """Return sounddevice index for g_audio USB gadget playback (feeds host mic)."""
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_output_channels"] < 1:
            continue
        name = dev["name"].lower()
        if any(keyword in name for keyword in GADGET_KEYWORDS):
            return idx
    return None


def load_noise_scale() -> float:
    if CALIBRATION_FILE.exists():
        data = json.loads(CALIBRATION_FILE.read_text())
        return float(data.get("noise_scale", 0.85))
    return 0.85


def run(
    input_device: int,
    output_device: int,
    config: FilterConfig,
) -> None:
    processor = DualMicFilter(config)
    overflow_count = 0

    def callback(indata, outdata, _frames, _time_info, status):
        nonlocal overflow_count
        if status:
            overflow_count += 1
            if overflow_count <= 3:
                print(status, file=sys.stderr)

        if indata.shape[1] < 2:
            raise RuntimeError("Input device must provide 2 channels (stereo I2S mics).")

        filtered = processor.process_block(indata[:, 0], indata[:, 1])
        outdata[:, 0] = filtered.reshape(-1, 1)

    in_dev = sd.query_devices(input_device)
    out_dev = sd.query_devices(output_device)
    print(
        f"USB voice mic active\n"
        f"  Input:  [{input_device}] {in_dev['name']}\n"
        f"  Output: [{output_device}] {out_dev['name']}\n"
        f"  Rate:   {config.sample_rate} Hz mono, mode={config.mode}, "
        f"noise_scale={config.noise_scale:.3f}\n"
        f"Plug the Pi into your PC via USB data port. Press Ctrl+C to stop."
    )

    try:
        with sd.Stream(
            device=(input_device, output_device),
            samplerate=config.sample_rate,
            blocksize=config.block_size,
            channels=(2, 1),
            dtype="float32",
            callback=callback,
        ):
            while True:
                time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopped.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stream filtered dual-mic audio to USB gadget microphone."
    )
    parser.add_argument(
        "--input-device",
        type=int,
        default=0,
        help="ALSA input device (I2S mics, default: 0)",
    )
    parser.add_argument(
        "--output-device",
        type=int,
        default=None,
        help="ALSA output device (USB gadget; auto-detected if omitted)",
    )
    parser.add_argument("--mode", choices=["noise_cancel", "beamform"], default="noise_cancel")
    parser.add_argument("--noise-scale", type=float, default=None)
    parser.add_argument("--sample-rate", type=int, default=48000)
    parser.add_argument("--block-size", type=int, default=2048)
    parser.add_argument("--list-devices", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.list_devices:
        print(sd.query_devices())
        gadget = find_gadget_playback()
        print(f"\nGadget playback device: {gadget}")
        return

    output_device = args.output_device
    if output_device is None:
        output_device = find_gadget_playback()
        if output_device is None:
            print(
                "USB audio gadget not found. Run setup first:\n"
                "  sudo ./setup_usb_gadget.sh\n"
                "Then reboot and plug the Pi into your PC via USB.",
                file=sys.stderr,
            )
            sys.exit(1)

    noise_scale = args.noise_scale if args.noise_scale is not None else load_noise_scale()
    config = FilterConfig(
        sample_rate=args.sample_rate,
        block_size=args.block_size,
        mode=args.mode,
        noise_scale=noise_scale,
    )
    run(args.input_device, output_device, config)


if __name__ == "__main__":
    main()
