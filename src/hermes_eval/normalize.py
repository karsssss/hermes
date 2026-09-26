"""Text normalization modes.

Normalization is the single biggest gaming vector in ASR benchmarking (R6): published
"Whisper achieves X% WER" numbers are computed with a normalizer that erases casing,
punctuation, fillers, contractions and number formatting — i.e. exactly the dimensions
this product is about. So the modes here are few, explicit, versioned, and applied
identically to reference and hypothesis.

Modes
-----
raw       NFC + whitespace collapse only. The F-WER scoring mode: case-sensitive,
          punctuation-sensitive, on the literal text that would be injected.
casefold  raw + lowercase. Exists solely so that (F-WER - WER_casefold) isolates the
          casing error rate.
basic     casefold + strip Unicode punctuation. The plain-WER mode, for comparability
          with published numbers. Nothing more.

`basic` deliberately does NOT: remove fillers, expand contractions, map British to
American spelling, or convert number words to digits. Each of those is a judgement call
that flatters whoever designed it, and we would be scoring our own ITN with an eraser.
A vendored, version-pinned Whisper `EnglishTextNormalizer` is a separate, clearly
labelled secondary score (deferred; see docs/CURRENT.md).
"""

from __future__ import annotations

import re
import unicodedata

NORMALIZER_VERSION = "hermes/1"

MODES = ("raw", "casefold", "basic")

_WS = re.compile(r"\s+")


def _collapse(text: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFC", text)).strip()


# Apostrophes are deleted rather than replaced with a space, so that a backend writing
# "dont" scores as one token against "don't" instead of being penalised twice. Every
# other punctuation mark becomes a space, so "kube-system" and "tokio::sync" split into
# the words a listener would hear. Symbols (S*) are left alone: + and = carry meaning in
# dev speech. This is a judgement call, applied identically to both sides.
_APOSTROPHES = frozenset("'’ʼ")


def _strip_punctuation(text: str) -> str:
    out = []
    for ch in text:
        if ch in _APOSTROPHES:
            continue
        out.append(" " if unicodedata.category(ch).startswith("P") else ch)
    return _collapse("".join(out))


def normalize(text: str, mode: str = "raw") -> str:
    if mode == "raw":
        return _collapse(text)
    if mode == "casefold":
        return _collapse(text).lower()
    if mode == "basic":
        return _strip_punctuation(_collapse(text).lower())
    raise ValueError(f"unknown normalization mode: {mode!r} (expected one of {MODES})")


def tokenize(text: str, mode: str = "raw") -> list[str]:
    """Whitespace tokenization after normalization.

    In `raw` mode punctuation stays attached to its word, so a missing comma makes that
    whole token wrong. That is intentional: F-WER scores what the user sees.
    """
    norm = normalize(text, mode)
    return norm.split() if norm else []
