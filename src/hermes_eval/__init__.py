"""Hermes evaluation harness.

Scope (v0): scoring only. No model, no audio pipeline, no Rust, no NLP. The harness
consumes a manifest of utterances plus an adapter that returns final text, and emits an
immutable, reproducible run record.

Deliberately dependency-free at runtime: the scoring path has to be defensible line by
line, and a published benchmark cannot blame its numbers on a third-party WER package.
"""

HARNESS_VERSION = "0.1.0"
