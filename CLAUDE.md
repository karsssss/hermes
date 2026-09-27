# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Hermes is a local-first Windows dictation service. **Phase 0 is under way.** The only code
in the repository is the evaluation harness (`src/hermes_eval/`, `eval/`) — no ASR, no
audio capture, no Rust yet. Read `docs/CURRENT.md` for where things stand.

Read `docs/SYNTHESIS.md` first — it is the current decision document (R1–R9 synthesized,
Phase 1 scope, proposed contracts, deferred decisions) and it corrects several claims in
`ARCHITECTURE.md`. Then read `docs/ARCHITECTURE.md` for the target design.

## Commands

Python 3.11 managed by `uv` (installed at `~/.local/bin`), with ruff, pyright and pytest.

```
uv sync --group dev          # create/refresh .venv
uv run pytest                # tests
uv run ruff check . ; uv run ruff format --check .
uv run pyright

uv run hermes-eval validate eval/datasets/mock/manifest.jsonl
uv run hermes-eval run --manifest <manifest> --adapter perturb:seed=1 --label <name>
uv run hermes-eval compare <baseline-run-dir> <candidate-run-dir> --latency-budget-ms 700

uv sync --group data     # only for the line below; the scoring path stays stdlib-only
uv run hermes-eval build-dataset eval/datasets/public-proxy-v1/spec.json     --out eval/datasets/public-proxy-v1
```

`eval/README.md` documents the harness: metric definitions, the decision rule, the adapter
seam, and what is deliberately not in v0.

**On the public proxy set (`eval/datasets/public-proxy-v1/`): F-WER and E-WER are not
computable on it** — no public corpus in scope ships a formatted reference or entity
annotations. Read WER. Never publish a number from it as F-WER. Its README says this first
for a reason; `COVERAGE.md` lists everything it cannot measure. **Never commit third-party
audio** — EdAcc and Golos both carry ShareAlike, so the set ships as a manifest plus a
fetcher.

## Architecture constraints that are easy to violate

These are decided, documented, and costly to undo. Do not quietly deviate — if a change
seems necessary, add an entry to `docs/DECISIONS.md`.

- **Models sit behind interfaces.** `AsrEngine`, `Injector`, `ContextHarvester`,
  `AudioSource` are the seams. The Python prototype is deliberately throwaway (D-0003);
  it must keep these seams clean so the Phase 3 Rust port is mechanical. No Win32 types
  leak into pipeline code (D-0001).
- **`AsrResult` carries token-level confidences and an N-best list**, never just a string.
  The correction pass is impossible without them, and most ASR wrappers discard them.
- **The audio thread does no allocation, no logging, and takes no locks.** Even in Python.
- **1.5 s pre-roll is mandatory**, not an optimization. Removing it clips first words.
- **Nothing hits the network unless the user opted into a cloud tier** (D-0002), and the
  UI states which tier ran, per utterance.
- **The LLM correction pass selects among candidates; it never freely rewrites.** Every
  correction passes an edit-distance validator before acceptance, and falls back silently
  to the unedited transcript on rejection. See `docs/ARCHITECTURE.md` §5.5. **It does not
  ship in Phase 1** (D-0009): measured TTFT on our GPU exceeds the entire correction budget
  before a single token is generated, and the confidence signal that would gate it is
  uncalibrated. Phase 1 ships confidence-based highlighting only.
- **Injection checks preconditions, not postconditions.** R2 established that injection
  success is *not verifiable in general* — UIA read-back is slow, stale in Chromium/Electron,
  and UIPI-blocked for elevated targets. So: verify before (focus stable since activation,
  integrity level <= ours, `IsEnabled && IsKeyboardFocusable`, not a password field, not
  blocklisted), make every insert atomic and Ctrl+Z-undoable, keep the text in our own history
  so a silent failure is recoverable, and **never report success we did not observe**. Fall
  back down the cascade and persist the winning strategy per process. Always restore the
  clipboard in a `finally`, and register the clipboard privacy formats or Windows Clipboard
  History captures every utterance.

## Working norms for this repo

- **No pipeline change lands without an eval delta.** `docs/BENCHMARKS.md` defines the
  metrics. The headline number is **F-WER** (formatted WER on the final injected text), not
  plain WER. Latency p95 is a build gate, not a nice-to-have.
- Deltas smaller than the bootstrap confidence interval are noise. Don't report them as wins.
- Features that sound impressive but don't move F-WER get cut. This applies especially to
  the denoiser and the LLM correction pass — both are explicitly on probation.
- Prefer measuring over reasoning when they conflict. Audio intuition is unreliable.

## Domain vocabulary

| Term | Meaning |
|---|---|
| **F-WER** | Formatted WER — computed on the final injected text, post-ITN, case- and punctuation-sensitive |
| **E-WER** | Entity WER — restricted to code identifiers, names, domain terms |
| **ITN** | Inverse text normalization: "twenty twenty six" → "2026" |
| **Biasing** | Boosting the probability of context-derived terms during decoding |
| **Injection** | Delivering recognized text into the focused application |
| **Pre-roll** | Audio retained from before the hotkey press |
| **Endpointing** | Deciding that an utterance has finished |
| **W1–W4** | The four candidate differentiators in `docs/PRODUCT.md` §3 |

## Non-goals

Meeting transcription, diarization, voice assistants/agentic commands, mobile, real-time
conversational translation, batch file transcription. See `docs/ROADMAP.md`.
