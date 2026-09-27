"""Decode, resample to 16 kHz mono, and apply the two robustness transforms.

Everything the harness scores is 16 kHz mono 16-bit PCM WAV, matching what the capture
path will produce. Sources arrive at 32 kHz (EdAcc), 16 kHz (RuLS, Golos) and as FLAC
(LibriSpeech), so a decode-and-resample step is unavoidable.

Resampling quality matters more than it looks: naive decimation of EdAcc's 32 kHz audio
aliases energy above 8 kHz back down into the speech band, and a benchmark that
introduces its own artefacts measures the artefacts. So: windowed-sinc low-pass below the
new Nyquist, then linear interpolation onto the new time base. After the low-pass the
signal is band-limited well inside the target Nyquist, which is the condition under which
linear interpolation is cheap and honest.

This module needs numpy (and soundfile for FLAC). Both live in the optional `data`
dependency group — see `hermes_eval.datasets.__init__` for why that boundary exists.
"""

from __future__ import annotations

import hashlib
import io
import math
import struct
import wave
from pathlib import Path
from typing import Any

TARGET_RATE = 16000


class MissingDependency(RuntimeError):
    pass


def _numpy() -> Any:
    try:
        import numpy
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise MissingDependency(
            "numpy is required to build the public proxy set: `uv sync --group data`"
        ) from exc
    return numpy


def _soundfile() -> Any:
    try:
        import soundfile
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise MissingDependency(
            "soundfile is required to decode FLAC sources: `uv sync --group data`"
        ) from exc
    return soundfile


# ------------------------------------------------------------------------- decoding


def _decode_wav(data: bytes) -> tuple[Any, int]:
    np = _numpy()
    with wave.open(io.BytesIO(data), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if width == 2:
        samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        samples = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    elif width == 1:
        samples = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:  # pragma: no cover - 24-bit WAV is not produced by any pinned source
        raise ValueError(f"unsupported WAV sample width: {width} bytes")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


def decode(data: bytes) -> tuple[Any, int]:
    """Decode arbitrary source bytes to (float32 mono samples in [-1, 1], sample rate)."""
    if data[:4] == b"RIFF":
        return _decode_wav(data)
    np = _numpy()
    sf = _soundfile()
    samples, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    return np.asarray(samples).mean(axis=1), int(rate)


# ----------------------------------------------------------------------- resampling


def _lowpass_kernel(cutoff_norm: float, taps: int = 129) -> Any:
    """Windowed-sinc low-pass. `cutoff_norm` is the cutoff as a fraction of the input
    sample rate (so 0.25 means one quarter of the input rate)."""
    np = _numpy()
    n = np.arange(taps, dtype=np.float64) - (taps - 1) / 2.0
    kernel = 2.0 * cutoff_norm * np.sinc(2.0 * cutoff_norm * n)
    kernel *= np.hamming(taps)
    return (kernel / kernel.sum()).astype(np.float32)


def resample(samples: Any, source_rate: int, target_rate: int = TARGET_RATE) -> Any:
    if source_rate == target_rate:
        return samples
    np = _numpy()
    if source_rate > target_rate:
        # 0.45 rather than 0.5 leaves a transition band; a brick wall at Nyquist would
        # need far more taps to be worth claiming.
        kernel = _lowpass_kernel(0.45 * target_rate / source_rate)
        samples = np.convolve(samples, kernel, mode="same")
    duration = len(samples) / source_rate
    n_out = int(math.floor(duration * target_rate))
    if n_out <= 0:
        return np.zeros(0, dtype=np.float32)
    t_out = np.arange(n_out, dtype=np.float64) / target_rate
    t_in = np.arange(len(samples), dtype=np.float64) / source_rate
    return np.interp(t_out, t_in, samples).astype(np.float32)


def to_target(data: bytes) -> tuple[Any, int]:
    """Decode source bytes and return (16 kHz mono float32, original sample rate)."""
    samples, rate = decode(data)
    return resample(samples, rate, TARGET_RATE), rate


# ---------------------------------------------------------------------- augmentation


def _rms(samples: Any) -> float:
    np = _numpy()
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))


def mix_noise(speech: Any, noise: Any, snr_db: float, seed: int) -> Any:
    """Add a noise clip at a stated SNR, tiling or cropping it to length.

    SNR is computed on full-signal RMS, not on voice-active frames. That is the simpler
    and more reproducible definition; it makes the effective SNR during speech slightly
    higher than the label on utterances with leading silence, which is stated here rather
    than hidden.
    """
    np = _numpy()
    if len(noise) == 0:
        return speech
    rng = np.random.default_rng(seed)
    if len(noise) < len(speech):
        reps = int(math.ceil(len(speech) / len(noise)))
        noise = np.tile(noise, reps)
    start = int(rng.integers(0, max(1, len(noise) - len(speech) + 1)))
    segment = noise[start : start + len(speech)].astype(np.float32)

    speech_rms = _rms(speech)
    noise_rms = _rms(segment)
    if speech_rms <= 0.0 or noise_rms <= 0.0:
        return speech
    scale = speech_rms / (noise_rms * (10.0 ** (snr_db / 20.0)))
    mixed = speech + scale * segment
    return _guard_clipping(mixed)


def apply_rir(speech: Any, rir: Any) -> Any:
    """Convolve with a room impulse response, keep the original length and loudness.

    The RIR is trimmed to start at its direct-path peak so the reverberant copy stays
    time-aligned with the clean one; otherwise the propagation delay baked into a
    simulated RIR would shift every word and make a paired clean-vs-reverb comparison
    measure alignment rather than reverberation.
    """
    np = _numpy()
    if len(rir) == 0:
        return speech
    peak = int(np.argmax(np.abs(rir)))
    rir = rir[peak:]
    norm = float(np.sqrt(np.sum(np.square(rir.astype(np.float64)))))
    if norm <= 0.0:
        return speech
    rir = (rir / norm).astype(np.float32)
    wet = np.convolve(speech, rir, mode="full")[: len(speech)]
    before, after = _rms(speech), _rms(wet)
    if after > 0.0:
        wet = wet * (before / after)
    return _guard_clipping(wet)


def _guard_clipping(samples: Any) -> Any:
    np = _numpy()
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    if peak > 0.999:
        samples = samples * (0.999 / peak)
    return samples.astype(np.float32)


# --------------------------------------------------------------------------- output


def write_wav(path: Path, samples: Any, rate: int = TARGET_RATE) -> str:
    """Write 16-bit PCM mono and return the sha256 of the file that was written."""
    np = _numpy()
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = np.round(clipped * 32767.0).astype("<i2").tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    return sha256_file(path)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def duration_s(samples: Any, rate: int = TARGET_RATE) -> float:
    return round(len(samples) / rate, 3)


def silence(seconds: float, rate: int = TARGET_RATE) -> Any:  # pragma: no cover - test aid
    np = _numpy()
    return np.zeros(int(seconds * rate), dtype=np.float32)


def pcm16_wav_bytes(samples: Any, rate: int = TARGET_RATE) -> bytes:  # pragma: no cover - test aid
    np = _numpy()
    pcm = np.round(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm),
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        rate,
        rate * 2,
        2,
        16,
        b"data",
        len(pcm),
    )
    return header + pcm
