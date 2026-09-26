"""The RUN record: everything needed to reproduce a run, or to distrust it.

R6 is specific about this. A number without its git SHA, model hash, quantization,
decoding parameters, thread count and hardware is not a measurement, it is an anecdote —
and the anecdotes are exactly what the whole H200-RTFx problem is made of.

Collection is best-effort and never fails a run: anything we cannot determine is
recorded as null and listed in `missing`, so the gap is visible in the report instead of
being invisible in the number.
"""

from __future__ import annotations

import ctypes
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from . import HARNESS_VERSION


def _run(cmd: list[str], timeout: float = 5.0) -> str | None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    out = proc.stdout.strip()
    return out if proc.returncode == 0 and out else None


def git_state(repo: Path) -> dict[str, object]:
    sha = _run(["git", "-C", str(repo), "rev-parse", "HEAD"])
    status = _run(["git", "-C", str(repo), "status", "--porcelain"])
    return {
        "sha": sha,
        # `git status --porcelain` returns empty output when clean, which _run maps to
        # None; that is indistinguishable from failure, so check sha too.
        "dirty": None if sha is None else bool(status),
    }


def _total_ram_gb() -> float | None:
    if sys.platform != "win32":
        return None

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    try:
        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
            return None
        return round(status.ullTotalPhys / (1024**3), 2)
    except Exception:
        return None


def hardware() -> dict[str, object]:
    gpu = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total",
            "--format=csv,noheader",
        ]
    )
    return {
        "platform": platform.platform(),
        "os_version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "logical_cores": os.cpu_count(),
        "total_ram_gb": _total_ram_gb(),
        "gpu": gpu,
    }


def software() -> dict[str, object]:
    return {
        "harness_version": HARNESS_VERSION,
        "python": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        # Thread count is a first-class decoding parameter on this hardware (P/E split),
        # so it belongs in provenance even when no model is loaded.
        "omp_num_threads": os.environ.get("OMP_NUM_THREADS"),
    }


def run_id(prefix: str) -> str:
    """Sortable, readable, and unique even for two runs of the same adapter in one
    second — which is exactly what happens when the suite is driven from a script."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in prefix)
    return f"{stamp}-{safe}-{time.time_ns() % 0x10000:04x}"


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
