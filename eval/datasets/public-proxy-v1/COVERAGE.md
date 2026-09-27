# Coverage — Public Proxy Evaluation Set v1

Built 2026-09-27. 160 records, 17.6 minutes of audio; 120 clean records (12.9 minutes) plus
40 perturbed copies of 20 of them. Manifest sha256 prefix `2b3a46ede2700f30`.

The build is reproducible: deleting `manifest.jsonl` and `audio/` and re-running
`build-dataset` reproduces a **byte-identical** manifest and byte-identical WAVs.

## What is in it

| Subset | Source | n | Speakers | Audio | Median utt | Reference style | Category |
|---|---|---:|---:|---:|---:|---|---|
| `accented_en` | EdAcc test, L1 ≠ English | 50 | 25 | 6.1 min | 6.6 s | `caps_nopunct` | `prose` |
| `general_en` | LibriSpeech test-clean | 30 | 30 | 3.6 min | 7.0 s | `caps_nopunct` | `prose` |
| `ru_clean` | RuLS test | 20 | 7 | 2.1 min | 5.6 s | `lower_nopunct` | `prose` |
| `ru_command` | Golos crowd test | 10 | **none published** | 0.7 min | 3.7 s | `lower_nopunct` | `command` |
| `ru_farfield` | Golos farfield test | 10 | **none published** | 0.4 min | 2.6 s | `lower_nopunct` | `command` |
| `robust_noise` | derived, 10 dB SNR | 20 | 20 | 2.4 min | 5.4 s | inherited | inherited |
| `robust_reverb` | derived, simulated RIR | 20 | 20 | 2.4 min | 5.4 s | inherited | inherited |

Sampling drew 63 EdAcc candidates to accept 50, 31 LibriSpeech to accept 30, and hit quota
for the rest exactly. No build warnings. `build.json` carries the full rejection breakdown.

### Accent coverage — the W2 axis

`accented_en` spans **16 distinct L1 backgrounds** out of the 17 non-English L1s available
in EdAcc's test split, across 25 of its 60 speakers, capped at 3 utterances per speaker and
8 per L1:

| L1 | n | | L1 | n | | L1 | n |
|---|---:|---|---|---:|---|---|---:|
| Lithuanian | 8 | | Italian | 3 | | Indonesian | 2 |
| Vietnamese | 8 | | Bulgarian | 2 | | Sinhalese | 1 |
| Spanish | 7 | | Romanian | 2 | | French | 1 |
| Urdu | 4 | | Tagalog | 2 | | Spanish (Mexican) | 1 |
| Hindi | 3 | | Mandarin | 2 | | Filipino | 1 |
| Hebrew | 3 | | | | | | |

**The target user's own L1 background — Ukrainian or Russian — is not in this list.** EdAcc's
test split has no Ukrainian or Russian L1 speakers. The nearest neighbours are the Slavic and
Baltic entries (Bulgarian, Lithuanian) plus the corpus' own catch-all "Eastern European"
accent label. This is a proxy for the target accent, not a measurement of it.

### Robustness

Both conditions use the **same 20 source utterances** (14 with speaker identity across
EdAcc/LibriSpeech, 6 from Golos/RuLS), so noise, reverb and clean are all directly
comparable on identical speech. Noise clips are MUSAN free-sound recordings reached through
OpenSLR 28; RIRs are simulated small and medium rooms from the same archive.

## What is *not* in it

This is the important half of the table.

| Target behaviour | Status | Why |
|---|---|---|
| **F-WER** — the headline metric | **Unmeasurable** | No public corpus in scope ships a formatted reference. Every record is `caps_nopunct` or `lower_nopunct`. A run over this manifest reports an `fwer` figure; it is an artefact of reference formatting, not a measurement. |
| **Casing error rate, punctuation F1** | **Unmeasurable** | Same cause. The decomposition has nothing to decompose. |
| **E-WER** — the rare-word guard | **Unmeasurable** | Needs annotated entity spans. No public corpus annotates them, and inventing spans would fabricate the very guard meant to catch rare-word damage. `entities` is empty on all 160 records. |
| **ITN slot error rate** | **Unmeasurable** | Needs utterances whose references contain digits, dates and units. These corpora spell numbers out (`SATURDAY AUGUST FIFTEENTH`), which is the inverse of what ITN produces. |
| **Dev-speak** — identifiers, CLI, paths | **Absent** | No defensible public source found. Earnings-22 was the closest candidate for dense domain vocabulary and was rejected because its audio licence is unstated. SPGISpeech needs a signed agreement; GigaSpeech and TED-LIUM are non-commercial. |
| **Russian–English code-switching** | **Absent** | CS-FLEURS has a `cs_rus_eng` pair, but only in its `mms` subset, which is **concatenative TTS**; its real-human `read` subset covers `rus` but the whole dataset is CC BY-NC 4.0. Synthetic code-switch audio is not an acceptable substitute. |
| **Ukrainian–English code-switching** | **Absent, and harder** | CS-FLEURS' `cs_ukr_eng` exists **only** in the TTS `mms` subset. No corpus of real Ukrainian–English code-switched speech was found at all. This confirms `SYNTHESIS.md` risk #7 rather than resolving it. |
| **Russian spontaneous conversation** | **Absent** | Golos is not conversational — crowd is read short phrases from Toloka workers, farfield is smart-speaker commands (`салют продолжить`). Labelling it `ru_command`/`ru_farfield` rather than "Russian conversational" is deliberate. |
| **The real microphone and room** | **Absent** | EdAcc is video-call audio, LibriSpeech and RuLS are audiobooks, Golos is a smart-speaker array. None is a desk microphone in the developer's room. The synthetic noise and reverb approximate an *effect*, not this environment. |
| **Pre-roll clipping, endpointing, latency** | **Absent** | These are properties of the capture path, not of a file. Nothing file-based can measure them. |
| **Partial-hypothesis stability (UPWR/UPSR)** | **Absent** | Needs a backend emitting partials; already deferred in `docs/CURRENT.md`. |

## Recommendations

### A. Suitable for evaluation only

**All seven subsets.** Every record in this set is evaluation-only, and should stay that way
for two independent reasons: the speakers are reserved as an evaluation pool (below), and
two of the source corpora carry ShareAlike, which would attach obligations to a model or
dataset derived from them if that derivative were distributed.

Within that, read them differently:

- `accented_en` is the only subset that speaks to a differentiator (W2). Treat it as the
  primary signal.
- `general_en` is a **sanity check, not a result.** LibriSpeech test-clean is saturated;
  a number on it confirms the pipeline runs, and little else.
- `ru_clean` is read literary Russian from seven readers. Useful for a coarse Russian WER;
  too narrow and too few speakers for a published claim.
- `ru_command` and `ru_farfield` are small (10 each) and short. They are indicative only —
  at that size the confidence interval will swallow most differences.
- `robust_noise` / `robust_reverb` are only meaningful as a **paired delta against their own
  clean originals**. The absolute number on them means nothing.

Two standing rules: **no speaker in this set may ever enter a training pool** (every record
carries `provenance.speaker_id` so the claim stays checkable), and **EdAcc's validation split
stays reserved** — only `test` is sampled, so validation remains available as a genuinely
unseen second set.

### B. Could later be used for training or fine-tuning

| Corpus | Training-eligible portion | Caveat |
|---|---|---|
| **LibriSpeech** train-clean-100/360, train-other-500 | ~960 h | CC BY 4.0, speaker-disjoint from test-clean by construction. Saturated and register-mismatched (read audiobooks), so useful for warm-up, not for the differentiators. |
| **RuLS** train | ~95 h, 5 readers | Public domain / CC BY 4.0. Reader-disjoint from test — **verified** in `CHAPTERS_READERS.TXT`. Five readers is very little speaker diversity. |
| **Golos** train | ~1 227 h (crowd 1 095 h + farfield 132 h) | Licence permits it — no non-commercial clause. But ShareAlike: a distributed model or dataset derived from it inherits obligations, which needs a legal read **before** any fine-tune, not after. And with no speaker IDs, train/eval speaker overlap is unverifiable, so any Golos-trained model must not be evaluated on `ru_command`/`ru_farfield`. |
| **Common Voice** | ~30 000 h, CC0 | The cleanest licence in the whole field for training. Blocked only on access: account plus terms acceptance at Mozilla Data Collective. Worth doing manually when training becomes real. |
| **MUSAN** / **OpenSLR 28** | augmentation material | CC BY 4.0 / Apache-2.0. Standard, safe, already wired into the build. |
| **EdAcc** | **No.** | It is an evaluation corpus, it is small (~40 h), and training on it would destroy the one accent measurement available. |

None of this changes the standing position: **no training or fine-tuning in Phase 0.** This
table exists so that when the question arrives, the licence work is already done.

### C. Target behaviours that remain unmeasured

In rough order of how much they matter to Hermes:

1. **Every formatting-dependent metric** — F-WER, casing, punctuation, ITN. These are the
   product's headline and its three diagnostic decompositions, and this set reaches none of
   them. **Nothing published from this set may be called F-WER.**
2. **Dev-speak accuracy (W3).** The differentiator most likely to decide whether the product
   is useful, with zero public coverage.
3. **Slavic–English code-switching (W2's hard half).** Absent, and — now verified twice — not
   available anywhere in real recorded form for Ukrainian–English.
4. **Confidence calibration on accented and code-switched speech.** This set could support the
   accented half once a backend emits confidences, and cannot support the code-switched half
   at all. It remains `SYNTHESIS.md` risk #2.
5. **The developer's own voice, microphone, room and applications** — i.e. the entire
   real-use distribution. Task 1b is not retired by this set and should still be the next
   thing recorded.
6. **Everything about the capture path**: pre-roll, endpointing, injection, end-to-end
   latency, catastrophic rate.

### The single highest-value v2 addition

**FLEURS `en_us` + `ru_ru`.** Its `raw_transcription` field is the only **formatted**
reference found in the entire candidate pool — real casing, punctuation and digits, in both
languages — under CC BY 4.0, ungated, real human speech. Adding ~20 utterances from it would
restore F-WER, punctuation F1, casing error rate and ITN slot measurement to the public set,
turning it from a WER-only proxy into something that exercises the actual headline metric.

It was deferred on fetch mechanics, not on licence: its parquet row groups exceed the
datasets-server scan limit, so audio has to come from the per-language test tarballs
(`en_us/test.tar.gz` 290 MB, `ru_ru/test.tar.gz` 433 MB). That is a second fetch backend,
which is a day of work, not a research question.
