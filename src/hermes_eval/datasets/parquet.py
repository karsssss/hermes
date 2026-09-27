"""Metadata scanning straight from the pinned parquet, with column pruning.

Why not the datasets-server for this: paging 9289 EdAcc rows costs 93 requests and the
anonymous endpoint rate-limits well before that. Parquet column pruning gets the same
information in one pass over a few hundred kilobytes, because the non-audio columns of an
EdAcc row group total about 10 KB against 53 MB of audio in the same row group — the
reader never touches the audio column chunk at all.

It is also the stronger pin. `HfFileSystem` resolves `datasets/<repo>@<sha>/<path>`, so
the revision is part of the read rather than something inferred afterwards from a URL.

Row ordering: `datasets` numbers a split's rows by concatenating its shards in sorted
filename order, which is what `_shards` reproduces. `verify_alignment` spot-checks that
assumption against the datasets-server — if the two ever disagree, every row_id in the
manifest would point at the wrong audio, so it is worth one request to find out.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .hub import HubError, RowMeta


class ParquetUnavailable(RuntimeError):
    pass


def _filesystem() -> Any:
    try:
        from huggingface_hub import HfFileSystem
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise ParquetUnavailable(
            "huggingface_hub is required for the parquet metadata pass: `uv sync --group data`"
        ) from exc
    return HfFileSystem()


def _parquet() -> Any:
    try:
        import pyarrow.parquet
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise ParquetUnavailable(
            "pyarrow is required for the parquet metadata pass: `uv sync --group data`"
        ) from exc
    return pyarrow.parquet


def _shards(fs: Any, dataset: str, revision: str, patterns: tuple[str, ...]) -> list[str]:
    root = f"datasets/{dataset}@{revision}"
    found: list[str] = []
    for pattern in patterns:
        found.extend(str(p) for p in fs.glob(f"{root}/{pattern}"))
    if not found:
        raise HubError(
            f"{dataset}@{revision}: no parquet shards matched {patterns}. "
            "The repository layout changed; re-pin the source."
        )
    return sorted(set(found))


def scan(
    dataset: str,
    revision: str,
    patterns: tuple[str, ...],
    columns: list[str],
) -> list[RowMeta]:
    """Read the named columns of every row in the split, in split order."""
    pq = _parquet()
    fs = _filesystem()
    out: list[RowMeta] = []
    index = 0
    for shard in _shards(fs, dataset, revision, patterns):
        with fs.open(shard, "rb") as handle:
            table = pq.ParquetFile(handle).read(columns=columns)
        for row in table.to_pylist():
            out.append(RowMeta(index, row))
            index += 1
    return out


def verify_alignment(
    metas: list[RowMeta],
    *,
    dataset: str,
    config: str,
    split: str,
    revision: str,
    audio_field: str,
    text_field: str,
    probe_rows: tuple[int, ...] = (0,),
) -> None:
    """Confirm parquet row N and datasets-server row N are the same utterance."""
    from .hub import check_revision, observed_revision, rows

    by_index = {meta.row_idx: meta for meta in metas}
    for row_idx in probe_rows:
        if row_idx not in by_index:
            continue
        payload = rows(dataset, config, split, row_idx, 1)
        batch = payload["rows"]
        if not batch:
            raise HubError(f"{dataset}/{split}: probe row {row_idx} returned nothing")
        served = batch[0]["row"]
        check_revision(
            observed_revision(served, audio_field), revision, f"{dataset}/{config}/{split}"
        )
        if int(payload["num_rows_total"]) != len(metas):
            raise HubError(
                f"{dataset}/{split}: parquet has {len(metas)} rows, the datasets-server "
                f"reports {payload['num_rows_total']}. Row indices would not line up."
            )
        mine = str(by_index[row_idx].fields.get(text_field, ""))
        theirs = str(served.get(text_field, ""))
        if mine.strip() != theirs.strip():
            raise HubError(
                f"{dataset}/{split}: row {row_idx} differs between the parquet shards and "
                f"the datasets-server ({mine[:40]!r} vs {theirs[:40]!r}). Shard ordering "
                "is not what the row index assumes; do not build a manifest from this."
            )


def cache_path(cache_dir: Path, dataset: str, split: str, revision: str) -> Path:
    safe = f"{dataset}-{split}".replace("/", "__")
    return Path(cache_dir) / f"meta-{safe}-{revision[:12]}.jsonl"
