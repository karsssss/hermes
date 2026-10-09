from __future__ import annotations

from types import SimpleNamespace

from hermes_eval import t2d, t2e

RATE = 100  # fake samples per second; each sample's value is its absolute index


class FakeRec:
    """Emits fixed absolute-time words that fall wholly inside the decoded window."""

    def __init__(self, words):
        self.words = words  # [(token, start_s, end_s)]
        self.decoded: list[tuple[float, float]] = []

    def create_stream(self):
        return SimpleNamespace(accept_waveform=self._accept, result=None)

    def _accept(self, rate, samples):
        self._samples = samples

    def decode_stream(self, stream):
        s0 = self._samples[0] / RATE
        s1 = (self._samples[-1] + 1) / RATE
        self.decoded.append((s0, s1))
        ws = [w for w in self.words if w[1] >= s0 and w[2] <= s1]
        stream.result = SimpleNamespace(
            tokens=[w[0] for w in ws],
            timestamps=[w[1] - s0 for w in ws],
            durations=[w[2] - w[1] for w in ws],
        )


WORDS = [(" one", 0.2, 0.6), (" two", 0.8, 1.2), (" three", 1.4, 1.9), (" four", 2.1, 2.5)]
SAMPLES = list(range(3 * RATE))


def test_zero_left_context_is_task_2d_tail():
    rec = FakeRec(WORDS)
    words, lo = t2d._decode_tail(rec, SAMPLES, RATE, 1.3, None, 0.0)
    assert lo == 1.3 and rec.decoded == [(1.3, 3.0)]
    assert [w[0] for w in words] == ["three", "four"]


def test_left_context_re_reads_committed_audio_and_drops_it_by_midpoint():
    rec = FakeRec(WORDS)
    words, lo = t2d._decode_tail(rec, SAMPLES, RATE, 1.3, None, 1.0)
    assert rec.decoded == [(0.3, 3.0)]  # "two" heard again as context...
    assert [w[0] for w in words] == ["three", "four"]  # ...but not emitted twice
    assert words[0][1:] == [1.4, 1.9]  # timestamps stay absolute


def test_left_context_is_clamped_at_the_start_and_short_tails_are_skipped():
    rec = FakeRec(WORDS)
    _, lo = t2d._decode_tail(rec, SAMPLES, RATE, 0.5, None, 2.0)
    assert lo == 0.0
    words, _ = t2d._decode_tail(rec, SAMPLES, RATE, 2.95, None, 1.0)
    assert words == [] and len(rec.decoded) == 1  # < MIN_DECODE_S of tail: nothing decoded


def test_a_word_straddling_the_cut_belongs_to_the_side_its_midpoint_is_on():
    rec = FakeRec([(" a", 0.9, 1.25), (" b", 1.22, 1.6)])  # onset shifted one frame early
    words, _ = t2d._decode_tail(rec, SAMPLES, RATE, 1.3, None, 1.0)
    assert [w[0] for w in words] == ["b"]


def _row(final_words, cuts, audio_s=3.0):
    return {
        "audio_s": audio_s,
        "partials": [{"seg0": c} for c in [0.0, *cuts]],
        "final": {"words": final_words},
    }


def test_boundary_ops_classify_duplicates_drops_and_hallucinations():
    # offline: "one two three four"; cut at 1.3 between "two" and "three"
    dup = _row(
        [
            ["one", 0.2, 0.6],
            ["two", 0.8, 1.2],
            ["two", 1.3, 1.4],
            ["three", 1.4, 1.9],
            ["four", 2.1, 2.5],
        ],
        [1.3],
    )
    ops = t2e.boundary_ops(dup, "one two three four")
    assert ops["dup"] == 1 and ops["div"] == 1 and ops["div_boundary"] == 1

    drop = _row([["one", 0.2, 0.6], ["two", 0.8, 1.2], ["four", 2.1, 2.5]], [1.3])
    ops = t2e.boundary_ops(drop, "one two three four")
    assert ops["drop"] == 1 and ops["div_boundary"] == 1

    halluc = _row(
        [
            ["one", 0.2, 0.6],
            ["two", 0.8, 1.2],
            ["um", 1.3, 1.4],
            ["three", 1.4, 1.9],
            ["four", 2.1, 2.5],
        ],
        [1.3],
    )
    assert t2e.boundary_ops(halluc, "one two three four")["halluc"] == 1

    far = _row(
        [["one", 0.2, 0.6], ["two", 0.8, 1.2], ["three", 1.4, 1.9], ["for", 2.1, 2.5]], [0.7]
    )
    ops = t2e.boundary_ops(far, "one two three four")
    assert ops["div"] == 1 and ops["div_boundary"] == 0


def _arm(p95, delta, ci_low):
    return {"final": {"latency_p95_ms": p95}, "quality": {"delta_pp": delta, "ci_pp": [ci_low, 1]}}


def test_select_applies_the_pre_registered_rule():
    keep, why = t2e.select(
        {
            "0.0": _arm(440, 13.0, 10.0),
            "1.0": _arm(480, 0.3, -0.5),
            "2.0": _arm(495, 0.1, -0.6),
            "3.0": _arm(620, 0.0, -0.4),
        }
    )
    assert keep == 1.0  # 2.0 is better by < 0.25 pp, so the smaller context wins
    assert why["0.0"] == "control" and why["3.0"].startswith("eliminated: p95")
    keep, _ = t2e.select({"1.0": _arm(450, 1.2, 0.2), "2.0": _arm(520, 0.0, -1)})
    assert keep is None
