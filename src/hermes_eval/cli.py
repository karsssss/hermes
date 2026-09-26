"""`hermes-eval` — one command runs the suite and emits a diffable report.

    hermes-eval validate eval/datasets/mock/manifest.jsonl
    hermes-eval run --manifest eval/datasets/mock/manifest.jsonl --adapter perturb:seed=1
    hermes-eval compare eval/runs/<baseline> eval/runs/<candidate> --latency-budget-ms 700

Exit codes: 0 success (or a comparison verdict of improvement/noise), 1 failure — an
invalid manifest, or a comparison verdict of regression / blocked_*. `compare` is
therefore usable directly as the CI gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bootstrap import DEFAULT_RESAMPLES, DEFAULT_SEED, MIN_EFFECT_PP
from .manifest import ManifestValidationError, load
from .report import console_report
from .runner import compare, execute


def _repo_root(start: Path | None = None) -> Path:
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").exists() or (candidate / ".git").exists():
            return candidate
    return here


def _cmd_validate(args: argparse.Namespace) -> int:
    manifest = load(Path(args.manifest), require_audio=not args.no_require_audio)
    if manifest.errors:
        print(f"{manifest.path}: {len(manifest.errors)} invalid entries", file=sys.stderr)
        for err in manifest.errors:
            print(f"  {err}", file=sys.stderr)
        return 1
    print(f"{manifest.path}: {len(manifest.records)} valid records (sha256 {manifest.sha256[:16]})")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    root = _repo_root()
    out_root = Path(args.out) if args.out else root / "eval" / "runs"
    try:
        artifacts = execute(
            Path(args.manifest),
            args.adapter,
            out_root=out_root,
            repo_root=root,
            label=args.label,
            seed=args.seed,
            dataset_name=args.dataset,
            require_audio=not args.no_require_audio,
            manual_steps=args.manual_step or (),
        )
    except ManifestValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(console_report(artifacts.run))
    print(f"artifacts  {artifacts.run_dir.as_posix()}")
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    root = _repo_root()
    out_root = Path(args.out) if args.out else root / "eval" / "runs" / "comparisons"
    result, out_dir = compare(
        Path(args.baseline),
        Path(args.candidate),
        out_root=out_root,
        seed=args.seed,
        resamples=args.resamples,
        latency_budget_ms=args.latency_budget_ms,
        min_effect_pp=args.min_effect_pp,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        f = result["fwer"]
        print(f"baseline   {result['baseline']['run_id']}  F-WER {f['rate_a'] * 100:.2f}%")
        print(f"candidate  {result['candidate']['run_id']}  F-WER {f['rate_b'] * 100:.2f}%")
        print(
            f"delta      {f['delta_pp']:+.2f} pp  95% CI [{f['ci_low_pp']:+.2f}, "
            f"{f['ci_high_pp']:+.2f}]  (n={result['n_paired']}, "
            f"{result['resamples']} resamples, seed {result['seed']})"
        )
        if result["ewer"]:
            e = result["ewer"]
            print(
                f"E-WER      {e['delta_pp']:+.2f} pp  95% CI [{e['ci_low_pp']:+.2f}, "
                f"{e['ci_high_pp']:+.2f}]"
            )
        print(f"verdict    {result['decision']['verdict']}")
        for reason in result["decision"]["reasons"]:
            print(f"           - {reason}")
        if out_dir:
            print(f"artifacts  {out_dir.as_posix()}")
    return 0 if result["decision"]["verdict"] in ("improvement", "noise") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-eval", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate", help="validate a manifest")
    p_val.add_argument("manifest")
    p_val.add_argument("--no-require-audio", action="store_true", help="skip audio file checks")
    p_val.set_defaults(func=_cmd_validate)

    p_run = sub.add_parser("run", help="score an adapter over a manifest")
    p_run.add_argument("--manifest", required=True)
    p_run.add_argument(
        "--adapter", required=True, help="perturb:seed=1,error_rate=0.05 | replay:<file.jsonl>"
    )
    p_run.add_argument("--out", default="", help="run root (default eval/runs)")
    p_run.add_argument("--label", default="", help="short label, becomes part of the run id")
    p_run.add_argument("--dataset", default="", help="dataset name for the run record")
    p_run.add_argument("--seed", type=int, default=DEFAULT_SEED, help="bootstrap seed to record")
    p_run.add_argument("--no-require-audio", action="store_true")
    p_run.add_argument(
        "--manual-step",
        action="append",
        help="operator note; required for semi-manual adapters",
    )
    p_run.set_defaults(func=_cmd_run)

    p_cmp = sub.add_parser("compare", help="paired bootstrap comparison of two runs")
    p_cmp.add_argument("baseline")
    p_cmp.add_argument("candidate")
    p_cmp.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p_cmp.add_argument("--resamples", type=int, default=DEFAULT_RESAMPLES)
    p_cmp.add_argument("--min-effect-pp", type=float, default=MIN_EFFECT_PP)
    p_cmp.add_argument("--latency-budget-ms", type=float, default=None)
    p_cmp.add_argument("--out", default="", help="comparison root (default eval/runs/comparisons)")
    p_cmp.add_argument("--json", action="store_true")
    p_cmp.set_defaults(func=_cmd_compare)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
