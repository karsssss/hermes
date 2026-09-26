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
| `reference` | yes | **The formatted reference**: exactly the text that should have been injected, with real casing, punctuation and ITN applied. F-WER scores against it as-is; plain WER scores against its normalized form. There is only ever one reference. |
| `duration_s` | no | Positive seconds. |
| `metadata` | yes | The slicing axes. See below. |
| `entities` | no | Surface strings that count as entities for E-WER: code identifiers, commands, names, domain terms. Matched as contiguous token subsequences of the reference under `basic` normalization. An entity that does not occur in its own reference is reported as a manifest bug, not silently skipped. |
| `itn_slots` | no | `{text, kind}` — the exact formatted surface form expected in the output, for the ITN slot error rate. |
| `ground_truth` | no | The transcribe-twice audit trail. If present, `reconciled` **must** be `true`. |
| `notes` | no | Free text for a human. |

## Metadata

Required on every record: `language`, `accent`, `domain`, `category`.
Optional: `code_switch`, `speaker`, `noise`, `source`, `app`.

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

## What is deliberately absent

No per-utterance transcript from a competitor, no confidence scores, no partial
hypotheses. Those belong to a run, not to the dataset — a dataset that carries results
from one system stops being a neutral reference.
