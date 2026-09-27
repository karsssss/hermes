from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_eval.manifest import ManifestValidationError, load, load_strict

VALID = {
    "id": "u-0001",
    "audio": "audio/u-0001.wav",
    "duration_s": 2.5,
    "reference": "Run git rebase --interactive HEAD~3.",
    "metadata": {
        "language": "en",
        "accent": "uk-L1",
        "domain": "git",
        "category": "dev_speak",
        "code_switch": [],
        "speaker": "primary",
        "noise": "quiet",
        "source": "real-use",
        "app": "WindowsTerminal.exe",
    },
    "entities": ["git rebase --interactive"],
    "itn_slots": [{"text": "HEAD~3", "kind": "identifier"}],
    "ground_truth": {"pass1": "a", "pass2": "a", "reconciled": True},
    "notes": "",
}


def write(tmp_path: Path, *records: object, audio: bool = True) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "manifest.jsonl"
    lines = []
    for r in records:
        lines.append(r if isinstance(r, str) else json.dumps(r))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if audio:
        (tmp_path / "audio").mkdir(exist_ok=True)
        (tmp_path / "audio" / "u-0001.wav").write_bytes(b"RIFF")
        (tmp_path / "audio" / "u-0002.wav").write_bytes(b"RIFF")
    return path


def errors_for(tmp_path: Path, mutate) -> list[str]:
    record = json.loads(json.dumps(VALID))
    mutate(record)
    manifest = load(write(tmp_path, record))
    return [str(e) for e in manifest.errors]


def test_valid_record_loads(tmp_path: Path):
    manifest = load_strict(write(tmp_path, VALID))
    assert len(manifest.records) == 1
    record = manifest.records[0]
    assert record.id == "u-0001"
    assert record.entities == ("git rebase --interactive",)
    assert record.itn_slots[0].text == "HEAD~3"
    assert record.audio == tmp_path / "audio" / "u-0001.wav"
    assert manifest.sha256  # provenance for the run record


def test_comments_and_blank_lines_are_ignored(tmp_path: Path):
    path = write(tmp_path, "// a comment", "", json.dumps(VALID))
    assert len(load_strict(path).records) == 1


def test_manifest_sha_changes_with_content(tmp_path: Path):
    a = load(write(tmp_path / "a", VALID)).sha256
    other = json.loads(json.dumps(VALID))
    other["reference"] = "Something else entirely."
    b = load(write(tmp_path / "b", other)).sha256
    assert a != b


def test_invalid_json_reports_the_line_number(tmp_path: Path):
    path = write(tmp_path, json.dumps(VALID), "{not json")
    manifest = load(path)
    assert len(manifest.errors) == 1
    assert manifest.errors[0].line == 2
    assert "invalid JSON" in manifest.errors[0].message
    assert len(manifest.records) == 1  # the good record still loads


def test_unknown_top_level_key_is_rejected(tmp_path: Path):
    out = errors_for(tmp_path, lambda r: r.update({"referance": "typo"}))
    assert any("unknown keys: referance" in e for e in out)


def test_unknown_metadata_key_is_rejected(tmp_path: Path):
    out = errors_for(tmp_path, lambda r: r["metadata"].update({"dialect": "x"}))
    assert any("unknown keys: dialect" in e for e in out)


def test_missing_required_metadata_is_rejected(tmp_path: Path):
    out = errors_for(tmp_path, lambda r: r["metadata"].pop("accent"))
    assert any("metadata.accent" in e for e in out)


def test_unknown_category_is_rejected(tmp_path: Path):
    out = errors_for(tmp_path, lambda r: r["metadata"].update({"category": "rambling"}))
    assert any("metadata.category" in e for e in out)


def test_empty_reference_is_rejected(tmp_path: Path):
    out = errors_for(tmp_path, lambda r: r.update({"reference": "   "}))
    assert any("reference" in e for e in out)


def test_missing_audio_file_is_rejected(tmp_path: Path):
    out = errors_for(tmp_path, lambda r: r.update({"audio": "audio/nope.wav"}))
    assert any("file not found" in e for e in out)


def test_absolute_audio_path_is_rejected(tmp_path: Path):
    out = errors_for(tmp_path, lambda r: r.update({"audio": "C:/audio/u.wav"}))
    assert any("relative to the manifest directory" in e for e in out)


def test_negative_duration_is_rejected(tmp_path: Path):
    out = errors_for(tmp_path, lambda r: r.update({"duration_s": -1}))
    assert any("duration_s" in e for e in out)


def test_unreconciled_ground_truth_is_rejected(tmp_path: Path):
    out = errors_for(tmp_path, lambda r: r["ground_truth"].update({"reconciled": False}))
    assert any("ground_truth.reconciled" in e for e in out)


def test_malformed_itn_slot_is_rejected(tmp_path: Path):
    out = errors_for(tmp_path, lambda r: r.update({"itn_slots": [{"text": "3:30"}]}))
    assert any("itn_slots[0]" in e for e in out)


def test_empty_entity_string_is_rejected(tmp_path: Path):
    out = errors_for(tmp_path, lambda r: r.update({"entities": ["ok", ""]}))
    assert any("entities" in e for e in out)


def test_duplicate_ids_are_rejected(tmp_path: Path):
    manifest = load(write(tmp_path, VALID, VALID))
    assert any("duplicate of line 1" in str(e) for e in manifest.errors)
    assert len(manifest.records) == 1


def test_all_errors_are_collected_not_just_the_first(tmp_path: Path):
    broken = json.loads(json.dumps(VALID))
    broken.pop("reference")
    broken["metadata"].pop("domain")
    broken["duration_s"] = 0
    manifest = load(write(tmp_path, broken))
    assert len(manifest.errors) >= 3


def test_load_strict_raises_with_every_error_listed(tmp_path: Path):
    broken = json.loads(json.dumps(VALID))
    broken["metadata"]["category"] = "nope"
    with pytest.raises(ManifestValidationError) as excinfo:
        load_strict(write(tmp_path, broken))
    assert "metadata.category" in str(excinfo.value)


def test_require_audio_can_be_disabled(tmp_path: Path):
    path = write(tmp_path, VALID, audio=False)
    assert load(path, require_audio=False).ok
    assert not load(path, require_audio=True).ok


def test_the_checked_in_mock_manifest_is_valid():
    root = Path(__file__).resolve().parents[1]
    manifest = load_strict(root / "eval" / "datasets" / "mock" / "manifest.jsonl")
    assert len(manifest.records) == 12


def test_the_personal_template_is_valid():
    root = Path(__file__).resolve().parents[1]
    path = root / "eval" / "datasets" / "personal" / "manifest.template.jsonl"
    manifest = load(path, require_audio=False)
    assert manifest.ok, [str(e) for e in manifest.errors]


# ------------------------------------------------- provenance and the proxy-set axes

PROVENANCE = {
    "source": "hf:edinburghcstr/edacc",
    "revision": "d9ae7bd344f0562b766ec93ee5ce8f2f9568ce66",
    "config": "default",
    "split": "test",
    "row_id": "5000:EDACC-C36-A",
    "speaker_id": "EDACC-C36-A",
    "license": "CC-BY-SA-4.0",
    "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
    "source_url": "https://datasets-server.huggingface.co/cached-assets/x",
    "source_audio_sha256": "a" * 64,
    "source_sample_rate_hz": 32000,
    "audio_sha256": "b" * 64,
    "sampling_seed": 20260926,
    "derived_from": None,
    "transform": None,
    "retrieved_utc": "2026-09-26T20:00:00Z",
}


def test_provenance_round_trips(tmp_path: Path):
    record = json.loads(json.dumps(VALID))
    record["provenance"] = PROVENANCE
    record["metadata"]["subset"] = "accented_en"
    record["metadata"]["reference_style"] = "caps_nopunct"
    manifest = load_strict(write(tmp_path, record))
    assert manifest.records[0].provenance == PROVENANCE
    assert manifest.records[0].metadata["subset"] == "accented_en"


def test_provenance_requires_the_fields_that_make_a_number_auditable(tmp_path: Path):
    for missing in ("source", "revision", "split", "row_id", "license", "retrieved_utc"):
        payload = {k: v for k, v in PROVENANCE.items() if k != missing}
        errors = errors_for(tmp_path, lambda r, p=payload: r.update(provenance=p))
        assert any(f"provenance.{missing}" in e for e in errors), missing


def test_provenance_rejects_unknown_keys_and_bad_hashes(tmp_path: Path):
    errors = errors_for(tmp_path, lambda r: r.update(provenance={**PROVENANCE, "licence": "CC0"}))
    assert any("unknown keys: licence" in e for e in errors)

    errors = errors_for(
        tmp_path, lambda r: r.update(provenance={**PROVENANCE, "audio_sha256": "nope"})
    )
    assert any("provenance.audio_sha256" in e for e in errors)

    errors = errors_for(
        tmp_path, lambda r: r.update(provenance={**PROVENANCE, "sampling_seed": "1"})
    )
    assert any("provenance.sampling_seed" in e for e in errors)


def test_reference_style_is_constrained(tmp_path: Path):
    errors = errors_for(tmp_path, lambda r: r["metadata"].update(reference_style="shouty"))
    assert any("metadata.reference_style" in e for e in errors)
