"""Peak memory and GPU sampling for a run. Stdlib only, best-effort, never fatal.

`docs/CURRENT.md` deferred this until the first real model, with the cold-vs-warm-start
discipline attached. This is that.

Two things are worth measuring and one is worth refusing to measure:

- **Process peak working set and peak commit**, read from the OS's own counters for
  *this* process. Per-process is the only honest choice on a developer laptop: system
  free memory says more about how many browser tabs are open than about the model.
- **GPU memory**, polled from `nvidia-smi` for this PID. Reported as null rather than
  zero when no GPU work happened, because "the model used 0 MB of VRAM" and "we could
  not see whether it did" are different claims.
- **Not** system-wide free RAM. It is not attributable and it is not reproducible.

Sampling runs on a daemon thread at a fixed interval. It costs a syscall per tick and is
off by default, because a scoring run that shells out to nvidia-smi 5000 times is a
scoring run whose latency numbers are its own fault.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Any

SAMPLE_INTERVAL_S = 0.25


class _ProcessMemoryCountersEx(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


def process_memory() -> dict[str, float | None]:
    """Working set and commit for this process, in MB. Windows-only; null elsewhere."""
    if sys.platform != "win32":
        return {"working_set_mb": None, "peak_working_set_mb": None, "private_mb": None}
    try:
        # argtypes/restype are not optional here. ctypes defaults a return value to C int,
        # so GetCurrentProcess()'s 64-bit pseudo-handle (0xFFFF...FFFF) comes back as -1 and
        # is then re-widened wrongly, and GetProcessMemoryInfo silently returns 0. Declaring
        # the signatures is the difference between a real number and a null.
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        psapi = ctypes.windll.psapi  # type: ignore[attr-defined]
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetCurrentProcess.argtypes = []
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ProcessMemoryCountersEx),
            wintypes.DWORD,
        ]

        counters = _ProcessMemoryCountersEx()
        counters.cb = ctypes.sizeof(_ProcessMemoryCountersEx)
        ok = psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        )
        if not ok:
            return {"working_set_mb": None, "peak_working_set_mb": None, "private_mb": None}
        mb = 1024.0 * 1024.0
        return {
            "working_set_mb": round(counters.WorkingSetSize / mb, 1),
            "peak_working_set_mb": round(counters.PeakWorkingSetSize / mb, 1),
            "private_mb": round(counters.PrivateUsage / mb, 1),
        }
    except Exception:
        return {"working_set_mb": None, "peak_working_set_mb": None, "private_mb": None}


def gpu_memory_mb(pid: int | None = None) -> float | None:
    """VRAM attributed to this process, in MB, or None when it cannot be determined.

    None is not zero. A model running entirely on the CPU EP and a machine where
    nvidia-smi is missing both produce no reading, and conflating them would let a
    CPU-only result masquerade as a measured VRAM figure.
    """
    pid = os.getpid() if pid is None else pid
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,used_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2 and parts[0].isdigit() and int(parts[0]) == pid:
            try:
                return float(parts[1])
            except ValueError:
                return None
    return None


@dataclass
class ResourceSampler:
    """Polls this process' memory (and GPU memory) on a daemon thread until stopped."""

    interval_s: float = SAMPLE_INTERVAL_S
    poll_gpu: bool = True
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    _peak_ws_mb: float = 0.0
    _peak_private_mb: float = 0.0
    _peak_gpu_mb: float | None = None
    _samples: int = 0

    def _tick(self) -> None:
        mem = process_memory()
        ws = mem.get("peak_working_set_mb")
        if isinstance(ws, float):
            self._peak_ws_mb = max(self._peak_ws_mb, ws)
        private = mem.get("private_mb")
        if isinstance(private, float):
            self._peak_private_mb = max(self._peak_private_mb, private)
        if self.poll_gpu:
            gpu = gpu_memory_mb()
            if gpu is not None:
                self._peak_gpu_mb = (
                    gpu if self._peak_gpu_mb is None else max(self._peak_gpu_mb, gpu)
                )
        self._samples += 1

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._tick()
            self._stop.wait(self.interval_s)

    def start(self) -> ResourceSampler:
        self._tick()
        self._thread = threading.Thread(target=self._loop, name="hermes-resources", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._tick()
        return self.summary()

    def summary(self) -> dict[str, Any]:
        return {
            "peak_working_set_mb": round(self._peak_ws_mb, 1) or None,
            "peak_private_mb": round(self._peak_private_mb, 1) or None,
            "peak_gpu_mb": self._peak_gpu_mb,
            "samples": self._samples,
            "interval_s": self.interval_s,
            "note": (
                "per-process counters; peak_gpu_mb is null when no GPU allocation was "
                "attributable to this PID, which is not the same as zero"
            ),
        }
