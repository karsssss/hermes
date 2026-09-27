# Current

The only doc expected to change every session. Read this first when resuming work.

**Last updated:** 2026-09-27

## Where we are

**Research is complete.** R1–R9 all landed, were verified on disk, and have been synthesized
centrally into `docs/SYNTHESIS.md`, which is now the current decision document. Five new
decisions (D-0007…D-0011) were recorded, and six corrections were applied to
`ARCHITECTURE.md`, `BENCHMARKS.md` and `CLAUDE.md`.

**Phase 0 has started. The evaluation harness exists and passes its own tests.**
`uv` is installed; `pyproject.toml`, `src/hermes_eval/` and `eval/` are on disk. 88 tests,
ruff and pyright clean. Zero runtime dependencies — the scoring path is pure stdlib on
purpose, because a published benchmark cannot blame its numbers on a third-party WER
package.

What the harness does today: strict manifest validation, per-utterance and corpus WER,
F-WER with the full decomposition (casing error rate, per-class punctuation F1, ITN slot
error rate), E-WER over annotated entity spans, latency percentiles, subset metrics on
every metadata axis, a seeded paired utterance-level bootstrap, the decision rule from
`BENCHMARKS.md` §1.2 encoded in code, and immutable run directories carrying full
provenance. Two adapters: `perturb` (deterministic synthetic fake-ASR, for fixtures) and
`replay` (scores transcripts captured by hand — this is how closed competitors get
measured). See `eval/README.md`.

**The Public Proxy Evaluation Set v1 exists and validates.** 160 utterances from pinned
public corpora — EdAcc (50, 25 speakers, 16 L1 backgrounds), LibriSpeech test-clean (30, one
per speaker), RuLS (20, 7 readers), Golos crowd and farfield (10 each), plus 20 noise and 20
reverb variants of the same 20 clean utterances. Built by `hermes-eval build-dataset` from
full commit shas; the manifest and audio are **byte-identical across rebuilds**. No audio is
redistributed — EdAcc and Golos both carry ShareAlike, and `eval/datasets/**/audio/` stays
gitignored. See D-0012 and `eval/datasets/public-proxy-v1/`.

**It is a proxy and it does not retire Task 1b.** No public corpus in scope ships a formatted
reference, so **F-WER is not computable on it**, and none annotates entity spans, so **E-WER
is not either**. It measures WER on accented English, read English, read Russian, Russian
far-field commands, and two robustness deltas. It measures nothing about dev-speak,
code-switching, ITN, punctuation, the real microphone or the capture path. Any model decision
made on it alone is provisional.

**Task 2a (ASR candidate screening) is two-thirds measured and INTERRUPTED.** Three real ASR
backends now run through the harness on ONNX Runtime. Two completed against the frozen proxy
set; the third was killed before it decoded anything. Full state in **§ Task 2a — recovery
state** below and in `docs/research/T2A-screening.md`. **Do not restart a run without
reading that section first** — one of the three is unmeasured and the eliminations are on
hold because of it.

**No audio capture, no Rust.** That is deliberate and unchanged. There is now ASR, but only
as a measurement harness: `src/hermes_eval/asr_sherpa.py` exists to score candidates, not to
ship.

## Read order for a fresh session

1. `CLAUDE.md` — invariants and vocabulary
2. **`docs/SYNTHESIS.md`** — the decision document; supersedes `ARCHITECTURE.md` where they
   disagree
3. `docs/DECISIONS.md` — D-0001…D-0012
4. `docs/ROADMAP.md` — phases and checkpoints (Phase 1 scope is narrowed by SYNTHESIS §19)
5. `docs/research/R1…R9` — evidence, only as needed

## Research status — closed

| # | Workstream | State |
|---|---|---|
| R1 | Quantization & contextual biasing | Done — partially superseded by R4 |
| R2 | Hotkeys & text injection | Done |
| R3 | Streaming stability & code-switch LID | Done |
| R4 | ASR model landscape (salvaged) | Done |
| R5 | Rust stack | Done |
| R6 | Benchmark methodology & harness design | Done |
| R7 | NLP, intent, ITN | **Done** 2026-09-26 |
| R8 | Correction pass, GER, confidence | **Done** 2026-09-26 |
| R9 | Voice-command safety | **Done** 2026-09-26 |
| — | **Central synthesis** | **Done** 2026-09-26 → `docs/SYNTHESIS.md` |

## Target hardware

i5-12450H (8C/12T, Alder Lake, AVX-VNNI) · 15.7 GB RAM · RTX 4050 Laptop **6 GB VRAM** ·
Windows 11. CPU-only must be first-class.

**Methodology warning:** Open ASR Leaderboard RTFx is measured on 1x H200 + 23 vCPU + 256 GB
RAM. **None of it transfers.** The only laptop-class figures found anywhere are qwen3-asr.cpp
on an RTX 5060 8 GB (235 ms median per 2 s chunk, 0.6B) and LocalScore's RTX 4050 llama.cpp
submissions (Llama-3.2-1B Q4_K_M: 301 ms TTFT).

Toolchain: Python 3.11.14, Node 24.14, git 2.53, **`uv` 0.12.19** (installed 2026-09-26 to
`~/.local/bin`). **Missing: `rustup`** — a Phase 1 prerequisite (D-0006), not Phase 0.

## Task 2a — recovery state (2026-09-27)

**Read this before touching anything ASR.** Task 2a is screening three candidates from
`SYNTHESIS.md` §5 against the frozen proxy set, to eliminate the unsuitable ones cheaply. It
is **incomplete**. Two of three runs finished; the third was killed by the harness because the
machine ran critically low on memory while the session was idle. That kill says nothing about
the model — it never decoded an utterance.

### Run status

| Candidate | Status | Run ID |
|---|---|---|
| **Parakeet TDT 0.6B v3 int8** | **Complete** | `20260927T022919Z-t2a-parakeet-tdt-v3-aff8` |
| **Nemotron Speech Streaming EN 0.6B @560 ms int8** | **Complete** | `20260927T031249Z-t2a-nemotron-stream-en-560ms-c9f4` |
| **Whisper large-v3-turbo int8** | **INCOMPLETE — no usable data** | none; killed 03:12:50Z, before the first utterance |

Both completed runs scored manifest sha256 `2b3a46ede2700f30…`, n=160, and carry all six run
artifacts. **Both live under `eval/runs/`, which is gitignored** — they exist on this machine
only. Promote them with `git add -f` if they belong in the record; otherwise re-running is the
only way to get them back.

### THE NEXT ACTION — rerun Whisper alone to finish Task 2a

```
uv run hermes-eval run --manifest eval/datasets/public-proxy-v1/manifest.jsonl \
    --adapter "sherpa:whisper-large-v3-turbo,langs=en|ru" \
    --label t2a-whisper-large-v3-turbo --dataset public-proxy-v1 --resources
```

Roughly 35 minutes at the measured RTF of ~1.8, holding 1–1.5 GB. **Close the browser first.**
At the time of the kill, Edge alone held 4.3 GB of the machine's 15.7 GB and free physical RAM
was 1.7 GB; that is what triggered the reap.

Nothing else in Task 2a is outstanding. The adapters, the resource sampling and the report
scaffold are all on disk and working.

### Provisional finding — Nemotron is dominated, pending Whisper

On identical audio, runtime, provider, thread count and warm-up policy (WER %, lower better):

| subset | n | Parakeet TDT v3 | Nemotron EN 560 ms |
|---|---:|---:|---:|
| OVERALL | 160 | **13.29** | 32.55 |
| general_en | 30 | **1.81** | 4.12 |
| accented_en | 50 | **18.74** | 27.67 |
| ru_clean / ru_command / ru_farfield | 20/10/10 | 13.41 / 3.08 / 37.78 | 100 / 100 / 100 |
| robust_noise | 20 | **18.42** | 30.12 |
| robust_reverb | 20 | **12.57** | 28.36 |

| | Parakeet | Nemotron |
|---|---:|---:|
| RTF corpus (p50 / p95) | **0.47** (0.52 / 0.79) | 2.44 (2.44 / 2.84) |
| latency p50 / p95 | **2693 / 5707 ms** | 12741 / 40029 ms |
| median latency, utterances ≤3 s | **1961 ms** | 5886 ms |
| model load / warm-up | 5735 / 5121 ms | 6699 / 19132 ms |
| peak working set | 996 MB | **797 MB** |
| peak VRAM | null (CPU EP) | null (CPU EP) |
| empty outputs | 2 | 23 |

Nemotron's Russian rows are **100% by design, not by failure** — it is en-US only, and
SYNTHESIS §6 puts Phase 1 on an English-first track, so those rows carry no weight in an
elimination. It loses the English rows too, and the decisive number is **RTF 2.44 on the CPU
EP**: about a fifth of real time, p95 40 s per utterance against a 700 ms end-to-end budget.
CPU-only is a first-class requirement, so that is a 5× gap rather than a tuning gap.

**This directly contradicts SYNTHESIS §5, which calls Nemotron at 560 ms the "leading
hypothesis."** That hypothesis was formed without a laptop-class measurement, which is exactly
the trap `BENCHMARKS.md` §1.3 warns about. It is not overturned until Whisper lands and the
eliminations are written — but expect it to be.

**No candidate has been eliminated and no production backend has been chosen.** Both are
deliberately deferred until all three are measured.

### Findings already banked, independent of Whisper

- **ORT DLL conflict on Windows, and it will recur.** The sherpa-onnx wheel ships no
  `onnxruntime.dll`, so Windows resolves the bare name to the inbox
  `C:\Windows\System32\onnxruntime.dll` — version 1.17, the Windows ML copy — while sherpa
  1.13.8 needs ORT API 28. Symptom: `The requested API version [28] is not available, only API
  versions [1, 17] are supported in this build`. Fix: pin `onnxruntime==1.28.0` and copy its
  DLL next to `_sherpa_onnx.pyd`, since a dependent DLL resolves from the loading module's own
  directory before System32. `hermes_eval.asr_sherpa.ensure_runtime()` does it.
  **Anyone shipping ORT on Windows meets this; the inbox copy is not going away.**
- **DirectML needs a D-0011 revisit.** ONNX Runtime's own documentation now states: *"DirectML
  continues to be supported, but new feature development has moved to WinML for Windows-based
  ONNX Runtime deployments."* On top of that, sherpa-onnx ships no prebuilt DirectML wheels
  (source build only), and all three candidate exports are dynamic int8 (`producer:
  onnx.quantize`) — the pattern the DML EP handles worst, so expect CPU fallback rather than
  speed-up, and an fp16 re-export if a DML path is wanted. DirectML viability is therefore
  **unmeasured for all three, uniformly**. D-0011's reasoning for DirectML (ships with the
  driver stack, vendor-neutral, no redistribution question) still holds; its upstream status
  does not. **Needs a DECISIONS entry weighing WinML, not a silent switch.**
- **The confidence signal is partially reachable, cheaply.** sherpa-onnx's
  `OfflineRecognitionResult` exposes `ys_log_probs`, `tokens` and `timestamps`;
  `OnlineRecognizerResult` exposes `ys_probs`, `lm_probs` and `context_scores`. That is the
  log-prob of the **emitted** token, not the full per-step distribution that R8's entropy
  method needs, so it narrows open question #1 without closing it — and it is reachable
  through a decode loop somebody else already wrote, which is evidence about §5.1's fallback
  plan. N-best would come from `decoding_method="modified_beam_search"`, untested.
- **Whisper's 30 s window is structural.** Its encoder pads every input to 30 seconds, so a 3 s
  utterance costs what a 30 s one does. For dictation, where the median utterance is a few
  seconds, that is an architectural property and not something tuning fixes. Calibration showed
  ~11 s per decode regardless of utterance length.
- **A fairness defect to correct when Whisper is rerun.** sherpa binds Whisper's language at
  recognizer construction, so `langs=en|ru` builds two ORT sessions over the same weights and
  its peak RAM will read roughly 2× high against the other two. Either measure a single-session
  figure separately, or report the number as an upper bound and say why.

### Harness changes made for Task 2a (on disk, uncommitted)

- `src/hermes_eval/asr_sherpa.py` — the three candidates, pinned, behind the existing
  `ASRAdapter` seam. Never reads `record.reference`.
- `src/hermes_eval/resources.py` — per-process peak working set / commit, and PID-attributed
  VRAM. This is R6's deferred resource sampling, now landed. Peak VRAM is **null rather than
  zero** when nothing is attributable: "no GPU allocation" and "could not observe one" are
  different claims.
- `runner.py` re-reads `describe_env()` after the loop, so corpus RTF and decode totals reach
  the run record; `predictions.jsonl` now carries per-utterance `extra` (RTF, audio seconds).
- `hermes-eval run --resources` turns sampling on. Off by default.
- `pyproject.toml` gains an optional `asr` group (sherpa-onnx, onnxruntime, numpy, soundfile).
  The scoring path stays stdlib-only and never imports it.
- Models live in `models/` (gitignored), ~1.5 GB, fetched from the sherpa-onnx `asr-models`
  release. Download commands are in `docs/research/T2A-screening.md`.

## Next steps — Phase 0

Phase 0 is a **throwaway Python spike, ~1 week** (D-0006). Its purpose is no longer vague:
it exists to settle a specific measurement list that every research memo deferred to it.

### AFTER TASK 2a — record the personal eval set (Task 1b)

**Not the immediate next action.** Finishing Task 2a (the Whisper rerun, above) comes
first, and the personal set is explicitly deferred for now. This stays here because it is
the task that unblocks every differentiator, and because no amount of proxy-set work
retires it.

The harness half of Task 1 is done, and the public proxy set now covers the part of the data
half that does not need a microphone. **The rest still needs one.** Every differentiator —
dev-speak, code-switching, ITN, punctuation and casing, the real room — is measurable only
against the personal set.

Concretely:

1. Record **30 utterances** during real use, 16 kHz mono 16-bit WAV, one file per
   utterance, into `eval/datasets/personal/audio/`.
2. Follow `eval/datasets/personal/RECORDING.md` — it has the coverage split (8 dev_speak,
   6 prose, 6 code_switch, 5 itn, 5 adversarial) and the **transcribe-twice-and-reconcile**
   discipline, which is not optional.
3. Annotate `entities` and `itn_slots` as you go. E-WER is only as good as that
   annotation, and E-WER is the guard that stops an aggregate win from hiding rare-word
   damage.
4. Start from `manifest.template.jsonl`; run
   `uv run hermes-eval validate eval/datasets/personal/manifest.jsonl` until it is clean.
5. Sanity-check the harness against the real set with
   `uv run hermes-eval run --manifest eval/datasets/personal/manifest.jsonl --adapter perturb:seed=1`
   — the numbers are meaningless, but a real manifest exercising the real code path is not.

This is a recording session, not a coding session. It needs a human with a microphone.

### Deferred out of the harness, deliberately

- **UPWR/UPSR** (partial-hypothesis stability, arXiv 2006.01416). Needs a backend that
  emits partial hypotheses; there is nothing to measure until one exists.
- **The vendored, version-pinned Whisper `EnglishTextNormalizer`** for the secondary
  legacy-comparable score. Needs a pinned third-party source; it is a secondary number,
  never the headline.
- ~~**Resource sampling** (`nvidia-smi`, `Get-Counter` per R6).~~ **Landed 2026-09-27**
  with the first real models — `src/hermes_eval/resources.py`, enabled by
  `hermes-eval run --resources`. Per-process counters, not system free memory, because on
  a laptop with a browser open the system figure measures the browser. Peak VRAM is null
  rather than zero when unattributable. The cold-vs-warm-start discipline is in the
  adapter: model load, model hash and warm-up are timed separately from decode, and
  warm-up is two passes over a fixed synthetic signal, never dataset audio.
- A **CI canary manifest and checked-in baselines**. Premature while the only dataset is
  synthetic — `hermes-eval compare` already exits non-zero on a regression, so the gate
  itself is ready.

One harness detail worth remembering: WER can come out *above* F-WER on the same run,
because `basic` normalization splits `kube-system` into two tokens while `raw` keeps it as
one. Different denominators, not a bug.

**Task 2 — the measurement list.** Every one of these is scored through
`hermes-eval`; none of them is worth running before Task 1b exists. In rough priority
order:

1. **Can per-token logits be reached from an ONNX export?** (`SYNTHESIS.md` §5.1.) This is an
   explicit Phase 0 exit criterion. If no, Phase 1 scope changes materially — we would have to
   run the transducer decode loop ourselves.
2. fp32 vs int8 WER on our own audio, for whichever backend we test. **No measured pair exists
   anywhere** — circulating claims trace to content farms.
3. Nemotron Streaming EN vs Parakeet TDT v3 on the personal set: F-WER, E-WER, latency.
4. int8-vs-fp32 joiner emission *timestamp* drift (WER is insensitive to this failure mode).
5. Thread-count sweep on the P/E-core split — `-t 4/6/8/12`.
6. Confidence signal quality on **accented and code-switched** speech — nobody has measured
   this, and it is the gap that matters most for our user.
7. Process-boundary (IPC + serialization) latency against the 700 ms p95 budget.
8. Whether biasing actually moves E-WER without raising false insertions on a no-bias-term
   control set.

**Checkpoint 0 is unchanged:** hotkey → speak → text lands in Notepad. Any latency.

**Two early spikes that are cheap and de-risk Phase 1**, worth doing whenever blocked on
Phase 0: transparent + click-through + always-on-top on WebView2/Win11 with a throwaway
window; and `embed-manifest` injecting `uiAccess="true"` through Tauri's bundler (~half a day).

## Open questions

Settled since the last update: **#10 (Pynini/OpenFst on Windows) — closed by D-0008.**

1. **Can an ONNX export supply token-level confidences and an N-best list?** Highest-value
   unknown in the plan. If not, the fix is writing our own transducer decode loop in Rust —
   substantial work for a Rust beginner. Phase 0 exit criterion.
   **Narrowed 2026-09-27, not closed.** sherpa-onnx's result objects expose
   `ys_log_probs` / `tokens` / `timestamps` (offline) and `ys_probs` / `lm_probs` /
   `context_scores` (online) over these exact ONNX exports. So *a* per-token probability is
   reachable from an ONNX artifact, through a transducer decode loop that already exists in
   C++. What is still unverified is whether the **full per-step distribution** is reachable —
   R8's entropy method needs the distribution, not just the emitted token's log-prob — and
   whether N-best comes out of `modified_beam_search`. Both are cheap to test next.
2. **Is the confidence signal usable on accented/code-switched speech?** Every published
   number is LibriSpeech clean read speech. Our user is neither.
3. **CUDA/cuDNN redistribution** — needs a direct EULA read before any CUDA-in-installer work.
   DirectML is the default until then — but see #14: DirectML's own status has changed.
4. **universal-ctags is GPL-2.0-or-later** — legal read before bundling the binary. Subprocess
   invocation differs from linking, but that is not a question to settle by inference.
5. **espeak-ng / `phonemizer` are GPL-3.0**, and `phonemizer` loads `libespeak-ng` via ctypes
   (dynamic linking, not arm's-length). Avoid in any shipped path pending a legal read.
   `piper-plus-g2p` (MIT) is the clean Rust-native alternative.
6. `uiAccess` through Tauri's bundler — unverified; `embed-manifest` 1.5.1 is the candidate.
7. Transparent + click-through + always-on-top HUD on WebView2/Win11 — unverified.
8. Process-boundary latency inside the 700 ms p95 budget — unmeasured.
9. ~~Dataset licences: Common Voice post-migration terms, TED-LIUM, CHiME, Earnings-21/22.~~
   **Closed 2026-09-27** for everything the proxy set touches; see
   `eval/datasets/public-proxy-v1/LICENSES.md`. Common Voice: still CC0, but exclusively via
   Mozilla Data Collective behind an account and terms acceptance since Oct 2025 — excluded on
   *access*, not licence. Golos: licence PDF read in full — CC BY-SA 4.0 reword, attribution
   plus ShareAlike, **no non-commercial clause**, and no speaker IDs published at all.
   Earnings-22: `LICENSE.md` covers transcripts only, **audio licence unstated** — rejected.
   TED-LIUM 3: CC BY-NC-ND. CS-FLEURS: CC BY-NC. GigaSpeech unusable. EdAcc verified.
10. **No Slavic-English code-switching corpus found** — re-verified 2026-09-27 and now sharper.
    CS-FLEURS has `cs_rus_eng` and `cs_ukr_eng`, but **only in its `mms` subset, which is
    concatenative TTS**; its real-human `read` subset covers `rus` but not `ukr`, and the whole
    dataset is CC BY-NC 4.0. Synthetic code-switch audio is not an acceptable substitute.
    Collect our own; say so in any published methodology.
11. Nemotron 3.5 multilingual carries `openmdw-1.1`, **a different licence from its English
    sibling** — verify separately before relying on it.
12. ~~sherpa-onnx `token_log_probs` (PR #2897) merge/release status is ambiguous~~ —
    **resolved 2026-09-27**: sherpa-onnx 1.13.8 exposes `ys_log_probs` on
    `OfflineRecognitionResult` and `ys_probs` on `OnlineRecognizerResult`, observed
    directly on the installed wheel. `rule_fsts` / `HomophoneReplacerConfig` semantics
    remain unconfirmed. Note this now matters more than it did: sherpa-onnx is the
    screening harness, even though R5's objection to shipping it from Rust still stands.
13. Model licensing audit still incomplete for Kyutai, FireRedASR, Granite Speech, Canary-Qwen,
    SenseVoice.
14. **Is DirectML still the right default execution provider?** ONNX Runtime's docs now say
    new feature development has moved to **WinML**; sherpa-onnx has no prebuilt DirectML
    wheels; and dynamic-int8 graphs are what the DML EP handles worst. D-0011's *reasons*
    for DirectML still hold, its upstream trajectory does not. Raised 2026-09-27 by Task 2a.
15. **Does any candidate reach the 700 ms p95 budget on this hardware at all?** Measured so
    far: Parakeet p95 5707 ms, Nemotron p95 40029 ms, on the CPU EP at 4 threads, whole-
    utterance decode. The budget assumes streaming decode overlapped with speech, which none
    of these runs did — so this is not yet a fair comparison against it, and making it one is
    its own experiment.

## Decisions (full text in `DECISIONS.md`)

- **D-0001** Windows first
- **D-0002** Local-first inference, optional cloud
- **D-0003** Python prototype then Rust core *(partially superseded by D-0006)*
- **D-0004** Flat, purpose-named docs
- **D-0005** Workflow contracts frozen day one, engine deferred past Checkpoint 1
- **D-0006** Rust shell from Phase 1; Python as inference sidecar behind a versioned protocol
- **D-0007** Injection is precondition-checked, not read-back-verified
- **D-0008** No Pynini/OpenFst at runtime; ITN is a hand-written rule cascade
- **D-0009** No LLM correction pass in Phase 1; confidence highlighting instead
- **D-0010** Voice actions: Tier 0/1 only; the process boundary is the safety boundary
- **D-0011** ONNX Runtime is the substrate; the ASR model is decided by measurement
- **D-0012** Public proxy eval set stands in for the personal set, and never replaces it

## Standing instructions

- **Commit only on request.** `docs/research/`, `docs/SYNTHESIS.md` are untracked or modified
  but on disk; so is the whole Phase 0 harness (`pyproject.toml`, `src/`, `tests/`, `eval/`)
  as of 2026-09-26, and the public proxy set as of 2026-09-27. **Task 2a's harness work is
  uncommitted as of 2026-09-27**: `src/hermes_eval/asr_sherpa.py`,
  `src/hermes_eval/resources.py`, and edits to `adapters.py`, `runner.py`, `cli.py`,
  `pyproject.toml`, `tests/test_datasets.py`.
- **The two completed Task 2a runs are gitignored and exist on this machine only.**
  `eval/runs/20260927T022919Z-t2a-parakeet-tdt-v3-aff8` and
  `eval/runs/20260927T031249Z-t2a-nemotron-stream-en-560ms-c9f4`. Losing them costs ~50
  minutes of compute to regenerate. Promote with `git add -f` if they belong in the record.
- **`eval/datasets/public-proxy-v1/manifest.jsonl` and `build.json` are the artifacts; the
  audio is not.** Never commit third-party audio — two source corpora carry ShareAlike.
- `eval/runs/` is gitignored. Promote a run deliberately with `git add -f` when it belongs
  in the record; baselines change only by an explicit reviewed edit, never silently.
- No pipeline change lands without an eval delta. F-WER is the headline; latency p95 is a
  hard gate.
- Deltas smaller than the bootstrap CI are noise, not wins.
