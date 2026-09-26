# 05 — Evaluation

Status: draft, 2026-09-24.

**Build this first.** Not second. The eval harness is the only thing that distinguishes
engineering from guessing, and in this domain intuition is actively misleading: denoisers
that sound better raise WER, LLM correction passes that read beautifully change meaning,
and "this feels faster" is uncorrelated with p95.

It is also, per `PRODUCT.md` §3 (W2), a marketing asset. The harness ships publicly.

## 1. Metrics

Plain WER is necessary and badly insufficient for this product.

| Metric | Definition | Why |
|---|---|---|
| **WER** | Standard, on normalized text | Comparability with published numbers. Nothing more. |
| **F-WER** (formatted WER) | WER computed on the *final injected text*, post-ITN, punctuation- and case-sensitive | This is what the user actually sees. It's the number that matters. |
| **E-WER** (entity WER) | WER restricted to code identifiers, names, and domain terms | Measures W3 directly. A tool that gets `kubectl` wrong is useless to the target user regardless of its overall WER. |
| **Punctuation F1** | Per-mark precision/recall | Punctuation errors are disproportionately annoying |
| **Latency p50 / p95 / p99** | Per-stage and end-to-end, hotkey-release → text-on-screen | A feature (`ARCHITECTURE.md` §8) |
| **Keystrokes saved** | `len(final_text) - len(user_corrections)` | The closest proxy to real value. Track it in daily use. |
| **Correction rate** | Fraction of utterances the user edits within 10 s | The honest retention signal |
| **Catastrophic rate** | Fraction of utterances with hallucinated content, wrong-window injection, or clipboard loss | Must be ~0. Weight these far above WER. |

**Report WER with confidence intervals.** On a 200-utterance set, a 0.3% WER difference is
noise. Bootstrap the CI; don't celebrate deltas smaller than it.

## 2. Datasets

### Public (for comparability and for the published benchmark)

| Set | Purpose |
|---|---|
| **LibriSpeech** test-clean / test-other | The universal baseline. Saturated; useful only as a sanity check. |
| **EdAcc** (Edinburgh International Accents of English) | **The core of W2.** Conversational English across many L1 backgrounds. |
| **Common Voice**, stratified by accent metadata | Accent breadth, with the caveat that its labels are self-reported and noisy |
| **FLEURS** | Multilingual coverage, 100+ languages |
| **AMI** / **CHiME** | Noise and far-field robustness |
| **TED-LIUM**, **Earnings-22** | Long-form and domain vocabulary |
| **SEAME** or equivalent | Code-switching reference point |

### Proprietary (the differentiated data — this is an asset, treat it as one)

1. **Your voice, your apps, your workflow.** 200+ utterances recorded during real use, with
   corrected ground truth. Start collecting in Phase 0; it grows forever.
2. **The dev-speak set.** Deliberately recorded: code identifiers, CLI commands, file paths,
   library names, git operations. `git rebase --interactive HEAD~3`, `kubectl get pods -n
   kube-system`, `tokio::sync::mpsc::unbounded_channel`. Nothing public covers this and it
   is exactly where competitors fail.
3. **The code-switching set.** Sentences that mix English with Ukrainian/Russian/other L1
   mid-utterance — names, places, technical terms. Recruit a handful of non-native-English
   developer friends; 20 utterances each is enough to be informative.
4. **The adversarial set.** Homophone pairs in context, numbers and dates, proper nouns,
   fast speech, background noise, low mic gain, speaking too close to the mic.

**Ground truth discipline:** transcribe twice, independently, reconcile differences. A
benchmark with sloppy references produces confident wrong conclusions, and if you publish
it, it produces public confident wrong conclusions.

## 3. Harness design

```
eval/
├── datasets/           # manifests only; audio via DVC or a content-addressed store
├── engines/            # adapters: hermes, whisper.cpp, wispr, superwhisper, win-native, ...
├── metrics/            # wer, fwer, ewer, punctuation_f1, latency, bootstrap CIs
├── runs/               # timestamped, immutable results — never overwrite
└── report/             # markdown + charts, diffable in PRs
```

Requirements:

- **One command** runs the full suite and emits a diffable report. If it takes more than
  one command, you will stop running it.
- **Every run is immutable and recorded** with model versions, config hash, and git SHA.
- **Competitor engines are first-class adapters.** Benchmarking Wispr, Superwhisper, and
  Windows native on the same audio is the whole point of the public benchmark; build the
  plumbing for it early even if the adapters are semi-manual at first.
- **Per-utterance drill-down.** Aggregate WER tells you nothing actionable. You need to sort
  by error and look at the worst 20 — that's where the actual bugs are.
- **CI gate:** F-WER regression or p95 latency regression fails the build.

## 4. The judgment calls this harness will force

Write down the decision rule *before* running the experiment, so you can't rationalize
afterwards:

| Question | Decision rule |
|---|---|
| Ship the denoiser? | Only if F-WER improves on the noisy subset **and** doesn't regress on clean |
| Ship the LLM correction pass? | Only if F-WER improves **and** catastrophic rate stays ~0 |
| Parakeet or Whisper as default? | Whichever wins on F-WER at equal latency budget, evaluated per-language |
| Enable aggressive biasing? | Only if E-WER improves **without** raising the false-insertion rate on a control set of utterances containing no bias terms |
| Is W2 real? | Publish only if the accent-stratified gap between Hermes and cloud competitors is small or favorable |

That last row matters: the benchmark must be able to embarrass you. A benchmark you'd only
publish if it flatters you isn't a benchmark, it's an ad, and the community will tell the
difference immediately.

## 5. What to measure in production (opt-in, content-free)

Never transcripts. Only:

- Per-stage latency histograms
- Model tier used per utterance
- Injection strategy used, and fallback frequency per process name — this is how the
  per-app compatibility table improves for everyone
- Correction rate (edit within 10 s), as a scalar, with no text
- Crash and error codes
