"""Backend-agnostic adapter interface, plus the two adapters v0 needs.

The seam. Everything above it is scoring; everything below it is somebody's ASR. Phase 1
adds `transcribe_stream` with partial-hypothesis emission (needed for UPWR/UPSR); v0 has
no backend that produces partials, so the interface stops at the final transcript.

A real adapter MUST NOT read `record.reference`. It is passed the whole record because
`audio`, `duration_s` and `metadata.language` are legitimately useful to a backend;
reading the reference would be scoring against the answer key. `PerturbAdapter` does
exactly that, on purpose, because its job is to fabricate fixtures — it is not a backend.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from .manifest import Record

# Provenance every run record must carry (R6, "The RUN record"). An adapter that cannot
# supply a field reports it as null; the run then records it as missing rather than
# quietly pretending the run is reproducible.
REQUIRED_ENV_KEYS = (
    "backend",
    "version",
    "model_id",
    "model_sha256",
    "quantization",
    "runtime",
    "provider",
    "decode_params",
    "thread_count",
)


@dataclass
class Hypothesis:
    """What the adapter produces: the text that would have been injected."""

    text: str
    latency_ms: float | None = None
    # R6: semi-manual adapters (VB-Cable + UI Automation polling) cannot time honestly.
    low_confidence_timing: bool = False
    extra: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class ASRAdapter(Protocol):
    name: str

    def describe_env(self) -> dict[str, object]:
        """Resolved model id and hash, quantization, runtime/provider, decoding params."""
        ...

    def transcribe(self, record: Record) -> Hypothesis: ...


def missing_env_keys(env: dict[str, object]) -> list[str]:
    return [k for k in REQUIRED_ENV_KEYS if env.get(k) in (None, "", {})]


# ------------------------------------------------------------------------ replay


class ReplayAdapter:
    """Replays transcripts from a JSONL file of {"id": ..., "text": ...}.

    This is how closed competitors get scored: a human drives the app through VB-Cable,
    pastes the output into a file, and the harness scores it on identical code paths.
    Optional sidecar `<path>.env.json` carries the provenance a human recorded by hand.
    """

    def __init__(self, path: Path, name: str | None = None) -> None:
        self.path = Path(path)
        self.name = name or self.path.stem
        self._rows: dict[str, dict[str, object]] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            self._rows[str(row["id"])] = row
        env_path = self.path.with_suffix(self.path.suffix + ".env.json")
        self._env: dict[str, object] = (
            json.loads(env_path.read_text(encoding="utf-8")) if env_path.exists() else {}
        )

    def describe_env(self) -> dict[str, object]:
        env: dict[str, object] = {k: None for k in REQUIRED_ENV_KEYS}
        env.update({"backend": f"replay:{self.name}", "source_file": str(self.path)})
        env.update(self._env)
        return env

    def transcribe(self, record: Record) -> Hypothesis:
        row = self._rows.get(record.id)
        if row is None:
            raise KeyError(f"{self.path}: no replayed transcript for utterance {record.id!r}")
        latency = row.get("latency_ms")
        return Hypothesis(
            text=str(row.get("text", "")),
            latency_ms=float(latency) if isinstance(latency, (int, float)) else None,
            low_confidence_timing=bool(row.get("low_confidence_timing", False)),
        )


# ----------------------------------------------------------------------- perturb

_DIGIT_WORDS = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
}
_TRAILING_MARKS = ".,?!:;"


def _spell_digits(token: str) -> str:
    return "".join(_DIGIT_WORDS.get(ch, ch) for ch in token)


def _corrupt_word(word: str, rng: random.Random) -> str:
    if len(word) > 3 and rng.random() < 0.5:
        i = rng.randrange(len(word) - 1)
        return word[:i] + word[i + 1] + word[i] + word[i + 2 :]
    return word + rng.choice(("s", "e", "d"))


class PerturbAdapter:
    """A synthetic, deterministic, fake ASR: corrupts the reference in the ways real ASR
    does — dropped words, casing loss, missing punctuation, failed ITN, mangled
    identifiers. It exists so the harness can be exercised end to end without a model.

    Seeded per utterance, so results do not depend on manifest ordering or on how many
    utterances ran before this one.
    """

    name = "perturb"

    def __init__(
        self,
        seed: int = 1,
        error_rate: float = 0.08,
        punct_drop: float = 0.25,
        case_drop: float = 0.20,
        itn_fail: float = 0.30,
        latency_base_ms: float = 280.0,
        latency_jitter_ms: float = 220.0,
    ) -> None:
        self.seed = int(seed)
        self.error_rate = float(error_rate)
        self.punct_drop = float(punct_drop)
        self.case_drop = float(case_drop)
        self.itn_fail = float(itn_fail)
        self.latency_base_ms = float(latency_base_ms)
        self.latency_jitter_ms = float(latency_jitter_ms)

    def describe_env(self) -> dict[str, object]:
        return {
            "backend": "perturb",
            "version": "0.1.0",
            "model_id": f"synthetic-perturb-seed{self.seed}",
            "model_sha256": "n/a-synthetic",
            "quantization": "none",
            "runtime": "python-stdlib",
            "provider": "cpu",
            "decode_params": {
                "seed": self.seed,
                "error_rate": self.error_rate,
                "punct_drop": self.punct_drop,
                "case_drop": self.case_drop,
                "itn_fail": self.itn_fail,
            },
            "thread_count": 1,
            "note": "synthetic fixture generator; reads the reference. Not a backend.",
        }

    def transcribe(self, record: Record) -> Hypothesis:
        rng = random.Random(f"{self.seed}:{record.id}")
        out: list[str] = []
        for token in record.reference.split():
            roll = rng.random()
            if roll < self.error_rate * 0.4:
                continue  # deletion
            core, mark = token, ""
            while core and core[-1] in _TRAILING_MARKS:
                mark = core[-1] + mark
                core = core[:-1]
            if roll < self.error_rate:
                core = _corrupt_word(core, rng)
            if any(ch.isdigit() for ch in core) and rng.random() < self.itn_fail:
                core = _spell_digits(core)
            if core[:1].isupper() and rng.random() < self.case_drop:
                core = core[0].lower() + core[1:]
            if mark and rng.random() < self.punct_drop:
                mark = ""
            out.append(core + mark)
        latency = self.latency_base_ms + rng.random() * self.latency_jitter_ms
        return Hypothesis(text=" ".join(out), latency_ms=round(latency, 2))


# ------------------------------------------------------------------------ registry


def build_adapter(spec: str, root: Path) -> ASRAdapter:
    """Parse an adapter spec.

    `perturb:seed=7,error_rate=0.05` | `replay:path/to.jsonl` | `sherpa:<candidate-key>`
    """
    kind, _, rest = spec.partition(":")
    kind = kind.strip()
    if kind == "perturb":
        kwargs: dict[str, float] = {}
        for part in filter(None, (p.strip() for p in rest.split(","))):
            key, _, value = part.partition("=")
            kwargs[key.strip()] = float(value)
        return PerturbAdapter(**kwargs)  # type: ignore[arg-type]
    if kind == "replay":
        if not rest:
            raise ValueError("replay adapter needs a path: replay:<file.jsonl>")
        path = Path(rest)
        return ReplayAdapter(path if path.is_absolute() else root / path)
    if kind == "sherpa":
        # Imported lazily: real backends need the optional `asr` dependency group, and
        # `hermes-eval validate` / `compare` must keep working on a bare stdlib install.
        from .asr_sherpa import build as build_sherpa

        return build_sherpa(rest, root)
    raise ValueError(
        f"unknown adapter spec {spec!r} (expected perturb:..., replay:... or sherpa:...)"
    )
