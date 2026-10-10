# T2F — Acceleration of full `redecode`: provider selection and pre-registered gate

Status: **provider selected, gate pre-registered, nothing measured**, 2026-10-10. Phase 0,
Task 2f. **Decision: TEST DIRECTML NEXT.** Decision record: **D-0018**.

**The question.** D-0017 made execution-provider acceleration of the full-utterance
`redecode` final the next experiment. Two candidates were named in open question #14:
Windows ML (WinML) and the ONNX Runtime DirectML EP. Which one should carry that experiment,
and what result would count?

**What this document is not.** It does not choose the shipping execution provider. DirectML
is chosen here as the **measurement vehicle** for the next experiment, because it gives the
cleanest controlled comparison with the frozen CPU baseline. The shipping provider remains
undecided (D-0011's DirectML default stays under review as open question #14).

**Scope of this step.** Documentation research only. No package was installed, no inference
code was changed, and nothing was benchmarked. The two wheels named below were downloaded to
a scratch directory and inspected as zip archives. Neither was installed.

## 1. The target

From Task 2d (D-0016), `redecode`, Parakeet TDT 0.6B v3 FP32, sherpa-onnx 1.13.8 greedy,
ORT 1.28.0 CPU EP, 4 threads, HighQoS, all 160 rows:

| | |
|---|---|
| final WER | 10.643%, eligible (Δ −0.08 pp [−0.24, 0.00] vs offline 10.721%) |
| final-decode compute p50 / p95 | 351 / **863** ms |
| wait for in-flight partial p50 / p95 | 95 / **575** ms |
| release-to-final p50 / p95 | 452 / **1339** ms |
| gate (`t2d.GATE`) | PASS ≤ 300 ms, MARGINAL ≤ 450 ms, FAIL above |

Final compute must fall roughly 2–3×, and the in-flight wait must fall with it. The wait falls
only if the partials are accelerated too, because each partial is itself a whole-prefix decode.

## 2. Evidence (checked 2026-10-10)

### 2.1 What "Windows ML" means on this GPU

Microsoft's *Windows ML execution providers* page (updated 2026-10-07) lists:

- **Included with Windows ML:** CPU, and DirectML, labelled *"(legacy)"*.
- **Downloaded on demand through `ExecutionProviderCatalog`:** MIGraphX, **NvTensorRtRtx**,
  OpenVINO, QNN, VitisAI, and WebGPU (experimental). The only NVIDIA entry is
  `NvTensorRtRtxExecutionProvider` (RTX 30xx and newer, driver 32.0.15.5585 or later).

So on an RTX 4050, "test Windows ML" means one of two things:

1. testing Windows ML's included DirectML EP, which is the DirectML EP; or
2. testing TensorRT for RTX, which the brief excludes unless DirectML fails.

Windows ML contributes no in-scope NVIDIA accelerator of its own.

### 2.2 The two wheels are the same DirectML EP, at different ORT versions

PyPI on 2026-10-10:

| package | latest | ORT inside | `DirectML.dll` | notes |
|---|---|---|---|---|
| `onnxruntime` | 1.31.0 (2026-10-09) | — | — | CPU only; Hermes pins 1.28.0 for sherpa |
| `onnxruntime-directml` | **1.24.4 (2026-03-17)** | 1.24.4 | 1.15.4 | no release since March 2026 |
| `onnxruntime-windowsml` | 1.30.0.202609102321 | — | — | 1.28.0 and 1.28.2 builds also published |

Inspection of `onnxruntime_windowsml-1.28.0.202607272323-cp311-cp311-win_amd64.whl`
(sha256 `7303a7ef8bc42da2cc912d9d5184783180ceda1481071ed4e41065653410d47e`, equal to PyPI's
digest; uploaded 2026-08-17):

- `build_and_package_info.py`: `package_name = 'onnxruntime-directml'`, `__version__ = '1.28.0'`.
- It bundles `onnxruntime.dll` (file version `1.28.0.20260727.1.1dc6392`), `DirectML.dll`
  (`1.15.4+241025-1615.1.dml-1.15.fac7597`) and `onnxruntime_pybind11_state.pyd`.
- `onnxruntime.dll` contains `DmlExecutionProvider` and the `ep.dml.*` session keys
  (`disable_graph_fusion`, `disable_memory_arena`, `enable_graph_capture`, …), plus
  `session.disable_cpu_ep_fallback`.
- The `.pyd` exposes `get_ep_devices`, `add_provider_for_devices`,
  `set_provider_selection_policy` and `get_provider_options`.

The standalone `onnxruntime-directml 1.24.4` wheel bundles **the same `DirectML.dll` file
version**. It differs only in carrying an older ORT.

**Consequence.** `onnxruntime-windowsml==1.28.0.202607272323` is the only available build of
the DirectML EP on **ORT 1.28.0, the exact ORT version of the frozen CPU baseline.** Used on
its own, it is a plain ORT + DirectML distribution. None of the Windows ML catalog, Windows App
SDK runtime or bootstrap is needed to reach `DmlExecutionProvider`. Microsoft's
*Register execution providers* page confirms that before any registration,
`get_ep_devices()` lists `CPUExecutionProvider` and `DmlExecutionProvider`.

### 2.3 sherpa cannot drive DirectML

The installed sherpa-onnx 1.13.8 wheel (`_sherpa_onnx.cp311-win_amd64.pyd`) contains the
`directml` provider string and its fallback message, but no DirectML append symbol. The
DirectML path is compiled out, and asking for it **falls back to CPU with only a log line**.
A DirectML-enabled sherpa means a source build, which is out of scope.

**Consequence.** The experiment needs **direct ORT sessions** over the same
`encoder.onnx` / `decoder.onnx` / `joiner.onnx`, driven by a Hermes-owned TDT greedy loop.
The owned loop already exists in `tdt_probe.TdtProbe.greedy`, which agrees with sherpa on
159/160 FP32 transcripts (Task 2c, D-0015).

### 2.4 The owned loop as it stands is too slow

Task 2b measured `TdtProbe`'s decode loop (Python, on top of the encoder) at RTF 0.057,
**325 / 741 ms p50 / p95**. That figure is non-decision-grade, but on its own it would sink a
450 ms gate whatever the GPU does. Most of the cost is per-step instrumentation:
`step_measures` computes full-distribution softmax, entropies and a sorted alternative list
over 8198 logits at every step. The **lean** loop keeps the control flow and drops the
instrumentation (§4, Stage 0).

### 2.5 The model graphs

Read from `models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-fp32/`, without external data:

| graph | opset | nodes | inputs (dynamic dims) | external data |
|---|---|---|---|---|
| `encoder.onnx` | 17 | 4491 (1661 `Constant`) | `audio_signal` [B, 128, T], `length` [B] | 612 initializers in `encoder.weights`, 2.44 GB |
| `decoder.onnx` | 17 | 29 (2 `LSTM`) | `targets` [B, U], states [2, B, 640] | none (47 MB) |
| `joiner.onnx` | 17 | 14 | enc [B, 1024, T'], dec [B, 640, U'] | none (25 MB) |

- Every encoder op is a standard ONNX op: `MatMul`, `Conv`, `LayerNormalization`, `Softmax`,
  `Sigmoid`, `Where`, `Pad`, `Split`, `Range`, `Tile`, and so on.
- ORT's DirectML EP supports up to opset 20.
- There are 175 `Shape`, 132 `Cast` and many int64 `Gather` / `Concat` / `Unsqueeze` nodes.
  This is the shape-computation subgraph that ORT normally places on the CPU.

### 2.6 This machine

- **Two GPUs.** Intel UHD Graphics (driver 32.0.101.6790) and NVIDIA GeForce RTX 4050 Laptop
  GPU (6 GB, driver 566.24 / 32.0.15.6624). DirectML `device_id` 0 is the DXGI default
  adapter, which may be the iGPU.
- **Two DirectML copies.** `C:\Windows\System32\DirectML.dll` is file version 1.15.5 (inbox).
  The wheel's is 1.15.4. Which one loads has to be checked, not assumed.
- **`C:\Windows\System32\onnxruntime.dll` is 1.17** (Task 2a's DLL conflict).
- **The laptop was on battery** when this was checked. A discrete GPU on battery is
  power-limited.

### 2.7 Scorecard

| # | criterion | Windows ML (catalog path) | ORT DirectML EP (via `onnxruntime-windowsml` 1.28.0) |
|---|---|---|---|
| 1 | support today | active; NVIDIA path is TensorRT-RTX; DirectML "legacy" | sustained engineering; standalone wheel frozen at 1.24.4 |
| 2 | FP32 artifacts | TensorRT-RTX builds engines; precision behaviour unverified | used unchanged |
| 3 | external data | TensorRT-RTX needs `nv_use_external_data_initializer` | ORT loads it normally |
| 4 | ops / dynamic shapes | needs shape profiles | opset 17 ≤ 20; dynamic T is the main risk (§5) |
| 5 | RTX 4050 | yes, via TensorRT | yes, if the NVIDIA adapter is selected explicitly |
| 6 | sherpa directly | no | no; direct ORT sessions required |
| 7 | semantic preservation | same owned loop, plus catalog setup | encoder on DirectML; decoder and joiner on CPU; same owned loop |
| 8 | silent CPU fallback | higher (selection policy, on-demand download) | medium, and detectable (Stage 1) |
| 9 | verification | `get_ep_devices`, catalog ready-state | `get_ep_devices` vendor 0x10DE, node placement, profiling, GPU counters, loaded-DLL path |
| 10 | Python sidecar | needs Windows App SDK runtime plus bootstrap; Python must register EPs one by one | one wheel, no bootstrap |
| 11 | packaging | framework-dependent only for Python | bundled DLLs |
| 12 | longevity | better | worse |
| 13 | fair paired benchmark | ORT build and EP both change | **same ORT 1.28.0 build on both arms; only the encoder's EP differs** |

Criteria 2–10 and 13 decide the experiment. Criterion 12 favours Windows ML, and it is the
reason this does not decide the shipping provider.

## 3. Decision: TEST DIRECTML NEXT

- **Vehicle.** `DmlExecutionProvider` from `onnxruntime-windowsml==1.28.0.202607272323`
  (sha256 above), used only as an isolated ORT 1.28 + DirectML distribution.
- **Not used:**
  - the Windows ML `ExecutionProviderCatalog`, Windows App SDK runtime or bootstrap packages;
  - standalone `onnxruntime-directml` 1.24.4;
  - TensorRT-RTX or CUDA.
- **Isolation.** The wheel installs the same `onnxruntime` import package as
  `onnxruntime==1.28.0`, which sherpa depends on. So it goes into a **separate virtual
  environment** (`.venv-t2f/`, gitignored when created) and **never into `.venv`**.
- **Not decided here:** the shipping provider, the packaging route, and anything about Windows
  ML's longevity advantage. A positive result says the DirectML EP can meet the gate on this
  machine. It does not say Hermes ships DirectML.
- **Out of scope unless DirectML fails:** TensorRT-RTX, through Windows ML or otherwise.

## 4. Pre-registered gate

Fixed before any Task 2f number exists. Stages run in order. A stage that fails stops the
task, except where a single diagnostic retry is written in.

**Held fixed throughout.**

- Parakeet TDT 0.6B v3 FP32 sherpa export, with the same file hashes as Task 2d (encoder
  `3eed7ce4…`).
- Public Proxy v1 (manifest `2b3a46ed…`) and `basic`-normalized WER.
- Features as `tdt_probe.features` (kaldi-native-fbank pinned to sherpa's).
- Greedy TDT semantics: `GREEDY_MAX_TOKENS_PER_FRAME = 5`, token argmax, duration argmax, and
  blank with skip 0 forced to skip 1.
- CPU-side sessions at 4 threads, with HighQoS.
- `t2d.GATE` and the eligibility rule, unchanged: paired bootstrap, 2000 resamples, seed
  20260926; CI lower bound ≤ 0 and point Δ ≤ +0.5 pp.
- The `redecode` policy: 0.5 s hop, push-to-talk release at the end of the audio.

**Pre-flight, every session.**

- On AC power, with the state recorded.
- Available memory at least 6 GB, with large browsers closed.
- NVIDIA driver version recorded.
- No stale ASR processes.
- Model hashes equal to Task 2d.
- PDH sampler running, extended with per-process GPU engine utilization and dedicated GPU
  memory.
- The isolated environment's `onnxruntime.dll`, `DirectML.dll` and wheel hash recorded.

**Arms.** All arms use the same isolated environment, the same lean loop and the same model.

- **C:** direct ORT, all three sessions on the CPU EP.
- **G:** direct ORT, encoder on `DmlExecutionProvider` (NVIDIA device), decoder and joiner on
  the CPU EP.

Keeping the decoder and joiner on the CPU in G means the loop's numerics are identical
between arms. Only the encoder output can differ.

### STAGE 0 — Lean decoder validation (CPU only)

**Purpose.** Before any GPU speed result counts, the owned lean greedy path must be
**validated independently on CPU against the frozen sherpa baseline.**

**What is built.**

- A lean greedy loop with the same control flow as `TdtProbe.greedy` (sherpa's
  `DecodeOneTDT`). It records only token, frame, duration and the emitted token's log-prob.
  The emitted-token probability is the D-0014 confidence.
- A result shim exposing the sherpa result fields the `t2d` redecode path reads.

**Measurements**, arm C, offline whole-utterance decode, all 160 rows, one fresh process,
2 warm-ups:

- Lean loop against `TdtProbe.greedy`, on the same encoder output: token and frame sequences
  compared row by row.
- Lean-loop text against the Task 2d sherpa offline transcripts
  (`20261007T040840Z-t2d-parakeet-fp32-cpu-190c/offline-t4-r1.jsonl`).
- WER Δ against sherpa offline (10.721%), using the eligibility rule.
- Time split per row: features, encoder, loop. **Loop overhead is measured on its own.**

**Pass, all required.**

1. Lean equals `TdtProbe.greedy` on **160/160** token and frame sequences. Same sessions
   and same encoder output, so any difference is a bug.
2. Lean text equals sherpa offline text on **≥ 159/160** rows. That is Task 2c's FP32 parity.
3. WER Δ against sherpa offline is **eligible**.
4. **Loop overhead p95 ≤ 100 ms.**

**Early stop.**

- Fewer than 159/160, or not eligible: fix the loop. Nothing is timed on the GPU.
- Loop p95 above 100 ms: stop. No GPU can rescue a Python loop that already spends a quarter
  of the budget, and moving the loop to native code is a different task.

### STAGE 1 — Provider and device validation

Runs in arm G. Each item is recorded in `run.json`.

1. **Enumerate.** List `get_ep_devices()` (EP name, vendor, vendor ID, device ID, type,
   metadata). There must be a `DmlExecutionProvider` device with **vendor ID 0x10DE**.
2. **Select explicitly.** Build the encoder session with `add_provider_for_devices` on that
   device only, or an equivalent explicit NVIDIA selection. Never rely on the default
   adapter. Record `get_providers()` and `get_provider_options()`.
3. **Session options DirectML requires.** Memory pattern off and sequential execution. The
   batch free dimension is overridden to 1. The time dimension stays dynamic. No graph
   change, no fp16 and no re-export.
4. **Loaded DLLs.** Record the process's loaded-module paths and file versions for
   `onnxruntime.dll` and `DirectML.dll`. Expected: the isolated environment's 1.28.0 and the
   wheel's 1.15.4. If the inbox System32 `DirectML.dll` (1.15.5) is loaded, record it. It is
   acceptable only if stated.
5. **Node placement.** Collect a verbose-log "Node placements" dump and an ORT profiling
   JSON for one 10 s clip. Also try a session with `session.disable_cpu_ep_fallback = 1` and
   record whether it is accepted.
6. **GPU activity.** Run the encoder 20 times on a 10 s clip. Per-process GPU compute-engine
   utilization must be above zero, and dedicated GPU memory must rise by about the weight size
   (~2.4 GB). The arm C negative control must show no GPU activity for the process.
7. **Shape behaviour.** Record first-call against second-call encoder time at the same input
   length, and the cost of a never-seen length.
8. **Numerics.** Over all 160 rows, record the maximum absolute and relative difference of
   encoder outputs, G against C.

**Pass.**

- Items 1, 2 and 6 succeed.
- Every `MatMul`, `Conv`, `Softmax`, `LayerNormalization` and attention-path node is on the
  DirectML EP.
- Only shape-computation nodes (int64 `Shape` / `Gather` / `Concat` / `Cast` / `Unsqueeze`
  and the like) and their copies are on the CPU EP.

**Early stop (meaningful CPU fallback).**

- No NVIDIA DirectML device.
- Any compute-heavy node (`MatMul`, `Conv`, `Softmax`, `LayerNormalization`) on the CPU EP.
- No GPU activity during encoder runs.
- Session creation fails or runs out of memory, dedicated GPU memory goes above 5 GB, or
  available RAM falls below 6 GB during load.

### STAGE 2 — 40-row acceleration screen

**Rows.** The same representative subset as Task 2e, `records[1::4]` (40 rows, all 7
subsets, every length bucket). It reproduces Task 2d redecode's p95 (1335 against 1339 ms).

**Procedure.**

- Streaming `redecode` in arms C and G, with the same lean loop and model.
- Two sessions per arm in **G, C, C, G** order, each a fresh process.
- Recorded per row:
  - final compute, in-flight wait and release-to-final;
  - the feature, encoder and loop split of the final;
  - GPU counters.

**Screen quantities.**

- Final-compute p95 for each arm, over the 80 pooled finals (2 sessions × 40).
- **Speedup** = C final-compute p95 / G final-compute p95.
- Also reported: the median per-row paired ratio, the in-flight wait p95 per arm, and
  release-to-final p95 per arm.
- Each arm's two sessions must agree on final-compute p95 within 15%. Otherwise the screen is
  non-decision-grade and is rerun once.

**Quality on the screen.** G's finals against C's must be eligible under the existing rule.
G must also agree with C on ≥ 38/40 final texts. Below that, Stage 1 item 8 is examined, with
one diagnostic retry using `disable_metacommands`.

**Early stop, any one ends Task 2f with DIRECTML FAILS SCREEN.**

- **G final-compute p95 > 300 ms.**
- **Speedup < 2.0.**
- G quality not eligible on the screen after the single diagnostic retry.

**Cancellation is not used here.** A provider that fails the compute screen is not rescued by
cancelling in-flight partials.

### STAGE 3 — Full gate

Runs only if Stage 2 survives.

1. **160-row offline equivalence.**
   - Arm G must agree with arm C on **≥ 155/160** texts.
   - G must be eligible against Task 2d's sherpa offline (10.721%) and against C.
   - Arm C must reproduce Stage 0's parity.
2. **160-row streaming `redecode`, arm G.**
   - Two sessions, plus arm C in **G, C, G** order. C is the paired control and the drift
     check against Task 2d.
   - **Verdict on the first G session** under `t2d.GATE`, unchanged: release-to-final p95
     PASS ≤ 300 ms, MARGINAL ≤ 450 ms, FAIL above. Eligibility of G's finals against offline
     is required.
   - The second G session must reproduce the first's p95 within 15%, or the verdict is
     non-decision-grade.
3. **Cancellation, a separately attributable variant (G+cancel).**
   - At release, the in-flight partial is abandoned (`RunOptions.terminate`, result
     discarded), and the final starts at once. Everything else is identical to G.
   - One 160-row streaming session, run only after item 2.
   - It gets its own verdict under the same gate and is reported **next to G, never in place
     of G.** The provider verdict is G's.

**Reported by stage.**

- Stage 0: parity counts and the time split.
- Stage 1: the validation record.
- Stage 2: screen speedup and quality.
- Stage 3:
  - G and G+cancel release-to-final p50 / p95 / p99;
  - wait and final compute;
  - p95 by length bucket;
  - WER and eligibility;
  - GPU memory and utilization;
  - cold-after-idle first-call penalty, as a product finding, not a gate input.

## 5. Expected compatibility blockers

1. **Dynamic time length.** Every partial and final has a new length. DirectML may re-plan
   or decline graph fusion on each call. This is the largest performance risk and the reason
   for Stage 1 item 7.
2. **Shape subgraph on the CPU.** About 400 int64 shape nodes will likely run on the CPU EP,
   with copies in between. `disable_cpu_ep_fallback` will probably reject the session, so
   Stage 1 counts and classifies these nodes instead of requiring zero.
3. **Adapter selection on a hybrid laptop.** Default adapter 0 may be the Intel UHD.
4. **DLL resolution.** Inbox `System32\DirectML.dll` 1.15.5 against the wheel's 1.15.4, and
   inbox `onnxruntime.dll` 1.17 (Task 2a's conflict).
5. **Load memory.** Loading 2.44 GB of external initializers, plus the GPU upload, may push
   resident memory above Task 2d's 2.75 GB peak during load. The 6 GB available floor applies.
6. **FP32 numerics.** GPU kernels change reduction order, and vendor metacommands may change
   precision. FP32 tolerated inaudible dither on 152/160 rows (Task 2c), so a few flipped
   transcripts are expected and the parity thresholds allow for them.
7. **Python loop overhead** (§2.4). Addressed by Stage 0.
8. **Laptop GPU power gating.** The discrete GPU may power down between utterances, so
   cold-after-idle cost is recorded separately.
9. **Battery.** Pre-flight requires AC.

## 6. Minimum implementation (for the next step, not done here)

1. Create the `.venv-t2f/` isolated environment with `onnxruntime-windowsml==1.28.0.202607272323`
   pinned by hash, plus numpy and the sherpa-pinned kaldi-native-fbank. Add it to
   `.gitignore`.
2. In `tdt_probe`, add per-session provider and session options. The default stays
   `CPUExecutionProvider` for every session, so existing callers are unchanged.
3. Add the lean greedy loop and a unit test that it matches `greedy()` step for step on
   fixtures.
4. Add a result shim and a `t2d` backend switch (`probe-cpu` / `probe-dml`), so the
   `redecode` policy code runs unchanged.
5. Extend the PDH sampler with per-process GPU engine utilization and dedicated GPU memory.
6. Add a `t2f` module holding these constants, the stage runners and the analysis.

## Sources

- ONNX Runtime, *DirectML Execution Provider*:
  https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html
- Microsoft Learn, *Windows ML execution providers* (updated 2026-10-07):
  https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/supported-execution-providers
- Microsoft Learn, *Install and deploy Windows ML*:
  https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/distributing-your-app
- Microsoft Learn, *Register Windows ML execution providers*:
  https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/register-execution-providers
- ONNX Runtime, *TensorRT RTX Execution Provider*:
  https://onnxruntime.ai/docs/execution-providers/TensorRTRTX-ExecutionProvider.html
- PyPI JSON API for `onnxruntime`, `onnxruntime-directml` and `onnxruntime-windowsml`, read
  2026-10-10.
