"""Tests for the public-proxy build path.

Nothing here touches the network. The parts that do — paging the datasets-server and
range-reading a 1.3 GB ZIP — are exercised by actually running `build-dataset`, and their
output is pinned in `eval/datasets/public-proxy-v1/build.json`. What is worth testing in
CI is the logic that decides *which* rows get picked and *what* the audio ends up being,
because those are the parts whose silent drift would invalidate a published number.
"""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from hermes_eval.datasets import hub
from hermes_eval.datasets.build import (
    _passes_field_filters,
    _passes_text_filters,
    _seed_key,
)
from hermes_eval.datasets.sources import SOURCES

np = pytest.importorskip("numpy")
audio = pytest.importorskip("hermes_eval.datasets.audio")


# ------------------------------------------------------------------------- registry


def test_every_source_is_fully_pinned() -> None:
    for key, source in SOURCES.items():
        assert source.key == key
        assert len(source.revision) == 40, f"{key}: revision must be a full commit sha"
        assert all(c in "0123456789abcdef" for c in source.revision)
        assert source.n_rows > 0
        assert source.license and source.license_url
        assert source.reference_style in {"formatted", "caps_nopunct", "lower_nopunct"}


def test_ruls_speaker_comes_from_the_audio_path() -> None:
    source = SOURCES["ruls_test"]
    row = {"audio_filepath": "audio/2671/2145/poemi_01_pushkin_0000.wav", "text": "x"}
    assert source.speaker_of(row) == "2671"
    assert source.row_id_of(7, row) == "7:audio/2671/2145/poemi_01_pushkin_0000.wav"


def test_golos_publishes_no_speaker_identity() -> None:
    # Not an oversight to route around: the corpus is anonymous Toloka workers, so a
    # speaker-disjointness claim about it would be fiction.
    for key in ("golos_crowd_test", "golos_farfield_test"):
        assert SOURCES[key].speaker_of({"transcription": "салют"}) is None


# -------------------------------------------------------------------------- filters


def test_text_filters() -> None:
    stratum = {"min_tokens": 3, "max_tokens": 5}
    assert _passes_text_filters("", stratum) == "empty_text"
    assert _passes_text_filters("one two", stratum) == "too_few_tokens"
    assert _passes_text_filters("one two three four five six", stratum) == "too_many_tokens"
    assert _passes_text_filters("one two three", stratum) is None


def test_field_filters_split_native_from_non_native_l1() -> None:
    stratum = {"exclude_suffix": {"l1": "English"}}
    assert _passes_field_filters({"l1": "Scottish English"}, stratum) == "excluded_l1_suffix"
    assert _passes_field_filters({"l1": "Ghanain English"}, stratum) == "excluded_l1_suffix"
    assert _passes_field_filters({"l1": "Hindi"}, stratum) is None


def test_seed_key_is_stable_and_scoped() -> None:
    spec = {"seed": 1, "name": "x"}
    assert _seed_key(spec, "a", "b") == "1|x|a|b"
    assert _seed_key(spec, "a", "b") != _seed_key({"seed": 2, "name": "x"}, "a", "b")


# ------------------------------------------------------------------ revision pinning


def test_revision_is_read_out_of_the_asset_url() -> None:
    sha = "d9ae7bd344f0562b766ec93ee5ce8f2f9568ce66"
    row = {
        "audio": [
            {
                "src": f"https://datasets-server.huggingface.co/cached-assets/e/d/--/{sha}"
                "/--/default/test/5000/audio/audio.wav?Expires=1&Signature=x",
                "type": "audio/wav",
            }
        ]
    }
    assert hub.observed_revision(row, "audio") == sha
    assert hub.observed_revision({"audio": []}, "audio") is None


def test_revision_mismatch_aborts_rather_than_scoring_other_audio() -> None:
    hub.check_revision("a" * 40, "a" * 40, "where")
    with pytest.raises(hub.RevisionMismatch):
        hub.check_revision("b" * 40, "a" * 40, "where")
    with pytest.raises(hub.HubError):
        hub.check_revision(None, "a" * 40, "where")


def test_deterministic_choice_ignores_listing_order() -> None:
    names = [f"n{i}.wav" for i in range(50)]
    first = hub.deterministic_choice(names, "seed", 3)
    assert first == hub.deterministic_choice(list(reversed(names)), "seed", 3)
    assert first != hub.deterministic_choice(names, "other-seed", 3)


# ---------------------------------------------------------------------------- audio


def _tone(freq: float, seconds: float, rate: int) -> Any:
    t = np.arange(int(seconds * rate), dtype=np.float64) / rate
    return (0.5 * np.sin(2 * math.pi * freq * t)).astype(np.float32)


def test_resample_preserves_duration() -> None:
    samples = _tone(440.0, 1.0, 32000)
    out = audio.resample(samples, 32000, 16000)
    assert abs(len(out) / 16000 - 1.0) < 0.01


def test_resample_suppresses_energy_above_the_new_nyquist() -> None:
    # A 12 kHz tone at 32 kHz has nowhere to go at 16 kHz. Naive decimation folds it back
    # to 4 kHz — right in the speech band — and the benchmark would then be measuring its
    # own aliasing.
    aliasing_bait = _tone(12000.0, 0.5, 32000)
    out = audio.resample(aliasing_bait, 32000, 16000)
    assert float(np.sqrt(np.mean(np.square(out)))) < 0.02


def test_resample_passes_speech_band_through() -> None:
    speech_band = _tone(1000.0, 0.5, 32000)
    out = audio.resample(speech_band, 32000, 16000)
    rms = float(np.sqrt(np.mean(np.square(out))))
    assert 0.25 < rms < 0.45


def test_wav_round_trip_and_hash(tmp_path) -> None:
    samples = _tone(300.0, 0.25, audio.TARGET_RATE)
    path = tmp_path / "a.wav"
    digest = audio.write_wav(path, samples)
    assert digest == audio.sha256_file(path)
    back, rate = audio.decode(path.read_bytes())
    assert rate == audio.TARGET_RATE
    assert len(back) == len(samples)
    assert float(np.max(np.abs(back - samples))) < 2e-4


def test_mix_noise_hits_the_requested_snr() -> None:
    speech = _tone(300.0, 1.0, audio.TARGET_RATE)
    rng = np.random.default_rng(0)
    noise = rng.standard_normal(audio.TARGET_RATE).astype(np.float32) * 0.1
    mixed = audio.mix_noise(speech, noise, 10.0, seed=1)
    residual = mixed - speech
    snr = 20 * math.log10(
        float(np.sqrt(np.mean(np.square(speech)))) / float(np.sqrt(np.mean(np.square(residual))))
    )
    assert abs(snr - 10.0) < 0.5


def test_mix_noise_tiles_a_short_clip() -> None:
    speech = _tone(300.0, 1.0, audio.TARGET_RATE)
    short = _tone(80.0, 0.1, audio.TARGET_RATE)
    mixed = audio.mix_noise(speech, short, 10.0, seed=2)
    assert len(mixed) == len(speech)


def test_apply_rir_keeps_length_and_loudness() -> None:
    speech = _tone(300.0, 1.0, audio.TARGET_RATE)
    rir = np.zeros(400, dtype=np.float32)
    rir[10] = 1.0
    rir[120] = 0.4
    rir[300] = 0.2
    wet = audio.apply_rir(speech, rir)
    assert len(wet) == len(speech)
    dry_rms = float(np.sqrt(np.mean(np.square(speech))))
    wet_rms = float(np.sqrt(np.mean(np.square(wet))))
    assert abs(wet_rms - dry_rms) / dry_rms < 0.02


def test_apply_rir_aligns_on_the_direct_path() -> None:
    # A simulated RIR carries propagation delay before its direct-path peak. Left in, it
    # would shift every word and a paired clean-vs-reverb comparison would be measuring
    # misalignment rather than reverberation.
    impulse = np.zeros(2000, dtype=np.float32)
    impulse[0] = 1.0
    rir = np.zeros(500, dtype=np.float32)
    rir[200] = 1.0
    wet = audio.apply_rir(impulse, rir)
    assert int(np.argmax(np.abs(wet))) == 0


def test_transforms_do_not_clip() -> None:
    loud = _tone(300.0, 0.5, audio.TARGET_RATE) * 1.9
    rng = np.random.default_rng(3)
    noise = rng.standard_normal(audio.TARGET_RATE).astype(np.float32)
    assert float(np.max(np.abs(audio.mix_noise(loud, noise, 0.0, seed=4)))) <= 1.0
    rir = np.zeros(200, dtype=np.float32)
    rir[0] = 1.0
    assert float(np.max(np.abs(audio.apply_rir(loud, rir)))) <= 1.0


# ----------------------------------------------------------------------------- spec


def test_spec_matches_the_registry_and_the_size_target(repo_root) -> None:
    spec = json.loads(
        (repo_root / "eval" / "datasets" / "public-proxy-v1" / "spec.json").read_text("utf-8")
    )
    subsets = {s["subset"] for s in spec["strata"]}
    for stratum in spec["strata"]:
        assert stratum["source"] in SOURCES
    total = sum(int(s["n"]) for s in spec["strata"])
    for plan in spec["perturbations"]:
        assert set(plan["from"]) <= subsets
        total += int(plan["n"])
    assert 120 <= total <= 200, "Public Proxy Set v1 is specified at 120-200 utterances"


def test_integer_speaker_ids_are_read_not_dropped() -> None:
    # LibriSpeech stores speaker_id as int64. A str-only reader returned None for every
    # row, which silently disabled the per-speaker quota and produced a sample whose
    # speaker disjointness could not be checked. Regression test for exactly that.
    source = SOURCES["librispeech_test_clean"]
    row = {"text": "X", "speaker_id": 6930, "chapter_id": 75918, "id": "6930-75918-0004"}
    assert source.speaker_of(row) == "6930"
    assert source.row_id_of(4, row) == "4:6930-75918-0004"


def test_sources_declare_whether_they_publish_speakers() -> None:
    for key, source in SOURCES.items():
        probe = {"speaker": "S", "speaker_id": 1, "audio_filepath": "audio/9/8/a.wav"}
        resolved = source.speaker_of(probe)
        if source.publishes_speakers:
            assert resolved, f"{key} claims speaker identity but resolves none"
        else:
            assert resolved is None, f"{key} claims no speaker identity but resolved one"
