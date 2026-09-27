# Licences — Public Proxy Evaluation Set v1

Verified 2026-09-26 against the live sources, not against secondary summaries. Where a
licence was a PDF (Golos) it was extracted and read; where a repository's licence file
turned out to cover only part of the artefact (Earnings-22) that is recorded as the reason
for rejection.

**No third-party audio is redistributed from this repository.** `eval/datasets/**/audio/`
and `*.wav` are gitignored, and `hermes-eval build-dataset` reproduces the audio locally
from pinned revisions. That is deliberate: two of the four corpora carry ShareAlike, so
derived audio would be Adapted Material with obligations attached. Shipping a manifest and
a fetcher sidesteps the question entirely while still reproducing byte-identical inputs —
every record carries the sha256 of the exact 16 kHz WAV it was scored on.

## Accepted

| Corpus | Revision | Licence | Commercial | Obligations |
|---|---|---|---|---|
| **EdAcc** `edinburghcstr/edacc` | `d9ae7bd3` | CC BY-SA 4.0 | Yes | Attribution + **ShareAlike** on adapted material |
| **LibriSpeech** test-clean `openslr/librispeech_asr` | `71cacbfb` | CC BY 4.0 | Yes | Attribution |
| **RuLS** `istupakov/russian_librispeech` | `a519c986` | CC BY 4.0 (mirror); upstream OpenSLR 96 states "Public Domain in the USA" | Yes | Attribution to both NVIDIA/OpenSLR and the mirror |
| **Golos** crowd + farfield (`bond005/…`) | `e634b6b8`, `c93949f7` | **Golos Public License** | Yes | Attribution + **ShareAlike**; see below |
| **OpenSLR 28** RIRS_NOISES | n/a (static zip, 1 311 166 223 bytes) | Apache-2.0 | Yes | Notice |
| **MUSAN** (via OpenSLR 28 `pointsource_noises/`) | n/a | CC BY 4.0 | Yes | Attribution |

### The Golos licence, read in full

Golos ships `license/en_us.pdf`, not an SPDX identifier, and the PDF's own first footnote
says: *"This license is not a Creative Commons license. The text of this license is a
reworking of a Creative Commons Corporation (Attribution-ShareAlike 4.0) license."*

What it actually grants (§2(a)(1)): a **worldwide, royalty-free, non-sublicensable,
non-exclusive, irrevocable** licence to reproduce and make available the Licensed Material
and to create Adapted Material. Conditions: attribution (§3(a)), and Adapted Material must
be released under a licence with the same License Elements or a BY-SA-compatible one
(§3(b)(1)). Sui generis database rights are handled under the Civil Code of the Russian
Federation (§1(k), §4). Termination is automatic on breach with a 30-day cure (§6).

**There is no non-commercial clause.** The earlier working assumption — inherited from the
"unverified terms" row in `docs/SYNTHESIS.md` §14 — was more pessimistic than the text.

One practical consequence: Golos publishes **no speaker identity at all**. Its crowd data
comes from anonymous Toloka workers. Speaker-disjoint sampling is therefore impossible on
Golos by construction, and the manifest records `speaker_id: null` rather than pretending
otherwise.

### RuLS provenance note

Upstream RuLS (OpenSLR 96, created by NVIDIA from LibriVox public-domain audiobooks)
states "Public Domain in the USA". The Hugging Face mirror used here declares CC BY 4.0.
Both are permissive and the stricter of the two is assumed; attribute both.

Use the `text` column only. The mirror's `text_no_preprocessing` column — the one that
would have carried casing and punctuation — is **mojibake-corrupted** on Cyrillic
sentence-initial characters (`Рукою` → `\xa0укою`, reproduced on at least two sampled
rows). It is unusable as a formatted reference.

## Rejected, and why

| Candidate | Status | Reason |
|---|---|---|
| **Mozilla Common Voice** | **Rejected on access, not licence** | Still CC0. But effective **October 2025** the Hugging Face repositories were emptied (`mozilla-foundation/common_voice_17_0` now contains only `README.md` and `.gitattributes`) and distribution is exclusively via **Mozilla Data Collective**, which requires an account and per-dataset terms acceptance before download, and asks that datasets not be mirrored. There is a REST API, but it is authenticated. A set that cannot be rebuilt by `build-dataset` from a pinned revision is not reproducible, so Common Voice is out of v1. |
| **MUSAN** (direct) | Rejected on access | `musan.tar.gz` is 11 GB, monolithic, and gzip is not seekable, so there is no subset access. Superseded: OpenSLR 28's `pointsource_noises/noise-free-sound-*.wav` **are** the MUSAN free-sound clips, reachable by HTTP Range inside a 1.3 GB ZIP. |
| **CS-FLEURS** (`byan/cs-fleurs`) | Rejected twice over | Licence is **CC BY-NC 4.0** — non-commercial, the same trap that made GigaSpeech unusable. And the `rus`/`ukr` English pairs exist **only in the `mms` subset, which is concatenative TTS**. The `read` subset (real human speech, 14 pairs) does include `rus`, but not `ukr`. Synthetic code-switch audio is explicitly not an acceptable substitute here. |
| **Earnings-22** | Rejected on unclear terms | `earnings22/LICENSE.md` in `revdotcom/speech-datasets` covers "the transcripts and associated text files that are used for alignment" under CC BY-SA 4.0. **The audio licence is not stated anywhere in the repository.** This was the strongest candidate for a technical/domain-vocabulary subset; it fails the "reject unless terms are clear" rule. |
| **GigaSpeech** | Rejected (pre-existing finding) | Apache-2.0 label is misleading; actual terms are non-commercial and bind for-profit employers. |
| **TED-LIUM 3** | Rejected | CC BY-NC-ND 3.0 — non-commercial *and* no-derivatives, which rules out even the resampling this harness does. |
| **SPGISpeech** | Rejected | Requires a signed user agreement; not redistributable and not scriptable. |
| **FLEURS** | Deferred, not rejected | CC BY 4.0, ungated, and its `raw_transcription` field is the only **formatted** reference found anywhere in the candidate pool — real casing, punctuation and digits, in both `en_us` and `ru_ru`. It is deferred only on fetch cost: its parquet row groups exceed the datasets-server scan limit, so audio must come from the per-language tarballs (`en_us/test.tar.gz` 290 MB, `ru_ru/test.tar.gz` 433 MB). See `COVERAGE.md` for why this is the highest-value v2 addition. |

## Attribution block

Any published result over this set must carry:

> Evaluated on the Hermes Public Proxy Set v1, derived from: the Edinburgh International
> Accents of English Corpus (Sanabria et al., ICASSP 2023), CC BY-SA 4.0; LibriSpeech
> (Panayotov et al., ICASSP 2015), CC BY 4.0; Russian LibriSpeech (NVIDIA, OpenSLR 96),
> public domain, via the `istupakov/russian_librispeech` mirror (CC BY 4.0); Golos (Karpov
> et al., Interspeech 2021, SberDevices), Golos Public License; the Room Impulse Response
> and Noise Database (OpenSLR 28), Apache-2.0; and MUSAN (Snyder et al., 2015), CC BY 4.0.
> No audio from these corpora is redistributed.
