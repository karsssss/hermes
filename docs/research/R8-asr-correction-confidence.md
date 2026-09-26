# R8 — ASR correction pass: what works, and confidence estimation

Research landed 2026-09-26. Every claim is labeled **VERIFIED** (fetched primary source and
quoted/cited it), **PLAUSIBLE/SECONDARY** (credible secondary report, primary not fetched or
fetch was too degraded to confirm numbers), or **UNVERIFIED** (repeated but unconfirmed).
Never treat an UNVERIFIED line as a recommendation. Two numbers were caught mid-research as
**fabricated by a search-summary tool** (not by me pulling them from a paper) and are called
out explicitly in §E as a warning about exactly this failure mode.

## Headline

1. **PAC (arXiv 2509.12647) is miscited in our architecture doc.** VERIFIED by fetching the
   abstract directly: PAC is an **audio-in, LLM-based ASR model** (G2P-interleaved context
   learning + RL for homophone discrimination), evaluated by *replacing* a pretrained
   LLM-ASR baseline — **not a text-only post-hoc correction pass over a separate ASR's
   output.** If `ARCHITECTURE.md` cites PAC as the basis for the correction pass design,
   that citation should be corrected or dropped (lead's call, not mine to edit). The
   grapheme-phoneme-interleaving *idea* is reusable as inspiration for phonetic candidate
   generation; the paper itself is not evidence about correcting Nemotron/Parakeet
   hypotheses.
2. **Real hardware data kills synchronous free-generation correction.** VERIFIED via
   LocalScore.ai (crowdsourced llama.cpp benchmark) on our exact GPU class, **RTX 4050
   Laptop 6GB**: Llama-3.2-1B-Instruct Q4_K_M gets **301 ms time-to-first-token**; Gemma-3-4B
   Q4_K_M gets **1.28 s** TTFT. The correction budget is 60 ms p50 / 150 ms p95. **TTFT alone
   for the smallest usable model already exceeds the entire p95 budget**, before generating a
   single output token. A synchronous, free-generation correction pass is not achievable on
   this hardware at any model size we'd consider. Constrained/selective correction over a
   short span is the only synchronous option worth evaluating, and even that is tight (see §E).
3. **Transducer token-level confidence is obtainable, not automatically trustworthy.**
   NeMo ships `ConfidenceConfig`/`ConfidenceMethodConfig` (VERIFIED, GitHub primary) with
   `exclude_blank`, `aggregation` (mean/min/max/prod), and per-frame methods `max_prob` and
   entropy variants (Gibbs/Tsallis/Rényi). The entropy methods trace to a real NVIDIA/NeMo
   paper (arXiv 2212.08703, PLAUSIBLE/SECONDARY — summary-level fetch, not full-text quote)
   reporting **entropy-based confidence detects incorrect words up to 4x better than
   max-probability** for Conformer-RNNT on LibriSpeech. That is a genuine, usable signal.
   But **nothing in NeMo's own docstrings claims calibration**, there is no shipped
   *trained* confidence-estimation head by default (see §D), and none of this was evaluated
   on accented/code-switched speech, which is our actual target population. **Raw transducer
   confidence is a good binary "flag this word" signal after cheap calibration on our own
   data; it is not trustworthy for auto-accept/auto-correct decisions out of the box.**
4. **The evidence supports the project's frozen "select, don't rewrite" position**, from
   three independent angles: Apple's own research group found a **15x-smaller specialized
   seq2seq corrector beats LLM correction on WER** (VERIFIED primary fetch, arXiv 2405.15216);
   a training-free constrained-reranking method removed **38.8–57.1% of hallucinated
   failures** while "largely maintaining" WER (arXiv 2608.30776, PLAUSIBLE/SECONDARY,
   abstract only); and a three-stage verified-correction framework was built specifically
   *because* "directly using LLMs will encounter hallucinations problem" (arXiv 2505.24347,
   VERIFIED abstract quote). No 2024–2026 source found argues free generation is *safer* on
   meaning-preservation; the closest counter-signal is that free-generation LLM rescoring
   reports the largest raw WER gains (ProGRes, arXiv 2409.00217, PLAUSIBLE/SECONDARY,
   "5–25% relative" per secondary summary, not confirmed in the primary abstract text I
   could fetch). **Preserving this tradeoff, not resolving it, per the brief.**

## A. Second-pass ASR correction — what actually works

**HyPoradise / GER lineage.** VERIFIED (arXiv 2309.15701, HTML fetched via search summary,
core dataset claim consistent across sources): 334K N-best-hypothesis/transcription pairs,
introduces "generative error correction" (LLM predicts the transcription directly from
N-best, not just picks from the list). GitHub org `Hypotheses-Paradise` hosts `HP-v0`,
`Hypo2Trans`, `RobustGER`, `UADF` — follow-on work exists at least into 2025
(`RobustGER` = "LLMs are Efficient Learners of Noise-Robust Speech Recognition").
**Current (2026) maintenance activity on these repos was not directly checked (budget) —
do not assume they are still active without checking commit dates before depending on them.**

**PAC (2509.12647) — read in full**, per headline: audio-input LLM-ASR, not correction.
Verbatim abstract (VERIFIED, fetched twice from arxiv.org/abs and cross-checked):
> "PAC ... reduces relative Word Error Rate (WER) by 30.2% and 53.8% compared to pre-trained
> LLM-based ASR models, and achieves 31.8% and 60.5% relative reductions in biased WER for
> long-tail words compared to strong baselines" — LibriSpeech (English) and AISHELL-1
> (Mandarin). Authors: Li Fu, Yu Xin, Sunlu Zeng, Lu Fan, Youzheng Wu, Xiaodong He. Submitted
> 2025-09-16, targeting ICASSP 2026. No absolute WER numbers in the abstract; no code
> release found.

**Negative results on plain LLM correction (this is the section CLAUDE.md's probation rule
is really asking about):**
- **Apple ML Research, "Revisiting ASR Error Correction with Specialized Models" (arXiv
  2405.15216).** VERIFIED, primary fetch: a specialized seq2seq corrector reaches **1.5%/3.3%
  WER on LibriSpeech test-clean/test-other**, "outperforms LLMs" with **15x fewer
  parameters**, trained on synthetic corpora from cascaded TTS→ASR, and generalizes across
  CTC/seq2seq/transducer source ASR. Directly on point: a much smaller, non-LLM, purpose
  built corrector beat general LLM correction on the headline metric.
- **RLLM-CF (arXiv 2505.24347).** VERIFIED abstract quote: *"directly using LLMs will
  encounter hallucinations problem, which may lead to the modification of the correct
  text."* Their 3-stage fix (error pre-detection → CoT correction → verification) gets
  GPT-4o to **21% / 11% / 9% / 11.4% relative CER/WER reduction** on AISHELL-1/AISHELL-2/
  LibriSpeech — i.e., naive LLM correction was bad enough that the paper's entire
  contribution is damage control around it.
- **LCAR — Likelihood-Constrained Acoustic Reranking (arXiv 2608.30776).** PLAUSIBLE/SECONDARY
  (abstract-level fetch only). Restricts token choice to alternatives within a likelihood
  margin of the base model's greedy token, then reranks by acoustic compatibility.
  **Removes 38.8–57.1% of hallucination-detector-flagged failures at threshold δ=0.60**
  while "largely maintaining" WER on open test sets, across four LLM-based ASR systems.
  This is architecturally close to what our correction pass would need to do: constrain to
  plausible alternatives, don't let the model roam free.

**N-best rescoring.** ProGRes (arXiv 2409.00217, PLAUSIBLE/SECONDARY): zero-shot rescoring
using Llama-3-Instruct/GPT-3.5/GPT-4 as generators with Llama-3 as scorer; secondary
summaries report "5–25% relative WER improvement" but I could not confirm the number against
the primary abstract text within budget — **flag as unconfirmed, plausible.** Older
literature (ELECTRA rescoring, BERT-based confidence rescoring, ROVER) is well established
as a category but is 2020–2022 vintage and not re-verified here.

**Domain vocabulary in the correction prompt.** Not separately verified this session; see
R1's TurboBias/hotwords findings for the biasing-at-decode-time equivalent. No 2024–2026
paper specifically evaluating "put the user's biasing wordlist in the LLM correction
prompt" was found — treat as a plausible design choice, not evidence-backed yet.

## B. Constrained selection vs. free generation

The 2024–2026 evidence, taken together, **favors constraint** for our use case, but not
unanimously, and "semantic drift" is not a standardized, ASR-specific measurement — it is
borrowed. Specifically:

- No paper found runs a clean, controlled **A/B of constrained-selection vs. free-generation
  on the same model/data with both WER and a meaning-preservation metric reported side by
  side.** The evidence is indirect: papers that add constraints (LCAR, RLLM-CF, PMF-CEC
  below) do so explicitly *because* unconstrained generation hallucinated, and report
  hallucination-rate or verification-stage improvements, not a head-to-head drift number.
- **"Semantic drift" as a named, measured concept** exists in general text generation
  research (Meta AI, "Know When To Stop: A Study of Semantic Drift in Text Generation",
  PLAUSIBLE/SECONDARY, arXiv 2404.05411) — it measures the point where autoregressive
  generation starts preferring hallucinated content over correct content, via a "semantic
  drift score" over atomic facts. **This methodology was built for open-ended generation,
  not ASR correction — porting it would require adapting "atomic facts" to something like
  "words/entities changed vs. reference," which nobody has published for ASR correction
  specifically, as far as this research found.**
- **PMF-CEC (arXiv 2506.11064, PLAUSIBLE/SECONDARY, partial abstract only)** is the closest
  thing to a direct, quantified selection-mechanism paper: it uses **"error-specific
  selective decoding"** with **"a retention probability mechanism to filter out editing
  operations with confidence scores below a set threshold, preserving the original
  operation."** This is, functionally, the exact pattern `CLAUDE.md` already specifies
  (falls back silently to the unedited transcript on rejection) — evidence that the pattern
  is independently converged on elsewhere, not invented in a vacuum. Full numeric results
  not verified (fetch was abstract-only).
- Net: **preserve the tradeoff, do not resolve it.** The directionally consistent finding is
  that free generation buys larger raw WER numbers in some papers (ProGRes-style rescoring,
  unconfirmed magnitude) at a hallucination cost that multiple 2025–2026 papers built entire
  architectures to suppress. Nothing found contradicts the project's frozen position; nothing
  found gives it a hard number either.

## C. GER / error-mode characterization

| Error mode | Frequency signal (with caveat) | Text-only recoverable? | Needs N-best? | Needs phonetic info? | Needs audio? |
|---|---|---|---|---|---|
| Substitutions | Dominant class, **~83–87% of edit operations** in one 2026 multi-system study (ChinaVoices Challenge 2026, PLAUSIBLE/SECONDARY — Mandarin systems, not verified for our English/transducer case) | Partially — LM-plausible subs yes, acoustically-confusable proper nouns no | Helps (alt spellings often in N-best) | Often yes (homophones) | Sometimes |
| Deletions | Transducers reportedly show **more deletions relative to WER** than attention-based models (PLAUSIBLE/SECONDARY, uncited specifics) | Hard — nothing to anchor a missing word without context | Marginal | No | Best fixed at the source (endpointing/streaming), not post-hoc |
| Insertions | Transducers reportedly show **fewer insertions** than attention/CTC-with-LM models (same secondary source) | Easier — LM fluency signal alone often flags a spurious repeated/filler token | Helps | No | No |
| Named entities / proper nouns | Long-tail, exactly what biasing (R1) targets | Only if in a bias list / vocabulary; otherwise no | Yes — critical | Yes (near-homophone entity confusion) | Sometimes |
| Homophones / near-homophones | Not separately quantified this session | No, by definition — needs disambiguating signal | Yes | **Yes — this is the core case for phonetic candidate generation** | Helpful, not always necessary if phonetic distance + context suffice |
| Punctuation / casing | Handled by ITN/formatting layer per architecture, not this memo's scope | Yes, text-only | No | No | No |
| Code-switching errors | **Catastrophic, not incremental.** VERIFIED quote, arXiv 2609.11786 (English–Yoruba): *"Yoruba token recognition collapses (error 0.97 for almost all systems)"*. Malay-English and Korean-English degradation numbers (22%→58.67% WER; 50.1% PIER at switch points) were reported by a search-summary tool but **I could not confirm them against a primary abstract within budget — treat as unverified, not cited as fact.** | Partially — if the correction model is genuinely bilingual | Helps some | Sometimes (cross-language near-homophones) | Would help a lot; text-only correction is weak here |
| Accented (L2) speech | Not independently quantified this session with a verified number; treated as a first-class error source per project brief, consistent with the general code-switching/entity findings above | Same limits as substitutions/entities | Helps | Helps | Would help |
| Project-specific terms / code identifiers | Long-tail, same bucket as named entities; TARQ (R1, arXiv 2605.27808) already shows quantization hits this class hardest | Only with vocabulary/biasing | Yes | Yes (e.g., "getUserID" vs. spoken form) | Sometimes |

**Bottom line for what the correction pass can be given as input:** N-best list and a
phonetic distance to a project vocabulary are load-bearing for the two error classes that
matter most for a developer/technical user (entities, code identifiers, homophones). Deletions
are largely *not* fixable post-hoc without audio and are better addressed upstream
(endpointing, VAD) — do not budget correction-pass effort against them.

### Phonetic candidate generation — G2P options and licenses

| Tool | License | Verified? | Note |
|---|---|---|---|
| `g2p_en` (Kyubyong Park) | **Apache-2.0** | VERIFIED (`setup.py` license field, GitHub) | English-only, rule+lookup based, clean for commercial use |
| `phonemizer` (bootphon) | **GPL-3.0** | VERIFIED (LICENSE file, GitHub) | The Python wrapper itself is GPL, independent of any backend choice |
| `espeak-ng` | **GPL-3.0 (was considering LGPL relicense as of an open GitHub issue, not resolved)** | VERIFIED (repo license; relicense issue #2131 open, PLAUSIBLE/SECONDARY that it's unresolved) | **Subprocess vs. linking does change the analysis, but only partially.** GPL's copyleft is triggered by "linking"/combining into one work; invoking as an independent subprocess via CLI is the standard way projects avoid inheriting GPL. **However, `phonemizer`'s own espeak backend loads `libespeak-ng` as a **shared library via ctypes**, not a subprocess — that is dynamic linking, which is the case GPL's copyleft argument applies to most directly.** A build that shells out to the `espeak-ng` CLI binary (not through `phonemizer`) is the more defensible arm's-length pattern, but **get a real legal read before shipping any espeak-ng-adjacent path in a commercial installer** — this is not something to resolve by inference. |
| CharsiuG2P (`lingjzhu`) | **MIT** | PLAUSIBLE/SECONDARY (search-summary, not a fetched LICENSE file) | Transformer-based, 100 languages; verify LICENSE file directly before depending on it |
| `piper-plus-g2p` (Rust crate) | **MIT** | VERIFIED (crates.io API JSON) | Described by its own maintainer as **"eSpeak-ng free"** — i.e., built specifically to avoid the GPL dependency. Current best Rust-native candidate. v0.4.0. |
| `grapheme_to_phoneme` (Rust crate) | **BSD-4-Clause** | VERIFIED (crates.io API JSON) | Stuck at v0.1.0, one release ever — treat as effectively unmaintained. BSD-4's advertising clause is also a real nuisance clause to carry into a commercial NOTICE file. |
| `g2p2-core` (Rust crate) | Not verified this session | UNVERIFIED | Advertised as zero-dependency, covers the 101 Whisper languages; check license before use |

**Recommendation direction (not a decision — lead's call):** `piper-plus-g2p` is the cleanest
Rust-native path (MIT, no GPL entanglement) if its English phoneme quality is adequate;
`g2p_en` is the clean Python fallback for the prototype phase. **Avoid espeak-ng/phonemizer
in any shipped path without a legal read**, matching R5's existing pattern of flagging
license questions rather than resolving them by inference.

**Weighted phoneme edit distance:** published weightings exist (Phonologically Weighted
Levenshtein Distance / PWLD, and a "Data-Driven PWLD" variant weighting substitution cost by
articulatory-feature distance; also older confusion-matrix-derived weighted edit distance
work going back to Wagner–Fischer-style formulations) — **PLAUSIBLE/SECONDARY, not fetched
from a primary paper this session.** No off-the-shelf, English-ASR-tuned, redistributable
weight table was found; expect to either adopt PWLD's articulatory-feature weighting scheme
or derive our own from our own confusion data. **This is not a solved, drop-in problem.**

## D. Confidence estimation — the load-bearing section

**What NeMo actually ships (VERIFIED, `nemo/collections/asr/parts/utils/asr_confidence_utils.py`,
GitHub primary fetch):**
- `ConfidenceConfig`: `preserve_frame_confidence`, `exclude_blank` (blank-token scores are
  excluded from token-level aggregation "to avoid contaminating scores with information from
  deleted units" — i.e., NeMo's own authors treat raw blank-inclusive confidence as unreliable
  by default), `aggregation` ∈ {mean, min, max, prod} for token→word rollup.
- `ConfidenceMethodConfig`: per-frame score via `max_prob`, or entropy (Gibbs/Tsallis/Rényi,
  linear or exponential normalization).
- **No explicit calibration claim anywhere in the docstrings.** This is a toolkit for
  *computing* a confidence signal, not a certification that the signal is calibrated
  probability. Treat it as a ranking/thresholding feature, not a probability.
- The entropy methods are grounded in a real NeMo-affiliated paper, **arXiv 2212.08703**
  (PLAUSIBLE/SECONDARY — summary-level, not full-text-quoted): entropy-based confidence
  **"up to 2 and 4 times better than max-probability at detecting incorrect words for
  Conformer-CTC and Conformer-RNN-T"** on LibriSpeech test sets, with the best configuration
  reported as **Tsallis entropy (α=1/3), exponential normalization, min aggregation.** This
  is a genuinely useful, RNNT-specific, LibriSpeech-measured result — but LibriSpeech is
  clean read speech, not accented/code-switched conversational dictation. **Expect the
  detection quality to degrade on our actual user population; this has not been measured
  anywhere found.**
- **Dedicated confidence estimation model (CEM) as a separate trained head:** the literature
  has one (word-level confidence estimation for RNN-T, arXiv 2110.15222, a lightweight neural
  model using time-alignment info, PLAUSIBLE/SECONDARY) but **this is not what NeMo ships by
  default** — NeMo's shipped path is the non-trainable entropy/max-prob aggregation above, not
  a trained CEM. Building a real CEM means training a small model on our own labeled
  correct/incorrect-word data; nothing off-the-shelf was found that we could just import.

**What sherpa-onnx exposes:** a PR (**#2897**, k2-fsa/sherpa-onnx) adds
`SherpaOnnxVocabLogProbs` / `token_log_probs`, giving **per-token full-vocabulary
log-probability distributions for both streaming and offline transducer models (Zipformer,
NeMo-family)**, intended to support confidence scoring, entropy estimation, and ROVER-style
fusion. **PR status was ambiguous when fetched — the page header showed "Closed" while
conversation activity continued into April 2026; I could not confirm whether it is merged
into a released version. Verify current status and which sherpa-onnx release contains it
before depending on it** — do not assume it's in whatever version we pin.

**Blank tokens and calibration, the honest synthesis:** transducer posteriors are
well-documented in this research as needing blank-exclusion to be usable at all (NeMo does
this by default), and the entropy-vs-max-prob comparison is the main lever anyone has
published for *relative* ranking of confidence within an utterance. **Nothing found supports
treating a raw (or even entropy-transformed) transducer score as a calibrated probability
usable for an absolute accept/reject threshold without fitting a calibration curve
(temperature scaling / Platt / isotonic) on labeled data from our own pipeline.** Calibration
of this kind is standard ML practice and can be fit on a few hundred to low-thousands of
labeled utterances — feasible on a small personal dataset — but **it has to be done, it does
not come free from the model or the runtime.**

**Product-question answer, plainly:**
- **Auto-accept:** not supportable by raw or entropy confidence alone at any threshold found
  in this research. Requires calibration on our own data first, and even then should be
  scoped to high-confidence, non-entity, non-code-switched spans only.
- **Visually highlight low-confidence spans for the user:** **this is the well-supported use.**
  Entropy-based ranking is explicitly validated for *detecting* likely-incorrect words (the
  2212.08703 result), which is exactly what a highlight needs — relative discrimination, not
  calibrated probability.
- **Trigger a correction attempt:** supportable as a *gate*, using the same relative-ranking
  signal — attempt correction only on flagged low-confidence spans, not the whole utterance
  (this also solves the latency problem in §E).
- **Ask the user to confirm:** the same gate, at a stricter threshold, reserved for spans that
  are both low-confidence and touch a named entity / code identifier / bias-list term.

## E. Latency

**Correction-pass budget: 60 ms p50 / 150 ms p95, inside an overall 300/700 ms p95 hotkey-to-
text budget.**

**Real measured data on our target GPU class — RTX 4050 Laptop 6GB (VERIFIED,
LocalScore.ai, a crowdsourced llama.cpp benchmark database, `localscore.ai/accelerator/598`):**

| Model | Quant | Prompt tok/s | Gen tok/s | **TTFT** |
|---|---|---|---|---|
| Llama-3.2-1B-Instruct | Q4_K_M | 4917 | 118 | **301 ms** |
| Gemma-3-4B-it | Q4_K_M | 1201 | 31.4 | **1.28 s** |
| Llama-3.1-8B-Instruct | Q4_K_M | 2455 | 45.5 | 525 ms |

These are individual crowdsourced runs (single submissions, not averaged, context length and
driver version unspecified) — **treat as indicative, not lab-grade**, but they are the only
verified numbers this research found on our exact card. **Even the smallest usable model's
TTFT (301 ms) exceeds the entire 150 ms p95 correction budget before a single output token is
generated.** Generation speed (118 tok/s for the 1B model) means each additional ~8 tokens of
output costs another ~68 ms on top of that. **A synchronous, whole-utterance, free-generation
correction pass is not achievable on this hardware at any model size worth using.**

**A caught fabrication, reported per the task's evidence-discipline requirement:** an earlier
search-summary in this session claimed specific RTX 4050 Laptop numbers from a *different*
page (`databasemart.com`) that, on direct fetch, **did not contain any RTX 4050 data at all**
— the summarizer had invented or misattributed numbers. I discarded that claim entirely and
only cite the LocalScore.ai numbers above, which I verified by fetching the actual
accelerator page directly. This is exactly the failure mode the task brief warned about;
flagging it here rather than silently dropping it.

**CPU-only, i5-12450H specifically: no verified benchmark found.** General secondary claims
("3–13B models at 8–15 tok/s on modern CPUs," "Phi-4-mini ~12 tok/s CPU-only") came from
content-farm-quality sources (`promptquorum.com`, similar) with no methodology shown —
**UNVERIFIED, not to be cited as fact.** Expect CPU-only to be meaningfully slower than the
GPU numbers above; this needs to be measured directly on the target machine, not estimated
from these sources.

**The one verified laptop-GPU-class ASR (not correction-LLM) latency figure, for context**
(consistent with R4's note that this is the only one found anywhere): **qwen3-asr.cpp on an
RTX 5060 Laptop 8GB (VERIFIED, GitHub README fetched directly)** — 235 ms median per 2 s
chunk for the 0.6B model, 317 ms for the 1.7B model, MIT license (model weights Apache-2.0).
This is the ASR encoder, not a correction LLM, but it confirms the general shape: even a
purpose-built streaming ASR component on a *stronger* laptop GPU than ours is consuming a
large fraction of a 150–300 ms budget, leaving very little room for a second LLM pass to
share the same window.

**Small local LLM shortlist, licenses (all VERIFIED against HuggingFace model cards
directly, 2026-09-26):**

| Model | Params | License | OSI-approved | GGUF Q4_K_M size |
|---|---|---|---|---|
| Qwen3-1.7B | 1.7B (1.4B non-embed) | **Apache-2.0** | Yes | **1.28 GB** (VERIFIED, bartowski GGUF listing) |
| Qwen3-4B | 4B | Apache-2.0 (consistent with Qwen3 family; 4B card itself not individually re-checked) | Yes | not directly measured; ~0.6 GB/B rule of thumb ≈ 2.4 GB |
| Phi-4-mini-instruct | 3.8B | **MIT** | Yes | not directly measured, ONNX release confirmed on the model card; GGUF via community quantizers |
| Gemma-3-4B-it | 4B | **Gemma custom terms** (ai.google.dev/gemma/terms) | **No — not OSI-approved**, commercial use allowed but Google's terms are not a standard open license | — |
| Llama-3.2-3B / 1B | 3B / 1B | **Llama 3.2 Community License** | No | Llama-3.2-1B Q4_K_M measured above, 301 ms TTFT | 
| SmolLM3-3B | 3B | **Apache-2.0** | Yes | not directly measured |

Note: the Llama 3.2 license text I fetched contains the familiar Meta restriction verbatim
(VERIFIED, model card): *"If ... the monthly active users of the products or services made
available by or for Licensee ... is greater than 700 million monthly active users ... you
must request a license from Meta"* — irrelevant at Hermes's scale, noted for completeness.

**Sync vs. async — the real options, given TTFT alone blows the sync budget for whole-utterance
correction:**
1. **Correct only flagged low-confidence spans, not the whole utterance.** A span is typically
   1–3 words. At ~118 tok/s generation (1B model, our GPU numbers) plus the fixed ~300 ms
   TTFT, this is *still* over budget for synchronous use inside 150 ms p95 — **TTFT, not
   generation speed, is the bottleneck**, and TTFT does not shrink much with shorter output.
   This only becomes viable synchronously if the model can be kept **warm and resident**
   (avoiding cold-start TTFT) and prompt length is kept minimal — neither eliminates the
   fundamental prefill cost, but a resident, pre-warmed model is the only lever that could
   plausibly get a *span-only* correction near budget. **Not verified as sufficient — would
   need direct measurement of warm-resident TTFT, which none of the sources found report.**
2. **Correct-after-injection and patch (async).** Inject the raw ASR output immediately (meets
   the 700 ms p95 hard gate), run correction in the background, then patch the injected text
   via the same UIA-verified injection path if a correction is accepted. Technically
   consistent with the architecture's existing "injection is verified, not fire-and-forget"
   principle — this just means the correction path reuses that same verified-injection
   machinery a second time. UX cost: a visible micro-edit after the fact, which is jarring in
   fast-typing contexts but far less bad than the alternatives, and it's the only option that
   doesn't touch the hard latency gate at all.
3. **Correct only on explicit user request** (e.g., a hotkey to "clean up last utterance").
   No latency budget pressure at all. Lowest engineering risk, lowest automatic value —
   the user must notice something is wrong and ask.
4. **Never correct, ship nothing in Phase 1** — see recommendation below.

## What should run synchronously (inside the 700 ms p95 budget)

- Entropy/max-prob confidence computation and aggregation (NeMo-style, cheap — this is
  arithmetic over already-computed logits, not a second model call).
- Confidence-based **highlighting** of low-confidence spans in the injected/displayed text.
- Deterministic FST-style rewrites (`rule_fsts`/`rule_fars`, per R1) for known exact-spelling
  enforcement — these are not LLM calls and do not carry LLM latency.

## What may run asynchronously (after injection, or on demand)

- Any LLM-based correction pass, whole-utterance or span-level, given the TTFT numbers above.
- N-best/ROVER-style rescoring beyond what decode-time beam search already does.
- User-requested "clean up last utterance."

## What should never be auto-corrected

- **Any span the confidence signal has not been calibrated to trust** — per §D, that's
  effectively everything until we run our own calibration study.
- **Named entities, proper nouns, and code identifiers changed to a *different* entity/
  identifier than what N-best or the bias list supports** — this is exactly the
  hallucination failure mode LCAR and RLLM-CF were built to suppress, and it is the
  single worst failure for a developer tool (a corrected variable name that silently
  becomes a *different* real identifier is worse than a visible error).
- **Anything in a password field or blocklisted process** — already a hard architecture rule
  for injection generally; a correction pass must inherit the same exclusion, not just the
  initial injection.
- **Deletions** (missing words) — per §C, these are not text-recoverable and a "correction"
  that inserts a plausible-sounding word the user never said is fabrication, not correction.
- **Any span where the correction candidate is not present in the N-best list or the
  phonetic-candidate set** — i.e., never let the model introduce a token that came from
  neither the ASR's own hypotheses nor a bounded phonetic-distance search. This is the
  concrete implementation of "selects among candidates, never freely rewrites."
- **Code-switched spans**, until we have a bilingual-aware correction path — per the verified
  Yoruba finding, current systems don't even recognize these reliably, let alone correct them
  safely.

## Recommended Phase 1 correction policy

Given §E's finding that synchronous free-generation correction is not achievable on target
hardware, and §D's finding that raw confidence is not yet trustworthy for auto-accept:

**Ship confidence-based highlighting only in Phase 1. Do not ship an LLM correction pass yet.**
Concretely:
1. Compute NeMo-style entropy-based word confidence (cheap, already-available signal, no
   second model, no latency risk) and expose it in `AsrResult` per the architecture's existing
   requirement — this is infrastructure we need regardless of whether correction ships.
2. Surface low-confidence spans to the user visually (this is the one product use §D's
   evidence actually supports without calibration).
3. Defer any LLM correction call entirely to a **user-requested, async, on-demand** path
   (§E option 3) — no latency gate risk, and it buys time to run a real calibration study on
   our own usage data before trusting the signal for anything automatic.
4. Treat "correct-after-injection and patch" (§E option 2) as the Phase 2 candidate *if* the
   calibration study shows the confidence signal is good enough to gate it — not before.
5. **This is the honest "ship nothing automatic in Phase 1" option**, scoped down from "ship
   nothing at all" only because the confidence/highlighting infrastructure is low-risk,
   already required by the architecture, and independently useful even if correction itself
   never ships. If F-WER measurement later shows highlighting alone doesn't move the number,
   cut it too, per the project's own probation rule.

## Unresolved research questions

- Exact current merge/release status of sherpa-onnx PR #2897 (`token_log_probs`/
  `vocab_log_probs`) — check before depending on it.
- Whether NeMo's or sherpa-onnx's confidence signals degrade specifically on accented (L2)
  and code-switched speech — not measured anywhere found; this is the single most relevant
  gap given the user's own speech profile.
- Warm-resident TTFT for a 1–2B model on the RTX 4050 6GB when sharing VRAM with a resident
  ASR model — no source measured this; needs a direct spike.
- CPU-only (i5-12450H specifically) small-LLM tokens/sec — no credible source found;
  needs direct local measurement.
- A real, citable, ASR-specific semantic-drift metric — does not appear to exist yet as
  published methodology; §B's finding stands as a gap, not a citation.
- Whether HyPoradise-lineage repos (`RobustGER`, `UADF`, `CHSER`) are still maintained as of
  2026 — existence confirmed, current activity not checked.
- A redistributable, English-tuned weighted-phoneme-edit-distance table — not found;
  PWLD/DD-PWLD are the closest published starting points but were not independently verified
  this session beyond secondary summary.
- Direct legal read of espeak-ng's GPL exposure for a subprocess-only integration pattern —
  flagged, not resolved, consistent with R5's existing CUDA/cuDNN flag-don't-resolve pattern.

## Sources

arXiv [2509.12647](https://arxiv.org/abs/2509.12647) (PAC) ·
[2309.15701](https://arxiv.org/abs/2309.15701) (HyPoradise) ·
[2405.15216](https://arxiv.org/html/2405.15216) (Apple, specialized correction models) ·
[2505.24347](https://arxiv.org/abs/2505.24347) (RLLM-CF) ·
[2608.30776](https://arxiv.org/pdf/2608.30776) (LCAR) ·
[2506.11064](https://arxiv.org/pdf/2506.11064) (PMF-CEC) ·
[2409.00217](https://arxiv.org/abs/2409.00217) (ProGRes) ·
[2212.08703](https://arxiv.org/abs/2212.08703) (entropy-based confidence, NeMo-affiliated) ·
[2110.15222](https://arxiv.org/pdf/2110.15222) (word-level RNN-T confidence / CEM) ·
[2609.11786](https://arxiv.org/abs/2609.11786) (English–Yoruba code-switch WER) ·
[2508.07285](https://arxiv.org/pdf/2508.07285) (non-intrusive ASR refinement survey) ·
[2404.05411](https://arxiv.org/html/2404.05411v1) (semantic drift in text generation, Meta) ·
[NeMo `asr_confidence_utils.py`](https://github.com/NVIDIA-NeMo/NeMo/blob/main/nemo/collections/asr/parts/utils/asr_confidence_utils.py) ·
[sherpa-onnx PR #2897](https://github.com/k2-fsa/sherpa-onnx/pull/2897) ·
[Hypotheses-Paradise GitHub org](https://github.com/Hypotheses-Paradise) ·
[g2p_en / Kyubyong/g2p](https://github.com/Kyubyong/g2p) (Apache-2.0, `setup.py`) ·
[phonemizer LICENSE](https://github.com/bootphon/phonemizer/blob/master/LICENSE) (GPL-3.0) ·
[espeak-ng](https://github.com/espeak-ng/espeak-ng) (GPL-3.0) and
[relicense discussion #2131](https://github.com/espeak-ng/espeak-ng/issues/2131) ·
[CharsiuG2P](https://github.com/lingjzhu/CharsiuG2P) ·
crates.io API for
[`piper-plus-g2p`](https://crates.io/api/v1/crates/piper-plus-g2p) (MIT) and
[`grapheme_to_phoneme`](https://crates.io/api/v1/crates/grapheme_to_phoneme) (BSD-4-Clause) ·
HuggingFace model cards:
[Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B),
[Phi-4-mini-instruct](https://huggingface.co/microsoft/Phi-4-mini-instruct),
[gemma-3-4b-it](https://huggingface.co/google/gemma-3-4b-it),
[Llama-3.2-3B](https://huggingface.co/meta-llama/Llama-3.2-3B),
[SmolLM3-3B](https://huggingface.co/HuggingFaceTB/SmolLM3-3B) ·
[bartowski/Qwen_Qwen3-1.7B-GGUF](https://huggingface.co/bartowski/Qwen_Qwen3-1.7B-GGUF) ·
[LocalScore RTX 4050 Laptop results](https://www.localscore.ai/accelerator/598) ·
[qwen3-asr.cpp](https://github.com/JohnsonChang123/qwen3-asr.cpp) (MIT; RTX 5060 Laptop 8GB
benchmark in README) ·
R1 (`docs/research/R1-quantization-and-biasing.md`), R4, R5
(`docs/research/R5-rust-stack.md`) for prior-finding cross-references.
