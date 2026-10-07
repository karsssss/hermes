# Task 2d partial run: diagnostic only, NOT a result

Interrupted 2026-10-06. Claude Code's memory-pressure reaper killed the sweep while the
12-thread worker was loading. Completed: default QoS (power throttling left to Windows), round 1,
4/6/8 threads, 160/160 rows each. Never started: 12 threads, rounds 2-3, every `--qos high`
worker, and all streaming runs.

Do not quote these latencies as Parakeet FP32 CPU performance. Two contaminations are on
record in `counters.jsonl`:

1. The worker ran on the 4 E-cores only (logical 8-11 at 100% busy, P-cores at background
   load) at every thread count.
2. Severe paging: available memory fell to ~520 MB, and each pass paged in ~1.9-3.8 GB.

Kept because it is the evidence for both findings. WER, 10.721% at every thread count, is
unaffected and matches Task 2c FP32 exactly. See docs/CURRENT.md, section "Task 2d -
INTERRUPTED".

The offline rows were collected by `t2d.py` at 4e403e5 plus the then-uncommitted file
(sha256 in `run.json` preflight). The committed `t2d.py` adds a `qos` argument and the
streaming and analysis code; the offline worker and the sampler are otherwise unchanged.
