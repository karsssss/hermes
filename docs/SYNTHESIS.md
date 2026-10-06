# Synthesis — R1 through R9

Status: 2026-09-26. Written by the lead after all nine research memos landed.
**Amended 2026-10-05:** §5 and §11 corrected by the Task 2a measurement (D-0013).
**Amended 2026-10-06:** §5.1 resolved for Parakeet, §9, §15 and C5 updated, by Task 2b (D-0014).

This is the decision document. `ARCHITECTURE.md` describes the target system; this says
what the research actually settled, what it left open, and what Phase 1 should build.
Where two memos conflict, the conflict is preserved and the resolution rule is stated
rather than the conflict being papered over.

**Nothing here is code. Contracts in §18 are proposed, not implemented.**

---

## 0. What R7–R9 changed

Five things moved. Everything else confirmed what we already believed.

1. **ITN's toolchain question is settled, against WFST.** Pynini/OpenFst has no first-party
   Windows wheel and no first-party MSVC build story; the working Windows paths are
   conda-forge (implies shipping a conda runtime), WSL, or third-party wheel rebuilds. None
   is acceptable under a signed installer. Phase 1 ITN is a hand-written rule cascade. This
   closes open question #10, open since 2026-09-24.
2. **The correction pass cannot run synchronously, at any model size.** On our exact GPU
   class, Llama-3.2-1B Q4_K_M has **301 ms time-to-first-token** and Gemma-3-4B has 1.28 s.
   The correction budget is 150 ms p95. TTFT alone exceeds the whole budget before one output
   token exists, and TTFT does not shrink meaningfully with shorter output — prefill, not
   generation, is the wall. This is not a tuning problem.
3. **Token-level transducer confidence is obtainable but uncalibrated.** NeMo ships the
   machinery (`ConfidenceConfig`, entropy methods, `exclude_blank`); entropy beats max-prob
   by 2–4x at detecting wrong words on Conformer-RNNT. But nothing claims calibration, no
   trained confidence head ships by default, and none of it was measured on accented or
   code-switched speech — which is our user. Good enough to rank and highlight; not good
   enough to auto-accept.
4. **Push-to-talk deletes most of the voice-attack threat model.** DolphinAttack,
   SurfingAttack, CommanderSong, TV-triggered commands, accidental-activation studies — all
   assume an always-listening wake-word engine. We have no wake-word engine to spoof. A
   keypress is a stronger provenance signal than anything that literature produced. Those
   mitigations gate the voice-activated mode's release, not Phase 1's.
5. **What replaces it is prompt injection through text we already read** — focused field,
   clipboard, harvested page text. Indifferent to activation mode, ranked #1 by OWASP two
   editions running, and the named reason Microsoft built agent accounts and workspace
   isolation into Windows. This is where safety effort belongs.

And one correction owed to our own doc: **`ARCHITECTURE.md` §5.5 miscites PAC**
(arXiv 2509.12647). PAC is an audio-in LLM-ASR model with G2P-interleaved training, not a
text-only post-hoc corrector. The phoneme-interleaving *idea* is reusable; the paper is not
evidence about correcting a separate ASR's output.

---

## 1. Target architecture

Unchanged in shape from `ARCHITECTURE.md` §2, with the process boundary given a second job.

```
┌─ hermesd (Rust) ─────────────────────────────────────────────┐
│  audio thread ──ring──► capture supervisor ──► sidecar client│
│  hotkey thread (WH_KEYBOARD_LL + pump + watchdog)            │
│  orchestrator (tokio): state machine, context harvest,       │
│                        policy layer, executor, injection     │
│  SQLite: vocabulary, per-process strategy table, profiles    │
└──────────────────────────┬───────────────────────────────────┘
                           │ NDJSON / localhost TCP / versioned
┌──────────────────────────▼───────────────────────────────────┐
│  hermes-infer (Python, replaceable)                          │
│  ASR decode · confidence · N-best · ITN rules · intent       │
└──────────────────────────────────────────────────────────────┘
```

**The process boundary is also the safety boundary.** R9's central architectural
requirement — the component that classifies intent must never call the executor, and the
executor must never re-invoke the model to ask whether an action is safe — is satisfied *by
construction* by D-0006's existing Rust/Python split. The sidecar can only emit a serialized
value across a socket; it has no handle to anything that touches the OS. We get CaMeL-shaped
separation for free from a decision made for entirely different reasons.

Do not lose this property when the sidecar is later replaced by in-process Rust inference. At
that point the separation stops being enforced by the OS and becomes a module boundary
enforced by review.

## 2. Phase 1 architecture

Tauri-as-daemon (one process to build, sign, install), **with the Rust core written as a
UI-agnostic library crate from day one** and `main()` in the Tauri binary doing nothing but
calling into it. R5 is right that this is the single most important structural discipline
available: it makes the later daemon extraction mechanical instead of a rewrite, and it costs
nothing now.

Python sidecar shipped as a bundled, signed executable. Expect SmartScreen friction until
reputation builds.

## 3. Process and thread ownership

| Thread / process | Owns | Forbidden |
|---|---|---|
| **Audio thread** (cpal callback, dedicated OS thread, MMCSS) | Write into pre-roll ring buffer, atomic counters | Allocation, logging, mutexes, `.unwrap()`, slow `Drop`, anything async |
| **Hotkey thread** (dedicated, `GetMessage` pump) | `WH_KEYBOARD_LL` callback: read struct, `try_send` on a bounded channel, `CallNextHookEx` | Everything else. Target < 100 µs. Watchdog reinstalls on silent unhook |
| **Orchestrator** (tokio) | State machine, context harvest, sidecar protocol, policy layer, executor, injection, SQLite via `spawn_blocking` | Touching the audio callback |
| **Sidecar** (Python process) | ASR decode, confidence, N-best, ITN, intent resolution | Any OS side effect. It emits values; it never acts |

Pre-roll buffer is **hand-rolled** — one pre-allocated `Box<[f32]>` plus a wrapping write
cursor. It is a single-owner circular *overwrite* buffer, not a producer/consumer queue;
`rtrb`/`ringbuf` error when full, which is the wrong semantics. Use one of those crates for
the callback→consumer handoff only.

## 4. Rust vs Python responsibility

| Concern | Phase 1 | Later |
|---|---|---|
| Audio capture, resample, pre-roll | **Rust** (`cpal` + `rubato`) | Rust |
| Hotkeys, injection, clipboard, UIA inspection | **Rust** | Rust |
| State machine, policy layer, executor | **Rust** | Rust |
| Persistence | **Rust** (`rusqlite`, bundled) | Rust |
| ASR decode, confidence, N-best | **Python** | Rust (`ort`) |
| ITN rule cascade | **Python** | Rust — literal rule-for-rule translation |
| Intent resolution | **Python** (trivial under D-0005) | Rust |

The ITN choice in §8 is partly *because* of this row: a hand-written rule cascade ports as a
mechanical rewrite, whereas an FST toolchain migration does not.

## 5. ASR backend strategy

**Substrate is settled; the model is not, and should not be.**

- **Inference substrate: ONNX Runtime via `ort`.** R5's elimination still holds — `sherpa-rs`
  is archived, NeMo-Speech.cpp has no Rust bindings and is a 17-commit project, and Parakeet
  TDT is explicitly ignored by NVIDIA's word boosting. `ort` + ONNX is the only path where
  streaming, biasing, a maintained Rust binding, and a commercial licence hold at once.
- **Execution provider: DirectML default, CPU EP always working.** CUDA is blocked on a legal
  question, not an engineering one — cuDNN's redistributability is unconfirmed and needs a
  direct EULA read before any engineering time. DirectML ships with the Windows/driver stack,
  works across vendors, and has no redistribution question. *Reopened, not decided
  (2026-10-05):* ONNX Runtime now says new feature development has moved to WinML, and no
  candidate has been measured on DirectML — see `CURRENT.md` open question #14.
- **Model: decided in Phase 0 by measurement, not here.** *Corrected 2026-10-05 (D-0013).*
  This section originally named Nemotron Speech Streaming EN 0.6B @ 560 ms the leading
  hypothesis, on architecture and licensing alone. Task 2a measured all three candidates on
  this laptop (`docs/research/T2A-screening.md`) and **eliminated Nemotron**: worse WER than
  both others with the CI clear of zero, slowest of the three, 23/160 empty outputs.
  **Parakeet TDT 0.6B v3 is the front-runner** — best English and accented-English WER, and
  the only candidate faster than real time on the CPU EP. **Whisper large-v3-turbo is
  retained as the accuracy-tier fallback and comparator.** The production backend is still
  undecided: the proxy set cannot compute F-WER or E-WER, so the choice waits for the
  personal set (Task 1b).

### 5.1 The risk this creates, which no single memo owns

**RESOLVED for Parakeet TDT 0.6B v3 — 2026-10-06, Task 2b, D-0014** (`docs/research/T2B-confidence.md`).
The contract is kept unchanged. What was measured on the int8 sherpa-onnx export:

- **The export exposes everything**: the joiner returns the full token distribution and the
  TDT duration distribution at every step.
- **sherpa's emitted-token probability (`ys_log_probs`, public API) is sufficient for Phase 1
  confidence.** Word-error AUROC 0.884 [0.855, 0.908]; no signal computed from the full
  distribution beats it by more than 0.005, and R8's Tsallis-1/3 is significantly worse.
  **Richer full-distribution confidence is not needed for Phase 1.**
- **N-best requires a small Hermes-owned Python TDT beam loop.** sherpa computes several
  hypotheses and returns one through every released API. The owned loop is ~35 lines
  (greedy) / ~75 (beam) over three ORT sessions, in the Python sidecar where Phase 1 decodes
  anyway (§4).
- **No Rust decoder is required.** The loop is Python, Phase 1 decodes in the Python sidecar,
  and a Rust port belongs to Phase 3 (D-0003).

The scope is Parakeet only. Whisper large-v3-turbo, the retained fallback, was not tested and
does not inherit this result. **DirectML vs WinML remains unresolved** (§5, open question
#14): every Task 2b figure is CPU EP. The original risk statement follows, kept for the record.

> The architecture requires `AsrResult` to carry **token-level confidences and an N-best
> list**. R8 confirms NeMo's Python stack provides them. ~~It is unverified that an ONNX export
> does.~~ If the export is a black box that emits text, the production Rust path silently
> loses the signal the entire correction and highlighting design depends on — and we would
> not discover it until the Phase 1 port.
>
> There is a resolution: run the transducer decode loop ourselves (encoder → decoder/joiner,
> step by step, over ONNX), which yields the logits by construction and is also where biasing
> has to be implemented anyway. That is what sherpa-onnx does. ~~It is a substantial Rust task
> for a developer with no Rust experience.~~ **[Superseded by measurement: for Parakeet the
> loop is small, and it is Python, not Rust, in Phase 1 — see above.]**
>
> **Therefore: Phase 0 must verify, as an explicit exit criterion, that per-token logits are
> reachable from the exported artifact.** **[Met for Parakeet — D-0014.]**

## 6. Multilingual strategy

The W2/W3 conflict resolves by noticing they are on different tracks.

**W2 is a benchmark deliverable before it is a product capability.** `PRODUCT.md` §3 already
says lead with W1+W3 and build W2 as the public benchmark; `ROADMAP.md` already says the accent
benchmark needs no product code. So Phase 1 can ship an English-first engine without W2 dying,
provided the benchmark work runs in parallel as evaluation.

Phase 1: English-first. Multilingual and code-switched utterances escalate to a second tier —
mechanically identical to the opt-in cloud tier in D-0002, reusing the same per-utterance tier
indicator in the HUD. Do not build a second resident model in Phase 1; VRAM allows it (§11) but
complexity does not earn it yet.

Honest caveat: the developer is user zero and is an L1 Ukrainian/Russian speaker. If
Checkpoint 1's "30 days without reaching for the keyboard" fails specifically on code-switched
utterances, that is a signal about the model choice, not about the product thesis — diagnose
before concluding.

No Slavic-English code-switching corpus was found (R6). Collect our own and say so in the
published methodology rather than silently omitting the pair.

## 7. Contextual biasing strategy

The evidence now supports a specific shape, not just an instinct.

**Large static corpus, small dynamically-retrieved active subset.** BR-ASR reaches 200K entries
at 0.3/2.9% WER/B-WER degradation — *conditioned on a 99.99% pruning rate*. The win comes from
not biasing against most of the list. TurboBias independently reduces its boosting weight from
1 to 0.7 to avoid false accepts on expanded lists. Both point the same way: a flat growing
hotword list is the failure mode, not the design.

Vocabulary sources, cheapest first:

1. **Git metadata + filenames + path components** — zero parser, captures branch names, ticket
   prefixes, feature names. Do this first.
2. **universal-ctags** — fast multi-language bootstrap. Official Windows CI builds exist.
   **GPL-2.0-or-later; needs a `DECISIONS.md` entry and a legal read before bundling the
   binary.** Subprocess invocation is a materially different exposure from linking, but that is
   not a question to settle by inference.
3. **tree-sitter** — MIT, Rust-native, per-language precision upgrade for the languages the
   user actually uses. Cold parse of a large repo is the real cost, not incremental updates.
4. **LSP `workspace/symbol`** — real and standard, but requires being a full LSP client with
   per-project server lifecycle management. Phase 2+ at the earliest, and only where a server
   is already running for other reasons.

Identifier splitting is rule-based (case conventions; `::`, `.`, `/`, `_` separators; a small
abbreviation dictionary). There is real open-vocabulary literature behind this if rules prove
insufficient, but rules first.

Active-subset selection keyed on focused application + open repo + recent history is, as far as
R7 could find, **not published prior art**. It is our contribution, which means it needs its
own eval, not a citation.

Guardrails, both required from day one: confidence-gated activation, and a **control set of
utterances containing no bias terms** to measure false-insertion rate. E-WER improving while
false insertions rise is not a win.

## 8. NLP / ITN pipeline

Hand-written Python rule cascade, structured as ordered tagger→verbalizer passes mirroring
NeMo-text-processing's *shape* but none of its dependencies. Separate, independently testable
modules for numbers, dates, times, units, currencies, URLs/emails/paths.

**Per-application ITN aggressiveness**, gated by the same focused-window signal that drives
biasing. "Dash dash interactive" → `--interactive` is right in a terminal and wrong in Slack.
This is our invention — R7 found it attested nowhere — so it ships with an eval plan (F-WER
stratified by app profile), not as a known-good pattern.

Punctuation and casing come natively from the model where available; a small fallback model
only if measurement shows a gap. Russian/Ukrainian ITN is scoped to numbers and dates only,
hand-written; no ready-made grammar exists.

`rustfst` (MIT/Apache-2.0, pure Rust, no C++ toolchain) is the right engine *if* we ever want
WFST-based ITN natively. Watch `RustedBytes/ukrainian-itn`; do not adopt it at 14 commits.

Intent detection in Phase 1 is **deterministic trigger-phrase matching only**, plus a
Talon-style `"escape"` / `"literal"` prefix that unconditionally forces literal dictation. Talon
is real, directly-applicable prior art and worth reading before designing our grammar. No
classifier, no embedding router, no LLM — under D-0005 there is nothing for them to gate.

## 9. Correction policy

**Ship confidence-based highlighting in Phase 1. Ship no LLM correction pass.**

This follows from two independent findings, either of which alone would be sufficient:
synchronous correction does not fit the latency budget on this hardware (§0.2), and the
confidence signal that would gate it is uncalibrated (§0.3).

What ships:

- ~~Entropy-based~~ word confidence, computed in the sidecar, carried in the result.
  **Amended 2026-10-06 (D-0014): for Parakeet it is the emitted-token probability** that
  sherpa already returns (word = min over its tokens). Entropy measures did not beat it on
  Parakeet. This is arithmetic over already-computed logits — no second model, no latency
  risk — and the architecture requires it regardless of whether correction ever ships.
- Visual highlighting of low-confidence spans. This is the one use the evidence supports
  without calibration: the signal is validated for *detecting* likely-wrong words, which
  needs relative discrimination, not calibrated probability. On the proxy set, flagging the
  lowest 10% of words catches 56% of scorable errors. Deletions (~41% of word errors there)
  are invisible to any word confidence.

What is deferred: any LLM call, to a user-requested async path at the earliest.
"Correct-after-injection and patch" becomes a Phase 2 candidate only if a calibration study on
our own data shows the signal is good enough to gate it.

The frozen "select, don't rewrite" position survives review and is strengthened. Apple's own
team found a 15x-smaller specialized seq2seq corrector beats LLM correction on WER; a
constrained reranking method removed 38.8–57.1% of hallucinated failures; a three-stage
framework exists specifically because naive LLM correction hallucinates. No source argues free
generation is safer on meaning preservation.

**But the tradeoff is preserved, not resolved:** free-generation rescoring reports the largest
raw WER gains, and no controlled A/B of constrained vs. free with both WER and a
meaning-preservation metric exists. There is also no citable ASR-specific semantic-drift
metric — that is a gap in the field, not an oversight in the search.

**Never auto-correct**, when correction eventually ships: uncalibrated spans; entities or
identifiers changed to a *different* entity than N-best or the bias list supports; anything in a
password field or blocklisted process (the correction path inherits the injection exclusions —
it does not get its own); deletions, because inserting a plausible word the user never said is
fabrication; any candidate not present in the N-best list or a bounded phonetic search; and
code-switched spans until a bilingual-aware path exists.

G2P, when phonetic candidates are needed: `g2p_en` (Apache-2.0) for the Python prototype,
`piper-plus-g2p` (MIT, explicitly built to avoid espeak-ng) as the Rust-native candidate.
**Avoid `phonemizer`/espeak-ng in any shipped path without a legal read** — `phonemizer` is
GPL-3.0 and loads `libespeak-ng` via ctypes, which is dynamic linking, not arm's-length
subprocess invocation. No redistributable English-tuned weighted-phoneme-edit-distance table
exists; expect to derive our own from our own confusion data.

## 10. Voice-action safety boundary

Phase 1 ships **Tier 0 (read-only) and Tier 1 (reversible with a real, tested undo) only.** No
Tier 2 or Tier 3 action type exists in the allowlist at all, because there is no
confirmation-outcome data to calibrate against and the HCI evidence says that data is the only
way to know whether any confirmation design works.

Minimum viable architecture:

- `WorkflowAction` is a **closed, versioned enum**, schema-validated. Anything that fails to
  parse falls back silently to literal dictation — the same shape D-0005 already specifies.
- **Allowlist action types** (our own closed design surface — an allowlist is strictly better
  and cheap here). **Blocklist targets** (processes, password fields — the universe of
  sensitive processes is open-ended and only heuristically identifiable).
- Executor is a separate module taking only the validated struct — never a string, never a
  callback into the model layer. **It must never re-invoke the model to ask whether an action is
  safe.** In Phase 1 this boundary is a process boundary (§1).
- **Undo-ability is a classification input, not a UI nicety.** An action without a reliable,
  tested undo is not Tier 1, regardless of how small it looks.
- Audit log records the structured action — type, tier, parameters, confirmation outcome,
  undo-used — **never the raw transcript.** This preserves the no-stored-transcripts promise
  while still producing the calibration data. Short retention, user-visible, user-clearable.
- Speaker similarity, if ever built, is a **risk-score input, never a gate** (§14).
- Rate limiting on Tier 1 bursts as a cheap tripwire.
- When Tier 2/3 eventually ships, confirmation UI is **templated from validated struct fields,
  never model-authored text** — otherwise the dialog itself becomes the injection vector.

Prohibited in Phase 1 regardless of usefulness: anything leaving the machine; file deletion or
overwrite outside a Hermes-owned scratch directory; anything targeting the blocklist, with no
override path; anything changing OS or application security settings or credentials; anything
financial; **any action whose parameters are sourced from harvested context rather than the
user's own dictated utterance** (this directly targets the injection vector); any action chained
from a prior action without a fresh hotkey press; and no action tier above 0 in voice-activated
mode.

That chaining rule comes from the browser's transient-activation model, which is the right
analogy: one keypress authorizes the utterance it started, not a session-long licence.

One constraint from the skill-squatting literature that is easy to miss: **similar-sounding
actions must not sit at different risk tiers**, or a misrecognition becomes a privilege
escalation. This constrains the action-naming scheme, not just the policy layer.

## 11. Model and runtime lifecycle

Revised VRAM budget, now that the correction LLM is out of Phase 1:

| Component | VRAM | Note |
|---|---|---|
| Silero VAD | ~0 (CPU) | ~1 MB ONNX |
| Parakeet TDT 0.6B v3 int8 | unmeasured on GPU | Resident; 996 MB working set on the CPU EP (Task 2a) |
| **Phase 1 total** | **~1 GB, estimated** | Large headroom against 6 GB |

*Corrected 2026-10-05:* this table originally budgeted Nemotron Streaming EN at ~0.7 GB.
Nemotron was eliminated by Task 2a (D-0013). Every Task 2a figure is CPU EP, so no candidate's
VRAM has been measured; the row above is a working-set figure, not a VRAM one.

The 4.8 GB worst case in `ARCHITECTURE.md` §1 was driven by a correction LLM that is no longer
in Phase 1. Headroom is now available for a second ASR tier (§6) if measurement justifies it —
but it must be justified, not filled because it is free.

Lifecycle requirements: models downloaded on first run with **SHA-256 verification**, resident
and warm (per-utterance model load is unacceptable), cold start < 2 s measured with the file
cache evicted, and both cold and warm start reported separately and labelled (omitting the gap
is a classic misleading benchmark).

Windows 11's WDDM compositor reserves an unmeasured slice of a 6 GB laptop GPU. Budget
empirically.

## 12. Windows injection strategy

**Correction to `ARCHITECTURE.md` §6.1 and `CLAUDE.md`: injection cannot be verified by
read-back.** Every method is unreliable, slow, or blocked by UIPI — `ValuePattern` readback
exists only where failure was least likely, `TextPattern.GetText` is cross-process COM costing
tens to hundreds of milliseconds and frequently stale in Chromium/Electron, `WM_GETTEXT` is
Win32-only and UIPI-blocked, and clipboard comparison proves only that we set the clipboard.

Replacement, and a better design anyway — **check preconditions, not postconditions**:

1. Before injecting: foreground HWND stable since activation, target integrity level ≤ ours,
   focused element `IsEnabled && IsKeyboardFocusable`, not a password field, not blocklisted.
2. Every injection is **idempotent and undoable** — one utterance is one atomic insert the user
   can Ctrl+Z.
3. Recognized text stays in our own history UI, so a silent failure is recoverable.
4. **Never report success we did not observe.** Detecting "target is elevated and I am not"
   *before* injecting and saying so beats a silent drop.

Cascade, per target: clipboard + Ctrl+V primary above ~100 chars and for
terminals/Office/Electron; `SendInput` + `KEYEVENTF_UNICODE` via raw `windows-rs` for short
inserts; UIA `ValuePattern.SetValue` as a narrow opportunistic path only, never the main one.
UIA's role is **inspection, not insertion**.

Clipboard hygiene is not fully solvable and must be honest about it: snapshot only
`CF_UNICODETEXT`, `CF_HDROP`, `CF_DIB`/`CF_DIBV5` and registered HTML/RTF; accept lossiness
elsewhere and document it; retry `OpenClipboard` with backoff (it is a single global lock); and
**register the privacy formats** — `ExcludeClipboardContentFromMonitorProcessing`,
`CanIncludeInClipboardHistory`, `CanUploadToCloudClipboard` — or Windows Clipboard History and
Cloud Clipboard capture every dictated utterance. For a privacy-positioned dictation app that is
a requirement, not an optimization.

Hotkeys: our own `WH_KEYBOARD_LL` on a dedicated thread with a watchdog, because silent unhook
is undetectable by design. `tauri-plugin-global-shortcut` cannot express push-to-talk — it wraps
`RegisterHotKey` and fakes key-release by polling `GetAsyncKeyState` every 50 ms.

uiAccess (for elevated windows) requires Authenticode signing plus per-machine install into
Program Files, which kills MSIX and user-local install. Phase 1 detects and warns. **Budget for
a code-signing certificate and a Program Files installer from day one** — retrofitting means
rebuilding the distribution pipeline.

## 13. Benchmark plan

`BENCHMARKS.md` stands, with four corrections applied (§17).

Headline is **F-WER**, decomposed for diagnosis into casing error rate, per-class punctuation
F1, and ITN slot error rate. Publishing the decomposition makes it harder to game than either
existing convention, which is the defensible position for a public benchmark. Vendor the Whisper
normalizer, version-pinned, to publish a secondary legacy-comparable score.

Decision rule, encoded before running experiments: per-utterance WER, paired bootstrap ≥2000
resamples with a fixed recorded seed, CI excluding zero, point estimate ≥0.3–0.5pp, E-WER
non-regression guard, latency p95 as a hard SLA gate rather than a statistical question.
**n=200 only reliably detects 1–3pp** — the canary set is for CI gating, not for publication.

Add **UPWR/UPSR** for partial-hypothesis stability. Note that beam-search biasing breaks the
monotonic-prefix property — the UI must tolerate already-displayed text being rewritten.

EdAcc (CC BY-SA 4.0) is the verified accent anchor. GigaSpeech is unusable (its Apache-2.0 label
is misleading; actual terms are non-commercial and bind for-profit employers). Common Voice
moved to Mozilla Data Collective with unverified terms. TED-LIUM, CHiME and Earnings licences
are unconfirmed and block publication until checked.

> **Superseded 2026-09-27** by the licence verification behind D-0012. Common Voice is still
> CC0 but is obtainable only through Mozilla Data Collective behind an account and a terms
> acceptance, so it is excluded on *access*, not licence. Golos' licence PDF was read in full:
> a CC BY-SA 4.0 reword with attribution plus ShareAlike and **no non-commercial clause**.
> Earnings-22's `LICENSE.md` covers transcripts only and the audio licence is unstated, so it
> is rejected. TED-LIUM 3 is CC BY-NC-ND. Full table:
> `eval/datasets/public-proxy-v1/LICENSES.md`.

## 14. Licensing constraints, consolidated

| Item | Licence | Status |
|---|---|---|
| Nemotron Speech Streaming **EN** 0.6B | NVIDIA Open Model License | Commercial OK |
| Nemotron 3.5 ASR Streaming (multilingual) | **`openmdw-1.1` — different from its EN sibling** | Verify separately |
| Parakeet TDT 0.6B v3, Canary-1B-v2 | CC-BY-4.0 | Commercial with attribution |
| ONNX Runtime, whisper.cpp, llama.cpp, `ort`, `llama-cpp-2` | MIT / Apache-2.0 | Clean, no GPL exposure |
| **universal-ctags** | **GPL-2.0-or-later** | **Legal read before bundling** |
| **`phonemizer` / espeak-ng** | **GPL-3.0**, loaded via ctypes = dynamic linking | **Avoid in shipped path** |
| `g2p_en`, `piper-plus-g2p`, `rustfst`, tree-sitter | Apache-2.0 / MIT | Clean |
| Gemma 3 | Google custom terms | **Not OSI-approved** |
| Llama 3.2 | Llama Community License | 700M MAU clause, irrelevant at our scale |
| Qwen3, Phi-4-mini, SmolLM3 | Apache-2.0 / MIT | Clean |
| SimulStreaming | **PolyForm Noncommercial** | Blocked; WhisperLiveKit inherits it by default |
| Moonshine | MIT **except non-English models** | Carve-out lands on our differentiator |
| SenseVoiceSmall | Custom proprietary | Verify before any commercial use |
| **CUDA / cuDNN** | cuDNN redistributability unconfirmed | **Blocks CUDA-in-installer pending legal read** |
| GigaSpeech | Non-commercial in practice | Unusable |
| EdAcc | CC BY-SA 4.0 | Verified, usable — **ShareAlike: do not redistribute derived audio** |
| Golos (crowd + farfield) | Golos Public License (CC BY-SA 4.0 reword) | **Verified 2026-09-27** — commercial OK, ShareAlike, no speaker IDs |
| LibriSpeech, RuLS | CC BY 4.0 / public domain | Verified, usable |
| OpenSLR 28 RIRs, MUSAN | Apache-2.0 / CC BY 4.0 | Verified, usable |
| Common Voice | CC0 | Licence fine; **access-gated** via Mozilla Data Collective since Oct 2025 |
| Earnings-22 | Transcripts CC BY-SA 4.0; **audio unstated** | Rejected |
| CS-FLEURS | CC BY-NC 4.0 | Rejected; ru/uk pairs are TTS anyway |

Three of these — ctags, espeak-ng, cuDNN — are the ones that could actually bite, because each
is easy to adopt casually and expensive to remove later.

## 15. Key risks

1. ~~**ONNX export may not expose per-token logits** (§5.1).~~ **Retired for Parakeet
   (D-0014, 2026-10-06):** the export exposes them, sherpa's API returns a sufficient token
   confidence, and N-best needs only a small owned Python loop. Still open for any other
   backend, Whisper included.
2. **Confidence is uncalibrated on our actual speech.** Every published number is LibriSpeech
   clean read speech. Our user is accented and code-switches. *Partly measured (Task 2b):*
   on accented English (EdAcc) Parakeet's word confidence reaches AUROC 0.863 and is mildly
   overconfident in aggregate. Code-switched speech and the user's own voice remain
   unmeasured.
3. **Per-app ITN aggressiveness is unattested.** Our invention, so it carries invention risk.
4. **Transparent + click-through + always-on-top HUD on WebView2/Win11 is unverified** and
   historically a pain point. Spike early with a throwaway window.
5. **uiAccess through Tauri's bundler is unverified.** `embed-manifest` 1.5.1 is the candidate;
   treat as a half-day spike.
6. **Process-boundary latency inside a 700 ms p95 budget is unmeasured.**
7. **No Slavic-English code-switching corpus exists.** Re-verified 2026-09-27: CS-FLEURS'
   `cs_rus_eng`/`cs_ukr_eng` are concatenative TTS and CC BY-NC. We collect our own or W2 has
   a hole.
8. ~~**Dataset licence blockers** could gut the published benchmark.~~ **Largely closed** by
   D-0012's verification. What remains is not a licence problem but a *reference* problem: no
   permissively-licensed public corpus ships a formatted reference, so F-WER — the headline —
   cannot be published from public data alone.
9. **Device hot-swap in cpal is not turnkey** — no stream auto-migration, no ergonomic
   `IMMNotificationClient`. Budget real time.
10. **`ort` has been pre-1.0 for years.** Pin exactly; expect breaking changes.

## 16. Reversible vs. difficult-to-reverse

**Difficult to reverse — decide carefully:**

- Signing certificate, per-machine Program Files installer, uiAccess posture. Retrofitting
  rebuilds the entire distribution pipeline.
- The Rust core as a library crate vs. entangled with Tauri. Cheap now, a rewrite later.
- The wire protocol's envelope and versioning discipline.
- Bundling a GPL binary (ctags) or a GPL-linked library (espeak-ng) into a commercial installer.
- AGPL-vs-Apache core licensing and the CLA.

**Reversible — decide fast, change on data:**

- ASR model choice. It is behind an interface; that is the whole point.
- Execution provider (DirectML ↔ CPU ↔ CUDA later).
- Quantization level.
- ITN rule content.
- Embedding model, speaker-verification model, correction LLM — all swappable behind narrow
  interfaces, and none ships in Phase 1 anyway.
- Transport (TCP ↔ named pipes) — localized behind a protocol module.

## 17. Corrections applied to existing docs

1. `ARCHITECTURE.md` §6.1 and `CLAUDE.md` — read-back verification replaced with precondition
   checks (§12).
2. `ARCHITECTURE.md` — UPWR/UPSR adopted; monotonic-prefix break recorded.
3. `BENCHMARKS.md` — H200 RTFx caveat, F-WER decomposition, CI decision rule, n=200
   detectability.
4. `ARCHITECTURE.md` — Rust core as a UI-agnostic library crate from day one.
5. `ARCHITECTURE.md` §5.5 — PAC citation corrected; correction pass moved out of Phase 1.
6. `ARCHITECTURE.md` §5.6 — WFST/Pynini ITN replaced with a rule cascade.

## 18. Proposed contracts — NOT implemented

Only what is needed to preserve backend replaceability. Deliberately fewer than the candidate
list in the brief: `SpeechSegment` is absent because VAD is internal to the sidecar and no other
subsystem needs to see segments; `RecognitionMetadata` is folded into `FinalTranscript` because
splitting them buys nothing while they always travel together.

Envelope for everything crossing the process boundary:
`{schema_version, type, seq, payload}`, version checked on **every** message from day one.

| # | Contract | Owner | Producer | Consumer | Crosses process | Latency-sensitive |
|---|---|---|---|---|---|---|
| C1 | `AudioChunk` | Rust core | Capture supervisor | Sidecar ASR | **Yes** | **Yes** — steady stream |
| C2 | `BiasContext` | Rust core | Context harvester | Sidecar ASR | **Yes** | Yes — must precede decode |
| C3 | `RecognitionRequest` | Rust core | Orchestrator | Sidecar ASR | **Yes** | Yes |
| C4 | `PartialTranscript` | Sidecar | Sidecar ASR | Orchestrator → HUD | **Yes** | **Yes** — highest frequency |
| C5 | `FinalTranscript` | Sidecar | Sidecar ASR + NLP | Orchestrator | **Yes** | **Yes** — on the p95 path |
| C6 | `NlpResult` | Sidecar | Sidecar NLP | Orchestrator | **Yes** | Yes |
| C7 | `Intent` | Sidecar | Sidecar NLP | Policy layer | **Yes** (inside C6) | No |
| C8 | `WorkflowAction` + `ActionRisk` | Rust core | Policy layer (from C7) | Executor | No — **must not** | No |
| C9 | `InjectionRequest` / `InjectionResult` | Rust core | Orchestrator | Injector | No | Yes |

**C1 `AudioChunk`** — `seq`, `sample_rate` (always 16000), `samples` (mono f32), `is_preroll`,
`capture_timestamp`. Versioning: format frozen; new fields additive-only. `is_preroll` exists so
the sidecar can distinguish pre-hotkey audio, which matters for endpointing.

**C2 `BiasContext`** — `session_id`, `phrases` (the *pruned active subset*, not the master
vocabulary), `per_phrase_boost`, `source_tags` (which harvester produced each), `profile_id`,
`vocabulary_hash` (for the benchmark RUN record). Versioning: additive. **`source_tags` is
load-bearing for safety, not diagnostics** — §10 forbids harvested context from parameterizing
an action, and this field is how that rule is enforceable. Do not drop it as redundant.

**C3 `RecognitionRequest`** — `session_id`, `mode` (streaming | final), `tier` (local | accuracy
| cloud), `language_hint`, `profile_id`, `decode_params` (beam, chunk_ms). Versioning:
`decode_params` is an open map so a new backend's knobs do not force a schema bump.

**C4 `PartialTranscript`** — `session_id`, `seq`, `text`, `stable_prefix_len`, `tokens[]` with
per-token `confidence`. `stable_prefix_len` is the contract that makes UPWR/UPSR measurable and
tells the HUD what it may stop re-rendering. **Must tolerate revision of already-emitted text** —
beam-search biasing breaks the monotonic-prefix property, so this is not hypothetical.

**C5 `FinalTranscript`** — `session_id`, `text`, `tokens[]` (`text`, `confidence`, `start_ms`,
`end_ms`), `nbest[]` (hypothesis + score), `language`, `tier_used`, `model_id`, `stage_timings`.
**`tokens[].confidence` and `nbest[]` are non-negotiable** — they are the reason this is a
contract and not a string, and §5.1 flags that a backend may not be able to supply them. A
backend that cannot is not a valid backend. *Parakeet can (D-0014):* `confidence` from
sherpa's emitted-token probability, `nbest[]` from an owned Python beam (K ≤ 4,
deduplicated, only when `decode_params.beam > 1`), and `nbest[].score` is rank-only, never a
probability.

**C6 `NlpResult`** — `raw_text`, `formatted_text` (post-ITN, what actually gets injected),
`itn_spans[]` (what changed and by which rule — needed for the ITN slot error rate),
`low_confidence_spans[]`, `intent` (C7). `formatted_text` is the F-WER measurement target.

**C7 `Intent`** — a closed enum. **In Phase 1 it has exactly one inhabited variant: `Literal`.**
Other variants are declared and never produced, per D-0005. Versioning: adding variants is a
minor bump; the consumer must reject unknown variants rather than ignore them.

**C8 `WorkflowAction` + `ActionRisk`** — closed versioned enum, schema-validated, typed
parameters only, never a string that gets executed. `ActionRisk` ∈ {Tier0, Tier1, Tier2, Tier3};
Phase 1 admits only Tier0 and Tier1. **This contract deliberately does not cross the process
boundary — the sidecar produces `Intent` (C7), and the Rust policy layer alone constructs the
`WorkflowAction`.** That asymmetry is the safety property; preserving it is what §10 is for.

**C9 `InjectionRequest` / `InjectionResult`** — request: `text`, `target_hwnd`, `strategy_hint`,
`activation_token` (proves focus has not changed since the hotkey press). Result:
`strategy_used`, `precondition_failures[]`, `attempted`, **and explicitly no `success: bool`** —
per §12, we do not report success we did not observe. Internal to Rust, but a real seam: it is
where the per-process strategy table is read and written.

---

## 19. Phase 1 milestone

Unchanged from `ROADMAP.md` Checkpoint 1 in substance, sharpened in scope:

1. Dictate for 30 consecutive days without reaching for the keyboard out of frustration.
2. F-WER beats Windows built-in dictation on the developer's own voice by a clear margin, with
   a bootstrap CI that excludes zero.
3. p95 end-to-end latency < 700 ms.

Scope changes from this synthesis: **no LLM correction pass** (§9), **no Tier 2/3 actions**
(§10), **English-first** (§6), **rule-cascade ITN** (§8), **confidence highlighting instead of
correction** (§9). Every one of these makes Phase 1 smaller than `ROADMAP.md` currently assumes.
That is the correct direction.

## 20. Explicitly deferred — do not freeze

- **ASR model choice.** Phase 0 measurement decides. Freezing now would be deciding from
  leaderboard numbers measured on an H200.
- **Whether a WFST build-time toolchain is worth it.** The runtime conclusion (no Pynini in the
  installer) is solid; whether an offline Linux/WSL grammar-compilation step beats hand rules is
  a tradeoff to settle once rule coverage is measured against F-WER.
- **The action-risk taxonomy's escalation/de-escalation triggers.** The four tiers are
  directionally solid and map onto Apple's model. The triggers are a first draft, and the HCI
  evidence says only real confirmation and undo-rate data can calibrate them.
- **Speaker verification at all.** Signal-not-gate is the recommendation *if* it is built;
  whether to build it is undecided and low priority.
- **Embedding model, NER, intent classifier tiers.** No consumer exists under D-0005.
- **The correction pass, permanently or otherwise.** It stays on probation. If highlighting
  alone does not move F-WER, cut that too.
- **ctags as a bundled dependency**, pending the GPL read.
- **CUDA execution provider**, pending the cuDNN read.
- **Two resident ASR models** for multilingual. VRAM allows it; nothing yet justifies it.

## Sources

This document synthesizes `docs/research/R1`–`R9`. Primary sources, with evidence labels and
verification status, live in those memos; nothing is asserted here that is not sourced there.
