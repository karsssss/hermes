# Public Proxy Evaluation Set v1

A reproducible, permissively-licensed stand-in for the personal dictation set, built from
pinned public corpora. It exists because the personal 30-utterance recording set cannot be
collected right now, and **nothing else in Phase 0 can be believed without some scored
data** (`docs/CURRENT.md`).

It is a *proxy*. Read the next section before reading any number produced over it.

**Status: frozen, 2026-09-27.** Manifest sha256 `2b3a46ede2700f30479a218abcdf0f3d55d12c2610dfeb82575e0595c9d7053e`.
Nothing in `spec.json` or the pinned revisions changes again under this name — a different
composition is `public-proxy-v2`, a new directory with its own manifest, so that a number
quoted against v1 stays meaningful. ASR model benchmarking can start.

## What this set cannot measure

Three limits, stated first because they are load-bearing.

**1. F-WER is not computable here.** F-WER — the project's headline metric — is WER on the
literal text that would be injected, case- and punctuation-sensitive. **No public corpus in
scope ships a formatted reference.** EdAcc and LibriSpeech references are upper-case and
unpunctuated; Golos and RuLS are lower-case and unpunctuated. Scoring F-WER against those
would penalise a backend for producing *correct* casing and punctuation.

Every record therefore carries `metadata.reference_style` (`caps_nopunct` or
`lower_nopunct`), the harness slices on it, and **the number to read from a run over this
manifest is WER, not F-WER.** The `fwer` figure in a run over this set is an artefact of
reference formatting; it is not a measurement of the product.

**2. E-WER is not computable here.** E-WER needs annotated entity spans — code
identifiers, commands, domain terms. No public corpus annotates them, and inventing spans
would be fabricating the guard that is supposed to catch rare-word damage. `entities` is
empty on every record, so E-WER is absent rather than wrong.

**3. Dev-speak, code-switching and the real acoustic environment are absent entirely.** See
`COVERAGE.md`. The personal set remains irreplaceable; this set reduces how much rides on
it, it does not substitute for it.

What it *does* buy: a real WER number on real accented speech, a real Russian number, a
controlled clean-vs-noisy and clean-vs-reverberant delta, and a licence story clean enough
to publish.

## Build it

```
uv sync --group data
uv run hermes-eval build-dataset eval/datasets/public-proxy-v1/spec.json \
    --out eval/datasets/public-proxy-v1
uv run hermes-eval validate eval/datasets/public-proxy-v1/manifest.jsonl
```

First build takes 10-20 minutes and downloads about 56 MB. Re-runs are nearly free: split
metadata and every fetched audio asset are cached under `.cache/` (gitignored). The
datasets-server rate-limits anonymous callers on a short-window bucket; the fetcher backs
off for up to five minutes and the cache means an interrupted build resumes rather than
restarts. Setting `HF_TOKEN` raises the bucket but is never required — every source is
ungated.

`manifest.jsonl` and `build.json` are checked in. **The audio is not**, and must not be:
EdAcc and Golos both carry ShareAlike, so redistributed derived audio would be Adapted
Material. `LICENSES.md` has the details.

## How the sample is drawn

Deterministic, given the spec, the seed and the pinned revisions:

1. Read the split's non-audio columns once, straight from the pinned parquet with column
   pruning — kilobytes, no rate limit, and the revision is part of the read rather than
   inferred afterwards. One datasets-server request per source then confirms that parquet
   row *N* and server row *N* are the same utterance; if they were not, every `row_id` in
   the manifest would point at the wrong audio.
2. Drop rows failing the text filters (token-count bounds).
3. Sort by source row index — never trust server page order — then take a seeded
   permutation of that list.
4. Walk the permutation, accepting a row unless it exceeds its **speaker quota** or its
   **stratum quota**, and unless its audio falls outside the duration bounds. Duration is
   only knowable after download for most sources, so that one is a post-fetch rejection.

The seed for each stratum is `"<seed>|<spec name>|<subset>|<source>|<revision>"`, so
re-pinning a revision necessarily redraws that stratum rather than silently mixing old and
new audio.

This is checked, not asserted: deleting `manifest.jsonl` and `audio/` and rebuilding
produces a **byte-identical manifest and byte-identical WAVs**. Retrieval timestamps are
cached alongside the bytes rather than regenerated, precisely so that this stays testable.

### Speaker disjointness

| Source | Speaker IDs | Eval-vs-train separation |
|---|---|---|
| EdAcc | `speaker` (e.g. `EDACC-C36-A`) | EdAcc is an evaluation-only corpus. Only the **test** split is sampled; **validation is reserved** and must stay reserved. Max 3 utterances per speaker. |
| LibriSpeech test-clean | `speaker_id` | Disjoint from every train split by construction. Max **1** utterance per speaker. |
| RuLS | derived from `audio_filepath` (LibriVox reader) | **Verified from `CHAPTERS_READERS.TXT`: train 5 readers, dev 1, test 7, zero overlap.** Max 3 per reader. |
| Golos | **none published** | Anonymous Toloka workers; the corpus publishes no speaker identity, so disjointness is unverifiable. Recorded as `speaker_id: null` rather than assumed. |

**No speaker in this set may ever enter a training pool.** The whole point of the quota
columns above is that the claim stays checkable from the manifest alone — every record
carries `provenance.speaker_id`.

## Subsets

| `metadata.subset` | Source | n | What it is |
|---|---|---|---|
| `accented_en` | EdAcc test, L1 ≠ English | 50 | Conversational English from non-native speakers, stratified by L1. The W2 anchor. |
| `general_en` | LibriSpeech test-clean | 30 | Read English, one utterance per speaker. The comparability anchor — saturated, and useful only as a sanity check. |
| `ru_clean` | RuLS test | 20 | Read Russian from LibriVox audiobooks. |
| `ru_command` | Golos crowd test | 10 | Russian voice-assistant commands, close-talk. |
| `ru_farfield` | Golos farfield test | 10 | The same register at 1 m / 3 m / 5 m on SberPortal hardware. Genuine far-field. |
| `robust_noise` | derived | 20 | The same utterances as `robust_reverb`, plus MUSAN point-source noise at 10 dB SNR. |
| `robust_reverb` | derived | 20 | The same utterances, convolved with an OpenSLR 28 simulated small/medium-room RIR. |

160 records; 120 are clean and 40 are perturbed copies of 20 of them.

**Read the corpus aggregate on the clean records.** The perturbed records duplicate speech
already present, so an aggregate over all 160 double-counts those 20 utterances. The
harness emits per-`noise` and per-`subset` subset metrics, so the clean aggregate and the
paired robustness delta are both directly available in `summary.md`.

`robust_noise` and `robust_reverb` deliberately draw the **same** 20 source utterances
(`pair_key` in the spec), so the two conditions are comparable to each other and to their
own clean originals rather than to two unrelated samples.

## The two transforms

Both are applied to the 16 kHz mono WAV the harness would otherwise score, and both record
exactly what was done in `provenance.transform`.

- **Noise**: a deterministically chosen `noise-free-sound-*.wav` from OpenSLR 28's
  `pointsource_noises/` — these are MUSAN's free-sound clips — tiled or cropped to length
  and mixed at **10 dB SNR** computed on full-signal RMS. Full-signal rather than
  voice-active RMS is the simpler and more reproducible definition; it makes the effective
  SNR during speech slightly *higher* than the label on utterances with leading silence.
- **Reverb**: convolution with a simulated small- or medium-room RIR, **trimmed to its
  direct-path peak** so the reverberant copy stays time-aligned with the clean one. Without
  that trim, the propagation delay baked into a simulated RIR shifts every word and a
  paired comparison measures misalignment instead of reverberation. Output RMS is matched
  back to the input.

## Audio conventions

16 kHz mono 16-bit PCM WAV, matching what the capture path will produce. EdAcc arrives at
32 kHz, so it is low-passed with a windowed-sinc filter below the new Nyquist before
resampling; naive decimation would fold energy above 8 kHz back into the speech band and
the benchmark would be measuring its own aliasing. `tests/test_datasets.py` pins that
behaviour with a 12 kHz tone that must not survive.

## Files

```
spec.json        the sampling plan — subsets, quotas, filters, seed
manifest.jsonl   the set itself, one record per line (checked in)
build.json       what the build actually did: counts, rejections, revisions, warnings
LICENSES.md      per-corpus terms, what was rejected and why
COVERAGE.md      the coverage table and the gaps
audio/           gitignored, regenerated by build-dataset
.cache/          gitignored, makes re-runs cheap
```
