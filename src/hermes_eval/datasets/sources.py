"""The pinned source registry: what we sample from, at which revision, under which licence.

Every entry here was verified on 2026-09-26 against the live dataset: revision sha, split
row count, column names, whether speaker identity exists, and the licence text itself
(Golos' licence is a PDF, and reading it changed the verdict — see `licence_note`).

Adding a source means answering the same questions. A source whose commercial terms are
unclear does not go in the registry; it goes in
`eval/datasets/public-proxy-v1/LICENSES.md` under "rejected", with the reason.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Reference formatting, per manifest.REFERENCE_STYLES. No public source in the registry
# ships a formatted reference, which is the single most important thing to know about
# this proxy set: it can measure WER, it cannot measure F-WER.
CAPS = "caps_nopunct"
LOWER = "lower_nopunct"


@dataclass(frozen=True)
class Source:
    key: str
    dataset: str
    config: str
    split: str
    revision: str
    """Full commit sha on the Hugging Face hub. Verified at fetch time against the sha
    embedded in the served asset URL; a mismatch aborts the build."""
    n_rows: int
    """Row count observed at pinning time. A drift here is the same red flag as a
    revision mismatch."""
    audio_field: str
    text_field: str
    parquet_patterns: tuple[str, ...]
    """Glob(s) resolving the split's parquet shards inside the repository. Sorted shard
    order is what defines the split-global row index."""
    meta_columns: tuple[str, ...]
    """Non-audio columns to read. Naming them explicitly is what keeps the metadata pass
    to kilobytes instead of gigabytes."""
    reference_style: str
    language: str
    license: str
    license_url: str
    source_url: str
    publishes_speakers: bool
    """Whether the corpus publishes speaker identity at all. When True, a build that
    resolves zero speakers is a bug in the field mapping, not a property of the data, and
    the build fails rather than shipping an unenforced speaker quota."""
    speaker_of: Callable[[dict[str, Any]], str | None]
    """Speaker identity for a row, or None when the corpus does not publish it. Golos
    genuinely does not: its crowd data comes from anonymous Toloka workers."""
    row_id_of: Callable[[int, dict[str, Any]], str]
    accent_of: Callable[[dict[str, Any]], str]
    domain: str
    category: str
    licence_note: str = ""
    extra_of: Callable[[dict[str, Any]], dict[str, str]] = field(default=lambda _row: {})


def _first_str(row: dict[str, Any], key: str) -> str:
    """Read a scalar column as a string.

    Integers are coerced on purpose: LibriSpeech stores `speaker_id` and `chapter_id` as
    int64 in parquet, and a str-only reader silently returned None for every speaker —
    which silently disabled the per-speaker quota. `publishes_speakers` now turns that
    class of mistake into a failed build instead of a quietly wrong sample.
    """
    value = row.get(key)
    if isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return ""


def _ruls_reader(row: dict[str, Any]) -> str | None:
    # 'audio/2671/2145/poemi_01_pushkin_0000.wav' -> LibriVox reader 2671. RuLS splits are
    # reader-disjoint by construction (train 5 readers, dev 1, test 7, no overlap), which
    # is verified in CHAPTERS_READERS.TXT and is why this corpus needs no extra guard.
    parts = _first_str(row, "audio_filepath").split("/")
    return parts[1] if len(parts) > 2 else None


def _ruls_row_id(idx: int, row: dict[str, Any]) -> str:
    path = _first_str(row, "audio_filepath")
    return f"{idx}:{path}" if path else str(idx)


def _edacc_accent(row: dict[str, Any]) -> str:
    accent = _first_str(row, "accent") or "unknown"
    return accent.strip().lower().replace(" ", "-")


SOURCES: dict[str, Source] = {
    "edacc_test": Source(
        key="edacc_test",
        dataset="edinburghcstr/edacc",
        config="default",
        split="test",
        revision="d9ae7bd344f0562b766ec93ee5ce8f2f9568ce66",
        n_rows=9289,
        audio_field="audio",
        text_field="text",
        parquet_patterns=("data/test-*.parquet",),
        meta_columns=("speaker", "text", "accent", "raw_accent", "gender", "l1"),
        reference_style=CAPS,
        language="en",
        license="CC-BY-SA-4.0",
        license_url="https://creativecommons.org/licenses/by-sa/4.0/",
        source_url="https://huggingface.co/datasets/edinburghcstr/edacc",
        publishes_speakers=True,
        speaker_of=lambda row: _first_str(row, "speaker") or None,
        row_id_of=lambda idx, row: f"{idx}:{_first_str(row, 'speaker')}",
        accent_of=_edacc_accent,
        domain="conversation",
        category="prose",
        licence_note=(
            "ShareAlike. Derived audio is Adapted Material, so no audio is redistributed "
            "from this repository — the manifest plus the fetcher reproduces it locally."
        ),
        extra_of=lambda row: {
            "l1": _first_str(row, "l1"),
            "gender": _first_str(row, "gender"),
            "raw_accent": _first_str(row, "raw_accent"),
        },
    ),
    "librispeech_test_clean": Source(
        key="librispeech_test_clean",
        dataset="openslr/librispeech_asr",
        config="clean",
        split="test",
        revision="71cacbfb7e2354c4226d01e70d77d5fca3d04ba1",
        n_rows=2620,
        audio_field="audio",
        text_field="text",
        parquet_patterns=("clean/test/*.parquet",),
        meta_columns=("text", "speaker_id", "chapter_id", "id"),
        reference_style=CAPS,
        language="en",
        license="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        source_url="https://huggingface.co/datasets/openslr/librispeech_asr",
        publishes_speakers=True,
        speaker_of=lambda row: _first_str(row, "speaker_id") or None,
        row_id_of=lambda idx, row: f"{idx}:{_first_str(row, 'id')}",
        accent_of=lambda _row: "en-read",
        domain="literature",
        category="prose",
        licence_note="Audio served as FLAC; decoding needs the optional `data` group.",
        extra_of=lambda row: {"chapter_id": _first_str(row, "chapter_id")},
    ),
    "ruls_test": Source(
        key="ruls_test",
        dataset="istupakov/russian_librispeech",
        config="default",
        split="test",
        revision="a519c986bb3342cc8136d3d14e5ad8a4f1e1a2bd",
        n_rows=1352,
        audio_field="audio",
        text_field="text",
        parquet_patterns=("data/test-*.parquet",),
        meta_columns=("text", "duration", "audio_filepath"),
        reference_style=LOWER,
        language="ru",
        license="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        source_url="https://huggingface.co/datasets/istupakov/russian_librispeech",
        publishes_speakers=True,
        speaker_of=_ruls_reader,
        row_id_of=_ruls_row_id,
        accent_of=lambda _row: "ru-read",
        domain="literature",
        category="prose",
        licence_note=(
            "Upstream RuLS (OpenSLR 96, NVIDIA, from LibriVox) states 'Public Domain in "
            "the USA'; this mirror declares CC-BY-4.0. Both are permissive; attribute "
            "both. Use the `text` column only — `text_no_preprocessing` is mojibake-"
            "corrupted on Cyrillic sentence-initial characters in this mirror."
        ),
    ),
    "golos_crowd_test": Source(
        key="golos_crowd_test",
        dataset="bond005/sberdevices_golos_10h_crowd",
        config="default",
        split="test",
        revision="e634b6b810e4d30c81b4c6d8262379fe8b9f708c",
        n_rows=9994,
        audio_field="audio",
        text_field="transcription",
        parquet_patterns=("data/test-*.parquet",),
        meta_columns=("transcription",),
        reference_style=LOWER,
        language="ru",
        license="Golos Public License (CC-BY-SA-4.0 reword, not a Creative Commons licence)",
        license_url="https://github.com/sberdevices/golos/blob/master/license/en_us.pdf",
        source_url="https://huggingface.co/datasets/bond005/sberdevices_golos_10h_crowd",
        publishes_speakers=False,
        speaker_of=lambda _row: None,
        row_id_of=lambda idx, _row: str(idx),
        accent_of=lambda _row: "ru-crowd",
        domain="smart-speaker",
        category="command",
        licence_note=(
            "Licence text read in full: worldwide, royalty-free, irrevocable, attribution "
            "+ ShareAlike, no non-commercial clause, governed by Russian law. NOT a "
            "Creative Commons licence, by its own first footnote. No speaker identity is "
            "published, so speaker-disjoint sampling is impossible here by construction."
        ),
    ),
    "golos_farfield_test": Source(
        key="golos_farfield_test",
        dataset="bond005/sberdevices_golos_100h_farfield",
        config="default",
        split="test",
        revision="c93949f7140beef4adc404e7b54841e957f81c54",
        n_rows=1916,
        audio_field="audio",
        text_field="transcription",
        parquet_patterns=("data/test-*.parquet",),
        meta_columns=("transcription",),
        reference_style=LOWER,
        language="ru",
        license="Golos Public License (CC-BY-SA-4.0 reword, not a Creative Commons licence)",
        license_url="https://github.com/sberdevices/golos/blob/master/license/en_us.pdf",
        source_url="https://huggingface.co/datasets/bond005/sberdevices_golos_100h_farfield",
        publishes_speakers=False,
        speaker_of=lambda _row: None,
        row_id_of=lambda idx, _row: str(idx),
        accent_of=lambda _row: "ru-farfield",
        domain="smart-speaker",
        category="command",
        licence_note=(
            "Same licence as the crowd split. Recorded on SberPortal devices at 1 m, 3 m "
            "and 5 m — genuine far-field, which is why it carries noise=far-field rather "
            "than being treated as clean Russian."
        ),
    ),
}


# ------------------------------------------------------------- augmentation material

RIR_ZIP_URL = "https://www.openslr.org/resources/28/rirs_noises.zip"
RIR_ZIP_BYTES = 1311166223
RIR_LICENSE = "Apache-2.0"
RIR_LICENSE_URL = "https://www.openslr.org/28/"

# The point-source noises inside rirs_noises.zip *are* MUSAN's free-sound noise clips.
# Taking them from here costs a range-read of a 1.3 GB ZIP instead of an 11 GB tarball
# with no subset access, which is why MUSAN is not fetched directly.
NOISE_PREFIX = "RIRS_NOISES/pointsource_noises/noise-free-sound-"
MUSAN_ATTRIBUTION = "MUSAN (CC-BY-4.0, https://www.openslr.org/17/), redistributed in OpenSLR 28"

RIR_PREFIXES = (
    "RIRS_NOISES/simulated_rirs/smallroom/",
    "RIRS_NOISES/simulated_rirs/mediumroom/",
)
