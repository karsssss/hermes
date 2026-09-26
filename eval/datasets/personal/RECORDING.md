# The personal set — recording protocol

This is the differentiated data. It is the only dataset in the project that no competitor
can obtain, and it is what every Phase 0 measurement is scored against. Treat it as an
asset: back it up, version the manifest, never let a sloppy reference into it.

Target for Phase 0 Task 1: **30 utterances**, recorded during real use. It grows forever;
`BENCHMARKS.md` §2 wants 200+ before anything is published.

## Capture

1. Record at **16 kHz mono, 16-bit PCM WAV**, the same rate the pipeline will use. Resampling
   later is a variable we do not want in the measurement.
2. One utterance per file, named `audio/personal-NNNN.wav`, zero-padded, never renumbered.
3. Speak as you actually dictate — do not slow down or over-articulate for the recording.
   A set of read speech measures read speech, and dictation is closer to spontaneous
   monologue (R6).
4. Note the focused app and the noise condition **at capture time**. Reconstructing them
   later is guesswork.

## Coverage for the first 30

Aim for roughly this split. It is deliberately weighted toward where we expect to lose.

| Count | `category` | What it is |
|---|---|---|
| 8 | `dev_speak` | Commands, identifiers, paths, library names — `git rebase --interactive HEAD~3`, `kubectl get pods -n kube-system`, `tokio::sync::mpsc::unbounded_channel` |
| 6 | `prose` | Normal sentences: messages, commit bodies, notes |
| 6 | `code_switch` | English mixed with Ukrainian/Russian mid-utterance — names, places, technical terms |
| 5 | `itn` | Numbers, dates, times, versions, percentages |
| 5 | `adversarial` | Homophones in context, proper nouns, fast speech, low mic gain, background noise |

## Ground truth — transcribe twice

**This is not optional.** Transcribe each utterance independently on two separate passes,
then reconcile the differences. Record both passes in `ground_truth`, and set
`reconciled: true` only once you have actually reconciled them. A benchmark with sloppy
references produces confident wrong conclusions — and if published, public ones.

Write the reference as **the text you would have wanted injected**: real casing, real
punctuation, ITN already applied (`2026`, not `twenty twenty six`). That formatted string
is the F-WER target; the harness derives the normalized form for plain WER itself.

## Entities and ITN slots

- Mark every code identifier, command, file path, library and proper noun in `entities`.
  E-WER is only as good as this annotation, and E-WER is the guard that stops an aggregate
  win from hiding rare-word damage.
- Mark expected formatted surface forms in `itn_slots` (`3:30`, `2026-10-02`, `12%`).
  Spurious ITN insertions are **not** measured in v0 — the rate reported is misses only.

## Before using it

```
hermes-eval validate eval/datasets/personal/manifest.jsonl
```

Start from `manifest.template.jsonl`. Keep the file sorted by id so it diffs cleanly.
