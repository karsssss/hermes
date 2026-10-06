# Current

The only doc expected to change every session. Read this first when resuming work.

**Last updated:** 2026-10-06

## Where we are

**Research is complete.** R1–R9 all landed, were verified on disk, and have been synthesized
centrally into `docs/SYNTHESIS.md`, which is now the current decision document. Five new
decisions (D-0007…D-0011) were recorded, and six corrections were applied to
`ARCHITECTURE.md`, `BENCHMARKS.md` and `CLAUDE.md`.

**Phase 0 has started. The evaluation harness exists and passes its own tests.**
`uv` is installed; `pyproject.toml`, `src/hermes_eval/` and `eval/` are on disk. 122 tests,
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

**Task 2b (Parakeet confidence / N-best architecture gate) is INTERRUPTED at 91/160.** The
collection was killed by Claude Code's memory-pressure reaper while the session was idle —
not a failure of the run. Everything collected is on disk and resumable; nothing has been
recomputed or re-run. The static half of the question (what the export and sherpa-onnx
expose) is **settled**; the empirical half (how good each signal is) has **PRELIMINARY**
numbers only. **No verdict has been issued.** See **§ Task 2b — INTERRUPTED** below.

**No audio capture, no Rust.** That is deliberate and unchanged. There is now ASR, but only
as a measurement harness: `src/hermes_eval/asr_sherpa.py` exists to score candidates, not to
ship.

## Read order for a fresh session

1. `CLAUDE.md` — invariants and vocabulary
2. **`docs/SYNTHESIS.md`** — the decision document; supersedes `ARCHITECTURE.md` where they
   disagree
3. `docs/DECISIONS.md` — D-0001…D-0013
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
  plan. N-best would come from `decoding_method="modified_beam_search"`, untested. With the
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

## Task 2b — INTERRUPTED at 91/160 (2026-10-06)

Task 2b asks whether the ONNX / sherpa-onnx / ORT path can supply useful token confidences
and N-best **without Hermes owning the transducer decode loop** (SYNTHESIS §5.1, D-0011's
Phase 0 exit criterion, open question #1). Model: Parakeet TDT 0.6B v3 int8 only. No models,
datasets or fine-tuning added. **No verdict yet — it waits for the full 160.**

### Run state — verified 2026-10-06

| Check | Result |
|---|---|
| Run directory | `eval/runs/20261006T033722Z-t2b-parakeet-confidence-27dc` (`run.json`, `raw.jsonl`) |
| Rows present | **91 valid, 91 unique**, every row complete, exactly manifest rows 1–91 in order |
| Remaining | 69, starting at `pp1-librispeech_test_clean-000101` |
| Manifest identity | sha256 `2b3a46ede2700f30479a218abcdf0f3d55d12c2610dfeb82575e0595c9d7053e` — matches `run.json`, matches Task 2a, file untouched since `a2bbbf3` |
| Model identity | combined sha256 `d0a44f3cb58043af…` — identical to the Task 2a Parakeet run |
| Code that produced the rows | `t2b.py` / `tdt_probe.py` last modified before the run started and not changed in any way that affects a row since; `run.json` records `013217b`, `dirty: true` (the instrument was uncommitted then) |
| Bugged earlier run | `…-t2b-parakeet-confidence-9374` (entropy-normalization bug, below) **deleted**; not in `eval/runs/` |
| Resume | skips completed ids before any audio is read — completed rows are never recomputed; verified on a byte copy of the real `raw.jsonl` (91 ids, file unmodified). Hardened at this checkpoint: a torn trailing line from a mid-write kill is cut before appending, duplicate ids refuse to resume, and each resume is appended to `run.json["resumes"]` |

**Resume command** (≈30 min, ~25 s per utterance; close memory-heavy apps first):

```
uv run --group asr python -m hermes_eval.t2b collect --resume eval/runs/20261006T033722Z-t2b-parakeet-confidence-27dc
uv run python -m hermes_eval.t2b analyze eval/runs/20261006T033722Z-t2b-parakeet-confidence-27dc
```

If the reaper keeps firing, start Claude Code with `CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP=1`.
`analyze` is stdlib-only and takes ~4 min at 2000 resamples.

**The run itself is not committed** (`eval/runs/` is gitignored; an incomplete run is not a
record). It will be force-added with the T2B write-up once complete, as Task 2a's were.

**Coverage of the 91 rows is uneven:** all 50 accented_en, all 20 Russian (ru_clean,
ru_command, ru_farfield), 10 noise, 10 reverb — and **1 general_en**. General English is
effectively unmeasured until the run is resumed.

### The instrument (committed at this checkpoint)

- `src/hermes_eval/tdt_probe.py` — **a measurement instrument, not a shipping decoder.** A
  line-for-line Python/ORT port of sherpa-onnx v1.13.8's TDT greedy and modified-beam
  decoders, recording what sherpa computes and discards: the full per-step token and
  duration distributions, top-5 alternatives per emitted token, and every beam hypothesis
  with its score. Features via `kaldi-native-fbank==1.22.3`, the exact version sherpa 1.13.8
  compiles in.
- `src/hermes_eval/confidence_eval.py` — stdlib-only scoring: WER-unit labelling, AUROC, AP,
  recall@k, ECE, utterance-level paired bootstrap (2000 resamples, seed 20260926).
- `src/hermes_eval/t2b.py` — `collect` (two sherpa arms + the probe) and `analyze`.
- `pyproject.toml` — the `asr` group gains `kaldi-native-fbank==1.22.3`.
- `tests/test_confidence_eval.py` — metrics, labelling, measures, resume.

### Static findings — ESTABLISHED (independent of the interrupted run)

1. **The export exposes everything.** The joiner outputs raw logits `[…, 8198]` = 8193 tokens
   (incl. blank, id 8192) + **5 TDT duration logits** (0–4 frames), every step. The full
   per-step token distribution *and* the duration distribution are in the artifact.
   Encoder `audio_signal [B,128,T]` → `[B,1024,T']`; the decoder is a 2-layer 640-d LSTM
   prediction net with explicit state in and out. Nothing is hidden by the ONNX export.
2. **sherpa-onnx 1.13.8 exposes, offline, through both Python and the C API**
   (`SherpaOnnxOfflineRecognizerResult`): `tokens`, `timestamps`, `durations`, and
   `ys_log_probs` = log-softmax over the token head (incl. blank, excl. durations) of the
   **emitted token only**, i.e. max-prob confidence. Blank steps' probabilities and the
   duration distribution are computed and discarded.
3. **No full distribution, no sequence score, no N-best — through any released API.**
   R8's PR #2897 ("Vocabulary Log Probabilities API") was **closed unmerged**; 1.13.8 is the
   latest release (2026-09-10). `T2A-screening.md`'s line "on the installed 1.13.8 wheel, it
   is there" conflated it with `ys_log_probs` and is wrong; to be corrected in the T2B
   write-up.
4. **N-best is computed and thrown away.** `modified_beam_search` genuinely runs for TDT
   (differed from greedy on 15/40 sampled utterances) and keeps `max_active_paths`
   hypotheses, but `OfflineTransducerDecoderResult` holds one hypothesis and the decoder
   returns only the best. Its TDT beam also takes the argmax duration (no duration
   branching), never merges identical prefixes (so the internal list carries
   alignment-only duplicates), and compares scores of hypotheses sitting at different
   frames. Getting N-best needs either a sherpa C++ patch or owning the loop.
5. **Owning the loop is small.** The greedy TDT loop is ~60 lines over three ORT sessions;
   the Python port costs **~0.06× real time** on top of the encoder (beam-4 ~0.23×, beam-8
   ~0.37×), measured on 91 rows. Phase 1 decodes in the Python sidecar (SYNTHESIS §4), so it
   would not be a Rust task in Phase 1.
6. **The int8 export is numerically chaotic — new, see open question #17.** A 1e-7 relative
   perturbation of the input features changed the transcript; a single-ULP change to one
   feature value did not. The probe and sherpa run the same algorithm on features that differ
   only in float32 reduction order (numpy vs Eigen), and on 91 rows: greedy text identical on
   **68/91**, beam-4 best identical on 57/91; on identical texts the emitted-token log-prob
   differs by median 0.0003, p95 0.059, max 0.75 nats. WER is unbiased by it (sherpa 19.08%,
   probe 18.81%). Bit-parity with sherpa is therefore **unattainable by porting**, and the
   comparison is designed around that: every signal is compared on the *same* (probe)
   hypothesis, and sherpa's native signal is scored separately on its own hypothesis.

**A bug of ours, fixed before the current run.** NeMo's exp-normalized Tsallis-1/3 underflows
over 8193 classes (H_max ≈ 609, so a *confident* step scores ≈e⁻⁶⁰), and the first
collection rounded signals to 6 decimals, collapsing most words into ties. The current run
stores linear-normalized entropies (rank-identical under min aggregation) and **no rounding
on any signal**. The bugged run was discarded, never analyzed in full.

### PRELIMINARY — 91/160 rows, NOT conclusions

**Nothing in this subsection may be quoted as a Task 2b result.** Coverage is uneven
(general_en n=1) and the full run may move any of it. Unit = `basic`-normalized hypothesis
word (the WER unit); AUROC = separation of correct from incorrect words; 95% CI by
utterance-level bootstrap; Δ is paired against `maxprob_min`, the signal sherpa already
exposes. Raw output: scratch analysis of a copy, not written into the run directory.

| signal (word = min over its tokens) | needs | overall AUROC | accented_en | russian | noise | reverb |
|---|---|---:|---:|---:|---:|---:|
| sherpa native `ys_log_probs`, its own hyp | sherpa API | 0.863 [0.826, 0.899] | 0.863 | 0.984 | 0.856 | 0.834 |
| `maxprob_min` (same quantity, probe hyp) | sherpa API | 0.859 [0.822, 0.893] | 0.856 | 0.981 | 0.847 | 0.840 |
| `gibbs_min` (Shannon entropy) | distribution | 0.861, Δ +0.002 [−0.003, +0.007] | 0.856 | 0.991 | 0.855 | 0.842 |
| `tsallis_min` α=1/3 (R8 §D's best) | distribution | 0.822, Δ **−0.036 [−0.070, −0.009]** | 0.825 | 0.966 | 0.780 | 0.727 |
| `margin_min` (top1 − top2) | distribution | 0.845, Δ −0.014 [−0.020, −0.007] | 0.845 | 0.959 | 0.821 | 0.828 |
| blank-inclusive Tsallis | distribution | 0.806, Δ −0.052 | 0.811 | 0.956 | 0.755 | 0.710 |
| TDT duration confidence | distribution | 0.664, Δ −0.194 | 0.627 | 0.739 | 0.680 | 0.768 |

(Rényi-1/3 is rank-identical to Tsallis-1/3 under min aggregation — both are monotone in
Σp^α — so it is not listed separately. Russian has only 7 erroneous words in 98; its
AUROCs are high and wide.)

Provisional reading: on this model, **the emitted-token probability sherpa already returns
separates errors as well as anything the full distribution offers**; Gibbs entropy ties it;
Tsallis-1/3 — R8 §D's best LibriSpeech configuration — is *worse*, CI clear of zero overall.
Flagging the lowest-confidence 10% of words catches ~51% of errors overall (accented 49%).
The product of token probabilities is near-calibrated in aggregate as P(word correct)
(ECE 0.038; mean P 0.897 vs accuracy 0.892). Deletions (128 overall) are invisible to any
word-level confidence by construction.

N-best (probe beam = sherpa's algorithm with all hypotheses kept), PRELIMINARY: beam-4 best
vs greedy WER Δ −0.14 pp [−1.32, +1.07] — noise; **oracle WER 16.31% vs greedy 18.81%** —
the alternatives carry real headroom; 69% of utterances have a lexically distinct
alternative at K=4. Beam-8's best is *worse* than greedy (+2.0 pp [−0.06, +4.53]),
consistent with the cross-frame score comparison in static finding 4. Sequence level: mean
emitted-token log-prob (sherpa-reachable) tracks utterance WER best (Spearman 0.70; AUROC
0.82 for "has any error").

### What is still owed

Resume to 160, re-analyze, write `docs/research/T2B-confidence-nbest.md` (including the
T2A correction above), then issue exactly one verdict — A keep / B weaken / C architecture
change — naming which `FinalTranscript` fields are supportable. DECISIONS.md changes only if
the full evidence changes an existing assumption; D-0009's "entropy-based word confidence"
is the one these preliminary numbers put in question. **No verdict has been drawn from the
preliminary numbers.**

## Next steps — Phase 0

Phase 0 is a **throwaway Python spike, ~1 week** (D-0006). Its purpose is no longer vague:
it exists to settle a specific measurement list that every research memo deferred to it.

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

1. **Can per-token logits be reached from an ONNX export?** (`SYNTHESIS.md` §5.1.) This is an
   explicit Phase 0 exit criterion. If no, Phase 1 scope changes materially — we would have to
   run the transducer decode loop ourselves.
2. fp32 vs int8 WER on our own audio, for whichever backend we test. **No measured pair exists
   anywhere** — circulating claims trace to content farms.
3. **Parakeet TDT v3 vs Whisper large-v3-turbo on the personal set: F-WER, E-WER,
   latency.** The two Task 2a survivors; Nemotron was eliminated 2026-09-28. This is the
   measurement that picks the production backend, and the proxy set cannot substitute for
   it — it cannot compute either headline metric.
4. int8-vs-fp32 joiner emission *timestamp* drift (WER is insensitive to this failure mode).
5. Thread-count sweep on the P/E-core split — `-t 4/6/8/12`.
6. Confidence signal quality on **accented and code-switched** speech — nobody has measured
   this, and it is the gap that matters most for our user.
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
   `modified_beam_search` and discarded. Whether that matters is the empirical half,
   interrupted at 91/160 — see § Task 2b. **Verdict pending.**
2. **Is the confidence signal usable on accented/code-switched speech?** Every published
   number is LibriSpeech clean read speech. Our user is neither.
3. **CUDA/cuDNN redistribution** — needs a direct EULA read before any CUDA-in-installer work.
   DirectML is the default until then — but see #14: DirectML's own status has changed.
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
15. **Does any candidate reach the 700 ms p95 budget on this hardware at all?** Now measured
    for all three: Parakeet p95 5707 ms, Whisper 22343 ms, Nemotron 40029 ms, on the CPU EP
    at 4 threads, whole-utterance decode. The budget assumes streaming decode overlapped with
    speech, which none of these runs did — so this is still not a fair comparison against it,
    and making it one is its own experiment. What the screening *did* settle is that only
    Parakeet is even in range: it is the sole candidate faster than real time on the CPU EP
    (RTF 0.47, slower than real time on 2 of 160 utterances, against 160 of 160 for both
    others). A backend that cannot keep up with the audio cannot overlap with it either.
16. **Is Whisper's inconsistent formatting a property of the model or of this export?**
    Raised 2026-09-28 by Task 2a. Through the sherpa-onnx int8 export at `greedy_search`,
    ~a quarter of Whisper's outputs came back with no punctuation and no casing, where
    Parakeet formatted 154 of 158. Whisper's formatting is known to be prompt-sensitive and
    this run did not control the decoder prompt tokens sherpa supplies. It matters because
    F-WER is the headline metric and unformatted output fails it outright — but it cannot be
    settled on the proxy set, whose references are unformatted anyway.

17. **How unstable is the int8 Parakeet export, and is fp32 better?** Raised 2026-10-06 by
    Task 2b. A 1e-7 relative perturbation of the features flips the transcript; float32
    reduction-order differences alone changed the greedy text on 23 of 91 utterances, with
    no WER bias. Hypothesis, untested: dynamic int8 activation quantization turns sub-ULP
    input noise into rounding flips that propagate through 24 encoder layers. It puts a
    noise floor under any confidence value, means two correct implementations of the same
    decode will not agree byte-for-byte (a hazard for the Phase 3 Rust port's parity
    testing), and folds into Task 2 item 2 (fp32 vs int8). Testing it needs the fp32 export,
    which is a model addition and outside Task 2b's scope.

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

## Standing instructions

- **Commit only on request.** Task 2a is committed in full as of 2026-10-05: the
  one-resident-recognizer support, `--decode-order`, their tests, the write-ups, D-0013 and
  the SYNTHESIS §5/§11 corrections.
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
