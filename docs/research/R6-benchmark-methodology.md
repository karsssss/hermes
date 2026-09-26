# R6 — Benchmark methodology & harness design

Research landed 2026-09-25. WebSearch budget was exhausted, so everything was verified by
direct fetch of primary sources. **Several items are explicitly unverified** and are marked
as such — they must be confirmed before anything is published.

## Licence findings — three traps

**1. GigaSpeech's "Apache 2.0" label is misleading.** The HF card says Apache 2.0, but the
actual terms of access require **non-commercial research and educational use only**, a
signed agreement, indemnification of SpeechColab/Tsinghua, and **explicitly bind
"for-profit employers"**. *(Verified by fetching the dataset card.)* **Unusable for our
public benchmark without written permission.**

**2. Common Voice has moved.** Mozilla's HF dataset page states Common Voice is now
**empty on HuggingFace and available exclusively through Mozilla Data Collective** as of
~Oct 2025. Current licence terms on the new platform could not be confirmed. **Do not
assume CC0 still applies.**

**3. TED-LIUM, CHiME, Earnings-21/22 licences could not be reached** this session. TED-LIUM
is widely reported as CC BY-NC-ND 3.0 — if true, **NC-ND disqualifies it** from a
commercial published comparison. CHiME-5/6 historically required a signed data-use
agreement for privacy-sensitive home recordings. **All three: verify before use.**

### Dataset table

| Dataset | Licence | Verified | Verdict for a published comparison |
|---|---|---|---|
| **EdAcc** — 40h, 62 speakers, 25 accent categories, 29 L1s | **CC BY-SA 4.0** | **Yes** | **Yes — our accent anchor.** Fully open. Already has a public leaderboard |
| LibriSpeech — ~1000h read audiobook | CC BY 4.0 | Yes | Sanity check only. **Heavy contamination risk** — nearly every model trained on it |
| AMI — 100h meetings | CC BY 4.0 | Yes | Usable; meeting/overlap domain, not accent-stratified |
| FLEURS — 102 languages, ~12h each | CC BY 4.0 | Yes | Fine, but *different languages*, not different English accents |
| ML-SUPERB — 143 languages | CC BY 4.0 | Yes | Same caveat as FLEURS |
| Common Voice | **Re-verify** | Partial | Blocked pending Mozilla Data Collective terms |
| TED-LIUM 3 | Reported CC BY-NC-ND 3.0 | **No** | **Blocked** — NC-ND would disqualify |
| CHiME 5/6/7/8 | Unclear, likely DUA | **No** | **Blocked** |
| Earnings-21/22 — 39h / 119h accented business calls | Unconfirmed | Size only | Promising for accented conversational speech; **licence unconfirmed** |
| GigaSpeech — 10,000h | **Non-commercial in practice** | Yes | **Blocked** |
| SEAME — 192h Mandarin-English code-switching | LDC paid, membership-gated | Yes | Not free, not redistributable, and wrong language pair |

**No Slavic-English code-switching corpus exists that the researcher could find.** This
matches the field's known gap outside Mandarin/Spanish/Hindi-English. *Caveat: WebSearch
was unavailable, so this is "not found", not "confirmed absent" — redo the search.*
**Working conclusion: budget to collect our own**, even 1–2 hours from a few dozen
bilingual speakers, and **say so explicitly in the published methodology** rather than
silently omitting the pair.

## Normalization — the biggest source of misleading numbers

Whisper's `EnglishTextNormalizer` (source read directly) lowercases, strips **all**
punctuation, removes fillers, expands contractions and honorifics, converts spelled-out
numbers to digits, and normalizes British/American spelling. **Published Whisper WER is
therefore computed on text with casing, punctuation, fillers, and spelling variance all
erased.**

Stated plainly: *papers reporting "Whisper achieves X% WER" using Whisper's own normalizer
are grading Whisper's output with an eraser Whisper co-designed.* A non-Whisper model
scored with a different normalizer looks artificially worse. **This is the single biggest
gaming vector in ASR benchmarking**, and it is exactly the dimension our product cares
about.

**There is no single canonical "formatted WER" metric in the field.** The closest existing
convention is NVIDIA's **"WER with PnC" vs "WER no-PnC"** pairing *(unverified — could not
fetch a NeMo model card to confirm the label)*. Punctuation is normally scored separately
as per-class F1, in the punctuation-restoration literature rather than the ASR literature.
ITN has its own class-based WER / slot-error-rate tradition.

**Recommendation:** stop hunting for a pre-existing name. Publish **F-WER as the headline**
(raw, case- and punctuation-sensitive, on the literal text injected into the target app),
and **decompose it for diagnosis**: casing error rate (WER delta raw vs lowercased),
punctuation F1 per class, and ITN slot error rate on a curated set of ITN-triggering
utterances. Disclosing the decomposition makes it *harder to game than either existing
convention*, which is the defensible position for a public benchmark.

Also vendor the Whisper normalizer, version-pinned, to publish a secondary
"legacy-comparable" score alongside — so readers can map our numbers onto the ones they
already know.

## Statistics — the CI decision rule

**Detectability at n=200 is worse than intuition suggests: roughly 1–3 absolute percentage
points.** Treat any claimed win below ~0.5pp on a 200-utterance set as noise unless a
bootstrap CI says otherwise. Use the full set (thousands of utterances) for anything
published; the 200-utterance canary is for CI gating only.

**The rule, to encode in `run_ci_gate.py`:**

1. Compute WER **per utterance**, not per word — this is what makes pairing valid.
2. **Paired utterance-level bootstrap**: resample N utterances with replacement ≥2000 times,
   compute ΔF-WER each time, take 2.5/97.5 percentiles. **Fix and record the RNG seed.**
3. A change counts as an **improvement** only if: the 95% CI excludes zero in the improving
   direction, **and** the point estimate is ≥ **0.3–0.5pp absolute F-WER**, **and**
   **E-WER does not regress** beyond its own noise floor, **and** latency p95 stays within
   its absolute budget.
4. Latency p95 is a **hard SLA gate, not a statistical question** — it is a UX requirement.

The E-WER guard is the TARQ-motivated one (R1): an aggregate win can hide rare-word damage.

Standard references: NIST SCTK's `sc_stats` implements the **Matched Pair Sentence Segment
(Word Error) test** *(verified in the repo)*. Gillick & Cox 1989 (MAPSSWE) and Bisani & Ney
2004 (bootstrap CIs) are the classical citations but **could not be verified this session** —
confirm venue/year before citing publicly.

## Benchmarking closed competitors

**No ToS found that explicitly bans publishing benchmark results.** Wispr Flow and
Superwhisper both ban reverse engineering; Microsoft's MSA bans disassembly. None mentions
benchmarking. *This is encouraging, not legal clearance* — vendors reserve termination
rights, so an unhappy vendor could still cut off access.

**One genuine grey area:** Superwhisper's ToS states *"You may not access the Backend
Services through any automated, scripted, programmatic, or bulk method."* If their
transcription is cloud-backed, a tight automated loop could be read as covered.
**Mitigation: keep volume at interactive-equivalent levels and use a human-triggered
semi-manual harness rather than a tight loop.**

**Mechanism:** **VB-Audio Virtual Cable** — play the benchmark WAV to "CABLE Input", set
"CABLE Output" as the app's microphone. Standard, well-established. Note you **cannot feed
faster than real time** into a live-mic app, which is actually a feature: it forces honest
streaming-speed testing.

**Hazards to record per run:** each app applies its own casing/punctuation/ITN (that is
what we want to measure — never "fix" their output before scoring); default settings must
be locked and recorded; and the sharpest one — **a cloud competitor can silently swap
server-side models with zero client version bump.** Date every run and publish closed
competitor numbers explicitly as *a snapshot in time, not a permanent claim*. Their latency
numbers also deserve visibly wider error bars than our own instrumented pipeline's.

## Resource measurement on Windows

- **GPU:** `nvidia-smi --query-gpu=utilization.gpu,memory.used,power.draw --format=csv -l 1`.
  NVML underneath. Simple, scriptable, no extra privileges.
- **CPU/RAM:** PowerShell `Get-Counter` against `\Process(<name>)\% Processor Time`,
  `\Process(<name>)\Working Set`, and `\GPU Engine(*)\Utilization Percentage` — the last
  gives vendor-neutral per-process GPU use.
- **ETW + WPR/WPA** only for one-off deep investigation ("why is idle CPU 3% not 0.1%").
  Overkill for CI.
- **Trustworthy idle CPU:** a single sample is worthless. Run the service alone with no
  audio for **≥5 minutes**, sample every 1 s, **discard the first 30 s** (JIT/startup
  settling), report **median and p95, never mean**, after a cold boot with Defender not
  actively scanning — and note it if you could not control for that.
- **Cold vs warm start:** to measure genuine cold start you must evict the file cache —
  reboot, or flush the standby list. **Always report both, explicitly labelled.** The gap
  is large for multi-hundred-MB models and omitting it is a classic misleading benchmark.

## Anti-patterns to avoid (and to call out in the published report)

- **Contamination** — LibriSpeech and Common Voice are almost certainly in the pretraining
  data of every modern model. Even EdAcc has a public leaderboard, so rotate in fresh
  held-out audio periodically.
- **Cherry-picked normalization** — the most common way "our WER beats theirs" gets
  discredited. Same scoring code path, checked in, version-pinned.
- **Unreported decoding params** — beam size, chunk size, LM weight each swing WER by points.
- **Batch-vs-streaming conflation** — leaderboard RTFx from large-batch offline decoding says
  nothing about a real-time single-stream desktop app. (Compounds the R4 finding that Open
  ASR Leaderboard RTFx is measured on an H200.)
- **Ignoring cold start.**
- **Comparing quantized against unquantized without saying so.**
- **Evaluating on read speech, claiming conversational performance** — dictation is closer
  to spontaneous monologue than to read audiobook speech. Weight EdAcc and
  Earnings-style sets above LibriSpeech in any headline claim.

## Harness design — a harness, not a framework

Flat files in git, one Python process, no database, no web server. Everything a reviewer
needs to judge a regression must be visible in a text diff.

```
bench/
  adapters/       base.py (ASRAdapter protocol), hermes, whisper (sanity baseline),
                  wispr_flow / superwhisper / windows_dictation (semi-manual, VAC)
  datasets/       manifest_schema.json, <name>/prepare.py + manifest.jsonl,
                  LICENSES/ (verbatim copy per dataset), accent_strata.json
  normalization/  raw.py (identity, for F-WER), whisper_english.py (vendored, pinned,
                  for a legacy-comparable secondary score), components.py
  metrics/        align.py, wer.py (f_wer, e_wer), stability.py (UPWR/UPSR),
                  latency.py, bootstrap.py
  resource/       sample_windows.ps1, parse_resource.py
  runners/        run_eval.py, run_ci_gate.py
  reports/<run_id>/  run.json, predictions.jsonl, per_utterance.jsonl,
                     summary.md, summary.json
  ci/             baseline/<dataset>/<engine>/summary.json, canary_manifest.jsonl
```

### The RUN record — what must be captured

`run_id`, UTC timestamp, **git SHA + dirty flag**; engine name/version, **model id +
weights SHA-256**, quantization method and bits, **full decoding params** (beam, chunk_ms,
lookahead_ms, lm_weight), adapter type; hardware; **OS build + NVIDIA driver + audio
driver**; software env including **thread count**; dataset name, **manifest commit**,
licence, n utterances, accent stratum; audio pipeline (sample rate, capture method, VAC
device); normalization mode; entity-list version hash; **bootstrap seed**; all metrics;
and `manual_steps_log` — **required** for semi-manual adapters.

### Adapter interface

```python
class ASRAdapter(Protocol):
    name: str
    def load(self, config: dict) -> None: ...
    def transcribe_stream(self, audio_path: Path,
                          emit_partial: Callable[[PartialHypothesis], None]) -> FinalTranscript: ...
    def describe_env(self) -> dict: ...   # resolved model hash, decoding params, version
```

Native adapters emit true partial timestamps for UPWR/UPSR. Semi-manual adapters implement
the same interface but route audio through VB-Cable at real-time speed, trigger the app's
hotkey, and poll a text sink via UI Automation/clipboard with timestamps — **tag those
traces `low_confidence_timing: true`** and log the operator's setup confirmation.

### Reports and CI

`summary.md` is a fixed-order Markdown table (no dynamic ordering, no HTML) so `git diff`
shows exactly which cells moved. `summary.json` uses sorted keys and stable formatting.
**`per_utterance.jsonl`, sorted by id, lets a reviewer see *which* utterances regressed** —
addressing the "aggregate hides rare-word damage" concern at review level, not just via
E-WER.

**Per-PR:** ~100–200-utterance canary, native adapter only, apply the decision rule above.
**Baselines are updated only by an explicit reviewed PR, never silently by CI.**
**Nightly:** full EdAcc + stratified slices, native only.
**Closed competitors: never in automated CI** — manual, dated, human-operated, published as
periodic snapshots.

### Explicitly out of scope for v0

No web dashboard, no database, no parallel execution, no plugin auto-discovery, no
cross-OS support, no statistics beyond paired bootstrap, no automatic accent-label
inference (strata come from a hand-curated checked-in map). UPWR/UPSR for closed
competitors may be deferred if UI-Automation partial capture proves too noisy.

## Must resolve before publishing

1. TED-LIUM 3, CHiME, Earnings-21/22 licences.
2. Common Voice terms post-migration.
3. GigaSpeech — treat as unusable absent written permission.
4. Redo the Slavic-English code-switching corpus search once search quota resets.
5. Confirm Gillick & Cox 1989 and Bisani & Ney 2004 citation details.
6. Confirm whether Open ASR Leaderboard and NeMo actually apply the Whisper normalizer.
7. Redo the search for 2025–2026 accent benchmarks (none found, but search was unavailable).
8. Legal review of Superwhisper's automated-access clause if we publish against it.

## Sources

[Open ASR Leaderboard 2510.06961](https://arxiv.org/abs/2510.06961) ·
[UPWR/UPSR 2006.01416](https://arxiv.org/abs/2006.01416) ·
[TARQ 2605.27808](https://arxiv.org/abs/2605.27808) ·
[Whisper normalizers](https://github.com/openai/whisper/blob/main/whisper/normalizers/english.py) ·
[EdAcc](https://huggingface.co/datasets/edinburghcstr/edacc) ·
[Common Voice migration notice](https://huggingface.co/datasets/mozilla-foundation/common_voice_17_0) ·
[FLEURS 2205.12446](https://arxiv.org/abs/2205.12446) ·
[ML-SUPERB 2305.10615](https://arxiv.org/abs/2305.10615) ·
[LibriSpeech](https://www.openslr.org/12/) ·
[AMI](https://groups.inf.ed.ac.uk/ami/corpus/) ·
[GigaSpeech](https://huggingface.co/datasets/speechcolab/gigaspeech) ·
[SEAME LDC2015S04](https://catalog.ldc.upenn.edu/LDC2015S04) ·
[Earnings datasets](https://github.com/revdotcom/speech-datasets) ·
[NIST SCTK](https://github.com/usnistgov/SCTK) ·
[NVML](https://docs.nvidia.com/deploy/nvml-api/index.html) ·
[VB-Audio Cable](https://vb-audio.com/Cable/) ·
[Wispr Flow ToS](https://www.wisprflow.ai/terms) ·
[Superwhisper ToS](https://superwhisper.com/terms)
