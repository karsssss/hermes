from __future__ import annotations

from hermes_eval.align import Op, align, error_counts
from hermes_eval.metrics import counts_from

REF = ["the", "cat", "sat", "on", "the", "mat"]


def test_identical_sequences_have_no_errors():
    a = align(REF, REF)
    assert a.errors == 0
    assert all(e.op is Op.EQUAL for e in a.edits)
    assert counts_from(REF, REF).rate == 0.0


def test_single_substitution():
    hyp = ["the", "cat", "sat", "on", "a", "mat"]
    c = counts_from(REF, hyp)
    assert (c.sub, c.ins, c.dele) == (1, 0, 0)
    assert c.rate == 1 / 6


def test_single_deletion():
    hyp = ["the", "cat", "sat", "on", "the"]
    c = counts_from(REF, hyp)
    assert (c.sub, c.ins, c.dele) == (0, 0, 1)
    assert c.rate == 1 / 6


def test_single_insertion():
    hyp = ["the", "cat", "sat", "on", "the", "big", "mat"]
    c = counts_from(REF, hyp)
    assert (c.sub, c.ins, c.dele) == (0, 1, 0)
    assert c.rate == 1 / 6


def test_empty_hypothesis_is_all_deletions():
    c = counts_from(REF, [])
    assert (c.errors, c.ref_len, c.dele) == (6, 6, 6)
    assert c.rate == 1.0


def test_empty_reference_with_hypothesis_saturates_at_one():
    # Guard only: the manifest validator rejects empty references.
    c = counts_from([], ["hello"])
    assert c.ref_len == 0
    assert c.rate == 1.0


def test_wer_can_exceed_one():
    c = counts_from(["a"], ["b", "c", "d"])
    assert c.errors == 3
    assert c.rate == 3.0


def test_edit_indices_are_consistent():
    hyp = ["the", "cat", "sat", "on", "a", "mat"]
    a = align(REF, hyp)
    for edit in a.edits:
        if edit.op in (Op.EQUAL, Op.SUB):
            assert edit.ref_index is not None and edit.hyp_index is not None
        elif edit.op is Op.DEL:
            assert edit.ref_index is not None and edit.hyp_index is None
        else:
            assert edit.ref_index is None and edit.hyp_index is not None
    assert [e.ref_index for e in a.edits if e.ref_index is not None] == list(range(6))


def test_error_counts_matches_alignment():
    hyp = ["a", "cat", "sat", "under", "the", "mat", "today"]
    errors, ref_len = error_counts(REF, hyp)
    assert ref_len == 6
    assert errors == align(REF, hyp).errors


def test_alignment_is_deterministic_under_ties():
    # Ambiguous alignment: several equal-cost paths exist. The result must not drift.
    ref, hyp = ["a", "b", "c"], ["c", "b", "a"]
    first = align(ref, hyp)
    for _ in range(5):
        assert align(ref, hyp) == first
