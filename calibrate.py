#!/usr/bin/env python3
"""Calibrate dual-mic noise cancellation gain using ambient-only recording."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

CALIBRATION_FILE = Path(__file__).resolve().parent / "calibration.json"


def calibrate(device: int | None, sample_rate: int, seconds: float, save: bool) -> float:
    import sounddevice as sd

    print("Stay quiet for calibration (ambient noise only)...")
    time.sleep(1.0)

    recording = sd.rec(
        int(seconds * sample_rate),
        samplerate=sample_rate,
        channels=2,
        device=device,
        dtype="float32",
    )
    sd.wait()

    primary = recording[:, 0]
    reference = recording[:, 1]

    num = np.dot(primary, reference)
    den = np.dot(reference, reference) + 1e-12
    scale = float(num / den)

    print(f"\nRecommended --noise-scale: {scale:.3f}")
    if save:
        CALIBRATION_FILE.write_text(
            json.dumps({"noise_scale": round(scale, 4), "sample_rate": sample_rate}, indent=2)
            + "\n"
        )
        print(f"Saved: {CALIBRATION_FILE}")
    print("Run capture with:")
    print(f"  python3 dual_mic_filter.py --noise-scale {scale:.3f} --output-wav voice.wav")
    print("Or start USB mic:")
    print("  python3 usb_voice_mic.py")
    return scale


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate dual-mic noise scale.")
    parser.add_argument("--device", type=int, default=None)
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--sample-rate", type=int, default=48000)
    parser.add_argument(
        "--save",
        action="store_true",
        help="Write noise_scale to calibration.json for usb_voice_mic.py",
    )
    args = parser.parse_args()
    calibrate(args.device, args.sample_rate, args.seconds, args.save)


if __name__ == "__main__":
    main()
