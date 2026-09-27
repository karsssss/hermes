# T2A — ASR candidate screening

Status: 2026-09-27. Phase 0, Task 2a. **Screening, not selection.** Nothing here decides the
production backend; the purpose is to eliminate candidates cheaply enough that deep
integration effort only goes where it can pay off.

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
| Warm-up | 2 decodes of a fixed 5 s synthetic signal (seed 20260926), before any timed utterance |
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

### What "peak RAM" means here

Per-process counters (`GetProcessMemoryInfo`) for the harness process, not system free memory.
On this machine that distinction is not academic: at the time of the runs, Edge alone held
4.3 GB and free physical RAM moved between 1.7 GB and 4.2 GB. System-wide figures would have
measured the browser. Peak VRAM is reported as **null rather than zero** when nothing was
attributable to the PID — "no GPU allocation" and "could not observe one" are different
claims.

## 3. Integration findings

Three things cost real time and are worth writing down.

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

## 4. Results

### Status: INCOMPLETE — two of three candidates measured

| Candidate | Status | Immutable run directory |
|---|---|---|
| Parakeet TDT 0.6B v3 int8 | **Complete** | `eval/runs/20260927T022919Z-t2a-parakeet-tdt-v3-aff8/` |
| Nemotron Speech Streaming EN 0.6B @560 ms int8 | **Complete** | `eval/runs/20260927T031249Z-t2a-nemotron-stream-en-560ms-c9f4/` |
| Whisper large-v3-turbo int8 | **Incomplete — no usable data** | none |

Both completed runs scored manifest sha256 `2b3a46ede2700f30…`, n=160, and carry the full six
artifacts (`run.json`, `summary.json`, `summary.csv`, `summary.md`, `predictions.jsonl`,
`per_utterance.jsonl`). Raw predictions and per-utterance counts are preserved there, including
per-utterance RTF and audio duration under each prediction's `extra`.

`eval/runs/` is gitignored, so **these two directories exist on this machine only** and are not
in the repository. Regenerating them costs roughly 50 minutes.

**Whisper could not be fairly tested.** Its run was terminated by Claude Code's background
task reaper at 03:12:50Z, because the machine had dropped to critically low free memory while
the session was idle. It had been running for under a minute and had not decoded a single
utterance — there is no partial data, and nothing about the kill is attributable to the model.
Rerunning it is the next action; the command is in `docs/CURRENT.md`.

### Quality — WER %, lower is better

| subset | n | Parakeet TDT v3 | Nemotron EN 560 ms | Whisper turbo |
|---|---:|---:|---:|---|
| **OVERALL** | 160 | **13.29** | 32.55 | not measured |
| accented_en | 50 | **18.74** | 27.67 | not measured |
| general_en | 30 | **1.81** | 4.12 | not measured |
| ru_clean | 20 | **13.41** | 100.00 | not measured |
| ru_command | 10 | **3.08** | 100.00 | not measured |
| ru_farfield | 10 | **37.78** | 100.00 | not measured |
| robust_noise | 20 | **18.42** | 30.12 | not measured |
| robust_reverb | 20 | **12.57** | 28.36 | not measured |

By language, which is the axis that matters for the English-first Phase 1 track (SYNTHESIS §6):

| language | n | Parakeet TDT v3 | Nemotron EN 560 ms |
|---|---:|---:|---:|
| en | 112 | **12.79** | 18.66 |
| ru | 48 | **15.75** | 100.00 |

**Nemotron's Russian rows are 100% by design, not by failure.** It is an en-US-only model. Those
rows are reported for completeness and carry no weight in any elimination.

Robustness, measured on the *same* 20 source utterances as their clean originals:

| condition | Parakeet | Nemotron |
|---|---:|---:|
| clean originals (mixed subsets) | — | — |
| +MUSAN noise @10 dB SNR | 18.42 | 30.12 |
| +simulated RIR reverb | 12.57 | 28.36 |

Both degrade more under additive noise than under reverberation, which is the expected
ordering. Parakeet's reverb figure (12.57%) sits close to its overall corpus WER, i.e. the
direct-path-aligned RIR convolution costs it relatively little.

### Performance — CPU execution provider, 4 threads

| metric | Parakeet TDT v3 | Nemotron EN 560 ms | Whisper turbo |
|---|---:|---:|---|
| **RTF, corpus** | **0.47** | 2.44 | not measured |
| RTF p50 / p95, per utterance | 0.52 / 0.79 | 2.44 / 2.84 | not measured |
| warm latency p50 | **2693 ms** | 12741 ms | not measured |
| warm latency p95 | **5707 ms** | 40029 ms | not measured |
| warm latency p99 | **6409 ms** | 43533 ms | not measured |
| median latency, utterances ≤3 s (n=28) | **1961 ms** | 5886 ms | not measured |
| median latency, utterances ≥9 s (n=35) | **4713 ms** | 30187 ms | not measured |
| model load | 5735 ms | 6699 ms | not measured |
| warm-up (2× 5 s synthetic) | 5121 ms | 19132 ms | not measured |
| model hash (provenance, not inference) | 575 ms | 595 ms | — |
| **peak working set** | 996 MB | **797 MB** | not measured |
| peak private commit | 1354 MB | 1155 MB | not measured |
| **peak VRAM** | null — CPU EP | null — CPU EP | not measured |
| empty outputs | 2 / 160 | 23 / 160 | not measured |
| decode total | 493 s | 2581 s | not measured |

Audio total was 1055.86 s (17.6 min) for both, identical by construction.

**CPU-only viability.** Parakeet is the only measured candidate that runs faster than real
time on the CPU EP: corpus RTF 0.47, per-utterance RTF min 0.26 / p50 0.52 / p95 0.79 / max
1.02, exceeding real time on **2 of 160** utterances. Nemotron at 560 ms exceeded real time on
**160 of 160**, min RTF 1.61, max 3.03 — it never once kept pace with the audio it was
transcribing. On a machine where CPU-only must be first-class, that is the difference between a
viable backend and one that needs a GPU it may not have.

Neither allocated VRAM, because both ran on the CPU EP by design. `null` here means "no GPU
allocation attributable to this PID", not "0 MB".

### Caveats on these numbers

- **Whole-utterance decode, not streaming.** Every latency figure above is the cost of
  decoding a complete utterance after it ended. The 700 ms p95 budget in `ARCHITECTURE.md` §8
  assumes decode overlapped with speech. Comparing these numbers to that budget directly would
  be unfair to all candidates — see open question #15.
- **Nemotron is penalised by the harness shape.** It is a cache-aware *streaming* model driven
  here chunk-by-chunk through a Python loop over a finished utterance, so it pays per-chunk
  Python↔C++ overhead ~20 times for an 11 s utterance and gets no benefit from the overlap its
  architecture exists to exploit. Its RTF is therefore a pessimistic reading of its streaming
  potential — but it is the correct reading of *offline batch cost*, and it is 5× off the pace
  regardless.
- **One thread count.** All figures are at 4 threads. The P/E-core sweep is a separate deferred
  measurement and could move absolute numbers materially; it is unlikely to reorder a 5× gap.
- **n=160.** `BENCHMARKS.md` §1.2 puts detectability at n=200 at 1–3 pp. The gaps between
  Parakeet and Nemotron here are 6–20 pp, well outside that. No paired bootstrap was run
  because screening is elimination, not a ship/no-ship decision; `hermes-eval compare` is the
  tool when it becomes one.

### Eliminations — DEFERRED

**No candidate has been eliminated, and no production backend has been chosen.** The brief
allows at most two survivors, and that judgement needs all three measured: eliminating Whisper
without data, or keeping it without data, would both be guesses.

What can be said now, provisionally:

**Nemotron Speech Streaming EN 0.6B @560 ms is dominated by Parakeet TDT 0.6B v3 on every
measured axis except peak RAM.** It is worse on general English (4.12 vs 1.81), worse on
accented English (27.67 vs 18.74), worse under both perturbations, 5.2× slower (RTF 2.44 vs
0.47), and returns empty text on 23 of 160 utterances against Parakeet's 2. Its one win is
peak working set, 797 MB against 996 MB — 199 MB, on a machine with 15.7 GB. That is not a
trade anyone would take.

**This contradicts `SYNTHESIS.md` §5, which names Nemotron at 560 ms the "leading
hypothesis."** That hypothesis rested on architecture and licensing, not on a laptop-class
measurement, and `BENCHMARKS.md` §1.3 exists precisely because published throughput figures do
not transfer to this hardware. The hypothesis looks wrong. It is not formally overturned until
Whisper lands and the eliminations are written.

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
| Whisper large-v3-turbo | **Medium** | Language is bound at recognizer construction in sherpa-onnx, so multi-language means multiple sessions over the same weights unless the integration drops to a lower-level API. Plus the fixed 30 s window. |

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

This also partially answers open question #12, which had the merge status of sherpa-onnx's
`token_log_probs` down as ambiguous: on the installed 1.13.8 wheel, it is there.

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
