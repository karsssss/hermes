"""Subset access to public corpora: HF datasets-server rows, and range-read ZIP members.

Two access paths, both deliberately *partial*. Downloading a 5 GB corpus to score 50
utterances is not a download policy, it is an accident waiting to happen on a laptop.

1. `scan_metadata` / `fetch_asset` — the Hugging Face datasets-server `/rows` endpoint.
   It returns non-audio columns as JSON plus a per-row audio asset URL, so the metadata
   pass costs kilobytes and the audio pass costs exactly the rows we sampled. The
   metadata pass is cached on disk; re-running a build touches the network only for
   audio.

   Revision pinning: `/rows` has no revision parameter — it always serves the dataset's
   current default branch. The asset URLs, however, embed the commit sha. So we pin by
   *verification*: the caller states the revision it designed the sample against, and
   `check_revision` fails loudly if the server is serving something else. A silent
   upstream re-upload is exactly the failure that makes an old benchmark number a lie.

2. `ZipOverHttp` — a seekable file object over HTTP Range requests, handed to
   `zipfile.ZipFile`. OpenSLR's rirs_noises.zip is 1.3 GB; reading its central directory
   costs ~8 MB and each RIR or noise clip after that costs a few hundred kilobytes.

Stdlib only. Everything here is `urllib`.
"""

from __future__ import annotations

import io
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROWS_ENDPOINT = "https://datasets-server.huggingface.co/rows"
PAGE = 100
USER_AGENT = "hermes-eval/0.1 (+https://github.com/hermes; public benchmark build tool)"

# The datasets-server rate-limits anonymous callers on a short-window token bucket: a
# burst of about thirty requests empties it and it refills within minutes. Pacing plus a
# backoff that is willing to wait minutes, not seconds, is what makes an unattended build
# finish; combined with the on-disk asset cache below, an interrupted build resumes
# instead of restarting.
PACE_S = 1.0
MAX_RETRIES = 9
MAX_BACKOFF_S = 300.0


class HubError(RuntimeError):
    pass


class RevisionMismatch(HubError):
    """The server is serving a different commit than the manifest was designed against."""


def _auth_headers() -> dict[str, str]:
    """Use a Hugging Face token when the environment already has one.

    It is never required: every source in the registry is ungated, and a build that only
    works for someone holding a credential is not a reproducible build. A token simply
    buys a larger rate-limit bucket.
    """
    import os

    for name in ("HF_TOKEN", "HUGGINGFACE_HUB_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        token = os.environ.get(name)
        if token:
            return {"Authorization": f"Bearer {token}"}
    return {}


def _get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 120.0,
    on_wait: Any = None,
) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, **_auth_headers(), **(headers or {})}
    )
    delay = 2.0
    last: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in (429, 500, 502, 503, 504):
                raise HubError(f"{exc.code} {exc.reason} for {url}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
        if attempt < MAX_RETRIES - 1:
            if on_wait is not None:
                on_wait(delay, attempt, last)
            time.sleep(delay)
            delay = min(delay * 2, MAX_BACKOFF_S)
    raise HubError(f"giving up on {url} after {MAX_RETRIES} attempts: {last}")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _report_wait(delay: float, attempt: int, exc: Exception | None) -> None:
    print(f"    rate-limited ({exc}); retry {attempt + 1} in {delay:.0f}s", flush=True)


# --------------------------------------------------------------- datasets-server rows


def _rows_url(dataset: str, config: str, split: str, offset: int, length: int) -> str:
    query = urllib.parse.urlencode(
        {
            "dataset": dataset,
            "config": config,
            "split": split,
            "offset": offset,
            "length": length,
        }
    )
    return f"{ROWS_ENDPOINT}?{query}"


def rows(dataset: str, config: str, split: str, offset: int, length: int = PAGE) -> dict[str, Any]:
    payload = json.loads(
        _get(_rows_url(dataset, config, split, offset, length), on_wait=_report_wait)
    )
    if "error" in payload:
        raise HubError(f"{dataset}/{config}/{split} offset={offset}: {payload['error']}")
    return payload


_REVISION_IN_ASSET = re.compile(r"/(?:cached-)?assets/[^?]*?/--/([0-9a-f]{40})/--/")


def observed_revision(row: dict[str, Any], audio_field: str) -> str | None:
    """Pull the commit sha the server is serving out of an audio asset URL."""
    value = row.get(audio_field)
    if not isinstance(value, list) or not value:
        return None
    src = value[0].get("src")
    if not isinstance(src, str):
        return None
    match = _REVISION_IN_ASSET.search(src)
    return match.group(1) if match else None


def check_revision(seen: str | None, expected: str, where: str) -> None:
    if seen is None:
        raise HubError(f"{where}: could not read a revision out of the asset URL")
    if seen != expected:
        raise RevisionMismatch(
            f"{where}: pinned revision {expected} but the datasets-server is serving {seen}. "
            "Upstream re-uploaded. Re-pin the source in sources.py and rebuild the manifest "
            "with a fresh seed rather than silently scoring different audio."
        )


@dataclass(frozen=True)
class Fetched:
    """Where an asset came from and when.

    `retrieved_utc` is cached alongside the bytes rather than regenerated per build, so a
    rebuild from a warm cache reproduces the manifest byte for byte. A timestamp that
    moved on every run would make "the manifest is reproducible" untestable, and an
    untestable claim about reproducibility is the one kind not worth making.
    """

    url: str
    retrieved_utc: str


@dataclass(frozen=True)
class RowMeta:
    """One source row, non-audio columns only. This is what sampling runs over."""

    row_idx: int
    fields: dict[str, Any]


def scan_metadata(
    dataset: str,
    config: str,
    split: str,
    *,
    revision: str,
    audio_field: str,
    cache_dir: Path,
    progress: bool = True,
) -> list[RowMeta]:
    """Page the whole split collecting non-audio columns, cached on disk.

    Costs one request per 100 rows, once. The cache key includes the pinned revision, so
    re-pinning forces a re-scan instead of quietly reusing stale metadata.
    """
    safe = f"{dataset}-{config}-{split}".replace("/", "__")
    cache = Path(cache_dir) / f"rows-{safe}-{revision[:12]}.jsonl"
    if cache.exists():
        out = []
        for line in cache.read_text(encoding="utf-8").splitlines():
            if line.strip():
                obj = json.loads(line)
                out.append(RowMeta(obj["row_idx"], obj["fields"]))
        return out

    collected: list[RowMeta] = []
    offset = 0
    total: int | None = None
    checked = False
    while total is None or offset < total:
        payload = rows(dataset, config, split, offset, PAGE)
        total = int(payload["num_rows_total"])
        batch = payload["rows"]
        if not batch:
            break
        if not checked:
            check_revision(
                observed_revision(batch[0]["row"], audio_field),
                revision,
                f"{dataset}/{config}/{split}",
            )
            checked = True
        for item in batch:
            row = item["row"]
            collected.append(
                RowMeta(
                    int(item["row_idx"]),
                    {k: v for k, v in row.items() if k != audio_field},
                )
            )
        offset += len(batch)
        if progress:
            print(f"  scan {dataset}/{split}: {offset}/{total}", flush=True)
        if offset < total:
            time.sleep(PACE_S)

    cache.parent.mkdir(parents=True, exist_ok=True)
    with cache.open("w", encoding="utf-8", newline="\n") as fh:
        for meta in collected:
            fh.write(
                json.dumps({"row_idx": meta.row_idx, "fields": meta.fields}, ensure_ascii=False)
                + "\n"
            )
    return collected


def fetch_asset(
    dataset: str,
    config: str,
    split: str,
    row_idx: int,
    *,
    revision: str,
    audio_field: str,
    cache_dir: Path | None = None,
) -> tuple[bytes, Fetched]:
    """Download one row's audio asset. Returns (bytes, provenance of the fetch).

    The asset URL is signed and expires, so it is regenerated per fetch and only its
    unsigned prefix is recorded. Reproducibility comes from the pinned revision plus the
    sha256 of the bytes, not from a URL that will not resolve next month.

    Cached on disk under the pinned revision. Re-running a build after a rate-limit stall
    then costs nothing, which is the difference between a build that gets re-run and one
    that does not.
    """
    cached: Path | None = None
    if cache_dir is not None:
        safe = f"{dataset}-{config}-{split}".replace("/", "__")
        cached = Path(cache_dir) / "assets" / f"{safe}-{revision[:12]}-{row_idx:08d}"
        meta = cached.with_suffix(".json")
        if cached.exists() and meta.exists():
            sidecar = json.loads(meta.read_text(encoding="utf-8"))
            return cached.read_bytes(), Fetched(sidecar["url"], sidecar["retrieved_utc"])

    payload = rows(dataset, config, split, row_idx, 1)
    batch = payload["rows"]
    if not batch or int(batch[0]["row_idx"]) != row_idx:
        raise HubError(f"{dataset}/{config}/{split}: row {row_idx} not returned")
    row = batch[0]["row"]
    check_revision(
        observed_revision(row, audio_field), revision, f"{dataset}/{config}/{split}#{row_idx}"
    )
    value = row.get(audio_field)
    if not isinstance(value, list) or not value or not value[0].get("src"):
        raise HubError(f"{dataset}/{config}/{split}: row {row_idx} has no audio asset")
    src = str(value[0]["src"])
    data = _get(src, on_wait=_report_wait)
    # Pace the *next* caller rather than sprinting into the bucket and then waiting
    # minutes for it to refill. Steady beats bursty against a token bucket.
    time.sleep(PACE_S)
    fetched = Fetched(src.split("?")[0], _utc_now())
    if cached is not None:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
        cached.with_suffix(".json").write_text(
            json.dumps({"url": fetched.url, "retrieved_utc": fetched.retrieved_utc}),
            encoding="utf-8",
        )
    return data, fetched


# ------------------------------------------------------------------ range-read ZIP


class _HttpRangeFile(io.RawIOBase):
    """Minimal seekable read-only file over HTTP Range. Enough for `zipfile`."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._pos = 0
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp:
            length = resp.headers.get("Content-Length")
            if not length:
                raise HubError(f"{url}: server did not report Content-Length")
            self.size = int(length)
        self.requests = 0
        self.downloaded = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self._pos = offset
        elif whence == io.SEEK_CUR:
            self._pos += offset
        else:
            self._pos = self.size + offset
        return self._pos

    def tell(self) -> int:
        return self._pos

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = self.size - self._pos
        if size <= 0 or self._pos >= self.size:
            return b""
        end = min(self._pos + size, self.size) - 1
        data = _get(self.url, headers={"Range": f"bytes={self._pos}-{end}"})
        self.requests += 1
        self.downloaded += len(data)
        self._pos += len(data)
        return data

    def readinto(self, buffer: Any) -> int:  # pragma: no cover - exercised via zipfile
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


class ZipOverHttp:
    """Read individual members of a remote ZIP without downloading the archive."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._file = _HttpRangeFile(url)
        self._zip = zipfile.ZipFile(self._file)

    @property
    def total_bytes(self) -> int:
        return self._file.size

    @property
    def downloaded_bytes(self) -> int:
        return self._file.downloaded

    def names(self) -> list[str]:
        return self._zip.namelist()

    def read(self, name: str) -> bytes:
        return self._zip.read(name)

    def close(self) -> None:
        self._zip.close()
        self._file.close()

    def __enter__(self) -> ZipOverHttp:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def deterministic_choice(items: list[str], seed_key: str, count: int) -> list[str]:
    """A seeded, order-independent pick. `items` is sorted first so an upstream listing
    reshuffle cannot change the selection."""
    pool = sorted(items)
    rng = random.Random(seed_key)
    if count >= len(pool):
        return pool
    return [pool[i] for i in sorted(rng.sample(range(len(pool)), count))]


def iter_pages(total: int, page: int = PAGE) -> Iterator[int]:
    offset = 0
    while offset < total:
        yield offset
        offset += page
