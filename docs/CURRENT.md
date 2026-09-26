# Current

The only doc expected to change every session. Read this first when resuming work.

**Last updated:** 2026-09-26

## Recovery checkpoint

**Date:** 2026-09-26. Session interrupted mid-research; this file reconciled against the
filesystem, not against conversation recall.

- **Last successfully persisted memo:** `docs/research/R6-benchmark-methodology.md`
  (written 2026-09-25 11:54).
- **Interrupted workstreams:** the final research wave — **NLP/intent/ITN**,
  **correction pass** (constrained selection vs free generation, GER failure modes, ASR
  confidence estimation), and **voice-command safety**. Filesystem checked: **no output
  from these exists anywhere** — no files, no non-empty agent transcripts, no temporary
  artifacts. They produced nothing and must be run from scratch.
- **Verified intact:** R1–R6 all present and readable, each ending with a complete sources
  section. No truncation, no mojibake, no duplicated headings. D-0001…D-0006 all present.
- **Exact next action in a fresh session:** run the three remaining research workstreams
  (scope in "Remaining research" below). Max 3 concurrent, Sonnet, and **explicitly forbid
  subagents from spawning their own children** — uncontrolled fan-out is what exhausted
  quota on 2026-09-24 and destroyed eleven agents' work.

## Current objective

Finish the three remaining research workstreams, then synthesise centrally and freeze the
cross-subsystem contracts. **No production code until the Phase 0 plan is agreed.**

## Current state

Repository contains **documentation only — zero lines of code.**

```
CLAUDE.md             agent guidance, invariants, vocabulary
README.md             pitch, pipeline summary
docs/PRODUCT.md       market, competitors, wedge, business model
docs/ARCHITECTURE.md  target pipeline design   [CORRECTIONS OWED - see below]
docs/ROADMAP.md       phases with kill/continue checkpoints
docs/BENCHMARKS.md    metrics, datasets, harness  [CORRECTIONS OWED - see below]
docs/CURRICULUM.md    study path
docs/DECISIONS.md     decision log (D-0001..D-0006)
docs/CURRENT.md       this file
docs/research/        R1..R6 research memos
```

One commit (`529cf24`). Everything since is **staged or untracked but on disk** —
`docs/research/` is untracked. Standing instruction: **commit only on request.**

Toolchain: Python 3.11.14, Node 24.14, git 2.53. **Missing: `uv`, `rustup`.**

## Target hardware

i5-12450H (8C/12T) · 15.7 GB RAM · RTX 4050 Laptop **6 GB VRAM** · Windows 11.
CPU-only must be first-class.

**Methodology warning:** Open ASR Leaderboard RTFx figures are measured on 1x H200 +
23 vCPU + 256 GB RAM. **None of those numbers transfer to this hardware.** The only
laptop-GPU-class latency figure found is qwen3-asr.cpp on an RTX 5060 8 GB
(235 ms median per 2 s chunk, 0.6B).

## Research status

| # | Workstream | State |
|---|---|---|
| R1 | Quantization & contextual biasing | **Done** — partially superseded by R4 |
| R2 | Hotkeys & text injection | **Done** |
| R3 | Streaming stability & code-switch LID | **Done** |
| R4 | ASR model landscape (salvaged) | **Done** |
| R5 | Rust stack: Tauri, audio, inference, IPC, persistence | **Done** |
| R6 | Benchmark methodology & harness design | **Done** |
| R7 | NLP, intent, ITN | **Not started** |
| R8 | Correction pass: constrained selection, GER, confidence | **Not started** |
| R9 | Voice-command safety (7 gaps, zero prior coverage) | **Not started** |

## Remaining research — scope for a fresh session

**R7 — NLP, intent, ITN.** Inverse text normalization options for a local Windows app
(NeMo WFST/Pynini — **verify Windows buildability**, deterministic rule engines, neural
punctuation models); which modern ASR models emit punctuation/casing natively and how well.
Intent/command detection hierarchy (rules → classifier → embeddings → small LLM); best
small local embedding models for semantic routing with licences. Local NER worth using in
2026 (GLiNER, spaCy, small transformers). Contextual-biasing vocabulary extraction from a
git repo (tree-sitter vs ctags vs LSP), incremental update strategy, and **documented limits
on bias-list size before accuracy degrades**.

**R8 — Correction pass.** What the 2025–26 literature says actually works for LLM-based ASR
error correction / second-pass rescoring, with measured WER gains and documented failure
modes. **Is there evidence constrained selection beats free generation?** Reference PAC
(arXiv 2509.12647) and newer work. Small local LLM shortlist fitting ~2–3 GB VRAM
(Qwen3 1.7B/4B, Gemma 3, Llama 3.2, Phi-4-mini, SmolLM3) with licences and CPU/GPU speed.
Phonetic candidate generation (g2p_en, phonemizer/espeak-ng — **espeak-ng is GPL, flag the
commercial implication**, CharsiuG2P, neural G2P) and weighted phoneme edit distance.
**ASR confidence estimation** — how to get trustworthy token-level confidence from a
transducer, since the whole correction design depends on it.

**R9 — Voice-command safety.** Zero prior coverage; the earlier agent died before its first
tool call. Seven gaps: Windows agentic-OS/Copilot Actions security model; Apple App Intents
`requestConfirmation`/`authenticationPolicy` as prior art; voice-attack literature beyond
DolphinAttack (hidden voice commands, CommanderSong, adversarial audio, skill squatting,
SurfingAttack); audio/transcript prompt injection; confirmation-fatigue and
warning-habituation HCI literature; local speaker verification (models, licences, EER,
spoofing); action risk-tier taxonomies.

Per-workstream memo template: concrete libraries/runtimes, **licensing**, Windows support,
Rust integration quality, maintenance/activity, latency/accuracy implications,
implementation difficulty for a Rust beginner, and whether the choice is reversible.

## Corrections owed to existing docs (apply during synthesis, not before)

1. **`ARCHITECTURE.md` §6.1 and `CLAUDE.md` both assume injection can be verified by
   read-back. R2 shows it cannot** — every method is unreliable, slow, or blocked by UIPI.
   Replace with: precondition checks (focus stable, integrity level, `IsEnabled`, not a
   password field) + idempotent undoable inserts + never claim unobserved success.
2. `ARCHITECTURE.md` should adopt **UPWR/UPSR** (arXiv 2006.01416) as the flicker metric,
   and record that beam-search biasing **breaks the monotonic-prefix property**, so the UI
   must tolerate already-displayed text being rewritten.
3. `BENCHMARKS.md` should record: the H200 RTFx caveat; the **F-WER decomposition**
   (casing error rate, punctuation F1 per class, ITN slot error rate); the **CI decision
   rule** (paired utterance-level bootstrap ≥2000 resamples with fixed seed, CI excludes
   zero, ≥0.3–0.5pp effect, E-WER non-regression guard, latency p95 as a hard gate); and
   that **n=200 only reliably detects 1–3pp** differences.
4. `ARCHITECTURE.md` should record the R5 process-architecture decision shape: Rust core as
   a **UI-agnostic library crate** from day one so the later daemon extraction is mechanical.

## Known issues / open questions

1. **The central model-selection conflict.** W2 (accents/code-switching) favours Parakeet
   TDT v3 (CC-BY-4.0, 25 langs incl. Ukrainian/Russian). W3 (project vocabulary) needs
   contextual biasing — and **Parakeet TDT is explicitly ignored by NVIDIA's word boosting**.
   Leading resolution: **Nemotron Speech Streaming EN 0.6B** (cache-aware RNNT, configurable
   80–1120 ms chunks, supports boosting, NVIDIA Open Model License, **official Rust bindings
   via ONNX Runtime GenAI / Foundry Local**) — but it is **English-only**, and its
   multilingual sibling carries a *different* licence (`openmdw-1.1`).
2. **`sherpa-rs` is ARCHIVED** (R5). The only Rust binding to sherpa-onnx is dead, so
   sherpa-onnx from Rust means maintaining our own FFI. This is what narrows the production
   path to **`ort` + ONNX Runtime + Nemotron**.
3. **CUDA redistribution is a legal question, not just an engineering one** — cuDNN may not
   be redistributable. **DirectML is the pragmatic default.** Needs a direct read of the
   CUDA EULA and cuDNN SLA before any CUDA-in-installer work.
4. `uiAccess` (for elevated-window injection) requires **Authenticode signing + per-machine
   install into Program Files**, which **kills MSIX and user-local install**. Tauri does not
   address uiAccess; `embed-manifest` 1.5.1 is the candidate fix but is **unverified against
   Tauri's bundler — treat as a half-day spike.**
5. **Transparent + click-through + always-on-top HUD on WebView2/Win11 is unverified** —
   historically a pain point. **Spike early with a throwaway window.**
6. Dataset licence blockers (R6): **GigaSpeech's Apache-2.0 label is misleading** (actually
   non-commercial, binds for-profit employers); **Common Voice moved off HuggingFace to
   Mozilla Data Collective ~Oct 2025**, terms unverified; **TED-LIUM/CHiME/Earnings licences
   unconfirmed**. EdAcc (CC BY-SA 4.0) is verified and is the accent anchor.
7. **No Slavic-English code-switching corpus found.** Plan to collect our own, and say so
   explicitly in any published methodology.
8. Other licensing traps: **SimulStreaming is PolyForm Noncommercial** and WhisperLiveKit
   inherits it by default; **Moonshine's non-English models are carved out of MIT**.
9. sherpa-onnx Nemotron hotword support merged (2026-09-14) **after** the v1.13.8 release
   (2026-09-10) — verify release contents or build from source.
10. Pynini/OpenFst for WFST-based ITN on Windows — still unverified (R7 will settle).
11. Process-boundary latency for the Python sidecar inside a 700 ms p95 budget — unmeasured.
12. Model licensing audit incomplete for non-NVIDIA candidates (Kyutai, FireRedASR,
    Granite Speech, Canary-Qwen, SenseVoice).

## Decisions (full text in `DECISIONS.md`)

- **D-0001** Windows first
- **D-0002** Local-first inference, optional cloud
- **D-0003** Python prototype then Rust core *(partially superseded by D-0006)*
- **D-0004** Flat, purpose-named docs
- **D-0005** Workflow contracts frozen day one, engine deferred past Checkpoint 1
- **D-0006** Rust shell from Phase 1; Python as inference sidecar behind a versioned
  protocol. **Developer has no Rust experience** — favour simple, explicit, teachable
  patterns; keep the Python spike alive as a behavioural reference.

## Next steps

1. Run R7, R8, R9 (scope above). Max 3 concurrent, Sonnet, **no subagent fan-out**.
2. Synthesise centrally: target architecture, Phase 1 architecture, frozen contracts,
   backend selection matrix, risks, benchmark plan, milestones, deferred decisions.
   **Subagents must not define shared contracts.**
3. Apply the four corrections owed above.
4. Present frozen contracts + Phase 1 milestone + first implementation task + the Rust
   prerequisites for that task.
5. Only then write code.
