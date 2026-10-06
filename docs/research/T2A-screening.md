# T2A — ASR candidate screening

Status: **complete**, 2026-09-28. Phase 0, Task 2a. All three candidates measured;
Nemotron eliminated, Parakeet and Whisper retained (§4, Eliminations).

**Screening, not selection.** Nothing here decides the production backend; the purpose is
to eliminate candidates cheaply enough that deep integration effort only goes where it can
pay off.

Scored against **Public Proxy Evaluation Set v1**, frozen at commit `a2bbbf3`, manifest
sha256 `2b3a46ede2700f30…`, 160 utterances. The personal set does not exist yet, so
everything below inherits that set's limits — most importantly, **the headline number here
is WER, not F-WER.** See `eval/datasets/public-proxy-v1/COVERAGE.md`.

---

## 1. The shortlist, and why these three

`docs/SYNTHESIS.md` §5 names exactly three models and the roles they are candidates for. The
shortlist is those three, unexpanded:

| Candidate | Role in SYNTHESIS §5 | Licence |
|---|---|---|
| **Nemotron Speech Streaming EN 0.6B @ 560 ms** | "Leading hypothesis", cache-aware RNNT | NVIDIA Open Model License |
| **Parakeet TDT 0.6B v3** | "The multilingual candidate", 25 languages incl. ru/uk | CC-BY-4.0 |
| **Whisper large-v3-turbo** | "The accuracy-tier fallback" | MIT |

Canary-1B-v2 appears in SYNTHESIS §14's licence table but not in §5's candidate set, and the
only Canary export with a sherpa-onnx build is `canary-180m-flash-en-es-de-fr`, which has no
Russian and so cannot be scored on five of the seven subsets. Not added.

The 560 ms chunk configuration is the one SYNTHESIS §5 names specifically, so that is the one
measured. `nemotron-3.5-asr-streaming-0.6b` — the multilingual sibling carrying the different
`openmdw-1.1` licence flagged as open question #11 — was **not** tested; it is a different
licence question and a different model, and the shortlist was not to be expanded.

## 2. Method

Every candidate runs on **one runtime, one provider, one thread count, one warm-up policy,
one set of audio bytes**. That is the only thing that makes the comparison mean anything, and
it is why all three go through sherpa-onnx rather than through each model's native toolkit.

| Held constant | Value |
|---|---|
| Runtime | ONNX Runtime 1.28.0 via sherpa-onnx 1.13.8 |
| Provider | CPU execution provider |
| Threads | 4 (P-core count; the P/E thread sweep is a separate deferred measurement) |
| Quantization | int8 dynamic, for all three (`producer: onnx.quantize`) |
| Decoding | `greedy_search`, no per-subset tuning, no hotwords, no LM |
| Warm-up | 2 decodes of a fixed 5 s synthetic signal (seed 20260926), before any timed utterance — per recognizer, so a second language session is warmed identically |
| Resident models | **1 at a time**, enforced (`resident=1`); see below |
| Audio | The frozen manifest's 16 kHz mono 16-bit WAVs, byte-identical across candidates |
| Scoring | `hermes-eval run`, identical code path, WER under `basic` normalization |

**sherpa-onnx is a measurement harness here, not a production proposal.** R5's objection to it
— `sherpa-rs` is archived, so shipping it from Rust means maintaining our own FFI — is about
the Rust integration path and has no bearing on a Python screening run. D-0011 already settled
ONNX Runtime as the substrate; this puts all three candidates on it.

**Warm-up uses synthetic audio, never dataset audio.** Warming on a real utterance would either
bias whichever record went first or run an untimed pass over evaluation audio. A fixed
synthetic signal pays the same ORT graph-init, arena and thread-pool costs without either
problem.

**No evaluation transcript was used for prompting or adaptation.** The adapter is handed the
record and reads only `audio` and `metadata.language`; `record.reference` is never touched.
`metadata.language` is used only by Whisper, which requires a language at recognizer
construction — recorded in `decode_params.language_source`.

### Whisper is multi-language; the other two are not. Making that fair.

sherpa binds Whisper's language at **recognizer construction**, so a run covering English
and Russian naively builds two ORT sessions over the same weights and keeps both alive.
That is not a model property — it is a harness artefact — and it would have inflated
Whisper's peak RAM by roughly the size of a second session against two single-session
transducers. Reporting that number next to Parakeet's 996 MB would have been a fabricated
loss.

The protocol instead is **one resident recognizer at a time**, for every candidate:

1. Decode every English row with a single English recognizer.
2. Release it — drop the last Python reference and `gc.collect()`, which is what actually
   returns the ORT session, its weights and its arenas. Measured, not assumed: the release
   is timed and the working set is read before and after, and the run record carries the
   delta.
3. Build the Russian recognizer and give it the **identical** warm-up the first one got —
   two decodes of the same synthetic signal. A second session that skipped warm-up would
   pay ORT's graph-init cost inside its first *timed* utterance and show up as a latency
   outlier caused by the harness.
4. Decode every Russian row.

Both halves are one run over one manifest, scored in one pass: the run directory holds all
160 utterances, one manifest sha256, one set of metrics. Nothing is merged after the fact.
What makes it one run rather than two is `--decode-order language`, which groups the
manifest by `metadata.language` before decoding while still writing every output sorted by
id. The public proxy manifest alternates en/ru/en/ru, so **manifest order would have cost
four model loads and language order costs two** — same utterances, same scores, one
switch instead of three. The run record states which order it used and carries a hash of
the decode sequence, so the reordering is checkable rather than merely claimed.

The cost of that switch is reported **separately** from every decode number. It is a
property of the integration, not of the model's speed, and a production integration that
dropped to a lower-level API could avoid it entirely. Burying it inside a latency
percentile would misattribute it to Whisper.

Parakeet and Nemotron are unaffected: each has exactly one recognizer regardless, so their
two completed runs remain valid as measured and were not re-run.

### What "peak RAM" means here

Two readings, because one of them cannot tell sequential sessions apart.

**Peak working set** is the OS high-water mark (`PeakWorkingSetSize`) for the harness
process. It never falls, so for a run that stands up a second recognizer after releasing
the first it reports the larger of the two — correct as a whole-run figure, useless for
checking that only one was ever resident.

**Single-session working set** is the process' *current* working set, sampled after every
decode and maxed within each session. With one resident recognizer the two agree, and the
fact that they agree is the evidence that the release worked.

Both are per-process counters (`GetProcessMemoryInfo`) for the harness process, not system
free memory.
On this machine that distinction is not academic: at the time of the runs, Edge alone held
4.3 GB and free physical RAM moved between 1.7 GB and 4.2 GB. System-wide figures would have
measured the browser. Peak VRAM is reported as **null rather than zero** when nothing was
attributable to the PID — "no GPU allocation" and "could not observe one" are different
claims.

## 3. Integration findings

Four things cost real time and are worth writing down.

**The sherpa-onnx wheel ships no `onnxruntime.dll`.** Windows resolves the bare name to the
inbox `C:\Windows\System32\onnxruntime.dll` — version 1.17, the Windows ML copy — and sherpa
1.13.8 needs ORT API 28. The failure is `The requested API version [28] is not available, only
API versions [1, 17] are supported in this build`. Fix: pin `onnxruntime==1.28.0` and copy its
DLL next to `_sherpa_onnx.pyd`, because a dependent DLL is resolved from the loading module's
own directory before System32. `hermes_eval.asr_sherpa.ensure_runtime()` does this. Anyone
shipping ORT on Windows will meet this; the inbox copy is not going away.

**The Nemotron streaming export cannot be driven offline.** Feeding it to
`OfflineRecognizer.from_transducer` fails with `Missing Input: cache_last_time` — the graph
expects the cache tensors that only the online recognizer supplies. It is a cache-aware
streaming model and has to be fed as a stream, chunk by chunk. This is correct behaviour, but
it means its cost profile is a per-chunk cost, not a per-utterance one.

**Whisper's encoder is a fixed 30-second window.** A 3-second utterance costs what a
30-second one costs. For a dictation product whose median utterance is a few seconds, that is
a structural property of the architecture, not a tuning problem, and it shows up directly in
the short-utterance latency figures in §4.

**Whisper's language is bound at recognizer construction.** sherpa's
`OfflineRecognizer.from_whisper` takes `language=` as a constructor argument, so covering
two languages naively means two live ORT sessions over one set of weights — which would
have made Whisper's peak RAM a harness artefact rather than a measurement. §2 describes the
single-resident protocol that fixes it and §4 reports what the resulting switch costs
(29.6 s). The finding for the product is that a *measured* 29.6-second stall sits on every
language change through this API.

## 4. Results

### Status: COMPLETE — all three candidates measured

| Candidate | Status | Immutable run directory |
|---|---|---|
| Parakeet TDT 0.6B v3 int8 | Complete | `eval/runs/20260927T022919Z-t2a-parakeet-tdt-v3-aff8/` |
| Nemotron Speech Streaming EN 0.6B @560 ms int8 | Complete | `eval/runs/20260927T031249Z-t2a-nemotron-stream-en-560ms-c9f4/` |
| Whisper large-v3-turbo int8 | **Complete** 2026-09-28 | `eval/runs/20260928T002321Z-t2a-whisper-large-v3-turbo-c4c0/` |

All three scored manifest sha256 `2b3a46ede2700f30…`, n=160, and carry the full six
artifacts (`run.json`, `summary.json`, `summary.csv`, `summary.md`, `predictions.jsonl`,
`per_utterance.jsonl`). Raw predictions and per-utterance counts are preserved there,
including per-utterance RTF and audio duration under each prediction's `extra`.

`eval/runs/` is gitignored. **`run.json` and `predictions.jsonl` for all three are
committed** (force-added, ~0.9 MB of text) — the provenance, metrics and raw hypotheses, which
are what would cost ~80 minutes to regenerate. The other four artifacts are derived by
scoring and stay on this machine.

The Whisper run is the one that had to be repeated: its first attempt was killed by the
background task reaper at 03:12:50Z on 2026-09-27, before it decoded an utterance, when the
machine dropped to critically low free memory. Nothing about that kill was attributable to
the model. The rerun was done alone, with 2.8 GB free, under the one-resident-recognizer
protocol in §2, and was not re-run again afterwards.

### Quality — WER %, lower is better

| subset | n | Parakeet TDT v3 | Nemotron EN 560 ms | Whisper turbo |
|---|---:|---:|---:|---:|
| **OVERALL** | 160 | **13.29** | 32.55 | 14.89 |
| accented_en | 50 | **18.74** | 27.67 | 23.64 |
| general_en | 30 | **1.81** | 4.12 | **1.81** |
| ru_clean | 20 | 13.41 | 100.00 | **8.94** |
| ru_command | 10 | **3.08** | 100.00 | 7.69 |
| ru_farfield | 10 | **37.78** | 100.00 | **37.78** |
| robust_noise | 20 | **18.42** | 30.12 | **18.42** |
| robust_reverb | 20 | **12.57** | 28.36 | 13.74 |

By language, the axis that matters for the English-first Phase 1 track (SYNTHESIS §6):

| language | n | Parakeet TDT v3 | Nemotron EN 560 ms | Whisper turbo |
|---|---:|---:|---:|---:|
| en | 112 | **12.79** | 18.66 | 15.42 |
| ru | 48 | 15.75 | 100.00 | **12.33** |

**Nemotron's Russian rows are 100% by design, not by failure.** It is an en-US-only model.
Those rows are reported for completeness and carry no weight in any elimination.

**Three of the Parakeet/Whisper subset figures are identical to two decimals, and that is a
coincidence rather than a bug.** It was checked, because three exact ties invites suspicion:
146 of the 160 hypothesis strings differ between the two runs, and the tied subsets have
entirely different error *compositions* behind the same totals — on ru_farfield, Parakeet's
17 errors are 5 substitutions and 12 deletions while Whisper's 17 are 17 substitutions and 0
deletions. Small reference denominators (ru_farfield is 45 reference words) make identical
totals far likelier than intuition suggests.

### Is the Parakeet/Whisper gap real? — paired bootstrap

The two leaders are 1.60 pp apart overall, and `BENCHMARKS.md` §1.2 puts detectability at
this sample size at 1–3 pp. That is precisely the band where a point estimate must not be
read as a result, so the interval was computed rather than assumed.

Paired utterance-level bootstrap, 2000 resamples, seed 20260926 — the harness's own
`bootstrap.paired_bootstrap`, on the **WER** counts. *Not* F-WER: this set's references are
unformatted, so F-WER on it is ~89% for every candidate and measures the reference style
rather than the model (`COVERAGE.md`). `hermes-eval compare` bootstraps F-WER by design,
which is correct for a ship/no-ship gate on the personal set and wrong here.

Positive delta = Whisper worse than Parakeet.

| slice | n | Parakeet | Whisper | Δ pp | 95% CI | verdict |
|---|---:|---:|---:|---:|---|---|
| OVERALL | 160 | 13.29 | 14.89 | +1.60 | [−0.08, +3.31] | **noise** — CI includes zero |
| language=en | 112 | 12.79 | 15.42 | +2.63 | [+0.80, +4.43] | **real** — Parakeet better |
| language=ru | 48 | 15.75 | 12.33 | −3.42 | [−8.74, +1.53] | noise |
| accented_en | 50 | 18.74 | 23.64 | +4.90 | [+1.72, +8.35] | **real** — Parakeet better |
| ru_clean | 20 | 13.41 | 8.94 | −4.47 | [−8.89, −1.09] | **real** — Whisper better |
| general_en | 30 | 1.81 | 1.81 | +0.00 | [−1.11, +1.37] | noise |
| robust_noise | 20 | 18.42 | 18.42 | +0.00 | [−4.67, +4.42] | noise |
| robust_reverb | 20 | 12.57 | 13.74 | +1.17 | [−5.65, +6.68] | noise |
| ru_command | 10 | 3.08 | 7.69 | +4.62 | [−3.77, +14.29] | noise |
| ru_farfield | 10 | 37.78 | 37.78 | +0.00 | [−27.09, +25.01] | noise |

Read this carefully, because the headline number and the conclusion point different ways:

- **The overall 1.60 pp gap is not a result.** Anyone quoting "Parakeet beats Whisper by 1.6
  points" from this set would be quoting noise, and this document will not.
- **The English gap is a result**, +2.63 pp with the CI clear of zero — and so is the
  accented-English gap, +4.90 pp, on the subset `BENCHMARKS.md` §2 calls the core of W2.
  That is the slice this product lives on.
- **Whisper genuinely wins Russian read speech** (−4.47 pp on ru_clean, CI clear of zero),
  but its Russian advantage does not survive aggregation to the language level, and the two
  ten-utterance Russian subsets carry intervals ±25 pp wide — they decide nothing.

Against Nemotron, both are clear of zero and the direction never changes: Whisper beats it
by 17.66 pp overall [−23.32, −12.65] and by 3.24 pp on English alone [−5.48, −1.28];
Parakeet's margins over it are larger still.

### Formatting emitted, which is not the same as formatting scored

F-WER is this product's headline metric, and it cannot be computed here. What *can* be
observed without a formatted reference is how often each backend emits formatting at all:

| candidate | non-empty outputs | with any punctuation | with any uppercase |
|---|---:|---:|---:|
| Parakeet TDT v3 | 158 | 154 | 154 |
| Nemotron EN 560 ms | 137 | 50 | 137 |
| Whisper turbo | **160** | 117 | 120 |

Parakeet formats essentially everything it transcribes. **Whisper, through this export and
this runtime, does not** — roughly a quarter of its outputs come back with no punctuation
and no casing at all, including most of the LibriSpeech rows, where all three produce nearly
the same words and only Parakeet capitalises and punctuates them.

Two honest caveats. This is a property of *this sherpa-onnx int8 export driven at
`greedy_search`*, not necessarily of Whisper large-v3-turbo — the decoder prompt tokens
sherpa supplies are not something this run controlled, and Whisper's formatting is known to
be prompt-sensitive. And it is a count of emission, not a measure of correctness: nothing
here says the punctuation Parakeet emits is *right*. It is a flag for Task 1b, where a
formatted reference exists and F-WER becomes computable, not a score.

Nemotron emits casing but punctuates only 50 of 137 non-empty outputs — a third gap on top
of its other problems, and one that would need a separate punctuation model to close.

### Performance — CPU execution provider, 4 threads

| metric | Parakeet TDT v3 | Nemotron EN 560 ms | Whisper turbo |
|---|---:|---:|---:|
| **RTF, corpus** | **0.47** | 2.44 | 2.05 |
| RTF p50 / p95, per utterance | **0.52 / 0.79** | 2.44 / 2.84 | 2.34 / 3.94 |
| RTF min / max | **0.26 / 1.02** | 1.61 / 3.03 | 1.26 / 4.98 |
| utterances slower than real time | **2 / 160** | 160 / 160 | 160 / 160 |
| warm latency p50 | **2693 ms** | 12741 ms | 11965 ms |
| warm latency p95 | **5707 ms** | 40029 ms | 22343 ms |
| warm latency p99 | **6409 ms** | 43533 ms | 31109 ms |
| median latency, utterances ≤3 s (n=28) | **1958 ms** | 5792 ms | 9267 ms |
| median latency, utterances ≥9 s (n=35) | **4713 ms** | 30187 ms | 20081 ms |
| model load (first session) | 5735 ms | 6699 ms | **4932 ms** |
| warm-up (2× 5 s synthetic) | **5121 ms** | 19132 ms | 19836 ms |
| language-switch total | — | — | 29556 ms |
| **peak working set** | 996 MB | **797 MB** | 2135 MB |
| peak working set, single session | 996 MB | **797 MB** | 2118 MB |
| peak private commit | 1354 MB | **1155 MB** | 2814 MB |
| **peak VRAM** | null — CPU EP | null — CPU EP | null — CPU EP |
| empty outputs | 2 / 160 | 23 / 160 | **0 / 160** |
| decode total | **493 s** | 2581 s | 2162 s |

Audio total was 1055.86 s (17.6 min) for all three, identical by construction.

**CPU-only viability is where this screening actually separates the candidates.** Parakeet
is the only one that runs faster than real time on the CPU EP: corpus RTF 0.47, exceeding
real time on 2 of 160 utterances. Whisper exceeded real time on **160 of 160** (min RTF
1.26), Nemotron on **160 of 160** (min 1.61). On a machine where CPU-only must be
first-class, that is the difference between a viable backend and one that needs a GPU the
user may not have.

**Whisper's 30-second window shows up exactly where it hurts most.** It is the *fastest* of
the two slow candidates on long audio — 20081 ms median for utterances ≥9 s against
Nemotron's 30187 ms — and the *slowest of all three* on short audio, 9267 ms median for
utterances ≤3 s, where Parakeet takes 1958 ms. A 2-second utterance and a 25-second one cost
it nearly the same, because the encoder pads both to 30 s. Dictation is made of short
utterances. This is architecture, not tuning.

**Whisper's memory is real, and it is measured single-session.** 2118 MB while exactly one
recognizer was resident — 2.1× Parakeet and 2.7× Nemotron. The naive `langs=en|ru`
configuration would have reported roughly double that, and it would have been an artefact;
this is not. The two figures that would disagree if the protocol had failed — whole-run peak
2135 MB and single-session peak 2118 MB — agree to within 17 MB, and the release between
sessions returned 1940 MB to the OS.

### Whisper's language sessions, reported apart from decode

| session | language | utterances | load | warm-up | evict | released | peak WS | RTF |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 0 | en | 112 | 4932 ms | 19836 ms | 532 ms | 1940 MB | 2118 MB | 1.93 |
| 1 | ru | 48 | 6349 ms | 22675 ms | — | — | 1740 MB | 2.44 |

**A language switch costs 29.6 s**: 0.5 s to release the English recognizer, 6.3 s to build
the Russian one, 22.7 s to give it the identical warm-up. That is 1.4% of the run's 2162 s
of decode, and it is excluded from every latency and RTF figure above, because it is a
property of sherpa's API — Whisper's language is bound at recognizer construction — and not
of the model's speed.

For screening it is a footnote. **For the product it is not.** A code-switching user is the
target user (`PRODUCT.md` §3, W3), and a 29.6-second stall on every language change is not a
dictation experience. A production integration would have to drop below sherpa's recognizer
API to swap the decoder prompt without rebuilding the session — unverified work, and it
belongs in the cost column against Whisper.

Note also that the Russian session decoded *slower* per second of audio than the English one
(RTF 2.44 vs 1.93) despite identical weights and identical warm-up. Russian utterances in
this set are shorter, so more of them pay the full 30 s encoder window for less audio. The
same architectural fact, seen from a second angle.

### Caveats on these numbers

- **Whole-utterance decode, not streaming.** Every latency figure above is the cost of
  decoding a complete utterance after it ended. The 700 ms p95 budget in `ARCHITECTURE.md`
  §8 assumes decode overlapped with speech. Comparing these numbers to that budget directly
  would be unfair to all three — see open question #15.
- **Nemotron is penalised by the harness shape.** It is a cache-aware *streaming* model
  driven here chunk-by-chunk through a Python loop over a finished utterance, so it pays
  per-chunk Python↔C++ overhead ~20 times for an 11 s utterance and gets no benefit from the
  overlap its architecture exists to exploit. Its RTF is a pessimistic reading of its
  streaming potential — but the correct reading of *offline batch cost*, and its quality
  numbers carry no such excuse.
- **Whisper is not penalised by the harness shape**, and that is worth saying explicitly
  given the previous point. It is an offline model decoded offline, one recognizer, one
  utterance at a time, warmed identically. Its 30 s window is not something a different
  harness would avoid.
- **The three runs were measured under different machine memory pressure.** Same hardware,
  threads, provider and audio bytes, but not the same free RAM (1.7–4.2 GB for the
  2026-09-27 pair, 2.8 GB at the Whisper launch). Peak-memory figures are per-process and
  unaffected. Latency figures could be, at the margin — the direction is unknown and it is
  not large enough to move a 4.4× RTF gap.
- **One thread count.** All figures are at 4 threads. The P/E-core sweep is a separate
  deferred measurement and could move absolute numbers materially; it is unlikely to reorder
  a 4× gap.
- **n=160, and the intervals above say where that bites.** The two Russian ten-utterance
  subsets have CIs roughly ±25 pp wide. They are reported; they decide nothing.
- **Decode order differs between runs.** The Whisper run used `--decode-order language`
  (recorded in its run record with a hash of the decode sequence); the two earlier runs
  pre-date the flag and used manifest order. Scoring is per utterance and order-independent
  — `test_decode_order_does_not_change_the_scores` asserts it — so the quality tables
  compare cleanly. The only thing order changed is how many times Whisper had to rebuild.

### Eliminations

The brief allows at most two survivors. **One candidate is eliminated and two are retained.**

#### Eliminated: Nemotron Speech Streaming EN 0.6B @ 560 ms

It is dominated on every measured axis except peak RAM, by **both** other candidates.

- **Worse quality than both, with intervals to back it.** Whisper beats it on English by
  3.24 pp [−5.48, −1.28]; Parakeet's margin is larger. Against Parakeet it loses general
  English (4.12 vs 1.81), accented English (27.67 vs 18.74), and both perturbations.
- **Slowest of the three**, corpus RTF 2.44, p95 latency 40 s per utterance, never once
  faster than the audio it was transcribing.
- **23 of 160 utterances came back empty**, against Parakeet's 2 and Whisper's 0. An empty
  transcript is not a bad transcript; it is nothing injected and a user typing it themselves.
- **Punctuates only 50 of its 137 non-empty outputs**, so F-WER would need a separate
  punctuation model stacked on top.
- Its one win is peak working set, 797 MB against Parakeet's 996 MB — 199 MB, on a machine
  with 15.7 GB. Nobody would take that trade.

The streaming caveat is granted in full and does not save it: even reading its RTF as
pessimistic, its quality deficit is measured on the same audio as everyone else's and has
nothing to do with chunking.

**This overturns `SYNTHESIS.md` §5, which names Nemotron at 560 ms the "leading
hypothesis."** That hypothesis rested on architecture and licensing, not on a laptop-class
measurement, and `BENCHMARKS.md` §1.3 exists precisely because published throughput figures
do not transfer to this hardware. It was wrong, and this is the measurement that says so.
**Corrected 2026-10-05:** SYNTHESIS §5 and §11 now carry this ranking, and D-0013
supersedes D-0011's model hypothesis.

#### Retained: Parakeet TDT 0.6B v3 — the front-runner

Best English (12.79%), best accented English (18.74%, the W2 core, CI clear of zero), the
**only** candidate faster than real time on the CPU EP (RTF 0.47, 4.4× Whisper), the lowest
short-utterance latency by 4.7× (1958 ms vs 9267 ms — and dictation is short utterances),
996 MB, native punctuation and casing on 154 of 158 non-empty outputs, CC-BY-4.0, and the
simplest integration of the three. It also transcribes Russian acceptably without needing a
second session.

#### Retained: Whisper large-v3-turbo — the accuracy-tier fallback, on probation

It survives in exactly the role SYNTHESIS §5 nominated it for and no wider. **For:** best
Russian read speech (8.94%, CI clear of zero), 0 empty outputs of 160, statistically
indistinguishable from Parakeet in aggregate, MIT-licensed. **Against:** loses English and
accented English with the CIs clear of zero, RTF 2.05 with every single utterance slower
than real time, worst-of-three short-utterance latency because of the fixed 30 s window,
2.1 GB single-session RAM, formatting emitted on only ~three-quarters of outputs, and a
29.6-second stall on every language switch through this API.

It is retained because it is not dominated — it wins a slice, and a fallback tier is allowed
to be slow — **not** because it is a plausible default backend on this hardware. If Task 1b
shows Parakeet handling the personal set's Russian and code-switched rows, Whisper's
remaining advantage goes with it.

#### What this screening does *not* decide

**No production backend has been chosen, deliberately.** That decision needs the personal set
(Task 1b): F-WER against a formatted reference, E-WER against annotated entities, dev-speak,
code-switching, ITN, the real microphone. Everything above is WER on a public proxy, and
`COVERAGE.md` lists what it cannot see. Parakeet leads on every axis this set can measure;
that is a strong prior for Task 2 item 3, not a decision.

## 5. Deployment assessment

### Windows support

All three load and decode on Windows 11 under ORT 1.28 CPU EP, from a pip-installable wheel,
with no build step. Measured, not inferred.

### ONNX / ORT / DirectML viability

ONNX exports exist and work for all three — that much is now measured rather than assumed,
which also partially de-risks `SYNTHESIS.md` §5.1.

**DirectML is unmeasured for all three, and that is a finding rather than an omission.** Three
independent obstacles:

1. **No prebuilt DirectML wheels for sherpa-onnx.** It has a `SHERPA_ONNX_ENABLE_DIRECTML=ON`
   cmake flag, but using it means building from source with shared libraries.
2. **All three exports are dynamic int8** (`producer: onnx.quantize`). The DirectML EP's int8
   support is limited and version-dependent, and dynamically-quantized graphs
   (`DynamicQuantizeLinear` / `MatMulInteger`) are the pattern it handles worst — expect
   partial CPU fallback, not a speed-up. A DirectML path would likely need fp16 re-exports.
3. **DirectML is in sustained engineering.** ONNX Runtime's own documentation states: *"DirectML
   continues to be supported, but new feature development has moved to WinML for Windows-based
   ONNX Runtime deployments."*

Point 3 is the one that matters beyond this task. **D-0011 names DirectML as the default
execution provider.** That decision was made on sound reasoning — it ships with the Windows
driver stack, works across vendors, and carries no redistribution question, all of which
remain true. But its upstream status has changed, and the decision should be revisited against
WinML before any engineering time goes into a DirectML path. That is a `DECISIONS.md` follow-up,
not a call this screening gets to make.

### Licence suitability

| Candidate | Licence | Commercial | Notes |
|---|---|---|---|
| Parakeet TDT 0.6B v3 | CC-BY-4.0 | Yes, with attribution | Cleanest of the three |
| Nemotron Speech Streaming EN 0.6B | NVIDIA Open Model License | Yes | Confirmed in SYNTHESIS §14; the *multilingual* sibling's `openmdw-1.1` is a separate, unresolved question |
| Whisper large-v3-turbo | MIT | Yes | No carve-outs, unlike Moonshine |

No licence blocks any of the three at the screening stage.

### Integration difficulty

| Candidate | Difficulty | Why |
|---|---|---|
| Parakeet TDT 0.6B v3 | **Low** | Offline transducer, one recognizer, no language plumbing, native punctuation and casing in the output. |
| Nemotron EN 560 ms | **Medium** | Must be driven as a stream; the offline path fails outright. A production integration would have to feed it chunks from the ring buffer, which is the architecture we want anyway — but it is more code than a one-shot decode. |
| Whisper large-v3-turbo | **Medium-high** | Language is bound at recognizer construction, so multi-language means rebuilding the session — **measured at 29.6 s per switch** (§4), which a code-switching user would feel on every change. Avoiding it means dropping below sherpa's recognizer API, unverified. Plus the fixed 30 s window, and formatting emitted on only ~three-quarters of outputs, so a punctuation/casing stage may be needed on top. |

### What this says about SYNTHESIS §5.1 (the Phase 0 exit criterion)

Not a resolution, but a narrowing worth recording. sherpa-onnx's result objects expose
`ys_log_probs`, `tokens` and `timestamps` (offline) and `ys_probs`, `lm_probs` and
`context_scores` (online), over these exact ONNX exports. So a per-token probability **is**
reachable from an ONNX artifact, via a transducer decode loop that already exists in C++ —
which is direct evidence about §5.1's expensive fallback plan ("run the transducer decode loop
ourselves").

Two things remain unverified, and both are cheap to test:

1. Whether the **full per-step distribution** is reachable. R8's entropy method needs the
   distribution; the emitted token's log-prob is not the same thing and is the weaker signal.
2. Whether N-best comes out of `decoding_method="modified_beam_search"`.

**Both answered 2026-10-06 by Task 2b (`T2B-confidence.md`):** (1) not through sherpa's API —
and on Parakeet the emitted token's log-prob turned out *not* to be the weaker signal; it
ties the best full-distribution measure. (2) No — the beam computes K hypotheses and returns
one.

~~This also partially answers open question #12, which had the merge status of sherpa-onnx's
`token_log_probs` down as ambiguous: on the installed 1.13.8 wheel, it is there.~~
**Corrected 2026-10-06 (Task 2b):** that sentence was wrong. It conflated `ys_log_probs` —
the log-prob of the **emitted token only** — with PR #2897's full-vocabulary log-probs,
which was **closed unmerged**; 1.13.8 is the latest release. No released sherpa-onnx API
exposes the full per-step distribution, a sequence score, or N-best: `modified_beam_search`
computes several hypotheses and returns one. Both are reachable only by owning the decode
loop. See `T2B-confidence.md` §6.

With the shortlist now down to two, the cheap tests are cheaper: both survivors need
checking, but **Parakeet is the one that matters**, since it is the only candidate whose
speed makes it a plausible default. It is also a transducer, which is the case §5.1's
fallback plan was written about.

### Reproducing the model downloads

```
mkdir -p models && cd models
BASE=https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models
curl -sLO $BASE/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2
curl -sLO $BASE/sherpa-onnx-nemotron-speech-streaming-en-0.6b-560ms-int8-2026-04-25.tar.bz2
curl -sLO $BASE/sherpa-onnx-whisper-turbo.tar.bz2
for f in *.tar.bz2; do tar xjf "$f"; done
```

~1.5 GB. `models/` is gitignored. The model identity that matters is recorded per run as
`adapter.env.model_sha256`, a combined hash over the encoder, decoder, joiner and tokens files:

| Candidate | model_sha256 |
|---|---|
| Parakeet TDT 0.6B v3 int8 | `d0a44f3cb58043af…` |
| Nemotron EN 560 ms int8 | `2f6be7bdfb4a6a5f…` |
| Whisper large-v3-turbo int8 | `c7e7e7c7054940c0…` |
