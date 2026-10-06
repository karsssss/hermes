from __future__ import annotations

import math

import pytest

from hermes_eval import confidence_eval as ce


def test_auroc_perfect_inverted_and_tied():
    assert ce.auroc([0.9, 0.8], [0.1, 0.2]) == 1.0
    assert ce.auroc([0.1, 0.2], [0.9, 0.8]) == 0.0
    assert ce.auroc([0.5, 0.5], [0.5]) == 0.5
    assert ce.auroc([], [0.1]) is None


def test_auroc_matches_pairwise_definition():
    pos, neg = [0.3, 0.7, 0.7, 0.9], [0.1, 0.7, 0.8]
    pairs = [(p > n) + 0.5 * (p == n) for p in pos for n in neg]
    assert ce.auroc(pos, neg) == pytest.approx(sum(pairs) / len(pairs))


def test_constant_signal_scores_at_chance_not_by_arrival_order():
    scores = [1.0] * 10
    errors = [True, True] + [False] * 8  # errors arrive first
    assert ce.recall_at(scores, errors, 0.2) == 0.0
    assert ce.average_precision(scores, errors) == pytest.approx((1 / 9 + 2 / 10) / 2)


def test_average_precision_and_recall_on_a_perfect_ranker():
    scores = [0.1, 0.2, 0.9, 0.95, 0.99]
    errors = [True, True, False, False, False]
    assert ce.average_precision(scores, errors) == 1.0
    assert ce.recall_at(scores, errors, 0.2) == 0.5
    assert ce.recall_at(scores, errors, 0.4) == 1.0


def test_ece_zero_when_calibrated_and_large_when_overconfident():
    assert ce.ece([0.25] * 4, [True, False, False, False]) == pytest.approx(0.0)
    assert ce.ece([0.99] * 4, [False] * 4) == pytest.approx(0.99)


def test_group_words_uses_leading_space():
    pieces = [" Al", "les", " hat", ",", " ein"]
    assert ce.group_words(pieces) == [[0, 1], [2, 3], [4]]


def test_word_scores_exclude_punctuation_pieces():
    pieces = [" hat", ","]
    _, scores = ce.word_scores(pieces, {"s": [0.9, 0.1]}, {"m": "s:min"})
    assert scores == [{"m": 0.9}]


def test_labels_follow_wer_alignment_and_split_compounds():
    # "kube-system" is one ASR word but two WER units, both sharing the word's score.
    pieces = [" kube", "-", "system", " pods", " now"]
    words, scores = ce.word_scores(pieces, {"s": [0.9, 0.5, 0.8, 0.2, 0.7]}, {"m": "s:min"})
    lab = ce.label_units("kube system pod", pieces, words, scores)
    assert [u.text for u in lab.units] == ["kube", "system", "pods", "now"]
    assert [u.correct for u in lab.units] == [True, True, False, False]
    assert lab.units[0].scores["m"] == lab.units[1].scores["m"] == 0.8
    assert lab.deletions == 0 and lab.ref_len == 3


def test_deletions_are_counted_not_scored():
    pieces = [" hello"]
    words, scores = ce.word_scores(pieces, {"s": [0.9]}, {"m": "s:min"})
    lab = ce.label_units("hello there world", pieces, words, scores)
    assert len(lab.units) == 1
    assert lab.deletions == 2


def test_bootstrap_is_seeded_and_paired():
    groups = [
        [ce.Unit("a", 0, True, {"x": 0.9, "y": 0.9}), ce.Unit("b", 1, False, {"x": 0.1, "y": 0.9})],
        [ce.Unit("c", 0, True, {"x": 0.8, "y": 0.2}), ce.Unit("d", 1, False, {"x": 0.3, "y": 0.4})],
        [ce.Unit("e", 0, True, {"x": 0.7, "y": 0.5}), ce.Unit("f", 1, False, {"x": 0.2, "y": 0.6})],
    ]
    a = ce.bootstrap_auroc(groups, "x", "y", resamples=200, seed=3)
    b = ce.bootstrap_auroc(groups, "x", "y", resamples=200, seed=3)
    assert a == b
    assert a["delta_vs_baseline"] is not None and a["delta_vs_baseline"] > 0


def test_spearman():
    assert ce.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert ce.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0


def test_step_measures_bounds():
    np = pytest.importorskip("numpy")
    from hermes_eval.tdt_probe import step_measures

    v = 8193
    peaked = np.full(v, -50.0, dtype=np.float32)
    peaked[7] = 50.0
    uniform = np.zeros(v, dtype=np.float32)
    dur = np.zeros(5, dtype=np.float32)
    hi, lo = step_measures(peaked, dur), step_measures(uniform, dur)
    for k in ("gibbs", "tsallis", "renyi"):
        assert hi[k] == pytest.approx(1.0, abs=1e-6)
        assert lo[k] == pytest.approx(0.0, abs=1e-6)
    assert hi["logp"] == pytest.approx(0.0, abs=1e-6)
    assert lo["logp"] == pytest.approx(-math.log(v), rel=1e-6)
    assert lo["dur_gibbs"] == pytest.approx(0.0, abs=1e-9)
    assert lo["margin"] == 0.0


def test_resume_keeps_complete_rows_and_cuts_a_torn_tail(tmp_path):
    from hermes_eval.t2b import completed_ids

    raw = tmp_path / "raw.jsonl"
    raw.write_bytes(b'{"id": "a"}\n{"id": "b"}\n{"id": "c", "probe": {"st')
    assert completed_ids(raw) == {"a", "b"}
    assert raw.read_bytes() == b'{"id": "a"}\n{"id": "b"}\n'
    assert completed_ids(raw) == {"a", "b"}  # idempotent on a clean file


def test_resume_refuses_duplicates(tmp_path):
    from hermes_eval.t2b import completed_ids

    raw = tmp_path / "raw.jsonl"
    raw.write_bytes(b'{"id": "a"}\n{"id": "a"}\n')
    with pytest.raises(ValueError, match="duplicate"):
        completed_ids(raw)


def test_resume_is_recorded_in_run_json(tmp_path):
    import json

    from hermes_eval.t2b import record_resume

    (tmp_path / "run.json").write_text('{"run_id": "x"}', encoding="utf-8")
    record_resume(tmp_path, 91, {"sha": "abc", "dirty": False})
    run = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert run["run_id"] == "x"
    assert run["resumes"][0]["rows_present"] == 91
