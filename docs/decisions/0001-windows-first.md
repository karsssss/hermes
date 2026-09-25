# ADR-0001 — Windows first

- **Status:** accepted
- **Date:** 2026-09-24

## Context

The product must eventually be cross-platform, but the platform-specific layer (audio
capture, global hotkeys, and especially text injection) is a large fraction of the
engineering effort and differs completely per OS. Building all three at once triples the
hardest work before any of it is proven.

The good local-first dictation products (Superwhisper, MacWhisper, VoiceInk) are macOS-only.
The cross-platform ones (Wispr Flow, Aqua) are cloud-first. Windows has the weakest native
dictation and the thinnest local third-party options.

## Decision

Windows 11 first. macOS and Linux deferred to Phase 4.

## Rationale

- Largest capability gap vs. the OS baseline, so the product has the most room to be
  obviously better.
- Thinnest competition in the local-first niche.
- The developer machine is already Windows 11 — no hardware purchase, and the developer is
  user zero (`01-strategy.md` §6).
- The hardest Windows problem (injection into Electron apps and elevated processes,
  `02-architecture.md` §6) is precisely the kind of unglamorous work a funded consumer
  competitor deprioritizes, which makes it defensible.

## Consequences

- The paying-user density is lower on Windows than macOS for this category today. Accepted:
  the beachhead is developers and technical users, who are well represented on Windows.
- Core logic must stay behind platform traits/protocols from day one so the later port is
  mechanical. No Win32 types in the pipeline code.
- UIPI limits injection into elevated processes; Phase 1 degrades gracefully, Phase 3 ships
  a signed helper.
