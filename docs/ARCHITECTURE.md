# 02 — Architecture

Status: draft, 2026-09-24.

This describes the target system. `ROADMAP.md` says which parts get built when.
Nothing here is built yet.

> **`SYNTHESIS.md` (2026-09-26) supersedes this document where they disagree.** It corrects
> §1 (VRAM budget), §5.3 (stability metric), §5.5 (PAC citation; correction pass deferred out
> of Phase 1), §5.6 (ITN is a rule cascade, not WFST/Pynini), and §6.1 (injection is
> precondition-checked, not read-back-verified). Read it first.

## 0. Design principles

1. **The model is a replaceable part.** SOTA ASR turns over every ~6 months. Every model
   sits behind an interface; swapping Parakeet for whatever ships in 2027 must be a config
   change, not a refactor.
2. **Latency is a feature, not a metric.** Anything the user perceives as lag destroys the
   "faster than typing" premise. Budget it explicitly (§8) and regression-test it.
3. **Never lose audio.** A dropped first word is worse than a 200ms slower result. Ring
   buffer with pre-roll, always.
4. **Never corrupt the user's state.** Wrong text is recoverable; a clobbered clipboard, a
   keystroke sent to the wrong window, or text injected into a password field is not.
5. **Correctness is measured, not asserted.** No pipeline change merges without a WER /
   latency delta from the eval harness (`BENCHMARKS.md`).
6. **Local by default, cloud by consent, and the UI always says which ran.**

## 1. Target hardware

Development machine: i5-12450H (8C/12T), 15.7 GB RAM, **RTX 4050 Laptop, 6 GB VRAM**.

6 GB is the binding constraint and it is a *useful* one — it's roughly the low end of what
a target user has, so designing within it keeps the product broadly deployable. Budget:

| Component | VRAM (int8/int4) | Notes |
|---|---|---|
| Silero VAD | ~0 (CPU) | ~1 MB ONNX, runs on CPU in <1 ms/chunk |
| Parakeet TDT 0.6B v3 | ~0.8 GB | Streaming draft + final pass |
| Whisper large-v3-turbo (CT2 int8) | ~1.5 GB | Accuracy tier, 99 languages |
| Correction LLM (Qwen3-4B int4) | ~2.5 GB | **Not in Phase 1** — see §5.5 and D-0009 |
| **Total worst case** | **~4.8 GB** | Fits, barely. Anything larger goes cloud. |

**Revised Phase 1 budget (`SYNTHESIS.md` §11): ~0.7 GB** — Silero VAD on CPU plus one
streaming ASR model. The 4.8 GB figure was driven by a correction LLM that no longer ships in
Phase 1. The headroom is real but must be *earned* by measurement, not filled because it
is free.

A CPU-only path must also work (Moonshine v2 / Parakeet ONNX int8 hit RTFx > 6 on CPU —
*a published figure; measured here, Parakeet int8 runs at RTF 0.47, i.e. RTFx ≈ 2.1, on the
i5-12450H at 4 threads, whole-utterance decode — `docs/research/T2A-screening.md`*),
because a large share of Windows laptops have no usable discrete GPU. Treat CPU-only as a
first-class configuration, not a degraded fallback.

## 2. Process topology

```
┌──────────────────────────────────────────────────────────┐
│  hermesd  (background service, no window)                │
│                                                          │
│  ┌────────────┐   ring    ┌─────────┐    ┌────────────┐  │
│  │  Capture   │─ buffer ─▶│ Frontend│───▶│    ASR     │  │
│  │  (WASAPI)  │  pre-roll │ VAD/DSP │    │  engines   │  │
│  └────────────┘           └─────────┘    └─────┬──────┘  │
│        ▲                                       │         │
│  ┌─────┴──────┐                          ┌─────▼──────┐  │
│  │  Hotkey    │                          │  NLP post- │  │
│  │  listener  │                          │  processor │  │
│  └────────────┘                          └─────┬──────┘  │
│                                                │         │
│  ┌────────────┐   context   ┌───────────┐┌─────▼──────┐  │
│  │  Context   │────────────▶│  Biasing  ││  Injector  │  │
│  │  harvester │             │  store    │└─────┬──────┘  │
│  └────────────┘             └───────────┘      │         │
└─────────────────────────────────────────────── │ ────────┘
         ▲ IPC (named pipe / localhost)          │
┌────────┴─────────┐                             ▼
│  hermes-ui       │                      target application
│  (tray + HUD +   │
│   settings)      │
└──────────────────┘
```

**Why two processes:** the UI must be able to crash, restart, or be updated without
dropping the audio thread or the loaded models (model load is seconds; users will not
tolerate that per-utterance). The daemon holds all state; the UI is a thin client.

**Phasing (R5, and the single most important structural discipline here):** Phase 1 ships
*Tauri-as-daemon* — one process to build, sign, install and version — **but the Rust core
(audio, ring buffer, orchestrator, injection, IPC client) is written as a UI-agnostic library
crate from day one**, with `main()` in the Tauri binary doing nothing but calling into it. The
later extraction of a separate slim daemon is then mechanical rather than a rewrite.

**The Rust/Python process boundary is also the safety boundary** (`SYNTHESIS.md` §1, §10): the
inference sidecar can only emit serialized values across a socket, so it structurally cannot
execute anything. Preserve that separation when the sidecar is later replaced by in-process
Rust inference — at that point it stops being enforced by the OS.

**Threading inside `hermesd`:**

- **Audio thread** — real-time priority, lock-free, allocation-free. Touches only the ring
  buffer. Any `malloc`, `log`, or mutex here is a bug that manifests as audio dropouts.
- **Inference thread(s)** — owns model handles, pulls from the ring buffer.
- **Orchestrator** — async, owns the state machine, IPC, context harvesting, injection.

This split is why the Rust port matters (D-0003): Python's GIL plus GC makes a genuinely
real-time audio thread awkward. For the Phase 0/1 prototype, `sounddevice`'s C callback
with a `numpy` ring buffer is good enough to validate the pipeline.

## 3. Activation and the session state machine

```
      ┌────────────────────────────────────────────┐
      │                                            │
  ┌───▼───┐  hotkey down  ┌───────────┐  endpoint  │
  │ IDLE  │──────────────▶│ LISTENING │────────────┤
  └───────┘               └─────┬─────┘            │
      ▲                         │ hotkey up        │
      │                   ┌─────▼──────┐           │
      │      inject ok    │ FINALIZING │           │
      └───────────────────┴─────┬──────┘           │
                                │ inject failed    │
                          ┌─────▼──────┐           │
                          │  RECOVERY  │───────────┘
                          │ (clipboard │
                          │  fallback) │
                          └────────────┘
```

**Activation modes** (all three, user-selectable — people disagree strongly about this):

- **Push-to-talk (hold)** — default. Lowest cognitive load, no accidental activation.
  Requires a low-level keyboard hook (`WH_KEYBOARD_LL`); `RegisterHotKey` cannot express
  hold semantics or modifier-only chords.
- **Toggle** — for long-form dictation. Needs a visible always-on indicator or users
  forget it's live. Privacy hazard; must auto-timeout.
- **Voice-activated** — VAD-gated, no hotkey. Convenient and dangerous; off by default.

**Pre-roll is mandatory.** The ring buffer continuously retains the last **1.5 s** of audio
even in IDLE. When the hotkey fires, the utterance starts 1.5 s *in the past*. Users
habitually begin speaking a beat before or as they press; without pre-roll you clip the
first word and the product feels broken. Cost: a 48 kB buffer and a clear statement in the
privacy policy that the rolling buffer is never persisted.

**Elevated-window caveat:** a medium-integrity keyboard hook does not receive keys while an
elevated window has focus. See §6.4.

## 4. Capture and front-end DSP

| Stage | Choice | Rationale |
|---|---|---|
| API | WASAPI shared mode, event-driven | Low latency without exclusive-mode device grabbing |
| Format | Device native → **16 kHz mono f32** | All ASR models want 16 kHz; resample once, centrally |
| Resampler | soxr / libsamplerate VHQ | Cheap sinc resampling; naive decimation costs real WER |
| Gain | Loudness-normalize to a fixed RMS target; **disable OS AGC** | AGC pumping during pauses confuses VAD and hurts WER |
| VAD | **Silero VAD v5** (ONNX, CPU) | ~1 MB, sub-ms, far better than WebRTC VAD on noise |
| Denoise | DeepFilterNet3, **off by default, gated behind an A/B** | Denoisers frequently *increase* WER by removing cues the acoustic model uses. Never ship it on a hunch — measure. |

**Endpointing** (deciding the utterance ended) is its own tuned component, not a fixed
silence threshold. Trailing-silence timeout should adapt to the user's speech rate and to
whether the last token looks sentence-final. Too eager truncates mid-thought; too lazy adds
dead latency to every single utterance. This one parameter has an outsized effect on
perceived quality.

**Device hot-swap:** Bluetooth headsets connect and disconnect mid-session constantly.
Handle `IMMNotificationClient` device-change events and re-open the stream without dropping
the session.

## 5. Recognition and language processing

### 5.1 The engine interface

```python
class AsrEngine(Protocol):
    name: str
    supports_streaming: bool
    languages: set[str]

    def warmup(self) -> None: ...
    def stream(self, audio: AudioStream, ctx: BiasContext) -> Iterator[PartialResult]: ...
    def transcribe(self, audio: AudioBuffer, ctx: BiasContext) -> AsrResult: ...
```

`AsrResult` must carry **token-level confidences and an N-best list**, not just a string.
The correction layer (§5.5) is useless without them, and most wrappers throw them away —
check this before adopting any library.

### 5.2 Model tiers

| Tier | Model | Why |
|---|---|---|
| **Draft (streaming)** | Parakeet TDT 0.6B v3 | RTFx in the thousands; 25 languages; emits punctuation and casing natively; ~9.7% multilingual WER — ahead of whisper-large-v3's 9.9% at a fraction of the cost |
| **Final (local)** | Same model, full-utterance pass with full right context | A second pass over the complete utterance beats streaming output measurably, for ~100 ms |
| **Accuracy (local)** | Whisper large-v3-turbo, CT2 int8 | 99 languages; the fallback when the draft's confidence is low or the language is outside Parakeet's 25 |
| **Ceiling (cloud, opt-in)** | Canary-Qwen 2.5B (5.63% WER, current Open ASR Leaderboard #1) or a hosted API | Only on explicit escalation |
| **CPU-only** | Moonshine v2 / Parakeet ONNX int8 | Sliding-window attention, bounded latency, RTFx > 6 on CPU (published; measured RTFx ≈ 2.1 for Parakeet here — §1) |

Canary-Qwen is **English-only** — do not let it become the default path, or W2 (accents and
multilingual) silently dies.

### 5.3 Two-pass streaming

Emit a fast draft so words appear while the user speaks, then replace it with a
better-informed final transcript on release. The final pass sees the whole utterance
(right context), the full bias list, and can afford a heavier model.

**Stability metric: UPWR / UPSR** (Shangguan et al., arXiv 2006.01416) — Unstable Partial
Word Ratio and Unstable Partial Segment Ratio. Adopt these rather than inventing a "flicker
rate"; they are the peer-reviewed formalisms and they belong in `BENCHMARKS.md`.

**Beam-search biasing breaks the monotonic-prefix property.** Quoting sherpa-onnx PR #3895:
*"The best path can revise earlier text between chunks (inherent to beam) — greedy's
monotonic-prefix property does not hold."* The HUD must therefore tolerate already-displayed
text being rewritten, and the partial-hypothesis contract must carry an explicit stable-prefix
length. This is a design constraint, not a detail.

The catch: if the draft was already *injected* into the target app, the final pass must
express itself as a **diff** and apply it as backspaces + retype — and it must abort if
focus changed in the meantime. This is genuinely risky and belongs in Phase 3, not Phase 1.
Phase 1 shows the draft in the HUD only and injects once, on finalize.

### 5.4 Context harvesting and biasing — the core differentiator

Generic ASR cannot spell `useMemo`, `kubectl`, `tokio::sync::mpsc`, or a colleague's
surname. It can if you tell it what words are plausible *right now*. Sources, cheapest
first:

| Source | Signal | Cost |
|---|---|---|
| Active window title + process name | App identity, current file, repo name | ~0 |
| Focused control's existing text (UIA `TextPattern`) | Immediate linguistic context | low |
| Clipboard | What the user just copied is very likely to be said | ~0 |
| **Identifiers from the open git repo** | Function/variable/file names — ctags or tree-sitter over the working tree, cached and invalidated on FS events | moderate, amortized |
| User dictionary | Names, jargon, product terms | ~0 |
| **Learned corrections** | Every time the user fixes injected text, that's a free label | ~0 |
| Recent dictation history | Topic continuity across utterances | ~0 |

Applied two ways:

- **Shallow fusion / trie-based boosting** during beam search for the transducer path —
  TurboBias-style streaming context biasing, which is designed for exactly this
  (thousands of bias phrases, production latency).
- **Prompt injection of the bias list** into the LLM second pass (§5.5).

Two failure modes to design against from day one:
1. **Over-biasing** — a boosted term starts appearing when it wasn't said. Mitigate with
   confidence-gated activation and homophone-dispersion penalties.
2. **Privacy** — harvesting the focused field and clipboard means reading potentially
   sensitive text. This never leaves the machine, an app blocklist (password managers,
   banking) disables harvesting entirely, and the policy must state it plainly.

### 5.5 The correction pass — "double-check similar-sounding words"

This is the feature that makes output feel *authored* rather than transcribed, and it is
the easiest place in the whole system to make things worse. An unconstrained LLM asked to
"fix this transcript" will paraphrase, and users will not forgive silently altered meaning.

**Design it as constrained candidate selection, not free generation:**

1. From the ASR result, find spans whose token confidence is below threshold.
2. For each span, generate phonetically-near candidates: G2P the span, then search the bias
   vocabulary and a pronunciation lexicon by **phoneme edit distance**. (`kubectl` vs
   "cube control"; `useMemo` vs "use memo"; `Kyiv` vs "keev".)
3. Give the LLM: the full hypothesis, the flagged spans, their ranked candidates, the app
   context, and the recent history. Ask it to **select**, not to write.
4. **Validate the output before accepting it.** Reject any correction that (a) exceeds an
   edit-distance budget, (b) alters a high-confidence content word, or (c) changes the
   token count beyond a tolerance. On rejection, keep the original. Silent fallback to the
   unedited transcript is always the safe move.

**Phase 1 ships none of this (D-0009, `SYNTHESIS.md` §9).** Two independent findings, either
sufficient alone:

1. **It does not fit the latency budget on this hardware, at any model size.** Measured on our
   exact GPU class (RTX 4050 Laptop 6 GB, LocalScore): Llama-3.2-1B Q4_K_M has **301 ms
   time-to-first-token**; Gemma-3-4B has 1.28 s. The correction budget is 150 ms p95. TTFT
   alone exceeds it before one output token exists, and TTFT is prefill-bound — shortening the
   output does not help.
2. **The confidence signal that would gate it is uncalibrated.** NeMo computes token confidence
   (entropy beats max-prob by 2–4x at detecting wrong words on Conformer-RNNT), but nothing
   claims calibration, no trained confidence head ships, and none of it was measured on
   accented or code-switched speech — our actual user.

What Phase 1 *does* ship: entropy-based word confidence in `AsrResult`, and **visual
highlighting of low-confidence spans**. Highlighting needs only relative discrimination, which
is exactly what the evidence supports. Any LLM call is deferred to an async, user-requested
path at the earliest.

**Citation correction:** earlier drafts cited **PAC (arXiv 2509.12647)** as the basis for this
design. PAC is an audio-in LLM-ASR *model* with G2P-interleaved training, not a text-only
post-hoc corrector; it is not evidence about correcting a separate ASR's output. The
phoneme-interleaving idea remains reusable for phonetic candidate generation. The design is
instead supported by Apple's specialized-corrector result (arXiv 2405.15216), LCAR's
constrained reranking, and RLLM-CF.

Local model, if and when it ships: Qwen3-1.7B (Apache-2.0, 1.28 GB Q4_K_M) or Qwen3-4B int4.
**Measure the F-WER delta**: if the correction pass doesn't reduce formatted-WER on the eval
set, it is net harm, and shipping it because it's impressive-sounding is how products get
worse. The pass remains explicitly on probation.

### 5.6 The rest of the NLP layer

| Component | Approach | Notes |
|---|---|---|
| **ITN** (inverse text normalization) | **Hand-written rule cascade** (tagger→verbalizer shape, no Pynini) | "twenty twenty six" → "2026", "three p m" → "3 PM". Deterministic and debuggable — do not delegate this to an LLM. **Pynini/OpenFst is ruled out at runtime** (R7): no first-party Windows wheel, no first-party MSVC build; the only working paths are conda-forge, WSL, or third-party rebuilds, none acceptable under a signed installer. `rustfst` is the engine if a native WFST is ever wanted. **Aggressiveness is gated per-application** — "dash dash interactive" → `--interactive` is right in a terminal and wrong in Slack. That gating is our own invention and ships with its own eval, not as a known-good pattern. |
| **Punctuation + truecasing** | Native from Parakeet TDT v3; small BERT-class fallback | |
| **Disfluency removal** | Toggleable, conservative | Removing "um" is safe; removing false starts changes meaning. Off in code mode. |
| **Command vs. dictation** | Grammar + small intent classifier | "new paragraph", "scratch that", "select last sentence". Needs a literal-escape ("literally new paragraph"). |
| **Code formatting mode** | Rule-based | "camel case user name" → `userName`; "snake case max retries" → `max_retries` |
| **Translation** | Whisper/Canary X→En natively; NLLB-200 or LLM for En→X | Opt-in per profile |

### 5.7 Per-app profiles

Dictating into a terminal, Slack, an IDE, and a Word document are four different tasks.
A profile selects ASR mode, ITN aggressiveness, punctuation policy, disfluency handling,
and injection strategy, keyed on process name. Ship sensible defaults for the top ~30 apps;
let users override; learn from corrections.

Terminal profile, for example: no trailing period, no auto-capitalization, aggressive
code-identifier biasing, command-mode grammar enabled.

## 6. Output — text injection on Windows

The single hardest engineering problem in the product, and where competitors visibly fail.

### 6.1 The strategy cascade

| # | Method | Works | Fails |
|---|---|---|---|
| 1 | **UIA `TextPattern`/`ValuePattern` insert** | Native Win32, WinUI, WPF, many editors. Cleanest — talks to the app's real text model, no keystroke side effects | Inconsistent in Chromium/Electron; silently no-ops in some |
| 2 | **Clipboard + Ctrl+V** | Broadest compatibility, fast for long text | Clobbers the clipboard; some apps read it asynchronously, creating a race; paste is intercepted in some terminals |
| 3 | **`SendInput` + `KEYEVENTF_UNICODE`** | Works where paste is intercepted; no clipboard side effects | Slow for long text; drops characters under load; broken in some games and terminals |

**Correction (R2): injection success is not verifiable in general.** Every read-back method
fails somewhere that matters — `ValuePattern` readback exists only where failure was least
likely; `TextPattern.GetText` is cross-process COM costing tens to hundreds of milliseconds and
is frequently stale in Chromium/Electron; `WM_GETTEXT` is Win32-only and UIPI-blocked;
clipboard comparison proves only that *we* set the clipboard. UIA `TextChanged` is the best
available signal but is advisory and not universally raised.

**Check preconditions, not postconditions:**

1. Before injecting: foreground HWND stable since activation, target integrity level <= ours,
   focused element `IsEnabled && IsKeyboardFocusable`, not a password field, not blocklisted.
2. Every injection is **idempotent and undoable** — one utterance is one atomic insert the user
   can Ctrl+Z.
3. Recognized text stays in our own history UI, so a silent failure is recoverable.
4. **Never report success we did not observe.** Detecting "target is elevated and I am not"
   *before* injecting, and saying so, beats a silent drop.

Choose per app and **remember**: attempt the preferred strategy, fall back on precondition
failure or exception, and persist the winning strategy for that process name. Over a few days
this converges to a per-machine compatibility table that's better than anything shipped in the
box.

**Revised role for UIA: inspection, not insertion.** `SetValue` replaces the entire control's
contents, but dictation needs insertion at the caret; read-splice-write is racy, destroys undo
history, and breaks IME composition. Use UIA to identify the focused element and decide a
strategy, not to write text.

### 6.2 Clipboard hygiene

If clipboard-paste is used: snapshot, write ours with a custom marker format, paste, wait for
the app to consume it, restore. Losing a user's copied image or rich text to a dictation tool is
an uninstall-grade bug. Add a bounded retry and always restore in a `finally`.

**Full snapshot/restore is not achievable** (R2). Delayed rendering means enumerating formats
forces a synchronous `WM_RENDERFORMAT` in the owner process — a hung owner hangs *us*, and a
4-byte promise can materialize as a 200 MB DIB. `CF_OWNERDISPLAY` has no snapshottable payload.
Restoring makes us the owner, and `EmptyClipboard` notifies the original owner, which may free
what we are restoring. `OpenClipboard` is a single global lock, so **retry with backoff is
mandatory**. Practical rule: snapshot only `CF_UNICODETEXT`, `CF_HDROP`, `CF_DIB`/`CF_DIBV5`
and registered HTML/RTF; accept lossiness elsewhere and document it.

**Privacy requirement, not an optimization:** register
`ExcludeClipboardContentFromMonitorProcessing`, `CanIncludeInClipboardHistory` (0) and
`CanUploadToCloudClipboard` (0), or Windows Clipboard History and Cloud Clipboard capture every
dictated utterance.

### 6.3 Never inject into the wrong place

Before injecting, re-check that the focused window is still the one that was focused at
activation. If focus moved, do not inject — surface the text in the HUD with a copy button.
Additionally, **refuse to inject into password fields** (UIA `IsPassword`) and into
blocklisted processes.

### 6.4 UIPI and elevated processes

A medium-integrity process cannot send input to, or drive UIA in, a high-integrity process.
This is a Windows security boundary, not a bug to work around cleverly. So dictation into
an elevated terminal — a thing developers do constantly — fails in every competing product.

Options, in order of preference:
1. Document the limitation and degrade gracefully (HUD + copy button). Correct, unsatisfying.
2. Ship a **separate, signed, elevated helper** that the user installs deliberately, with a
   narrow IPC surface that accepts only "insert this text into the foreground window".
   This is a real attack surface and must be designed as such: authenticated pipe, caller
   verification, no arbitrary input replay, rate limits, audit log.
3. Run the whole daemon elevated. **No** — it makes every other component a privilege
   escalation risk.

Option 2 is the differentiator, but it is a Phase 3+ item and needs a security review
before it ships. Option 1 is what Phase 1 does.

## 7. Learning loop

When the user edits injected text within a few seconds of injection, in the same field,
that edit is a **free supervised label**. Capture (original audio hash, hypothesis, final
text) locally. Use it to:

1. Populate the personal dictionary and bias list (immediate, high value).
2. Tune per-app profile settings (medium term).
3. Build a personal fine-tuning / LoRA corpus (long term, opt-in, on-device).

This compounds: the product gets measurably better the more you use it, which is both a
retention mechanism and something a cloud competitor can only replicate by storing your
text on their servers.

## 8. Latency budget

Target for a 5-second utterance, hotkey-release to text-on-screen:

| Stage | p50 | p95 |
|---|---|---|
| Endpoint detection | 80 ms | 150 ms |
| Final ASR pass | 120 ms | 300 ms |
| NLP post-processing (ITN, punctuation) | 20 ms | 50 ms |
| Correction pass (when enabled) | 60 ms | 150 ms |
| Injection | 20 ms | 50 ms |
| **Total** | **~300 ms** | **~700 ms** |

Instrument every stage from day one and treat a p95 regression as a build failure. Latency
is the thing users feel before they notice accuracy.

## 9. Security and privacy posture

- Everything local by default; no network calls unless the user enables a cloud tier, and
  the HUD indicates the tier on every utterance.
- The rolling pre-roll buffer is memory-only, never written to disk.
- Audio is discarded after transcription unless the user opts into keeping it for the
  learning loop.
- Blocklist: password managers, banking sites, and any user-specified process — no capture,
  no context harvesting, no injection.
- Telemetry, if any, is opt-in and content-free (latencies, error codes, model IDs — never
  transcripts).
- The elevated helper (§6.4) gets an independent security review before release.

## Sources

- [Open ASR Leaderboard: multilingual & long-form tracks](https://huggingface.co/blog/open-asr-leaderboard) · [paper](https://arxiv.org/abs/2510.06961)
- [Canary-1B-v2 & Parakeet-TDT-0.6B-v3](https://arxiv.org/pdf/2509.14128)
- [TurboBias 2.0: streaming context biasing](https://arxiv.org/pdf/2608.21343)
- [Moonshine v2: ergodic streaming encoder ASR](https://huggingface.co/papers/2602.12241)
- [Pushing the limits of on-device streaming ASR (Microsoft)](https://arxiv.org/abs/2604.14493)
- [PAC: pronunciation-aware contextualized LLM ASR](https://arxiv.org/pdf/2509.12647)
- [Injecting text into any Windows app, including elevated processes](https://dev.to/howmindswork/how-i-inject-text-into-any-windows-app-including-elevated-processes-4jl6)
- [UI Automation — Microsoft Learn](https://learn.microsoft.com/en-us/windows/apps/dev-tools/winapp-cli/ui-automation)
