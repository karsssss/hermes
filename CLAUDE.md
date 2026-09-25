# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Hermes is a local-first Windows dictation service. **The repository currently contains only
planning documents — no code exists yet.** Start from `docs/03-roadmap.md` Phase 0.

Read `docs/02-architecture.md` before writing any pipeline code; it specifies component
boundaries that later phases depend on.

## Commands

No build system yet. When Phase 0 starts, the stack is Python 3.11 managed by `uv`
(not yet installed on this machine), with ruff, pyright, and pytest.

Update this section as soon as `pyproject.toml` exists.

## Architecture constraints that are easy to violate

These are decided, documented, and costly to undo. Do not quietly deviate — if a change
seems necessary, add an ADR to `docs/decisions/`.

- **Models sit behind interfaces.** `AsrEngine`, `Injector`, `ContextHarvester`,
  `AudioSource` are the seams. The Python prototype is deliberately throwaway (ADR-0003);
  it must keep these seams clean so the Phase 3 Rust port is mechanical. No Win32 types
  leak into pipeline code (ADR-0001).
- **`AsrResult` carries token-level confidences and an N-best list**, never just a string.
  The correction pass is impossible without them, and most ASR wrappers discard them.
- **The audio thread does no allocation, no logging, and takes no locks.** Even in Python.
- **1.5 s pre-roll is mandatory**, not an optimization. Removing it clips first words.
- **Nothing hits the network unless the user opted into a cloud tier** (ADR-0002), and the
  UI states which tier ran, per utterance.
- **The LLM correction pass selects among candidates; it never freely rewrites.** Every
  correction passes an edit-distance validator before acceptance, and falls back silently
  to the unedited transcript on rejection. See `docs/02-architecture.md` §5.5.
- **Injection is verified, not fire-and-forget.** Read back via UIA, fall back down the
  cascade, persist the winning strategy per process. Always restore the clipboard in a
  `finally`. Never inject if focus changed since activation, into a password field, or into
  a blocklisted process.

## Working norms for this repo

- **No pipeline change lands without an eval delta.** `docs/05-evaluation.md` defines the
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
| **W1–W4** | The four candidate differentiators in `docs/01-strategy.md` §3 |

## Non-goals

Meeting transcription, diarization, voice assistants/agentic commands, mobile, real-time
conversational translation, batch file transcription. See `docs/03-roadmap.md`.
