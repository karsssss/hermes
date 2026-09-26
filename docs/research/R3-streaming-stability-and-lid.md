# R3 — Partial-hypothesis stability & code-switched language ID

Research landed 2026-09-24. All URLs fetched directly; quotes verbatim. Items marked
**unverified** must not be treated as fact.

## Headline

1. There is a **rigorous, citable, ASR-specific metric for flicker** — UPWR/UPSR — that we
   should adopt in `BENCHMARKS.md`. We were going to invent one; we do not need to.
2. **No local Whisper-based dictation app has solved streaming partials.** They all sidestep
   it by not streaming. That is a real product opening.
3. **Whisper silently translates code-switched speech instead of transcribing it**, and the
   cause is in its training data construction — it is architectural, not a bug to configure
   around. This directly threatens W2.

## A. Metrics for flicker — adopt these

### UPWR / UPSR (ASR-specific, the one we want)

Shangguan et al. (Google), *Analyzing the Quality and Stability of a Streaming End-to-End
On-Device Speech Recognizer*, arXiv:2006.01416, Interspeech 2020.

- **Unstable Partial Word Ratio (UPWR):** total unstable words / total words in final
  hypotheses. Range [0, inf); closer to 0 is more stable.
- **Unstable Partial Segment Ratio (UPSR):** aggregated revised segments / total
  utterances.
- A segment is unstable if it *revises* previously-shown words (as opposed to merely
  appending); all words after an unstable word in that segment count as unstable too.

They decompose instability into **streaming instability** (the model emits partial subwords
before a full word is spoken — worse in E2E subword models) and **text-normalization
instability** (punctuation/spacing, capitalization 24.7%, numeral 1.7% — e.g. "eight
hundred" flipping to "800").

**Mitigations they measured:** domain-id conditioning (~50% UPWR/UPSR improvement), text
normalization on training data (~20-30%), lowercase-then-refresh FSTs to kill capitalization
flips, forcing punctuation to be single tokens rather than subword fragments.

### Erasure / Normalized Erasure (the MT-lineage alternative)

Arivazhagan et al. (Google), arXiv:1912.03393, ICASSP 2020.
`E(i) = |o_{i-1}| - |LCP(o_i, o_{i-1})|`; `NE = (1/|o_I|) * sum_i E(i)`.
Their "mask-k" heuristic plus biased beam search cut NE **up to ~20x with minimal quality
loss** — directly applicable if we stream partials.

### Google's `stability` field — the UX precedent

Cloud Speech-to-Text exposes, verbatim: *"An estimate of the likelihood that the recognizer
will not change its guess about this interim result. Values range from 0.0 (completely
unstable) to 1.0 (completely stable)."* A per-token numeric stability score is the right
shape for deciding when to stop re-rendering a word.

**No agreed industry term exists** ("flicker rate", "revision rate" are informal). UPWR/UPSR
and NE are the two peer-reviewed formalisms.

## B. Vendor semantics — the design space

| Vendor | Model | Key params / defaults |
|---|---|---|
| **AssemblyAI** | **Immutable** — "every character emitted is final and never changes". Single `Turn` event; per-word `word_is_final` | `end_of_turn_confidence_threshold` 0.4, `min_turn_silence` ~400 ms, `max_turn_silence` 1280 ms |
| **Deepgram** | Revisable interims. `is_final` = "this chunk is locked"; `speech_final` = "utterance ended" | **`endpointing` default 10 ms** (docs' own example uses 300); `utterance_end_ms` min/default 1000, requires `interim_results=true` |
| **Speechmatics** | `AddPartialTranscript` (revisable) vs `AddTranscript` (final). Partials opt-in | `max_delay` 0.7-4 s, **default 4 s**; `max_delay_mode` default `flexible` |
| **Soniox** | **Token-level** `is_final`; non-final tokens "may change, disappear, or be replaced" | Reports `final_audio_proc_ms` |
| **OpenAI Realtime** | `delta` (revisable) / `completed`. Docs explicitly tell integrators to handle deltas correcting earlier text | — |
| **Gladia** | `receive_partial_transcripts` default **false** | — |

Two viable product stances: **(a) immutable-from-the-outset** (AssemblyAI) or **(b) expose an
unstable tail and lock on silence/confidence** (Deepgram, Speechmatics). Both are defensible;
mixing them is not.

## C. Local dictation apps have not solved this — an opening

Surveyed Whispering, Handy, VoiceInk, Buzz, Vibe. **None implements true continuous
streaming with revisable live partials.** All are record-then-batch on offline
Whisper-family models.

- **Handy** — confirmed push-to-talk: hold, release, Whisper runs, text pastes. Silero VAD
  only trims silence. No live partials.
- **Buzz** — source inspected. Rolling numpy buffer, **RMS-based** silence detection (not
  real VAD), ~5 s batches with `initial_prompt` carried over, emits only finalized text per
  batch. Chunked-batch pseudo-streaming.
- **Whispering, VoiceInk** — README-level only, appear to be hold-then-batch. *Unverified.*
- **Vibe** — the only one advertising "Realtime preview", supports Parakeet-TDT-v3.
  Mechanism **unverified**; may be chunked re-transcription rather than a stability
  contract.

**Implication:** if we ship genuine stable streaming partials on-device, that is a visible
capability no local competitor currently has. It also means there is no local prior art to
copy — we would be porting the vendor patterns above.

## D. Whisper and code-switching — a structural problem for W2

`detect_language()` does **one encoder pass over the entire 30 s window** and reads a single
language token off the first decoder position. **One language per window, never per clause.**

**The cause of silent translation, from the Whisper paper section 2.1, verbatim:**

> "We use an audio language detector... to ensure that the spoken language matches the
> language of the transcript... If the two do not match, we don't include the pair as a
> speech recognition example... **We make an exception if the transcript language is English
> and add these pairs to the dataset as X-to-En speech translation training examples
> instead.**"

Whisper was **trained** to associate "language mismatch inside a chunk" with "translate to
English". This is why it silently translates code-switched speech even with
`task="transcribe"`. It is architectural.

The same paper concedes: *"Zero-shot Whisper's accuracy at language identification is not
competitive with prior supervised results on Fleurs."*

Three failure modes to design against: (1) silent translation instead of transcription;
(2) wrong script selection (Simplified vs Traditional Chinese); (3) **language flip-flop
between consecutive windows**, because each window re-runs detection with no memory of the
previous decision.

**faster-whisper mitigations (source-verified):** `language_detection_threshold` default
**0.5**; `language_detection_segments` default **1**; `multilingual` default **False** —
setting it re-runs detection per segment, which trades one failure mode for another.

**Mitigation patterns** (informed synthesis, not a single citable source): hysteresis
(require the challenger to beat the incumbent by a margin), majority vote over N chunks
(what `language_detection_segments` is), forcing the language when the set is known, and
probability thresholds.

## E. Model options for code-switching

| Model | License | Streaming | Notes |
|---|---|---|---|
| **parakeet-tdt-0.6b-v3** | **CC-BY-4.0** | **Yes** — repo ships a streaming script (`chunk_secs` 2 s, `left_context_secs` 10 s, `right_context_secs` 2 s) | 25 languages **including Ukrainian and Russian**. FastConformer + TDT, 600M. Open ASR avg 6.34%, LibriSpeech clean 1.93% |
| **canary-1b-v2** | **CC-BY-4.0** | **No** — encoder-decoder AED, treat as offline | Same 25 languages, 978M, bidirectional En<->24-lang translation. HF leaderboard mean 7.15% |
| **SenseVoiceSmall** | **Custom proprietary — verify before commercial use** | Not natively; sherpa-onnx wraps with VAD chunking | 50+ languages. **Joint LID + ASR in one non-autoregressive pass** — architecturally the cleanest answer to per-chunk LID flip-flop. Claims 70 ms per 10 s audio |
| **sherpa-onnx streaming** | varies | **Yes** — true transducers | Bilingual zh+en Zipformer, trilingual zh+yue+en Paraformer. Whisper/WeNet/NeMo listed **offline-only** in that catalog |
| **FireRedASR2S** | — | *unverified* | arXiv 2603.10420 (Mar 2026). Integrated ASR+VAD+**FireRedLID**+punctuation. LID claims 97.18% on FLEURS, 100+ languages, "outperforming Whisper and SpeechBrain". Explicitly targets code-switching |

**The licensing note that matters:** Parakeet-TDT-v3 and Canary-v2 are **CC-BY-4.0**, i.e.
commercially usable with attribution. SenseVoice is **not** a standard OSS licence.

## Cross-references to our own docs

- Adopt **UPWR/UPSR** in `BENCHMARKS.md` alongside F-WER and E-WER.
- Parakeet-TDT-v3's **native Ukrainian and Russian support** is directly relevant to the W2
  code-switching set, and it is CC-BY-4.0.
- Note the tension with **R1**: Parakeet TDT is the best code-switching fit here, but R1
  found NVIDIA's own runtime **ignores word boosting for Parakeet TDT**. W2 and W3 may pull
  toward different models. This is the central model-selection conflict to resolve.

## Sources

[arXiv 2006.01416](https://arxiv.org/abs/2006.01416) ·
[arXiv 1912.03393](https://arxiv.org/abs/1912.03393) ·
[Whisper paper 2212.04356](https://arxiv.org/abs/2212.04356) ·
[FireRedASR2S 2603.10420](https://arxiv.org/abs/2603.10420) ·
[parakeet-tdt-0.6b-v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) ·
[canary-1b-v2](https://huggingface.co/nvidia/canary-1b-v2) ·
[SenseVoiceSmall](https://huggingface.co/FunAudioLLM/SenseVoiceSmall) ·
[AssemblyAI streaming](https://www.assemblyai.com/docs/speech-to-text/universal-streaming) ·
[Deepgram interim results](https://developers.deepgram.com/docs/interim-results) ·
[Speechmatics RT API](https://docs.speechmatics.com/rt-api-ref) ·
[Soniox realtime](https://soniox.com/docs/stt/rt/real-time-transcription) ·
[sherpa-onnx pretrained models](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/index.html)
