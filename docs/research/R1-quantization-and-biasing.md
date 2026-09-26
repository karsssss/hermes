# R1 — Quantization & contextual biasing

Research landed 2026-09-24. Verified against primary sources (arXiv, GitHub raw source,
HuggingFace API, vendor docs). Items marked **unverified** must not be treated as fact.

> **PARTIALLY SUPERSEDED — read `R4-asr-model-salvage.md` first.** R4 corrects three claims
> below: (a) the word-boosting confirmation here is about **sherpa-onnx**, not
> NeMo-Speech.cpp, which was never verified to support boosting; (b) NeMo-Speech.cpp is a
> very new, thin project (17 commits on main) and the "our entire inference backend"
> framing below is over-enthusiastic; (c) sherpa-onnx's Nemotron hotword support merged
> 2026-09-14, **after** the v1.13.8 release, so it may not be in a pinned build.

## Headline

**The architectural fork is biasing, not quantization.** Quantization is a low-risk dial
(int8 everywhere; NVIDIA itself ships ASR at Q8_0). Biasing is where runtimes diverge, and
it eliminates more of our shortlist than any performance consideration:

- **Whisper has no true biasing anywhere** except whisper.cpp's logits-filter callback.
- **Parakeet TDT is explicitly ignored by NVIDIA's own word boosting.**

Since W3 (project-aware vocabulary) depends on biasing, this reshapes model selection.

## NVIDIA NeMo-Speech.cpp — the discovery

`https://github.com/NVIDIA/NeMo-Speech.cpp` — NVIDIA's official local speech runtime.
ggml-based C++, **PowerShell one-liner Windows installer**, day-0 NeMo model support.
Covers streaming ASR, Silero VAD, punctuation/capitalisation, endpointing, ITN,
diarization, TTS, and a local OpenAI-compatible HTTP + WebSocket server. Pushed daily.

This is, substantially, our entire inference backend in one shipped artifact.

**Its word boosting**, verbatim restriction: *"Flashlight CTC and cache-aware RNNT support
boosting; greedy CTC without an LM and **Parakeet TDT ignore it**."*

So biasing in this stack requires **Nemotron Speech Streaming 0.6B** (cache-aware RNNT):
boosting built in, needs no LM artifacts, works with **greedy** decoding, request scores
2-3, `boosting_max_boost` default 5.0 ("greedy-safe"), `boosting_tree_alpha` 1.0,
`boosting_depth_scaling` 2.0. Requires the SentencePiece tokenizer embedded in current
GGUFs; older GGUFs must be reconverted with `convert_model.py`.
API: `speech_contexts=[{"phrases":["Kowalczyk"],"boost":3.0}]`, CLI `--speech-context`,
gRPC `RecognitionConfig.speech_contexts`.

Those parameter names are TurboBias's — TurboBias shipped all the way into the CPU/ggml
runtime, not just the CUDA Python path.

## TurboBias (the biasing method, measured)

- v1: arXiv 2508.07014, ASRU 2025. GPU-accelerated phrase-boosting tree, log depth bonus,
  shallow fusion under **greedy as well as beam**, no retraining, scales to 20K phrases.
  CSTalks 200 phrases: CTC greedy F 35.0 to 64.8; RNN-T greedy 42.5 to 70.4; RNN-T beam
  44.2 to 82.9. **+8-10 absolute F under greedy, +17-23 under beam.** Cost: 2-5% RTFx.
- v2: arXiv 2608.21343, 2026-08-21. Adds case-insensitive boosting graph, per-stream
  batched decoding, streaming beam search. Earnings22 **streaming at 1.12 s latency:
  F 62.2 to 81.7, WER 16.3% to 14.3%**.
- Shipped in NeMo (PRs #14108, #14277, #15800, #15125, #15753). **Not in sherpa-onnx.**

Two caveats: the 1.12 s streaming latency is high for interactive dictation — we need the
F-score at *our* latency target. And the v2 case-insensitivity work implies case handling
was weak in v1, which matters directly for code identifiers (`getUserID` vs `getuserid`).

## sherpa-onnx biasing — usable, with two silent-failure traps

Real API, works streaming and offline. `hotwords_file` / `hotwords_buf` /
`hotwords_score` (default 1.5), and per-utterance `CreateStream(hotwords)` **without
reloading the model** — the important one for dictation.

**Traps, both silent, both on by default:**

1. `decoding_method` defaults to `greedy_search`, which **ignores hotwords entirely**.
   Must be `modified_beam_search`.
2. `modeling_unit` defaults to `"cjkchar"`. For English you must set `"bpe"` **and**
   supply `bpe_vocab`, or nothing matches.

Transducer models only — issue #3970 confirms non-transducer models hard-abort with
*"Only transducer models support contextual biasing."*

PR #3895 (merged 2026-09-14) adds a beam decoder for **streaming NeMo/Nemotron
transducers**, which previously had no hotwords path. Reported beam=4 22.11% WER vs greedy
23.16%, ~1.1x greedy cost, RTF ~0.11, and *"recovered proper nouns like 'Melchizedek'
that greedy mangled."*

**UI consequence from that PR, quoted:** *"The best path can revise earlier text between
chunks (inherent to beam) — greedy's monotonic-prefix property does not hold."* Our UI must
tolerate already-displayed text being rewritten. This is a design constraint, not a detail.

Also present: `HomophoneReplacerConfig` and `rule_fsts`/`rule_fars` — deterministic FST
post-rewriting. Worth pairing with probabilistic biasing, since it can *enforce* an exact
spelling that boosting can only make likelier.

## faster-whisper `hotwords` — the common claim is false

Source-verified in `get_prompt()`: `hotwords` is **pure prompt injection into the
startofprev block, mechanically identical to `initial_prompt`, with zero logit
manipulation.** Further:

- **Silently ignored whenever `prefix` is set** (docstring confirms; no warning).
- Competes with `condition_on_previous_text` for the same ~223-token budget.

faster-whisper is the **weakest** biasing option in our candidate set, and has had
**no release in ~11 months** (v1.2.1, 2025-10-31) while CTranslate2 ships regularly
(v4.8.2, 2026-08-31).

## whisper.cpp — stronger than expected

Three mechanisms in current `whisper.h`:

1. `initial_prompt` + **`carry_initial_prompt`** — re-prepends the prompt every window.
   Without it, a jargon list evaporates after the first 30 s window. Limit ~224 tokens.
2. **`whisper_logits_filter_callback`** — mutable `float * logits`, called after
   temperature. A genuine logit-bias primitive, strictly more reliable than prompting.
   C API only, not exposed on the CLI. **The only real logit-level biasing for Whisper.**
3. GBNF grammar — `--grammar` + `--grammar-rule` (both required, else silently skipped),
   `--grammar-penalty` default 100.0. A soft penalty, not a hard constraint. Suitable for
   structured command input, far too restrictive for prose.

## Quantization — settled, low risk

**CTranslate2 silent fallbacks on our hardware.** On the i5-12450H: `int8_float16`,
`int8_bfloat16`, `float16`, `bfloat16` **all silently degrade** (to `int8_float32` or
`float32`). `int8_float16` is a GPU-only concept. On the RTX 4050 (CC 8.9) they pass
through natively. Diagnose with `CT2_VERBOSE=1`.

**Measured (faster-whisper README, large-v2, 13 min, beam 5):**

- GPU RTX 3070 Ti: fp16 1m03s / 4525 MB to int8 59s / **2926 MB**. *int8 on GPU buys memory
  (-35%), not speed (-6%).*
- CPU **i7-12700K, same Alder Lake family**, small model: fp32 2m37s / 2257 MB to int8
  **1m42s / 1477 MB**. *int8 on CPU is a genuine **~1.54x speedup**.*

Practical rule: **int8 on CPU for the speed, int8 on GPU for the memory headroom.**

**AVX-VNNI build trap.** ggml models our exact part as a first-class dispatch target
(`ggml_add_cpu_backend_variant(alderlake ... AVX_VNNI)`), but `GGML_AVX_VNNI` **defaults to
OFF**. Official release binaries runtime-dispatch correctly; a **self-built whisper.cpp
with default flags silently forfeits the int8 speedup with no error.** Pass
`-DGGML_AVX_VNNI=ON` or use official binaries.

**Sizes (HF API, verified):** large-v3-turbo ggml fp16 1624.6 MB to q8_0 874.2 MB to
q5_0 574.0 MB. Parakeet TDT 0.6B sherpa ONNX fp32 ~2.51 GB to int8 ~670 MB.
Upstream ships **no K-quants for Whisper** — only q5_0/q5_1/q8_0.

**VRAM fit:** large-v3-turbo fp16 estimated **~3 GB total**, comfortable in 6 GB
(*extrapolated from the large-v2 measurement, not measured for turbo*). Full large-v3 fp16
measured 4525 MB of 6144 — fits but thin; use `int8_float16` (2926 MB measured).

**q5 is slow.** q5_0/q5_1 were 3-5.5x slower than q4_0 in the community benchmark, because
q4_0 has the repacked SIMD dot-product path. Practical GGML choice is **q8_0 or q4_0, not
q5** — awkward, since q5_0 is what upstream ships for turbo.

**int4 is out of scope for the encoder.** NVIDIA's own NeMo-Speech.cpp defaults:
ASR to Q8_0, VAD/diarization to F32, **Q4_K_M only for the S2S LLM bundle.** That is
exactly the split: 4-bit for the LLM half, 8-bit for the acoustic model.

## The cross-cutting finding worth acting on

**TARQ (arXiv 2605.27808, May 2026): quantization damages rare words disproportionately**,
because PTQ calibration is frequency-weighted, so *"names, numerals and domain terms
receive proportionally little calibration mass."*

Our quantization choice and our biasing requirement are the same problem viewed twice.
**Aggregate WER will hide this.** Independent justification for E-WER (`BENCHMARKS.md`)
as a first-class metric rather than a nice-to-have.

Counterpoint: *Quantizing Whisper-small* (arXiv 2511.08093) found **dynamic int8 (Quanto)
improved on baseline WER** at 57% size reduction; static was worse. int4 reached 71%
compression "at the cost of accuracy in noisy conditions."

## Gaps (unverified — do not cite as fact)

- **No measured fp32-vs-int8 WER pair exists** for CT2/Whisper, whisper.cpp GGML quants, or
  sherpa-onnx int8. None is published. Claims circulating ("Q5_1 loses <1% WER") trace to
  content farms. **We must measure this ourselves on our own audio.**
- Joiner-specific int8 degradation (blank collapse, emission-timing drift) is plausible on
  first principles but **unsourced**. Cheap test: compare int8 vs fp32 joiner on emission
  *timestamps*, not WER — WER is insensitive to that failure mode.
- Windows 11 WDDM compositor VRAM reserve on a 6 GB laptop GPU. Budget empirically.
- Alder Lake P/E straggler effects and optimal thread count. SYSTRAN benchmarked their
  8P+4E part at exactly 8 threads, not 20 — suggestive, circumstantial. **Sweep
  `-t 4/6/8/12` ourselves.**
- Vosk, Kaldi, ESPnet, WeNet, Moonshine biasing: not checked (budget exhausted).

## Sources

arXiv [2608.21343](https://arxiv.org/abs/2608.21343) ·
[2508.07014](https://arxiv.org/abs/2508.07014) ·
[2605.27808](https://arxiv.org/abs/2605.27808) ·
[2511.08093](https://arxiv.org/abs/2511.08093) ·
[2505.22857](https://arxiv.org/pdf/2505.22857) ·
[NeMo-Speech.cpp](https://github.com/NVIDIA/NeMo-Speech.cpp) ·
[NeMo word boosting](https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/asr_customization/word_boosting.html) ·
[sherpa-onnx hotwords](https://k2-fsa.github.io/sherpa/onnx/hotwords/index.html) ·
[sherpa PR #3895](https://github.com/k2-fsa/sherpa-onnx/pull/3895) ·
[CT2 quantization](https://opennmt.net/CTranslate2/quantization.html) ·
[faster-whisper transcribe.py](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py) ·
[whisper.h](https://github.com/ggml-org/whisper.cpp/blob/master/include/whisper.h)
