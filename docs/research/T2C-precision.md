# T2C — Parakeet INT8 vs FP32: the precision gate

Status: **complete**, 2026-10-06. Phase 0, Task 2c. **Verdict: FP32 PREFERRED** (§7).

**The question.** Does FP32 provide enough quality or stability benefit to justify its
additional memory and runtime cost over INT8 for Phase 1?

**Scope.** Two representations of one model, nothing else varied:

| | INT8 (Tasks 2a/2b) | FP32 |
|---|---|---|
| source | HF `csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8` (= GitHub `asr-models` tarball) | HF `csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3` @ `1a468a35` |
| files | `encoder/decoder/joiner.int8.onnx` | `encoder.onnx` + `encoder.weights` (external data), `decoder.onnx`, `joiner.onnx` |
| on disk | 670 MB | 2550 MB (3.8×) |
| `tokens.txt` | byte-identical between the two | |

Same exporter, same day (2025-08-16). Local INT8 files are byte-identical to the HF int8
repo; every FP32 file matches its HF LFS sha256. Held identical: Public Proxy v1 audio
(n=160, manifest `2b3a46ed…d7053e`), sherpa-onnx 1.13.8 features and `greedy_search` TDT
decoder, ORT 1.28.0 CPU EP, 4 threads, `basic`-normalized WER scoring. **WER, not F-WER** —
the proxy set has no formatted reference. No other models, datasets, fine-tuning or GPU EPs.

**Run.** `eval/runs/20261006T055203Z-t2c-parakeet-int8-vs-fp32-01d0`, one sitting.

```
uv run --group asr python -m hermes_eval.t2c collect    # ~95 min
uv run python -m hermes_eval.t2c analyze <run-dir>       # analysis.json
```

## 1. Method

Four **arm processes** in ABAB order — int8-p1, fp32-p1, int8-p2, fp32-p2 — each a fresh
interpreter, so load time and peak working set belong to one representation, and system
drift lands on both arms. Each process builds the sherpa recognizer (timed), warms it twice
on Task 2a's synthetic signal, and decodes all 160 rows in manifest order (the only timed
pass). Pass-1 processes then decode two perturbations of every row and finally release
sherpa and run Task 2b's direct-ORT probe greedy over the same files. Peak working set is read
after the timed pass, before anything else loads.

Perturbations, identical for both arms: **dither** — N(0, 1 LSB) added to the waveform,
seeded per utterance, inaudible; **shift5ms** — drop the first 80 samples, moving the 10 ms
frame grid by half a hop (what a different hotkey instant does to the same speech).

Statistics: paired utterance-level bootstrap, 2000 resamples, seed 20260926. Confidence is
sherpa's emitted-token probability only (`ys_log_probs`, word = min over tokens), as D-0014
fixed it; the two arms' hypotheses differ, so AUROC deltas are paired by utterance resample,
not by word.

## 2. Quality — WER %, Δ = FP32 − INT8

| slice | n | INT8 | FP32 | Δ pp [95% CI] | |
|---|---:|---:|---:|---:|---|
| **overall** | 160 | 13.29 | **10.72** | **−2.57 [−3.94, −1.32]** | real |
| language=en | 112 | 12.79 | 10.77 | −2.02 [−3.46, −0.78] | real |
| language=ru | 48 | 15.75 | 10.50 | −5.25 [−9.13, −1.34] | real |
| accented_en | 50 | 18.74 | 16.99 | −1.74 [−4.01, +0.34] | not resolved |
| general_en | 30 | 1.81 | 1.81 | 0.00 [−0.45, +0.51] | tie |
| ru_clean | 20 | 13.41 | 9.35 | −4.07 [−8.17, −0.72] | real |
| ru_command | 10 | 3.08 | 0.00 | −3.08 [−8.57, 0.00] | thin |
| ru_farfield | 10 | 37.78 | 33.33 | −4.44 [−24.4, +21.6] | uninformative |
| robust_noise | 20 | 18.42 | 11.70 | −6.73 [−12.98, −1.97] | real |
| robust_reverb | 20 | 12.57 | 8.77 | −3.80 [−7.48, −1.12] | real |

- **FP32 is 2.57 pp better overall (≈19% relative), CI clear of zero.** It is never worse
  on any slice. Clean read English is a tie; the gain concentrates where the signal is
  degraded — noise (−6.7), Russian (−5.3), reverb (−3.8).
- INT8 reproduces Task 2a exactly (13.294%). Empty outputs: INT8 2/160, FP32 **0**/160.
- **accented_en, the W2 core, points the same way but is not resolved** (CI touches +0.34).
- The two representations give identical raw text on only 57/160 utterances (81 after
  normalization): int8 quantization changes the transcript on half the corpus.

## 3. Stability

### 3.1 Repeated identical runs (separate processes, ABAB)

Both arms: **160/160 texts identical, `ys_log_probs` bit-identical on 160/160**, max |Δ| 0.0.
Neither representation is non-deterministic. What follows is input sensitivity, not noise.

### 3.2 sherpa vs direct ORT (same algorithm, features differing only in reduction order)

| | INT8 | FP32 |
|---|---:|---:|
| greedy text identical | 127/160 | **159/160** |
| WER Δ probe − sherpa, pp | −0.31 [−0.71, +0.11] | −0.08 [−0.24, 0.00] |
| emitted log-prob \|Δ\| on identical texts, median / p95 / max (nats) | 0.0002 / 0.055 / 0.75 | **0.0 / 0.0 / 0.00035** |

INT8 reproduces Task 2b's parity numbers exactly. **FP32 closes it:** float32 reduction-order
noise no longer changes the transcript (1 divergence in 160) and the log-probs agree to
3.5e-4 nats at worst. Open question #17's hypothesis — that dynamic int8 activation
quantization amplifies sub-ULP input noise into argmax flips — is confirmed.

### 3.3 Controlled perturbations

| | INT8 changed (raw / norm) | FP32 changed (raw / norm) | words changed INT8 / FP32 | flip-rate Δ FP32−INT8 (norm), pp [CI] |
|---|---:|---:|---:|---:|
| dither (1 LSB) | 38 / 30 | **12 / 8** | 46 / 12 | **−13.8 [−20.6, −7.5]** |
| shift 5 ms | 51 / 45 | 38 / 34 | 80 / 64 | −6.9 [−14.4, +0.6] |

WER moves by noise in every case (|Δ| ≤ 0.31 pp, all CIs straddle zero) — perturbations
reshuffle errors, they don't add them. **Inaudible dither changes 19% of INT8 transcripts and
5% of FP32's**, CI clear. The frame-grid shift is a larger, real change of input and moves
both a lot; FP32 is fewer, but not resolved.

## 4. Confidence — sherpa emitted-token probability

| slice | utts | INT8 AUROC [CI] | FP32 AUROC [CI] | Δ AUROC [CI] | Δ AP [CI] |
|---|---:|---:|---:|---:|---:|
| overall | 160 | 0.884 [0.855, 0.908] | 0.892 [0.862, 0.917] | +0.008 [−0.014, +0.030] | +0.012 [−0.077, +0.096] |
| accented_en | 50 | 0.863 | 0.866 | +0.003 [−0.035, +0.042] | +0.007 |
| general_en ⚠ | 30 | 0.829 | 0.874 | +0.045 [−0.011, +0.136] | +0.103 |
| russian | 48 | 0.887 | 0.897 | +0.010 [−0.067, +0.061] | −0.030 |
| noise | 20 | 0.881 | 0.900 | +0.019 [−0.018, +0.062] | +0.016 |
| reverb | 20 | 0.859 | 0.881 | +0.023 [−0.041, +0.083] | −0.040 |

Overall AP 0.513 → 0.525; recall@10% 0.558 → 0.565; ECE 0.022 → 0.022. **Confidence quality
is unchanged within noise** — every delta CI straddles zero. FP32 makes fewer errors (191 vs
206 scorable) and ranks them as well. D-0014's signal choice holds for either representation.

## 5. Performance

| | INT8 | FP32 | FP32 / INT8 |
|---|---:|---:|---:|
| model on disk | 670 MB | 2550 MB | 3.8× |
| peak working set (process, after 160 decodes) | 996 MB | **2736 MB** | +1.74 GB |
| working set after load | 742 MB | 2232 MB | |
| load (sherpa recognizer construction), p1 / p2 | 4.75 / 4.60 s | 11.76 / 8.70 s | ~2–2.5× |
| warm-up (2 × 5 s synthetic), p1 / p2 | 5.9 / 4.1 s | 4.6 / 3.9 s | ≈ |
| **per-utterance decode-time ratio, median [p05, p95]**, regime-matched | | | **1.07 [1.01, 1.15]** (p2), 1.09 [1.03, 1.16] (p1) |
| RTF, p2 regime-matched (155 rows) | 0.367 | 0.393 | |
| latency p50 / p95, p2 regime-matched | 2130 / 4053 ms | 2272 / 4109 ms | |
| median latency, utterances ≤3 s, p2 | 1701 ms | 1824 ms | |

**Timing caveat — anomalous fast regime.** Every arm process except int8-p2 contained
contiguous stretches of rows decoding several times faster than the same utterance did in
Task 2a (e.g. 200–800 ms instead of ~2–4 s): int8-p1 rows 13–31 and 121–123, fp32-p1 rows
109–159, fp32-p2 five rows. They are contiguous in time, not tied to content, and hit both
arms, so they are a system-state regime (P-core vs E-core placement on this hybrid
i5-12450H is the likely cause; unverified, out of scope). Raw pass-1 per-utterance ratios
therefore span 0.15–6.9 and are meaningless. The table uses **regime-matched rows**: rows
where neither arm of a pass decoded faster than 0.5× Task 2a's time for that utterance (91
rows in p1, 155 in p2). On those, the two passes agree: **FP32 costs 7–9% more decode time**,
tightly (p05–p95 within 1.01–1.16). Absolute latencies remain non-decision-grade; the ratio
is. The regime itself is a flag for Task 2 item 5 (thread sweep): a ~5× swing from scheduling
alone dwarfs the 7% precision cost.

## 6. Reading

- **Quality: FP32 wins, real.** −2.57 pp overall, −2.0 English, −5.3 Russian, −6.7 noise,
  CIs clear; never worse anywhere. Larger than the Parakeet–Whisper gap Task 2a measured.
- **Stability: FP32 wins, real.** Inaudible-dither flips 4× fewer (CI clear), sherpa/ORT
  parity 159/160 vs 127/160. Both are fully deterministic run to run.
- **Confidence: tie.** Same AUROC/AP within noise.
- **Cost: INT8 wins on every resource axis** — 1.74 GB less resident memory, 3.8× less disk,
  ~5 s faster load, ~7% faster decode.

Neither is dominated, so no early stop: FP32 wins quality and stability, INT8 wins every
resource. The 7% decode cost is small against both the 700 ms budget gap (whole-utterance p95
is ~4 s for either; the fix for that is streaming/overlap, not precision) and the scheduling
swing in §5. The memory cost is real: ~2.7 GB resident for the sidecar on a 15.7 GB machine.

## 7. Verdict

# FP32 PREFERRED

A ~19% relative WER reduction with the CI clear of zero, four times fewer transcript flips
under inaudible input noise, and near-exact reproducibility across implementations, for 7%
more decode time and 1.7 GB more RAM. On this machine the memory fits; the quality does not
come any other way within this task's scope.

### Phase 1 implication

- **Ship Parakeet TDT v3 as the FP32 export on the CPU EP.** Budget the sidecar at ~2.8 GB
  working set and ~9–12 s model load — load once at service start and keep it resident; never
  load per utterance. Pre-roll and hotkey latency are unaffected (decode is +7%).
- **Every Parakeet number from Tasks 2a/2b is an INT8 number and understates the model.** The
  backend decision (Task 2 item 3, personal set) must run Parakeet FP32. Fairness: Whisper
  was also measured INT8 only, so its fp32 headroom is unmeasured — the same question applies
  to it if it stays in contention.
- **D-0014 is unaffected:** emitted-token confidence is as good on FP32; the owned decode loop
  works over the FP32 sessions unchanged (parity 159/160).
- **Phase 3 Rust port parity testing gets much easier:** with FP32, two correct
  implementations agree on 159/160 transcripts and to 3.5e-4 nats; with INT8 they disagree on
  1 in 5 at near-tie margins.
- INT8 stays the documented low-memory fallback, not the default. A
  better-quantized export (static int8, fp16, or int8 excluding sensitive layers) might
  recover most of the gap at lower memory; that is a separate measurement, not done here.

## 8. Limits

- WER on a public proxy set; no F-WER, E-WER, dev-speak, code-switching or the user's
  microphone. The quality gap is measured where the set can see; the personal set can confirm
  or shrink it.
- One INT8 export (dynamic, `onnx.quantize`); its loss is a property of this quantization,
  not of INT8 in general.
- CPU EP, 4 threads only. GPU EPs and thread counts were out of scope. **The execution-provider
  question — DirectML vs WinML (open question #14) — remains unresolved**; "FP32 on the CPU
  EP" is the measured default, not a decision against a GPU EP.
- **FP32 has not been measured on personal speech.** Nothing here is the user's voice,
  microphone or room; Task 1b does not exist yet.
- Absolute timings are non-decision-grade (§5); the FP32/INT8 ratio is.
- accented_en, the slice that matters most, is in FP32's favour but not resolved (n=50).
