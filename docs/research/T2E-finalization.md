# T2E — Context-preserving finalization on the CPU EP

Status: **complete**, 2026-10-09. Phase 0, Task 2e. **Verdict: CPU FINALIZATION NOT RESCUED**
(§5). Decision record: **D-0017**.

**The question.** Can a bounded context-preserving finalization policy keep offline-quality WER
while holding release-to-final latency within the existing ≤ 450 ms MARGINAL ceiling, on the CPU?

**Why it was asked.** Task 2d (D-0016) measured two policies:

- **`redecode`** keeps offline quality: WER 10.643%, Δ −0.08 pp [−0.24, 0.00]. Its
  release-to-final p95 is 1339 ms.
- **Context-free LocalAgreement-2 `commit`** reaches a p95 of 443 ms, but its WER is 24.094%
  (+13.37 pp [+10.71, +16.32]).

Task 2d attributed `commit`'s damage to decoding each tail with no left context. Task 2e tests
whether giving that tail back a bounded amount of context closes the gap.

**Scope.** These were held fixed, all as in Task 2d:

- Parakeet TDT 0.6B v3 **FP32** sherpa-onnx export, greedy search.
- ORT 1.28.0 **CPU EP**, **4 threads**, **HighQoS**.
- 0.5 s hop and 1.0 s right context.
- LocalAgreement-2 commit rule and cut placement.
- Public Proxy v1 and `basic`-normalized WER.
- `t2d.GATE` and the eligibility rule, unchanged.

Not touched: the model, the representation, the thread count, QoS, datasets, fine-tuning,
partial generation and GPU providers. **WER, not F-WER**, because the proxy set has no
formatted reference.

**Run.** `eval/runs/20261009T193507Z-t2e-overlap-finalization-9264`.

```
uv run --group asr python -m hermes_eval.t2e screen
uv run python -m hermes_eval.t2e analyze <run-dir>
uv run --group asr python -m hermes_eval.t2e gate <run-dir> --left L   # not run: nothing retained
```

## 1. Design: what was possible, in the order the brief required

1. **Reusing decoder, encoder or cache state.** This is unavailable. The export is offline
   and full-context (the encoder attends over the whole input), so no encoder cache stays valid
   across a cut. sherpa-onnx's `OfflineRecognizer` accepts no decoder state. Re-seeding the
   decoder would mean replacing sherpa's decode with the owned Python loop (`tdt_probe`), a new
   decoder path. It would also leave the encoder starting cold at every cut, which is where
   Task 2d's hallucinated fillers come from.
2. **Bounded acoustic left overlap.** This is the policy tested here.
3. Stable-prefix plus overlap-tail re-decode is the same mechanism as 2 under LocalAgreement-2,
   so it needed no separate arm.

**The policy.** Task 2d `commit`, with one change: **every tail decode, partials and final
alike, starts `L` seconds before the current cut** (clamped at 0). The overlap applies to
partials as well as the final, because Task 2d's damage was also in *committed* words: they
came from context-free partial decodes. In Task 2d, "What about you? Did" became "What about
that" before the final ever ran.

**What is preserved.** Up to `L` s of audio that has already been committed is re-encoded. This
gives the encoder acoustic context and lets the decoder rebuild its token history across the
cut. Committed text is never revised.

**What is re-decoded at release.** `[cut − L, end]`.

**Duplicates and stitching.** Words carry absolute timestamps (sherpa `timestamps` +
`durations`, offset by the decode start). A word belongs to the tail iff its **timestamp
midpoint is at or after the cut**. Words before the cut were re-read as context and are
dropped. Alignment is by time alone: no text dedupe and no fuzzy match. The cut sits between
two words (`t2d._cut_point`), so this was expected to survive a one-frame onset shift.

**Code.**
- `t2d._decode_tail` holds the policy.
- `t2d.stream_utterance` and `t2d.run_stream` take `left_s`.
- With `left_s = 0` the path is Task 2d `commit` byte for byte, and it ran as the drift
  control.

## 2. Pre-registration

Fixed in `hermes_eval.t2e` before any Task 2e number existed.

- **Arms.** L ∈ {1.0, 2.0, 3.0} s, plus an L = 0 control that is never retained.
- **Screen subset.** `records[1::4]`, 40 rows:
  - all 7 subsets, 28 English and 12 Russian;
  - 7 rows ≤ 3 s, 13 of 3–6 s, 13 of 6–10 s, 7 > 10 s;
  - accented, read, far-field, noise and reverb all present.

  It was chosen because, on Task 2d's own rows, it reproduces the full-set latency: commit
  p95 443 vs 443 ms, redecode 1335 vs 1339 ms. Nothing about Task 2e informed the choice.
- **Elimination.** An arm is eliminated if its screen p95 is above 500 ms, or its WER Δ vs
  offline is above +1.0 pp, or the CI lower bound of that Δ is above 0.
- **Retention.** At most one arm: the smallest WER Δ, and within 0.25 pp the smaller L.
- **Full gate.** Only for a retained arm, on all 160 rows, under the unchanged `t2d.GATE`:
  - **PASS** at p95 ≤ 300 ms, **MARGINAL** at p95 ≤ 450 ms, **FAIL** above that.
  - **Eligibility:** CI low ≤ 0 and Δ ≤ +0.5 pp, from a paired bootstrap with 2000 resamples,
    seed 20260926.
- **Boundary attribution.** The final is aligned to the **offline transcript**, so every op
  is a divergence that streaming introduced. An op counts as "at a boundary" if its span,
  padded by 0.5 s, contains a cut. An inserted token equal to a neighbour is a duplicate; any
  other boundary insertion is a hallucination.

## 3. Run conditions — and a contamination

**Recorded.**
- 2026-10-09 19:35Z.
- HEAD `8c22264`, dirty: the Task 2e code was uncommitted (`t2d.py` `a7cebe28…`, `t2e.py`
  `dda7bf24…`). It was committed unchanged with this write-up.
- FP32 hashes, ORT, sherpa and the DLL equal to Task 2d.
- QoS high read back in all four workers (mask 1, state 0).
- One session per arm, 40/40 rows each.

**Contaminated.**
- Pre-flight had 6.76 GB available, but Edge stayed open (~2.6 GB).
- Available memory fell to **4.27 GB** during the run, under the 6 GB floor.
- About 1.4 GB was paged in, and the CPU was 81% busy at the median.

**Consequence.** The L = 0 control is the same code as Task 2d `commit`, on the same 40 rows.
It ran at **p95 753 ms against Task 2d's 443**, with final compute p50 232 against 168 ms.
**Absolute latencies in this task are not decision-grade.** The verdict does not use them
(§5).

## 4. Results (40-row screen)

| | L = 0 (control) | L = 1.0 | L = 2.0 | L = 3.0 | Task 2d commit, same rows |
|---|---:|---:|---:|---:|---:|
| **WER** (offline 12.34% on these rows) | 29.06 | 20.16 | **17.34** | 18.75 | 24.69 |
| **Δ pp [95% CI]** | +16.7 [+10.5, +24.0] | +7.8 [+4.4, +11.7] | **+5.0 [+1.3, +9.0]** | +6.4 [+2.7, +10.1] | +12.3 [+8.3, +16.6] |
| S / I / D (offline 43 / 19 / 17) | 86 / 46 / 54 | 48 / 51 / 30 | 35 / 47 / 29 | 41 / 47 / 32 | 69 / 42 / 47 |
| en / ru WER (offline 11.99 / 13.82) | 29.4 / 27.6 | 21.1 / 16.3 | 18.4 / 13.0 | 19.9 / 13.8 | 24.0 / 27.6 |
| utterances worse / better than offline | 30 / 1 | 23 / 3 | 16 / 5 | 16 / 3 | 28 / 3 |
| finals identical to offline | 2 | 7 | 12 | 11 | 2 |
| cuts | 143 | 195 | 217 | 232 | 144 |
| divergences from offline per 100 cuts (at a boundary) | 105 (70) | 45 (35) | 31 (26) | 31 (25) | 91 (74) |
| duplicate per 100 cuts | 10.5 | 15.9 | 12.9 | 12.9 | 11.8 |
| drop per 100 cuts | 23.1 | 8.7 | 6.5 | 7.3 | 27.8 |
| hallucination per 100 cuts | 9.8 | 2.1 | 2.3 | 1.3 | 8.3 |
| substitution at a boundary, per 100 cuts | 26.6 | 8.7 | 4.1 | 3.9 | 25.7 |
| release-to-final p50 / p95 ms *(contaminated)* | 279 / 753 | 336 / 748 | 455 / 866 | 517 / 720 | 190 / 443 |
| in-flight wait p95 / final compute p95 ms *(contaminated)* | 211 / 584 | 318 / 467 | 368 / 525 | 340 / 444 | 152 / 269 |
| final audio re-decoded p50 / p95 s | 2.2 / 6.9 | 2.8 / 4.7 | 3.5 / 6.3 | 4.3 / 5.3 | 2.2 / 3.7 |
| **screen decision** | control | **out** | **out** | **out** | — |

Every overlap arm fails the quality rule: Δ is above +1.0 pp and the CI lower bound is above 0.
Every one also exceeds the 500 ms latency line, but that reading is contaminated and is not
relied on. **No arm was retained, so the 160-row gate was not run**, as pre-registered.

## 5. Verdict: CPU FINALIZATION NOT RESCUED

The verdict **rests on quality alone**. The best arm (L = 2 s) is +5.0 pp [+1.3, +9.0] worse
than offline. That is ten times the eligibility tolerance, and the CI lies clear of zero. The
latency contamination cannot reverse it. The control's WER moved by +4.4 pp against Task 2d on
the same rows, because LocalAgreement-2's cut placement depends on timing. Even so, that is
not enough to bring any arm within +0.5 pp.

## 6. What failed, and why

1. **Left context fixes what it was expected to fix.** Against the control:
   - substitutions at a boundary fall ~6×;
   - hallucinated fillers fall ~4–7×;
   - dropped words fall ~3×.

   Russian returns to offline at L ≥ 2 (13.0 / 13.8 against 13.8).
2. **Duplicates do not fall at all.** They stay at 13–16 per 100 cuts, and insertions stay at
   ~2.5× offline (47–51 against 19).
3. **The cause is timestamp disagreement between independently decoded windows.** When words
   abut, the cut sits at the next word's onset. A re-decode heard with different left context
   places the already-committed word one 80 ms encoder frame later, its midpoint crosses the
   cut, and it is emitted twice. Example from `edacc_test-000216-noise10`: committed `was`
   [2.32, 2.48], re-decoded `was` [2.40, 2.56], cut at 2.48.
4. **Overlap creates more stitches.** Context-aware partials agree more often, so cuts rise
   from 143 to 195–232. Each cut is another chance for the failure in 3.
5. **A better stitcher would not close the gap.** This check was post-hoc and did not inform
   the verdict. Deleting *every* cross-cut adjacent duplicate from the finals still leaves:

   | L | WER after removing duplicates | Δ vs offline | deletions (offline 17) |
   |---|---:|---:|---:|
   | 1.0 | 16.25% | +3.9 pp | 38 |
   | 2.0 | 13.75% | +1.4 pp | 36 |
   | 3.0 | 15.00% | +2.7 pp | 39 |

   That is an oracle-like edit, and the best case is still nearly 3× the +0.5 pp tolerance.

**Conclusion.** The failure mode is **independent tail decoding with timestamp stitching**, not
the absence of context alone. Each window is a separate offline decode with its own
segmentation and timing, and no rule over the timestamps of two independent decodes reconciles
them reliably at word granularity.

## 7. What this establishes

1. **Cached or stateful reuse is unavailable** in the current sherpa-onnx offline export path.
2. **Context-free commit fails badly:** +13.4 pp on the full set (Task 2d), +12.3 to +16.7 pp
   on this screen.
3. **Acoustic-overlap commit improves some stitch errors but remains materially worse than
   offline:** +5.0 to +7.8 pp, with every CI clear of zero.
4. **Independent tail decoding plus timestamp stitching is the failure mode.**
5. **A commit-family CPU path would need true state continuity**, meaning a cache-aware
   streaming export of the model, **not more overlap tuning.** Overlap sizes beyond those
   pre-registered were not tried and should not be.
6. **Full `redecode` remains the only measured quality-preserving policy:** 159/160 finals
   identical to offline (Task 2d).
7. **The next experiment is acceleration of full `redecode`.** It fails only on cost: ~57 ms
   per audio-second of final compute (p95 863 ms) plus the in-flight partial wait (p95 575 ms).
   An execution provider (DirectML or WinML, open question #14) attacks the first. Reaching
   p95 ≤ 450 ms needs the sum to fall by roughly 3×.
8. **In-flight partial cancellation is a separate, orthogonal latency lever, not a
   replacement for acceleration.** It removes the wait but not the length-proportional
   compute, which on its own already exceeds 450 ms beyond ~6.5 s of audio.

## 8. What this does not settle

- **Clean latency for the overlap arms.** They were not re-measured, because the quality
  verdict makes it moot.
- **Whether a cache-aware streaming Parakeet export exists and keeps FP32 quality.** That is
  a model or export question, outside this task.
- **Any execution provider.** DirectML, WinML and CUDA remain unmeasured.
- **Personal speech, F-WER, E-WER.** All of the above is proxy-set WER.

## Artifacts

`eval/runs/20261009T193507Z-t2e-overlap-finalization-9264/` (promoted with `git add -f`):

| file | content |
|---|---|
| `run.json` | pre-flight (git, hardware, software, model hashes, topology, memory), config with pre-registered ids / arms / rule, `stream_sessions` |
| `screen-commit-L{0,1,2,3}.0-t4.json` | per-arm session summary (load, QoS read-back, memory) |
| `screen-commit-L{0,1,2,3}.0-t4.jsonl` | per-utterance partials (with `seg0` and `lo`) and final (words, latency decomposition, `decoded_s`) |
| `counters-screen.jsonl` | PDH samples for the whole screen, which is the contamination evidence |
| `analysis.json` | `t2e analyze` output: per-arm metrics, screen decision, Task 2d commit on the same ids |

The offline reference texts come from the Task 2d baseline
(`20261007T040840Z-t2d-parakeet-fp32-cpu-190c/offline-t4-r1.jsonl`, already committed). No
audio, models or caches are committed.
