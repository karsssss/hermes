from __future__ import annotations

from types import SimpleNamespace

from hermes_eval import t2d


def _res(tokens, starts, durs):
    return SimpleNamespace(tokens=tokens, timestamps=starts, durations=durs)


def test_words_join_subwords_and_punctuation_and_offset():
    res = _res(
        [" Y", "es", ",", " that", " was", "."],
        [0.0, 0.32, 0.48, 0.64, 0.96, 1.2],
        [0.32, 0.16, 0.16, 0.32, 0.24, 0.08],
    )
    words = t2d._words(res, 2.0)
    assert [w[0] for w in words] == ["Yes,", "that", "was."]
    assert words[0][1:] == [2.0, 2.64]
    assert words[2][1:] == [2.96, 3.28]


def test_cut_point_sits_between_words_and_never_past_the_next_onset():
    assert t2d._cut_point(["a", 0.0, 1.0], ["b", 1.2, 1.5]) == 1.1
    # A long pause: lean toward the next onset, at most 0.24 s before it.
    assert t2d._cut_point(["a", 0.0, 1.0], ["b", 3.0, 3.3]) == 2.76
    # Overlapping timestamps: never cut after the next word starts.
    assert t2d._cut_point(["a", 0.0, 1.4], ["b", 1.2, 1.5]) == 1.2


def _row(partials, final_words, latency_ms=100.0, audio_s=3.0):
    return {
        "audio_s": audio_s,
        "partials": [
            {"emit_s": e, "audio_s": a, "seg0": 0.0, "ms": 50.0, "words": w} for e, a, w in partials
        ],
        "final": {"words": final_words, "latency_ms": latency_ms},
    }


def test_stream_metrics_count_revisions_and_stable_display_lag():
    final = [["Hello", 0.2, 0.6], ["world.", 0.8, 1.4]]
    row = _row(
        [
            (0.6, 0.5, []),
            (1.1, 1.0, [["Hello", 0.6], ["word", 1.0]]),
            (1.6, 1.5, [["Hello", 0.6], ["world", 1.4]]),
        ],
        final,
    )
    m = t2d._stream_utt(row)
    assert m["empty_partials"] == 1
    assert m["ttfp_s"] == 1.1 and m["ttfup_s"] == 1.1
    assert m["ttfup_from_onset_s"] == 0.9
    # "word" -> "world" is one unstable word; "world" -> "world." is not, once normalized.
    assert m["unstable_norm"] == 1
    assert m["unstable_raw"] == 2
    assert m["revising_partials"] == 1
    # "Hello" stable from the partial emitted at 1.1 s; "world" from 1.6 s.
    assert m["word_lag_s"] == [0.5, 0.2]
    assert m["cadence_s"] == [0.5, 0.5]


def test_words_never_shown_in_a_partial_lag_until_the_final():
    row = _row([(0.6, 0.5, [])], [["Hi", 0.1, 0.4]], latency_ms=250.0, audio_s=1.0)
    m = t2d._stream_utt(row)
    assert m["ttfup_s"] is None
    assert m["word_lag_s"] == [0.85]
