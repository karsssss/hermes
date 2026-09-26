# R4 — ASR model landscape (salvaged from interrupted research)

Recovered 2026-09-25 from an interrupted agent transcript. **This memo corrects parts of
R1.** Items marked **unverified** must not be treated as fact.

Provenance caveat: the original agent spawned five sub-agents that were all killed before
writing anything. Everything here is the orchestrator's own direct fetches; it never
reached synthesis. Treat as raw findings, not a considered recommendation.

## Corrections to R1 — read these first

1. **R1 conflated two runtimes.** R1's boosting confirmation is about **sherpa-onnx**, not
   NeMo-Speech.cpp. The transcript **never confirmed word boosting inside NeMo-Speech.cpp
   itself.** Do not assume parity between them.
2. **NeMo-Speech.cpp is much thinner than R1 implied**: 126 stars, 30 forks, 9 open issues,
   **17 commits on main**, with several suspicious same-description forks. R1 called it
   "substantially our entire inference backend" — that was over-enthusiastic on a very new,
   low-traffic project. Verify activity independently before betting the Rust core on it.
   Backends are CPU/CUDA/Metal/Vulkan — **no DirectML**. No Rust bindings (C headers + CMake).
   Apache-2.0 for NVIDIA's own code.
3. **sherpa-onnx hotword support for Nemotron is 11 days old and may not be in the release
   you pin.** PR #3895 merged **2026-09-14**; latest release v1.13.8 is **2026-09-10** and
   therefore probably **predates it**. Before v1.13.8: Nemotron streaming was
   greedy-search only, no hotwords (issue #3572). **Verify the release contents or build
   from source.**
4. **Open ASR Leaderboard RTFx numbers are measured on 1x H200 (141 GB) + 23 vCPU + 256 GB
   RAM.** Confirmed from the leaderboard's own repo. **None of those RTFx figures transfer
   to an RTX 4050 6 GB / i5-12450H.** This invalidates casual use of "RTFx 3332" as
   evidence of anything about our hardware. Propagate this caveat into `BENCHMARKS.md`.

## The strongest new candidate: Nemotron Speech Streaming EN 0.6B

| Property | Value |
|---|---|
| License | **NVIDIA Open Model License** (commercial + non-commercial permitted) |
| Architecture | Cache-Aware FastConformer-RNNT, 24 layers, 0.6B |
| Streaming | **80 / 160 / 560 / 1120 ms configurable chunks, no retraining** |
| Accuracy | 1.12 s chunk: 8-dataset avg **WER 6.93%** (LibriSpeech-clean 2.32%, Earnings22 12.52%). Degrades to **8.43% at 80 ms** |
| Quantized | int4 k-quant 2.47 GB to **0.67 GB**; streaming WER 8.20% vs 7.28% batch; CPU RTFx >6x — **but measured on AMD EPYC 32-core, not laptop CPU** |
| Rust | **Ships via Microsoft Foundry Local with ONNX Runtime GenAI SDK, which lists official Rust bindings** alongside C#/Python/JS/C++ |
| Released | 2026-03-13 |

**Why this matters.** It is the only candidate that potentially solves *streaming +
biasing + first-class Rust integration + commercial license* simultaneously. The
latency/accuracy curve is explicitly tunable, which maps directly onto our 700 ms p95
budget. This should be the leading production candidate to validate in Phase 0.

**Multilingual sibling — different license, verify separately.** Nemotron 3.5 ASR
Streaming 0.6B: license string is **"openmdw-1.1"**, *not* the same as its English sibling.
40 locales (19 transcription-ready). FLEURS at 1.12 s: Spanish 4.11%, English 7.91%,
German 8.31%, French 9.03%; 19-locale avg 8.84%. (Its HF page claims a 2024 release date —
almost certainly a bad fetch artifact; everything else about it is 2026.)

sherpa-onnx ships both as int8 exports:
`sherpa-onnx-nemotron-speech-streaming-en-0.6b-560ms-int8-2026-04-25` and
`sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8-2026-06-11`.

## Other new models

| Model | License | Streaming | Notes |
|---|---|---|---|
| **Qwen3-ASR** (Alibaba, 2026-01-29) | **Apache-2.0** | Unified streaming/offline; vLLM backend streams, transformers backend offline-only | 0.6B / 1.7B. 52 languages (30 + 22 Chinese dialects), LID 97.9%. **WER numbers conflict across sources** (LibriSpeech clean 1.63% vs 1.68%; FLEURS-en 2.94% vs Whisper-large-v3 2.40%) — unverified. GitHub recommends **96 GB RAM** for the reference stack, a red flag against our 15.7 GB |
| **qwen3-asr.cpp** (community GGML port) | **MIT** (weights stay Apache-2.0) | True block-diagonal windowed streaming, 8 s windows, only tail window recomputed | **The only laptop-GPU-class latency numbers found anywhere**: RTX 5060 Laptop 8 GB, **235 ms median latency per 2 s chunk (0.6B)**, 317 ms (1.7B); RTFx 16-21x on AISHELL-1; streaming CER 2.92% approx equals offline. No Rust bindings; no mic input yet; no CUDA CI |
| **Parakeet-Unified-En-0.6b** (2026-04-07) | NVIDIA Open Model License | **Single model does both offline and streaming**, 160-2080 ms configurable | 5.91% WER offline, 15.63% at 80 ms. **English-only** — limits code-switching value |
| **Qwen-Audio-3.0-ASR** (arXiv 2609.07549, Sept 2026) | CC-BY-4.0 *(abstract page only, license text unverified)* | Dedicated "-Streaming" variant | MoE LLM-based. 30 languages + 16 Chinese dialects |

Parakeet TDT 0.6B v3 reconfirmed: CC-BY-4.0, released 2025-08-14, English FLEURS 4.85%,
multilingual avg 11.97% FLEURS / 7.83% MLS / 11.98% CoVoST. GGUF q8_0 exists.

## Licensing traps found

- **SimulStreaming** (the AlignAtt reference implementation for Whisper streaming) is
  **PolyForm Noncommercial 1.0.0**. Commercial use requires negotiating with the authors.
  An initial fetch wrongly reported MIT — corrected on follow-up. **Real trap.**
- **WhisperLiveKit** is Apache-2.0 itself but **defaults to the SimulStreaming backend**, so
  out-of-the-box commercial use likely inherits the non-commercial restriction unless you
  force the LocalAgreement/WhisperStreaming backend.
- **Moonshine** is MIT **except** "legacy non-streaming models for non-English languages",
  explicitly carved out under unspecified alternate terms — which lands precisely on our
  multilingual differentiator. Moonshine v2 specifics could not be verified (JS-rendered
  pages).
- **Nemotron EN vs Nemotron 3.5 multilingual carry different licenses.** Do not assume
  parity between sibling models.

## Streaming decode policies

- **AlignAtt** (Papi et al. 2023) is the current SOTA simultaneous-decoding policy — uses
  encoder-decoder attention to detect a "dangerous zone" near the buffer end and decide
  emit-vs-wait. Reference implementation is the non-commercial SimulStreaming.
- **LocalAgreement** (longest common prefix across consecutive decode updates) is the older
  2023-era policy, still used by WhisperStreaming/Canary/FunASR. **Commercially safe.**
- arXiv 2604.19079 (NVIDIA): consistency regularization closes the offline-streaming gap —
  LibriSpeech test-clean streaming ~3.2% vs offline ~2.1%, improved to ~2.8%. Likely the
  technique behind Parakeet-Unified / Nemotron 3.5's offline-approx-streaming behaviour.
  *Abstract-level, not fully verified.*

## Still completely unresearched

Five sub-agent workstreams returned zero bytes:

- **Non-NVIDIA models**: Kyutai STT, FireRedASR, Distil-Whisper, IBM Granite Speech,
  Canary-Qwen 2.5B, SenseVoice deep-dive — *zero mentions anywhere*.
- **Rust runtime crate maturity**: `whisper-rs`, `ort`, llama.cpp bindings — not assessed.
  (Now covered by the in-flight Rust systems workstream.)
- **GPU execution providers on Windows**: DirectML never mentioned once. CUDA vs DirectML,
  Vulkan viability, signed-installer packaging pain — unaddressed.
- **VAD**: Silero v5/v6, TEN VAD, WebRTC, pyannote — zero coverage.
- **No CPU RTFx numbers on anything resembling an i5-12450H were found anywhere.**

**The voice-command safety transcript contained nothing at all** — the agent was
rate-limited on its first turn, before any tool call. All seven gaps need a fresh run:
Windows agentic-OS security model, Apple App Intents confirmation APIs, voice-attack
literature beyond DolphinAttack, audio/transcript prompt injection, confirmation-fatigue
HCI literature, local speaker verification (models/licenses/EER), and action risk-tier
taxonomies.

## Sources

[Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR) ·
[qwen3-asr.cpp](https://github.com/JohnsonChang123/qwen3-asr.cpp) ·
[Qwen-Audio-3.0 2609.07549](https://arxiv.org/abs/2609.07549) ·
[nemotron-speech-streaming-en-0.6b](https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b) ·
[nemotron-3.5-asr-streaming-0.6b](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b) ·
[parakeet-unified-en-0.6b](https://huggingface.co/nvidia/parakeet-unified-en-0.6b) ·
[SimulStreaming](https://github.com/ufal/SimulStreaming) ·
[WhisperLiveKit](https://github.com/QuentinFuxa/WhisperLiveKit) ·
[sherpa-onnx PR #3895](https://github.com/k2-fsa/sherpa-onnx/pull/3895) ·
[issue #3572](https://github.com/k2-fsa/sherpa-onnx/issues/3572) ·
[open_asr_leaderboard repo](https://github.com/huggingface/open_asr_leaderboard) ·
[arXiv 2604.19079](https://arxiv.org/pdf/2604.19079) ·
[arXiv 2604.14493](https://arxiv.org/html/2604.14493v1)
