# Hermes

Local-first speech-to-text for people who think faster than they type.

A background dictation service for Windows that works in every app — terminal, IDE,
browser, chat — runs entirely on-device, and understands the vocabulary of the project you
actually have open.

> **Status: planning.** No code yet. The design, strategy, and roadmap are in `docs/`.
> `Hermes` is an internal codename; it collides with several existing products and needs a
> trademark check before any public launch.

## Why

Native dictation on Windows is mediocre. The good local-first alternatives are macOS-only.
The cross-platform alternatives are cloud-first, English-first, and tuned for writers rather
than for people who spend the day in a terminal.

Three bets:

1. **Local** — because context harvesting (reading your clipboard, your focused text field,
   and the identifiers in your open git repo) is only defensible if nothing leaves the
   machine. Privacy isn't a compliance checkbox here; it's what makes the accuracy feature
   possible at all.
2. **Windows, properly** — including the places every competitor silently fails: Electron
   apps and elevated terminals.
3. **Accents** — non-native English speakers are the largest underserved group in the
   category, and nobody publishes accent-stratified numbers. We will.

## Documents

| | |
|---|---|
| [`docs/01-strategy.md`](docs/01-strategy.md) | Market, competitors, the wedge, business model, risks |
| [`docs/02-architecture.md`](docs/02-architecture.md) | The full pipeline: capture → VAD → ASR → NLP → injection |
| [`docs/03-roadmap.md`](docs/03-roadmap.md) | Phased plan with kill/continue checkpoints |
| [`docs/04-curriculum.md`](docs/04-curriculum.md) | What to study, sequenced against the phases |
| [`docs/05-evaluation.md`](docs/05-evaluation.md) | Metrics, datasets, and the benchmark harness |
| [`docs/decisions/`](docs/decisions/) | Architecture decision records |

## The pipeline, in one paragraph

A low-level keyboard hook starts a session; a ring buffer that has been retaining the last
1.5 seconds of audio the whole time means the first word is never clipped. Silero VAD finds
the endpoint. A streaming transducer (Parakeet TDT) emits a draft while you speak, then a
second pass over the complete utterance — with the full bias vocabulary harvested from your
active window, clipboard, and open repository — produces the final transcript. WFST inverse
text normalization turns "twenty twenty six" into "2026". Low-confidence spans get
phonetically-near candidates and a constrained LLM pass picks between them, with an
edit-distance guard so it can never quietly rewrite what you said. The text is then injected
via a verified cascade — UI Automation, then clipboard paste, then synthetic Unicode
keystrokes — with the winning strategy remembered per application.

Target: **p95 under 700 ms**, hotkey release to text on screen.

## Hardware target

Designed against 6 GB VRAM (RTX 4050 Laptop) with a first-class CPU-only path, because
that's roughly the low end of what a target user has.

## License

Planned: Apache-2.0 for the evaluation harness and benchmark, AGPL for the engine. Not yet
applied — see `docs/01-strategy.md` §5.
