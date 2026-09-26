# 04 — Curriculum

Status: draft, 2026-09-24.

A reading list is not a plan. This is sequenced against `ROADMAP.md`: study each block
while building the phase that needs it, so the theory has something to attach to. Reading
all of it before writing code is the most common way this kind of project dies.

**Rule of thumb:** for every block below, the goal is to be able to *debug* the component,
not to reimplement it from scratch. You need enough theory to know why WER went up.

---

## The disciplines, and why each one earns its place

| Discipline | What breaks without it |
|---|---|
| **Digital signal processing** | You resample badly, mis-set gain, or window your STFT wrong, and lose WER before the model sees anything |
| **Phonetics & speech science** | You can't reason about accents, homophones, or why your G2P candidate generation is producing nonsense |
| **Classical ASR** (HMM, WFST, CTC, RNN-T) | Transducers, beam search, and contextual biasing are opaque magic; you can't implement §5.4 |
| **Deep learning / sequence models** | You can't fine-tune, quantize, or diagnose a model |
| **NLP & LLMs** | The correction pass, ITN, and punctuation layers are guesswork |
| **Real-time systems** | Audio dropouts, GC pauses, latency spikes you can't explain |
| **Evaluation & statistics** | You ship changes that feel better and measure worse — or worse, you can't tell |
| **Product & positioning** | You build the thing nobody asked for, beautifully |

---

## Block A — Foundations (during Phase 0)

**DSP, just enough**
- *The Scientist and Engineer's Guide to Digital Signal Processing* — Steven W. Smith.
  Free at [dspguide.com](https://www.dspguide.com/). Read ch. 1–12. Practical, not rigorous.
- Coursera: **Audio Signal Processing for Music Applications** (UPF/Stanford — Xavier Serra,
  Julius O. Smith). The best hands-on audio DSP course that exists; the sms-tools
  assignments will teach you STFT and windowing properly.
- Julius O. Smith's free online books at [ccrma.stanford.edu/~jos](https://ccrma.stanford.edu/~jos/)
  for reference when you hit a specific resampling or filtering question.

**The canonical text**
- *Speech and Language Processing* — Jurafsky & Martin, 3rd ed. Free draft at
  [web.stanford.edu/~jurafsky/slp3](https://web.stanford.edu/~jurafsky/slp3/). The ASR,
  phonetics, and text-normalization chapters are directly relevant. This is the one book to
  actually own.

**Hands-on, immediately**
- **Hugging Face Audio Course** — [huggingface.co/learn/audio-course](https://huggingface.co/learn/audio-course).
  Free, short, and maps 1:1 onto what you're building. Do this in week one.

*Deliverable for this block: you can explain, from memory, what happens to a sound wave
between the microphone and the encoder's first layer.*

---

## Block B — How ASR actually works (during Phase 1)

**Papers, in this order** — this sequence is the intellectual history of the field and each
paper answers a problem the previous one created:

1. **CTC** — Graves et al. 2006, *Connectionist Temporal Classification*. Why alignment-free
   training works. ([Distill's "Sequence Modeling with CTC"](https://distill.pub/2017/ctc/)
   is the best explainer ever written on this — read it first.)
2. **RNN-T** — Graves 2012, *Sequence Transduction with RNNs*. Why streaming ASR is a
   transducer. This is the architecture family Parakeet belongs to.
3. **Listen, Attend and Spell** — Chan et al. 2015. The encoder-decoder alternative.
4. **Attention Is All You Need** — Vaswani et al. 2017.
5. **Conformer** — Gulati et al. 2020. Convolution + attention; the backbone of most modern
   ASR encoders. Then **FastConformer** (NVIDIA) for the efficiency variant Parakeet uses.
6. **wav2vec 2.0** (Baevski 2020) and **HuBERT** (Hsu 2021). Self-supervised speech
   representation — why modern ASR needs less labeled data.
7. **Whisper** — Radford et al. 2022. Weak supervision at scale; also read the criticism of
   its hallucination behavior.
8. **Token-and-Duration Transducer (TDT)** — the decoding scheme in Parakeet TDT.

**Courses**
- **Stanford CS224S — Spoken Language Processing.** The closest thing to a course on
  exactly this project.
- **Stanford CS224N — NLP with Deep Learning.** Full lectures on YouTube. Do this if your
  transformer intuition is shaky.
- **CMU 11-785 Introduction to Deep Learning** — has unusually good sequence-modeling and
  ASR coverage; homeworks build a CTC recognizer.
- **University of Edinburgh ASR course** (Renals & Bell) — slides public, strongest
  treatment of the classical HMM/WFST material that everyone now skips and then regrets.

**Books**
- *Automatic Speech Recognition: A Deep Learning Approach* — Yu & Deng. The bridge from
  classical to neural.
- *Spoken Language Processing* — Huang, Acero, Hon. Dated (2001) and still the best
  systems-level treatment of a complete speech stack. Skim; reference.
- *Dive into Deep Learning* — [d2l.ai](https://d2l.ai/). Free, executable, excellent.

**Toolkits — learn by reading their source**
- **NVIDIA NeMo** — Parakeet/Canary live here; read the transducer decoding code
- **sherpa-onnx** (k2/Next-gen Kaldi) — the deployment path you'll likely use
- **faster-whisper** / **CTranslate2** — quantized inference done well
- **whisper.cpp / ggml** — read this to understand quantization concretely
- **ESPnet**, **icefall** — research-grade recipes when you need to train something
- **torchaudio**, **librosa** — everyday tooling

*Deliverable: you can read a Parakeet decoding trace and say why it produced a given token.*

---

## Block C — Making the text right (during Phase 2)

This block is the actual product differentiator and the least-taught material. It is mostly
papers, not courses.

**Contextual biasing** — the core of W3:
- [TurboBias 2.0: Streaming Context-Biasing for Production-Efficient ASR](https://arxiv.org/pdf/2608.21343) — start here, it's the closest to what you'll build
- [N-gram Boosting: Improving Contextual Biasing with Normalized N-gram Targets](https://arxiv.org/html/2308.02092)
- [Contextual Biasing for ASR in Speech LLM with Common Word Cues](https://arxiv.org/abs/2604.12398)
- [LOGIC: Efficient and Robust Contextual Biasing for Speech LLMs via Logit-Space Integration](https://arxiv.org/pdf/2601.15397)
- [Contextual Biasing for LLM-Based ASR with Hotword Retrieval and RL](https://arxiv.org/abs/2512.21828)

**Homophones and pronunciation-aware correction** — the core of §5.5:
- [PAC: Pronunciation-Aware Contextualized LLM-based ASR](https://arxiv.org/pdf/2509.12647)
- [Contextualized Speech Recognition: Rethinking Second-Pass Rescoring](https://www.ijcai.org/proceedings/2024/0716.pdf)
- Grapheme-to-phoneme: CMUdict, `g2p_en`, `phonemizer`/espeak-ng. Learn the IPA well enough
  to compute phoneme edit distances meaningfully.

**Text normalization**
- Jurafsky & Martin ch. on text normalization
- NeMo's WFST ITN grammars (Pynini) — read the source; the grammars are the documentation
- Sproat & Jaitly, *RNN Approaches to Text Normalization: A Challenge* (why the naive neural
  approach fails catastrophically and deterministic grammars survive)

**Streaming and latency**
- [Moonshine v2: Ergodic Streaming Encoder ASR](https://huggingface.co/papers/2602.12241)
- [Pushing the Limits of On-Device Streaming ASR (Microsoft)](https://arxiv.org/abs/2604.14493)
- [CUSIDE: Chunking, Simulating Future Context and Decoding](https://arxiv.org/pdf/2203.16758)
- Silero VAD — read the repo and the model card

**Accents and multilingual** — the core of W2:
- [Open ASR Leaderboard paper](https://arxiv.org/abs/2510.06961) — read the methodology
  section carefully; you're going to build something like this
- **EdAcc** (Edinburgh International Accents of English) — the dataset and its paper
- **Common Voice**, **FLEURS**, **ML-SUPERB** — coverage and their known biases
- Code-switching ASR literature (SEAME corpus work is the standard reference point)

---

## Block D — Systems and shipping (during Phase 3)

- *The Rust Programming Language* (the book) — free at [doc.rust-lang.org/book](https://doc.rust-lang.org/book/)
- ***Rust Atomics and Locks*** — Mara Bos. Free at [marabos.nl/atomics](https://marabos.nl/atomics/).
  Directly applicable: your lock-free audio ring buffer lives or dies on this material.
- **Ross Bencina, "Real-time audio programming 101: time waits for nothing"** — the single
  most useful article on why you must not allocate or lock on the audio thread. Read it
  before writing the capture code, not after.
- Win32: the WASAPI, UI Automation, and `SendInput`/UIPI documentation on Microsoft Learn.
  There is no book; the docs and other people's bug reports are the literature.
- Quantization: the ONNX Runtime and CTranslate2 quantization docs; `llama.cpp`'s GGUF
  quantization notes for the intuition.

---

## Block E — Strategy and product (continuous, ~10 hours total)

Short list on purpose. Reading more business books is a way to avoid talking to users.

- ***The Mom Test*** — Rob Fitzpatrick. Short, and the highest-ROI thing on this page. How
  to interview users without collecting flattering lies.
- ***Obviously Awesome*** — April Dunford. Positioning. Directly relevant to §4 of the
  strategy doc.
- *Crossing the Chasm* — Geoffrey Moore. Skim; the beachhead-market chapter is the point.
- Follow the **Open ASR Leaderboard**, **r/LocalLLaMA**, and the NeMo / sherpa-onnx release
  notes. In this field the literature that matters is 3 months old, not 3 years.

---

## A suggested weekly rhythm

- **~70% building**, ~30% studying. Adjust toward studying only when you're blocked by not
  understanding something, not by default.
- One paper per week, read properly (reimplement the core idea in a notebook if you can).
- Keep a `notes/` directory of what you learned and what it changed in the design. If a
  paper doesn't change a decision, you probably didn't need it yet.
