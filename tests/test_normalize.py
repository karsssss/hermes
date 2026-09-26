from __future__ import annotations

import pytest

from hermes_eval.normalize import normalize, tokenize


def test_raw_collapses_whitespace_only():
    assert normalize("  Hello,   world! \n", "raw") == "Hello, world!"


def test_raw_preserves_case_and_punctuation():
    assert tokenize("Hello, world!", "raw") == ["Hello,", "world!"]


def test_casefold_lowers_but_keeps_punctuation():
    assert normalize("Hello, World!", "casefold") == "hello, world!"


def test_basic_strips_punctuation_and_case():
    assert normalize("Hello, World!", "basic") == "hello world"


def test_basic_deletes_apostrophes_but_splits_other_punctuation():
    # "dont" should cost one token, not two, against "don't".
    assert tokenize("don't", "basic") == ["dont"]
    assert tokenize("don’t", "basic") == ["dont"]
    assert tokenize("kube-system", "basic") == ["kube", "system"]
    assert tokenize("tokio::sync::mpsc::unbounded_channel", "basic") == [
        "tokio",
        "sync",
        "mpsc",
        "unbounded",
        "channel",
    ]


def test_basic_keeps_symbols_that_carry_meaning():
    # ~ + = are Unicode symbols, not punctuation; dev speech depends on them.
    assert tokenize("HEAD~3", "basic") == ["head~3"]
    assert tokenize("a+b=c", "basic") == ["a+b=c"]


def test_nfc_composition_is_applied():
    decomposed = "éclair"
    assert normalize(decomposed, "raw") == "éclair"
    assert len(normalize(decomposed, "raw")) == 6


def test_empty_text_tokenizes_to_nothing():
    assert tokenize("   ", "raw") == []
    assert tokenize("", "basic") == []


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="unknown normalization mode"):
        normalize("x", "whisper")
