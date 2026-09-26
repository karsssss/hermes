from __future__ import annotations

from pathlib import Path

import pytest

from hermes_eval.manifest import Record, Slot
from hermes_eval.metrics import (
    _slot_present,
    aggregate,
    entity_counts,
    entity_spans,
    punctuation_counts,
    score_utterance,
)
from hermes_eval.normalize import tokenize

META = {"language": "en", "accent": "uk-L1", "domain": "general", "category": "prose"}


def record(reference: str, **kwargs) -> Record:
    return Record(
        id=kwargs.pop("id", "u1"),
        audio=Path("audio/u1.wav"),
        reference=reference,
        metadata=dict(META),
        **kwargs,
    )


def agg(reference: str, hypothesis: str, **kwargs) -> dict:
    return aggregate([score_utterance(record(reference, **kwargs), hypothesis)])


# ------------------------------------------------------------------ F-WER vs WER


def test_casing_error_is_invisible_to_wer_and_visible_to_fwer():
    a = agg("Hello World", "hello world")
    assert a["fwer"] == 1.0
    assert a["wer"] == 0.0
    assert a["wer_casefold"] == 0.0
    assert a["casing_error_rate_pp"] == 100.0


def test_punctuation_error_is_invisible_to_wer_and_visible_to_fwer():
    a = agg("Hello, world.", "Hello world")
    assert a["fwer"] == 1.0
    assert a["wer"] == 0.0
    # Punctuation, not casing: the decomposition must attribute it correctly.
    assert a["casing_error_rate_pp"] == 0.0


def test_clean_hypothesis_scores_zero_everywhere():
    text = "Ship the release on Friday, but only if the tests pass."
    a = agg(text, text)
    assert a["fwer"] == 0.0
    assert a["wer"] == 0.0
    assert a["casing_error_rate_pp"] == 0.0
    assert a["punctuation_f1_micro"] == 1.0


def test_aggregate_is_corpus_level_not_macro_average():
    # Two utterances: 1 error / 2 tokens, and 0 errors / 8 tokens.
    scores = [
        score_utterance(record("a b", id="u1"), "a c"),
        score_utterance(record("c d e f g h i j", id="u2"), "c d e f g h i j"),
    ]
    a = aggregate(scores)
    assert a["fwer"] == round(1 / 10, 6)  # corpus, not (0.5 + 0.0) / 2


# ----------------------------------------------------------------- punctuation F1


def test_punctuation_f1_counts_per_class():
    counts = punctuation_counts("Hello, world. Bye!", "Hello world. Bye.")
    assert (counts[","].tp, counts[","].fp, counts[","].fn) == (0, 0, 1)
    assert (counts["."].tp, counts["."].fp, counts["."].fn) == (1, 1, 0)
    assert (counts["!"].tp, counts["!"].fp, counts["!"].fn) == (0, 0, 1)
    assert counts["."].precision == 0.5
    assert counts["."].recall == 1.0
    assert counts["."].f1 == pytest.approx(2 / 3)


def test_punctuation_scoring_ignores_the_words_own_casing():
    counts = punctuation_counts("Hello, world.", "hello, WORLD.")
    assert counts[","].tp == 1
    assert counts["."].tp == 1
    assert counts[","].fn == 0


def test_free_standing_mark_attaches_to_the_previous_word():
    counts = punctuation_counts("Hello , world .", "Hello, world.")
    assert counts[","].tp == 1
    assert counts["."].tp == 1


def test_spurious_punctuation_is_a_false_positive():
    counts = punctuation_counts("Hello world", "Hello, world.")
    assert counts[","].fp == 1
    assert counts["."].fp == 1
    assert counts[","].tp == 0


# ------------------------------------------------------------------------- E-WER


def test_entity_spans_locate_multiword_entities():
    ref = tokenize("Check kubectl get pods -n kube-system now.", "basic")
    span_of, unmatched = entity_spans(ref, ["kubectl get pods", "kube-system"])
    assert unmatched == []
    assert [i for i, s in enumerate(span_of) if s == 0] == [1, 2, 3]
    assert [i for i, s in enumerate(span_of) if s == 1] == [5, 6]


def test_entity_absent_from_its_own_reference_is_reported():
    ref = tokenize("Check the logs.", "basic")
    span_of, unmatched = entity_spans(ref, ["kubectl"])
    assert unmatched == ["kubectl"]
    assert set(span_of) == {-1}


def test_ewer_counts_only_entity_tokens():
    r = record("run kubectl get pods now", entities=("kubectl get pods",))
    s = score_utterance(r, "run cubectl get pods now")
    assert s.wer.errors == 1 and s.wer.ref_len == 5
    assert s.ewer.errors == 1 and s.ewer.ref_len == 3
    assert s.ewer.rate == 1 / 3


def test_ewer_ignores_errors_outside_entity_spans():
    r = record("run kubectl get pods now", entities=("kubectl get pods",))
    s = score_utterance(r, "ran kubectl get pods later")
    assert s.wer.errors == 2
    assert s.ewer.errors == 0
    assert s.ewer.rate == 0.0


def test_ewer_counts_insertions_strictly_inside_a_span():
    ref = tokenize("run kubectl get pods now", "basic")
    hyp = tokenize("run kubectl xx get pods now", "basic")
    span_of, _ = entity_spans(ref, ["kubectl get pods"])
    c = entity_counts(ref, hyp, span_of)
    assert (c.ins, c.errors, c.ref_len) == (1, 1, 3)


def test_ewer_ignores_insertions_outside_a_span():
    ref = tokenize("run kubectl get pods now", "basic")
    hyp = tokenize("run kubectl get pods right now", "basic")
    span_of, _ = entity_spans(ref, ["kubectl get pods"])
    assert entity_counts(ref, hyp, span_of).errors == 0


def test_ewer_is_null_when_no_utterance_carries_entities():
    a = agg("just some words", "just some words")
    assert a["ewer"] is None
    assert a["ewer_reference_tokens"] == 0


# --------------------------------------------------------------------------- ITN


def test_itn_slot_presence_respects_token_boundaries():
    assert _slot_present("meet at 3:30 today", "3:30")
    assert not _slot_present("meet at 30 past", "3")
    assert _slot_present("revenue rose 12% again", "12%")
    assert not _slot_present("revenue rose 120% again", "12")


def test_itn_slot_error_rate_counts_misses():
    r = record(
        "The review is at 3:30 p.m. on 2026-10-02.",
        itn_slots=(Slot("3:30", "time"), Slot("2026-10-02", "date")),
    )
    s = score_utterance(r, "The review is at 3:30 p.m. on October second twenty twenty six.")
    assert s.itn_slots_total == 2
    assert s.itn_slots_missed == 1
    a = aggregate([s])
    assert a["itn"]["slot_error_rate"] == 0.5
    # Spurious ITN output is not detectable in v0; the report must not imply otherwise.
    assert a["itn"]["insertions_measured"] is False


def test_itn_slot_error_rate_is_null_without_slots():
    a = agg("no slots here", "no slots here")
    assert a["itn"]["slot_error_rate"] is None


# ---------------------------------------------------------------------- latency


def test_latency_percentiles_are_nearest_rank():
    scores = []
    for i, ms in enumerate([100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]):
        scores.append(score_utterance(record("a b", id=f"u{i}"), "a b", latency_ms=ms))
    lat = aggregate(scores)["latency_ms"]
    assert lat["n"] == 10
    assert lat["p50"] == 500
    assert lat["p95"] == 1000
    assert lat["p99"] == 1000
