#!/usr/bin/env python3
"""
Dual-microphone noise filtering for voice capture on Raspberry Pi.

Supports two processing modes:
  - noise_cancel: primary mic (voice + noise) minus scaled reference mic (ambient noise)
  - beamform: delay-and-sum end-fire array to focus on sound from one direction

Hardware: stereo capture device with two microphones (USB adapter or I2S pair).
"""

from __future__ import annotations

import argparse
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import signal


@dataclass
class FilterConfig:
    sample_rate: int = 48000  # googlevoicehat / dual INMP441 fixed rate
    block_size: int = 1024
    mode: str = "noise_cancel"  # noise_cancel | beamform
    mic_spacing_m: float = 0.05
    beam_angle_deg: float = 0.0
    noise_scale: float = 0.85
    highpass_hz: float = 80.0
    noise_gate_db: float = -45.0
    enable_vad: bool = True
    vad_threshold_db: float = -40.0
    hangover_ms: float = 300.0


class DualMicFilter:
    """Real-time dual-mic processor."""

    def __init__(self, config: FilterConfig):
        self.config = config
        self._hp_b, self._hp_a = signal.butter(
            2, config.highpass_hz, btype="highpass", fs=config.sample_rate
        )
        self._hp_state = signal.lfilter_zi(self._hp_b, self._hp_a)
        self._delay_samples = self._compute_beam_delay()
        self._hangover_samples = int((config.hangover_ms / 1000.0) * config.sample_rate)
        self._hangover_counter = 0

    def _compute_beam_delay(self) -> int:
        """End-fire array delay for steering toward beam_angle_deg."""
        c = 343.0  # speed of sound m/s
        angle = np.deg2rad(self.config.beam_angle_deg)
        tau = (self.config.mic_spacing_m / c) * np.cos(angle)
        delay = int(round(abs(tau) * self.config.sample_rate))
        return max(0, delay)

    def process_block(self, mic_primary: np.ndarray, mic_reference: np.ndarray) -> np.ndarray:
        """Process one block. mic_primary = channel 0, mic_reference = channel 1."""
        primary = mic_primary.astype(np.float32)
        reference = mic_reference.astype(np.float32)

        if self.config.mode == "beamform":
            if self._delay_samples > 0:
                reference = np.roll(reference, self._delay_samples)
            output = 0.5 * (primary + reference)
        else:
            output = primary - self.config.noise_scale * reference

        output, self._hp_state = signal.lfilter(
            self._hp_b, self._hp_a, output, zi=self._hp_state
        )
        output = self._apply_noise_gate(output)
        output = self._apply_vad_gate(output)
        return np.clip(output, -1.0, 1.0)

    def _apply_noise_gate(self, audio: np.ndarray) -> np.ndarray:
        threshold = 10 ** (self.config.noise_gate_db / 20.0)
        rms = np.sqrt(np.mean(audio**2) + 1e-12)
        if rms < threshold:
            return audio * (rms / threshold)
        return audio

    def _apply_vad_gate(self, audio: np.ndarray) -> np.ndarray:
        if not self.config.enable_vad:
            return audio

        threshold = 10 ** (self.config.vad_threshold_db / 20.0)
        rms = np.sqrt(np.mean(audio**2) + 1e-12)

        if rms >= threshold:
            self._hangover_counter = self._hangover_samples
            return audio
        elif self._hangover_counter > 0:
            self._hangover_counter -= len(audio)
            return audio
        else:
            return np.zeros_like(audio)


def list_devices() -> None:
    import sounddevice as sd

    print("Available audio devices:\n")
    print(sd.query_devices())
    print("\nDefault input:", sd.default.device[0])


def run_live(config: FilterConfig, device: int | None, output_wav: Path | None) -> None:
    import sounddevice as sd

    processor = DualMicFilter(config)
    wav_writer: wave.Wave_write | None = None
    if output_wav:
        wav_writer = wave.open(str(output_wav), "wb")
        wav_writer.setnchannels(1)
        wav_writer.setsampwidth(2)
        wav_writer.setframerate(config.sample_rate)

    print(
        f"Capturing at {config.sample_rate} Hz, mode={config.mode}, "
        f"block={config.block_size}. Press Ctrl+C to stop."
    )

    def callback(indata, _frames, _time_info, status):
        if status:
            print(status, file=sys.stderr)
        if indata.shape[1] < 2:
            raise RuntimeError("Need a stereo input device (2 microphone channels).")

        filtered = processor.process_block(indata[:, 0], indata[:, 1])
        pcm = (filtered * 32767).astype(np.int16)

        if wav_writer:
            wav_writer.writeframes(pcm.tobytes())

    try:
        with sd.InputStream(
            samplerate=config.sample_rate,
            blocksize=config.block_size,
            device=device,
            channels=2,
            dtype="float32",
            callback=callback,
        ):
            while True:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if wav_writer:
            wav_writer.close()
            print(f"Saved: {output_wav}")


def run_offline(config: FilterConfig, input_wav: Path, output_wav: Path) -> None:
    with wave.open(str(input_wav), "rb") as wf:
        if wf.getnchannels() != 2:
            raise ValueError("Input WAV must be stereo (2 channels).")
        sample_rate = wf.getframerate()
        if sample_rate != config.sample_rate:
            print(f"Warning: resampling config from {config.sample_rate} to {sample_rate}")
            config.sample_rate = sample_rate

        raw = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        stereo = raw.reshape(-1, 2).astype(np.float32) / 32768.0

    processor = DualMicFilter(config)
    block = config.block_size
    chunks: list[np.ndarray] = []

    for start in range(0, len(stereo), block):
        end = min(start + block, len(stereo))
        primary = stereo[start:end, 0]
        reference = stereo[start:end, 1]
        if len(primary) < block:
            pad = block - len(primary)
            primary = np.pad(primary, (0, pad))
            reference = np.pad(reference, (0, pad))
        chunks.append(processor.process_block(primary, reference))

    output = np.concatenate(chunks)[: len(stereo)]
    pcm = (output * 32767).astype(np.int16)

    with wave.open(str(output_wav), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(config.sample_rate)
        out.writeframes(pcm.tobytes())

    print(f"Wrote filtered audio: {output_wav}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dual-microphone noise filtering for voice input."
    )
    parser.add_argument("--list-devices", action="store_true", help="Show audio devices")
    parser.add_argument("--device", type=int, default=None, help="Input device index")
    parser.add_argument("--mode", choices=["noise_cancel", "beamform"], default="noise_cancel")
    parser.add_argument("--sample-rate", type=int, default=48000)
    parser.add_argument("--block-size", type=int, default=1024)
    parser.add_argument("--mic-spacing", type=float, default=0.05, help="Meters between mics")
    parser.add_argument("--beam-angle", type=float, default=0.0, help="Beam direction (degrees)")
    parser.add_argument("--noise-scale", type=float, default=0.85, help="Reference subtraction gain")
    parser.add_argument("--input-wav", type=Path, help="Process stereo WAV offline")
    parser.add_argument("--output-wav", type=Path, help="Save filtered mono WAV")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        return

    config = FilterConfig(
        sample_rate=args.sample_rate,
        block_size=args.block_size,
        mode=args.mode,
        mic_spacing_m=args.mic_spacing,
        beam_angle_deg=args.beam_angle,
        noise_scale=args.noise_scale,
    )

    if args.input_wav:
        if not args.output_wav:
            parser.error("--output-wav is required with --input-wav")
        run_offline(config, args.input_wav, args.output_wav)
    else:
        run_live(config, args.device, args.output_wav)


if __name__ == "__main__":
    main()
