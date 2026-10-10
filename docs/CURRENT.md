# Current

The only doc expected to change every session. Read this first when resuming work.

**Last updated:** 2026-10-10

## Where we are

**Research is complete.** R1–R9 all landed, were verified on disk, and have been synthesized
centrally into `docs/SYNTHESIS.md`, which is now the current decision document. Five new
decisions (D-0007…D-0011) were recorded, and six corrections were applied to
`ARCHITECTURE.md`, `BENCHMARKS.md` and `CLAUDE.md`.

**Phase 0 has started. The evaluation harness exists and passes its own tests.**
`uv` is installed; `pyproject.toml`, `src/hermes_eval/` and `eval/` are on disk. 155 tests,
ruff and pyright clean. Zero runtime dependencies — the scoring path is pure stdlib on
purpose, because a published benchmark cannot blame its numbers on a third-party WER
package.

What the harness does today: strict manifest validation, per-utterance and corpus WER,
F-WER with the full decomposition (casing error rate, per-class punctuation F1, ITN slot
error rate), E-WER over annotated entity spans, latency percentiles, subset metrics on
every metadata axis, a seeded paired utterance-level bootstrap, the decision rule from
`BENCHMARKS.md` §1.2 encoded in code, and immutable run directories carrying full
provenance. Three adapters: `perturb` (deterministic synthetic fake-ASR, for fixtures),
`replay` (scores transcripts captured by hand — this is how closed competitors get
measured), and `sherpa` (real ONNX Runtime ASR, for screening only — not a shipping path).
See `eval/README.md`.

**The Public Proxy Evaluation Set v1 exists and validates.** 160 utterances from pinned
public corpora — EdAcc (50, 25 speakers, 16 L1 backgrounds), LibriSpeech test-clean (30, one
per speaker), RuLS (20, 7 readers), Golos crowd and farfield (10 each), plus 20 noise and 20
reverb variants of the same 20 clean utterances. Built by `hermes-eval build-dataset` from
full commit shas; the manifest and audio are **byte-identical across rebuilds**. No audio is
redistributed — EdAcc and Golos both carry ShareAlike, and `eval/datasets/**/audio/` stays
gitignored. See D-0012 and `eval/datasets/public-proxy-v1/`.

**It is a proxy and it does not retire Task 1b.** No public corpus in scope ships a formatted
reference, so **F-WER is not computable on it**, and none annotates entity spans, so **E-WER
is not either**. It measures WER on accented English, read English, read Russian, Russian
far-field commands, and two robustness deltas. It measures nothing about dev-speak,
code-switching, ITN, punctuation, the real microphone or the capture path. Any model decision
made on it alone is provisional.

**Task 2a (ASR candidate screening) is COMPLETE.** All three candidates from SYNTHESIS §5
ran through the harness on ONNX Runtime against the frozen proxy set, on one runtime, one
provider, one thread count and one set of audio bytes. **Nemotron Speech Streaming EN
@560 ms is eliminated; Parakeet TDT v3 and Whisper large-v3-turbo are retained.** Parakeet
leads every axis this set can measure. **No production backend has been chosen** — that
needs Task 1b. Full detail in **§ Task 2a — COMPLETE** below and in
`docs/research/T2A-screening.md`.

**Task 2b (Parakeet confidence / N-best architecture gate) is COMPLETE — verdict A, KEEP
CURRENT CONTRACT (D-0014).** 160/160 rows. sherpa's public emitted-token probability is as
good a word confidence as anything the full distribution offers (AUROC 0.884); N-best is
reachable only by owning a small Python TDT beam loop, and carries ~2 pp of oracle headroom
the decoder cannot rank. SYNTHESIS §5.1's risk is retired for Parakeet: no Rust decoder in
Phase 1. See **§ Task 2b — COMPLETE** below and `docs/research/T2B-confidence.md`.

**Task 2c (Parakeet INT8 vs FP32 precision gate) is COMPLETE — FP32 PREFERRED (D-0015).**
FP32 cuts WER 2.57 pp overall [−3.94, −1.32] (13.29 → 10.72), is worse on no slice, flips 4×
fewer transcripts under inaudible dither, and agrees with a direct-ORT decode on 159/160 (INT8
127/160). Confidence ties. Cost: +1.74 GB resident (2.74 GB peak), 3.8× disk, ~2× load,
+7–9% decode time. See **§ Task 2c — COMPLETE** below and `docs/research/T2C-precision.md`.

**Task 2d (Parakeet FP32 CPU thread sweep / streaming latency gate) — COMPLETE: CPU FP32
STREAMING: FAIL (2026-10-08).** On this machine, Parakeet FP32 on the ORT CPU EP runs at
**4 threads (frozen) with `--qos high` (required)**: offline RTF 0.0694, WER 10.721%. Under the
pre-registered gate, the only *eligible* policy, `redecode` (WER 10.643%, Δ −0.08 pp
[−0.24, 0.00]), has **release-to-final p95 1339 ms** (p50 452, p99 1838), so it fails the 450 ms
MARGINAL line by 3×. LocalAgreement-2 `commit` would land at p95 443 ms (MARGINAL), but it
raises WER to **24.09% (+13.4 pp [+10.7, +16.3])** and is **ineligible**. No CPU policy
qualifies. Run: `eval/runs/20261007T040840Z-t2d-parakeet-fp32-cpu-190c`. **Recorded as
D-0016**; write-up `docs/research/T2D-cpu-streaming.md`. HighQoS is now a Phase 1 requirement on
the Windows CPU path. DirectML/WinML is still unmeasured. **The next blocker is finalization
architecture and acceleration, not model selection.** See **§ Task 2d** below.

**Task 2e (context-preserving finalization gate) — COMPLETE: CPU FINALIZATION NOT RESCUED
(2026-10-09).** LocalAgreement-2 `commit` with bounded acoustic left overlap (every tail
decode re-reads 1, 2 or 3 s of committed audio; re-read words dropped by timestamp midpoint)
cuts boundary substitutions, drops and hallucinations ~3–6×, but every arm stays resolved
worse than offline: **+7.8 / +5.0 / +6.4 pp WER** (CIs clear of zero) on a pre-registered
40-row screen, so none was eligible and the full 160-row gate was not run. The remaining
damage is duplicated and dropped words at the stitch, where two decodes disagree on a
boundary word's timestamp. Screen latency was contaminated (the L=0 control ran 1.7× slower at p95
than Task 2d on the same rows) and is not decision-grade; the verdict rests on quality. **Next:
execution-provider acceleration of the full `redecode` final.** **Recorded as D-0017**;
write-up `docs/research/T2E-finalization.md`. See **§ Task 2e** below.

**Task 2f (acceleration path selection) — PROVIDER SELECTED, GATE PRE-REGISTERED, NOT RUN
(2026-10-10).** **TEST DIRECTML NEXT**, as a *measurement vehicle*: the shipping provider stays
undecided. On an RTX 4050, Windows ML adds no in-scope accelerator. Its only included GPU EP
is DirectML ("legacy"), and its only NVIDIA catalog EP is TensorRT-RTX. The DirectML EP comes
from `onnxruntime-windowsml==1.28.0.202607272323`, which is an ORT 1.28.0 + DirectML 1.15.4
build, so it matches the CPU baseline's ORT version. It is used only as an isolated
distribution, outside `.venv`. Standalone `onnxruntime-directml` is frozen at 1.24.4. sherpa's
wheel cannot drive DirectML, so the experiment uses direct ORT sessions and a lean owned TDT
greedy loop, which **must first pass CPU parity against sherpa** (Stage 0). **Recorded as
D-0018**; plan and gate in `docs/research/T2F-acceleration-plan.md`. See **§ Task 2f** below.

**No audio capture, no Rust.** That is deliberate and unchanged. There is now ASR, but only
as a measurement harness: `src/hermes_eval/asr_sherpa.py` exists to score candidates, not to
ship.

## Read order for a fresh session

1. `CLAUDE.md` — invariants and vocabulary
2. **`docs/SYNTHESIS.md`** — the decision document; supersedes `ARCHITECTURE.md` where they
   disagree
3. `docs/DECISIONS.md` — D-0001…D-0018
4. `docs/ROADMAP.md` — phases and checkpoints (Phase 1 scope is narrowed by SYNTHESIS §19)
5. `docs/research/R1…R9` — evidence, only as needed

## Research status — closed

| # | Workstream | State |
|---|---|---|
| R1 | Quantization & contextual biasing | Done — partially superseded by R4 |
| R2 | Hotkeys & text injection | Done |
| R3 | Streaming stability & code-switch LID | Done |
| R4 | ASR model landscape (salvaged) | Done |
| R5 | Rust stack | Done |
| R6 | Benchmark methodology & harness design | Done |
| R7 | NLP, intent, ITN | **Done** 2026-09-26 |
| R8 | Correction pass, GER, confidence | **Done** 2026-09-26 |
| R9 | Voice-command safety | **Done** 2026-09-26 |
| — | **Central synthesis** | **Done** 2026-09-26 → `docs/SYNTHESIS.md` |

## Target hardware

i5-12450H (8C/12T, Alder Lake, AVX-VNNI) · 15.7 GB RAM · RTX 4050 Laptop **6 GB VRAM** ·
Windows 11. CPU-only must be first-class.

**Methodology warning:** Open ASR Leaderboard RTFx is measured on 1x H200 + 23 vCPU + 256 GB
RAM. **None of it transfers.** The only laptop-class figures found anywhere are qwen3-asr.cpp
on an RTX 5060 8 GB (235 ms median per 2 s chunk, 0.6B) and LocalScore's RTX 4050 llama.cpp
submissions (Llama-3.2-1B Q4_K_M: 301 ms TTFT).

Toolchain: Python 3.11.14, Node 24.14, git 2.53, **`uv` 0.12.19** (installed 2026-09-26 to
`~/.local/bin`). **Missing: `rustup`** — a Phase 1 prerequisite (D-0006), not Phase 0.

## Task 2a — COMPLETE (2026-09-28)

Task 2a screened the three candidates from `SYNTHESIS.md` §5 against the frozen proxy set,
to eliminate the unsuitable ones cheaply. **All three are now measured. One is eliminated,
two are retained, and no production backend has been chosen** — that was never this task's
job. Full write-up: `docs/research/T2A-screening.md`.

### Run status

| Candidate | Status | Run ID |
|---|---|---|
| **Parakeet TDT 0.6B v3 int8** | Complete | `20260927T022919Z-t2a-parakeet-tdt-v3-aff8` |
| **Nemotron Speech Streaming EN 0.6B @560 ms int8** | Complete | `20260927T031249Z-t2a-nemotron-stream-en-560ms-c9f4` |
| **Whisper large-v3-turbo int8** | **Complete** | `20260928T002321Z-t2a-whisper-large-v3-turbo-c4c0` |

All three scored manifest sha256 `2b3a46ede2700f30…`, n=160, and carry all six run
artifacts locally. **`run.json` and `predictions.jsonl` for each are committed** (force-added
past the `eval/runs/` ignore, ~0.9 MB of text): the provenance, metrics and raw hypotheses,
which is everything that costs ~80 minutes of compute to regenerate. The other four
artifacts are derived by scoring and stay local.

### The outcome

WER %, lower is better. The bold column is the front-runner.

| subset | n | **Parakeet TDT v3** | Nemotron EN 560 ms | Whisper turbo |
|---|---:|---:|---:|---:|
| OVERALL | 160 | **13.29** | 32.55 | 14.89 |
| en / ru | 112/48 | **12.79** / 15.75 | 18.66 / 100 | 15.42 / **12.33** |
| accented_en | 50 | **18.74** | 27.67 | 23.64 |
| general_en | 30 | **1.81** | 4.12 | 1.81 |
| ru_clean | 20 | 13.41 | 100 | **8.94** |
| robust_noise / reverb | 20/20 | **18.42 / 12.57** | 30.12 / 28.36 | 18.42 / 13.74 |

| | **Parakeet** | Nemotron | Whisper |
|---|---:|---:|---:|
| RTF corpus | **0.47** | 2.44 | 2.05 |
| utterances slower than real time | **2 / 160** | 160 / 160 | 160 / 160 |
| latency p50 / p95 | **2693 / 5707 ms** | 12741 / 40029 ms | 11965 / 22343 ms |
| median latency, utterances ≤3 s | **1958 ms** | 5792 ms | 9267 ms |
| peak working set (single session) | 996 MB | **797 MB** | 2118 MB |
| empty outputs | 2 / 160 | 23 / 160 | **0 / 160** |

**Eliminated: Nemotron Speech Streaming EN 0.6B @ 560 ms.** Dominated on every axis except
peak RAM, by *both* other candidates — worse English than Whisper by 3.24 pp (CI clear of
zero) and worse than Parakeet by more, slowest of the three, 23/160 empty outputs,
punctuation on only 50 of 137 non-empty outputs. Its one win is 199 MB of RAM on a 15.7 GB
machine. The streaming-harness caveat is granted and does not rescue the quality deficit.

**This overturns `SYNTHESIS.md` §5, which calls Nemotron at 560 ms the "leading
hypothesis."** That hypothesis rested on architecture and licensing, never on a laptop-class
measurement. **Corrected 2026-10-05:** SYNTHESIS §5 and §11 now carry the measured
ranking, and **D-0013** supersedes D-0011's model hypothesis.

**Retained: Parakeet TDT 0.6B v3**, the front-runner. Best English and best accented English
(the W2 core, CI clear of zero), the only candidate faster than real time on the CPU EP,
4.7× lower short-utterance latency, 996 MB, native formatting on 154/158 non-empty outputs,
CC-BY-4.0, simplest integration.

**Retained: Whisper large-v3-turbo**, as the accuracy-tier fallback and no wider. It wins
Russian read speech (8.94%, CI clear of zero) and returned 0 empty outputs, and it is
statistically indistinguishable from Parakeet in aggregate. But it loses English and
accented English with the CIs clear of zero, never once beats real time, has the worst
short-utterance latency of all three because of the fixed 30 s encoder window, holds 2.1 GB,
emits formatting on only ~¾ of outputs, and stalls **29.6 s on every language switch**
through sherpa's API.

**The aggregate gap between the two survivors is noise and must not be quoted as a result.**
Parakeet is 1.60 pp better overall, 95% CI [−0.08, +3.31] — it includes zero. What *is* real
is the English slice: +2.63 pp [+0.80, +4.43] and accented English +4.90 pp [+1.72, +8.35].
Paired utterance-level bootstrap, 2000 resamples, seed 20260926, on **WER** counts — not
F-WER, which is uncomputable on this set.

### Fairness work the Whisper rerun required

`CURRENT.md` previously flagged this as "a fairness defect to correct when Whisper is
rerun". It was corrected in the harness rather than caveated in prose.

sherpa binds Whisper's language at recognizer construction, so `langs=en|ru` built two ORT
sessions over one set of weights and would have reported ~2× peak RAM against two
single-session transducers. The fix is a **one-resident-recognizer protocol**: decode all
English rows, release the session (`gc.collect()`, with the working set read before and
after), build the Russian one, warm it identically, decode the Russian rows. It stays **one
run over one manifest with one sha256** — nothing merged after the fact.

Verified, not assumed: the release returned **1940 MB**, and the whole-run peak (2135 MB)
and the single-session peak (2118 MB) agree to within 17 MB, which is what says only one
recognizer was ever resident. Switch cost is reported apart from every decode figure:
**29.6 s** = 0.5 s evict + 6.3 s load + 22.7 s warm-up.

Parakeet and Nemotron have one recognizer regardless, so their runs remain valid as measured
and were **not** re-run.

### Findings banked from Task 2a

- **ORT DLL conflict on Windows, and it will recur.** The sherpa-onnx wheel ships no
  `onnxruntime.dll`, so Windows resolves the bare name to the inbox
  `C:\Windows\System32\onnxruntime.dll` — version 1.17, the Windows ML copy — while sherpa
  1.13.8 needs ORT API 28. Symptom: `The requested API version [28] is not available, only API
  versions [1, 17] are supported in this build`. Fix: pin `onnxruntime==1.28.0` and copy its
  DLL next to `_sherpa_onnx.pyd`, since a dependent DLL resolves from the loading module's own
  directory before System32. `hermes_eval.asr_sherpa.ensure_runtime()` does it.
  **Anyone shipping ORT on Windows meets this; the inbox copy is not going away.**
- **DirectML needs a D-0011 revisit.** ONNX Runtime's own documentation now states: *"DirectML
  continues to be supported, but new feature development has moved to WinML for Windows-based
  ONNX Runtime deployments."* On top of that, sherpa-onnx ships no prebuilt DirectML wheels
  (source build only), and all three candidate exports are dynamic int8 (`producer:
  onnx.quantize`) — the pattern the DML EP handles worst, so expect CPU fallback rather than
  speed-up, and an fp16 re-export if a DML path is wanted. DirectML viability is therefore
  **unmeasured for all three, uniformly**. D-0011's reasoning for DirectML (ships with the
  driver stack, vendor-neutral, no redistribution question) still holds; its upstream status
  does not. **Needs a DECISIONS entry weighing WinML, not a silent switch.**
- **The confidence signal is partially reachable, cheaply.** sherpa-onnx's
  `OfflineRecognitionResult` exposes `ys_log_probs`, `tokens` and `timestamps`;
  `OnlineRecognizerResult` exposes `ys_probs`, `lm_probs` and `context_scores`. That is the
  log-prob of the **emitted** token, not the full per-step distribution that R8's entropy
  method needs, so it narrows open question #1 without closing it — and it is reachable
  through a decode loop somebody else already wrote, which is evidence about §5.1's fallback
  plan. N-best would come from `decoding_method="modified_beam_search"`, untested.
  **[Answered by Task 2b, 2026-10-06: the emitted-token prob ties the best
  full-distribution signal on Parakeet; sherpa's beam returns one hypothesis, so N-best
  needs an owned loop — D-0014.]** With the
  shortlist down to two, **Parakeet is the one to test first**: it is the only survivor whose
  speed makes it a plausible default, and it is a transducer, which is the case §5.1's
  fallback plan was written about.
- **Whisper's 30 s window is structural, and it is measured now.** Its encoder pads every
  input to 30 seconds, so a 2 s utterance costs what a 25 s one does. Measured effect: it is
  the *slowest of all three* on utterances ≤3 s (9267 ms median vs Parakeet's 1958 ms) while
  being the faster of the two slow candidates on utterances ≥9 s. Dictation is made of short
  utterances. Tuning does not fix this.
- **Formatting emission differs sharply between backends, and F-WER cannot see it yet.**
  Non-empty outputs carrying any punctuation / any uppercase: Parakeet 154/154 of 158,
  Whisper 117/120 of 160, Nemotron 50/137 of 137. So ~a quarter of Whisper's outputs come back
  unformatted through this export at `greedy_search`, and Nemotron would need a separate
  punctuation model. Caveat twice over: it is a property of these exports and this runtime,
  not necessarily of the models, and it counts emission rather than correctness. It is a flag
  for Task 1b, where a formatted reference exists, not a score.

### Harness changes made for Task 2a (on disk)

- `src/hermes_eval/asr_sherpa.py` — the three candidates, pinned, behind the existing
  `ASRAdapter` seam. Never reads `record.reference`. Now also takes `resident=N`, which caps
  how many recognizers may be alive at once and times/measures the teardown, plus a
  `language_sessions` block in the run record's provenance.
- `src/hermes_eval/resources.py` — per-process peak working set / commit, and PID-attributed
  VRAM. This is R6's deferred resource sampling, now landed. Peak VRAM is **null rather than
  zero** when nothing is attributable: "no GPU allocation" and "could not observe one" are
  different claims.
- `runner.py` re-reads `describe_env()` after the loop, so corpus RTF and decode totals reach
  the run record; `predictions.jsonl` now carries per-utterance `extra` (RTF, audio seconds).
- `runner.py` also gained `--decode-order manifest|language`. Language order groups the
  manifest by `metadata.language` before decoding, so a backend that binds a language at
  construction rebuilds once rather than once per alternation; outputs stay sorted by id, and
  the run record carries the mode plus a sha256 of the decode sequence. Default is unchanged.
- `hermes-eval run --resources` turns sampling on. Off by default.
- `pyproject.toml` gains an optional `asr` group (sherpa-onnx, onnxruntime, numpy, soundfile).
  The scoring path stays stdlib-only and never imports it.
- Models live in `models/` (gitignored), ~1.5 GB, fetched from the sherpa-onnx `asr-models`
  release. Download commands are in `docs/research/T2A-screening.md`.

### What Task 2a deliberately did not do

- **No production backend chosen.** That needs the personal set: F-WER on a formatted
  reference, E-WER on annotated entities, dev-speak, code-switching, ITN, the real
  microphone. Parakeet leads every axis this proxy set can measure; that is a strong prior
  for Task 2 item 3, not a decision.
- **No re-run of Parakeet or Nemotron**, no added models, no added datasets, no fine-tuning.

## Task 2b — COMPLETE (2026-10-06) — verdict A, keep the contract

Task 2b asked whether the ONNX / sherpa-onnx / ORT path can supply useful token confidences
and N-best for Parakeet TDT 0.6B v3 int8 **without Hermes owning a large decoder** (SYNTHESIS
§5.1, D-0011's Phase 0 exit criterion, open question #1). **Answered: yes. Verdict A — KEEP
CURRENT CONTRACT. Recorded as D-0014.** Full write-up: `docs/research/T2B-confidence.md`.

### Run

| | |
|---|---|
| Run directory | `eval/runs/20261006T033722Z-t2b-parakeet-confidence-27dc` — `run.json`, `raw.jsonl`, `analysis.json` (pre-registered), `supplement.json` (post-hoc) |
| Rows | **160/160**, unique, manifest order, no truncation — rows 1–91 at `013217b` (dirty), rows 92–160 resumed at `87ec846` (clean), resume recorded in `run.json["resumes"]` |
| Manifest / model | sha256 `2b3a46ed…d7053e` / `d0a44f3c…` — re-verified before and after the resume, identical to Task 2a |
| Reproduction | sherpa greedy WER 13.294% — Task 2a's Parakeet 13.2943% to every reported digit |

```
uv run --group asr python -m hermes_eval.t2b collect [--resume <run-dir>]   # ~45 min
uv run python -m hermes_eval.t2b analyze    <run-dir>   # ~10 min at 2000 resamples
uv run python -m hermes_eval.t2b supplement <run-dir>   # ~5 min
```

**Committed** with the write-up, force-added past the `eval/runs/` ignore as Task 2a's were:
`run.json`, `raw.jsonl` (3.3 MB — the raw measurements every number is computed from),
`analysis.json` and `supplement.json`. That is ~45 min of compute; the rest re-derives.

### Results

**Confidence.** AUROC for correct vs incorrect words, utterance-bootstrap 95% CI, n=160, 197
scorable errors:

| signal | reachable via | AUROC | Δ vs emitted-token prob |
|---|---|---:|---:|
| **sherpa native `ys_log_probs` (emitted-token prob)** | **sherpa API** | **0.884 [0.855, 0.908]** | — |
| Gibbs entropy | full distribution | 0.883 | +0.004 [+0.001, +0.008] — resolved, negligible |
| top-1/top-2 margin | full distribution | 0.866 | −0.013 [−0.018, −0.009] |
| Tsallis-1/3 = Rényi-1/3 (R8 §D's best) | full distribution | 0.841 | **−0.038 [−0.063, −0.016]** |
| TDT duration head | full distribution | 0.69 | −0.19 |

Same order in every slice. accented_en (94 errors) is the only well-measured slice and
ties at the top (0.856–0.863). **general_en (11 errors, CI ~0.40 wide) is uninformative**;
russian, noise and reverb (~30 errors each) show the signal works but cannot rank the
near-ties. Highlighting the lowest 10% / 20% of words catches 56% / 74% of scorable
errors. Word P = Π token p has ECE 0.022 (mildly overconfident on accented). **~41% of word
errors are deletions, invisible to any word confidence.** Best utterance score: mean
emitted-token log-prob, also sherpa-reachable (ρ 0.68 vs utterance WER).

**N-best** (owned beam = sherpa's algorithm, all hypotheses kept): **oracle WER −1.99 pp
[−2.86, −1.27] at K=4** (−3.05 pp on accented), but the decoder cannot rank the list —
beam-4 top-1 vs greedy −0.16 pp [−0.89, +0.53], and beam-8 top-1 is *worse* (+1.01 pp).
A lower-ranked hypothesis beats top-1 in 34/160 utterances; an error-free one is present
but not first in 7/100. Only ~2 of 4 hypotheses are lexically distinct. Python loop cost:
~3.6× greedy at K=4.

**Parity.** Probe vs sherpa greedy text identical on 127/160; WER Δ −0.31 pp
[−0.71, +0.11]; emitted log-prob |Δ| median 0.00017 nats. First divergences sit at a
median top-1/top-2 margin of 0.13 nats (88% under 1 nat, vs 8% of all steps) — the
recorded int8 numerical sensitivity, not an algorithmic difference. It moves neither
WER, nor confidence, nor N-best.

**Timing: non-decision-grade.** On matched content (ratio to Task 2a's per-utterance
latency), rows 92–160 ran ~20% *faster* than rows 1–91 (p50 0.79 vs 0.99; noise and reverb
both 1.00 → 0.81). No paging slowdown, but system state moved absolute timings between
sittings. Within-row ratios are stable and usable; absolute RTF and latency are not.

### What Phase 1 can rely on

- **`FinalTranscript.text`** — yes; greedy (sherpa or owned, equivalent). Not beam.
- **`tokens[].confidence`** — yes, emitted-token prob via sherpa's API, **for highlighting
  only**. Replaces D-0009's "entropy-based".
- **`nbest[]`** — yes, via the owned Python beam, K ≤ 4, deduplicated, only when
  `decode_params.beam > 1`. No Phase 1 consumer.
- **sequence score** — yes, rank-only; never a probability.
- **timestamps** — yes in shape (sherpa `timestamps` + `durations`); accuracy unmeasured.
- **`PartialTranscript`** — not established; Parakeet here is offline, partials would be
  re-decodes, and stability is unmeasured.

**A small custom Python decoder is justified for N-best and biasing, not for confidence.**

### Harness changes made for Task 2b (committed)

- `src/hermes_eval/tdt_probe.py` — the measurement instrument (committed at `87ec846`):
  a Python/ORT port of sherpa 1.13.8's TDT greedy and modified-beam decoders that keeps
  what sherpa discards. **Not a shipping decoder.**
- `src/hermes_eval/t2b.py` — `collect`, `analyze`; new since `87ec846`: unit construction
  shared via `_build_units` (verified to reproduce `analysis.json` exactly), and a
  `supplement` subcommand for the post-hoc measures.
- `src/hermes_eval/confidence_eval.py` — new `bootstrap_ap`.
- `tests/test_confidence_eval.py` — tests for `bootstrap_ap` and the divergence locus.

### Corrections applied

- `T2A-screening.md`'s "on the installed 1.13.8 wheel, it is there" — struck and corrected.
- D-0009 amended by D-0014 (emitted-token probability, not entropy). D-0011's exit
  criterion marked met.
- SYNTHESIS reconciled with D-0014: §5.1 marked resolved for Parakeet (the "substantial
  Rust task" claim superseded), §9's confidence source amended, §15 risks 1–2 updated, and
  a note added to C5. DirectML vs WinML is left unresolved.

## Task 2c — COMPLETE (2026-10-06) — FP32 PREFERRED

Task 2c asked whether Parakeet TDT v3 FP32 earns its memory/runtime cost over INT8 for
Phase 1. **Answered: yes. Recorded as D-0015.** Full write-up: `docs/research/T2C-precision.md`.

| | |
|---|---|
| Run directory | `eval/runs/20261006T055203Z-t2c-parakeet-int8-vs-fp32-01d0` — `run.json`, per-arm `{arm}-p{n}.json` + `-sherpa.jsonl`, pass-1 `-perturb.jsonl` / `-probe.jsonl`, `analysis.json` |
| FP32 model | HF `csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3` @ `1a468a35` → `models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-fp32/` (2.55 GB, external-data encoder; hashes match HF LFS) |
| Design | ABAB fresh processes (int8, fp32, int8, fp32), identical audio / features / decoder / CPU EP / 4 threads / scoring |
| Reproduction | INT8 WER 13.294% and INT8 sherpa/ORT parity 127/160 — Tasks 2a/2b exactly |

```
uv run --group asr python -m hermes_eval.t2c collect    # ~95 min
uv run python -m hermes_eval.t2c analyze <run-dir>
```

| | INT8 | FP32 |
|---|---:|---:|
| WER overall (Δ [CI]) | 13.29 | **10.72** (−2.57 [−3.94, −1.32]) |
| WER en / ru | 12.79 / 15.75 | 10.77 / 10.50 (both CIs clear) |
| WER accented_en | 18.74 | 16.99 (−1.74 [−4.01, +0.34], unresolved) |
| WER noise / reverb | 18.42 / 12.57 | 11.70 / 8.77 (both CIs clear) |
| repeated-run agreement | 160/160 bit-identical | 160/160 bit-identical |
| sherpa vs direct-ORT text identical | 127/160 | **159/160** |
| changed by inaudible 1-LSB dither | 30/160 | **8/160** (Δ −13.8 pp [−20.6, −7.5]) |
| changed by 5 ms frame shift | 45/160 | 34/160 (not resolved) |
| confidence AUROC (emitted-token) | 0.884 | 0.892 (Δ +0.008 [−0.014, +0.030]) |
| peak working set | **996 MB** | 2736 MB |
| model on disk / load | **670 MB / ~4.7 s** | 2550 MB / ~9–12 s |
| decode time, per-utt ratio | — | ×1.07 [1.01, 1.15] |

**Timing finding:** three of four arm processes hit contiguous stretches decoding ~5× faster
than the same utterances did in Task 2a, in both arms — a system-state regime (likely P/E-core
placement), not a model property. Ratios are computed on regime-matched rows; absolute
latencies are non-decision-grade. That scheduling swing dwarfs the 7% precision cost, which
raises the value of Task 2 item 5 (thread sweep).

**Phase 1 implication:** ship Parakeet FP32 on the CPU EP, sidecar budget ~2.8 GB, load once
at start. All Task 2a/2b Parakeet figures are INT8 and understate the model; the backend
decision must use FP32 (and Whisper's fp32 headroom is likewise unmeasured). **INT8 remains
the documented low-memory fallback.** D-0014's confidence / N-best design is unchanged.
DirectML vs WinML (open question #14) remains unresolved — this task chose a representation,
not an execution provider. **FP32 has not been measured on personal speech**; all of the
above is proxy-set WER.

Harness changes (committed in `4e403e5`): `src/hermes_eval/t2c.py` (new); `TdtProbe` takes
`model_dir` and `files` (defaults unchanged).

## Task 2d — COMPLETE: CPU FP32 STREAMING: FAIL (2026-10-08)

### Streaming gate — FAIL

| | |
|---|---|
| Run | the baseline run directory below — `stream-{redecode,commit}-t4.{json,jsonl}`, `counters-stream-t4.jsonl`, `run.json` `stream_sessions`, `analysis.json` (regenerated by `t2d analyze`) |
| Command | `t2d stream <run> --threads 4 --qos high`, unchanged: 0.5 s hop, 1.0 s right context, push-to-talk release = end of audio, 160 utterances in real time per policy |
| Pre-flight | 2026-10-08 18:46Z. The first attempt that day was **refused at pre-flight** (3.5 GB available, Edge ~8 GB private); it ran after the apps were closed: 8.47 GB available, FP32 hashes = baseline, ORT 1.28.0 / sherpa-onnx 1.13.8 / DLL `14e18662…`, CPU EP, QoS readback mask 1 / state 0 / priority `0x20`, only the pre-flight's own Python processes, CPU ~5% median, tree clean at `f088767` (`t2d.py` `b59c0119…`) |
| Integrity | one session per policy, no resume needed; 160/160 ids exactly once per policy, no duplicates, no malformed or torn lines; counters 4544 rows, none torn. The commit session records `git.dirty: true` **only because the redecode session had just appended to the tracked `run.json`**; HEAD and the `t2d.py` hash are the same in both sessions |
| System | ~76% total CPU busy during both policies; P-cores ~73–75% busy at ~195% performance, E-cores ~80% at ~130%; min available memory 6.05 GB; page-ins 45k (redecode) / 88k (commit) pages over ~19 min each, no paging regime; peak working set 2.75 / 2.61 GB |

| | `redecode` | `commit` (LocalAgreement-2) |
|---|---:|---:|
| **Release-to-final p50 / p95 / p99 / max** | 452 / **1339** / 1838 / 1895 ms | 193 / **443** / 610 / 816 ms |
| └ wait for in-flight partial p50 / p95 | 95 / 575 ms | 0.5 / 165 ms |
| └ final decode compute p50 / p95 | 351 / 863 ms | 171 / 345 ms |
| └ audio decoded at final p50 / p95 | 5.3 / 14.9 s | 2.1 / 5.3 s |
| p95 by length ≤3 s / 3–6 / 6–10 / >10 s | 273 / 598 / 1006 / 1838 ms | 258 / 374 / 484 / 610 ms |
| **Final WER** (offline 10.721%) | **10.643%, Δ −0.08 pp [−0.24, 0.00]**; 159/160 identical to offline | **24.094%, Δ +13.37 pp [+10.71, +16.32]**; 10/160 identical |
| Eligible (CI low ≤ 0 and Δ ≤ +0.5 pp) | **yes** | **no** |
| Gate on p95 | **FAIL** | MARGINAL (moot — ineligible) |
| Time to first partial p50 / p95 | 0.6 / 1.1 s | 0.6 / 1.1 s |
| Time to first useful partial p50 / p95 (from press) | 1.1 / 3.2 s | 1.1 / 1.7 s |
| — from speech onset p50 / p95 | 0.8 / 3.1 s | 0.6 / 1.6 s |
| Partial cadence p50 / p95 | 0.5 / 0.7 s | 0.5 / 0.5 s |
| Partial compute p50 / p95 | 251 / 665 ms | 165 / 296 ms |
| Unstable-partial-word rate (norm / raw) | 1.44 / 2.23 | 1.37 / 1.85 |
| Revising partials | 777 / 1952 | 973 / 2023 |
| Word-display lag p50 / p95 | 0.7 / 8.3 s | 1.1 / 3.6 s |
| Empty finals; empty partials while final non-empty | 0; 56 | 0; 52 |

**Verdict: CPU FP32 STREAMING: FAIL.** Only `redecode` meets the eligibility rule, and its p95
is 3× the MARGINAL line. The failure is a function of utterance length. Up to 3 s it would pass
(p95 273 ms), but every final re-decodes the whole utterance at ~57 ms per audio-second. On top
of that it waits for whichever partial is in flight at release, which is 575 ms at p95. Anything
longer than ~6 s cannot finalize inside 450 ms on this CPU.

**Why `commit` is ineligible.** Committing at a word boundary and decoding only the uncommitted
tail strips left context from every later segment. The errors are real word errors, not casing
(the WER is `basic`-normalized): substitutions 144 → 223, insertions 48 → 137, deletions
83 → 258. 109 utterances got worse and 9 better, in English and Russian alike (10.8 → 24.4%,
10.5 → 22.8%). The damage sits at the cut points: duplicated or dropped words, and hallucinated
fillers after a fresh segment start. Cutting the tail cuts latency, but this export, decoded
without context, cannot do it at this quality.

**Timestamps.** Every final has monotonic word starts, and no word ends after the end of the
audio. The commit failure is not timestamps pointing past the audio; it is decoding a segment
without its left context.

**What this does not settle.** It does not test a final that cancels the in-flight partial, a
longer right context, or a commit policy that re-decodes with overlap. Each of those is a
methodology change, so none was tried here. It also does not test any other execution
provider: DirectML/WinML (open question #14) is unmeasured. 4 threads stays frozen, because the
gate was not run as a thread sweep.

**What Task 2d establishes (D-0016; full write-up `docs/research/T2D-cpu-streaming.md`):**

1. **CPU throughput is not the same thing as the streaming failure.** The CPU decodes at
   RTF 0.069 (14× real time). `redecode` spends only 55% of wall time on partials, and each
   final costs 0.92× of what the offline fit predicts. The CPU keeps up with speech; it cannot
   finish a long utterance within 450 ms of release.
2. **A full-utterance final redecode is too expensive and scales with utterance length:**
   ~80 ms + 57 ms per audio-second, plus the in-flight partial wait (575 ms at p95). It
   exceeds 450 ms beyond ~6 s, on 83 of 160 utterances.
3. **A naive context-free tail commit meets latency only by losing unacceptable accuracy**
   (+13.4 pp WER, with substitutions, insertions and deletions all up at the cut points).
4. **4 threads remains frozen** for this machine.
5. **HighQoS is a Phase 1 requirement for this Windows CPU path.** The product's opt-out
   mechanism is still unmeasured.
6. **DirectML/WinML remains unmeasured.**
7. **The next blocker is finalization architecture and acceleration, not model selection.**
   Parakeet FP32's quality survives `redecode` intact (159/160 finals identical to offline).

## Task 2e — COMPLETE: CPU FINALIZATION NOT RESCUED (2026-10-09)

**The question.** Can a bounded context-preserving finalization policy keep offline-quality WER
while keeping release-to-final p95 ≤ 450 ms on the CPU? **No — not with acoustic overlap.**

**Design.** The approaches were tried in the brief's order:
1. **Reusing cached state is not available.** The export is offline and full-context, so no
   encoder cache is valid across a cut. sherpa's `OfflineRecognizer` accepts no decoder
   state, and re-seeding the decoder would mean switching to the owned Python loop
   (`tdt_probe`), a new decoder path. Even that would leave the encoder starting cold at every
   cut.
2. **Bounded acoustic left overlap was chosen.** Task 2d `commit` is unchanged: 0.5 s hop,
   1.0 s right context, LocalAgreement-2, the same cut placement. Every tail decode, **partials
   and final alike**, starts L s before the cut (clamped at 0). Task 2d's commit errors were in
   committed words too, so overlapping only the final would not have helped.
3. **Stitching is by timestamp.** Decoded words carry absolute times, and a word belongs to the
   tail iff its midpoint is at or after the cut; overlap words are the already-committed text
   and are dropped. There is no text dedupe.

L = 0 is byte-for-byte Task 2d `commit` and ran as a drift control (`t2d._decode_tail`).

**Pre-registered before any Task 2e number** (`hermes_eval.t2e`):
- **Arms.** L ∈ {1, 2, 3} s, plus the L=0 control.
- **Screen subset.** `records[1::4]`, 40 rows: all 7 subsets, en 28 / ru 12, 7 rows ≤ 3 s and
  7 rows > 10 s. It was chosen because it reproduces Task 2d's full-set latency (commit p95 443
  vs 443, redecode 1335 vs 1339).
- **Elimination.** An arm is out if its screen p95 > 500 ms, or its WER Δ > +1.0 pp, or its CI
  low > 0.
- **Retention.** At most one arm.
- **Gate.** `t2d.GATE` and eligibility, unchanged.

| | |
|---|---|
| Run | `eval/runs/20261009T193507Z-t2e-overlap-finalization-9264` — `run.json`, `screen-commit-L{0,1,2,3}.0-t4.{json,jsonl}`, `counters-screen.jsonl`, `analysis.json` (promoted with `git add -f`) |
| Provenance | 2026-10-09 19:35Z, HEAD `8c22264` **dirty** (Task 2e code uncommitted: `t2d.py` `a7cebe28…`, `t2e.py` `dda7bf24…`); FP32 / ORT / sherpa / DLL = Task 2d; 4 threads; QoS high read back (mask 1, state 0) in all four workers; one session per arm, 40/40 rows each |
| Contamination | Pre-flight 6.76 GB available, but Edge stayed open (~2.6 GB); available memory fell to **4.27 GB** during the run (under the 6 GB floor), ~1.4 GB paged in, CPU 81% busy median. **The L=0 control ran p95 753 ms vs Task 2d's 443 on the same 40 rows, with compute p50 232 vs 168 ms. Absolute latencies below are not decision-grade.** |

| 40-row screen | L=0 (control) | L=1.0 | L=2.0 | L=3.0 | Task 2d commit, same rows |
|---|---:|---:|---:|---:|---:|
| release-to-final p50 / p95 ms | 279 / 753 | 336 / 748 | 455 / 866 | 517 / 720 | 190 / 443 |
| in-flight wait p95 / final compute p95 ms | 211 / 584 | 318 / 467 | 368 / 525 | 340 / 444 | 152 / 269 |
| final audio decoded p50 / p95 s (tail p95) | 2.2 / 6.9 (6.9) | 2.8 / 4.7 (3.7) | 3.5 / 6.3 (4.3) | 4.3 / 5.3 (2.6) | 2.2 / 3.7 |
| **WER** (offline 12.34% on these rows) | 29.06 | 20.16 | **17.34** | 18.75 | 24.69 |
| **Δ pp [95% CI]** | +16.7 [+10.5, +24.0] | +7.8 [+4.4, +11.7] | **+5.0 [+1.3, +9.0]** | +6.4 [+2.7, +10.1] | +12.3 [+8.3, +16.6] |
| S / I / D (offline 43 / 19 / 17) | 86 / 46 / 54 | 48 / 51 / 30 | 35 / 47 / 29 | 41 / 47 / 32 | 69 / 42 / 47 |
| en / ru WER (offline 11.99 / 13.82) | 29.4 / 27.6 | 21.1 / 16.3 | 18.4 / 13.0 | 19.9 / 13.8 | 24.0 / 27.6 |
| finals identical to offline | 2 | 7 | 12 | 11 | 2 |
| cuts | 143 | 195 | 217 | 232 | 144 |
| divergences from offline per 100 cuts (within 0.5 s of a cut) | 105 (70) | 45 (35) | 31 (26) | 31 (25) | 91 (74) |
| └ duplicate / drop / hallucination / substitution, per 100 cuts | 10.5 / 23.1 / 9.8 / 26.6 | 15.9 / 8.7 / 2.1 / 8.7 | 12.9 / 6.5 / 2.3 / 4.1 | 12.9 / 7.3 / 1.3 / 3.9 | 11.8 / 27.8 / 8.3 / 25.7 |
| screen decision | control | out (WER; p95 748) | out (WER; p95 866) | out (WER; p95 720) | — |

**Verdict: CPU FINALIZATION NOT RESCUED.** No arm survived the screen, so the 160-row gate was
not run (by pre-registration). **The elimination rests on quality, which is independent of the
latency contamination:** every overlap arm is resolved worse than offline and fails the
unchanged eligibility rule (CI low ≤ 0 and Δ ≤ +0.5 pp) by a wide margin.

**Why overlap is not enough.**
- **Left context works on what it targets.** Boundary substitutions fall ~6×, hallucinated
  fillers ~4–7× and drops ~3× against the control, and Russian returns to offline at L ≥ 2.
- **Duplicates do not fall at all.** They stay at ~13–16 per 100 cuts, and insertions stay at
  2.5× offline.
- **The cause is timestamp disagreement between decodes.** When words abut, the cut sits at
  the next word's onset; a re-decode heard with different context shifts the committed word
  one 80 ms frame later, so its midpoint crosses the cut and it is emitted twice. Example:
  `was` [2.32, 2.48] committed, then `was` [2.40, 2.56] re-emitted, with the cut at 2.48.
- **More cuts, more exposure.** Context-aware partials agree more often, so overlap makes
  *more* cuts (195–232 against 143), each one a stitch.
- **A better stitcher would not close the gap (post-hoc, not used for the decision).** Even
  deleting every cross-cut adjacent duplicate, the best arm (L=2) is still 13.75%, +1.4 pp,
  with deletions at 2× offline (17 → 36).

**Latency, read with the contamination in mind.** Overlap raises latency in proportion to L.
Final compute and the in-flight wait both grow, because every partial now decodes L more
seconds, and median latency rose from 279 ms (control) to 336 / 455 / 517 ms. Scaled by the
control's drift, L=1 might land near 450 ms at p95 on a clean machine, and L ≥ 2 would not. This
does not change the verdict.

**What this establishes.**
1. **On this export, no CPU finalization path is both offline-quality and inside 450 ms.**
   `redecode` keeps quality but has p95 1339 ms (Task 2d). Commit-family policies, with or
   without bounded overlap, lose ≥ 5 pp.
2. **Stitching across independently decoded windows is the failure, not the absence of
   context alone.** A commit-based design would need state continuity, i.e. a cache-aware
   streaming export, rather than more overlap.
3. **The next experiment should be execution-provider acceleration of the full `redecode`
   final.** That is DirectML/WinML, open question #14. Redecode is the only policy that
   preserves quality (159/160 finals identical to offline). Its failure is ~57 ms per
   audio-second of final compute plus the in-flight partial wait (575 ms at p95), and an EP
   attacks the first directly. Cancelling the in-flight partial at release is a cheap,
   orthogonal lever on the second, and should be measured in the same task with its own
   pre-registration. To reach p95 ≤ 450 ms, final compute p95 (863 ms) must fall roughly 2–3×,
   together with the wait.

**Harness changes (committed with the write-up).**
- `t2d._decode_tail`: the tail decode with optional left context. `stream_utterance` and
  `run_stream` take `left_s`; `run_stream` also takes `only` and `tag`. Rows gain `lo` and
  `decoded_s`.
- `src/hermes_eval/t2e.py`: `screen`, `gate`, `worker`, `analyze`. It refuses below 6 GB
  available at start, and `gate` refuses any L that the screen did not retain.
- `tests/test_t2e.py`: stitching, clamping, the straddling word, boundary attribution and the
  selection rule.
- The fake streamer in `tests/test_t2d.py` accepts `left_s`.
- 161 tests pass; ruff and pyright are clean. With L=0 the path is Task 2d's `commit` exactly.

### Offline CPU baseline — 4 threads, HighQoS (frozen for this machine and configuration)

| | |
|---|---|
| Run | `eval/runs/20261007T040840Z-t2d-parakeet-fp32-cpu-190c` — `run.json`, `offline-t4-r{1,2,3}.{json,jsonl}`, `counters.jsonl`, `analysis.json` (written 2026-10-08 by `t2d analyze`; reads only, no decoding). Promoted with `git add -f` |
| Provenance | `t2d sweep --threads 4 --rounds 3 --qos high`, 2026-10-07 04:08–04:13Z, tree clean at `ce9c773` (`t2d.py` sha256 `08fbc40f…`); manifest `public-proxy-v1` sha256 `2b3a46ed…`, 160 rows; FP32 hashes = Task 2c (encoder `3eed7ce4…`); greedy search; on AC; ~8.3 GB available at pre-flight |
| QoS | `high` applied and read back in every round (control mask 1, state 0, priority class unchanged) |
| Rounds | 3 × 160/160 rows; RTF 0.0692 / 0.0685 / 0.0706 → **mean 0.0694, CV 1.5%** |
| Latency | pooled p50 **381 ms**, p95 **970 ms**, p99 1070 ms; median 226 ms at ≤ 3 s audio; p95 409 ms at 4–6 s; fit 79.5 ms + 57.4 ms per audio-second (5 s → 366 ms) |
| Quality | **WER 10.721%** in every round (= Task 2c FP32); transcripts identical across rounds |
| System | P- and E-cores both ~80% busy (the worker is no longer confined to the E-cores); page-in median 0 per row; available memory ≥ 5.5 GB during decoding; 0 fast and 2 slow (> 1.5× median) rows of 480; peak working set 2.74 GB |

**Why 4 threads.** Six HighQoS pilots (`eval/runs/20261007T0*-t2d-pilot-highqos-*`,
local only: a 56-row every-third-utterance subset, round 1, run by an uncommitted pilot script,
each comparison repeated in reversed order) put 4 threads ahead of 2, 3, 5, 6 and 8:
RTF ≈ 0.096 (2), 0.075 (3), **0.068–0.069 (4)**, 0.091–0.094 (5), 0.146 (6), 0.21–0.22 (8).
Beyond 4 threads every core is saturated and decode slows down. The pilots are supporting
evidence only; the frozen figures above come from the full-corpus run. 12 threads was not run
under HighQoS — at 8 it is already 3× slower.

**Why HighQoS is required.** Without it (the 2026-10-06 run below) Windows kept the windowless
worker on the 4 E-cores: RTF 0.42 at 4 threads, about 6× slower. The 0.0694 baseline holds only
with execution-speed throttling opted out. This carries over to the product: the Phase 1
sidecar must opt out too (not yet a decision record — the product mechanism is unmeasured).

**What this does not settle.** These are whole-utterance offline decodes. The p95 of 970 ms is
decode time for the full utterance from scratch; it is not release-to-final latency, which is
what `t2d.GATE` judges. **The streaming verdict is above (FAIL, 2026-10-08).** Both policies
(`redecode`, `commit`) were run against this run directory with:
```
uv run --group asr python -m hermes_eval.t2d stream eval/runs/20261007T040840Z-t2d-parakeet-fp32-cpu-190c --threads 4 --qos high
uv run python -m hermes_eval.t2d analyze eval/runs/20261007T040840Z-t2d-parakeet-fp32-cpu-190c
```
**The streaming command is resume-safe** (2026-10-08). Each row is fsynced as it completes.
Rerunning the same command skips completed utterances and completed policies, and it cuts only
a torn final line (that utterance is redone). It refuses, changing nothing, on a malformed
interior line, a duplicate or unknown id, or a QoS or `t2d.py` hash that differs from an earlier
session of the same policy. Every session is appended to `run.json` as `stream_sessions`: tag,
policy, threads, QoS, start time, rows present, torn bytes cut, git state, `t2d.py` hash. The
sampler cuts a torn line from its own counters file before appending. Streaming metrics,
policies and the gate are unchanged.

A power loss on 2026-10-08 happened after this baseline was written and before any streaming
run started; recovery found no `stream-*` or `counters-stream*` files and every baseline file
structurally valid.

### First attempt — INTERRUPTED (2026-10-06) — diagnostic only


Task 2d asks whether Parakeet TDT v3 **FP32 on the ORT CPU EP** is fit for the Phase 1
interactive path: a bounded thread sweep (Part A), streaming behaviour (Part B), and a latency
gate (Part C). **None of the three is answered.** The run was cut short, and what did finish was
measured under two contaminations that it then diagnosed. **No CPU streaming PASS / MARGINAL /
FAIL decision has been made; no thread configuration is frozen or provisional; DirectML/WinML
is neither deferred nor recommended on the strength of this run.**

| | |
|---|---|
| Partial run | `eval/runs/20261006T194724Z-t2d-parakeet-fp32-cpu-15e4` — `run.json` (pre-flight), `offline-t{4,6,8}-r1.{json,jsonl}`, `counters.jsonl` (PDH, 0.5 s), `NOTE.md`. Committed as diagnostic evidence, ~1.3 MB |
| Pre-flight | tree clean at `4e403e5`; FP32 hashes = Task 2c; ORT 1.28.0 DLL pinned beside sherpa (sha256 `14e18662…`); no stale ASR processes; Balanced plan, on AC; available RAM 1.7–5.0 GB of 15.7 (Edge ~7 GB); topology 4 SMT P-cores = logical 0–7, 4 E-cores = 8–11 |
| Completed | default QoS, round 1 only: **4, 6, 8 threads**, 160/160 rows each |
| Not started | 12 threads; rounds 2–3; every HighQoS worker; both streaming policies |
| Why it stopped | Claude Code's background-shell memory-pressure reaper killed the sweep during the 12-thread load. Not a harness failure |

**Finding 1 — Windows placed the worker on the E-cores.** With power throttling left to the OS
(control mask 0, the state of every Task 2a–2c worker), the windowless console worker ran on
the 4 E-cores: E-cores 100% busy, P-cores at background load (~14–20%) for all 480 rows, at
every thread count. Extra threads only oversubscribed those 4 cores:

| threads (default QoS) | RTF | p50 / p95 | cores busy | E-busy / P-busy |
|---|---:|---:|---:|---:|
| 4 | 0.42 | 2432 / 4508 ms | 3.68 | 100% / ~20% |
| 6 | 0.67 | 3955 / 6955 ms | 3.68 | 100% / ~19% |
| 8 | 0.89 | 5342 / 9031 ms | 3.78 | 100% / ~14% |

This is the likely explanation of Task 2c's "~5× fast regime": stretches where the scheduler
happened to use P-cores. **It is a product issue, not a benchmarking artefact** — the Phase 1
sidecar is also a windowless background process and will get the same treatment unless it opts
out. The harness now can: `--qos high` sets `PROCESS_POWER_THROTTLING_EXECUTION_SPEED` with
state 0 (no priority, affinity or power-plan change) and records the read-back state per worker.
Its effect is **unmeasured**.

**Finding 2 — severe paging contaminated the timing.** The FP32 sidecar peaks at 2.74 GB; with
Edge holding ~7 GB, available memory fell to ~520 MB and each 160-row pass paged in ~1.9–3.8 GB
from disk. Every absolute figure above carries that. **The numbers in the table are diagnostic
only and must not be quoted as Parakeet's CPU latency.**

Untouched by both contaminations: WER is **10.721%** at 4, 6 and 8 threads — Task 2c's FP32
figure exactly; transcripts do not depend on thread count here.

The streaming gate is pre-registered in `t2d.GATE`, fixed before any streaming number existed:
release-to-final p95 ≤ 300 ms PASS (ARCHITECTURE §8 final-ASR budget), ≤ 450 ms MARGINAL (700 ms
end-to-end minus endpoint 150, NLP 50, injection 50; no correction pass per D-0009), else FAIL;
a finalization policy counts only if its WER is not resolved worse than the offline full decode.

Harness changes (checkpoint `ce9c773`): `src/hermes_eval/t2d.py` — `cpu_topology` (P/E split from
`GetLogicalProcessorInformationEx`), a PDH sampler process (per-logical-CPU busy % and
performance %, hard page-ins, available MB, via `PdhAddEnglishCounterW` because `typeperf`
rejects English counter names on this Russian-locale Windows), `set_qos`, the offline sweep
worker, the real-time streaming worker (`redecode` and LocalAgreement-2 `commit` policies,
0.5 s hop, push-to-talk release), and the analysis (per-row counter attribution, regime flags,
latency fit, TTFP / useful-partial / UPWR / word-display lag / finalization decomposition,
paired WER bootstrap vs offline). `tests/test_t2d.py` covers the streaming bookkeeping.

## Task 2f — PROVIDER SELECTED: TEST DIRECTML NEXT; gate pre-registered, not run (2026-10-10)

**The question.** Which execution provider carries D-0017's acceleration experiment: Windows
ML or the ORT DirectML EP? **DirectML, as the measurement vehicle only** (D-0018). Nothing was
installed, changed or benchmarked. The wheels were downloaded to scratch and inspected as zip
archives.

**Evidence, in short** (full detail in `docs/research/T2F-acceleration-plan.md` §2):

- **Windows ML on NVIDIA means DirectML or TensorRT.** Its included EPs are CPU and DirectML
  ("legacy"). Its only NVIDIA catalog EP is `NvTensorRtRtxExecutionProvider`, which is out of
  scope unless DirectML fails.
- **`onnxruntime-windowsml` 1.28.0.202607272323 is ORT 1.28.0 + DirectML 1.15.4.** It reports
  `package_name='onnxruntime-directml'`, and `DmlExecutionProvider` is reachable without the
  Windows ML catalog or app runtime.
- **Standalone `onnxruntime-directml` is frozen at 1.24.4** (2026-03-17), with the same
  `DirectML.dll`.
- **sherpa 1.13.8's prebuilt wheel has DirectML compiled out**, and falls back to CPU with a
  log line. So: direct ORT sessions plus the owned loop.
- **The owned loop as instrumented costs 325 / 741 ms p50 / p95** (Task 2b). A lean
  argmax-only loop is required, and it must be shown equivalent.
- **The graphs** are opset 17 with standard ops only. The encoder has dynamic B and T, and
  612 external initializers in a 2.44 GB `encoder.weights`.
- **This machine** has an Intel UHD + RTX 4050 hybrid, so the NVIDIA adapter must be selected
  explicitly. An inbox `System32\DirectML.dll` 1.15.5 sits alongside the wheel's 1.15.4.

**Pre-registered stages** (all thresholds fixed in the plan §4; `t2d.GATE` unchanged):

| stage | what | pass / early stop |
|---|---|---|
| 0 | lean greedy loop, direct ORT **CPU** EP, 160 rows | 160/160 step-identical to `TdtProbe.greedy`; **≥ 159/160** text parity with Task 2d sherpa offline; eligible WER; **loop p95 ≤ 100 ms**. Else stop, with no GPU timing |
| 1 | provider and device validation | DirectML device with **vendor 0x10DE** selected explicitly; GPU activity shown; loaded `onnxruntime.dll` / `DirectML.dll` recorded; node placement and profiling. Stop if no NVIDIA device, any compute-heavy node on the CPU, or no GPU activity |
| 2 | 40-row `records[1::4]` streaming `redecode`, arms C (CPU) and G (DirectML encoder), G C C G | **stop if G final-compute p95 > 300 ms, speedup < 2.0×**, or G ineligible against C after one `disable_metacommands` retry |
| 3 | 160-row equivalence (G vs C ≥ 155/160, eligible) and 160-row streaming `redecode`, G C G | verdict on the first G session under `t2d.GATE`; second G session within 15%. **G+cancel** reported as a separate variant, never in place of G |

**Next action for this track:** Stage 0. That means the lean loop, the result shim, per-session
providers in `tdt_probe` (defaulting to CPU), and the isolated `.venv-t2f/` environment.

## Next steps — Phase 0

Phase 0 is a **throwaway Python spike, ~1 week** (D-0006). Its purpose is no longer vague:
it exists to settle a specific measurement list that every research memo deferred to it.

### Engineering blocker after Task 2d — finalization architecture / acceleration (not started)

Task 2d (D-0016) leaves no CPU finalization policy that qualifies for Phase 1. The next
engineering task is **not** another model comparison. It is either (a) a finalization design
that is neither a full redecode nor a context-free commit (in-flight cancellation,
overlapped-context commit, a cache-aware export), or (b) acceleration through DirectML/WinML
(open question #14). Each needs its own pre-registered gate, and nothing selects between them
yet. **Task 2e (2026-10-09) closed lever (a) for acoustic overlap: CPU FINALIZATION NOT
RESCUED.** Bounded left overlap cannot hold offline WER (best +5.0 pp). The next experiment is
**(b): execution-provider acceleration of the full `redecode` final**, with in-flight
cancellation measured alongside, under its own pre-registered gate. A cache-aware export
remains the only commit-family route left. **Task 2f (2026-10-10, D-0018) chose the vehicle and
pre-registered that gate: DirectML via `onnxruntime-windowsml` 1.28.0, isolated, in stages
0–3.** The next step is Stage 0, the lean-loop CPU parity check (§ Task 2f). Task 1b below still needs a human with a
microphone and is independent of this.

### THE NEXT ACTION — record the personal eval set (Task 1b)

**Task 2a is done, so this is now the top of the queue.** It unblocks every differentiator,
and no amount of proxy-set work retires it. Task 2a's own conclusion points here: Parakeet
leads on the proxy set, but the proxy set cannot see F-WER, E-WER, dev-speak,
code-switching, ITN or the real microphone, so the backend decision cannot be made without
this.

**It needs a human with a microphone, not a coding session.** Everything that could be done
without one has been.

The harness half of Task 1 is done, and the public proxy set now covers the part of the data
half that does not need a microphone. **The rest still needs one.** Every differentiator —
dev-speak, code-switching, ITN, punctuation and casing, the real room — is measurable only
against the personal set.

Concretely:

1. Record **30 utterances** during real use, 16 kHz mono 16-bit WAV, one file per
   utterance, into `eval/datasets/personal/audio/`.
2. Follow `eval/datasets/personal/RECORDING.md` — it has the coverage split (8 dev_speak,
   6 prose, 6 code_switch, 5 itn, 5 adversarial) and the **transcribe-twice-and-reconcile**
   discipline, which is not optional.
3. Annotate `entities` and `itn_slots` as you go. E-WER is only as good as that
   annotation, and E-WER is the guard that stops an aggregate win from hiding rare-word
   damage.
4. Start from `manifest.template.jsonl`; run
   `uv run hermes-eval validate eval/datasets/personal/manifest.jsonl` until it is clean.
5. Sanity-check the harness against the real set with
   `uv run hermes-eval run --manifest eval/datasets/personal/manifest.jsonl --adapter perturb:seed=1`
   — the numbers are meaningless, but a real manifest exercising the real code path is not.

This is a recording session, not a coding session. It needs a human with a microphone.

### Deferred out of the harness, deliberately

- **UPWR/UPSR** (partial-hypothesis stability, arXiv 2006.01416). Needs a backend that
  emits partial hypotheses; there is nothing to measure until one exists.
- **The vendored, version-pinned Whisper `EnglishTextNormalizer`** for the secondary
  legacy-comparable score. Needs a pinned third-party source; it is a secondary number,
  never the headline.
- ~~**Resource sampling** (`nvidia-smi`, `Get-Counter` per R6).~~ **Landed 2026-09-27**
  with the first real models — `src/hermes_eval/resources.py`, enabled by
  `hermes-eval run --resources`. Per-process counters, not system free memory, because on
  a laptop with a browser open the system figure measures the browser. Peak VRAM is null
  rather than zero when unattributable. The cold-vs-warm-start discipline is in the
  adapter: model load, model hash and warm-up are timed separately from decode, and
  warm-up is two passes over a fixed synthetic signal, never dataset audio.
- A **CI canary manifest and checked-in baselines**. Premature while the only dataset is
  synthetic — `hermes-eval compare` already exits non-zero on a regression, so the gate
  itself is ready.

One harness detail worth remembering: WER can come out *above* F-WER on the same run,
because `basic` normalization splits `kube-system` into two tokens while `raw` keeps it as
one. Different denominators, not a bug.

**Task 2 — the measurement list.** Every one of these is scored through
`hermes-eval`; none of them is worth running before Task 1b exists. In rough priority
order:

1. ~~**Can per-token logits be reached from an ONNX export?** (`SYNTHESIS.md` §5.1.)~~
   **Answered for Parakeet, 2026-10-06 (Task 2b, D-0014):** yes. Confidence via sherpa's
   API; N-best via a small owned Python loop. Exit criterion met. Untested for Whisper.
2. fp32 vs int8 WER on our own audio, for whichever backend we test. **No measured pair exists
   anywhere** — circulating claims trace to content farms.
   **Answered for Parakeet on the proxy set, 2026-10-06 (Task 2c, D-0015):** FP32 −2.57 pp
   [−3.94, −1.32]; FP32 preferred. Re-check on the personal set; untested for Whisper.
3. **Parakeet TDT v3 vs Whisper large-v3-turbo on the personal set: F-WER, E-WER,
   latency.** The two Task 2a survivors; Nemotron was eliminated 2026-09-28. This is the
   measurement that picks the production backend, and the proxy set cannot substitute for
   it — it cannot compute either headline metric.
4. int8-vs-fp32 joiner emission *timestamp* drift (WER is insensitive to this failure mode).
5. Thread-count sweep on the P/E-core split — `-t 4/6/8/12`.
   **Answered for Parakeet FP32 on this machine, 2026-10-07 (Task 2d): 4 threads, HighQoS,
   frozen** — RTF 0.0694 over three clean full-corpus rounds; 2/3/5/6/8 slower in HighQoS
   pilots. Without HighQoS the worker is confined to the E-cores. See § Task 2d.
6. Confidence signal quality on **accented and code-switched** speech — the gap that
   matters most for our user. *Accented English measured on the proxy set by Task 2b
   (AUROC 0.863); code-switched speech and the user's own voice still need Task 1b.*
7. Process-boundary (IPC + serialization) latency against the 700 ms p95 budget.
8. Whether biasing actually moves E-WER without raising false insertions on a no-bias-term
   control set.

**Checkpoint 0 is unchanged:** hotkey → speak → text lands in Notepad. Any latency.

**Two early spikes that are cheap and de-risk Phase 1**, worth doing whenever blocked on
Phase 0: transparent + click-through + always-on-top on WebView2/Win11 with a throwaway
window; and `embed-manifest` injecting `uiAccess="true"` through Tauri's bundler (~half a day).

## Open questions

Settled since the last update: **#10 (Pynini/OpenFst on Windows) — closed by D-0008.**

1. **Can an ONNX export supply token-level confidences and an N-best list?** Highest-value
   unknown in the plan. If not, the fix is writing our own transducer decode loop in Rust —
   substantial work for a Rust beginner. Phase 0 exit criterion.
   **Narrowed 2026-09-27, not closed.** sherpa-onnx's result objects expose
   `ys_log_probs` / `tokens` / `timestamps` (offline) and `ys_probs` / `lm_probs` /
   `context_scores` (online) over these exact ONNX exports. So *a* per-token probability is
   reachable from an ONNX artifact, through a transducer decode loop that already exists in
   C++. What is still unverified is whether the **full per-step distribution** is reachable —
   R8's entropy method needs the distribution, not just the emitted token's log-prob — and
   whether N-best comes out of `modified_beam_search`. Both are cheap to test next.
   **Static half answered 2026-10-06 (Task 2b):** the full distribution is in the export
   but not reachable through any released sherpa API; N-best is computed by
   `modified_beam_search` and discarded.
   **CLOSED 2026-10-06 by Task 2b — verdict A, D-0014.** For Parakeet: token confidence via
   sherpa's API (emitted-token prob, AUROC 0.884, no full-distribution signal better by more
   than 0.005); N-best via a small Hermes-owned Python beam loop. No Rust decoder needed in
   Phase 1.
2. **Is the confidence signal usable on accented/code-switched speech?** Every published
   number is LibriSpeech clean read speech. Our user is neither.
   **Half-answered 2026-10-06 (Task 2b):** on accented English (EdAcc, 94 errors) Parakeet's
   emitted-token prob reaches AUROC 0.863 [0.815, 0.910], ECE 0.037, mildly overconfident.
   Code-switched speech and the user's own voice remain unmeasured — Task 1b.
3. **CUDA/cuDNN redistribution** — needs a direct EULA read before any CUDA-in-installer work.
   DirectML is the default until then — but see #14: DirectML's own status has changed.
   *2026-10-10 (D-0018):* TensorRT-RTX, CUDA's nearest relative here, stays out of scope
   unless DirectML fails Task 2f.
4. **universal-ctags is GPL-2.0-or-later** — legal read before bundling the binary. Subprocess
   invocation differs from linking, but that is not a question to settle by inference.
5. **espeak-ng / `phonemizer` are GPL-3.0**, and `phonemizer` loads `libespeak-ng` via ctypes
   (dynamic linking, not arm's-length). Avoid in any shipped path pending a legal read.
   `piper-plus-g2p` (MIT) is the clean Rust-native alternative.
6. `uiAccess` through Tauri's bundler — unverified; `embed-manifest` 1.5.1 is the candidate.
7. Transparent + click-through + always-on-top HUD on WebView2/Win11 — unverified.
8. Process-boundary latency inside the 700 ms p95 budget — unmeasured.
9. ~~Dataset licences: Common Voice post-migration terms, TED-LIUM, CHiME, Earnings-21/22.~~
   **Closed 2026-09-27** for everything the proxy set touches; see
   `eval/datasets/public-proxy-v1/LICENSES.md`. Common Voice: still CC0, but exclusively via
   Mozilla Data Collective behind an account and terms acceptance since Oct 2025 — excluded on
   *access*, not licence. Golos: licence PDF read in full — CC BY-SA 4.0 reword, attribution
   plus ShareAlike, **no non-commercial clause**, and no speaker IDs published at all.
   Earnings-22: `LICENSE.md` covers transcripts only, **audio licence unstated** — rejected.
   TED-LIUM 3: CC BY-NC-ND. CS-FLEURS: CC BY-NC. GigaSpeech unusable. EdAcc verified.
10. **No Slavic-English code-switching corpus found** — re-verified 2026-09-27 and now sharper.
    CS-FLEURS has `cs_rus_eng` and `cs_ukr_eng`, but **only in its `mms` subset, which is
    concatenative TTS**; its real-human `read` subset covers `rus` but not `ukr`, and the whole
    dataset is CC BY-NC 4.0. Synthetic code-switch audio is not an acceptable substitute.
    Collect our own; say so in any published methodology.
11. Nemotron 3.5 multilingual carries `openmdw-1.1`, **a different licence from its English
    sibling** — verify separately before relying on it.
12. **Corrected 2026-10-06:** PR #2897 (full-vocabulary log-probs) was **closed unmerged**,
    and 1.13.8 is the latest release. What 1.13.8 has is `ys_log_probs` — the emitted
    token's log-prob only. The resolution recorded below mistook one for the other.
    ~~sherpa-onnx `token_log_probs` (PR #2897) merge/release status is ambiguous~~ —
    **resolved 2026-09-27**: sherpa-onnx 1.13.8 exposes `ys_log_probs` on
    `OfflineRecognitionResult` and `ys_probs` on `OnlineRecognizerResult`, observed
    directly on the installed wheel. `rule_fsts` / `HomophoneReplacerConfig` semantics
    remain unconfirmed. Note this now matters more than it did: sherpa-onnx is the
    screening harness, even though R5's objection to shipping it from Rust still stands.
13. Model licensing audit still incomplete for Kyutai, FireRedASR, Granite Speech, Canary-Qwen,
    SenseVoice.
14. **Is DirectML still the right default execution provider?** ONNX Runtime's docs now say
    new feature development has moved to **WinML**; sherpa-onnx has no prebuilt DirectML
    wheels; and dynamic-int8 graphs are what the DML EP handles worst. D-0011's *reasons*
    for DirectML still hold, its upstream trajectory does not. Raised 2026-09-27 by Task 2a.
    **Raised in priority 2026-10-08 (Task 2d, D-0016):** the CPU EP fails the streaming gate
    for Parakeet FP32, so acceleration is now one of the two levers against the finalization
    blocker. Still unmeasured.
    **Narrowed 2026-10-10 (Task 2f, D-0018), not closed.** For the *next experiment*, DirectML
    is the vehicle. Windows ML's GPU options on NVIDIA are its "legacy" included DirectML EP or
    TensorRT-RTX, and `onnxruntime-windowsml` 1.28.0 supplies the same DirectML EP at the
    baseline's ORT version. The int8 concern no longer applies, because Parakeet is FP32
    (D-0015). The *shipping* choice is still open: DirectML is in sustained engineering, while
    Windows ML (and TensorRT-RTX within it) is where Microsoft's development has gone.
15. **Does any candidate reach the 700 ms p95 budget on this hardware at all?** Now measured
    for all three: Parakeet p95 5707 ms, Whisper 22343 ms, Nemotron 40029 ms, on the CPU EP
    at 4 threads, whole-utterance decode. The budget assumes streaming decode overlapped with
    speech, which none of these runs did — so this is still not a fair comparison against it,
    and making it one is its own experiment. What the screening *did* settle is that only
    Parakeet is even in range: it is the sole candidate faster than real time on the CPU EP
    (RTF 0.47, slower than real time on 2 of 160 utterances, against 160 of 160 for both
    others). A backend that cannot keep up with the audio cannot overlap with it either.
    **CPU answer for Parakeet FP32, 2026-10-08 (Task 2d): no.** With streaming partials
    overlapped with speech, the only quality-preserving policy (`redecode`) has
    release-to-final p95 1339 ms against a 450 ms allowance for ASR finalization.
16. **Is Whisper's inconsistent formatting a property of the model or of this export?**
    Raised 2026-09-28 by Task 2a. Through the sherpa-onnx int8 export at `greedy_search`,
    ~a quarter of Whisper's outputs came back with no punctuation and no casing, where
    Parakeet formatted 154 of 158. Whisper's formatting is known to be prompt-sensitive and
    this run did not control the decoder prompt tokens sherpa supplies. It matters because
    F-WER is the headline metric and unformatted output fails it outright — but it cannot be
    settled on the proxy set, whose references are unformatted anyway.

17. **How unstable is the int8 Parakeet export, and is fp32 better?** Raised 2026-10-06 by
    Task 2b. A 1e-7 relative perturbation of the features flips the transcript; float32
    reduction-order differences alone changed the greedy text on 33 of 160 utterances, with
    no WER bias (Δ −0.31 pp [−0.71, +0.11]); first divergences sit at near-tie margins
    (median 0.13 nats). Hypothesis, untested: dynamic int8 activation quantization turns sub-ULP
    input noise into rounding flips that propagate through 24 encoder layers. It puts a
    noise floor under any confidence value, means two correct implementations of the same
    decode will not agree byte-for-byte (a hazard for the Phase 3 Rust port's parity
    testing), and folds into Task 2 item 2 (fp32 vs int8). Testing it needs the fp32 export,
    which is a model addition and outside Task 2b's scope.
    **CLOSED 2026-10-06 by Task 2c (D-0015): confirmed, and fp32 is better.** FP32 parity with
    a direct-ORT decode is 159/160 (int8 127/160), inaudible dither flips 8/160 vs 30/160, and
    WER drops 2.57 pp. Both are bit-deterministic run to run — the problem was input
    sensitivity, not nondeterminism.

## Decisions (full text in `DECISIONS.md`)

- **D-0001** Windows first
- **D-0002** Local-first inference, optional cloud
- **D-0003** Python prototype then Rust core *(partially superseded by D-0006)*
- **D-0004** Flat, purpose-named docs
- **D-0005** Workflow contracts frozen day one, engine deferred past Checkpoint 1
- **D-0006** Rust shell from Phase 1; Python as inference sidecar behind a versioned protocol
- **D-0007** Injection is precondition-checked, not read-back-verified
- **D-0008** No Pynini/OpenFst at runtime; ITN is a hand-written rule cascade
- **D-0009** No LLM correction pass in Phase 1; confidence highlighting instead
- **D-0010** Voice actions: Tier 0/1 only; the process boundary is the safety boundary
- **D-0011** ONNX Runtime is the substrate; the ASR model is decided by measurement
- **D-0012** Public proxy eval set stands in for the personal set, and never replaces it
- **D-0013** Task 2a eliminates Nemotron; Parakeet TDT v3 is the front-runner, Whisper the fallback
- **D-0014** Task 2b keeps the confidence / N-best contract; N-best from an owned Python decode loop
- **D-0015** Task 2c: Parakeet ships as the FP32 export; INT8 is the low-memory fallback
- **D-0016** Task 2d: Parakeet FP32 fails the CPU streaming gate; 4 threads frozen, HighQoS required
- **D-0017** Task 2e: overlap-based CPU finalization ruled out; accelerate full redecode next
- **D-0018** Task 2f: test DirectML next as the controlled acceleration vehicle; shipping provider undecided

## Standing instructions

- **Commit only on request.** Task 2a is committed in full as of 2026-10-05: the
  one-resident-recognizer support, `--decode-order`, their tests, the write-ups, D-0013 and
  the SYNTHESIS §5/§11 corrections.
- **Task 2b is committed** (`phase0: characterize Parakeet confidence and N-best`): the
  write-up, D-0014, the SYNTHESIS / T2A reconciliation, `supplement`, and the run
  `eval/runs/20261006T033722Z-t2b-parakeet-confidence-27dc` (`run.json`, `raw.jsonl`,
  `analysis.json`, `supplement.json`). Rows 1–91 record `013217b` dirty — the instrument
  was then uncommitted; it was committed unchanged in `87ec846`, where rows 92–160 ran.
- **Task 2c is committed** (`phase0: prefer Parakeet FP32 over INT8`): the write-up, D-0015,
  `t2c.py`, the `TdtProbe` model-dir parameters, and the run
  `eval/runs/20261006T055203Z-t2c-parakeet-int8-vs-fp32-01d0` (`run.json`, the four per-arm
  `{arm}-p{n}.json` + `-sherpa.jsonl`, the pass-1 `-perturb.jsonl` / `-probe.jsonl`,
  `analysis.json` — ~1.8 MB, ~95 min of compute). Collected at `bdbca28` dirty (`t2c.py` then
  uncommitted); the committed `t2c.py` reproduces `analysis.json` byte-for-byte. Model files
  stay in `models/` (gitignored).
- **Task 2d is checkpointed, not complete** (`phase0: checkpoint CPU streaming benchmark
  harness`): `t2d.py`, `tests/test_t2d.py`, this section, and the partial diagnostic run
  `eval/runs/20261006T194724Z-t2d-parakeet-fp32-cpu-15e4` with its `NOTE.md`. Collected at
  `4e403e5` dirty (`t2d.py` then uncommitted; the offline worker and sampler are unchanged in
  the committed file apart from the added `qos` argument). It is evidence for two findings, not
  a Task 2d result.
- **Task 2d offline baseline is committed** (`phase0: persist CPU baseline and harden streaming
  resume`): the run `eval/runs/20261007T040840Z-t2d-parakeet-fp32-cpu-190c` with its
  `analysis.json`, the resume-safe streaming worker and its tests, and this section. Collected
  at `ce9c773` clean. The HighQoS pilot runs are not committed.
- **Task 2d streaming result is committed** (`phase0: characterize Parakeet FP32 CPU
  streaming`): `stream-{redecode,commit}-t4.{json,jsonl}`, `counters-stream-t4.jsonl`, the
  `stream_sessions` entries in `run.json`, the regenerated `analysis.json`, D-0016,
  `docs/research/T2D-cpu-streaming.md`, and this section. Collected at `f088767` clean (see the
  provenance note on the commit session's `dirty` flag above).
- **Task 2e is committed** (`phase0: rule out overlap-based CPU finalization`): `t2e.py`,
  `t2d._decode_tail` / `left_s`, `tests/test_t2e.py`, D-0017,
  `docs/research/T2E-finalization.md`, the SYNTHESIS reconciliation, this section, and the
  run `eval/runs/20261009T193507Z-t2e-overlap-finalization-9264` (`run.json`,
  `screen-commit-L{0,1,2,3}.0-t4.{json,jsonl}`, `counters-screen.jsonl`, `analysis.json`).
  Collected at `8c22264` dirty (Task 2e code then uncommitted, committed unchanged).
- **Task 2f provider selection is committed** (`phase0: select DirectML acceleration
  experiment`): D-0018, `docs/research/T2F-acceleration-plan.md` with the pre-registered
  stages, this section, and the SYNTHESIS / open-question #14 notes. It is documentation
  only: no code, no run, no package installed.
- **Task 2a runs:** `run.json` + `predictions.jsonl` are committed for
  `eval/runs/20260927T022919Z-t2a-parakeet-tdt-v3-aff8`,
  `eval/runs/20260927T031249Z-t2a-nemotron-stream-en-560ms-c9f4` and
  `eval/runs/20260928T002321Z-t2a-whisper-large-v3-turbo-c4c0`. All three record
  `git.dirty: true`: Parakeet and Nemotron ran on `a2bbbf3` plus the Task 2a adapter work
  committed in `fa56244`; Whisper ran on `fa56244` plus the resident/decode-order work
  committed with this checkpoint. Its decode-sequence sha256 (`d0b0bc90…`) reproduces from
  the committed code.
- **`eval/datasets/public-proxy-v1/manifest.jsonl` and `build.json` are the artifacts; the
  audio is not.** Never commit third-party audio — two source corpora carry ShareAlike.
- `eval/runs/` is gitignored. Promote a run deliberately with `git add -f` when it belongs
  in the record; baselines change only by an explicit reviewed edit, never silently.
- No pipeline change lands without an eval delta. F-WER is the headline; latency p95 is a
  hard gate.
- Deltas smaller than the bootstrap CI are noise, not wins.
