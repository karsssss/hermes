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

**Status:** accepted · 2026-09-26 · **"entropy-based" amended by D-0014**: the shipped word
confidence is the emitted-token probability; everything else stands

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

**Status:** accepted · 2026-09-26 · **its model hypothesis is superseded by D-0013**; the
substrate decision stands; the DirectML default is under review (open question #14), not changed;
**its Phase 0 exit criterion (confidences + N-best from the export) is met — D-0014**

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

---

## D-0012 — A public proxy evaluation set stands in for the personal set, and never replaces it

**Status:** accepted · 2026-09-26

**Context.** Task 1b of Phase 0 was to record 30 personal utterances. That needs a human with
a microphone and cannot happen now, and `CURRENT.md` is explicit that nothing else in Phase 0
can be believed until *some* scored data exists. The alternative to waiting is a set built from
public corpora — which is also, per `PRODUCT.md` §3 (W2), what the published benchmark will
eventually need anyway.

**Decision.** Build **Public Proxy Evaluation Set v1**: 160 utterances from pinned public
corpora (EdAcc, LibriSpeech test-clean, RuLS, Golos crowd + farfield, plus OpenSLR-28 noise and
RIRs), sampled deterministically with speaker quotas, and shipped as a **manifest plus a
fetcher** — never as redistributed audio. `hermes-eval build-dataset` is the fetcher. The
manifest schema gains an optional, strictly-validated `provenance` block and two metadata axes,
`subset` and `reference_style`.

**Rationale.** Three constraints forced the shape.

*Licensing.* EdAcc is CC BY-SA 4.0 and Golos' bespoke licence is a CC BY-SA 4.0 reword, so
derived audio would be Adapted Material with obligations attached. A manifest plus a
content-addressed fetcher makes the question moot and keeps the repository small. `*.wav` and
`eval/datasets/**/audio/` were already gitignored, so this costs nothing.

*Reproducibility.* Revisions are pinned to full commit shas, sampling seeds and per-record
audio sha256 are written into the manifest, and metadata is read from the pinned parquet rather
than from an endpoint that serves whatever is current. Common Voice is excluded for exactly
this reason — CC0, but since October 2025 it is only obtainable through Mozilla Data
Collective behind an account and a terms acceptance, so a build cannot reproduce it.

*Honesty about what it measures.* No public corpus in scope ships a formatted reference, so
**F-WER is not computable on this set** and neither is E-WER. That fact is encoded
(`reference_style`), sliceable, and stated at the top of the set's README rather than left for
a reader to discover from a suspiciously large number.

**Consequences.** The scoring path stays stdlib-only; the *build* path is allowed an optional
`data` dependency group (numpy, soundfile, pyarrow, huggingface-hub) because decoding FLAC and
convolving an RIR in pure Python is not a defensible use of anyone's time. Nothing in `runner`,
`metrics` or the scoring CLI imports it.

The set does **not** retire Task 1b. It measures accented English, read English, read Russian,
Russian far-field commands and two robustness conditions. It measures nothing about dev-speak,
Slavic-English code-switching, ITN, punctuation, casing, the real microphone, or the real
acoustic environment — which is to say, it measures none of the four differentiators directly.
**Any model decision made on this set alone is provisional and must be re-run against the
personal set.**

**v1 is frozen** as of 2026-09-27 (manifest sha256 `2b3a46ede2700f30…`): its spec and pinned
revisions do not change again under that name, so a number quoted against it stays meaningful.
**Not frozen:** the *next* set. v2's highest-value addition is FLEURS `en_us`/`ru_ru`,
whose `raw_transcription` field is the only formatted reference found in the whole candidate
pool and would restore F-WER, ITN and punctuation measurement; it was deferred on fetch cost
(290–433 MB per language split), not on licence.

---

## D-0013 — Task 2a eliminates Nemotron; Parakeet TDT v3 is the front-runner

**Status:** accepted · 2026-10-05 · **supersedes D-0011's model hypothesis**

**Context.** D-0011 named Nemotron Speech Streaming EN 0.6B @ 560 ms the leading hypothesis,
with Parakeet TDT 0.6B v3 as the multilingual candidate and Whisper large-v3-turbo as the
accuracy-tier fallback. That ranking rested on architecture and licensing; nothing in it was
measured on this hardware. Task 2a then ran all three through `hermes-eval` on one runtime
(ORT 1.28 via sherpa-onnx 1.13.8), the CPU EP, 4 threads, int8, `greedy_search`, against the
frozen public proxy set (n=160, manifest `2b3a46ede2700f30…`). Full write-up:
`docs/research/T2A-screening.md`.

**Decision.** **Nemotron Speech Streaming EN @ 560 ms leaves the Phase 1 candidate set.**
**Parakeet TDT 0.6B v3 is the front-runner. Whisper large-v3-turbo is retained as the
accuracy-tier fallback and as the comparator** the backend decision is measured against. The
production backend is **still not chosen** — that waits for F-WER and E-WER on the personal
set (Task 1b), per D-0012.

**Rationale.** WER %, lower is better; Δ by paired bootstrap, 2000 resamples, seed 20260926.

| | Parakeet | Whisper | Nemotron |
|---|---:|---:|---:|
| WER overall / en / accented_en | 13.29 / 12.79 / 18.74 | 14.89 / 15.42 / 23.64 | 32.55 / 18.66 / 27.67 |
| RTF, CPU EP | 0.47 | 2.05 | 2.44 |
| median latency, utterances ≤3 s | 1958 ms | 9267 ms | 5792 ms |
| empty outputs | 2 / 160 | 0 / 160 | 23 / 160 |

Nemotron is dominated by both others on every axis except peak RAM (797 MB vs 996 MB): Whisper
alone beats it on English by 3.24 pp, CI [1.28, 5.48]. Its streaming harness is pessimistic
about its speed, but that caveat does not touch its quality. Parakeet beats Whisper on English
(+2.63 pp [0.80, 4.43]) and accented English (+4.90 pp [1.72, 8.35]), and is the only
candidate faster than real time. Whisper wins Russian read speech (−4.47 pp [−8.89, −1.09]),
so it is not dominated and stays. **The overall Parakeet–Whisper gap (+1.60 pp, CI
[−0.08, +3.31]) is noise and must not be quoted as a result.**

**Consequences.** All of this is WER on a proxy set that cannot see F-WER, E-WER, dev-speak,
code-switching, ITN or the real microphone, so it is a strong prior, not a selection. The
boosting support and ORT GenAI bindings that made Nemotron attractive go with it; biasing on
Parakeet has to be built in our own decode loop (§5.1), which was already the expected path.
Whisper carries a measured 29.6 s stall per language switch through sherpa's API and pads
every input to a 30 s window, both costs against it as anything but a fallback.
**DirectML vs WinML is explicitly not decided here** — every Task 2a figure is CPU EP, so this
entry says nothing about any GPU execution provider.

---

## D-0014 — Task 2b: the confidence / N-best contract is kept; N-best comes from an owned Python decode loop

**Status:** accepted · 2026-10-06 · **meets D-0011's Phase 0 exit criterion; amends D-0009's
"entropy-based" word confidence**

**Context.** SYNTHESIS §5.1 and D-0011 made it a Phase 0 exit criterion to show that an ONNX
export can supply `FinalTranscript.tokens[].confidence` and `nbest[]` (C5), with "own the
transducer decode loop" as the feared, expensive fallback. D-0009 committed Phase 1 to
"entropy-based word confidence", on R8's LibriSpeech/NeMo evidence that entropy beats max-prob
2–4×. Task 2b measured both on Parakeet TDT 0.6B v3 int8 against the frozen proxy set (n=160).
Full write-up: `docs/research/T2B-confidence.md`; run
`20261006T033722Z-t2b-parakeet-confidence-27dc`.

**Decision.** **Keep C4/C5 unchanged** — verdict A. Below the contract:
1. **`tokens[].confidence` is the emitted-token probability** (sherpa's `ys_log_probs`; word =
   min over its tokens). Not entropy.
2. **`nbest[]` comes from a Hermes-owned Python TDT beam loop** in the sidecar, K ≤ 4,
   deduplicated, computed only when `decode_params.beam > 1`; otherwise it holds the top-1 alone.
   The transcript itself is decoded greedily.
3. **`nbest[].score` and any utterance score are rank-only**, never presented or consumed as
   probabilities.

**Rationale.** AUROC for separating correct from incorrect words, utterance-bootstrap 95% CI.
sherpa's native emitted-token probability: **0.884 [0.855, 0.908]**. Best full-distribution
signal, Gibbs entropy: 0.883, +0.004 [+0.001, +0.008] over the same quantity on the same
hypothesis — resolved but negligible. **R8's Tsallis-1/3 is worse: −0.038 [−0.063, −0.016].**
The full distribution buys nothing for confidence. N-best is another matter: sherpa computes K
hypotheses and returns one, through every released API. The owned beam's list has real
headroom — oracle WER −1.99 pp [−2.86, −1.27] at K=4, −3.05 pp on accented English — but the
decoder cannot rank it (beam-4 top-1 vs greedy −0.16 pp [−0.89, +0.53]; beam-8 top-1 is worse,
+1.01 pp). The loop is small (greedy ~35 lines, beam ~75, over three ORT sessions), costs a
decode-loop RTF of 0.06 / 0.20 on top of the encoder, and is where Parakeet's biasing must live
anyway (D-0013). Phase 1 decodes in the Python sidecar (SYNTHESIS §4), so this is not Rust work.

**Consequences.** §5.1's risk is retired for Parakeet: no architecture change, no Rust decoder
in Phase 1. D-0009's highlighting stands on a better-measured footing — flagging the lowest 10%
of words catches 56% of scorable errors — but it is blind to deletions (~41% of word errors
here), its calibration is aggregate-only and mildly overconfident on accented English, and none
of it is measured on the user's voice; auto-correction stays out. N-best has no Phase 1
consumer, so its value is deferred to whatever selector eventually reads it. A correct TDT beam
(prefix merging, duration branching), the only route to a useful decoder ranking, is not
required and not planned. Whisper, the retained fallback, was not tested and does not inherit
this result. Every Task 2b latency figure is non-decision-grade (resumed run, ~20% shift between
sittings on matched content).

---

## D-0015 — Task 2c: Parakeet ships as the FP32 export; INT8 is the low-memory fallback

**Status:** accepted · 2026-10-06 · **refines D-0013** (which named the model, not its
representation)

**Context.** Tasks 2a and 2b measured Parakeet TDT 0.6B v3 only as sherpa-onnx's dynamic-int8
export, and Task 2b found that export numerically fragile: a 1e-7 feature perturbation flips
transcripts, and sherpa vs a direct-ORT port of the same decoder disagreed on 33/160
(open question #17). Task 2c ran the int8 export against its fp32 sibling (same exporter,
same day, identical tokens) on everything else held fixed — Public Proxy v1, sherpa 1.13.8
greedy, ORT 1.28 CPU EP, 4 threads — in ABAB fresh processes. Full write-up:
`docs/research/T2C-precision.md`; run `20261006T055203Z-t2c-parakeet-int8-vs-fp32-01d0`.

**Decision.** **Phase 1 runs Parakeet as the FP32 export** on the CPU EP, loaded once at
service start and kept resident. The INT8 export remains a documented fallback for
low-memory machines, not the default. Any further backend comparison uses Parakeet FP32.
This decides the model's **representation**, not the execution provider: DirectML vs WinML
(open question #14, D-0011) remains unresolved, and a GPU EP is neither chosen nor ruled out.

**Rationale.** Paired bootstrap, 2000 resamples, seed 20260926; WER, not F-WER.
FP32 − INT8: **overall −2.57 pp [−3.94, −1.32]** (13.29 → 10.72), English −2.02 [−3.46, −0.78],
Russian −5.25 [−9.13, −1.34], noise −6.73, reverb −3.80, all clear of zero; worse on no slice;
accented English −1.74 [−4.01, +0.34], unresolved. Inaudible 1-LSB dither changes 30/160 INT8
transcripts and 8/160 FP32 (Δ −13.8 pp [−20.6, −7.5]); sherpa/ORT parity rises from 127/160
to 159/160. Both are bit-deterministic run to run. Confidence (emitted-token prob) ties:
AUROC 0.884 → 0.892, Δ +0.008 [−0.014, +0.030]. Cost: peak working set 996 → 2736 MB, disk
670 → 2550 MB, load ~4.7 → ~9–12 s, decode time +7–9% (regime-matched per-utterance ratio
1.07 [1.01, 1.15]). **Absolute Task 2c latencies are non-decision-grade** — three of four arm
processes hit a ~5× fast system-state regime — only the regime-matched FP32/INT8 ratio is.

**Consequences.** The sidecar budget becomes ~2.8 GB resident. Every Task 2a/2b Parakeet
figure is an INT8 figure and understates the model; Whisper was also measured INT8 only, so
its fp32 headroom is equally unmeasured. D-0014 stands unchanged on FP32. Phase 3 Rust-port
parity testing becomes tractable (two implementations agree to 3.5e-4 nats). A better
quantization (static int8, fp16, sensitive-layer exclusion) could recover the memory and is a
separate measurement. All of it is proxy-set WER: **FP32 has not been measured on personal
speech**, and the gap is re-checked on the personal set (Task 1b).

---

## D-0016 — Task 2d: Parakeet FP32 fails the CPU streaming gate; 4 threads frozen, HighQoS required

**Status:** accepted · 2026-10-08 · **refines D-0011** (CPU EP is not sufficient on its own for
the interactive path) and **D-0015** (which chose the representation, not the finalization path)

**Context.** D-0015 put Parakeet TDT 0.6B v3 FP32 on the ORT CPU EP for Phase 1, without
measuring push-to-talk release-to-final latency. Task 2d did, with the gate pre-registered in
`t2d.GATE`. The gate is p95 ≤ 300 ms PASS and ≤ 450 ms MARGINAL, and a finalization policy is
eligible only if its WER is not resolved worse than the offline full decode. Full write-up:
`docs/research/T2D-cpu-streaming.md`. Run: `20261007T040840Z-t2d-parakeet-fp32-cpu-190c`.

**Decision.**

- **CPU FP32 STREAMING: FAIL.** No measured CPU finalization policy qualifies for Phase 1.
- **4 threads is frozen** for this machine's CPU path.
- **The Phase 1 sidecar must opt out of Windows execution-speed throttling (HighQoS)** whenever
  it runs ASR on the CPU.
- The next Phase 0 blocker is **finalization architecture and acceleration**, not model
  selection.

**Rationale.**

- **Offline throughput.** 3 clean full-corpus rounds at 4 threads with HighQoS: RTF 0.0694
  (CV 1.5%), WER 10.721%, transcripts identical across rounds. HighQoS pilots put 2, 3, 5, 6 and
  8 threads behind 4. Without HighQoS, Windows confined the windowless worker to the E-cores at
  RTF 0.42.
- **`redecode` (eligible, FAIL).** WER 10.643%, Δ −0.08 pp [−0.24, 0.00], 159/160 finals
  identical to offline. Release-to-final p50 / p95 / p99 is 452 / **1339** / 1838 ms.
- **LocalAgreement-2 `commit` (ineligible).** p95 443 ms, but WER 24.094%, Δ +13.37 pp
  [+10.71, +16.32].
- **Throughput is not the cause.** The CPU runs 14× faster than real time and finals cost what
  the offline fit predicts. What fails is that a full-utterance final redecode costs
  ~80 ms + 57 ms per audio-second and also waits for the in-flight partial (575 ms at p95), so
  it exceeds 450 ms beyond ~6 s.
- **Context-free tail commit** bounds that cost only by decoding each segment without left
  context, which more than doubles word errors.

**Consequences.**

- DirectML/WinML (open question #14) is still unmeasured and becomes one of the two levers. The
  other is a finalization design that is neither a full redecode nor a context-free commit:
  in-flight cancellation, overlapped-context commit, or a cache-aware export. Either is a new
  task with its own pre-registered gate; nothing here selects one.
- Parakeet FP32 stays the front-runner (D-0013, D-0015) because its quality is intact under
  `redecode`. Whisper large-v3-turbo, slower still on the CPU EP, inherits no streaming result.
- The HighQoS opt-out mechanism the shipped sidecar will use is unmeasured.
- The thread count and QoS finding are for this laptop (4 SMT P-cores, 4 E-cores, 16 GB).
- All quality figures are proxy-set WER, not F-WER.
