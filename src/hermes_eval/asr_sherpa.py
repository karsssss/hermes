"""ONNX Runtime ASR adapters for candidate screening, via sherpa-onnx.

Why sherpa-onnx for screening: D-0011 already settled ONNX Runtime as the substrate, and
sherpa-onnx is the only way to put every candidate on *one* runtime, *one* provider and
*one* thread count today. That is what makes the comparison legitimate. It is a screening
harness, not a production decision — R5's objection to sherpa-onnx is about the Rust side
(sherpa-rs is archived, so shipping it means maintaining our own FFI), and none of that
applies to a Python measurement.

The three candidates are the three named in `docs/SYNTHESIS.md` §5. The registry pins the
directory, the decode path and the parameters for each; nothing is tuned per subset, and
no adapter reads `record.reference`.

Three integration facts worth recording, because each cost time to find:

1. The sherpa-onnx wheel ships no `onnxruntime.dll`. Windows resolves the bare name to the
   inbox `C:\\Windows\\System32\\onnxruntime.dll` (1.17, Windows ML), which is too old —
   sherpa 1.13.8 needs ORT API 28. `ensure_runtime()` puts ORT 1.28's DLL next to the
   extension module so the extension's own directory wins the search order.
2. The Nemotron streaming export **cannot** be driven by the offline recognizer: its graph
   expects cache tensors (`cache_last_time`) that only the online recognizer supplies. It
   is a cache-aware streaming model and has to be fed as a stream, one chunk at a time.
3. Whisper's encoder is a fixed 30-second window. A 3-second utterance costs the same as a
   30-second one. For a dictation product, where the median utterance is a few seconds,
   that is a structural property rather than a tuning problem.
"""

from __future__ import annotations

import hashlib
import math
import shutil
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .adapters import Hypothesis
from .manifest import Record

TARGET_RATE = 16000

# Identical for every candidate. The P/E-core thread sweep is a separate Phase 0
# measurement (docs/CURRENT.md, Task 2 item 5); holding it constant is what makes this
# comparison a comparison.
NUM_THREADS = 4
PROVIDER = "cpu"
WARMUP_RUNS = 2
WARMUP_SECONDS = 5.0


class SherpaUnavailable(RuntimeError):
    pass


# ------------------------------------------------------------------ runtime plumbing


def ensure_runtime() -> str | None:
    """Make sherpa-onnx load the pinned ORT rather than the Windows inbox one.

    Returns the path it installed, or None when nothing needed doing. Copying rather than
    mutating PATH is deliberate: a dependent DLL is resolved from the loading module's own
    directory before System32, and PATH games are order-dependent and invisible later.
    """
    try:
        import onnxruntime  # noqa: F401
        import sherpa_onnx
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise SherpaUnavailable(
            "sherpa-onnx and onnxruntime are required: `uv sync --group asr`"
        ) from exc

    import onnxruntime as ort

    lib_dir = Path(sherpa_onnx.__file__).parent / "lib"
    target = lib_dir / "onnxruntime.dll"
    if target.exists():
        return str(target)
    source = Path(ort.__file__).parent / "capi" / "onnxruntime.dll"
    if not source.exists():  # pragma: no cover - non-Windows
        return None
    shutil.copy2(source, target)
    return str(target)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _combined_sha256(paths: list[Path]) -> str:
    """One hash over the model's files, in sorted name order, so the id is stable."""
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(_sha256(path).encode("ascii"))
    return digest.hexdigest()


def read_wav(path: Path) -> tuple[Any, int, float]:
    import numpy as np

    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != 2 or handle.getnchannels() != 1:
            raise ValueError(f"{path}: expected 16-bit mono, got {handle.getsampwidth()}B")
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    return samples, rate, len(samples) / rate


def _warmup_signal() -> Any:
    """A deterministic synthetic waveform, never dataset audio.

    Warm-up exists to pay ORT's graph-init, arena and thread-pool costs once. Using a real
    utterance for it would either bias whichever record went first or leak evaluation audio
    into an untimed pass; a fixed synthetic signal does the job and is identical for every
    candidate.
    """
    import numpy as np

    n = int(WARMUP_SECONDS * TARGET_RATE)
    t = np.arange(n, dtype=np.float64) / TARGET_RATE
    wave_ = np.zeros(n, dtype=np.float64)
    for freq, amp in ((140.0, 0.30), (420.0, 0.18), (900.0, 0.10), (1800.0, 0.05)):
        wave_ += amp * np.sin(2 * math.pi * freq * t)
    envelope = 0.5 * (1.0 - np.cos(2 * math.pi * 3.0 * t))
    rng = np.random.default_rng(20260926)
    wave_ = wave_ * envelope + 0.01 * rng.standard_normal(n)
    return (wave_ / max(1e-9, float(np.max(np.abs(wave_)))) * 0.6).astype(np.float32)


# --------------------------------------------------------------------- the registry


@dataclass(frozen=True)
class Candidate:
    key: str
    model_dir: str
    kind: str
    """offline_transducer | online_transducer | whisper"""
    model_id: str
    quantization: str
    license: str
    languages: str
    files: tuple[str, ...]
    model_type: str = ""
    notes: str = ""


CANDIDATES: dict[str, Candidate] = {
    "parakeet-tdt-v3": Candidate(
        key="parakeet-tdt-v3",
        model_dir="sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
        kind="offline_transducer",
        model_type="nemo_transducer",
        model_id="nvidia/parakeet-tdt-0.6b-v3 (sherpa-onnx int8 export)",
        quantization="int8-dynamic",
        license="CC-BY-4.0",
        languages="25 European languages incl. en, ru, uk",
        files=("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"),
        notes="TDT transducer, offline decode, native punctuation and casing.",
    ),
    "nemotron-stream-en-560ms": Candidate(
        key="nemotron-stream-en-560ms",
        model_dir="sherpa-onnx-nemotron-speech-streaming-en-0.6b-560ms-int8-2026-04-25",
        kind="online_transducer",
        model_id="nvidia/nemotron-speech-streaming-en-0.6b @560ms (sherpa-onnx int8 export)",
        quantization="int8-dynamic",
        license="NVIDIA Open Model License",
        languages="en-US only",
        files=("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"),
        notes=(
            "Cache-aware streaming FastConformer-RNNT. Must be driven by the ONLINE "
            "recognizer; the offline path fails on a missing cache_last_time input."
        ),
    ),
    "whisper-large-v3-turbo": Candidate(
        key="whisper-large-v3-turbo",
        model_dir="sherpa-onnx-whisper-turbo",
        kind="whisper",
        model_id="openai/whisper-large-v3-turbo (sherpa-onnx int8 export)",
        quantization="int8-dynamic",
        license="MIT (model weights), Apache-2.0 (sherpa export tooling)",
        languages="multilingual, language selected per utterance",
        files=("turbo-encoder.int8.onnx", "turbo-decoder.int8.onnx", "turbo-tokens.txt"),
        notes=(
            "Fixed 30 s encoder window: a 3 s utterance costs what a 30 s one costs. "
            "One recognizer is constructed per language present in the manifest."
        ),
    ),
}


# ------------------------------------------------------------------------- adapter


@dataclass
class _Timing:
    load_ms: float = 0.0
    warmup_ms: float = 0.0
    hash_ms: float = 0.0
    decode_ms_total: float = 0.0
    audio_s_total: float = 0.0
    utterances: int = 0
    empty_outputs: int = 0
    per_language: dict[str, int] = field(default_factory=dict)


class SherpaAdapter:
    """One candidate, one runtime, one thread count. Never reads `record.reference`."""

    def __init__(
        self,
        candidate: Candidate,
        models_root: Path,
        *,
        num_threads: int = NUM_THREADS,
        provider: str = PROVIDER,
        warmup_runs: int = WARMUP_RUNS,
        languages: tuple[str, ...] = ("en",),
    ) -> None:
        ensure_runtime()
        import sherpa_onnx

        self._sherpa = sherpa_onnx
        self.candidate = candidate
        self.name = candidate.key
        self.num_threads = int(num_threads)
        self.provider = provider
        self.timing = _Timing()

        self.dir = Path(models_root) / candidate.model_dir
        if not self.dir.is_dir():
            raise SherpaUnavailable(
                f"model directory missing: {self.dir}. "
                "See docs/research/T2A-screening.md for the download commands."
            )

        started = time.perf_counter()
        self.model_sha256 = _combined_sha256([self.dir / f for f in candidate.files])
        self.timing.hash_ms = (time.perf_counter() - started) * 1000.0

        started = time.perf_counter()
        self._recognizers: dict[str, Any] = {}
        if candidate.kind == "whisper":
            for lang in languages:
                self._recognizers[lang] = self._build_whisper(lang)
        else:
            self._recognizers["*"] = self._build_transducer()
        self.timing.load_ms = (time.perf_counter() - started) * 1000.0

        started = time.perf_counter()
        signal = _warmup_signal()
        for _ in range(warmup_runs):
            for recognizer in self._recognizers.values():
                self._decode(recognizer, signal, TARGET_RATE)
        self.timing.warmup_ms = (time.perf_counter() - started) * 1000.0

    # -- construction -----------------------------------------------------------

    def _path(self, name: str) -> str:
        return str(self.dir / name)

    def _build_transducer(self) -> Any:
        common = {
            "encoder": self._path("encoder.int8.onnx"),
            "decoder": self._path("decoder.int8.onnx"),
            "joiner": self._path("joiner.int8.onnx"),
            "tokens": self._path("tokens.txt"),
            "num_threads": self.num_threads,
            "provider": self.provider,
        }
        if self.candidate.kind == "online_transducer":
            return self._sherpa.OnlineRecognizer.from_transducer(**common)
        return self._sherpa.OfflineRecognizer.from_transducer(
            **common, model_type=self.candidate.model_type, decoding_method="greedy_search"
        )

    def _build_whisper(self, language: str) -> Any:
        return self._sherpa.OfflineRecognizer.from_whisper(
            encoder=self._path("turbo-encoder.int8.onnx"),
            decoder=self._path("turbo-decoder.int8.onnx"),
            tokens=self._path("turbo-tokens.txt"),
            language=language,
            task="transcribe",
            num_threads=self.num_threads,
            provider=self.provider,
            decoding_method="greedy_search",
        )

    # -- decoding ---------------------------------------------------------------

    def _decode(self, recognizer: Any, samples: Any, rate: int) -> str:
        stream = recognizer.create_stream()
        stream.accept_waveform(rate, samples)
        if self.candidate.kind == "online_transducer":
            stream.input_finished()
            while recognizer.is_ready(stream):
                recognizer.decode_stream(stream)
            return str(recognizer.get_result(stream))
        recognizer.decode_stream(stream)
        return str(stream.result.text)

    def _recognizer_for(self, record: Record) -> Any:
        if self.candidate.kind != "whisper":
            return self._recognizers["*"]
        language = str(record.metadata.get("language") or "en")
        if language not in self._recognizers:
            self._recognizers[language] = self._build_whisper(language)
        return self._recognizers[language]

    def transcribe(self, record: Record) -> Hypothesis:
        samples, rate, audio_s = read_wav(record.audio)
        recognizer = self._recognizer_for(record)
        started = time.perf_counter()
        text = self._decode(recognizer, samples, rate)
        decode_ms = (time.perf_counter() - started) * 1000.0

        self.timing.decode_ms_total += decode_ms
        self.timing.audio_s_total += audio_s
        self.timing.utterances += 1
        if not text.strip():
            self.timing.empty_outputs += 1
        language = str(record.metadata.get("language") or "?")
        self.timing.per_language[language] = self.timing.per_language.get(language, 0) + 1

        return Hypothesis(
            text=text.strip(),
            latency_ms=decode_ms,
            extra={
                "audio_s": round(audio_s, 3),
                "rtf": round(decode_ms / 1000.0 / audio_s, 4) if audio_s > 0 else None,
            },
        )

    # -- provenance -------------------------------------------------------------

    def describe_env(self) -> dict[str, object]:
        timing = self.timing
        rtf = (
            round(timing.decode_ms_total / 1000.0 / timing.audio_s_total, 4)
            if timing.audio_s_total > 0
            else None
        )
        return {
            "backend": f"sherpa-onnx:{self.candidate.key}",
            "version": getattr(self._sherpa, "__version__", "1.13.8"),
            "model_id": self.candidate.model_id,
            "model_sha256": self.model_sha256,
            "quantization": self.candidate.quantization,
            "runtime": "onnxruntime 1.28.0 via sherpa-onnx 1.13.8",
            "provider": self.provider,
            "decode_params": {
                "decoding_method": "greedy_search",
                "kind": self.candidate.kind,
                "model_type": self.candidate.model_type or None,
                "warmup_runs": WARMUP_RUNS,
                "warmup_signal": f"synthetic {WARMUP_SECONDS:g}s, seed 20260926",
                "language_source": (
                    "manifest metadata.language" if self.candidate.kind == "whisper" else "n/a"
                ),
            },
            "thread_count": self.num_threads,
            "model_license": self.candidate.license,
            "model_languages": self.candidate.languages,
            "model_dir": self.dir.name,
            "notes": self.candidate.notes,
            "load_ms": round(timing.load_ms, 1),
            "model_hash_ms": round(timing.hash_ms, 1),
            "warmup_ms": round(timing.warmup_ms, 1),
            "decode_ms_total": round(timing.decode_ms_total, 1),
            "audio_s_total": round(timing.audio_s_total, 2),
            "rtf_corpus": rtf,
            "utterances_decoded": timing.utterances,
            "empty_outputs": timing.empty_outputs,
            "utterances_per_language": dict(sorted(timing.per_language.items())),
        }


def build(spec: str, repo_root: Path) -> SherpaAdapter:
    """`sherpa:<candidate-key>[,threads=N][,langs=en|ru]`"""
    key, _, rest = spec.partition(",")
    key = key.strip()
    if key not in CANDIDATES:
        raise ValueError(f"unknown sherpa candidate {key!r}; known: {sorted(CANDIDATES)}")
    options: dict[str, str] = {}
    for part in filter(None, (p.strip() for p in rest.split(","))):
        name, _, value = part.partition("=")
        options[name.strip()] = value.strip()
    languages = tuple(filter(None, options.get("langs", "en").split("|")))
    return SherpaAdapter(
        CANDIDATES[key],
        Path(repo_root) / "models",
        num_threads=int(options.get("threads", NUM_THREADS)),
        languages=languages or ("en",),
    )
