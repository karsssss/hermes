# R5 — Rust stack: Tauri, audio, inference, IPC, concurrency, persistence

Research landed 2026-09-25. Crate versions verified against crates.io and the GitHub API.
Hotkeys and text injection are in **R2** and not repeated here. Items marked **unverified**
must not be treated as fact.

## The finding that reshapes backend selection

**`sherpa-rs` is ARCHIVED.** The only Rust binding to sherpa-onnx is dead (v0.6.8, repo
archived). Using sherpa-onnx from Rust now means **writing and maintaining our own FFI
layer** — real, non-trivial, ongoing cost.

Combine with R1/R4:

| Path to contextual biasing | Blocker |
|---|---|
| sherpa-onnx hotwords | **No maintained Rust binding.** Also, Nemotron hotword support merged after the last release |
| NeMo-Speech.cpp word boosting | **No Rust bindings** (C headers + CMake). Thin project, 17 commits. Boosting for it never verified |
| Parakeet TDT via any runtime | **Explicitly ignored by NVIDIA word boosting** |
| **ONNX Runtime + Nemotron Speech Streaming** | **`ort` 2.0.0-rc.13 is very active; ONNX Runtime GenAI ships official Rust bindings** |

**This converges on one coherent production path: `ort` + Nemotron Speech Streaming EN
0.6B (ONNX, int8/int4), DirectML execution provider.** It is the only combination where
streaming + biasing + a maintained Rust binding + a commercial licence all hold at once.
Treat this as the leading hypothesis for Phase 0 to validate, not a settled decision.

## Inference crates

| Crate | Version | Last activity | Verdict |
|---|---|---|---|
| **`ort`** (pykeio) | 2.0.0-rc.13 | pushed today, 2533 stars, **4 open issues** | Very active. **Pre-1.0 for years** — pin the exact version, expect breaking changes before 1.0 |
| `llama-cpp-2` | 0.1.157 | pushed 2026-09-24, Apache-2.0 | **Best-maintained of the group.** The path for a GGUF correction LLM |
| `whisper-rs` | 0.16.0 | last commit **2026-03-14**, ~6 months stale | Ambiguous — "stable" or "losing steam". Watch item, not a green light |
| `sherpa-rs` | 0.6.8 | **repo ARCHIVED** | **Dead. Do not adopt.** |

Licensing at the binding and C++ layers is clean throughout: whisper.cpp MIT, llama.cpp
MIT, ONNX Runtime MIT. **No GPL exposure.**

### GPU execution providers — DirectML wins on pragmatics

`ort` exposes both `cuda` and `directml` feature flags.

**CUDA in a consumer installer is a legal problem, not just a size problem.** The CUDA
EULA appears to list `cudart`, `cublas`, `cufft` as redistributable with conditions — but
**cuDNN did not appear in that redistributable list**, and cuDNN is typically required for
the conv/attention kernels ASR models use under the CUDA EP. cuDNN has its own separate
SLA, unchecked. *This summary is unverified — it needs a direct legal read of the primary
EULA text before any engineering time goes into a CUDA-in-installer path.* Separately,
CUDA requires matching a bundled runtime to the user's driver, which is a real support
burden on an install base we do not control.

**DirectML is the default.** Microsoft-owned, D3D12-based, ships with the Windows/driver
stack, works across NVIDIA/AMD/Intel, no redistribution question, no driver-matching
problem. Lower throughput than tuned CUDA+cuDNN, but for a single always-on dictation
stream on a 4050 that is very unlikely to be the bottleneck.

**Keep the CPU EP path working regardless** — install-base coverage and a smaller installer
variant.

## Tauri

**Version: 2.11.6 stable (2026-09-19).** v3.0.0-alpha.2 exists — do not build on it.
Repo pushed today, 111k stars. Not a risk area.

- **Sidecar:** `bundle.externalBin`, binaries suffixed with the target triple
  (`hermes-sidecar-x86_64-pc-windows-msvc.exe`), invoked via `tauri-plugin-shell`. Tauri v2
  permissions are **deny-by-default** — must explicitly grant `shell:allow-execute` with
  `sidecar: true` in `capabilities/*.json`. Expect **Defender/SmartScreen friction** on a
  bundled PyInstaller-style sidecar until reputation builds; sign the sidecar too.
- **Tray:** mature, not a risk.
- **Overlay HUD:** `setIgnoreCursorEvents()`, `setAlwaysOnTop()`, and `transparent: true`
  all exist individually. **The three-way combination on Windows 11's WebView2 compositor
  was NOT verified** — historically a pain point across WebView2/Electron/CEF (alpha
  artifacts, click-through needing window recreation on some drivers). **Spike this early
  with a throwaway window.**
- **Bundle size:** Tauri uses the OS WebView2 runtime (inbox on Win11), so installers are
  typically single-digit MB.

### Installer, signing, and the uiAccess gap

- Per-machine install to Program Files: **native support** via `installMode: "perMachine"`.
  Not a custom-pipeline problem.
- NSIS and MSI (WiX v3) both supported; custom WiX fragments supported
  (`src-tauri/windows/fragments`), so MSI customization needs no bundler fork.
- Authenticode: via `signtool.exe` or a custom `signCommand` (Azure Trusted Signing works).
  **EV certs no longer get special SmartScreen treatment** (Microsoft ended that in 2024) —
  a standard OV cert plus reputation building is the practical path.
- **uiAccess is not addressed anywhere in Tauri's docs.** This is the one custom step.
  Fix: the **`embed-manifest` crate (1.5.1, updated 2026-09-14)** is a `build.rs` manifest
  embedder that can inject `uiAccess="true"`. **Not verified end-to-end against Tauri's
  bundler — treat as a half-day spike.** Do **not** use `winres` (stale since 2021).

## Audio capture

**`cpal` 0.18.2** (2026-08-16, Apache-2.0, repo pushed 2026-09-20, healthy). Event-driven
callback model, WASAPI-backed. Raw WASAPI via `windows-rs` gives more control (exclusive
mode, explicit `SetEventHandle`) at materially more COM/FFI code, **with no payoff at this
scale** — shared-mode is sufficient for dictation. **Difficulty 3/5.**

**`rubato` 5.0.0** (2026-08-10, permissive) for 48/44.1 kHz to 16 kHz. **Pure Rust — no
soxr FFI, no C build step**, which matters a lot on Windows for a beginner. `SincFixedIn`
for quality, `FastFixedIn` for speed. CPU cost is irrelevant next to the idle target since
it only runs while recording. **Difficulty 2/5.**

**Device hot-swap is not free.** cpal does not auto-migrate a running stream and does not
ergonomically expose `IMMNotificationClient`. Pragmatic pattern: poll
`host.default_input_device()` every 1–2 s from a supervisor thread and rebuild the stream
when device identity changes. **Budget real engineering time — this is one of the least
turnkey parts of cpal.**

## Real-time thread discipline

**Ring buffers:** `ringbuf` 0.5.2 (2026-09-13) or `rtrb` 0.4.0 (2026-08-18). Both healthy.
Either is fine for **callback-to-consumer handoff**; pick one and move on.

**Important design correction: do NOT use them for the pre-roll buffer.** "Always retain
the last 1.5 s" is a single-owner circular *overwrite* buffer, not a producer/consumer
queue — rtrb errors when full rather than overwriting, which is the wrong semantics.
**Hand-roll it:** one pre-allocated `Box<[f32]>` sized at stream start plus a `write_pos`
cursor with wrapping index arithmetic. More teachable than a second crate API for what is
just modular arithmetic, and it sidesteps the full/empty question entirely.

**MMCSS:** no crate exists (`mmcss` is not on crates.io). Call
`AvSetMmThreadCharacteristicsW` / `AvRevertMmThreadCharacteristics` directly via
`windows-rs`, `Win32::Media::Multimedia`. *Exact module path and feature flag could not be
confirmed via docs.rs — verify locally with `cargo doc --open` before coding against it.*

### The four footguns, specifically

1. **Allocation on the audio thread.** `Vec::push` past capacity, `.clone()` of a `String`,
   `format!()`, `println!`, `log::info!` — most logging backends allocate *and* lock. Causes
   intermittent glitches that "mostly work", the hardest class of bug for a beginner.
   Pre-allocate before `stream.play()`; ban logging macros in the callback; write raw stats
   into a ring buffer and log from another thread.
2. **Mutexes.** Even usually-uncontended ones can hit priority inversion under Windows
   scheduling. Audio data moves only through the SPSC ring buffer; flags are
   `Arc<AtomicBool>`/`AtomicUsize`, never a mutex.
3. **Panics are silent death.** An `.unwrap()` here unwinds and kills the callback thread;
   cpal just stops calling you. **No crash dialog — the app appears to hang while doing
   nothing.** Never `.unwrap()`/`.expect()` on this thread; `match` explicitly and route
   errors through an atomic counter a supervisor polls.
4. **`Drop` doing slow or fallible work** on the real-time path (e.g. an RAII MMCSS guard).
   Keep `Drop` on audio-path types trivial.

Rust has no built-in no-alloc enforcement outside `no_std`, so this is **review
discipline**: keep the callback body under ~20 lines calling pre-audited helpers, and scope
`#![deny(clippy::unwrap_used)]` to that module.

## IPC — NDJSON over localhost TCP

Rejected: **shared memory** (payloads are tiny — 16 kHz mono PCM is ~32 KB/s, partials are
hundreds of bytes; adds unsafe complexity for zero benefit). **stdin/stdout** (Python ML
libraries routinely print warnings to stdout and will silently corrupt the protocol — an
easy rule for a dependency to violate). **Named pipes** via `interprocess` 2.4.4 are
idiomatic and slightly more secure, but duplex role semantics are less commonly taught and
there is no "telnet it and see" debugging.

**Chosen: localhost TCP, loopback-bound**, because `TcpListener`/`TcpStream` on the Rust
side and `asyncio` on the Python side are both extremely well documented and debuggable
with ubiquitous tools. Loopback binding typically avoids the Windows Firewall prompt
(*unverified for this exact setup*).

**Serialization: JSON Lines, not MessagePack or protobuf.** At our message sizes
`serde_json` is single-digit microseconds — utterly negligible against hundreds of
milliseconds of inference. Optimizing this before it appears in a profile costs
beginner-friendliness for no measured gain, and Python's `json` needs zero extra
dependencies. (`rmp-serde` 1.3.1 is the option if it ever matters. **Avoid
`msgpack-simple` — unmaintained since 2020.**)

Message envelope: `{schema_version, type, seq, payload}`, version checked on every message
from day one.

**Backpressure:** partial hypotheses go through a **single-slot "latest value" mailbox**
(`tokio::sync::watch`) so a slow consumer sees the newest partial rather than a queue of
stale ones — this bounds latency. Finals go through a **small bounded `mpsc` (capacity ~8)**
because finals must not be dropped.

**Reversibility: good.** Transport sits behind a small protocol module; swapping TCP for
named pipes later is localized and the framing/message types do not change.

## Process architecture — phase it

**Tauri-as-daemon (v1):** one process to build, sign, install, version. Right for learning
Rust fast. Risk: idle RAM and the real-time audio thread now share a process with WebView2,
which has non-trivial baseline RAM and whose GPU-process restarts sit uncomfortably close
to the audio path.

**Separate slim daemon + thin UI client (later):** literally matches "always-on background
service", never links WebView2, UI can close without stopping dictation, crash isolation
both ways. Costs a second process to install/sign/autostart/singleton.

**Recommendation: ship v1 as Tauri-as-daemon, but write the Rust core — audio, ring buffer,
orchestrator, IPC client — as a plain UI-agnostic library crate from day one**, with
`main()` in the Tauri binary just calling into it. The later extraction is then mechanical,
not a rewrite. This is the single most important structural discipline in this memo.

## Concurrency

`tokio` 1.53.1. **Async helps** downstream of the ring buffer: reading NDJSON from the
sidecar, serving UI IPC, silence timers, `spawn_blocking` SQLite, the orchestrator state
machine. **Async is a category error** on the cpal callback and the `WH_KEYBOARD_LL` hook —
both are synchronous time-constrained OS callbacks that cannot `.await`.

Pattern: dedicated OS thread owns the cpal stream (no tokio near it) → SPSC ring buffer →
tokio "capture supervisor" drains, resamples, writes to the sidecar → tokio hosts IPC,
SQLite via `spawn_blocking`, and the orchestrator. Tauri's runtime is already tokio, so no
impedance mismatch.

**Beginner sequencing, and this matters:** build the first working prototype **fully
synchronously** — mic to file, shell out to a Python script, print text — with **zero
tokio**. Learn ownership, threads, and channels first. Introduce tokio only when you
actually need to wait on multiple independent I/O sources. *Introducing async and
real-time audio discipline simultaneously on day one is the single biggest way to
overwhelm a Rust beginner on this project.*

## Persistence

**`rusqlite` 0.40.2 with the `bundled` feature** — statically compiles SQLite into the
binary, no DLL to ship or locate on a user's machine. Synchronous API, called via
`spawn_blocking`. **Difficulty 2/5.**

`sqlx` 0.9.0 is async-native but its compile-time-checked queries need a live DB at build
time or an offline cache step — extra pipeline machinery for a single-writer local SQLite
file. Not worth it here. Partially reversible: schema and SQL carry over, connection code
would be rewritten.

## Learn-this-first, in order (for the audio capture + ring buffer task)

1. Ownership and borrowing (`&` vs `&mut`, move semantics)
2. Closures and `move` closures — cpal's callback owns its captured state
3. `Send`/`Sync` — and what those compiler errors actually mean
4. Fixed-size arrays / `Vec` and pre-allocation discipline
5. `Arc<AtomicBool>` / `AtomicUsize` and `Ordering` basics — as distinct from `Mutex`
6. `Result` / `?` / why `.unwrap()` is forbidden on the audio thread
7. Enough traits/generics to read `cpal::Stream`, `SampleFormat`, `Producer<T>`/`Consumer<T>`
8. `Drop`/RAII and the slow-Drop footgun
9. Enough FFI reading comfort for a `windows-rs` signature (`HRESULT` conventions)

## Key uncertainties

- `ort` pre-1.0 for a long time — pin exactly, review changelogs on upgrade.
- `whisper-rs` cadence ambiguous — monitor.
- **CUDA/cuDNN redistribution terms unverified** — the one item with real commercial/legal
  exposure. Get a direct read before any CUDA-in-installer work.
- Tauri carrying an `embed-manifest`-injected uiAccess exe through its bundler — spike.
- `AvSetMmThreadCharacteristicsW` exact module path in `windows-rs` 0.62.2 — verify locally.
- Transparent + click-through + always-on-top on WebView2/Win11 — spike early.

## Sources

crates.io API for: tauri, cpal, rubato, rtrb, ringbuf, ort, whisper-rs, llama-cpp-2,
sherpa-rs, interprocess, tokio, rusqlite, sqlx, embed-manifest, winres, rmp-serde ·
GitHub API for the corresponding repos ·
[ort features](https://docs.rs/crate/ort/2.0.0-rc.13/features) ·
[Tauri sidecar](https://v2.tauri.app/develop/sidecar/) ·
[Tauri Windows installer](https://v2.tauri.app/distribute/windows-installer/) ·
[Tauri Windows signing](https://v2.tauri.app/distribute/sign/windows/) ·
[CUDA EULA](https://docs.nvidia.com/cuda/eula/index.html) *(summary only — verify primary text)*
