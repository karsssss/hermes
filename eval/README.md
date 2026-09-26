# The evaluation harness

Build this first. Not second. It is the only thing that distinguishes engineering from
guessing, and in this domain intuition is actively misleading.

A harness, not a framework: one Python process, flat files in git, zero runtime
dependencies. Everything a reviewer needs to judge a regression is visible in a text diff.

## Use it

```
uv sync --group dev

uv run hermes-eval validate eval/datasets/mock/manifest.jsonl
uv run hermes-eval run --manifest eval/datasets/mock/manifest.jsonl \
    --adapter perturb:seed=11 --label baseline --dataset mock
uv run hermes-eval compare eval/runs/<baseline> eval/runs/<candidate> --latency-budget-ms 700
```

`compare` exits non-zero on `regression`, `blocked_ewer_regression` or `blocked_latency`,
so it is directly usable as the CI gate.

## What it measures

| Metric | Definition |
|---|---|
| **F-WER** | The headline. WER on the literal text that would be injected — `raw` normalization: NFC + whitespace collapse only, case- and punctuation-sensitive, punctuation attached to its word. |
| WER | Plain WER under `basic` normalization (casefold, apostrophes deleted, other punctuation split to whitespace). For comparability with published numbers. Nothing more. |
| Casing error rate | F-WER minus the same WER computed with casefolding, in pp. |
| Punctuation F1 | Per mark class (`.` `,` `?` `!` `:` `;`), from a word-level alignment with trailing-mark labels. |
| ITN slot error rate | Misses of the curated `itn_slots` surface forms. **Spurious insertions are not measured** — the report says so explicitly. |
| E-WER | WER restricted to reference tokens inside `entities` spans, plus insertions strictly inside a span. The guard against an aggregate win hiding rare-word damage. |
| Latency | p50/p95/p99, nearest-rank, adapter-reported where available. |

Aggregates are corpus-level (sum of edits over sum of reference tokens). Per-utterance
counts are kept for every metric, because pairing is only valid at utterance granularity.

## The decision rule

Written down in `bootstrap.py` before any experiment runs. A change is an **improvement**
only if all of:

1. the 95% CI on ΔF-WER excludes zero in the improving direction (paired utterance-level
   bootstrap, ≥2000 resamples, seed fixed and recorded), **and**
2. the point estimate is ≥ 0.3 pp absolute, **and**
3. E-WER does not regress beyond its own noise floor, **and**
4. latency p95 stays inside its absolute budget — a hard SLA gate, not a statistic.

Detectability at n=200 is 1–3 pp. The canary set is for CI gating; anything published uses
the full set.

## Adapters

`ASRAdapter` in `adapters.py` is the seam: `describe_env()` + `transcribe(record)`.

- `perturb:seed=N,...` — a deterministic synthetic fake-ASR. It reads the reference on
  purpose, to fabricate fixtures. **Not a backend.**
- `replay:<file.jsonl>` — scores transcripts captured elsewhere. This is how a closed
  competitor gets measured: drive the app by hand through VB-Cable at real-time speed,
  save `{id, text, latency_ms}` per line, and score it on identical code paths. Record
  what you did with `--manual-step`, and put the hand-gathered provenance in
  `<file>.jsonl.env.json`.

A real adapter must not read `record.reference`.

## Runs

Every run writes an immutable directory under `eval/runs/<run_id>/`:

```
run.json            provenance + aggregate metrics + subsets
summary.json        sorted-key aggregate
summary.csv         machine-readable aggregate + subset rows
summary.md          fixed-order human report, diffable
predictions.jsonl   what the adapter said, sorted by id
per_utterance.jsonl every per-metric count, sorted by id — the drill-down
```

The runner refuses to overwrite an existing run directory. `eval/runs/` is gitignored:
promote a run deliberately with `git add -f` when it belongs in the record.

## Not in v0

No web dashboard, no database, no parallel execution, no cross-OS support, no statistics
beyond the paired bootstrap. Also deliberately absent, and tracked in `docs/CURRENT.md`:

- **UPWR/UPSR** (partial-hypothesis stability) — needs a backend that emits partials.
- **The vendored, version-pinned Whisper `EnglishTextNormalizer`** for a secondary
  legacy-comparable score — needs a pinned third-party source, and it is a secondary
  number, not the headline.
- **Resource sampling** (`nvidia-smi`, `Get-Counter`) — belongs with the first real model.
