"""Task 2d: Parakeet TDT v3 FP32 on the CPU EP — thread sweep and streaming latency gate.

    uv run --group asr python -m hermes_eval.t2d sweep  [--threads 4,6,8,12] [--rounds 3] [--qos]
    uv run --group asr python -m hermes_eval.t2d stream <run-dir> --threads N [--qos]
    uv run python -m hermes_eval.t2d analyze <run-dir>

Task 2c found that absolute decode times swing ~5x between contiguous stretches of a run,
in both arms, for reasons outside the model. This task exists to produce timing that a
decision can rest on, so every timed process runs beside a **sampler process** that reads
system counters through PDH every 0.5 s: per-logical-processor busy % and performance %
(the P/E split is read from the OS, not assumed — `cpu_topology`), hard page-ins, and
available memory. Every decode row carries its wall-clock window, so a slow or fast row
can be attributed to core placement, frequency or paging instead of being guessed at.

`sweep` runs one fresh **worker process** per (thread count, round): load (timed), warm up
on the synthetic signal Tasks 2a-2c used, decode all 160 rows in manifest order. Thread
counts are interleaved in a different order each round so drift lands on every config.

`stream` replays each utterance in real time against an offline model, the only way this
export can run (it is not cache-aware): partials are re-decodes at a fixed hop, and the
final is produced at push-to-talk release. Two finalization policies are measured — see
`stream_utterance`.

`stream` is resume-safe: each utterance row is fsynced as it completes, a rerun of the
same command skips completed ids and completed policies, cuts only a torn final line, and
refuses (changing nothing) on a malformed or duplicate row. Every streaming session is
appended to run.json as `stream_sessions` with its git SHA and the rows already present.

**`--qos`.** The first (interrupted) Task 2d run found that with Windows left to decide
(`default`), a windowless worker ran entirely on the E-cores, and extra threads only
oversubscribed them. `high` opts the process out of execution-speed throttling — see
`set_qos`. It changes no priority, affinity or power-plan setting, and it is recorded per
worker as read back from the OS.
"""

from __future__ import annotations

import argparse
import bisect
import ctypes
import json
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any

from .bootstrap import paired_bootstrap
from .manifest import load_strict
from .metrics import percentile
from .normalize import tokenize
from .provenance import git_state, hardware, run_id, software, utc_now
from .t2c import ARMS, MANIFEST, REPO, RESAMPLES, SEED, _counts, _jsonl, _rate, _ws

ARM = ARMS["fp32"]
THREADS = (4, 6, 8, 12)
ROUND_ORDERS = ((4, 6, 8, 12), (12, 8, 6, 4), (6, 12, 4, 8), (8, 4, 12, 6))
SAMPLE_S = 0.5
UTF8 = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
QOS = ("default", "high")


# =========================================================================== topology


def cpu_topology() -> dict[str, Any]:
    """Logical processors per physical core, with the core's EfficiencyClass.

    On a hybrid Intel part the higher class is the P-core. A single-class CPU reports every
    logical processor under `p_logical` and none under `e_logical`.
    """
    from ctypes import wintypes as w

    k = ctypes.windll.kernel32  # type: ignore[attr-defined]
    size = w.DWORD(0)
    k.GetLogicalProcessorInformationEx(0, None, ctypes.byref(size))  # RelationProcessorCore
    buf = ctypes.create_string_buffer(size.value)
    if not k.GetLogicalProcessorInformationEx(0, buf, ctypes.byref(size)):
        raise OSError("GetLogicalProcessorInformationEx failed")
    cores = []
    off = 0
    while off < size.value:
        entry = ctypes.c_uint32.from_buffer(buf, off + 4).value
        # PROCESSOR_RELATIONSHIP: Flags, EfficiencyClass, Reserved[20], GroupCount, then
        # GROUP_AFFINITY{KAFFINITY Mask, ...}; the mask sits 32 bytes into the entry.
        mask = ctypes.c_uint64.from_buffer(buf, off + 32).value
        cores.append(
            {
                "efficiency_class": buf.raw[off + 9],
                "smt": bool(buf.raw[off + 8]),
                "logical": [i for i in range(64) if mask >> i & 1],
            }
        )
        off += entry
    top = max(c["efficiency_class"] for c in cores)
    return {
        "p_logical": sorted(i for c in cores if c["efficiency_class"] == top for i in c["logical"]),
        "e_logical": sorted(i for c in cores if c["efficiency_class"] < top for i in c["logical"]),
        "cores": cores,
        "source": "GetLogicalProcessorInformationEx(RelationProcessorCore)",
    }


# ================================================================================ QoS


class _PowerThrottling(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_ulong),
        ("control_mask", ctypes.c_ulong),
        ("state_mask", ctypes.c_ulong),
    ]


_PROCESS_POWER_THROTTLING = 4  # PROCESS_INFORMATION_CLASS.ProcessPowerThrottling
_EXECUTION_SPEED = 0x1  # PROCESS_POWER_THROTTLING_EXECUTION_SPEED


def set_qos(qos: str) -> dict[str, Any]:
    """Apply and read back this process's execution-speed throttling (EcoQoS) state.

    `default` leaves it to Windows (control mask 0), which is what every Task 2a-2c worker
    got. Task 2d's counters show what that means for a windowless console process on this
    hybrid CPU: Windows runs it on the E-cores. `high` opts out explicitly — control mask
    EXECUTION_SPEED, state 0 — which is the documented way for a latency-sensitive process
    to say it must not be throttled. Neither touches priority, affinity or the power plan.
    """
    from ctypes import wintypes as w

    k = ctypes.windll.kernel32  # type: ignore[attr-defined]
    k.GetCurrentProcess.restype = w.HANDLE
    k.SetProcessInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    k.GetProcessInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    k.GetPriorityClass.argtypes = [w.HANDLE]
    proc = k.GetCurrentProcess()
    applied = None
    if qos == "high":
        state = _PowerThrottling(1, _EXECUTION_SPEED, 0)
        applied = bool(
            k.SetProcessInformation(
                proc, _PROCESS_POWER_THROTTLING, ctypes.byref(state), ctypes.sizeof(state)
            )
        )
    elif qos != "default":
        raise ValueError(qos)
    seen = _PowerThrottling(1, 0, 0)
    k.GetProcessInformation(
        proc, _PROCESS_POWER_THROTTLING, ctypes.byref(seen), ctypes.sizeof(seen)
    )
    return {
        "qos": qos,
        "applied": applied,
        "control_mask": seen.control_mask,
        "state_mask": seen.state_mask,
        "priority_class": hex(k.GetPriorityClass(proc)),
    }


# ============================================================================ sampler


def _pdh_sampler(out: Path, stop: Path) -> None:
    """Append one JSON line of system counters every SAMPLE_S until `stop` exists."""
    from ctypes import wintypes as w

    pdh = ctypes.windll.pdh  # type: ignore[attr-defined]

    class Value(ctypes.Structure):
        _fields_ = [("status", w.DWORD), ("pad", w.DWORD), ("value", ctypes.c_double)]

    class Item(ctypes.Structure):
        _fields_ = [("name", w.LPWSTR), ("fmt", Value)]

    query = w.HANDLE()
    if pdh.PdhOpenQueryW(None, 0, ctypes.byref(query)) != 0:
        raise OSError("PdhOpenQueryW failed")
    paths = {
        "busy": r"\Processor Information(*)\% Processor Time",
        "perf": r"\Processor Information(*)\% Processor Performance",
        "page_in": r"\Memory\Pages Input/sec",
        "avail_mb": r"\Memory\Available MBytes",
    }
    handles = {}
    for key, path in paths.items():
        h = w.HANDLE()
        if pdh.PdhAddEnglishCounterW(query, path, 0, ctypes.byref(h)) != 0:
            raise OSError(f"PdhAddEnglishCounterW failed: {path}")
        handles[key] = h

    def read(h: Any) -> dict[str, float]:
        size, n = w.DWORD(0), w.DWORD(0)
        pdh.PdhGetFormattedCounterArrayW(h, 0x200, ctypes.byref(size), ctypes.byref(n), None)
        buf = (ctypes.c_byte * size.value)()
        if pdh.PdhGetFormattedCounterArrayW(h, 0x200, ctypes.byref(size), ctypes.byref(n), buf):
            return {}
        items = ctypes.cast(buf, ctypes.POINTER(Item))
        return {items[i].name: round(items[i].fmt.value, 1) for i in range(n.value)}

    pdh.PdhCollectQueryData(query)
    with out.open("a", encoding="utf-8") as sink:
        while not stop.exists():
            time.sleep(SAMPLE_S)
            pdh.PdhCollectQueryData(query)
            row: dict[str, Any] = {"t": round(time.time(), 3)}
            for key in ("busy", "perf"):
                vals = read(handles[key])
                row[key] = [vals.get(f"0,{i}") for i in range(12)]
                row[f"{key}_total"] = vals.get("_Total")
            row["page_in"] = read(handles["page_in"]).get("")
            row["avail_mb"] = read(handles["avail_mb"]).get("")
            sink.write(json.dumps(row) + "\n")
            sink.flush()


class Sampler:
    def __init__(self, run_dir: Path, name: str = "counters") -> None:
        self.out = run_dir / f"{name}.jsonl"
        self.stop = run_dir / f".{name}.stop"

    def __enter__(self) -> Sampler:
        _cut_torn(self.out, _read_appended(self.out)[1])  # resumed runs append to it
        self.stop.unlink(missing_ok=True)
        cmd = [sys.executable, "-m", "hermes_eval.t2d", "sample", str(self.out), str(self.stop)]
        self.proc = subprocess.Popen(cmd, cwd=REPO)
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop.touch()
        self.proc.wait(timeout=30)
        self.stop.unlink(missing_ok=True)


# ============================================================================= worker


def _cpu_s() -> float:
    t = os.times()
    return t.user + t.system


def load_recognizer(threads: int) -> tuple[Any, dict[str, Any]]:
    from .asr_sherpa import TARGET_RATE, _warmup_signal, ensure_runtime

    ensure_runtime()
    import sherpa_onnx

    model_dir = REPO / "models" / ARM.model_dir
    info: dict[str, Any] = {"memory_before_load": _ws()}
    t0 = time.perf_counter()
    rec = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(model_dir / ARM.encoder),
        decoder=str(model_dir / ARM.decoder),
        joiner=str(model_dir / ARM.joiner),
        tokens=str(model_dir / "tokens.txt"),
        num_threads=threads,
        provider="cpu",
        model_type="nemo_transducer",
        decoding_method="greedy_search",
    )
    info["load_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    info["memory_after_load"] = _ws()
    t0 = time.perf_counter()
    signal = _warmup_signal()
    for _ in range(2):
        decode(rec, signal, TARGET_RATE)
    info["warmup_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    return rec, info


def decode(rec: Any, samples: Any, rate: int) -> Any:
    stream = rec.create_stream()
    stream.accept_waveform(rate, samples)
    rec.decode_stream(stream)
    return stream.result


def run_offline(run_dir: Path, threads: int, round_idx: int, qos: str = "default") -> None:
    from .asr_sherpa import read_wav

    tag = f"offline-t{threads}-r{round_idx}"
    records = load_strict(MANIFEST).records
    summary: dict[str, Any] = {
        "threads": threads,
        "round": round_idx,
        "pid": os.getpid(),
        "qos": set_qos(qos),
        "started_utc": utc_now(),
    }
    rec, info = load_recognizer(threads)
    summary.update(info)
    wall0, cpu0 = time.perf_counter(), _cpu_s()
    with (run_dir / f"{tag}.jsonl").open("w", encoding="utf-8") as sink:
        for n, record in enumerate(records, start=1):
            samples, rate, audio_s = read_wav(record.audio)
            c0, t_wall, t0 = _cpu_s(), time.time(), time.perf_counter()
            res = decode(rec, samples, rate)
            ms = (time.perf_counter() - t0) * 1000.0
            row = {
                "id": record.id,
                "subset": record.metadata.get("subset"),
                "language": record.metadata.get("language"),
                "audio_s": round(audio_s, 3),
                "t_start": round(t_wall, 3),
                "decode_ms": round(ms, 2),
                "cpu_ms": round((_cpu_s() - c0) * 1000.0, 1),
                "text": res.text,
            }
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"[{tag} {n}/{len(records)}] {record.id} {ms:.0f}ms", flush=True)
    summary["decode_wall_s"] = round(time.perf_counter() - wall0, 2)
    summary["decode_cpu_s"] = round(_cpu_s() - cpu0, 2)
    summary["memory_after_decode"] = _ws()
    summary["finished_utc"] = utc_now()
    (run_dir / f"{tag}.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


# ========================================================================== preflight


def preflight() -> dict[str, Any]:
    """What the machine looked like before anything was timed."""
    from .asr_sherpa import _sha256, ensure_runtime

    ensure_runtime()
    import onnxruntime
    import sherpa_onnx

    model_dir = REPO / "models" / ARM.model_dir
    dll = Path(sherpa_onnx.__file__).parent / "lib" / "onnxruntime.dll"

    def ps(cmd: str) -> str:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", UTF8 + cmd], capture_output=True, timeout=60
        )
        return out.stdout.decode("utf-8", "replace").strip()

    return {
        "git": git_state(REPO),
        "hardware": hardware(),
        "software": {
            **software(),
            "sherpa_onnx": sherpa_onnx.__version__,
            "onnxruntime": onnxruntime.__version__,
            "ort_providers": onnxruntime.get_available_providers(),
            "sherpa_ort_dll_sha256": _sha256(dll) if dll.exists() else None,
        },
        "model_files": {f: _sha256(model_dir / f) for f in ARM.files},
        "topology": cpu_topology(),
        "power_scheme": ps("powercfg /getactivescheme"),
        "on_ac": ps("(Get-CimInstance -Namespace root/wmi BatteryStatus).PowerOnline"),
        "memory": ps(
            "$o=Get-CimInstance Win32_OperatingSystem; "
            "'total_mb={0:N0} available_mb={1:N0}' -f "
            "($o.TotalVisibleMemorySize/1KB),($o.FreePhysicalMemory/1KB)"
        ),
        "asr_processes": ps(
            "Get-Process | Where-Object { $_.ProcessName -match 'python|sherpa|onnx' } "
            "| ForEach-Object { '{0}:{1}' -f $_.Id, $_.ProcessName }"
        ).split(),
        "own_pids": [os.getpid(), os.getppid()],
        "t2d_py_sha256": _sha256(Path(__file__)),
        "affinity_priority_power_plan_changed": False,
    }


# ============================================================================== sweep


def sweep(out_root: Path, threads: Sequence[int], rounds: int, qos: str) -> Path:
    manifest = load_strict(MANIFEST)
    run_dir = out_root / run_id("t2d-parakeet-fp32-cpu")
    run_dir.mkdir(parents=True)
    run = {
        "run_id": run_dir.name,
        "task": "Phase 0 Task 2d - Parakeet FP32 CPU thread sweep and streaming gate",
        "started_utc": utc_now(),
        "preflight": preflight(),
        "manifest": {
            "path": str(MANIFEST.relative_to(REPO)).replace("\\", "/"),
            "sha256": manifest.sha256,
            "n": len(manifest.records),
        },
        "config": {
            "arm": ARM.__dict__,
            "provider": "cpu",
            "decoding_method": "greedy_search",
            "threads": list(threads),
            "rounds": rounds,
            "orders": [[t for t in ROUND_ORDERS[r % 4] if t in threads] for r in range(rounds)],
            "sample_interval_s": SAMPLE_S,
            "qos": qos,
        },
    }
    (run_dir / "run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    with Sampler(run_dir):
        time.sleep(20.0)  # an idle baseline before the first load
        for r in range(rounds):
            for t in ROUND_ORDERS[r % 4]:
                if t not in threads:
                    continue
                cmd = [sys.executable, "-m", "hermes_eval.t2d", "offline", str(run_dir)]
                subprocess.run([*cmd, str(t), str(r + 1), qos], check=True, cwd=REPO)
                time.sleep(5.0)
    return run_dir


# ========================================================================== streaming

HOP_S = 0.5  # partial cadence target: one HUD update per half second of new audio
RIGHT_CONTEXT_S = 1.0  # commit only words with at least this much audio after them
MIN_DECODE_S = 0.1
POLICIES = ("redecode", "commit")

# The gate, fixed before any streaming number existed. ARCHITECTURE §8 gives the final ASR
# pass 300 ms at p95; SYNTHESIS §19 gives the whole path 700 ms at p95. With no correction
# pass in Phase 1 (D-0009), 700 - endpoint 150 - NLP 50 - injection 50 leaves 450 ms for
# ASR finalization before IPC, which is still unmeasured. A policy is eligible only if its
# final WER is not resolved worse than the offline full-utterance decode.
GATE = {
    "metric": "release-to-final latency p95, all 160 utterances, push-to-talk release",
    "pass_ms": 300.0,
    "marginal_ms": 450.0,
    "eligibility": "final WER vs offline full decode: CI lower bound <= 0 and point <= +0.5 pp",
}


def _words(res: Any, offset: float) -> list[list[Any]]:
    """[text, start_s, end_s] per word, absolute; punctuation tokens join the word before."""
    out: list[list[Any]] = []
    for tok, ts, dur in zip(res.tokens, res.timestamps, res.durations, strict=False):
        if out and not tok.startswith(" "):
            out[-1][0] += tok
            out[-1][2] = round(offset + ts + dur, 3)
            continue
        out.append([tok.strip(), round(offset + ts, 3), round(offset + ts + dur, 3)])
    return out


def _cut_point(prev: list[Any], nxt: list[Any]) -> float:
    """Between two words, leaning toward the next word's onset; never past it."""
    mid = (prev[2] + nxt[1]) / 2.0
    return round(min(nxt[1], max(mid, nxt[1] - 0.24)), 3)


def _decode_tail(
    rec: Any, samples: Any, rate: int, seg0: float, end_s: float | None, left_s: float
) -> tuple[list[list[Any]], float]:
    """Words after the cut `seg0` in samples[:end_s], and where decoding started.

    With `left_s` > 0 (Task 2e), decoding starts up to `left_s` before the cut so the tail
    is heard with acoustic left context; words re-read from that overlap belong to the
    committed text and are dropped. A word belongs to the tail iff its timestamp midpoint
    is at or after the cut — the cut sits between two words (`_cut_point`), so this holds
    under a one-frame onset shift. With `left_s` = 0 this is Task 2d's context-free tail.
    """
    end = len(samples) if end_s is None else int(end_s * rate)
    lo = max(0.0, seg0 - left_s)
    if end - int(seg0 * rate) < MIN_DECODE_S * rate:
        return [], lo
    words = _words(decode(rec, samples[int(lo * rate) : end], rate), lo)
    if lo < seg0:
        words = [w for w in words if (w[1] + w[2]) / 2.0 >= seg0]
    return words, lo


def stream_utterance(
    rec: Any, samples: Any, rate: int, policy: str, left_s: float = 0.0
) -> dict[str, Any]:
    """Replay one utterance in real time; the push-to-talk release is the end of the audio.

    `redecode`: every partial re-decodes everything heard so far; the final re-decodes the
    whole utterance after release. `commit`: LocalAgreement-2 — a word prefix that two
    consecutive partials agree on, and that has RIGHT_CONTEXT_S of audio after it, is
    committed, and its audio is cut at the word boundary sherpa's timestamps give; later
    partials and the final decode only the uncommitted tail — re-reading `left_s` of
    committed audio before it (Task 2e; 0 in Task 2d), see `_decode_tail`.
    """
    duration = len(samples) / rate
    committed: list[list[Any]] = []
    seg0 = 0.0
    prev: list[str] | None = None
    partials: list[dict[str, Any]] = []
    t0 = time.perf_counter()

    def el() -> float:
        return time.perf_counter() - t0

    next_due = HOP_S
    while True:
        now = el()
        if now >= duration:
            break
        if now < next_due:
            time.sleep(min(next_due, duration) - now)
            continue
        avail = now
        start = el()
        hyp, lo = _decode_tail(rec, samples, rate, seg0, avail, left_s)
        end = el()
        n_commit = 0
        if policy == "commit" and prev is not None:
            agreed = 0
            while agreed < min(len(prev), len(hyp)) and prev[agreed] == hyp[agreed][0]:
                agreed += 1
            for i in range(agreed):
                if i + 1 < len(hyp) and hyp[i][2] <= avail - RIGHT_CONTEXT_S:
                    n_commit = i + 1
        shown = committed + hyp
        partials.append(
            {
                "audio_s": round(avail, 3),
                "start_s": round(start, 3),
                "ms": round((end - start) * 1000.0, 1),
                "emit_s": round(end, 3),
                "seg0": seg0,
                "lo": lo,
                "words": [[w[0], w[2]] for w in shown],
                "committed": len(committed) + n_commit,
            }
        )
        if n_commit:
            seg0 = _cut_point(hyp[n_commit - 1], hyp[n_commit])
            committed += hyp[:n_commit]
            hyp = hyp[n_commit:]
        prev = [w[0] for w in hyp]
        next_due = avail + HOP_S

    final_start = el()
    if policy == "redecode":
        seg0, committed = 0.0, []
    tail_words, lo = _decode_tail(rec, samples, rate, seg0, None, left_s)
    final_end = el()
    words = committed + tail_words
    return {
        "audio_s": round(duration, 3),
        "partials": partials,
        "final": {
            "text": " ".join(w[0] for w in words),
            "words": words,
            "inflight_wait_ms": round((final_start - duration) * 1000.0, 1),
            "compute_ms": round((final_end - final_start) * 1000.0, 1),
            "latency_ms": round((final_end - duration) * 1000.0, 1),
            "tail_s": round(duration - seg0, 3),
            "decoded_s": round(duration - lo, 3),
        },
    }


def _read_appended(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Rows of an append-only JSONL file, and the length of a torn final line, if any.

    A record is written as one line plus its newline, so after a power loss only the last
    line can be unterminated. Every terminated line must parse — a malformed one is an
    error, never silently dropped. Reads only; `_cut_torn` removes the fragment.
    """
    if not path.exists():
        return [], 0
    raw = path.read_bytes()
    keep = raw.rfind(b"\n") + 1
    rows: list[dict[str, Any]] = []
    for n, line in enumerate(raw[:keep].split(b"\n")[:-1], start=1):
        try:
            row = json.loads(line)
        except ValueError as e:
            raise ValueError(f"{path.name}:{n}: malformed record; refusing to resume") from e
        if not isinstance(row, dict):
            raise ValueError(f"{path.name}:{n}: record is not an object; refusing to resume")
        rows.append(row)
    return rows, len(raw) - keep


def _cut_torn(path: Path, torn: int) -> None:
    if torn:
        with path.open("r+b") as f:
            f.truncate(path.stat().st_size - torn)
            f.flush()
            os.fsync(f.fileno())


def _stream_done(path: Path, ids: Sequence[str]) -> tuple[set[str], int]:
    """Utterance ids already streamed into `path`, and the torn bytes at its end."""
    rows, torn = _read_appended(path)
    known, done = set(ids), set()
    for n, row in enumerate(rows, start=1):
        rid = row.get("id")
        if rid not in known:
            raise ValueError(f"{path.name}:{n}: id {rid!r} is not in the manifest")
        if rid in done:
            raise ValueError(f"{path.name}:{n}: duplicate id {rid!r}; refusing to resume")
        done.add(rid)
    return done, torn


def _stream_complete(run_dir: Path, tag: str, ids: Sequence[str]) -> bool:
    """A policy is complete when its summary exists and every manifest id has a row."""
    done, _ = _stream_done(run_dir / f"{tag}.jsonl", ids)
    if not (run_dir / f"{tag}.json").exists():
        return False
    if len(done) != len(ids):
        raise ValueError(f"{tag}.json exists but only {len(done)}/{len(ids)} rows do")
    return True


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _record_session(run_dir: Path, session: dict[str, Any]) -> list[dict[str, Any]]:
    """Append one streaming session to run.json; return this tag's sessions so far.

    A policy's rows may span sessions only if they all ran the same t2d.py and QoS.
    """
    run_path = run_dir / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    sessions = run.setdefault("stream_sessions", [])
    mine = [s for s in sessions if s["tag"] == session["tag"]]
    for key in ("t2d_py_sha256", "qos"):
        if mine and mine[0][key] != session[key]:
            raise ValueError(
                f"{session['tag']}: {key} {session[key]!r} differs from the earlier session's "
                f"{mine[0][key]!r}; refusing to mix them in one result"
            )
    sessions.append(session)
    _write_atomic(run_path, json.dumps(run, indent=2) + "\n")
    return [*mine, session]


def run_stream(
    run_dir: Path,
    threads: int,
    policy: str,
    qos: str = "default",
    *,
    left_s: float = 0.0,
    only: Sequence[str] | None = None,
    tag: str | None = None,
) -> None:
    """Stream every manifest utterance not already in this policy's JSONL, appending.

    Resume-safe: each row is flushed and fsynced as it completes, completed ids are
    skipped, and each session is recorded in run.json (`stream_sessions`). The summary's
    load, QoS and memory fields describe the last session. Task 2e passes `left_s`, a
    subset of ids (`only`, kept in manifest order) and its own `tag`.
    """
    from .asr_sherpa import _sha256, read_wav

    tag = tag or f"stream-{policy}-t{threads}"
    path = run_dir / f"{tag}.jsonl"
    records = load_strict(MANIFEST).records
    if only is not None:
        keep = set(only)
        records = [r for r in records if r.id in keep]
        if len(records) != len(keep):
            raise ValueError(f"{tag}: {len(keep) - len(records)} requested ids not in manifest")
    ids = [r.id for r in records]
    if _stream_complete(run_dir, tag, ids):
        print(f"[{tag}] complete, skipping", flush=True)
        return
    done, torn = _stream_done(path, ids)  # validates everything before anything is changed
    sessions = _record_session(
        run_dir,
        {
            "tag": tag,
            "policy": policy,
            "left_s": left_s,
            "threads": threads,
            "qos": qos,
            "started_utc": utc_now(),
            "rows_present": len(done),
            "torn_bytes_dropped": torn,
            "git": git_state(REPO),
            "t2d_py_sha256": _sha256(Path(__file__)),
        },
    )
    _cut_torn(path, torn)  # the torn utterance is not in `done`, so it is redone
    summary: dict[str, Any] = {
        "threads": threads,
        "policy": policy,
        "hop_s": HOP_S,
        "right_context_s": RIGHT_CONTEXT_S,
        "left_s": left_s,
        "n_ids": len(ids),
        "gate": GATE,
        "pid": os.getpid(),
        "qos": set_qos(qos),
        "started_utc": utc_now(),
    }
    rec, info = load_recognizer(threads)
    summary.update(info)
    with path.open("a", encoding="utf-8") as sink:
        for n, record in enumerate(records, start=1):
            if record.id in done:
                continue
            samples, rate, _ = read_wav(record.audio)
            t_wall = time.time()
            out = stream_utterance(rec, samples, rate, policy, left_s)
            row = {
                "id": record.id,
                "subset": record.metadata.get("subset"),
                "language": record.metadata.get("language"),
                "t_start": round(t_wall, 3),
                **out,
            }
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            sink.flush()
            os.fsync(sink.fileno())
            f = out["final"]
            print(
                f"[{tag} {n}/{len(records)}] {record.id} {len(out['partials'])} partials, "
                f"final {f['latency_ms']:.0f}ms (wait {f['inflight_wait_ms']:.0f})",
                flush=True,
            )
    summary["memory_after_decode"] = _ws()
    summary["finished_utc"] = utc_now()
    summary["sessions"] = sessions
    _write_atomic(run_dir / f"{tag}.json", json.dumps(summary, indent=2) + "\n")


def stream(run_dir: Path, threads: int, policies: Sequence[str], qos: str) -> None:
    """Run each policy in its own worker; a policy that already completed is not rerun."""
    ids = [r.id for r in load_strict(MANIFEST).records]
    todo = [p for p in policies if not _stream_complete(run_dir, f"stream-{p}-t{threads}", ids)]
    for p in policies:
        if p not in todo:
            print(f"[stream-{p}-t{threads}] complete, skipping", flush=True)
    if not todo:
        return
    with Sampler(run_dir, f"counters-stream-t{threads}"):
        time.sleep(10.0)
        for policy in todo:
            cmd = [sys.executable, "-m", "hermes_eval.t2d", "stream-worker", str(run_dir)]
            subprocess.run([*cmd, str(threads), policy, qos], check=True, cwd=REPO)
            time.sleep(5.0)


# ============================================================================ analyze


def _q(xs: Sequence[float], q: float) -> float | None:
    v = percentile(list(xs), q)
    return None if v is None else round(v, 1)


def _counters(run_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(run_dir.glob("counters*.jsonl")):
        rows += _jsonl(path)
    return sorted(rows, key=lambda r: r["t"])


def _window(counters: list[dict[str, Any]], times: list[float], s: float, e: float):
    """Counter samples covering [s, e]; a sample stamped t covers (t - SAMPLE_S, t]."""
    lo = bisect.bisect_right(times, s)
    hi = bisect.bisect_right(times, e + SAMPLE_S)
    return counters[lo : max(hi, lo + 1)]


def _topology(run_dir: Path) -> tuple[list[int], list[int]]:
    """P and E logical processors as recorded at pre-flight.

    The interrupted first run recorded them as `p_cores_smt_logical` / `e_cores_logical`.
    """
    top = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["preflight"]["topology"]
    p = top.get("p_logical", top.get("p_cores_smt_logical"))
    e = top.get("e_logical", top.get("e_cores_logical"))
    return list(p), list(e)


def _system(
    win: list[dict[str, Any]], p: Sequence[int], e: Sequence[int]
) -> dict[str, float | None]:
    def mean(key: str, idx: Sequence[int]) -> float | None:
        vals = [r[key][i] for r in win for i in idx if r.get(key) and r[key][i] is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    return {
        "p_busy": mean("busy", p),
        "e_busy": mean("busy", e),
        "p_perf": mean("perf", p),
        "e_perf": mean("perf", e),
        "page_in": round(sum((r.get("page_in") or 0.0) * SAMPLE_S for r in win), 0),
        "avail_mb_min": min((r["avail_mb"] for r in win if r.get("avail_mb")), default=None),
    }


def _fit(rows: Sequence[dict[str, Any]]) -> dict[str, float]:
    """decode_ms = a + b * audio_s, least squares."""
    xs = [r["audio_s"] for r in rows]
    ys = [r["decode_ms"] for r in rows]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sum(
        (x - mx) ** 2 for x in xs
    )
    a = my - b * mx
    return {"a_ms": round(a, 1), "b_ms_per_s": round(b, 1), "pred_5s_ms": round(a + 5 * b, 1)}


def analyze_sweep(run_dir: Path, refs: dict[str, str]) -> dict[str, Any]:
    counters = _counters(run_dir)
    p_logical, e_logical = _topology(run_dir)
    times = [r["t"] for r in counters]
    runs: dict[int, dict[int, tuple[dict[str, Any], list[dict[str, Any]]]]] = {}
    for path in sorted(run_dir.glob("offline-t*-r*.json")):
        meta = json.loads(path.read_text(encoding="utf-8"))
        rows = _jsonl(path.with_suffix(".jsonl"))
        for row in rows:
            win = _window(counters, times, row["t_start"], row["t_start"] + row["decode_ms"] / 1e3)
            row["sys"] = _system(win, p_logical, e_logical)
        runs.setdefault(meta["threads"], {})[meta["round"]] = (meta, rows)

    out: dict[str, Any] = {}
    flagged_all: list[dict[str, Any]] = []
    normal_all: list[dict[str, Any]] = []
    for t, reps in sorted(runs.items()):
        per_id: dict[str, list[float]] = {}
        for _, rows in reps.values():
            for row in rows:
                per_id.setdefault(row["id"], []).append(row["decode_ms"])
        med = {k: sorted(v)[len(v) // 2] for k, v in per_id.items()}
        reps_out = {}
        pooled: list[dict[str, Any]] = []
        for r, (meta, rows) in sorted(reps.items()):
            audio = sum(x["audio_s"] for x in rows)
            ms = [x["decode_ms"] for x in rows]
            for x in rows:
                x["ratio"] = x["decode_ms"] / med[x["id"]]
                (flagged_all if not 0.67 <= x["ratio"] <= 1.5 else normal_all).append(
                    {"threads": t, "round": r, **x}
                )
            reps_out[r] = {
                "rtf": round(sum(ms) / 1000.0 / audio, 4),
                "p50_ms": _q(ms, 0.5),
                "p95_ms": _q(ms, 0.95),
                "cores_busy": round(meta["decode_cpu_s"] / meta["decode_wall_s"], 2),
                "peak_ws_mb": meta["memory_after_decode"]["peak_working_set_mb"],
                "load_ms": meta["load_ms"],
                "fast_rows": sum(1 for x in rows if x["ratio"] < 0.67),
                "slow_rows": sum(1 for x in rows if x["ratio"] > 1.5),
                "wer": _rate([_counts(refs[x["id"]], x["text"]) for x in rows]),
            }
            pooled += rows
        rtfs = [v["rtf"] for v in reps_out.values()]
        mean_rtf = sum(rtfs) / len(rtfs)
        sd = (sum((x - mean_rtf) ** 2 for x in rtfs) / max(1, len(rtfs) - 1)) ** 0.5
        ms = [x["decode_ms"] for x in pooled]
        texts = {r: [x["text"] for x in rows] for r, (_, rows) in reps.items()}
        first = next(iter(texts.values()))
        out[str(t)] = {
            "reps": reps_out,
            "rtf_mean": round(mean_rtf, 4),
            "rtf_cv_pct": round(100.0 * sd / mean_rtf, 1),
            "rtf_range": [min(rtfs), max(rtfs)],
            "pooled_p50_ms": _q(ms, 0.5),
            "pooled_p95_ms": _q(ms, 0.95),
            "pooled_p99_ms": _q(ms, 0.99),
            "median_ms_le_3s": _q([x["decode_ms"] for x in pooled if x["audio_s"] <= 3.0], 0.5),
            "p95_ms_4to6s": _q([x["decode_ms"] for x in pooled if 4 <= x["audio_s"] <= 6], 0.95),
            "fit": _fit(pooled),
            "texts_identical_across_rounds": all(v == first for v in texts.values()),
            "texts": first,
        }
    ids = [x["id"] for x in next(iter(next(iter(runs.values())).values()))[1]]
    t_keys = list(out)
    base = out[t_keys[0]]["texts"]
    for k in t_keys:
        out[k]["texts_identical_to_t" + t_keys[0]] = sum(
            a == b for a, b in zip(out[k].pop("texts"), base, strict=True)
        )

    def profile(rows: list[dict[str, Any]]) -> dict[str, Any]:
        keys = ("p_busy", "e_busy", "p_perf", "e_perf", "page_in")
        return {
            "n": len(rows),
            **{k: _q([x["sys"][k] for x in rows if x["sys"][k] is not None], 0.5) for k in keys},
        }

    fast = [x for x in flagged_all if x["ratio"] < 0.67]
    slow = [x for x in flagged_all if x["ratio"] > 1.5]
    return {
        "configs": out,
        "n_ids": len(ids),
        "regime": {
            "definition": "row decode_ms / median over rounds of same id and threads",
            "fast_lt_0.67": profile(fast),
            "slow_gt_1.5": profile(slow),
            "normal": profile(normal_all),
            "slow_rows": [
                {k: x[k] for k in ("threads", "round", "id", "decode_ms", "ratio", "sys")}
                for x in sorted(slow, key=lambda x: -x["ratio"])[:20]
            ],
        },
    }


def _norm_words(words: Sequence[Sequence[Any]]) -> list[tuple[str, float]]:
    out = []
    for w in words:
        for tok in tokenize(str(w[0]), "basic"):
            out.append((tok, float(w[-1])))
    return out


def _lcp(a: Sequence[str], b: Sequence[str]) -> int:
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return n


def _stream_utt(row: dict[str, Any]) -> dict[str, Any]:
    fin = row["final"]
    fn = _norm_words([[w[0], w[2]] for w in fin["words"]])
    ftext = [w for w, _ in fn]
    seqs = [[w for w, _ in _norm_words(p["words"])] for p in row["partials"]]
    raws = [[str(w[0]) for w in p["words"]] for p in row["partials"]]
    final_emit = row["audio_s"] + fin["latency_ms"] / 1000.0
    out: dict[str, Any] = {"n_partials": len(seqs), "n_final_words": len(ftext)}
    out["empty_partials"] = sum(1 for s in seqs if not s)
    nonempty = [p for p, s in zip(row["partials"], seqs, strict=True) if s]
    out["ttfp_s"] = nonempty[0]["emit_s"] if nonempty else None
    useful = [
        p for p, s in zip(row["partials"], seqs, strict=True) if s and ftext and s[0] == ftext[0]
    ]
    out["ttfup_s"] = useful[0]["emit_s"] if useful else None
    onset = fin["words"][0][1] if fin["words"] else None
    out["ttfup_from_onset_s"] = (
        round(out["ttfup_s"] - onset, 3) if useful and onset is not None else None
    )
    chain = [*seqs, ftext]
    out["unstable_norm"] = sum(len(a) - _lcp(a, b) for a, b in pairwise(chain))
    rchain = [*raws, [str(w[0]) for w in fin["words"]]]
    out["unstable_raw"] = sum(len(a) - _lcp(a, b) for a, b in pairwise(rchain))
    out["revising_partials"] = sum(
        1 for a, b in zip(seqs, chain[1:], strict=True) if len(a) > _lcp(a, b)
    )
    lags = []
    for j, (_, end) in enumerate(fn):
        shown = final_emit
        for k in range(len(seqs) - 1, -1, -1):
            if _lcp(seqs[k], ftext) > j:
                shown = row["partials"][k]["emit_s"]
            else:
                break
        lags.append(round(shown - end, 3))
    out["word_lag_s"] = lags
    emits = [p["emit_s"] for p in row["partials"]]
    out["cadence_s"] = [round(b - a, 3) for a, b in pairwise(emits)]
    out["partial_ms"] = [p["ms"] for p in row["partials"]]
    out["partial_audio_s"] = [p["audio_s"] - p["seg0"] for p in row["partials"]]
    return out


def _flat(per: Sequence[dict[str, Any]], key: str) -> list[float]:
    return [x for p in per for x in p[key]]


def analyze_stream(run_dir: Path, refs: dict[str, str], offline: dict[str, dict[str, str]]):
    out: dict[str, Any] = {}
    for path in sorted(run_dir.glob("stream-*-t*.json")):
        meta = json.loads(path.read_text(encoding="utf-8"))
        rows = _jsonl(path.with_suffix(".jsonl"))
        t = str(meta["threads"])
        per = [_stream_utt(r) for r in rows]
        fin = [r["final"] for r in rows]
        lat = [f["latency_ms"] for f in fin]

        def bucket(lo: float, hi: float, rows: Any = rows, lat: Any = lat) -> dict[str, Any]:
            v = [x for r, x in zip(rows, lat, strict=True) if lo < r["audio_s"] <= hi]
            return {"n": len(v), "p50_ms": _q(v, 0.5), "p95_ms": _q(v, 0.95)}

        base = offline[t]
        a = [_counts(refs[r["id"]], base[r["id"]]) for r in rows]
        b = [_counts(refs[r["id"]], r["final"]["text"]) for r in rows]
        boot = paired_bootstrap(a, b, metric="wer", resamples=RESAMPLES, seed=SEED)
        n_final_words = sum(p["n_final_words"] for p in per)
        res = {
            "threads": meta["threads"],
            "load_ms": meta["load_ms"],
            "peak_ws_mb": meta["memory_after_decode"]["peak_working_set_mb"],
            "final": {
                "latency_p50_ms": _q(lat, 0.5),
                "latency_p95_ms": _q(lat, 0.95),
                "latency_p99_ms": _q(lat, 0.99),
                "latency_max_ms": max(lat),
                "inflight_wait_p50_ms": _q([f["inflight_wait_ms"] for f in fin], 0.5),
                "inflight_wait_p95_ms": _q([f["inflight_wait_ms"] for f in fin], 0.95),
                "compute_p50_ms": _q([f["compute_ms"] for f in fin], 0.5),
                "compute_p95_ms": _q([f["compute_ms"] for f in fin], 0.95),
                "tail_s_p50": _q([f["tail_s"] for f in fin], 0.5),
                "tail_s_p95": _q([f["tail_s"] for f in fin], 0.95),
                "by_duration": {
                    "le3s": bucket(0, 3),
                    "3to6s": bucket(3, 6),
                    "6to10s": bucket(6, 10),
                    "gt10s": bucket(10, 99),
                },
                "empty_finals": sum(1 for f in fin if not f["text"].strip()),
            },
            "partials": {
                "n": sum(p["n_partials"] for p in per),
                "empty_while_final_nonempty": sum(
                    p["empty_partials"] for p in per if p["n_final_words"]
                ),
                "ttfp_p50_s": _q([p["ttfp_s"] for p in per if p["ttfp_s"] is not None], 0.5),
                "ttfp_p95_s": _q([p["ttfp_s"] for p in per if p["ttfp_s"] is not None], 0.95),
                "ttfup_p50_s": _q([p["ttfup_s"] for p in per if p["ttfup_s"] is not None], 0.5),
                "ttfup_p95_s": _q([p["ttfup_s"] for p in per if p["ttfup_s"] is not None], 0.95),
                "ttfup_from_onset_p50_s": _q(
                    [p["ttfup_from_onset_s"] for p in per if p["ttfup_from_onset_s"] is not None],
                    0.5,
                ),
                "ttfup_from_onset_p95_s": _q(
                    [p["ttfup_from_onset_s"] for p in per if p["ttfup_from_onset_s"] is not None],
                    0.95,
                ),
                "no_useful_partial": sum(1 for p in per if p["ttfup_s"] is None),
                "cadence_p50_s": _q(_flat(per, "cadence_s"), 0.5),
                "cadence_p95_s": _q(_flat(per, "cadence_s"), 0.95),
                "compute_p50_ms": _q(_flat(per, "partial_ms"), 0.5),
                "compute_p95_ms": _q(_flat(per, "partial_ms"), 0.95),
                "decoded_audio_p95_s": _q(_flat(per, "partial_audio_s"), 0.95),
                "upwr_norm": round(sum(p["unstable_norm"] for p in per) / n_final_words, 3),
                "upwr_raw": round(sum(p["unstable_raw"] for p in per) / n_final_words, 3),
                "revising_partials": sum(p["revising_partials"] for p in per),
                "word_lag_p50_s": _q(_flat(per, "word_lag_s"), 0.5),
                "word_lag_p95_s": _q(_flat(per, "word_lag_s"), 0.95),
            },
            "quality": {
                "wer_offline": round(boot.rate_a * 100, 3),
                "wer_final": round(boot.rate_b * 100, 3),
                "delta_pp": boot.delta_pp,
                "ci_pp": [boot.ci_low_pp, boot.ci_high_pp],
                "raw_identical_to_offline": sum(
                    " ".join(r["final"]["text"].split()) == " ".join(base[r["id"]].split())
                    for r in rows
                ),
            },
        }
        q = res["quality"]
        res["eligible"] = q["ci_pp"][0] <= 0 and q["delta_pp"] <= 0.5
        p95 = res["final"]["latency_p95_ms"]
        res["gate"] = (
            "PASS"
            if p95 <= GATE["pass_ms"]
            else "MARGINAL"
            if p95 <= GATE["marginal_ms"]
            else "FAIL"
        )
        out[f"{meta['policy']}-t{t}"] = res
    return out


def analyze(run_dir: Path) -> dict[str, Any]:
    refs = {r.id: r.reference for r in load_strict(MANIFEST).records}
    sweep_out = analyze_sweep(run_dir, refs)
    offline: dict[str, dict[str, str]] = {}
    for path in sorted(run_dir.glob("offline-t*-r1.jsonl")):
        t = path.stem.split("-")[1][1:]
        offline[t] = {x["id"]: x["text"] for x in _jsonl(path)}
    result = {
        "generated_utc": utc_now(),
        "gate": GATE,
        "sweep": sweep_out,
        "stream": analyze_stream(run_dir, refs, offline),
    }
    (run_dir / "analysis.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


# =============================================================================== main


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m hermes_eval.t2d")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sweep")
    s.add_argument("--out", type=Path, default=REPO / "eval" / "runs")
    s.add_argument("--threads", default=",".join(map(str, THREADS)))
    s.add_argument("--rounds", type=int, default=3)
    s.add_argument("--qos", choices=QOS, default="high")
    s = sub.add_parser("offline")
    s.add_argument("run_dir", type=Path)
    s.add_argument("threads", type=int)
    s.add_argument("round", type=int)
    s.add_argument("qos", choices=QOS)
    s = sub.add_parser("stream")
    s.add_argument("run_dir", type=Path)
    s.add_argument("--threads", type=int, required=True)
    s.add_argument("--policies", default=",".join(POLICIES))
    s.add_argument("--qos", choices=QOS, default="high")
    s = sub.add_parser("stream-worker")
    s.add_argument("run_dir", type=Path)
    s.add_argument("threads", type=int)
    s.add_argument("policy", choices=POLICIES)
    s.add_argument("qos", choices=QOS)
    s = sub.add_parser("analyze")
    s.add_argument("run_dir", type=Path)
    s = sub.add_parser("sample")
    s.add_argument("out", type=Path)
    s.add_argument("stop", type=Path)
    a = p.parse_args(argv)
    if a.cmd == "sweep":
        print(sweep(a.out, [int(x) for x in a.threads.split(",")], a.rounds, a.qos))
    elif a.cmd == "offline":
        run_offline(a.run_dir, a.threads, a.round, a.qos)
    elif a.cmd == "stream":
        stream(a.run_dir, a.threads, a.policies.split(","), a.qos)
    elif a.cmd == "stream-worker":
        run_stream(a.run_dir, a.threads, a.policy, a.qos)
    elif a.cmd == "analyze":
        print(json.dumps(analyze(a.run_dir)["sweep"]["configs"], indent=2))
    elif a.cmd == "sample":
        _pdh_sampler(a.out, a.stop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
