"""Evaluation manifest: the record schema and its validator.

One JSON object per line (JSONL), so that a manifest diffs cleanly and a bad line is
localizable. The validator is strict — unknown keys are rejected — because the failure
mode we are protecting against is a mistyped field silently excluding an utterance from a
subset metric and nobody noticing for three months.

See eval/datasets/SCHEMA.md for the prose version.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REQUIRED_TOP_LEVEL = ("id", "audio", "reference", "metadata")
OPTIONAL_TOP_LEVEL = (
    "duration_s",
    "entities",
    "itn_slots",
    "ground_truth",
    "provenance",
    "notes",
)
ALLOWED_TOP_LEVEL = frozenset(REQUIRED_TOP_LEVEL + OPTIONAL_TOP_LEVEL)

# Metadata keys required on every record. These are the axes the harness can slice on,
# and a record that cannot be sliced is a record that cannot answer a question.
REQUIRED_METADATA = ("language", "accent", "domain", "category")
OPTIONAL_METADATA = (
    "code_switch",
    "speaker",
    "noise",
    "source",
    "app",
    "subset",
    "reference_style",
)
ALLOWED_METADATA = frozenset(REQUIRED_METADATA + OPTIONAL_METADATA)

CATEGORIES = frozenset({"prose", "dev_speak", "code_switch", "adversarial", "itn", "command"})

HEX = frozenset("0123456789abcdef")

# How much formatting the reference actually carries. Public corpora almost never ship a
# formatted reference: EdAcc and LibriSpeech are upper-case and unpunctuated, Golos and
# RuLS are lower-case and unpunctuated. F-WER against such a reference punishes a backend
# for producing correct casing and punctuation, so the value has to travel with the
# record and be sliceable — see eval/datasets/public-proxy-v1/README.md.
REFERENCE_STYLES = frozenset({"formatted", "caps_nopunct", "lower_nopunct"})

# Provenance is optional, but once present it is checked strictly. It is what makes a
# public benchmark auditable: source corpus, pinned revision, row identity, licence and
# the hash of the exact audio that was scored.
REQUIRED_PROVENANCE = ("source", "revision", "split", "row_id", "license", "retrieved_utc")
OPTIONAL_PROVENANCE = (
    "config",
    "speaker_id",
    "license_url",
    "source_url",
    "source_audio_sha256",
    "source_sample_rate_hz",
    "audio_sha256",
    "sampling_seed",
    "derived_from",
    "transform",
)
ALLOWED_PROVENANCE = frozenset(REQUIRED_PROVENANCE + OPTIONAL_PROVENANCE)


@dataclass(frozen=True)
class ManifestError:
    line: int
    record_id: str | None
    field: str
    message: str

    def __str__(self) -> str:
        who = f" id={self.record_id}" if self.record_id else ""
        return f"line {self.line}{who}: {self.field}: {self.message}"


class ManifestValidationError(ValueError):
    def __init__(self, path: Path, errors: list[ManifestError]) -> None:
        self.path = path
        self.errors = errors
        detail = "\n  ".join(str(e) for e in errors)
        super().__init__(f"{path}: {len(errors)} invalid manifest entries:\n  {detail}")


@dataclass(frozen=True)
class Slot:
    text: str
    kind: str


@dataclass(frozen=True)
class Record:
    id: str
    audio: Path
    reference: str
    metadata: dict[str, Any]
    duration_s: float | None = None
    entities: tuple[str, ...] = ()
    itn_slots: tuple[Slot, ...] = ()
    provenance: dict[str, Any] | None = None
    notes: str = ""

    @property
    def code_switch(self) -> tuple[str, ...]:
        return tuple(self.metadata.get("code_switch", ()))


def _err(line: int, rid: str | None, fld: str, msg: str) -> ManifestError:
    return ManifestError(line, rid, fld, msg)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_metadata(
    raw: Any, line: int, rid: str, errors: list[ManifestError]
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        errors.append(_err(line, rid, "metadata", "must be an object"))
        return {}
    unknown = sorted(set(raw) - ALLOWED_METADATA)
    if unknown:
        errors.append(_err(line, rid, "metadata", f"unknown keys: {', '.join(unknown)}"))
    for key in REQUIRED_METADATA:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(
                _err(line, rid, f"metadata.{key}", "required, must be a non-empty string")
            )
    category = raw.get("category")
    if isinstance(category, str) and category not in CATEGORIES:
        errors.append(_err(line, rid, "metadata.category", f"must be one of {sorted(CATEGORIES)}"))
    cs = raw.get("code_switch", [])
    if not isinstance(cs, list) or any(not isinstance(x, str) or not x for x in cs):
        errors.append(_err(line, rid, "metadata.code_switch", "must be a list of language codes"))
    for key in ("speaker", "noise", "source", "app", "subset"):
        if key in raw and not isinstance(raw[key], str):
            errors.append(_err(line, rid, f"metadata.{key}", "must be a string"))
    style = raw.get("reference_style")
    if style is not None and style not in REFERENCE_STYLES:
        errors.append(
            _err(
                line, rid, "metadata.reference_style", f"must be one of {sorted(REFERENCE_STYLES)}"
            )
        )
    return raw


def _validate_provenance(
    raw: Any, line: int, rid: str, errors: list[ManifestError]
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        errors.append(_err(line, rid, "provenance", "must be an object"))
        return None
    unknown = sorted(set(raw) - ALLOWED_PROVENANCE)
    if unknown:
        errors.append(_err(line, rid, "provenance", f"unknown keys: {', '.join(unknown)}"))
    for key in REQUIRED_PROVENANCE:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(
                _err(line, rid, f"provenance.{key}", "required, must be a non-empty string")
            )
    for key in ("config", "speaker_id", "license_url", "source_url", "derived_from", "transform"):
        if key in raw and raw[key] is not None and not isinstance(raw[key], str):
            errors.append(_err(line, rid, f"provenance.{key}", "must be a string or null"))
    for key in ("source_audio_sha256", "audio_sha256"):
        value = raw.get(key)
        if key in raw and (
            not isinstance(value, str) or len(value) != 64 or not all(c in HEX for c in value)
        ):
            errors.append(_err(line, rid, f"provenance.{key}", "must be a 64-char hex sha256"))
    if "sampling_seed" in raw and not isinstance(raw["sampling_seed"], int):
        errors.append(_err(line, rid, "provenance.sampling_seed", "must be an integer"))
    rate = raw.get("source_sample_rate_hz")
    if "source_sample_rate_hz" in raw and (not isinstance(rate, int) or rate <= 0):
        errors.append(
            _err(line, rid, "provenance.source_sample_rate_hz", "must be a positive integer")
        )
    return raw


def _validate_record(
    obj: Any, line: int, base_dir: Path, require_audio: bool, errors: list[ManifestError]
) -> Record | None:
    if not isinstance(obj, dict):
        errors.append(_err(line, None, "<record>", "must be a JSON object"))
        return None

    rid_raw = obj.get("id")
    rid = rid_raw if isinstance(rid_raw, str) and rid_raw.strip() else None
    if rid is None:
        errors.append(_err(line, None, "id", "required, must be a non-empty string"))

    unknown = sorted(set(obj) - ALLOWED_TOP_LEVEL)
    if unknown:
        errors.append(_err(line, rid, "<record>", f"unknown keys: {', '.join(unknown)}"))
    missing = [k for k in REQUIRED_TOP_LEVEL if k not in obj]
    if missing:
        errors.append(_err(line, rid, "<record>", f"missing keys: {', '.join(missing)}"))

    reference = obj.get("reference")
    if not isinstance(reference, str) or not reference.strip():
        errors.append(_err(line, rid, "reference", "required, must be a non-empty string"))

    audio_raw = obj.get("audio")
    audio_path: Path | None = None
    if not isinstance(audio_raw, str) or not audio_raw.strip():
        errors.append(_err(line, rid, "audio", "required, must be a relative path string"))
    else:
        candidate = Path(audio_raw)
        if candidate.is_absolute():
            errors.append(_err(line, rid, "audio", "must be relative to the manifest directory"))
        else:
            audio_path = base_dir / candidate
            if require_audio and not audio_path.exists():
                errors.append(_err(line, rid, "audio", f"file not found: {audio_path}"))

    duration = obj.get("duration_s")
    if duration is not None and (not _is_number(duration) or duration <= 0):
        errors.append(_err(line, rid, "duration_s", "must be a positive number"))

    entities = obj.get("entities", [])
    if not isinstance(entities, list) or any(
        not isinstance(x, str) or not x.strip() for x in entities
    ):
        errors.append(_err(line, rid, "entities", "must be a list of non-empty strings"))
        entities = []

    slots_raw = obj.get("itn_slots", [])
    slots: list[Slot] = []
    if not isinstance(slots_raw, list):
        errors.append(_err(line, rid, "itn_slots", "must be a list of text/kind objects"))
    else:
        for k, s in enumerate(slots_raw):
            valid = (
                isinstance(s, dict)
                and set(s) == {"text", "kind"}
                and isinstance(s.get("text"), str)
                and bool(str(s.get("text", "")).strip())
                and isinstance(s.get("kind"), str)
                and bool(str(s.get("kind", "")).strip())
            )
            if valid:
                slots.append(Slot(s["text"], s["kind"]))
            else:
                errors.append(
                    _err(line, rid, f"itn_slots[{k}]", "must be an object with text and kind")
                )

    gt = obj.get("ground_truth")
    if gt is not None:
        if not isinstance(gt, dict):
            errors.append(_err(line, rid, "ground_truth", "must be an object"))
        elif gt.get("reconciled") is not True:
            # Transcribe twice, independently, reconcile. A reference that never went
            # through that produces confident wrong conclusions (BENCHMARKS.md section 2).
            errors.append(
                _err(line, rid, "ground_truth.reconciled", "must be true once reconciled")
            )

    provenance: dict[str, Any] | None = None
    if "provenance" in obj:
        provenance = _validate_provenance(obj["provenance"], line, rid or "?", errors)

    notes = obj.get("notes", "")
    if not isinstance(notes, str):
        errors.append(_err(line, rid, "notes", "must be a string"))
        notes = ""

    metadata = _validate_metadata(obj.get("metadata"), line, rid or "?", errors)

    if rid is None or audio_path is None or not isinstance(reference, str) or not reference.strip():
        return None
    return Record(
        id=rid,
        audio=audio_path,
        reference=reference,
        metadata=metadata,
        duration_s=float(duration) if isinstance(duration, (int, float)) else None,
        entities=tuple(entities),
        itn_slots=tuple(slots),
        provenance=provenance,
        notes=notes,
    )


@dataclass
class Manifest:
    path: Path
    records: list[Record] = field(default_factory=list)
    errors: list[ManifestError] = field(default_factory=list)
    sha256: str = ""

    @property
    def ok(self) -> bool:
        return not self.errors


def load(path: Path, *, require_audio: bool = True) -> Manifest:
    """Parse and validate a manifest, collecting every error rather than failing fast."""
    path = Path(path)
    raw_bytes = path.read_bytes()
    manifest = Manifest(path=path, sha256=hashlib.sha256(raw_bytes).hexdigest())
    base_dir = path.parent
    seen: dict[str, int] = {}
    for line_no, line in enumerate(raw_bytes.decode("utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("//"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            manifest.errors.append(_err(line_no, None, "<line>", f"invalid JSON: {exc.msg}"))
            continue
        record = _validate_record(obj, line_no, base_dir, require_audio, manifest.errors)
        if record is None:
            continue
        if record.id in seen:
            manifest.errors.append(
                _err(line_no, record.id, "id", f"duplicate of line {seen[record.id]}")
            )
            continue
        seen[record.id] = line_no
        manifest.records.append(record)
    return manifest


def load_strict(path: Path, *, require_audio: bool = True) -> Manifest:
    manifest = load(path, require_audio=require_audio)
    if manifest.errors:
        raise ManifestValidationError(manifest.path, manifest.errors)
    return manifest
