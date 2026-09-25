# ADR-0002 — Local-first inference, optional cloud

- **Status:** accepted
- **Date:** 2026-09-24

## Context

Three options: fully offline, cloud-first, or local-first with opt-in cloud escalation.
The choice is simultaneously an architecture decision and the product's market position.

Cloud-first buys the best accuracy per engineering hour and the easiest multilingual
coverage, at the cost of recurring per-user GPU spend, a latency floor, no offline use, and
— critically — it puts us in direct competition with a company that raised $280M to do
exactly that.

## Decision

Local-first. All core functionality runs on-device with no network. A cloud accuracy tier is
opt-in, per-utterance, and always indicated in the UI.

## Rationale

- **Privacy is not just compliance here — it unlocks the main accuracy feature.** Context
  harvesting (`02-architecture.md` §5.4) reads the focused field, the clipboard, and the
  open repo's identifiers. That is only defensible if the data never leaves the machine. A
  cloud product structurally cannot offer W3.
- Zero marginal cost per user makes a free OSS tier sustainable, which is the open-core
  strategy in `01-strategy.md` §5.
- Latency floor of a local model beats any round trip.
- It's the honest differentiator against the incumbent rather than a worse version of them.

## Consequences

- Constrained to models that fit ~5 GB VRAM, and a CPU-only path must be first-class.
- Some hard audio and rare languages will be worse than cloud. Mitigated by the opt-in
  escalation tier; must be stated honestly in the UI rather than hidden.
- Model distribution, versioning, and updates become our problem (multi-GB downloads,
  integrity verification, disk usage).
- Users' hardware variance becomes a support surface.
