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
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd

from dual_mic_filter import DualMicFilter, FilterConfig

MIC_DIR = Path(__file__).resolve().parent
CALIBRATION_FILE = MIC_DIR / "calibration.json"
GADGET_KEYWORDS = ("uac", "gadget", "g_audio", "usb audio gadget")
I2S_KEYWORDS = ("googlevoicehat", "voicehat", "snd_rpi_googlevoicehat")


def _device_name(dev: object) -> str:
    return str(dev["name"]).lower() if isinstance(dev, dict) else str(dev).lower()


def find_gadget_playback() -> int | str | None:
    """Return sounddevice index for g_audio USB gadget playback (feeds host mic).

    PortAudio often misreports UAC2 gadget directions (shows 1 in / 0 out for the
    playback endpoint that feeds the host microphone). Match by name first.
    """
    fallback: int | str | None = None
    for idx, dev in enumerate(sd.query_devices()):
        name = _device_name(dev)
        if not any(keyword in name for keyword in GADGET_KEYWORDS):
            continue
        if dev["max_output_channels"] >= 1:
            return idx
        fallback = idx
    if fallback is not None:
        return fallback
    for candidate in ("hw:1,0", "default:CARD=UAC2Gadget,DEV=0"):
        try:
            sd.query_devices(candidate)
            return candidate
        except Exception:
            continue
    return None


def find_i2s_input() -> int | str:
    """Return the dual I2S MEMS capture device (googlevoicehat overlay)."""
    for idx, dev in enumerate(sd.query_devices()):
        name = _device_name(dev)
        if any(keyword in name for keyword in I2S_KEYWORDS):
            if dev["max_input_channels"] >= 2:
                return idx
            return idx
    return "hw:0,0"


def load_noise_scale() -> float:
    if CALIBRATION_FILE.exists():
        data = json.loads(CALIBRATION_FILE.read_text())
        return float(data.get("noise_scale", 0.85))
    return 0.85


def calibrate_noise_floor(
    input_device: int | str,
    config: FilterConfig,
    seconds: float = 1.5,
) -> float:
    """Record ambient audio and return the measured RMS noise floor in dB."""
    print(f"[VAD] Measuring noise floor for {seconds:.1f}s — stay quiet...")
    try:
        recording = sd.rec(
            int(seconds * config.sample_rate),
            samplerate=config.sample_rate,
            channels=2,
            device=input_device,
            dtype="float32",
        )
        sd.wait()
        # Use the primary channel (channel 0) for floor measurement
        rms = float(np.sqrt(np.mean(recording[:, 0] ** 2) + 1e-12))
        floor_db = 20.0 * np.log10(rms + 1e-12)
        return floor_db
    except Exception as exc:
        print(f"[VAD] Noise floor calibration failed ({exc}), using default threshold.", file=sys.stderr)
        return config.vad_threshold_db - 8.0  # fallback: keep original threshold


def _start_status_logger(processor: DualMicFilter, interval: float = 2.0) -> threading.Thread:
    """Start a background thread that prints VAD status every `interval` seconds."""
    stop_event = threading.Event()

    def _log():
        while not stop_event.is_set():
            state = "SPEECH  " if processor.vad_active else "SILENCE (gated)"
            print(f"[VAD] {state}  |  RMS: {processor.last_rms_db:+.1f} dB  |  threshold: {processor.config.vad_threshold_db:.1f} dB")
            stop_event.wait(interval)

    t = threading.Thread(target=_log, daemon=True)
    t.start()
    return t


def run(
    input_device: int | str,
    output_device: int | str,
    config: FilterConfig,
) -> None:
    # Auto-calibrate noise floor on startup (Change 1)
    if config.enable_vad and config.auto_calibrate:
        floor_db = calibrate_noise_floor(input_device, config)
        # Temporarily create filter just to call set_noise_floor and print result
        _tmp = DualMicFilter(config)
        _tmp.set_noise_floor(floor_db)
        config.vad_threshold_db = _tmp.config.vad_threshold_db

    processor = DualMicFilter(config)
    overflow_count = 0

    in_dev = sd.query_devices(input_device)
    out_dev = sd.query_devices(output_device)
    print(
        f"USB voice mic active\n"
        f"  Input:  [{input_device}] {in_dev['name']}\n"
        f"  Output: [{output_device}] {out_dev['name']}\n"
        f"  Rate:   {config.sample_rate} Hz mono, mode={config.mode}, "
        f"noise_scale={config.noise_scale:.3f}, "
        f"VAD={'ON' if config.enable_vad else 'OFF'} threshold={config.vad_threshold_db:.1f}dB\n"
        f"Plug the Pi into your PC via USB data port. Press Ctrl+C to stop."
    )

    # Start VAD status logger (Change 5)
    _start_status_logger(processor)

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

    # Auto-reconnect loop (Change 4)
    while True:
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
            break
        except Exception as exc:
            print(f"[USB] Stream error: {exc}. Retrying in 2s...", file=sys.stderr)
            time.sleep(2)
            # Re-detect gadget device in case it changed index after re-plug
            new_gadget = find_gadget_playback()
            if new_gadget is not None:
                output_device = new_gadget


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stream filtered dual-mic audio to USB gadget microphone."
    )
    parser.add_argument(
        "--input-device",
        default=None,
        help="ALSA input device for I2S mics (index or hw:CARD=...,DEV=0; auto-detected if omitted)",
    )
    parser.add_argument(
        "--output-device",
        default=None,
        help="ALSA output device for USB gadget (index or hw:1,0; auto-detected if omitted)",
    )
    parser.add_argument("--mode", choices=["noise_cancel", "beamform"], default="noise_cancel")
    parser.add_argument("--noise-scale", type=float, default=None)
    parser.add_argument("--sample-rate", type=int, default=48000)
    parser.add_argument("--block-size", type=int, default=2048)
    parser.add_argument("--no-vad", action="store_true", help="Disable VAD silence gating")
    parser.add_argument("--no-auto-calibrate", action="store_true", help="Skip startup noise floor measurement")
    parser.add_argument("--vad-threshold-db", type=float, default=-40.0, help="VAD RMS threshold in dB (overridden by auto-calibration)")
    parser.add_argument("--hangover-ms", type=float, default=300.0, help="VAD speech hangover hold time in ms")
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

    input_device = args.input_device
    if input_device is None:
        input_device = find_i2s_input()
    elif str(input_device).isdigit():
        input_device = int(input_device)

    output_device = args.output_device
    if output_device is None:
        output_device = find_gadget_playback()
        if output_device is None:
            print(
                "Error: USB gadget playback device not found. "
                "Ensure setup_usb_gadget.sh ran and g_audio module is loaded.",
                file=sys.stderr,
            )
            sys.exit(1)
    elif str(output_device).isdigit():
        output_device = int(output_device)

    noise_scale = args.noise_scale if args.noise_scale is not None else load_noise_scale()
    config = FilterConfig(
        sample_rate=args.sample_rate,
        block_size=args.block_size,
        mode=args.mode,
        noise_scale=noise_scale,
        enable_vad=not args.no_vad,
        auto_calibrate=not args.no_auto_calibrate,
        vad_threshold_db=args.vad_threshold_db,
        hangover_ms=args.hangover_ms,
    )

    run(input_device, output_device, config)


if __name__ == "__main__":
    main()
