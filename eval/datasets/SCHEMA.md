# Evaluation record schema

One JSON object per line. `src/hermes_eval/manifest.py` is the enforcer; this file is the
prose version. Validation is strict: **unknown keys are rejected**, because a mistyped
field silently dropping an utterance out of a subset metric is the failure we cannot see.

```json
{
  "id": "personal-0001",
  "audio": "audio/personal-0001.wav",
  "duration_s": 3.4,
  "reference": "Run git rebase --interactive HEAD~3 and squash the last two commits.",
  "metadata": {
    "language": "en",
    "accent": "uk-L1",
    "domain": "git",
    "category": "dev_speak",
    "code_switch": [],
    "speaker": "primary",
    "noise": "quiet",
    "source": "real-use",
    "app": "WindowsTerminal.exe"
  },
  "entities": ["git rebase --interactive", "HEAD~3"],
  "itn_slots": [{"text": "HEAD~3", "kind": "identifier"}],
  "ground_truth": {"pass1": "...", "pass2": "...", "reconciled": true},
  "notes": ""
}
```

## Fields

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Unique within the manifest. Stable forever — it is the join key for paired comparison. |
| `audio` | yes | Path **relative to the manifest file**. Absolute paths are rejected so a manifest stays portable. |
| `reference` | yes | **The formatted reference**: exactly the text that should have been injected, with real casing, punctuation and ITN applied. F-WER scores against it as-is; plain WER scores against its normalized form. There is only ever one reference. A record sampled from a public corpus usually cannot meet that bar — see `reference_style` below. |
| `duration_s` | no | Positive seconds. |
| `metadata` | yes | The slicing axes. See below. |
| `entities` | no | Surface strings that count as entities for E-WER: code identifiers, commands, names, domain terms. Matched as contiguous token subsequences of the reference under `basic` normalization. An entity that does not occur in its own reference is reported as a manifest bug, not silently skipped. |
| `itn_slots` | no | `{text, kind}` — the exact formatted surface form expected in the output, for the ITN slot error rate. |
| `ground_truth` | no | The transcribe-twice audit trail. If present, `reconciled` **must** be `true`. |
| `provenance` | no | Where a record came from, for records derived from a public corpus. Optional, but validated strictly once present. See below. |
| `notes` | no | Free text for a human. |

## Metadata

Required on every record: `language`, `accent`, `domain`, `category`.
Optional: `code_switch`, `speaker`, `noise`, `source`, `app`, `subset`, `reference_style`.

- **`language`** — primary language tag, e.g. `en`.
- **`code_switch`** — other languages present mid-utterance, e.g. `["uk"]`. Drives the
  code-switching subset, which is the one nothing public covers.
- **`accent`** — a hand-assigned stratum label, e.g. `uk-L1`, `en-GB`. Never inferred
  automatically (R6: strata come from a curated, checked-in map).
- **`domain`** — the project or subject vocabulary: `git`, `kubernetes`, `rust`, `general`.
- **`category`** — one of `prose`, `dev_speak`, `code_switch`, `adversarial`, `itn`,
  `command`.
- **`noise`** — recording condition: `quiet`, `cafe`, `fan`, `far-field`.
- **`source`** — `real-use`, `scripted`, `synthetic`. Real-use utterances are the asset;
  scripted ones fill coverage gaps.
- **`app`** — the process that was focused, when the utterance came from real use. This is
  what eventually makes the per-app compatibility table real.
- **`subset`** — a curated stratum label, e.g. `accented_en`, `ru_farfield`, `robust_noise`.
  It is the axis a designed evaluation set is *read* on, and it is hand-assigned by the set's
  spec, never inferred.
- **`reference_style`** — how much formatting the reference actually carries: `formatted`,
  `caps_nopunct`, or `lower_nopunct`. Default when absent is `formatted`, which is what a
  hand-written reference is.

  This exists because **public ASR corpora almost never ship a formatted reference**: EdAcc
  and LibriSpeech are upper-case and unpunctuated, Golos and RuLS are lower-case and
  unpunctuated. F-WER against such a reference punishes a backend for producing *correct*
  casing and punctuation, so the fact has to travel with the record and be sliceable. On a
  manifest whose records are not `formatted`, **the number to read is WER, not F-WER.**

## Provenance

Optional, and only meaningful for records sampled from a public corpus. Once present it is
validated strictly — a half-filled provenance block is worse than none, because it looks
like an audit trail without being one.

```json
{
  "source": "hf:edinburghcstr/edacc",
  "revision": "d9ae7bd344f0562b766ec93ee5ce8f2f9568ce66",
  "config": "default",
  "split": "test",
  "row_id": "5000:EDACC-C36-A",
  "speaker_id": "EDACC-C36-A",
  "license": "CC-BY-SA-4.0",
  "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
  "source_url": "https://datasets-server.huggingface.co/cached-assets/...",
  "source_audio_sha256": "...",
  "source_sample_rate_hz": 32000,
  "audio_sha256": "...",
  "sampling_seed": 20260926,
  "derived_from": null,
  "transform": null,
  "retrieved_utc": "2026-09-26T20:00:00Z"
}
```

Required once the key is present: `source`, `revision`, `split`, `row_id`, `license`,
`retrieved_utc`. Everything else is optional.

- **`revision`** — a full commit sha, never a branch name. A branch is not a pin.
- **`row_id`** — identity of the row within its split, including the corpus' own id where
  one exists. This is what makes a sampling decision re-checkable by hand.
- **`speaker_id`** — `null` is a legitimate and meaningful value: Golos publishes no speaker
  identity, so a speaker-disjointness claim about it would be fiction. Recording the null
  keeps that visible.
- **`audio_sha256`** — hash of the 16 kHz WAV that was actually scored. Together with
  `source_audio_sha256` it is what lets a third party confirm they rebuilt the same set.
- **`derived_from` / `transform`** — set on augmented records: the id of the clean record
  this one was made from, and exactly what was done to it (`noise:snr_db=10,clip=...`).

## What is deliberately absent

No per-utterance transcript from a competitor, no confidence scores, no partial
hypotheses. Those belong to a run, not to the dataset — a dataset that carries results
from one system stops being a neutral reference.
