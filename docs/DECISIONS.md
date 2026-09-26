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
