from __future__ import annotations

import pytest

from hermes_eval.bootstrap import apply_decision_rule, paired_bootstrap
from hermes_eval.metrics import Counts


def counts(errors_per_utt: list[int], ref_len: int = 10) -> list[Counts]:
    return [Counts(e, ref_len, e, 0, 0) for e in errors_per_utt]


BASELINE = counts([2, 3, 1, 4, 2, 3, 2, 1, 5, 2] * 4)  # n = 40, 25 errors per 10 utts


def test_same_seed_is_bit_identical():
    a = paired_bootstrap(BASELINE, BASELINE, seed=42, resamples=500)
    b = paired_bootstrap(BASELINE, BASELINE, seed=42, resamples=500)
    assert a == b


def test_the_seed_moves_the_interval_but_not_the_point_estimate():
    candidate = counts([1, 3, 1, 4, 2, 3, 2, 1, 5, 2] * 4)
    a = paired_bootstrap(BASELINE, candidate, seed=1, resamples=2000)
    b = paired_bootstrap(BASELINE, candidate, seed=2, resamples=2000)
    assert a.delta_pp == b.delta_pp  # the point estimate does not depend on the seed
    # The interval is an estimate, so it may move with the seed — but only slightly.
    # If it moved a lot, the resample count would be too low to report.
    assert abs(a.ci_low_pp - b.ci_low_pp) < 0.5
    assert abs(a.ci_high_pp - b.ci_high_pp) < 0.5


def test_identical_systems_have_zero_delta_and_a_ci_containing_zero():
    r = paired_bootstrap(BASELINE, BASELINE, seed=7, resamples=1000)
    assert r.delta_pp == 0.0
    assert r.ci_low_pp == 0.0 and r.ci_high_pp == 0.0
    assert not r.ci_excludes_zero


def test_clearly_better_candidate_excludes_zero():
    candidate = counts([0] * 40)
    r = paired_bootstrap(BASELINE, candidate, seed=7, resamples=2000)
    assert r.rate_a == pytest.approx(0.25)
    assert r.rate_b == 0.0
    assert r.delta_pp == pytest.approx(-25.0)
    assert r.ci_high_pp < 0
    assert r.ci_excludes_zero


def test_seed_and_resamples_are_recorded():
    r = paired_bootstrap(BASELINE, BASELINE, seed=123, resamples=321)
    assert (r.seed, r.resamples, r.n, r.confidence) == (123, 321, 40, 0.95)
    assert r.to_json()["ci_excludes_zero"] is False


def test_mismatched_lengths_are_rejected():
    with pytest.raises(ValueError, match="same utterances in the same order"):
        paired_bootstrap(BASELINE, BASELINE[:10], seed=1, resamples=10)


def test_empty_set_is_rejected():
    with pytest.raises(ValueError, match="empty set"):
        paired_bootstrap([], [], seed=1, resamples=10)


# --------------------------------------------------------------- the decision rule


def better(delta_errors: int = 1) -> list[Counts]:
    return counts([max(0, e - delta_errors) for e in [2, 3, 1, 4, 2, 3, 2, 1, 5, 2] * 4])


def test_verdict_improvement_when_ci_excludes_zero_and_effect_is_large():
    r = paired_bootstrap(BASELINE, better(), seed=7, resamples=2000)
    decision = apply_decision_rule(r)
    assert decision.verdict == "improvement"


def test_verdict_regression_when_candidate_is_worse():
    r = paired_bootstrap(better(), BASELINE, seed=7, resamples=2000)
    assert apply_decision_rule(r).verdict == "regression"


def test_verdict_noise_when_ci_contains_zero():
    r = paired_bootstrap(BASELINE, BASELINE, seed=7, resamples=500)
    assert apply_decision_rule(r).verdict == "noise"


def test_tiny_but_significant_effect_is_still_noise():
    # 40 utterances, one fewer error in total: significant by CI, far too small to ship.
    tiny = list(BASELINE)
    tiny[0] = Counts(tiny[0].errors - 1, tiny[0].ref_len, tiny[0].sub - 1, 0, 0)
    r = paired_bootstrap(BASELINE, tiny, seed=7, resamples=2000)
    assert abs(r.delta_pp) < 0.3
    assert apply_decision_rule(r).verdict == "noise"


def test_ewer_regression_blocks_an_fwer_win():
    fwer = paired_bootstrap(BASELINE, better(), seed=7, resamples=2000)
    ewer = paired_bootstrap(
        counts([0] * 40, ref_len=4), counts([2] * 40, ref_len=4), seed=7, resamples=2000
    )
    decision = apply_decision_rule(fwer, ewer=ewer)
    assert decision.verdict == "blocked_ewer_regression"
    assert any("rare-word damage" in r for r in decision.reasons)


def test_latency_gate_blocks_regardless_of_accuracy():
    fwer = paired_bootstrap(BASELINE, better(), seed=7, resamples=500)
    decision = apply_decision_rule(fwer, latency_p95_ms=900.0, latency_budget_ms=700.0)
    assert decision.verdict == "blocked_latency"


def test_latency_inside_budget_does_not_block():
    fwer = paired_bootstrap(BASELINE, better(), seed=7, resamples=2000)
    decision = apply_decision_rule(fwer, latency_p95_ms=650.0, latency_budget_ms=700.0)
    assert decision.verdict == "improvement"


def test_min_effect_threshold_is_configurable():
    fwer = paired_bootstrap(BASELINE, better(), seed=7, resamples=2000)
    assert apply_decision_rule(fwer, min_effect_pp=99.0).verdict == "noise"
