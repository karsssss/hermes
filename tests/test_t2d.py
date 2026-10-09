from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from hermes_eval import asr_sherpa, t2d


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


# ---------------------------------------------------------------- streaming resume

IDS = ["u1", "u2", "u3"]


@pytest.fixture
def fake_worker(monkeypatch, tmp_path):
    """run_stream against a 3-utterance manifest, with no model, audio or Win32 calls."""
    records = [SimpleNamespace(id=i, audio=i, metadata={}) for i in IDS]
    streamed: list[str] = []

    def utterance(rec, samples, rate, policy, left_s=0.0):
        streamed.append(samples)
        return {"audio_s": 1.0, "partials": [], "final": {"latency_ms": 1.0, "inflight_wait_ms": 0}}

    monkeypatch.setattr(t2d, "load_strict", lambda _: SimpleNamespace(records=records))
    monkeypatch.setattr(asr_sherpa, "read_wav", lambda audio: (audio, 16000, 1.0))
    monkeypatch.setattr(t2d, "set_qos", lambda qos: {"qos": qos})
    monkeypatch.setattr(t2d, "load_recognizer", lambda threads: (None, {"load_ms": 1.0}))
    monkeypatch.setattr(t2d, "stream_utterance", utterance)
    monkeypatch.setattr(t2d, "_ws", dict)
    monkeypatch.setattr(t2d, "git_state", lambda repo: {"sha": "abc", "dirty": False})
    (tmp_path / "run.json").write_text('{"run_id": "x"}\n', encoding="utf-8")
    return tmp_path, streamed


def _line(rid: str) -> str:
    return json.dumps({"id": rid, "final": {}}) + "\n"


def _ids(path):
    return [json.loads(x)["id"] for x in path.read_text(encoding="utf-8").splitlines()]


def test_stream_new_run_writes_every_row_and_a_summary(fake_worker):
    run_dir, streamed = fake_worker
    t2d.run_stream(run_dir, 4, "commit", "high")
    assert streamed == IDS
    assert _ids(run_dir / "stream-commit-t4.jsonl") == IDS
    summary = json.loads((run_dir / "stream-commit-t4.json").read_text(encoding="utf-8"))
    assert [s["rows_present"] for s in summary["sessions"]] == [0]


def test_stream_resume_skips_completed_ids_and_keeps_their_rows(fake_worker):
    run_dir, streamed = fake_worker
    path = run_dir / "stream-commit-t4.jsonl"
    path.write_text(_line("u1"), encoding="utf-8")
    t2d.run_stream(run_dir, 4, "commit", "high")
    assert streamed == ["u2", "u3"]
    assert path.read_text(encoding="utf-8").startswith(_line("u1"))
    assert _ids(path) == IDS


def test_stream_resume_cuts_a_torn_final_line_and_redoes_that_utterance(fake_worker):
    run_dir, streamed = fake_worker
    path = run_dir / "stream-commit-t4.jsonl"
    path.write_text(_line("u1") + '{"id": "u2", "fin', encoding="utf-8")
    t2d.run_stream(run_dir, 4, "commit", "high")
    assert streamed == ["u2", "u3"]
    assert _ids(path) == IDS
    session = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["stream_sessions"][0]
    assert session["rows_present"] == 1 and session["torn_bytes_dropped"] == 17


@pytest.mark.parametrize(
    ("content", "match"),
    [
        (_line("u1") + _line("u1"), "duplicate id"),
        (_line("u1") + '{"id": "u2"\n' + _line("u3"), "malformed record"),
        ('{"id": "u2"}garbage\n', "malformed record"),
        ("\n" + _line("u1"), "malformed record"),
        (_line("zz"), "not in the manifest"),
    ],
)
def test_stream_resume_refuses_damaged_interior_and_changes_nothing(fake_worker, content, match):
    run_dir, streamed = fake_worker
    path = run_dir / "stream-commit-t4.jsonl"
    path.write_text(content + '{"torn', encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        t2d.run_stream(run_dir, 4, "commit", "high")
    assert streamed == []
    assert path.read_text(encoding="utf-8") == content + '{"torn'
    assert "stream_sessions" not in json.loads((run_dir / "run.json").read_text(encoding="utf-8"))


def test_stream_records_resume_provenance_per_session(fake_worker):
    run_dir, _ = fake_worker
    (run_dir / "stream-redecode-t4.jsonl").write_text(_line("u1") + _line("u2"), encoding="utf-8")
    t2d.run_stream(run_dir, 4, "redecode", "high")
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["run_id"] == "x"
    (s,) = run["stream_sessions"]
    assert s["tag"] == "stream-redecode-t4" and s["policy"] == "redecode"
    assert s["rows_present"] == 2 and s["qos"] == "high" and s["git"]["sha"] == "abc"
    assert s["started_utc"] and len(s["t2d_py_sha256"]) == 64


def test_stream_refuses_to_mix_qos_within_one_policy(fake_worker):
    run_dir, _ = fake_worker
    (run_dir / "stream-commit-t4.jsonl").write_text(_line("u1"), encoding="utf-8")
    t2d._record_session(
        run_dir, {"tag": "stream-commit-t4", "qos": "default", "t2d_py_sha256": "?"}
    )
    with pytest.raises(ValueError, match="differs"):
        t2d.run_stream(run_dir, 4, "commit", "high")


def test_stream_skips_a_completed_policy_and_runs_only_the_other(fake_worker, monkeypatch):
    run_dir, streamed = fake_worker
    t2d.run_stream(run_dir, 4, "redecode", "high")
    done = (run_dir / "stream-redecode-t4.jsonl").read_bytes()
    streamed.clear()
    t2d.run_stream(run_dir, 4, "redecode", "high")
    assert streamed == []
    assert (run_dir / "stream-redecode-t4.jsonl").read_bytes() == done

    launched: list[str] = []

    class NoSampler:
        def __init__(self, *a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(t2d, "Sampler", NoSampler)
    monkeypatch.setattr(t2d.time, "sleep", lambda s: None)
    monkeypatch.setattr(t2d.subprocess, "run", lambda cmd, **kw: launched.append(cmd[-2]))
    t2d.stream(run_dir, 4, list(t2d.POLICIES), "high")
    assert launched == ["commit"]


def test_stream_summary_without_all_rows_is_an_error(fake_worker):
    run_dir, _ = fake_worker
    (run_dir / "stream-commit-t4.jsonl").write_text(_line("u1"), encoding="utf-8")
    (run_dir / "stream-commit-t4.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="1/3 rows"):
        t2d.run_stream(run_dir, 4, "commit", "high")
