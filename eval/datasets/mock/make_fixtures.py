"""Regenerate the synthetic audio fixtures for the mock dataset.

    python eval/datasets/mock/make_fixtures.py

These are 0.4 s placeholder tones, not speech: the mock dataset exists to exercise the
harness end to end without a model, and no adapter in v0 reads the audio. `duration_s` in
the manifest reflects the fixture file, not the length of the sentence.

Deterministic: same manifest in, byte-identical WAVs out.
"""

from __future__ import annotations

import json
import math
import struct
import wave
from pathlib import Path

SAMPLE_RATE = 16_000
DURATION_S = 0.4
HERE = Path(__file__).parent


def write_tone(path: Path, freq: float) -> None:
    n = int(SAMPLE_RATE * DURATION_S)
    frames = bytearray()
    for i in range(n):
        value = int(12_000 * math.sin(2 * math.pi * freq * i / SAMPLE_RATE))
        frames += struct.pack("<h", value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(bytes(frames))


def main() -> None:
    manifest = HERE / "manifest.jsonl"
    count = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        # Frequency derived from the id so each fixture differs but stays reproducible.
        freq = 180.0 + (sum(record["id"].encode()) % 24) * 20.0
        write_tone(HERE / record["audio"], freq)
        count += 1
    print(f"wrote {count} fixtures to {(HERE / 'audio').as_posix()}")


if __name__ == "__main__":
    main()
