# Decisions

Architectural decisions and why they were made. Append-only: supersede entries, don't
rewrite history. Newest last.

Format: context → decision → rationale → consequences. Keep each entry short; the detail
belongs in `ARCHITECTURE.md`.

---

## D-0001 — Windows first

**Status:** accepted · 2026-09-24

**Context.** The platform layer (audio capture, global hotkeys, text injection) is a large
fraction of total effort and differs completely per OS. Building three at once triples the
hardest work before any of it is proven. The good local-first dictation products
(Superwhisper, MacWhisper, VoiceInk) are macOS-only; the cross-platform ones (Wispr Flow,
Aqua) are cloud-first. Windows has the weakest native dictation and the thinnest local
third-party options.

**Decision.** Windows 11 first. macOS and Linux deferred to Phase 4.

**Rationale.** Largest gap vs. the OS baseline; thinnest competition in the local niche;
the developer's machine is Windows 11 and the developer is user zero. The hardest Windows
problem — injection into Electron apps and elevated processes — is exactly the unglamorous
work a funded consumer competitor deprioritizes, which makes it defensible.

**Consequences.** Lower paying-user density than macOS for this category today; accepted,
because the beachhead is technical users, who are well represented on Windows. Core logic
must stay behind platform traits from day one so the later port is mechanical — **no Win32
types in pipeline code**. UIPI limits injection into elevated processes: Phase 1 degrades
gracefully, Phase 3 ships a signed helper.

---

## D-0002 — Local-first inference, optional cloud

**Status:** accepted · 2026-09-24

**Context.** Fully offline, cloud-first, or local-first with opt-in escalation. This is
simultaneously an architecture decision and the market position. Cloud-first buys the best
accuracy per engineering hour and easy multilingual coverage, at the cost of per-user GPU
spend, a latency floor, no offline use, and direct competition with a company that raised
$280M to do exactly that.

**Decision.** Local-first. All core functionality runs on-device with no network. A cloud
accuracy tier is opt-in, per-utterance, and always indicated in the UI.

**Rationale.** Privacy here is not compliance theatre — it *unlocks the main accuracy
feature*. Context harvesting (reading the focused field, clipboard, and the open repo's
identifiers) is only defensible if the data never leaves the machine, so a cloud product
structurally cannot offer it. Zero marginal cost per user also makes a free OSS tier
sustainable, which is the open-core strategy in `PRODUCT.md` §5.

**Consequences.** Constrained to models fitting ~5 GB VRAM, with a first-class CPU-only
path. Some hard audio and rare languages will be worse than cloud — mitigated by opt-in
escalation, stated honestly in the UI rather than hidden. Model distribution, versioning,
integrity verification, and disk usage become our problem. User hardware variance becomes a
support surface.

---

## D-0003 — Python prototype, then Rust core

**Status:** accepted · 2026-09-24

**Context.** The product needs a real-time audio thread, small binary, low idle RAM, and
fast cold start — all arguments for Rust. But the pipeline design is unproven: model
choice, biasing approach, correction strategy, and injection cascade will all change
substantially during early phases. Writing that exploration in Rust means porting decisions
that are about to be discarded.

**Decision.** Phases 0–2 in Python 3.11. Phase 3 ports the hot path (`hermesd`) to Rust
with a Tauri UI. **The architecture must never depend permanently on Python.**

**Rationale.** ML experimentation velocity in Python is several times higher, and the early
phases are almost entirely experimentation. The Python prototype is throwaway *by design*,
which makes it cheap to be wrong. By Phase 3 the design has stabilized and the port is
mechanical. The genuine Rust wins all land in Phase 3 anyway.

**Consequences.** A rewrite is scheduled, not avoided; `ROADMAP.md` accounts for it. The
Python code must keep clean seams at exactly the boundaries the Rust version will have, or
the port stops being mechanical — enforce in review. Rust toolchain is not yet installed;
install `rustup` at the start of Phase 3, not before.

**Alternatives rejected.** Rust from day one (early iteration slows to a crawl in the phases
that need speed). Python + Electron throughout (300 MB+ app, high idle RAM, unacceptable for
an always-on service). C++ core (maximum control, slowest to write, smallest contributor
pool for an open-core project).

---

## D-0004 — Documentation layout

**Status:** accepted · 2026-09-24

**Context.** Initial planning used numbered docs (`01-strategy.md` … `05-evaluation.md`)
plus a `decisions/` directory of individual ADR files.

**Decision.** Flat, purpose-named docs: `PRODUCT.md`, `ARCHITECTURE.md`, `ROADMAP.md`,
`BENCHMARKS.md`, `CURRICULUM.md`, `DECISIONS.md` (this file), `CURRENT.md`. Individual ADR
files consolidated here.

**Rationale.** Numbers encode a reading order that stops being true. One decision log is
easier to scan than a directory of files when the count is small; revisit if it exceeds
~30 entries.

**Consequences.** `CURRENT.md` is the only doc expected to churn every session and is the
first thing to read when resuming work.

---

## D-0005 — Workflow engine: freeze the seam, defer the engine

**Status:** accepted · 2026-09-24

**Context.** The product brief adds an intent/workflow/action engine (speech → intent →
validated action → execution). Earlier planning listed voice commands and agentic execution
as explicit non-goals. Both positions are defensible; leaving the conflict unresolved would
have poisoned the contract design, since it determines whether `Intent` and `WorkflowAction`
are core types or a bolt-on.

**Decision.** The **contracts** include the full chain — `NlpResult → Intent →
WorkflowAction → policy layer → execution` — from day one. The **engine** ships no actions
until dictation quality clears Checkpoint 1. Until then the intent layer exists but always
resolves to "this is literal dictation".

**Rationale.** The seam is cheap now and expensive to retrofit: an action engine bolted onto
a pipeline that assumed text-only output means reworking the ASR→NLP boundary, the
permission model, and the UI event flow. The engine itself is a second product competing
for the same scarce weeks, and dictation that isn't excellent makes voice commands
*actively dangerous* — a misrecognized command executes something.

**Consequences.** `Intent` and `WorkflowAction` are first-class types with no first-class
implementations for now. The policy/permission layer is specified before any action can
execute. Default interpretation is always literal text; command detection must clear a high
confidence bar and is opt-in per profile. Model output never executes anything directly — it
produces a validated, allowlisted structured action that a policy layer approves.

---

## D-0006 — Rust shell from Phase 1; Python as an inference sidecar

**Status:** accepted · 2026-09-24 · **partially supersedes D-0003**

**Context.** D-0003 deferred all Rust to Phase 3. That conflates two very different kinds of
work. Audio capture, global hotkeys, text injection, tray, and persistence are *platform*
work: they gain nothing from Python's iteration speed, and building them in Python means
building them twice. Only the ML layer — model selection, decoding params, biasing,
correction — actually benefits from a fast experiment loop.

**Decision.** The seam runs between **platform (Rust) and inference (Python, for now)**,
not between phases.

- **Phase 0** stays a pure-Python throwaway spike: ~1 week, validates model choices and
  seeds the eval set. Explicitly disposable.
- **Phase 1** builds the Tauri/Rust shell owning audio, hotkeys, injection, state, IPC and
  UI. Python is demoted to an ASR/NLP sidecar behind a versioned wire protocol.
- **Later** the sidecar is replaced by in-process Rust inference (whisper.cpp / ONNX Runtime
  / sherpa-onnx) with **no change to the protocol or to any other subsystem.**

**Rationale.** The wire protocol *is* the stable interface the brief requires. It makes the
Python dependency provably temporary rather than aspirationally temporary: if the protocol
holds, the sidecar is swappable by construction. It also front-loads the genuinely hard and
genuinely durable work (injection, real-time audio) instead of discovering its constraints
late.

**Consequences.** Phase 1 is longer and harder than under D-0003, and **the developer has no
Rust experience** — so Phase 1 must be heavily scaffolded, favour simple patterns over
idiomatic-but-dense ones, and keep the Python spike alive as a working reference
implementation to diff behaviour against. Rust moves to the front of `CURRICULUM.md`.
`rustup` is now a Phase 1 prerequisite, not Phase 3. Process-boundary latency
(serialization + IPC) becomes a measured quantity with its own budget; if it proves
significant, in-process inference moves earlier.

**What survives from D-0003.** Python remains the experimentation layer, the architecture
must never depend permanently on Python, and the Phase 0 spike is still throwaway by design.

---

## D-0007 — Injection is precondition-checked, not read-back-verified

**Status:** accepted · 2026-09-26 · **supersedes the verification claim in `ARCHITECTURE.md`
§6.1 and in `CLAUDE.md`**

**Context.** The original design said: inject, read back via UIA to confirm the text landed,
fall back on failure. R2 established that this is not achievable. `ValuePattern` readback
exists only where failure was least likely. `TextPattern.GetText` is cross-process COM costing
tens to hundreds of milliseconds and is frequently stale in Chromium/Electron. `WM_GETTEXT` is
Win32-only and UIPI-blocked. Clipboard comparison proves only that we set the clipboard. UIA
`TextChanged` is advisory and not universally raised.

**Decision.** Verify **before**, not after. Preconditions: foreground HWND stable since
activation, target integrity level ≤ ours, focused element `IsEnabled && IsKeyboardFocusable`,
not a password field, not blocklisted. Every injection is one atomic, Ctrl+Z-undoable insert.
Recognized text is retained in our own history. **We never report success we did not observe.**
UIA's role becomes inspection and strategy selection, never insertion.

**Rationale.** A verification step that returns false negatives is worse than none — it
triggers spurious fallbacks that double-insert text. Detecting an impossible injection *before*
attempting it, and saying so plainly, is both more honest and more useful than a silent drop.

**Consequences.** The per-process strategy table is learned from precondition failures and
exceptions rather than from read-back results, so it converges more slowly. The UI must carry a
visible transcript history with a copy button as the recovery path, which is now load-bearing
rather than a nicety. `InjectionResult` deliberately has no `success: bool`.

---

## D-0008 — No Pynini/OpenFst at runtime; ITN is a hand-written rule cascade

**Status:** accepted · 2026-09-26 · closes open question #10

**Context.** The architecture specified WFST/Pynini grammars (NeMo-style) for inverse text
normalization. Whether that is buildable and shippable on Windows has been open since
2026-09-24. R7 settled it: Pynini's own documentation links a Stack Overflow post as its only
Windows resource; there is no first-party PyPI `win_amd64` wheel and no first-party MSVC build
story. The working paths are conda-forge `win-64` (implies shipping a conda runtime inside the
installer), WSL, or third-party wheel rebuilds of unverified provenance.

**Decision.** No Pynini or OpenFst in the shipped product. Phase 1 ITN is a hand-written rule
cascade in Python, structured as ordered tagger→verbalizer passes — separate, independently
testable modules for numbers, dates, times, units, currencies, and URLs/emails/paths.
**Aggressiveness is gated per-application**, using the same focused-window signal that drives
contextual biasing.

**Rationale.** Basing a signed commercial installer on an individual's unofficial wheel rebuild
is a supply-chain risk, not an inconvenience. A rule cascade also ports to Rust as a mechanical
rule-for-rule translation, whereas an FST toolchain migration does not — which matters directly
under D-0006.

**Consequences.** We own ITN coverage, and gaps show up in F-WER as our own bug. Russian and
Ukrainian ITN is scoped to numbers and dates only; no ready-made grammar exists for either.
`rustfst` (MIT/Apache-2.0, pure Rust, no C++ toolchain) remains the engine if a native WFST is
ever wanted. **Not decided:** whether an offline Linux/WSL step that compiles a grammar to a
portable FST artifact is worth the tooling complexity — revisit once rule coverage is measured.
The per-application aggressiveness dial is attested nowhere in the literature; it is our
invention and ships with its own eval plan, not as a known-good pattern.

---

## D-0009 — No LLM correction pass in Phase 1; confidence highlighting instead

**Status:** accepted · 2026-09-26

**Context.** `ARCHITECTURE.md` §5.5 specified a constrained LLM correction pass, budgeted at
60 ms p50 / 150 ms p95. R8 produced two independent findings, either sufficient alone. First,
measured on our exact GPU class, Llama-3.2-1B Q4_K_M has **301 ms time-to-first-token** and
Gemma-3-4B has 1.28 s — TTFT alone exceeds the entire budget before a single output token
exists, and TTFT is prefill-bound, so shortening the output does not help. Second, the
confidence signal that would gate the pass is uncalibrated: NeMo computes token confidence and
entropy beats max-prob by 2–4x at detecting wrong words, but nothing claims calibration, no
trained confidence head ships by default, and none of it has been measured on accented or
code-switched speech.

**Decision.** Phase 1 ships **entropy-based word confidence in the result, and visual
highlighting of low-confidence spans.** It ships no LLM correction pass. Any LLM call is
deferred to an async, user-requested path at the earliest. "Correct-after-injection and patch"
becomes a Phase 2 candidate only if a calibration study on our own data justifies it.

**Rationale.** Highlighting needs only relative discrimination, which is exactly what the
evidence supports; auto-correction needs calibrated probability, which we do not have. The
confidence plumbing is required by the architecture regardless of whether correction ever
ships, so building it is not speculative work.

**Consequences.** Phase 1 is smaller. The "select, don't rewrite" constraint survives and is
strengthened by Apple's specialized-corrector result, LCAR, and RLLM-CF — but the tradeoff is
*preserved, not resolved*: free generation reports the largest raw WER gains, no controlled A/B
with a meaning-preservation metric exists, and no citable ASR-specific semantic-drift metric
exists at all. The `ARCHITECTURE.md` PAC citation was wrong and is corrected — PAC is an
audio-in LLM-ASR model, not a text-only corrector. The correction pass remains on probation
under the standing rule: no F-WER gain, no ship.

---

## D-0010 — Voice actions: Tier 0/1 only, and the process boundary is the safety boundary

**Status:** accepted · 2026-09-26 · implements the policy layer D-0005 deferred

**Context.** D-0005 froze the `NlpResult → Intent → WorkflowAction → policy → execution` chain
as a contract while shipping no actions. R9 established what the policy layer must be. Two
findings reshape it. Most of the voice-attack literature — DolphinAttack, SurfingAttack,
CommanderSong, TV-triggered commands, accidental-activation studies — assumes an
always-listening wake-word engine, which push-to-talk does not have; a keypress is a stronger
provenance signal than anything that literature produced. What remains live is **prompt
injection through text we already read**: focused field, clipboard, harvested page content.
Separately, confirmation dialogs habituate within single-digit exposures, and the effect is
neurological rather than attitudinal, so it cannot be fixed with better wording.

**Decision.**

- Phase 1 admits **Tier 0 (read-only) and Tier 1 (reversible, with a real tested undo) only.**
  No Tier 2 or Tier 3 action type exists in the allowlist.
- **Undo-ability is a classification input, not a UI feature.** An action without reliable undo
  is not Tier 1, however small it looks.
- `WorkflowAction` is a closed, versioned, schema-validated enum. Action *types* are
  allowlisted; *targets* (processes, fields) remain blocklisted.
- **The executor never re-invokes the model to ask whether an action is safe.** In Phase 1 the
  Rust/Python process boundary enforces this structurally: the sidecar emits `Intent`, and the
  Rust policy layer alone constructs the `WorkflowAction`.
- Harvested context may **never** parameterize an action — only the user's own dictated,
  high-confidence utterance may.
- No action chains from a prior action without a fresh hotkey press.
- Audit log records structured actions, never transcripts.
- Speaker verification, if ever built, is a risk signal and never a gate.

**Rationale.** The safety separation the agentic-security literature converges on (Microsoft's
agent accounts and workspace isolation, CaMeL's control/data-flow split) falls out of D-0006's
Rust/Python seam for free — a decision made for entirely unrelated reasons. Meanwhile,
confirmations are a scarce resource that must be reserved for the irreversible, so
reversibility is the primary mechanism and confirmation is the exception.

**Consequences.** The voice-activated (always-listening) mode gets no action tier above 0 at
all, and the classic voice-attack mitigations gate *that* mode's release rather than Phase 1's.
Similar-sounding actions must not sit at different tiers, which constrains the action-naming
scheme. When the sidecar is later replaced by in-process Rust inference, the safety boundary
stops being OS-enforced and must be maintained by review — call this out at that time.
**Not frozen:** the tier escalation and de-escalation triggers. Only real confirmation and
undo-rate data can calibrate them, and none exists yet.

---

## D-0011 — ONNX Runtime is the inference substrate; the model is decided by measurement

**Status:** accepted · 2026-09-26

**Context.** R5's elimination converged the production path: `sherpa-rs` is archived (so
sherpa-onnx from Rust means maintaining our own FFI), NeMo-Speech.cpp has no Rust bindings and
is a 17-commit project, and Parakeet TDT is explicitly ignored by NVIDIA's word boosting. The
temptation is to read that as also selecting the model. It does not.

**Decision.** **Substrate:** ONNX Runtime via `ort`, pinned exactly, with **DirectML as the
default execution provider and a CPU EP that always works.** CUDA is blocked pending a direct
read of the cuDNN redistribution terms — a legal question, not an engineering one.
**Model:** decided in Phase 0 by measurement on the developer's own voice, not here. Leading
hypothesis is Nemotron Speech Streaming EN 0.6B at the 560 ms chunk configuration; Parakeet TDT
0.6B v3 is the multilingual candidate; Whisper large-v3-turbo CT2 int8 is the accuracy-tier
fallback.

**Rationale.** The substrate choice is forced by Rust binding maturity and is hard to reverse.
The model choice is behind the `AsrEngine` interface, is cheap to reverse, and every published
number that would inform it was measured on hardware unlike ours.

**Consequences.** A risk appears that no single research memo owned: **`AsrResult` requires
token-level confidences and an N-best list, and it is unverified that an ONNX export exposes
them.** NeMo's Python stack does. If the export is a text-emitting black box, the resolution is
to run the transducer decode loop ourselves over ONNX encoder/decoder/joiner — which yields the
logits by construction and is where biasing must live anyway, but is a substantial Rust task
for a developer with no Rust experience. **Phase 0 carries this as an explicit exit criterion:
verify per-token logits are reachable from the exported artifact.** A backend that cannot
supply confidences and N-best is not a valid backend under this architecture.
