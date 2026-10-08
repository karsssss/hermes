# T2D — Parakeet FP32 on the CPU EP: thread sweep and streaming latency gate

Status: **complete**, 2026-10-08. Phase 0, Task 2d. **Verdict: CPU FP32 STREAMING: FAIL** (§5).
Decision record: **D-0016**.

**The question.** Is Parakeet TDT 0.6B v3 FP32 (D-0015), on the ONNX Runtime CPU EP, fit for
the Phase 1 interactive path? That is: what thread configuration, what streaming behaviour,
and does push-to-talk release-to-final latency meet a gate fixed before any streaming number
existed?

**Scope.** One model, one representation, one execution provider. Held fixed throughout:
Parakeet TDT 0.6B v3 FP32 sherpa-onnx export (encoder `3eed7ce4…`, = Task 2c), sherpa-onnx
1.13.8 `greedy_search`, ORT 1.28.0 CPU EP (DLL `14e18662…`), Public Proxy v1 (n=160, manifest
`2b3a46ed…`), `basic`-normalized WER. **WER, not F-WER.** The proxy set has no formatted
reference. No GPU EP, no other model, no change to affinity, priority or power plan.

**Run.** `eval/runs/20261007T040840Z-t2d-parakeet-fp32-cpu-190c`, where the offline baseline
and both streaming policies share one directory and one pre-flight record.

```
uv run --group asr python -m hermes_eval.t2d sweep --threads 4 --rounds 3 --qos high
uv run --group asr python -m hermes_eval.t2d stream <run-dir> --threads 4 --qos high
uv run python -m hermes_eval.t2d analyze <run-dir>
```

## 1. Method

**Sampler.** Task 2c saw absolute decode times swing ~5× between stretches of one run. So every
timed process here runs beside a PDH sampler process, polling every 0.5 s. It records busy % and
performance % per logical processor (the P/E split comes from
`GetLogicalProcessorInformationEx`: P = logical 0–7, E = 8–11), hard page-ins, and available
memory. Each decode row carries its wall-clock window, so any outlier can be attributed to core
placement, frequency or paging.

**QoS.** `--qos high` opts the worker process out of execution-speed power throttling
(`PROCESS_POWER_THROTTLING_EXECUTION_SPEED`, state 0) and reads the state back. It changes no
priority, affinity or power-plan setting.

**Offline sweep (Part A).** Each round runs in a fresh worker process. The worker does a timed
load, warms up twice on Task 2a's synthetic signal, then decodes all 160 rows in manifest order.

**Streaming (Part B).** The export is not cache-aware, so streaming means replaying each
utterance in real time against the offline model. Every 0.5 s of new audio a partial
re-decodes, and push-to-talk release coincides with the end of the audio. Two finalization
policies:

- **`redecode`.** Each partial decodes everything heard so far. At release the final decodes
  the whole utterance.
- **`commit` (LocalAgreement-2).** A word prefix is committed when two consecutive partials
  agree on it and it has 1.0 s of audio after it. The committed audio is cut at the word
  boundary taken from sherpa's timestamps. Later partials, and the final, decode only the
  uncommitted tail.

Release-to-final latency is measured from the end of the audio to the final transcript. It
includes any wait for a partial already decoding when release happens.

**Gate (Part C), pre-registered in `t2d.GATE`.**

- **PASS:** p95 ≤ 300 ms, the ARCHITECTURE §8 final-ASR budget.
- **MARGINAL:** p95 ≤ 450 ms. That is 700 ms end-to-end minus 150 ms endpointing, 50 ms NLP and
  50 ms injection, with no correction pass (D-0009).
- **FAIL:** anything above 450 ms.
- **Eligibility:** a policy counts only if its final WER is not resolved worse than the offline
  full decode (paired-bootstrap CI lower bound ≤ 0 and point Δ ≤ +0.5 pp; 2000 resamples,
  seed 20260926).

## 2. History: one interrupted attempt and two contaminations (2026-10-06)

The first attempt (`20261006T194724Z-t2d-parakeet-fp32-cpu-15e4`, committed as diagnostic
evidence with its `NOTE.md`) was killed partway by a memory-pressure reaper. Before that, it
found two things:

1. **Windows ran the windowless worker on the E-cores.** With throttling left to the OS, the
   E-cores were 100% busy and the P-cores ~14–20% at 4, 6 and 8 threads alike: RTF 0.42 at
   4 threads, and extra threads only oversubscribed the four E-cores. This is a product issue,
   not a benchmarking artefact, because the Phase 1 sidecar is also a windowless background
   process.
2. **Paging.** With Edge holding ~7 GB, available memory fell to ~520 MB and every pass paged in
   1.9–3.8 GB. Its absolute timings are non-decision-grade.

WER was 10.721% at every thread count. Neither contamination touches transcripts.

## 3. Offline baseline: 4 threads, HighQoS (frozen)

Recorded 2026-10-07 04:08Z, tree clean at `ce9c773`, ~8.3 GB available at pre-flight.

| | |
|---|---|
| Rounds | 3 × 160/160 rows; RTF 0.0692 / 0.0685 / 0.0706, **mean 0.0694, CV 1.5%** |
| Whole-utterance decode | p50 381 ms, p95 970 ms, p99 1070 ms; fit **79.5 ms + 57.4 ms per audio-second** |
| Quality | **WER 10.721%** in every round, transcripts identical across rounds |
| System | P- and E-cores both ~80% busy; page-in median 0 per row; peak working set 2.74 GB |

**Why 4.** Six HighQoS pilots on a 56-row subset, each comparison also run in reversed order:
RTF ≈ 0.096 at 2 threads, 0.075 at 3, **0.068–0.069 at 4**, 0.091–0.094 at 5, 0.146 at 6,
0.21–0.22 at 8. Beyond four threads every core is saturated and decoding slows down. The
pilots are supporting evidence only; the frozen figures are the full-corpus rounds.

**Why HighQoS.** Without it the same configuration ran at RTF 0.42, about 6× slower.

## 4. Streaming results (2026-10-08)

**Pre-flight.** The first attempt on 2026-10-08 was **refused at pre-flight**: 3.5 GB available
against a 6 GB floor, with Edge holding ~8 GB private. It ran after the apps were closed, with
these readings:

- 8.47 GB available.
- FP32 hashes, ORT 1.28.0, sherpa-onnx 1.13.8 and the DLL all equal to the baseline.
- QoS read back as mask 1, state 0, priority `0x20`.
- No stale ASR processes; CPU ~5% median.
- Tree clean at `f088767` (`t2d.py` `b59c0119…`, which adds resume safety only; the offline
  worker is unchanged).

**Integrity.**

- One session per policy, with no resume needed.
- 160/160 ids exactly once per policy, no duplicates, no malformed or torn lines.
- `counters-stream-t4.jsonl` has 4544 rows, none torn.
- Both sessions recorded the same HEAD, `t2d.py` hash and QoS.
- The commit session's `git.dirty: true` is caused **only by the tracked `run.json`**, which the
  redecode session had just appended its session record to. That is a harness wart, not a code
  change.

**System during streaming.**

- ~76% total CPU busy.
- P-cores ~73–75% busy at ~195% performance; E-cores ~80% busy at ~130%.
- Minimum available memory 6.05 GB.
- Page-ins of 45k pages (redecode) and 88k (commit) over ~19 min each; no paging regime.
- Peak working set 2.75 GB (redecode) and 2.61 GB (commit).

| | `redecode` | `commit` |
|---|---:|---:|
| **Release-to-final p50 / p95 / p99 / max** | 452 / **1339** / 1838 / 1895 ms | 193 / **443** / 610 / 816 ms |
| wait for in-flight partial p50 / p95 | 95 / 575 ms | 0.5 / 165 ms |
| final-decode compute p50 / p95 | 351 / 863 ms | 171 / 345 ms |
| audio decoded at final p50 / p95 | 5.3 / 14.9 s | 2.1 / 5.3 s |
| utterances over 450 ms | 83 / 160 | 8 / 160 |
| p95 by length: ≤3 s / 3–6 / 6–10 / >10 s | 273 / 598 / 1006 / 1838 ms | 258 / 374 / 484 / 610 ms |
| **Final WER** (offline 10.721%) | **10.643%, Δ −0.08 pp [−0.24, 0.00]** | **24.094%, Δ +13.37 pp [+10.71, +16.32]** |
| finals identical to offline | 159 / 160 | 10 / 160 |
| **Eligible** | **yes** | **no** |
| Gate on p95 | **FAIL** | MARGINAL, moot because ineligible |
| time to first partial p50 / p95 | 0.6 / 1.1 s | 0.6 / 1.1 s |
| time to first useful partial p50 / p95 | 1.1 / 3.2 s | 1.1 / 1.7 s |
| ↳ measured from speech onset | 0.8 / 3.1 s | 0.6 / 1.6 s |
| partial cadence p50 / p95 | 0.5 / 0.7 s | 0.5 / 0.5 s |
| partial compute p50 / p95 | 251 / 665 ms | 165 / 296 ms |
| share of wall time spent decoding partials | 0.55 | 0.34 |
| unstable-partial-word rate, norm / raw | 1.44 / 2.23 | 1.37 / 1.85 |
| revising partials | 777 / 1952 | 973 / 2023 |
| word-display lag p50 / p95 | 0.7 / 8.3 s | 1.1 / 3.6 s |
| empty finals; empty partials while final non-empty | 0; 56 | 0; 52 |

**Timestamps.** Every final has monotonic word starts, and no word ends after the end of the
audio.

## 5. Verdict: CPU FP32 STREAMING: FAIL

Only `redecode` meets the eligibility rule. Its p95 of 1339 ms is 3× the MARGINAL line, and 83
of 160 utterances exceed 450 ms. `commit` reaches p95 443 ms, but only by doubling WER, so it is
ineligible. **No CPU policy qualifies.**

## 6. What the failure is, and what it is not

1. **CPU throughput is not the failure.** The CPU runs Parakeet FP32 at RTF 0.069, 14× faster
   than real time. Even `redecode`, which re-decodes the whole prefix twice a second, spends
   only 55% of wall time decoding partials. Each final's compute is 0.92× of what the offline
   fit predicts for its length, so the CPU delivered exactly the throughput it was measured at.
   It keeps up with speech; it cannot finish a long utterance inside 450 ms after release.
2. **A full-utterance final redecode is too expensive, and its cost grows with utterance
   length.** At ~57 ms per audio-second plus ~80 ms fixed, the final alone exceeds 450 ms
   beyond about 6.5 s of audio. Up to 3 s, `redecode` would pass (p95 273 ms). A second,
   independent component is that release waits for whichever partial is in flight: 575 ms at
   p95, and more than 100 ms on 78 utterances. That wait also grows with length, because the
   partials are themselves whole-prefix decodes.
3. **A naive tail commit without left context meets the latency target only by losing
   unacceptable accuracy.** Cutting committed audio and decoding the tail with no left context
   bounds the final's cost: 5.3 s of tail at p95 instead of 14.9 s. But the export, starting
   cold at every cut point, makes real word errors there:
   - substitutions 144 → 223, insertions 48 → 137, deletions 83 → 258;
   - 109 utterances worse, 9 better;
   - English 10.8 → 24.4% and Russian 10.5 → 22.8%.

   It is not casing, because the WER is `basic`-normalized, and not timestamps pointing past the
   audio. The failure is decoding without left context.

## 7. Consequences

- **4 threads remains frozen** for this machine and configuration. The streaming gate was not
  run as a thread sweep, and nothing in it argues for retuning.
- **HighQoS becomes a Phase 1 requirement for the Windows CPU path** (D-0016). Every
  decision-grade CPU number in this task depends on the process being opted out of
  execution-speed throttling. Without that, Windows confines a windowless worker to the E-cores
  at about 6× the cost. The mechanism the shipped sidecar will use to opt out, and whether the
  OS honours it there, is unmeasured.
- **DirectML/WinML remains unmeasured** (open question #14). Nothing here says a GPU EP passes.
  It would shrink the per-audio-second cost that dominates the final, but not the architecture
  that makes the final scale with length.
- **The next blocker is finalization architecture and acceleration, not model selection.**
  Parakeet FP32 stays the front-runner (D-0013, D-0015); its quality survives `redecode` intact
  (159/160 finals identical to offline). What fails is how and where the final is computed.

## 8. What this does not settle

- **Finalization designs not tried, each a methodology change and therefore out of scope:**
  - cancelling or pre-empting the in-flight partial at release;
  - committing with an overlapping left-context window, so that every tail decode re-reads some
    already-committed audio;
  - a longer right context;
  - finalizing from the last partial plus a short tail;
  - a cache-aware streaming export of the same model.
- **Any other execution provider.** DirectML, WinML and CUDA (still blocked on the cuDNN read)
  are all unmeasured.
- **Process-boundary (IPC) latency.** The 450 ms allowance already assumes it is small, and it
  is unmeasured.
- **Personal speech.** All of the above is proxy-set WER. F-WER and E-WER need Task 1b.
- **Other machines.** The frozen thread count and the QoS finding are for this laptop
  (4 SMT P-cores and 4 E-cores, 16 GB).

## Artifacts

`eval/runs/20261007T040840Z-t2d-parakeet-fp32-cpu-190c/`:

| file | content |
|---|---|
| `run.json` | pre-flight (git, hardware, software, model hashes, topology, memory), config, `stream_sessions` |
| `offline-t4-r{1,2,3}.{json,jsonl}` | offline baseline: per-round summary and per-utterance rows |
| `counters.jsonl` | PDH samples during the offline rounds |
| `stream-redecode-t4.{json,jsonl}` | `redecode`: session summary and per-utterance partials and final |
| `stream-commit-t4.{json,jsonl}` | `commit`: the same |
| `counters-stream-t4.jsonl` | PDH samples during both streaming policies |
| `analysis.json` | `t2d analyze` output: sweep, streaming metrics, gate |

The diagnostic first attempt is `eval/runs/20261006T194724Z-t2d-parakeet-fp32-cpu-15e4`. No
audio or model files are committed.
