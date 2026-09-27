"""Rendering: summary.md, summary.csv, and the console report.

`summary.md` is a fixed-order Markdown table — no dynamic ordering, no HTML — so that
`git diff` shows exactly which cells moved. `summary.json` is sorted-key JSON for the
same reason. The worst-N table is in here because aggregate WER tells you nothing
actionable; sorting by error and reading the worst 20 is where the bugs are.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from typing import Any

from .metrics import MARK_CLASSES

SUBSET_AXIS_ORDER = (
    # `subset` sits second because on a designed evaluation set it is the axis the run is
    # read on; `reference_style` sits last because it is a caveat, not a result — it says
    # which records could carry an F-WER at all.
    "language",
    "subset",
    "code_switch",
    "accent",
    "domain",
    "category",
    "speaker",
    "noise",
    "app",
    "reference_style",
)


def _pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.2f}%"


def _ms(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.0f} ms"


def _row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def summary_markdown(run: dict[str, Any], per_utterance: Sequence[dict[str, Any]]) -> str:
    m = run["metrics"]
    adapter = run["adapter"]
    dataset = run["dataset"]
    lat = m["latency_ms"]
    lines: list[str] = []

    lines.append(f"# Run `{run['run_id']}`")
    lines.append("")
    lines.append(_row(["field", "value"]))
    lines.append(_row(["---", "---"]))
    for key, value in (
        ("timestamp (UTC)", run["timestamp_utc"]),
        ("label", run.get("label") or "-"),
        ("adapter", adapter["spec"]),
        ("model", str(adapter["env"].get("model_id"))),
        ("model sha256", str(adapter["env"].get("model_sha256"))),
        ("quantization", str(adapter["env"].get("quantization"))),
        (
            "runtime / provider",
            f"{adapter['env'].get('runtime')} / {adapter['env'].get('provider')}",
        ),
        ("decode params", str(adapter["env"].get("decode_params"))),
        ("threads", str(adapter["env"].get("thread_count"))),
        ("dataset", f"{dataset['name']} (n={dataset['n_utterances']})"),
        ("manifest sha256", dataset["manifest_sha256"][:16]),
        ("git sha", f"{run['git']['sha']} (dirty={run['git']['dirty']})"),
        ("hardware", str(run["hardware"]["processor"])),
        ("gpu", str(run["hardware"]["gpu"])),
        ("normalizer", run["scoring"]["normalizer"]),
        ("bootstrap seed", str(run["bootstrap_seed"])),
    ):
        lines.append(_row([key, value]))

    lines += ["", "## Headline", "", _row(["metric", "value"]), _row(["---", "---"])]
    lines.append(_row(["**F-WER**", f"**{_pct(m['fwer'])}**"]))
    lines.append(_row(["WER (normalized)", _pct(m["wer"])]))
    lines.append(_row(["E-WER", _pct(m["ewer"])]))
    lines.append(
        _row(
            [
                "latency p50 / p95 / p99",
                f"{_ms(lat['p50'])} / {_ms(lat['p95'])} / {_ms(lat['p99'])}",
            ]
        )
    )

    lines += ["", "## F-WER decomposition", "", _row(["component", "value"]), _row(["---", "---"])]
    lines.append(_row(["casing error rate", f"{m['casing_error_rate_pp']:+.2f} pp"]))
    lines.append(_row(["punctuation F1 (micro)", f"{m['punctuation_f1_micro']:.3f}"]))
    itn = m["itn"]
    lines.append(
        _row(
            [
                "ITN slot error rate",
                "n/a"
                if itn["slot_error_rate"] is None
                else f"{_pct(itn['slot_error_rate'])} ({itn['slots_missed']}/{itn['slots_total']})",
            ]
        )
    )
    lines.append(_row(["ITN spurious insertions", "not measured in v0"]))

    lines += [
        "",
        "### Punctuation F1 per class",
        "",
        _row(["mark", "P", "R", "F1", "tp", "fp", "fn"]),
        _row(["---"] * 7),
    ]
    for mark in MARK_CLASSES:
        c = m["punctuation_f1"][mark]
        # A mark that never occurs in either the reference or the hypothesis has no
        # score. Printing 0.000 there would read as a failure instead of as no data.
        absent = (c["tp"] + c["fp"] + c["fn"]) == 0
        lines.append(
            _row(
                [
                    f"`{mark}`",
                    "-" if absent else f"{c['precision']:.3f}",
                    "-" if absent else f"{c['recall']:.3f}",
                    "-" if absent else f"{c['f1']:.3f}",
                    str(c["tp"]),
                    str(c["fp"]),
                    str(c["fn"]),
                ]
            )
        )

    for axis in SUBSET_AXIS_ORDER:
        groups = run.get("subsets", {}).get(axis)
        if not groups:
            continue
        lines += [
            "",
            f"## Subset: {axis}",
            "",
            _row([axis, "n", "F-WER", "WER", "E-WER", "p95"]),
            _row(["---"] * 6),
        ]
        for key in sorted(groups):
            g = groups[key]
            lines.append(
                _row(
                    [
                        key,
                        str(g["n_utterances"]),
                        _pct(g["fwer"]),
                        _pct(g["wer"]),
                        _pct(g["ewer"]),
                        _ms(g["latency_ms"]["p95"]),
                    ]
                )
            )

    worst = sorted(per_utterance, key=lambda u: (-u["fwer"], u["id"]))[:10]
    lines += [
        "",
        "## Worst 10 utterances by F-WER",
        "",
        _row(["id", "F-WER", "reference", "hypothesis"]),
        _row(["---"] * 4),
    ]
    for u in worst:
        lines.append(
            _row(
                [
                    u["id"],
                    _pct(u["fwer"]),
                    u["reference"].replace("|", "\\|"),
                    u["hypothesis"].replace("|", "\\|"),
                ]
            )
        )

    warnings = run.get("warnings") or []
    if warnings:
        lines += ["", "## Warnings", ""]
        lines += [f"- {w}" for w in warnings]
    lines.append("")
    return "\n".join(lines)


def summary_csv(run: dict[str, Any]) -> str:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(
        [
            "scope",
            "key",
            "n",
            "fwer",
            "wer",
            "ewer",
            "casing_pp",
            "punct_f1_micro",
            "itn_ser",
            "p50_ms",
            "p95_ms",
        ]
    )

    def emit(scope: str, key: str, g: dict[str, Any]) -> None:
        writer.writerow(
            [
                scope,
                key,
                g["n_utterances"],
                g["fwer"],
                g["wer"],
                "" if g["ewer"] is None else g["ewer"],
                g["casing_error_rate_pp"],
                g["punctuation_f1_micro"],
                "" if g["itn"]["slot_error_rate"] is None else g["itn"]["slot_error_rate"],
                "" if g["latency_ms"]["p50"] is None else g["latency_ms"]["p50"],
                "" if g["latency_ms"]["p95"] is None else g["latency_ms"]["p95"],
            ]
        )

    emit("overall", "all", run["metrics"])
    for axis in SUBSET_AXIS_ORDER:
        for key in sorted(run.get("subsets", {}).get(axis, {})):
            emit(axis, key, run["subsets"][axis][key])
    return buf.getvalue()


def console_report(run: dict[str, Any]) -> str:
    m = run["metrics"]
    lat = m["latency_ms"]
    out = [
        f"run        {run['run_id']}",
        f"adapter    {run['adapter']['spec']}  model={run['adapter']['env'].get('model_id')}",
        f"dataset    {run['dataset']['name']}  n={m['n_utterances']}",
        f"F-WER      {_pct(m['fwer'])}   (WER {_pct(m['wer'])}, E-WER {_pct(m['ewer'])})",
        f"decomp     casing {m['casing_error_rate_pp']:+.2f} pp"
        f" | punct F1 {m['punctuation_f1_micro']:.3f}"
        + (
            ""
            if m["itn"]["slot_error_rate"] is None
            else f" | ITN SER {_pct(m['itn']['slot_error_rate'])}"
        ),
        f"latency    p50 {_ms(lat['p50'])}  p95 {_ms(lat['p95'])}  p99 {_ms(lat['p99'])}",
    ]
    for axis in ("language", "subset", "code_switch", "accent", "category"):
        groups = run.get("subsets", {}).get(axis) or {}
        if groups:
            cells = "  ".join(
                f"{k}={_pct(g['fwer'])}(n={g['n_utterances']})" for k, g in sorted(groups.items())
            )
            out.append(f"{axis:<10} {cells}")
    for w in run.get("warnings") or []:
        out.append(f"warning    {w}")
    return "\n".join(out)


def comparison_markdown(cmp: dict[str, Any]) -> str:
    lines = [
        f"# Comparison — baseline `{cmp['baseline']['run_id']}` "
        f"vs candidate `{cmp['candidate']['run_id']}`",
        "",
        _row(["field", "baseline", "candidate"]),
        _row(["---", "---", "---"]),
        _row(["adapter", cmp["baseline"]["adapter"], cmp["candidate"]["adapter"]]),
        _row(["model", str(cmp["baseline"]["model_id"]), str(cmp["candidate"]["model_id"])]),
        _row(["F-WER", _pct(cmp["fwer"]["rate_a"]), _pct(cmp["fwer"]["rate_b"])]),
        _row(
            [
                "E-WER",
                "n/a" if cmp["ewer"] is None else _pct(cmp["ewer"]["rate_a"]),
                "n/a" if cmp["ewer"] is None else _pct(cmp["ewer"]["rate_b"]),
            ]
        ),
        _row(
            [
                "latency p95",
                _ms(cmp["latency_p95_ms"]["baseline"]),
                _ms(cmp["latency_p95_ms"]["candidate"]),
            ]
        ),
        "",
        "## Paired bootstrap",
        "",
        _row(["metric", "delta (pp)", "95% CI (pp)", "excludes zero"]),
        _row(["---"] * 4),
    ]
    for key in ("fwer", "ewer"):
        b = cmp[key]
        if b is None:
            continue
        lines.append(
            _row(
                [
                    key.upper(),
                    f"{b['delta_pp']:+.2f}",
                    f"[{b['ci_low_pp']:+.2f}, {b['ci_high_pp']:+.2f}]",
                    "yes" if b["ci_excludes_zero"] else "no",
                ]
            )
        )
    lines += [
        "",
        f"utterances paired: {cmp['n_paired']} · resamples: {cmp['resamples']}"
        f" · seed: {cmp['seed']}",
        "",
        f"## Verdict: **{cmp['decision']['verdict']}**",
        "",
    ]
    lines += [f"- {r}" for r in cmp["decision"]["reasons"]]
    lines.append("")
    return "\n".join(lines)
