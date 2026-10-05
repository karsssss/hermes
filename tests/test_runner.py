"""End-to-end: the harness must run, score, and compare without a model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_eval.adapters import PerturbAdapter, ReplayAdapter, build_adapter, missing_env_keys
from hermes_eval.cli import main
from hermes_eval.manifest import Record
from hermes_eval.runner import _decode_sequence, compare, execute

ROOT = Path(__file__).resolve().parents[1]
MOCK = ROOT / "eval" / "datasets" / "mock" / "manifest.jsonl"


def run(tmp_path: Path, spec: str, label: str):
    return execute(
        MOCK,
        spec,
        out_root=tmp_path / "runs",
        repo_root=ROOT,
        label=label,
        dataset_name="mock",
    )


def test_run_writes_the_full_artifact_set(tmp_path: Path):
    artifacts = run(tmp_path, "perturb:seed=1", "a")
    for name in (
        "run.json",
        "summary.json",
        "summary.csv",
        "summary.md",
        "predictions.jsonl",
        "per_utterance.jsonl",
    ):
        assert (artifacts.run_dir / name).is_file(), name
    assert len(artifacts.per_utterance) == 12
    assert [u["id"] for u in artifacts.per_utterance] == sorted(
        u["id"] for u in artifacts.per_utterance
    )


def test_run_record_carries_the_provenance_needed_to_reproduce_it(tmp_path: Path):
    run_json = json.loads(
        (run(tmp_path, "perturb:seed=1", "a").run_dir / "run.json").read_text("utf-8")
    )
    env = run_json["adapter"]["env"]
    for key in ("model_id", "quantization", "runtime", "provider", "decode_params", "thread_count"):
        assert env.get(key) is not None, key
    assert run_json["git"]["sha"]
    assert run_json["hardware"]["logical_cores"]
    assert run_json["software"]["python"]
    assert run_json["scoring"]["normalizer"]
    assert run_json["bootstrap_seed"]
    assert run_json["dataset"]["manifest_sha256"]
    assert run_json["timestamp_utc"].endswith("Z")


def test_subset_metrics_cover_the_analysis_axes(tmp_path: Path):
    subsets = run(tmp_path, "perturb:seed=1", "a").run["subsets"]
    for axis in ("language", "accent", "domain", "category", "code_switch"):
        assert axis in subsets, axis
    assert set(subsets["code_switch"]) == {"code_switched", "monolingual"}
    assert subsets["code_switch"]["code_switched"]["n_utterances"] == 2
    assert subsets["category"]["dev_speak"]["n_utterances"] == 3


def test_identical_seeds_produce_identical_scores(tmp_path: Path):
    a = run(tmp_path, "perturb:seed=5", "a")
    b = run(tmp_path, "perturb:seed=5", "b")
    assert a.run["metrics"] == b.run["metrics"]
    assert [u["hypothesis"] for u in a.per_utterance] == [u["hypothesis"] for u in b.per_utterance]


def test_runs_are_immutable(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("hermes_eval.runner.run_id", lambda prefix: "fixed-run-id")
    run(tmp_path, "perturb:seed=1", "a")
    with pytest.raises(FileExistsError, match="runs are immutable"):
        run(tmp_path, "perturb:seed=1", "a")


def test_compare_produces_a_seeded_reproducible_verdict(tmp_path: Path):
    good = run(tmp_path, "perturb:seed=3,error_rate=0.02,punct_drop=0.05,case_drop=0.05", "good")
    bad = run(tmp_path, "perturb:seed=3,error_rate=0.45,punct_drop=0.9,case_drop=0.9", "bad")

    result, out_dir = compare(
        good.run_dir, bad.run_dir, out_root=tmp_path / "cmp", seed=99, resamples=500
    )
    assert result["decision"]["verdict"] == "regression"
    assert result["n_paired"] == 12
    assert result["seed"] == 99
    assert out_dir is not None and (out_dir / "comparison.md").is_file()

    again, _ = compare(good.run_dir, bad.run_dir, seed=99, resamples=500)
    assert again["fwer"] == result["fwer"]

    flipped, _ = compare(bad.run_dir, good.run_dir, seed=99, resamples=500)
    assert flipped["fwer"]["delta_pp"] < 0


def test_compare_refuses_unpaired_utterance_sets(tmp_path: Path):
    a = run(tmp_path, "perturb:seed=1", "a")
    b = run(tmp_path, "perturb:seed=2", "b")
    rows = (b.run_dir / "per_utterance.jsonl").read_text("utf-8").splitlines()
    (b.run_dir / "per_utterance.jsonl").write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="identical utterance sets"):
        compare(a.run_dir, b.run_dir, seed=1, resamples=10)


def test_latency_budget_is_a_hard_gate(tmp_path: Path):
    good = run(tmp_path, "perturb:seed=3,error_rate=0.02", "good")
    bad = run(tmp_path, "perturb:seed=3,error_rate=0.45", "bad")
    result, _ = compare(bad.run_dir, good.run_dir, seed=1, resamples=200, latency_budget_ms=1.0)
    assert result["decision"]["verdict"] == "blocked_latency"


def test_replay_adapter_scores_a_transcript_file(tmp_path: Path):
    path = tmp_path / "competitor.jsonl"
    path.write_text(
        "\n".join(
            json.dumps({"id": f"mock-{i:04d}", "text": "whatever it heard", "latency_ms": 900})
            for i in range(1, 13)
        )
        + "\n",
        encoding="utf-8",
    )
    artifacts = execute(
        MOCK, f"replay:{path}", out_root=tmp_path / "runs", repo_root=ROOT, label="competitor"
    )
    assert artifacts.run["metrics"]["n_utterances"] == 12
    assert artifacts.run["metrics"]["latency_ms"]["p95"] == 900
    # A replay adapter cannot know the model it replayed: the gap is recorded, not hidden.
    assert artifacts.run["adapter"]["missing_provenance"]
    assert any("incomplete provenance" in w for w in artifacts.run["warnings"])


def test_replay_adapter_rejects_a_missing_utterance(tmp_path: Path):
    path = tmp_path / "partial.jsonl"
    path.write_text(json.dumps({"id": "mock-0001", "text": "hello"}) + "\n", encoding="utf-8")
    with pytest.raises(KeyError):
        execute(MOCK, f"replay:{path}", out_root=tmp_path / "runs", repo_root=ROOT)


def test_adapter_spec_parsing():
    adapter = build_adapter("perturb:seed=9,error_rate=0.5", ROOT)
    assert isinstance(adapter, PerturbAdapter)
    assert adapter.seed == 9 and adapter.error_rate == 0.5
    assert missing_env_keys(adapter.describe_env()) == []
    with pytest.raises(ValueError, match="unknown adapter spec"):
        build_adapter("whisper-turbo", ROOT)
    with pytest.raises(ValueError, match="needs a path"):
        build_adapter("replay:", ROOT)


def test_replay_adapter_reads_a_hand_written_env_sidecar(tmp_path: Path):
    path = tmp_path / "c.jsonl"
    path.write_text(json.dumps({"id": "mock-0001", "text": "x"}) + "\n", encoding="utf-8")
    path.with_suffix(".jsonl.env.json").write_text(
        json.dumps({"model_id": "competitor-2026-09", "quantization": "unknown"}), encoding="utf-8"
    )
    assert ReplayAdapter(path).describe_env()["model_id"] == "competitor-2026-09"


def test_cli_validate_and_run_and_compare(tmp_path: Path, capsys):
    assert main(["validate", str(MOCK)]) == 0
    runs = tmp_path / "runs"
    assert (
        main(["run", "--manifest", str(MOCK), "--adapter", "perturb:seed=1", "--out", str(runs)])
        == 0
    )
    assert (
        main(["run", "--manifest", str(MOCK), "--adapter", "perturb:seed=2", "--out", str(runs)])
        == 0
    )
    dirs = sorted(p for p in runs.iterdir() if p.is_dir())
    assert len(dirs) == 2
    capsys.readouterr()
    code = main(
        [
            "compare",
            str(dirs[0]),
            str(dirs[1]),
            "--out",
            str(tmp_path / "cmp"),
            "--resamples",
            "200",
        ]
    )
    out = capsys.readouterr().out
    assert "verdict" in out
    assert code in (0, 1)


def test_cli_validate_reports_bad_manifest(tmp_path: Path, capsys):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"id": "x"}\n', encoding="utf-8")
    assert main(["validate", str(bad)]) == 1
    assert "missing keys" in capsys.readouterr().err


# ---------------------------------------------------------------- decode order


def _rec(rid: str, language: str) -> Record:
    return Record(id=rid, audio=Path(rid), reference="x", metadata={"language": language})


def test_decode_order_manifest_is_the_manifest_order():
    records = [_rec("a", "en"), _rec("b", "ru"), _rec("c", "en")]
    assert [r.id for r in _decode_sequence(records, "manifest")] == ["a", "b", "c"]


def test_decode_order_language_groups_without_losing_or_duplicating_records():
    records = [
        _rec("a", "en"),
        _rec("b", "ru"),
        _rec("c", "en"),
        _rec("d", "ru"),
        _rec("e", "en"),
    ]
    ordered = _decode_sequence(records, "language")
    # First-appearance order across groups, manifest order within one.
    assert [r.id for r in ordered] == ["a", "c", "e", "b", "d"]
    # The set is what makes the run "complete"; grouping must never drop a row.
    assert sorted(r.id for r in ordered) == sorted(r.id for r in records)
    assert len(ordered) == len(records)


def test_decode_order_language_pays_one_switch_on_an_alternating_manifest():
    """The public proxy manifest alternates en/ru/en/ru — the reason this mode exists."""
    records = [_rec(f"{i}", lang) for i, lang in enumerate(["en", "ru"] * 6)]

    def transitions(seq: list[Record]) -> int:
        pairs = zip(seq, seq[1:], strict=False)
        return sum(1 for a, b in pairs if a.metadata["language"] != b.metadata["language"])

    assert transitions(_decode_sequence(records, "manifest")) == 11
    assert transitions(_decode_sequence(records, "language")) == 1


def test_decode_order_rejects_an_unknown_mode():
    with pytest.raises(ValueError, match="unknown decode order"):
        _decode_sequence([_rec("a", "en")], "alphabetical")


def test_decode_order_is_recorded_in_the_run(tmp_path: Path):
    artifacts = execute(
        MOCK,
        "perturb:seed=1",
        out_root=tmp_path / "runs",
        repo_root=ROOT,
        label="order",
        dataset_name="mock",
        decode_order="language",
    )
    recorded = artifacts.run["decode_order"]
    assert recorded["mode"] == "language"
    assert len(recorded["sequence_sha256"]) == 64
    # Outputs are sorted by id whatever order the decode ran in.
    ids = [row["id"] for row in artifacts.per_utterance]
    assert ids == sorted(ids)


def test_decode_order_does_not_change_the_scores(tmp_path: Path):
    """Reordering the decode must be invisible to every metric, or it is not safe."""
    a = execute(
        MOCK,
        "perturb:seed=1",
        out_root=tmp_path / "runs",
        repo_root=ROOT,
        label="m",
        dataset_name="mock",
        decode_order="manifest",
    )
    b = execute(
        MOCK,
        "perturb:seed=1",
        out_root=tmp_path / "runs",
        repo_root=ROOT,
        label="l",
        dataset_name="mock",
        decode_order="language",
    )
    assert a.run["metrics"] == b.run["metrics"]
    assert a.run["subsets"] == b.run["subsets"]
