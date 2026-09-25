# 03 — Roadmap

Status: draft, 2026-09-24.

Each phase has a **kill/continue checkpoint**. The point of a checkpoint is that it can
fail. If a checkpoint fails, the honest move is to change the plan, not to move the goal.

Durations assume part-time solo work with AI assistance. They are planning aids, not
commitments.

---

## Phase 0 — Skeleton and harness (~1 week)

Prove the loop exists end to end, at any quality.

- [ ] Repo scaffold, `uv`-managed Python 3.11 env, ruff + pyright + pytest
- [ ] WASAPI capture → 16 kHz mono f32 ring buffer with 1.5 s pre-roll
- [ ] Low-level keyboard hook, push-to-talk
- [ ] Silero VAD integration, basic endpointing
- [ ] One ASR engine behind the `AsrEngine` interface (start with faster-whisper
      `large-v3-turbo` int8 — easiest to get running, known-good baseline)
- [ ] Clipboard-paste injector with full clipboard save/restore
- [ ] Structured per-stage latency logging
- [ ] **Eval harness v0** (`05-evaluation.md`): WER on a fixed 30-utterance personal set

**Checkpoint 0:** hotkey → speak → text lands in Notepad. Any latency. Nothing else matters.

---

## Phase 1 — Usable daily driver (~3–4 weeks)

The goal is that *you* stop typing. Not that it's shippable.

- [ ] Parakeet TDT 0.6B v3 engine; A/B it against Whisper turbo on the eval set
- [ ] Two-pass: streaming draft shown in HUD, final pass injected on release
- [ ] Injection cascade: UIA → clipboard → SendInput, with read-back verification and a
      persisted per-process strategy table
- [ ] Focus-change guard, password-field refusal, process blocklist
- [ ] ITN (WFST) for English; punctuation and truecasing verified
- [ ] Tray app + HUD overlay (recording state, tier indicator, last transcript, copy button)
- [ ] Per-app profiles for ~10 apps you actually use (terminal, VS Code, browser, Slack)
- [ ] User dictionary, manually editable
- [ ] Latency instrumentation with p50/p95 dashboards; CI fails on p95 regression
- [ ] Device hot-swap handling

**Checkpoint 1 (the real one):**
1. You dictate for 30 consecutive days without reaching for the keyboard out of frustration.
2. Measured formatted-WER beats Windows built-in dictation on your voice by a clear margin.
3. p95 end-to-end latency < 700 ms.

If (1) fails, the product thesis is wrong — stop and re-diagnose. See `01-strategy.md` §8.

---

## Phase 2 — The differentiators (~6–8 weeks)

Now build the two things that make it not-a-clone. Only start this after Checkpoint 1.

**W3 — project-aware vocabulary**
- [ ] Context harvester: window title, process, focused-field text via UIA, clipboard
- [ ] Repo identifier extraction (tree-sitter or ctags) with FS-event cache invalidation
- [ ] Trie-based contextual biasing in the transducer beam search
- [ ] Over-biasing guardrails: confidence-gated activation, homophone-dispersion penalty
- [ ] Correction-capture learning loop → personal dictionary

**W2 — accents and code-switching**
- [ ] Accent-stratified eval set: EdAcc, Common Voice by L1, FLEURS
- [ ] A proprietary code-switching set (record it — this is differentiated data)
- [ ] Benchmark every competitor and every candidate model on it
- [ ] **Publish the benchmark and the harness** (Apache-2.0)

**Correction pass**
- [ ] Phonetic candidate generation (G2P + phoneme edit distance over the bias vocab)
- [ ] Constrained LLM selection pass with edit-distance validation and safe fallback
- [ ] Prove a formatted-WER improvement on the eval set, or cut the feature

**Checkpoint 2:** published benchmark shows Hermes competitive with cloud tools on
accented English while running locally, and code identifiers come out right in your daily
use. If the correction pass shows no WER gain, ship without it.

---

## Phase 3 — Rust core and public release (~8–12 weeks)

Port the hot path once the design has stopped moving. Not before — you'd be porting
decisions you're about to change.

- [ ] Rust `hermesd`: real-time audio thread (lock-free, allocation-free), ring buffer,
      hotkey hook, injection cascade, IPC
- [ ] ONNX Runtime / sherpa-onnx inference in-process
- [ ] Tauri UI replacing the Python tray
- [ ] Signed MSI/MSIX installer, auto-update, crash reporting (content-free)
- [ ] Cold start < 2 s; idle RAM < 300 MB; idle CPU ≈ 0
- [ ] Streaming injection with diff-based correction (behind a flag — see
      `02-architecture.md` §5.3 for why this is risky)
- [ ] Elevated helper service for admin terminals, **with an independent security review**
- [ ] Docs, website, OSS release

**Checkpoint 3:** a stranger installs it and it works in their apps without you present.

---

## Phase 4 — Business (only after Checkpoint 3)

- [ ] Cloud accuracy tier (opt-in, per-utterance tier indicator)
- [ ] Accounts, billing, cross-device sync of dictionary and profiles
- [ ] Translation
- [ ] macOS and Linux ports
- [ ] Team vocabulary, SSO, admin policy
- [ ] On-prem/air-gapped enterprise build
- [ ] SDK

Do not start any of this early. Billing infrastructure built before retention is proven is
pure waste.

---

## Explicit non-goals (for now)

Writing these down prevents scope creep from feeling like progress.

- Meeting transcription / note-taking (Wispr is going there; it's a different product)
- Speaker diarization
- Voice assistant / agentic command execution
- Mobile
- Real-time conversational translation
- Audio file batch transcription (MacWhisper's territory, low strategic value)

## Parallelization

Work that can run concurrently without blocking:

- Eval harness and dataset collection (Phase 0–2) is independent of the app and is the
  highest-leverage thing to start early — everything else is measured against it.
- The accent benchmark (W2) needs no product code at all; it's pure evaluation work.
- The curriculum (`04-curriculum.md`) is sequenced to match the phases — study the DSP and
  CTC/RNN-T material during Phase 0–1, biasing and LLM-rescoring literature during Phase 2,
  real-time systems and Rust during Phase 3.
