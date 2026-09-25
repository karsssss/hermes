# ADR-0003 — Python prototype, then Rust core

- **Status:** accepted
- **Date:** 2026-09-24

## Context

The final product needs a real-time audio thread, small binary, low idle RAM, and fast cold
start — all arguments for Rust. But the pipeline design is unproven: model choice, biasing
approach, correction strategy, and injection cascade will all change substantially during
Phases 0–2. Writing that exploration in Rust means porting decisions that are about to be
discarded.

## Decision

Phases 0–2 in Python 3.11. Phase 3 ports the hot path (`hermesd`) to Rust with a Tauri UI.

## Rationale

- ML experimentation velocity in Python is several times higher, and Phases 0–2 are almost
  entirely experimentation.
- The Python prototype is throwaway *by design*, which makes it cheap to be wrong.
- By Phase 3 the design has stabilized and the port is mechanical rather than exploratory.
- The genuine Rust wins (lock-free real-time audio thread, no GC pauses, 10 MB binary,
  sub-2 s cold start, signed installer) all land in Phase 3 anyway.

## Consequences

- A real rewrite is scheduled, not avoided. This is a deliberate cost, and the schedule
  in `03-roadmap.md` accounts for it.
- The Python code must keep clean seams at the same boundaries the Rust version will have
  (`AsrEngine`, `Injector`, `ContextHarvester`, `AudioSource`), or the port stops being
  mechanical. Enforce this in review.
- `sounddevice`'s C callback with a preallocated numpy ring buffer is adequate for Phase
  0–2 audio; do not over-engineer it, it is being replaced.
- Rust toolchain is not yet installed on the dev machine — install `rustup` at the start of
  Phase 3, not before.

## Alternatives rejected

- **Rust from day one** — no rewrite, but early iteration slows to a crawl in exactly the
  phases that need speed.
- **Python + Electron throughout** — ships a 300 MB+ app with a Python runtime and high idle
  RAM; unacceptable for an always-on background service.
- **C++ core** — maximum control, slowest to write, smallest contributor pool for an
  open-core project that depends on community contributions.
