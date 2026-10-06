# T2B — Parakeet confidence and N-best: the architecture gate

Status: **complete**, 2026-10-06. Phase 0, Task 2b. **Verdict: A — KEEP CURRENT CONTRACT**
(§8).

**The question.** Can the ONNX / sherpa-onnx / ORT path supply useful token confidences and
an N-best list for Parakeet TDT 0.6B v3 int8 **without Hermes owning a large decoder**?
That is SYNTHESIS §5.1's risk, D-0011's Phase 0 exit criterion, and open question #1.

**Scope.** One model (Parakeet TDT 0.6B v3, sherpa-onnx int8 export, combined sha256
`d0a44f3c…`), the frozen Public Proxy Evaluation Set v1 (n=160, manifest sha256
`2b3a46ed…d7053e`), CPU EP, 4 threads. No models, datasets or fine-tuning added.
**WER, not F-WER**: the proxy set has no formatted reference (its README).

**Run.** `eval/runs/20261006T033722Z-t2b-parakeet-confidence-27dc`. Collected in two
sittings: rows 1–91 from 2026-10-06T03:37Z (git `013217b`, dirty — the instrument was
uncommitted), then a resume of rows 92–160 from 04:37Z (git `87ec846`, clean), recorded in
`run.json["resumes"]`. 160/160 rows, unique, in manifest order, none truncated. Manifest
and model hashes re-verified against `run.json` before and after the resume.

```
uv run --group asr python -m hermes_eval.t2b collect [--resume <run-dir>]   # ~45 min
uv run python -m hermes_eval.t2b analyze    <run-dir>   # analysis.json   (pre-registered)
uv run python -m hermes_eval.t2b supplement <run-dir>   # supplement.json (post-hoc, §1)
```

---

## 1. Method

**Three arms per utterance.** (1) sherpa-onnx 1.13.8 `greedy_search`, everything its
public API returns; (2) sherpa `modified_beam_search`, `max_active_paths=4`; (3) **the probe**
(`src/hermes_eval/tdt_probe.py`): a line-for-line Python/ORT port of sherpa's TDT greedy and
modified-beam decoders over the same three ONNX sessions, which records what sherpa computes
and throws away — the full per-step token and duration distributions, top-5 alternatives
per emitted token, and every surviving beam hypothesis with its score (K=4 and K=8).

**Unit and labels.** The scored unit is the `basic`-normalized hypothesis word — the WER
unit. A word's confidence is an aggregate (min unless stated) over its non-punctuation
tokens. A unit is correct iff the WER alignment marks it EQUAL. Substitutions and insertions
are what a word confidence can flag; **deletions have no hypothesis word, so no word-level
confidence can detect them** — they are counted, not dropped (§2.4).

**Comparisons are paired where they can be.** Every probe signal is scored on the *same*
probe hypothesis, and the delta is against `maxprob_min` — the emitted-token probability,
i.e. exactly what sherpa already exposes. sherpa's native signal on sherpa's own hypothesis
is scored separately (different units, so not paired). Bit-parity between the two paths is
unattainable (§4), and the design is built around that.

**Statistics.** AUROC (correct vs incorrect units), average precision for error detection
(chance = error rate), recall@10% / @20% (share of errors caught by highlighting the lowest
10% / 20% of words), ECE for the one signal that claims to be a probability. 95% CIs by
**utterance-level** paired bootstrap, 2000 resamples, seed 20260926 — units within an
utterance are correlated, so the word is never the resampling unit.

**Pre-registered vs post-hoc.** `analyze` and every formula in it were fixed before the run
completed and were not changed after the full data was seen; a refactor of its unit
construction was verified to reproduce `analysis.json` exactly. `supplement` was written
after: AP intervals, sherpa-native calibration, N-best headroom by rank, per-beam cost,
the divergence locus, and the timing split. It reuses `analyze`'s units and redefines
nothing. Where a number comes from `supplement` it is marked †.

**Slices.** overall (160), accented_en (50, EdAcc), general_en (30, LibriSpeech
test-clean), russian (40: RuLS 20 + Golos crowd 10 + farfield 10), noise (20), reverb (20).
Noise and reverb are variants of the same 20 clean utterances, so they are not independent
of each other.

---

## 2. Confidence

### 2.1 Word level, overall (n=160, 2454 units, 197 errors, chance AP 0.080)

| signal (word = min over tokens) | reachable via | AUROC [95% CI] | Δ AUROC vs `maxprob_min` [CI] | AP [CI†] | R@10 | R@20 |
|---|---|---:|---:|---:|---:|---:|
| **sherpa native `ys_log_probs`, its own hyp** | **sherpa API** | **0.884 [0.855, 0.908]** | (unpaired) | **0.512 [0.430, 0.589]** | 0.558 | 0.743 |
| `maxprob_min` (same quantity, probe hyp) | sherpa API | 0.879 [0.850, 0.903] | — | 0.506 [0.421, 0.584] | 0.558 | 0.721 |
| `maxprob_prod` (word P = Π p) | sherpa API | 0.879 [0.851, 0.904] | +0.001 [−0.002, +0.003] | 0.502 [0.420, 0.582] | 0.553 | 0.731 |
| `maxprob_mean` | sherpa API | 0.879 [0.849, 0.903] | −0.000 [−0.006, +0.004] | 0.485 | 0.528 | 0.731 |
| `gibbs_min` (Shannon entropy) | full distribution | **0.883 [0.855, 0.907]** | **+0.004 [+0.001, +0.008]** | **0.523 [0.437, 0.599]** | 0.558 | 0.756 |
| `margin_min` (top-1 − top-2) | full distribution | 0.866 [0.837, 0.891] | −0.013 [−0.018, −0.009] | 0.364 [0.296, 0.445] | 0.502 | 0.716 |
| `tsallis_min` α=1/3 (R8 §D's best) | full distribution | 0.841 [0.806, 0.871] | **−0.038 [−0.063, −0.016]** | 0.433 [0.335, 0.525] | 0.472 | 0.645 |
| `renyi_min` α=1/3 | full distribution | 0.841 [0.806, 0.871] | −0.038 [−0.063, −0.016] | 0.433 [0.335, 0.525] | 0.472 | 0.645 |
| `tsallis_mean` (linear-normalized) | full distribution | 0.829 [0.790, 0.862] | −0.050 [−0.080, −0.024] | 0.419 | 0.467 | 0.665 |
| `tsallis_blank_min` (blank-inclusive) | full distribution | 0.834 [0.797, 0.863] | −0.045 [−0.070, −0.023] | 0.382 | 0.421 | 0.645 |
| `nonblank_min` (1 − P(blank)) | full distribution | 0.799 [0.762, 0.832] | −0.080 [−0.110, −0.053] | 0.237 | 0.355 | 0.579 |
| `dur_maxprob_min` (TDT duration head) | full distribution | 0.691 [0.650, 0.728] | −0.188 [−0.230, −0.150] | 0.140 | 0.198 | 0.386 |
| `dur_gibbs_min` | full distribution | 0.679 [0.638, 0.719] | −0.200 [−0.243, −0.159] | 0.136 | 0.213 | 0.381 |

Rényi-1/3 and Tsallis-1/3 are identical under min aggregation by construction — both are
monotone in Σp^α — so they are one result, not two.

**Reading.**

- **The emitted-token probability sherpa already returns is as good as anything the full
  distribution offers, to within 0.005 AUROC.** sherpa native 0.884; best full-distribution
  signal (Gibbs) 0.883.
- **Gibbs entropy beats `maxprob_min` by +0.004 AUROC, CI [+0.001, +0.008]** — clear of
  zero, so it is not noise, but it is 0.4 AUROC points, its AP interval overlaps
  `maxprob_min`'s almost entirely, and recall@10 is identical (0.558). Statistically
  resolved, **practically negligible**. It does not by itself justify anything.
- **R8 §D's recommended configuration — Tsallis α=1/3 — is worse than plain max-prob on
  this model, CI clear of zero** (−0.038 overall; −0.070 [−0.121, −0.017] on reverb). R8's
  "entropy beats max-prob by 2–4×" came from LibriSpeech on NeMo models with NeMo's
  exponential normalization; it does not transfer to Parakeet TDT v3 int8 on this set.
  Top-1/top-2 margin is also worse (−0.013, CI clear), and so is everything derived from the
  blank or duration heads.
- **The duration head carries little word-error information** (AUROC 0.68–0.69). TDT's
  extra output is not a confidence signal here.

### 2.2 By slice — AUROC [95% CI], and error counts

| slice | utts | units | errors | sherpa native | `maxprob_min` | `gibbs_min` (Δ) | `tsallis_min` (Δ) | `margin_min` (Δ) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| accented_en | 50 | 852 | 94 | 0.863 [0.815, 0.910] | 0.856 [0.805, 0.903] | 0.856 (+0.000 [−0.006, +0.006]) | 0.825 (−0.031 [−0.069, +0.002]) | 0.845 (−0.011 [−0.018, −0.004]) |
| general_en ⚠ | 30 | 610 | **11** | 0.829 [0.584, 0.977] | 0.820 [0.570, 0.973] | 0.824 (+0.004 [−0.003, +0.010]) | 0.809 (−0.011 [−0.070, +0.041]) | 0.816 (−0.004 [−0.019, +0.010]) |
| russian | 40 | 339 | 31 | 0.894 [0.832, 0.948] | 0.893 [0.834, 0.946] | 0.905 (+0.012 [−0.002, +0.026]) | 0.869 (−0.024 [−0.069, +0.018]) | 0.867 (−0.026 [−0.041, −0.013]) |
| noise | 20 | 318 | 31 | 0.881 [0.812, 0.938] | 0.869 [0.805, 0.921] | 0.877 (+0.008 [−0.002, +0.019]) | 0.843 (−0.025 [−0.083, +0.032]) | 0.849 (−0.019 [−0.036, −0.005]) |
| reverb | 20 | 335 | 30 | 0.859 [0.781, 0.928] | 0.862 [0.789, 0.930] | 0.866 (+0.004 [−0.004, +0.011]) | 0.792 (−0.070 [−0.121, −0.017]) | 0.852 (−0.010 [−0.020, +0.004]) |

AP† for sherpa native by slice: accented 0.546 [0.423, 0.667]; general_en 0.347
[0.061, 0.636]; russian 0.553 [0.372, 0.708]; noise 0.542 [0.380, 0.671]; reverb 0.468
[0.242, 0.670]. Recall@10 for sherpa native: accented 0.475, general_en 0.636, russian
0.438, noise 0.515, reverb 0.484.

**Thin slices — read these as flags, not findings.**

- **general_en is uninformative.** 11 errors in 610 units; AUROC CIs span ~0.40
  ([0.57, 0.98]); AP CIs span 0.06–0.69. Clean read English is where Parakeet barely errs
  (WER 1.8%), so there is almost nothing to detect. Nothing about confidence on general
  English may be quoted from this run.
- **russian, noise and reverb (30–31 errors each) have AUROC CIs ~0.13–0.15 wide.** Enough
  to say the signal works on each (every lower bound ≥ 0.78) and that Tsallis is worse on
  reverb; not enough to rank the near-ties (sherpa native, `maxprob_*`, Gibbs) within any
  of them. Noise and reverb share their source utterances.
- **accented_en (94 errors) is the only slice that is reasonably measured**, and it is the
  W2 core. There, every top signal ties: sherpa native 0.863, `maxprob_min` 0.856, Gibbs
  0.856 (Δ +0.000).

The ranking is the same in every slice: the max-prob family and Gibbs at the top, within
noise of each other; margin and Tsallis/Rényi below; blank- and duration-derived signals
last.

### 2.3 Calibration

The product of emitted-token probabilities, read as P(word correct):

| slice | ECE (probe hyp) | ECE (sherpa native†) | mean P / accuracy (sherpa native†) |
|---|---:|---:|---:|
| overall | 0.028 | 0.022 | 0.918 / 0.916 |
| accented_en | 0.044 | 0.037 | 0.901 / 0.885 |
| general_en ⚠ | 0.014 | 0.014 | 0.973 / 0.982 |
| russian | 0.027 | 0.032 | 0.889 / 0.905 |
| noise | 0.046 | 0.034 | 0.900 / 0.897 |
| reverb | 0.030 | 0.028 | 0.909 / 0.908 |

Near-calibrated in aggregate, and **mildly overconfident on accented English** (P 0.901 vs
accuracy 0.885). Two cautions keep this from meaning more than it says: ECE over a ~92%-accurate
population is dominated by the top bin, so aggregate calibration says little about the
low-confidence tail that matters for flagging; and none of this is measured on the user's
voice. **It supports highlighting (relative ranking). It does not license auto-correction**
— D-0009 stands.

### 2.4 What word confidence cannot see

136 deletions overall (76 on accented_en) have no hypothesis word to score. Against 197
scorable errors, **~41% of all word errors are invisible to any word-level confidence**,
whichever signal is chosen. Highlighting can only ever flag what was written.

### 2.5 Sequence / utterance level

Point estimates from `analyze` (no CI was pre-registered for these): Spearman ρ of each
score against utterance WER, and AUROC for separating error-free utterances from those
with any error.

| score | reachable via | ρ overall | AUROC overall | accented ρ | russian ρ | noise ρ | reverb ρ |
|---|---|---:|---:|---:|---:|---:|---:|
| mean emitted-token log-prob | **sherpa API** | **0.678** | 0.789 | **0.659** | 0.568 | **0.892** | **0.718** |
| min word Tsallis | full distribution | 0.616 | **0.802** | 0.529 | **0.676** | 0.637 | 0.636 |
| beam-4 score per frame | owned beam | 0.626 | 0.767 | 0.489 | 0.575 | 0.748 | 0.683 |
| beam-4 top-1 − top-2 score gap | owned beam | 0.127 | 0.599 | 0.152 | −0.027 | 0.024 | 0.333 |

general_en (9 utterances with any error) shows no signal for any score (|ρ| ≤ 0.17) and is
excluded from reading. **The best sequence-level score is the mean emitted-token log-prob,
which sherpa already exposes.** The beam score per frame is weaker, and the top-1/top-2 gap
— the obvious "how sure is the decoder" number from an N-best list — carries almost
nothing (ρ 0.13), because the beam's internal list is dominated by near-duplicate
alignments (§3).

---

## 3. N-best

The probe's beam is sherpa's TDT `modified_beam_search`, faithfully ported, with every
surviving hypothesis kept instead of only the best. It inherits sherpa's simplifications:
argmax duration (no duration branching), **no merging of identical prefixes**, and **scores
compared across hypotheses sitting at different frames**.

### 3.1 Overall (n=160; 101 utterances with a greedy error)

| | greedy | beam-4 | beam-8 |
|---|---:|---:|---:|
| WER@1 (top-ranked hypothesis) | 12.98 | 12.83 | 13.99 |
| Δ WER@1 vs greedy, pp [CI] | — | −0.16 [−0.89, +0.53] | +1.01 [−0.19, +2.48] |
| oracle WER@N† | — | 10.99 | 10.64 |
| Δ oracle vs greedy, pp [CI]† | — | **−1.99 [−2.86, −1.27]** | **−2.34 [−3.27, −1.35]** |
| mean distinct texts / distinct after `basic` norm | — | 3.27 / 1.96 | 6.04 / 2.98 |
| utterances with a lexically distinct alternative | — | 60% | 76% |
| utts where a lower-ranked hyp beats the top-1† | — | 34 / 160 | 52 / 160 |
| utts where some hyp beats greedy† | — | 37 / 160 | 48 / 160 |
| utts where an error-free hyp exists but is not top-1† | — | 7 / 100 | 16 / 100 |
| decode-loop RTF (Python, on top of the encoder) | 0.057 | 0.203 | 0.334 |
| decode-loop ms p50 / p95† | 325 / 741 | 1297 / 2513 | 1821 / 4460 |

Oracle WER by rank† — beam-4: 12.83 → 11.93 → 11.27 → 10.99; beam-8: 13.99 → 12.83 →
12.24 → 12.01 → 11.58 → 11.27 → 10.76 → 10.64. Each extra rank buys roughly 0.3–0.9 pp of
*oracle* WER; beam-8's ranks 1–4 are worse than beam-4's ranks 1–4.

### 3.2 By slice — oracle Δ vs greedy, pp [CI]†

| slice | utts | greedy WER | beam-4 WER@1 (Δ [CI]) | beam-4 oracle Δ | beam-8 oracle Δ | error-free-but-not-top-1 (b4 / b8) |
|---|---:|---:|---:|---:|---:|---:|
| accented_en | 50 | 18.52 | 18.19 (−0.33 [−1.90, +0.90]) | **−3.05 [−5.05, −1.42]** | −2.51 [−4.88, −0.21] | 1 / 3 of 41 |
| general_en ⚠ | 30 | 1.81 | 1.65 (−0.16 [−1.04, +0.45]) | −0.66 [−1.57, 0.00] | −1.32 [−2.32, −0.50] | 3 / 6 of 9 |
| russian | 40 | 14.04 | 13.48 (−0.56 [−1.96, +0.60]) | −2.25 [−4.30, −0.66] | −3.37 [−5.75, −1.47] | 2 / 3 of 22 |
| noise | 20 | 17.54 | 19.01 (+1.46 [−1.30, +5.26]) | −1.75 [−3.65, +0.34] | −2.92 [−5.34, −1.11] | 1 / 3 of 14 |
| reverb | 20 | 12.28 | 11.40 (−0.88 [−2.36, 0.00]) | −1.46 [−3.63, 0.00] | −2.05 [−4.51, −0.26] | 0 / 1 of 14 |

Beam-8's WER@1 is worse than greedy on noise, CI clear of zero (+2.34 [+0.27, +5.83]).

**Reading.**

- **The N-best list carries real, measurable headroom: ~2 pp of WER overall (≈15%
  relative), ~3 pp on accented English, CIs clear of zero.** That headroom is what a
  selector-style correction pass would pick from.
- **The decoder's own scores cannot exploit it.** Beam-4's top-1 is greedy within noise;
  beam-8's top-1 is *worse* than greedy (overall +1.0 pp, noise CI clear). Consistent with
  static finding 4: comparing scores of hypotheses at different frames, without prefix
  merging, rewards the wrong paths as the beam widens. **Beam search does not improve the
  transcript on this decoder; it only enumerates alternatives.**
- **Better hypotheses are present but rarely perfect.** A lower-ranked hypothesis beats
  the top-1 in 34/160 utterances at K=4, but a fully error-free hypothesis sits below the
  top-1 in only 7 of 100 erroneous ones. The list fixes words, not utterances.
- **The list is padded with alignment duplicates.** At K=4 only 1.96 of 4 hypotheses are
  lexically distinct after normalization; at K=8, 2.98 of 8. Any consumer must deduplicate.
- **Cost.** In Python the beam-4 loop costs ~3.6× the greedy loop (RTF 0.20 vs 0.06; p50
  1.3 s vs 0.3 s per utterance on top of the encoder). Beam-8 costs ~5.9×. These ratios are
  within-row and survive the timing caveat (§5); the absolute numbers do not.

**N-best value, in one line:** real headroom for a selector, no value as a re-ranker, a
~4× Python decode-loop cost at K=4, and no Phase 1 consumer (D-0009 removed the correction
pass from Phase 1).

---

## 4. Parity and numerical stability

The probe and sherpa run the same algorithm on features that differ only in float32
reduction order (numpy vs Eigen).

| | overall | accented | general_en | russian | noise | reverb |
|---|---:|---:|---:|---:|---:|---:|
| greedy text differs (raw) | 33/160 | 16/50 | 2/30 | 7/40 | 5/20 | 3/20 |
| differs after `basic` normalization† | 26 | 14 | 1 | 4 | 5 | 2 |
| words differing, median / max† | 1 / 5 | 1 / 5 | 1 / 1 | 1 / 1 | 1 / 2 | 1 / 1 |
| WER sherpa / probe | 13.29 / 12.98 | 18.74 / 18.52 | 1.81 / 1.81 | 14.61 / 14.04 | 18.42 / 17.54 | 12.57 / 12.28 |
| Δ probe − sherpa, pp [CI]† | **−0.31 [−0.71, +0.11]** | −0.22 [−1.16, +0.84] | 0.00 | −0.56 [−1.36, 0.00] | −0.88 [−2.34, +0.60] | −0.29 [−1.03, 0.00] |

- **Greedy text identical on 127/160** (79%); beam-4 best identical on 112/160 (70%).
- **Emitted-token log-prob on identical texts** (3701 tokens): |Δ| median 0.00017, p95
  0.055, max 0.75 nats.
- **WER is unaffected.** The two paths differ by −0.31 pp, CI straddling zero. sherpa
  greedy scores 13.294% here — the Task 2a Parakeet figure (13.2943%) to every reported digit, so the
  sherpa arm reproduced across runs.
- **Confidence quality is unaffected.** sherpa native AUROC on its own hypothesis (0.884)
  and the same signal on the probe's (0.879) agree within their CIs.

**The divergence is the int8 numerical sensitivity already recorded, not an algorithmic
difference.†** For each of the 32 divergent utterances where a first divergence could be
located, the probe's smallest top-1/top-2 margin over the steps that decided the first
differing token:

| | median margin (nats) | share < 0.1 nats | share < 1.0 nats |
|---|---:|---:|---:|
| **at the first divergence** | **0.13** | **34%** | **88%** |
| all greedy steps | 6.07 | 0.8% | 8.4% |
| emitted-token steps | 6.78 | 0.7% | 7.7% |

Paths split almost exclusively at near-ties — 88% under 1 nat, against 8% of steps in
general — which is exactly where a 1e-7 feature perturbation can flip an argmax (static
finding 6). One divergence sits at a 7.2-nat margin: the token margin cannot see a flip in
the duration head, which also changes which frame is decoded next. This is not treated as
an architecture failure: it moves neither WER, nor confidence quality, nor N-best utility.

---

## 5. Timing caveat — **Task 2b latency figures are NOT decision-grade**

Rows 1–91 and 92–160 were collected in separate sittings, and the resume ran under tighter
memory (≈3.5 GB available). The subsets on each side of the boundary differ (rows 1–91 are
all accented and Russian, rows 92–160 mostly LibriSpeech), so raw RTF cannot be compared
directly. Two content-matched controls†:

1. **Ratio to Task 2a.** Each row's sherpa greedy decode time divided by Task 2a's latency
   for the *same utterance*, same model, same sherpa greedy decode.
2. **Noise and reverb split 10/10 across the boundary**, so the same kind of audio appears
   on both sides.

| | rows 1–91 | rows 92–160 |
|---|---:|---:|
| sherpa greedy ms / Task 2a ms, p50 | **0.99** | **0.79** |
| … p95 / max | 1.12 / 1.24 | 1.04 / 1.34 |
| … robust_noise only (10 / 10 rows) | 1.00 | 0.81 |
| … robust_reverb only (10 / 10 rows) | 1.00 | 0.81 |
| probe encode / sherpa greedy, p50 (within-row) | 1.05 | 1.07 |

**No sign of paging slowdown** — the resumed rows ran *faster*, about 20% faster than both
the first sitting and Task 2a, on the same content. But a ~20% content-matched shift
between sittings is itself evidence that system state moved the absolute timings, so
**every absolute latency or RTF figure in this task is non-decision-grade.** Ratios
measured *within a row* (probe encode vs sherpa decode: 1.05 → 1.07; beam vs greedy loop
cost) are stable across the boundary and may be used. No rerun for timing — production
performance is measured in the later characterization task.

---

## 6. What the stack exposes — four tiers

**1. The Parakeet ONNX export exposes everything.** The joiner returns raw logits over 8198
outputs every step: 8193 tokens (incl. blank, id 8192) + 5 TDT duration logits (0–4 frames).
The full token distribution and the duration distribution are in the artifact. Encoder
`[B,128,T]` → `[B,1024,T']`; the decoder is a 2-layer 640-d LSTM with explicit state in and
out. Nothing is hidden by the export.

**2. sherpa-onnx 1.13.8's public API (offline; Python and C)** exposes `text`, `tokens`,
`timestamps`, `durations`, and `ys_log_probs` — the log-softmax (token head, incl. blank)
of the **emitted token only**. It does **not** expose the full distribution, blank-step
probabilities, the duration distribution, any sequence score, or more than one hypothesis.
`modified_beam_search` computes K hypotheses and returns one. PR #2897 (full-vocabulary log
probs) was closed unmerged; 1.13.8 is the latest release. **Tier 2 already supplies the best
word confidence (§2.1) and the best sequence score (§2.5) measured here.**

**3. A small Hermes-owned Python TDT decode layer** (the probe's loop over three ORT
sessions: greedy ~35 lines, beam ~75) adds: **N-best with scores**, per-step full
distributions (entropy, margin, top-k alternatives per token), blank and duration
confidences, and beam sequence scores. It costs a decode-loop RTF of 0.06 (greedy) / 0.20
(beam-4) on top of the encoder, in Python, on the CPU EP. It is also where contextual
biasing has to live for Parakeet (D-0013), and Phase 1 decodes in the Python sidecar
(SYNTHESIS §4), so it is not a Rust task in Phase 1.

**4. Materially more complexity — none of it required by the contract:**
- a *correct* TDT beam (prefix merging, duration branching, frame-synchronous comparison,
  e.g. NeMo's MAES/ALSD) — the only route to a beam top-1 that beats greedy and a
  non-duplicated N-best;
- calibrated confidence — needs held-out per-domain calibration or a trained confidence
  head, and data from the user's own voice;
- bit-parity with sherpa — unattainable by porting (§4), and unnecessary;
- streaming partials with stable prefixes from an offline TDT model — chunked re-decoding,
  not measured here;
- the Rust port of the decode loop — Phase 3 (D-0003).

---

## 7. Corrections to earlier documents

- **`T2A-screening.md`**, "What this says about SYNTHESIS §5.1": *"on the installed 1.13.8
  wheel, it is there"* conflated `ys_log_probs` (emitted-token log-prob) with PR #2897's
  full-vocabulary log-probs. The latter was never merged. Corrected in place.
- **R8 §D / D-0009**: "entropy beats max-prob by 2–4×" does not hold for Parakeet TDT v3
  int8 on this set; Tsallis-1/3 is significantly *worse* than max-prob, and Gibbs ties it.
  D-0009's "entropy-based word confidence" is amended by D-0014.
- **SYNTHESIS §5.1** called the owned decode loop "a substantial Rust task" and the risk
  open. For Parakeet the loop is small and Python. §5.1 is marked resolved, and §9, §15 and
  C5 are updated; the DirectML vs WinML question is untouched.

---

## 8. Verdict

# A. KEEP CURRENT CONTRACT

`FinalTranscript` (SYNTHESIS §18, C5) requires `tokens[].confidence` and `nbest[]`
(hypothesis + score), and D-0011 makes a backend that cannot supply them invalid. Parakeet
TDT v3 over the ONNX export supplies both:

- **token confidence through sherpa's public API**, at a quality no full-distribution
  signal beats by more than 0.005 AUROC;
- **N-best through a small, already-written Python decode loop** in the sidecar, where
  decoding was always going to live — not through a large decoder, and not through Rust.

Nothing in C4 or C5 has to be removed or weakened. No architecture change is required:
§5.1's expensive fallback ("run the transducer decode loop ourselves") is measured as small.
What *does* change is below the contract — which signal fills `confidence`, and what
`nbest[].score` may be used for — recorded in D-0014.

### What Phase 1 can reliably support

| field | Phase 1 support | source | caveat |
|---|---|---|---|
| **`FinalTranscript.text`** | **Yes** | sherpa greedy, or the owned greedy loop — equivalent (Δ −0.31 pp, CI [−0.71, +0.11]) | Beam top-1 is not better than greedy; do not decode the transcript with beam search. |
| **`tokens[].confidence`** | **Yes — for highlighting** | emitted-token log-prob (`ys_log_probs`), word = min over tokens | AUROC 0.88; flagging the lowest 10% / 20% of words catches 56% / 74% of scorable errors. Relative ranking only — not a calibrated P(correct) for any automatic action. Blind to the ~41% of errors that are deletions. Unmeasured on the user's voice. |
| **`nbest[]`** | **Yes, via the owned Python beam (K ≤ 4)** | probe beam-4, deduplicated | Real oracle headroom (−2 pp), but the order is not meaningful beyond top-1 and ~half the raw list is duplicates. Costs ~4× the greedy loop, so compute it only when `decode_params.beam > 1` (C3); with beam 1 the list is the single top-1. No Phase 1 consumer. K=8 makes top-1 worse — do not use. |
| **sequence score** | **Yes, rank-only** | mean emitted-token log-prob (sherpa API) for utterance confidence; beam log-score for `nbest[].score` | Mean token log-prob tracks utterance WER (ρ 0.68); the beam score less so (0.63); the top-1/top-2 gap is near-useless (0.13). None is a probability. |
| **timestamps (`start_ms`/`end_ms`)** | **Yes, in shape; accuracy unmeasured** | sherpa `timestamps` + `durations` (frame-level, 80 ms encoder frames) | No reference alignments in the proxy set, so timing accuracy is not validated. |
| **`PartialTranscript`** | **Not established by this task** | Parakeet via this path is an offline decoder; partials would be repeated re-decodes of the growing buffer | Each re-decode would carry token confidences for free, but `stable_prefix_len`, revision behaviour and per-partial cost are unmeasured (UPWR/UPSR are deferred). |

### Is a small custom Python decoder justified?

**Yes — for N-best and biasing, not for confidence.** Confidence alone does not justify it:
sherpa's public API already returns a signal as good as the best the full distribution
offers. N-best does: the contract requires it, it carries real selector headroom, and the
only alternative is patching sherpa's C++. Biasing on Parakeet has to live in an owned loop
anyway (D-0013). The cost is measured and small: ~35 lines for greedy, ~75 for beam, and a
decode-loop RTF of 0.06 on top of the encoder. Phase 1 should decode with sherpa greedy or
the owned greedy loop, and call the owned beam only when a candidate list is requested.

---

## 9. Limits

- **WER on a public proxy set.** No F-WER, E-WER, dev-speak, code-switching or the real
  microphone — the conditions confidence most needs to work under are the ones this set
  cannot see (`COVERAGE.md`).
- **One model, one export, int8, CPU EP.** fp16/fp32 or a GPU EP could shift the numerical
  sensitivity in §4.
- **The beam is sherpa's simplified TDT beam.** A correct TDT beam might make the decoder's
  own ranking useful; that is tier 4 and untested.
- **Thin slices** (§2.2): general_en is uninformative; russian, noise and reverb support
  "it works", not rankings.
- **Timing is non-decision-grade** (§5).
