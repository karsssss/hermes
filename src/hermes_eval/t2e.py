"""Task 2e: can a bounded context-preserving finalization keep offline WER inside 450 ms?

    uv run --group asr python -m hermes_eval.t2e screen            # ~25 min, 4 arms x 40 rows
    uv run python -m hermes_eval.t2e analyze <run-dir>
    uv run --group asr python -m hermes_eval.t2e gate <run-dir> --left L   # only if one survives
    uv run python -m hermes_eval.t2e analyze <run-dir>

Task 2d (D-0016) left two policies: `redecode` keeps offline quality but its final scales
with utterance length (p95 1339 ms); LocalAgreement-2 `commit` bounds the final (p95 443 ms)
but decodes each tail with no left context and doubles WER. Task 2e changes one thing:
every tail decode — partials and final — re-reads `left_s` of already-committed audio
before the cut, and the re-read words are dropped by timestamp midpoint
(`t2d._decode_tail`). Hop, right context, commit rule, cut placement, model, FP32, 4
threads and HighQoS are Task 2d's, unchanged. `left_s` = 0 is Task 2d's `commit` exactly,
and runs as the drift control.

Why acoustic overlap and not state reuse: the export is offline and full-context, so there
is no encoder cache that is valid across a cut, and sherpa's OfflineRecognizer accepts no
decoder state. Re-seeding the decoder would mean replacing sherpa's decode with the
owned Python loop (`tdt_probe`) — a new decoder path — and would still leave the encoder
starting cold at every cut, which is where Task 2d's hallucinated fillers come from.

Everything that decides the outcome is fixed here before any Task 2e number exists:
`SCREEN_IDS`, `SCREEN_LEFT_S`, `SCREEN_RULE`, `BOUNDARY_WINDOW_S`, and the unchanged
`t2d.GATE` and eligibility rule.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import t2d
from .align import Op, align
from .bootstrap import paired_bootstrap
from .manifest import load_strict
from .normalize import tokenize
from .provenance import run_id, utc_now
from .t2c import MANIFEST, REPO, RESAMPLES, SEED, _counts, _jsonl, _rate

THREADS = 4
QOS = "high"
BASELINE = REPO / "eval" / "runs" / "20261007T040840Z-t2d-parakeet-fp32-cpu-190c"
MIN_AVAILABLE_MB = 6000  # Task 2d's pre-flight floor: below it the FP32 sidecar pages

SCREEN_LEFT_S = (0.0, 1.0, 2.0, 3.0)  # 0.0 = Task 2d `commit`, the drift control
# Every fourth manifest row from the second: 40 rows, all seven subsets, en 28 / ru 12,
# 7 rows <= 3 s and 7 > 10 s. Chosen before any Task 2e number, because on Task 2d's own
# rows it reproduces the full set's latency (commit p95 443 vs 443, redecode 1335 vs 1339).
SCREEN_SLICE = (1, 4)
SCREEN_RULE = {
    "latency": "eliminate if screen release-to-final p95 > 500 ms (clearly beyond 450)",
    "quality": "eliminate if screen WER delta vs offline > +1.0 pp, or its CI low > 0",
    "retain": "at most one survivor: smallest WER delta; within 0.25 pp, the smaller left_s",
    "control": "left_s 0 is Task 2d commit, run only to check drift; never retained",
}
BOUNDARY_WINDOW_S = 0.5


def screen_ids() -> list[str]:
    start, step = SCREEN_SLICE
    return [r.id for r in load_strict(MANIFEST).records[start::step]]


def _tag(kind: str, left_s: float) -> str:
    return f"{kind}-commit-L{left_s:.1f}-t{THREADS}"


def _available_mb() -> float:
    import ctypes

    class Status(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (n, ctypes.c_ulonglong)
            for n in ("phys", "avail", "pf", "pf_avail", "virt", "virt_avail", "ext")
        ]

    s = Status()
    s.len = ctypes.sizeof(s)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))  # type: ignore[attr-defined]
    return s.avail / 2**20


def _check_memory() -> float:
    mb = _available_mb()
    if mb < MIN_AVAILABLE_MB:
        raise SystemExit(f"refused: {mb:.0f} MB available < {MIN_AVAILABLE_MB} MB floor")
    return mb


def _workers(run_dir: Path, kind: str, lefts: Sequence[float]) -> None:
    with t2d.Sampler(run_dir, f"counters-{kind}"):
        time.sleep(10.0)
        for left in lefts:
            cmd = [sys.executable, "-m", "hermes_eval.t2e", "worker", str(run_dir), kind]
            subprocess.run([*cmd, str(left)], check=True, cwd=REPO)
            time.sleep(5.0)


def screen(out_root: Path) -> Path:
    avail = _check_memory()
    manifest = load_strict(MANIFEST)
    run_dir = out_root / run_id("t2e-overlap-finalization")
    run_dir.mkdir(parents=True)
    run = {
        "run_id": run_dir.name,
        "task": "Phase 0 Task 2e - context-preserving finalization gate",
        "started_utc": utc_now(),
        "preflight": {**t2d.preflight(), "available_mb_at_start": round(avail)},
        "manifest": {"sha256": manifest.sha256, "n": len(manifest.records)},
        "baseline_run": BASELINE.name,
        "config": {
            "threads": THREADS,
            "qos": QOS,
            "hop_s": t2d.HOP_S,
            "right_context_s": t2d.RIGHT_CONTEXT_S,
            "screen_left_s": list(SCREEN_LEFT_S),
            "screen_slice": list(SCREEN_SLICE),
            "screen_ids": screen_ids(),
            "screen_rule": SCREEN_RULE,
            "boundary_window_s": BOUNDARY_WINDOW_S,
            "gate": t2d.GATE,
        },
    }
    (run_dir / "run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    _workers(run_dir, "screen", SCREEN_LEFT_S)
    return run_dir


def resume_screen(run_dir: Path) -> None:
    _check_memory()
    _workers(run_dir, "screen", SCREEN_LEFT_S)


def gate(run_dir: Path, left_s: float) -> None:
    survivor = json.loads((run_dir / "analysis.json").read_text(encoding="utf-8"))["retained"]
    if survivor != left_s:
        raise SystemExit(f"refused: the screen retained {survivor!r}, not {left_s}")
    _check_memory()
    _workers(run_dir, "gate", [left_s])


def worker(run_dir: Path, kind: str, left_s: float) -> None:
    only = screen_ids() if kind == "screen" else None
    t2d.run_stream(
        run_dir, THREADS, "commit", QOS, left_s=left_s, only=only, tag=_tag(kind, left_s)
    )


# ============================================================================ analyze


def _tokens(words: Sequence[Sequence[Any]]) -> list[tuple[str, float, float]]:
    return [(t, float(w[1]), float(w[2])) for w in words for t in tokenize(str(w[0]), "basic")]


def boundary_ops(row: dict[str, Any], offline_text: str) -> dict[str, int]:
    """Where the stitched final departs from the offline decode, relative to the cuts.

    The final is aligned to the *offline transcript*, not the reference, so every op is a
    divergence that streaming introduced. An op is at a boundary if its time span, padded
    by BOUNDARY_WINDOW_S, contains a cut. A deletion has no hypothesis token; its span is
    the gap between its hypothesis neighbours. An inserted token equal to a neighbour is a
    duplicate; any other inserted token at a boundary is a hallucination.
    """
    cuts = sorted({p["seg0"] for p in row["partials"] if p["seg0"] > 0})
    hyp = _tokens(row["final"]["words"])
    edits = align(tokenize(offline_text, "basic"), [t for t, _, _ in hyp]).edits
    keys = ("cuts", "div", "div_boundary", "dup", "drop", "halluc", "sub_boundary")
    out: dict[str, int] = dict.fromkeys(keys, 0)
    out["cuts"] = len(cuts)
    last_hyp = -1
    for k, e in enumerate(edits):
        if e.hyp_index is not None:
            last_hyp = e.hyp_index
        if e.op is Op.EQUAL:
            continue
        out["div"] += 1
        if e.hyp_index is not None:
            lo, hi = hyp[e.hyp_index][1], hyp[e.hyp_index][2]
        else:
            nxt = next((x.hyp_index for x in edits[k:] if x.hyp_index is not None), None)
            lo = hyp[last_hyp][2] if last_hyp >= 0 else 0.0
            hi = hyp[nxt][1] if nxt is not None else row["audio_s"]
        if not any(lo - BOUNDARY_WINDOW_S <= c <= hi + BOUNDARY_WINDOW_S for c in cuts):
            continue
        out["div_boundary"] += 1
        if e.op is Op.DEL:
            out["drop"] += 1
        elif e.op is Op.SUB:
            out["sub_boundary"] += 1
        else:
            i = e.hyp_index
            assert i is not None
            neighbours = {hyp[j][0] for j in (i - 1, i + 1) if 0 <= j < len(hyp)}
            out["dup" if hyp[i][0] in neighbours else "halluc"] += 1
    return out


def _arm(rows: list[dict[str, Any]], refs: dict[str, str], offline: dict[str, str]):
    q = t2d._q
    fin = [r["final"] for r in rows]
    lat = [f["latency_ms"] for f in fin]
    a = [_counts(refs[r["id"]], offline[r["id"]]) for r in rows]
    b = [_counts(refs[r["id"]], r["final"]["text"]) for r in rows]
    boot = paired_bootstrap(a, b, metric="wer", resamples=RESAMPLES, seed=SEED)
    bnd = [boundary_ops(r, offline[r["id"]]) for r in rows]
    tot = {k: sum(x[k] for x in bnd) for k in bnd[0]}

    def bucket(lo: float, hi: float) -> dict[str, Any]:
        v = [x for r, x in zip(rows, lat, strict=True) if lo < r["audio_s"] <= hi]
        return {"n": len(v), "p50_ms": q(v, 0.5), "p95_ms": q(v, 0.95)}

    def langwer(lang: str) -> list[float]:
        idx = [i for i, r in enumerate(rows) if r["language"] == lang]
        return [_rate([a[i] for i in idx]), _rate([b[i] for i in idx])]

    res = {
        "n": len(rows),
        "final": {
            "latency_p50_ms": q(lat, 0.5),
            "latency_p95_ms": q(lat, 0.95),
            "latency_p99_ms": q(lat, 0.99),
            "latency_max_ms": max(lat),
            "over_450": sum(1 for x in lat if x > t2d.GATE["marginal_ms"]),
            "inflight_wait_p50_ms": q([f["inflight_wait_ms"] for f in fin], 0.5),
            "inflight_wait_p95_ms": q([f["inflight_wait_ms"] for f in fin], 0.95),
            "compute_p50_ms": q([f["compute_ms"] for f in fin], 0.5),
            "compute_p95_ms": q([f["compute_ms"] for f in fin], 0.95),
            "tail_s_p50": q([f["tail_s"] for f in fin], 0.5),
            "tail_s_p95": q([f["tail_s"] for f in fin], 0.95),
            "decoded_s_p50": q([f.get("decoded_s", f["tail_s"]) for f in fin], 0.5),
            "decoded_s_p95": q([f.get("decoded_s", f["tail_s"]) for f in fin], 0.95),
            "by_duration": {
                "le3s": bucket(0, 3),
                "3to6s": bucket(3, 6),
                "6to10s": bucket(6, 10),
                "gt10s": bucket(10, 99),
            },
        },
        "partials": {
            "compute_p50_ms": q([p["ms"] for r in rows for p in r["partials"]], 0.5),
            "compute_p95_ms": q([p["ms"] for r in rows for p in r["partials"]], 0.95),
        },
        "quality": {
            "wer_offline": round(boot.rate_a * 100, 3),
            "wer_final": round(boot.rate_b * 100, 3),
            "delta_pp": boot.delta_pp,
            "ci_pp": [boot.ci_low_pp, boot.ci_high_pp],
            "sid_offline": [sum(c.sub for c in a), sum(c.ins for c in a), sum(c.dele for c in a)],
            "sid_final": [sum(c.sub for c in b), sum(c.ins for c in b), sum(c.dele for c in b)],
            "wer_en_offline_final": langwer("en"),
            "wer_ru_offline_final": langwer("ru"),
            "identical_to_offline": sum(
                " ".join(r["final"]["text"].split()) == " ".join(offline[r["id"]].split())
                for r in rows
            ),
            "worse_utts": sum(1 for x, y in zip(a, b, strict=True) if y.errors > x.errors),
            "better_utts": sum(1 for x, y in zip(a, b, strict=True) if y.errors < x.errors),
        },
        "boundary": {**tot, "per_100_cuts": _per100(tot)},
    }
    qq = res["quality"]
    res["eligible"] = qq["ci_pp"][0] <= 0 and qq["delta_pp"] <= 0.5
    p95 = res["final"]["latency_p95_ms"]
    res["gate"] = (
        "PASS"
        if p95 <= t2d.GATE["pass_ms"]
        else "MARGINAL"
        if p95 <= t2d.GATE["marginal_ms"]
        else "FAIL"
    )
    return res


def _per100(tot: dict[str, int]) -> dict[str, float]:
    n = tot["cuts"] or 1
    return {k: round(100.0 * v / n, 1) for k, v in tot.items() if k != "cuts"}


def select(screen: dict[str, dict[str, Any]]) -> tuple[float | None, dict[str, str]]:
    """Apply SCREEN_RULE. Returns the retained left_s (or None) and a reason per arm."""
    why: dict[str, str] = {}
    alive: list[tuple[float, float]] = []
    for key, r in screen.items():
        left = float(key)
        if left == 0.0:
            why[key] = "control"
            continue
        p95 = r["final"]["latency_p95_ms"]
        d, lo = r["quality"]["delta_pp"], r["quality"]["ci_pp"][0]
        if p95 > 500.0:
            why[key] = f"eliminated: p95 {p95} ms > 500"
        elif d > 1.0 or lo > 0:
            why[key] = f"eliminated: WER delta {d} pp, CI low {lo}"
        else:
            why[key] = "survived"
            alive.append((d, left))
    if not alive:
        return None, why
    best = min(d for d, _ in alive)
    keep = min(left for d, left in alive if d <= best + 0.25)
    for d, left in alive:
        why[f"{left:.1f}"] = "retained" if left == keep else f"survived, not retained ({d} pp)"
    return keep, why


def analyze(run_dir: Path) -> dict[str, Any]:
    refs = {r.id: r.reference for r in load_strict(MANIFEST).records}
    offline = {x["id"]: x["text"] for x in _jsonl(BASELINE / f"offline-t{THREADS}-r1.jsonl")}
    result: dict[str, Any] = {"generated_utc": utc_now(), "gate": t2d.GATE, "rule": SCREEN_RULE}
    for kind in ("screen", "gate"):
        arms = {}
        for left in SCREEN_LEFT_S:
            path = run_dir / f"{_tag(kind, left)}.jsonl"
            if (run_dir / f"{_tag(kind, left)}.json").exists():
                arms[f"{left:.1f}"] = _arm(_jsonl(path), refs, offline)
        result[kind] = arms
    result["retained"], result["screen_decision"] = select(result["screen"])
    # Task 2d's own commit rows on the screen ids: the drift reference for the L0 control.
    ids = set(screen_ids())
    t2d_rows = [x for x in _jsonl(BASELINE / "stream-commit-t4.jsonl") if x["id"] in ids]
    result["t2d_commit_on_screen_ids"] = _arm(t2d_rows, refs, offline)
    (run_dir / "analysis.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m hermes_eval.t2e")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("screen")
    s.add_argument("--out", type=Path, default=REPO / "eval" / "runs")
    s.add_argument("--resume", type=Path)
    s = sub.add_parser("gate")
    s.add_argument("run_dir", type=Path)
    s.add_argument("--left", type=float, required=True)
    s = sub.add_parser("worker")
    s.add_argument("run_dir", type=Path)
    s.add_argument("kind", choices=("screen", "gate"))
    s.add_argument("left_s", type=float)
    s = sub.add_parser("analyze")
    s.add_argument("run_dir", type=Path)
    a = p.parse_args(argv)
    if a.cmd == "screen":
        if a.resume:
            resume_screen(a.resume)
        else:
            print(screen(a.out))
    elif a.cmd == "gate":
        gate(a.run_dir, a.left)
    elif a.cmd == "worker":
        worker(a.run_dir, a.kind, a.left_s)
    elif a.cmd == "analyze":
        r = analyze(a.run_dir)
        print(json.dumps({"retained": r["retained"], "decision": r["screen_decision"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
