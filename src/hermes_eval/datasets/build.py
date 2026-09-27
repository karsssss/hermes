"""Deterministic sampling and manifest generation for the public proxy set.

The contract this module exists to keep: given the same spec file, the same seed and the
same pinned revisions, the build produces byte-identical audio and a byte-identical
manifest. Everything that could drift is either pinned and verified (dataset revision),
recorded (sha256 of every WAV written), or derived from a seed that is written into the
record itself.

Sampling is a seeded permutation with quotas, not a top-N scan:

1. Page the split's non-audio columns once (cached), so sampling runs over the whole
   split rather than over whatever the first page happened to contain.
2. Drop rows failing the text filters.
3. Sort by source row index — never trust server page order — then take a seeded
   permutation of that list.
4. Walk the permutation, accepting a row unless it would exceed its speaker quota or its
   stratum quota, and unless its audio falls outside the duration bounds. Duration is only
   knowable after download for most sources, so it is a post-fetch rejection.

Speaker quotas do the work requirement 4 asks for. Where a corpus publishes no speaker
identity — Golos does not, by design — the quota cannot be enforced and the build records
`speaker_id: null`, which is visible in the manifest rather than assumed away.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..provenance import utc_now
from . import audio as au
from . import hub
from . import parquet as pqmeta
from .sources import (
    MUSAN_ATTRIBUTION,
    NOISE_PREFIX,
    RIR_LICENSE,
    RIR_LICENSE_URL,
    RIR_PREFIXES,
    RIR_ZIP_URL,
    SOURCES,
    Source,
)


class BuildError(RuntimeError):
    pass


@dataclass
class BuildReport:
    manifest_path: Path
    records: list[dict[str, Any]] = field(default_factory=list)
    per_subset: dict[str, int] = field(default_factory=dict)
    speakers_per_subset: dict[str, int] = field(default_factory=dict)
    examined: dict[str, int] = field(default_factory=dict)
    rejected: dict[str, dict[str, int]] = field(default_factory=dict)
    bytes_fetched: int = 0
    warnings: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------- filtering


def _text_of(source: Source, row: dict[str, Any]) -> str:
    value = row.get(source.text_field)
    return value.strip() if isinstance(value, str) else ""


def _fields_for(source: Source, row: dict[str, Any]) -> dict[str, Any]:
    merged = dict(row)
    merged.update(source.extra_of(row))
    return merged


def _passes_text_filters(text: str, stratum: dict[str, Any]) -> str | None:
    """Return a rejection reason, or None when the row is eligible."""
    if not text:
        return "empty_text"
    tokens = text.split()
    if len(tokens) < int(stratum.get("min_tokens", 1)):
        return "too_few_tokens"
    if len(tokens) > int(stratum.get("max_tokens", 10_000)):
        return "too_many_tokens"
    return None


def _passes_field_filters(fields: dict[str, Any], stratum: dict[str, Any]) -> str | None:
    for name, suffix in (stratum.get("exclude_suffix") or {}).items():
        value = fields.get(name)
        if isinstance(value, str) and value.strip().endswith(suffix):
            return f"excluded_{name}_suffix"
    for name, suffix in (stratum.get("require_suffix") or {}).items():
        value = fields.get(name)
        if not isinstance(value, str) or not value.strip().endswith(suffix):
            return f"required_{name}_suffix"
    return None


# -------------------------------------------------------------------------- sampling


def _seed_key(spec: dict[str, Any], *parts: str) -> str:
    return "|".join((str(spec["seed"]), str(spec["name"]), *parts))


def _metadata(source: Source, cache_dir: Path, progress: bool) -> list[hub.RowMeta]:
    """Non-audio columns for the whole split, cached on disk under the pinned revision.

    Parquet first: one column-pruned pass costs kilobytes and no rate limit. The
    datasets-server fallback exists so the build still works without the optional `data`
    group, at the cost of one request per hundred rows.
    """
    cache = pqmeta.cache_path(cache_dir, source.dataset, source.split, source.revision)
    if cache.exists():
        return [
            hub.RowMeta(obj["row_idx"], obj["fields"])
            for obj in (
                json.loads(line)
                for line in cache.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        ]

    try:
        if progress:
            print(f"  metadata: {source.dataset}@{source.revision[:12]} (parquet)", flush=True)
        metas = pqmeta.scan(
            source.dataset,
            source.revision,
            source.parquet_patterns,
            list(source.meta_columns),
        )
        # One request, to prove parquet row N and datasets-server row N are the same
        # utterance. If they are not, every row_id in the manifest points at the wrong
        # audio, and that is not a thing to discover after publishing.
        pqmeta.verify_alignment(
            metas,
            dataset=source.dataset,
            config=source.config,
            split=source.split,
            revision=source.revision,
            audio_field=source.audio_field,
            text_field=source.text_field,
            probe_rows=(0, len(metas) // 2),
        )
    except pqmeta.ParquetUnavailable as exc:
        if progress:
            print(f"  metadata: falling back to datasets-server paging ({exc})", flush=True)
        metas = hub.scan_metadata(
            source.dataset,
            source.config,
            source.split,
            revision=source.revision,
            audio_field=source.audio_field,
            cache_dir=cache_dir,
            progress=progress,
        )

    cache.parent.mkdir(parents=True, exist_ok=True)
    with cache.open("w", encoding="utf-8", newline="\n") as fh:
        for meta in metas:
            fh.write(
                json.dumps({"row_idx": meta.row_idx, "fields": meta.fields}, ensure_ascii=False)
                + "\n"
            )
    return metas


def _sample_clean(
    spec: dict[str, Any],
    stratum: dict[str, Any],
    out_dir: Path,
    cache_dir: Path,
    report: BuildReport,
    progress: bool,
) -> list[dict[str, Any]]:
    key = str(stratum["source"])
    source = SOURCES.get(key)
    if source is None:
        raise BuildError(f"unknown source {key!r}; known: {sorted(SOURCES)}")
    subset = str(stratum["subset"])
    want = int(stratum["n"])

    metas = _metadata(source, cache_dir, progress)
    if len(metas) != source.n_rows:
        report.warnings.append(
            f"{key}: split has {len(metas)} rows, registry pinned {source.n_rows}. "
            "Upstream changed; re-pin before trusting this manifest."
        )

    rejects: dict[str, int] = {}
    eligible: list[hub.RowMeta] = []
    for meta in sorted(metas, key=lambda m: m.row_idx):
        fields = _fields_for(source, meta.fields)
        reason = _passes_text_filters(_text_of(source, meta.fields), stratum)
        if reason is None:
            reason = _passes_field_filters(fields, stratum)
        if reason is not None:
            rejects[reason] = rejects.get(reason, 0) + 1
            continue
        eligible.append(meta)

    rng = random.Random(_seed_key(spec, subset, key, source.revision))
    order = rng.sample(eligible, len(eligible))

    per_speaker_max = int(stratum.get("per_speaker_max", 10**9))
    per_stratum_max = int(stratum.get("per_stratum_max", 10**9))
    stratify_by = stratum.get("stratify_by")
    min_dur = float(stratum.get("min_duration_s", 0.0))
    max_dur = float(stratum.get("max_duration_s", 10**9))
    budget = int(stratum.get("examine_budget", max(want * 8, want + 40)))

    taken_speaker: dict[str, int] = {}
    taken_stratum: dict[str, int] = {}
    records: list[dict[str, Any]] = []
    examined = 0

    for meta in order:
        if len(records) >= want or examined >= budget:
            break
        fields = _fields_for(source, meta.fields)
        speaker = source.speaker_of(meta.fields)
        if speaker is not None and taken_speaker.get(speaker, 0) >= per_speaker_max:
            rejects["speaker_quota"] = rejects.get("speaker_quota", 0) + 1
            continue
        bucket = str(fields.get(stratify_by) or "") if stratify_by else ""
        if stratify_by and taken_stratum.get(bucket, 0) >= per_stratum_max:
            rejects["stratum_quota"] = rejects.get("stratum_quota", 0) + 1
            continue

        examined += 1
        data, fetched = hub.fetch_asset(
            source.dataset,
            source.config,
            source.split,
            meta.row_idx,
            revision=source.revision,
            audio_field=source.audio_field,
            cache_dir=cache_dir,
        )
        report.bytes_fetched += len(data)
        samples, src_rate = au.to_target(data)
        duration = au.duration_s(samples)
        if duration < min_dur or duration > max_dur:
            rejects["duration"] = rejects.get("duration", 0) + 1
            continue

        rid = f"pp1-{source.key}-{meta.row_idx:06d}"
        rel = Path("audio") / f"{rid}.wav"
        written_sha = au.write_wav(out_dir / rel, samples)

        record: dict[str, Any] = {
            "id": rid,
            "audio": rel.as_posix(),
            "duration_s": duration,
            "reference": _text_of(source, meta.fields),
            "metadata": {
                "language": source.language,
                "accent": source.accent_of(meta.fields),
                "domain": source.domain,
                "category": source.category,
                "source": "public-corpus",
                "subset": subset,
                "reference_style": source.reference_style,
                "noise": str(stratum.get("noise_label", "quiet")),
                **({"speaker": speaker} if speaker else {}),
            },
            "provenance": {
                "source": f"hf:{source.dataset}",
                "revision": source.revision,
                "config": source.config,
                "split": source.split,
                "row_id": source.row_id_of(meta.row_idx, meta.fields),
                "speaker_id": speaker,
                "license": source.license,
                "license_url": source.license_url,
                "source_url": fetched.url,
                "source_audio_sha256": au.sha256_bytes(data),
                "source_sample_rate_hz": int(src_rate),
                "audio_sha256": written_sha,
                "sampling_seed": int(spec["seed"]),
                "retrieved_utc": fetched.retrieved_utc,
            },
        }
        records.append(record)
        if speaker is not None:
            taken_speaker[speaker] = taken_speaker.get(speaker, 0) + 1
        if stratify_by:
            taken_stratum[bucket] = taken_stratum.get(bucket, 0) + 1
        if progress:
            print(f"  {subset}: {len(records)}/{want}  ({rid})", flush=True)

    if source.publishes_speakers and not taken_speaker:
        raise BuildError(
            f"{subset}: {key} publishes speaker identity but the build resolved none. "
            "The field mapping in sources.py is wrong, and the per-speaker quota was "
            "therefore not enforced — refusing to emit a sample whose speaker "
            "disjointness cannot be checked."
        )
    if len(records) < want:
        report.warnings.append(
            f"{subset}: wanted {want}, accepted {len(records)} after examining {examined} "
            f"candidates (budget {budget}). Rejections: {rejects}"
        )
    report.examined[subset] = examined
    report.rejected[subset] = rejects
    report.speakers_per_subset[subset] = len(taken_speaker)
    return records


# --------------------------------------------------------------------- perturbations


@dataclass
class _Augmentation:
    zip_handle: hub.ZipOverHttp
    noises: list[str]
    rirs: list[str]


def _open_augmentation(cache_dir: Path, progress: bool) -> _Augmentation:
    listing = Path(cache_dir) / "rirs_noises-members.json"
    handle = hub.ZipOverHttp(RIR_ZIP_URL)
    if listing.exists():
        payload = json.loads(listing.read_text(encoding="utf-8"))
        names = payload["names"]
    else:
        if progress:
            print("  reading rirs_noises.zip central directory (~8 MB)", flush=True)
        names = handle.names()
        listing.parent.mkdir(parents=True, exist_ok=True)
        listing.write_text(
            json.dumps({"url": RIR_ZIP_URL, "names": names}, indent=0), encoding="utf-8"
        )
    noises = [n for n in names if n.startswith(NOISE_PREFIX) and n.endswith(".wav")]
    rirs = [n for n in names if n.endswith(".wav") and n.startswith(RIR_PREFIXES)]
    if not noises or not rirs:
        raise BuildError("rirs_noises.zip did not contain the expected noise/RIR members")
    return _Augmentation(handle, noises, rirs)


def _perturb(
    spec: dict[str, Any],
    plan: dict[str, Any],
    clean: list[dict[str, Any]],
    out_dir: Path,
    aug: _Augmentation,
    report: BuildReport,
    progress: bool,
) -> list[dict[str, Any]]:
    subset = str(plan["subset"])
    kind = str(plan["kind"])
    want = int(plan["n"])
    pool = [r for r in clean if r["metadata"]["subset"] in set(plan["from"])]
    pool.sort(key=lambda r: str(r["id"]))
    if len(pool) < want:
        raise BuildError(f"{subset}: pool has {len(pool)} records, need {want}")

    # `pair_key` lets two perturbation plans draw the *same* source utterances, so that
    # noise and reverb are compared on identical speech rather than on two unrelated
    # samples that differ for reasons nobody can separate afterwards.
    rng = random.Random(_seed_key(spec, str(plan.get("pair_key") or f"{subset}|{kind}")))
    chosen = [pool[i] for i in sorted(rng.sample(range(len(pool)), want))]

    records: list[dict[str, Any]] = []
    for source_record in chosen:
        src_path = out_dir / str(source_record["audio"])
        samples, _rate = au.decode(src_path.read_bytes())
        seed_key = _seed_key(spec, subset, str(source_record["id"]))
        item_seed = int.from_bytes(seed_key.encode("utf-8")[-8:], "little")

        if kind == "noise":
            snr_db = float(plan.get("snr_db", 10.0))
            name = hub.deterministic_choice(aug.noises, seed_key, 1)[0]
            noise, noise_rate = au.decode(aug.zip_handle.read(name))
            noise = au.resample(noise, noise_rate, au.TARGET_RATE)
            out = au.mix_noise(samples, noise, snr_db, item_seed)
            transform = f"noise:snr_db={snr_db:g},clip={name}"
            suffix = f"noise{int(round(snr_db))}"
            noise_label = plan.get("noise_label", "additive-noise")
        elif kind == "reverb":
            name = hub.deterministic_choice(aug.rirs, seed_key, 1)[0]
            rir, rir_rate = au.decode(aug.zip_handle.read(name))
            rir = au.resample(rir, rir_rate, au.TARGET_RATE)
            out = au.apply_rir(samples, rir)
            transform = f"reverb:rir={name}"
            suffix = "reverb"
            noise_label = plan.get("noise_label", "reverberant")
        else:
            raise BuildError(f"unknown perturbation kind {kind!r}")

        rid = f"{source_record['id']}-{suffix}"
        rel = Path("audio") / f"{rid}.wav"
        written_sha = au.write_wav(out_dir / rel, out)

        metadata = dict(source_record["metadata"])
        metadata["subset"] = subset
        metadata["noise"] = str(noise_label)
        metadata["source"] = "public-corpus-augmented"

        provenance = dict(source_record["provenance"])
        provenance["audio_sha256"] = written_sha
        provenance["derived_from"] = str(source_record["id"])
        provenance["transform"] = transform
        provenance["license"] = (
            f"{provenance['license']} + {RIR_LICENSE} (OpenSLR 28); {MUSAN_ATTRIBUTION}"
        )
        provenance["license_url"] = f"{provenance['license_url']} ; {RIR_LICENSE_URL}"
        provenance["source_url"] = RIR_ZIP_URL
        provenance.pop("source_audio_sha256", None)
        # Inherited, not regenerated: the derived record is a pure function of the source
        # bytes and the seed, so it carries the source's retrieval time.

        records.append(
            {
                "id": rid,
                "audio": rel.as_posix(),
                "duration_s": au.duration_s(out),
                "reference": source_record["reference"],
                "metadata": metadata,
                "provenance": provenance,
                "notes": f"derived from {source_record['id']}",
            }
        )
        if progress:
            print(f"  {subset}: {len(records)}/{want}  ({rid})", flush=True)

    report.per_subset[subset] = len(records)
    return records


# ----------------------------------------------------------------------------- build


def build(
    spec_path: Path,
    out_dir: Path,
    *,
    progress: bool = True,
) -> BuildReport:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    out_dir = Path(out_dir)
    cache_dir = out_dir / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    report = BuildReport(manifest_path=out_dir / "manifest.jsonl")
    clean: list[dict[str, Any]] = []
    for stratum in spec["strata"]:
        if progress:
            print(f"[{stratum['subset']}] from {stratum['source']}", flush=True)
        got = _sample_clean(spec, stratum, out_dir, cache_dir, report, progress)
        report.per_subset[str(stratum["subset"])] = len(got)
        clean.extend(got)

    perturbed: list[dict[str, Any]] = []
    plans = spec.get("perturbations") or []
    if plans:
        aug = _open_augmentation(cache_dir, progress)
        try:
            for plan in plans:
                if progress:
                    print(f"[{plan['subset']}] {plan['kind']}", flush=True)
                perturbed.extend(_perturb(spec, plan, clean, out_dir, aug, report, progress))
            report.bytes_fetched += aug.zip_handle.downloaded_bytes
        finally:
            aug.zip_handle.close()

    records = sorted(clean + perturbed, key=lambda r: str(r["id"]))
    report.records = records
    with report.manifest_path.open("w", encoding="utf-8", newline="\n") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    build_record = {
        "spec": spec,
        "built_utc": utc_now(),
        "n_records": len(records),
        "per_subset": report.per_subset,
        "distinct_speakers_per_subset": report.speakers_per_subset,
        "candidates_examined": report.examined,
        "rejections": report.rejected,
        "bytes_fetched": report.bytes_fetched,
        "sources": {
            key: {
                "dataset": src.dataset,
                "config": src.config,
                "split": src.split,
                "revision": src.revision,
                "n_rows_pinned": src.n_rows,
                "license": src.license,
                "license_url": src.license_url,
            }
            for key, src in SOURCES.items()
        },
        "warnings": report.warnings,
    }
    (out_dir / "build.json").write_text(
        json.dumps(build_record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report
