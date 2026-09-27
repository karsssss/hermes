"""Run execution and paired comparison. One process, flat files, no database.

Every run writes an immutable directory:

    run.json            provenance + aggregate metrics + subsets
    predictions.jsonl   what the adapter said, sorted by id
    per_utterance.jsonl every per-metric count, sorted by id — the drill-down
    summary.json        sorted-key aggregate
    summary.csv         machine-readable aggregate + subsets
    summary.md          fixed-order human report

The runner refuses to overwrite an existing run directory. A benchmark you can silently
re-run in place is a benchmark whose history you cannot trust.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import HARNESS_VERSION
from .adapters import ASRAdapter, build_adapter, missing_env_keys
from .bootstrap import (
    DEFAULT_RESAMPLES,
    DEFAULT_SEED,
    MIN_EFFECT_PP,
    apply_decision_rule,
    paired_bootstrap,
)
from .manifest import load_strict
from .metrics import Counts, UtteranceScore, aggregate, score_utterance, subset_metrics
from .normalize import NORMALIZER_VERSION
from .provenance import git_state, hardware, run_id, software, utc_now
from .report import comparison_markdown, summary_csv, summary_markdown
from .resources import ResourceSampler


@dataclass
class RunArtifacts:
    run_dir: Path
    run: dict[str, Any]
    per_utterance: list[dict[str, Any]]
    scores: list[UtteranceScore]


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(
        json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def execute(
    manifest_path: Path,
    adapter_spec: str,
    *,
    out_root: Path,
    repo_root: Path,
    label: str = "",
    seed: int = DEFAULT_SEED,
    dataset_name: str = "",
    require_audio: bool = True,
    manual_steps: Sequence[str] = (),
    adapter: ASRAdapter | None = None,
    sample_resources: bool = False,
) -> RunArtifacts:
    manifest = load_strict(manifest_path, require_audio=require_audio)
    engine = adapter if adapter is not None else build_adapter(adapter_spec, repo_root)
    # Called once up front so a misconfigured adapter fails before any decoding; the
    # authoritative copy is re-read after the loop, below.
    engine.describe_env()
    warnings: list[str] = []

    sampler = ResourceSampler().start() if sample_resources else None

    scores: list[UtteranceScore] = []
    predictions: list[dict[str, Any]] = []
    for record in manifest.records:
        started = time.perf_counter()
        hypothesis = engine.transcribe(record)
        wall_ms = (time.perf_counter() - started) * 1000.0
        latency = hypothesis.latency_ms if hypothesis.latency_ms is not None else wall_ms
        latency_source = "adapter" if hypothesis.latency_ms is not None else "harness_wall_clock"
        if hypothesis.low_confidence_timing:
            warnings.append(f"{record.id}: low_confidence_timing — latency is not trustworthy")
        if not hypothesis.text.strip():
            warnings.append(f"{record.id}: adapter returned empty text")
        scores.append(score_utterance(record, hypothesis.text, latency))
        predictions.append(
            {
                "id": record.id,
                "text": hypothesis.text,
                "latency_ms": round(latency, 2),
                "latency_source": latency_source,
                "low_confidence_timing": hypothesis.low_confidence_timing,
                # Whatever the backend chose to report — per-utterance RTF and audio
                # duration for the real adapters. Kept raw; the harness does not interpret it.
                "extra": dict(hypothesis.extra),
            }
        )

    resources = sampler.stop() if sampler is not None else None

    # Re-read the adapter environment after the loop. A real backend only knows its
    # corpus RTF, decode total and empty-output count once it has decoded something, and a
    # provenance block captured before the first utterance would omit exactly that.
    env = engine.describe_env()
    missing = missing_env_keys(env)
    if missing:
        warnings.append("incomplete provenance from the adapter: " + ", ".join(missing))

    metrics = aggregate(scores)
    unmatched = sorted({e for s in scores for e in s.unmatched_entities})
    if unmatched:
        warnings.append(
            "entities not found in their own reference (manifest bug): " + ", ".join(unmatched)
        )

    rid = run_id(label or engine.name)
    run: dict[str, Any] = {
        "run_id": rid,
        "timestamp_utc": utc_now(),
        "label": label,
        "harness_version": HARNESS_VERSION,
        "git": git_state(repo_root),
        "hardware": hardware(),
        "software": software(),
        "adapter": {
            "spec": adapter_spec,
            "name": engine.name,
            "env": env,
            "missing_provenance": missing,
        },
        "dataset": {
            "name": dataset_name or manifest_path.parent.name,
            "manifest": str(manifest_path.as_posix()),
            "manifest_sha256": manifest.sha256,
            "n_utterances": len(manifest.records),
        },
        "scoring": {
            "normalizer": NORMALIZER_VERSION,
            "fwer_mode": "raw",
            "wer_mode": "basic",
            "casing_mode": "casefold",
        },
        "bootstrap_seed": seed,
        "resources": resources,
        "metrics": metrics,
        "subsets": subset_metrics(scores),
        "warnings": warnings,
        "manual_steps_log": list(manual_steps),
    }

    per_utterance = sorted((s.to_json() for s in scores), key=lambda u: str(u["id"]))

    run_dir = Path(out_root) / rid
    if run_dir.exists():
        raise FileExistsError(f"run directory already exists (runs are immutable): {run_dir}")
    run_dir.mkdir(parents=True)
    _write_json(run_dir / "run.json", run)
    _write_json(
        run_dir / "summary.json", {"run_id": rid, "metrics": metrics, "subsets": run["subsets"]}
    )
    _write_jsonl(run_dir / "predictions.jsonl", sorted(predictions, key=lambda p: str(p["id"])))
    _write_jsonl(run_dir / "per_utterance.jsonl", per_utterance)
    (run_dir / "summary.csv").write_text(summary_csv(run), encoding="utf-8", newline="\n")
    (run_dir / "summary.md").write_text(
        summary_markdown(run, per_utterance), encoding="utf-8", newline="\n"
    )
    return RunArtifacts(run_dir=run_dir, run=run, per_utterance=per_utterance, scores=scores)


# ------------------------------------------------------------------------ compare


def _load_run(run_dir: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    rows: dict[str, dict[str, Any]] = {}
    for line in (run_dir / "per_utterance.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[str(row["id"])] = row
    return run, rows


def _counts(row: dict[str, Any], metric: str) -> Counts:
    c = row["counts"][metric]
    return Counts(c["errors"], c["ref_len"], c["sub"], c["ins"], c["dele"])


def compare(
    baseline_dir: Path,
    candidate_dir: Path,
    *,
    out_root: Path | None = None,
    seed: int = DEFAULT_SEED,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = 0.95,
    latency_budget_ms: float | None = None,
    min_effect_pp: float = MIN_EFFECT_PP,
) -> tuple[dict[str, Any], Path | None]:
    base_run, base_rows = _load_run(Path(baseline_dir))
    cand_run, cand_rows = _load_run(Path(candidate_dir))

    only_base = sorted(set(base_rows) - set(cand_rows))
    only_cand = sorted(set(cand_rows) - set(base_rows))
    if only_base or only_cand:
        raise ValueError(
            "paired comparison requires identical utterance sets; "
            f"baseline-only={only_base[:5]} candidate-only={only_cand[:5]}"
        )
    ids = sorted(base_rows)

    fwer = paired_bootstrap(
        [_counts(base_rows[i], "fwer") for i in ids],
        [_counts(cand_rows[i], "fwer") for i in ids],
        metric="fwer",
        seed=seed,
        resamples=resamples,
        confidence=confidence,
    )
    base_ewer = [_counts(base_rows[i], "ewer") for i in ids]
    cand_ewer = [_counts(cand_rows[i], "ewer") for i in ids]
    ewer = None
    if sum(c.ref_len for c in base_ewer) and sum(c.ref_len for c in cand_ewer):
        ewer = paired_bootstrap(
            base_ewer,
            cand_ewer,
            metric="ewer",
            seed=seed,
            resamples=resamples,
            confidence=confidence,
        )

    cand_p95 = cand_run["metrics"]["latency_ms"]["p95"]
    decision = apply_decision_rule(
        fwer,
        ewer=ewer,
        latency_p95_ms=cand_p95,
        latency_budget_ms=latency_budget_ms,
        min_effect_pp=min_effect_pp,
    )

    result: dict[str, Any] = {
        "baseline": {
            "run_id": base_run["run_id"],
            "adapter": base_run["adapter"]["spec"],
            "model_id": base_run["adapter"]["env"].get("model_id"),
            "run_dir": str(Path(baseline_dir).as_posix()),
        },
        "candidate": {
            "run_id": cand_run["run_id"],
            "adapter": cand_run["adapter"]["spec"],
            "model_id": cand_run["adapter"]["env"].get("model_id"),
            "run_dir": str(Path(candidate_dir).as_posix()),
        },
        "n_paired": len(ids),
        "seed": seed,
        "resamples": resamples,
        "confidence": confidence,
        "min_effect_pp": min_effect_pp,
        "latency_budget_ms": latency_budget_ms,
        "latency_p95_ms": {
            "baseline": base_run["metrics"]["latency_ms"]["p95"],
            "candidate": cand_p95,
        },
        "fwer": fwer.to_json(),
        "ewer": ewer.to_json() if ewer else None,
        "decision": decision.to_json(),
    }

    out_dir: Path | None = None
    if out_root is not None:
        out_dir = Path(out_root) / f"{cand_run['run_id']}__vs__{base_run['run_id']}"
        out_dir.mkdir(parents=True, exist_ok=True)
        _write_json(out_dir / "comparison.json", result)
        (out_dir / "comparison.md").write_text(
            comparison_markdown(result), encoding="utf-8", newline="\n"
        )
    return result, out_dir
