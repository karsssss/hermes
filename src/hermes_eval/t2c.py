"""Task 2c: Parakeet TDT v3 INT8 vs FP32 — does FP32 earn its cost for Phase 1?

    uv run --group asr python -m hermes_eval.t2c collect [--resume <run-dir>]
    uv run python -m hermes_eval.t2c analyze <run-dir>

Two representations of the same model, published together by the same exporter
(csukuangfj, sherpa-onnx, 2025-08-16): the int8 export already used by Tasks 2a/2b, and its
fp32 sibling. Everything else is held identical: Public Proxy v1 audio bytes, sherpa-onnx
1.13.8 feature extraction and greedy TDT decoder, ORT 1.28 CPU EP, 4 threads, scoring.

`collect` runs four **arm processes** in ABAB order — int8, fp32, int8, fp32 — each a fresh
interpreter, so load time and peak working set belong to one representation and nothing
else, and so slow drift in system state lands on both arms rather than on one. Each arm
process:

1. builds the sherpa greedy recognizer (timed), warms it on the synthetic signal Task 2a
   used, and decodes all rows in manifest order — the only timed decode pass;
2. pass 1 only: decodes two controlled perturbations of every row (LSB dither; a 5 ms
   frame-grid shift), untimed for the latency figures;
3. pass 1 only: releases sherpa and runs the Task 2b direct-ORT probe greedy on the same
   files, for sherpa-vs-ORT parity.

Peak working set is read after step 1, before anything else is loaded.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import random
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import confidence_eval as ce
from .align import align
from .manifest import Record, load_strict
from .metrics import Counts, percentile
from .normalize import tokenize
from .provenance import git_state, hardware, run_id, software, utc_now

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "eval" / "datasets" / "public-proxy-v1" / "manifest.jsonl"
NUM_THREADS = 4
SEED = 20260926
RESAMPLES = 2000


@dataclass(frozen=True)
class Arm:
    precision: str
    model_dir: str
    encoder: str
    decoder: str
    joiner: str
    extra_files: tuple[str, ...] = ()

    @property
    def files(self) -> tuple[str, ...]:
        return (self.encoder, self.decoder, self.joiner, "tokens.txt", *self.extra_files)


ARMS = {
    "int8": Arm(
        "int8",
        "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
        "encoder.int8.onnx",
        "decoder.int8.onnx",
        "joiner.int8.onnx",
    ),
    # HF csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3 @ 1a468a35. The encoder exceeds
    # protobuf's 2 GB limit, so its weights live in an external-data file beside it.
    "fp32": Arm(
        "fp32",
        "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-fp32",
        "encoder.onnx",
        "decoder.onnx",
        "joiner.onnx",
        ("encoder.weights",),
    ),
}
SEQUENCE = (("int8", 1), ("fp32", 1), ("int8", 2), ("fp32", 2))


# =================================================================== perturbations


def _utt_seed(utt_id: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{SEED}:{utt_id}".encode()).digest()[:8], "little")


def perturb(kind: str, samples: Any, utt_id: str) -> Any:
    """Two perturbations a real capture path produces anyway, identical for both arms.

    `dither`: add N(0, 1 LSB) noise, seeded per utterance — below the 16-bit quantization
    step of the source audio, so no listener could hear it. `shift5ms`: drop the first 80
    samples, which moves the 10 ms feature frame grid by half a hop — what a different
    hotkey instant does to the same speech.
    """
    import numpy as np

    if kind == "dither":
        rng = np.random.default_rng(_utt_seed(utt_id))
        return (samples + rng.standard_normal(len(samples)) / 32768.0).astype(np.float32)
    if kind == "shift5ms":
        return samples[80:].copy()
    raise ValueError(kind)


PERTURBATIONS = ("dither", "shift5ms")


# ========================================================================= arm process


def _ws() -> dict[str, float | None]:
    from .resources import process_memory

    return process_memory()


def run_arm(run_dir: Path, precision: str, pass_idx: int, extras: bool) -> None:
    from .asr_sherpa import TARGET_RATE, _sha256, _warmup_signal, ensure_runtime, read_wav

    ensure_runtime()
    import sherpa_onnx

    arm = ARMS[precision]
    model_dir = REPO / "models" / arm.model_dir
    tag = f"{precision}-p{pass_idx}"
    records = load_strict(MANIFEST).records
    summary: dict[str, Any] = {
        "arm": precision,
        "pass": pass_idx,
        "started_utc": utc_now(),
        "git": git_state(REPO),
        "model_dir": arm.model_dir,
        "files": {
            f: {"bytes": (model_dir / f).stat().st_size, "sha256": _sha256(model_dir / f)}
            for f in arm.files
        },
        "memory_before_load": _ws(),
    }
    summary["model_bytes_total"] = sum(v["bytes"] for v in summary["files"].values())

    started = time.perf_counter()
    rec = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(model_dir / arm.encoder),
        decoder=str(model_dir / arm.decoder),
        joiner=str(model_dir / arm.joiner),
        tokens=str(model_dir / "tokens.txt"),
        num_threads=NUM_THREADS,
        provider="cpu",
        model_type="nemo_transducer",
        decoding_method="greedy_search",
    )
    summary["load_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
    summary["memory_after_load"] = _ws()

    def decode(samples: Any, rate: int) -> Any:
        stream = rec.create_stream()
        stream.accept_waveform(rate, samples)
        rec.decode_stream(stream)
        return stream.result

    started = time.perf_counter()
    signal = _warmup_signal()
    for _ in range(2):
        decode(signal, TARGET_RATE)
    summary["warmup_ms"] = round((time.perf_counter() - started) * 1000.0, 1)

    peak_current = 0.0
    with (run_dir / f"{tag}-sherpa.jsonl").open("w", encoding="utf-8") as sink:
        for n, record in enumerate(records, start=1):
            samples, rate, audio_s = read_wav(record.audio)
            t0 = time.perf_counter()
            res = decode(samples, rate)
            ms = round((time.perf_counter() - t0) * 1000.0, 2)
            cur = _ws().get("working_set_mb")
            if isinstance(cur, float):
                peak_current = max(peak_current, cur)
            row = {
                "id": record.id,
                "subset": record.metadata.get("subset"),
                "language": record.metadata.get("language"),
                "audio_s": round(audio_s, 3),
                "decode_ms": ms,
                "text": res.text,
                "tokens": list(res.tokens),
                "ys_log_probs": [float(x) for x in res.ys_log_probs],
            }
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"[{tag} {n}/{len(records)}] {record.id} {ms:.0f}ms", flush=True)
    summary["memory_after_decode"] = _ws()
    summary["peak_current_working_set_mb_during_decode"] = peak_current

    if extras:
        with (run_dir / f"{tag}-perturb.jsonl").open("w", encoding="utf-8") as sink:
            for n, record in enumerate(records, start=1):
                samples, rate, _ = read_wav(record.audio)
                row: dict[str, Any] = {"id": record.id}
                for kind in PERTURBATIONS:
                    res = decode(perturb(kind, samples, record.id), rate)
                    row[kind] = {
                        "text": res.text,
                        "tokens": list(res.tokens),
                        "ys_log_probs": [float(x) for x in res.ys_log_probs],
                    }
                sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"[{tag} perturb {n}/{len(records)}] {record.id}", flush=True)

        del rec
        gc.collect()
        from .tdt_probe import TdtProbe

        probe = TdtProbe(
            REPO / "models",
            num_threads=NUM_THREADS,
            model_dir=arm.model_dir,
            files=(arm.encoder, arm.decoder, arm.joiner),
        )
        with (run_dir / f"{tag}-probe.jsonl").open("w", encoding="utf-8") as sink:
            for n, record in enumerate(records, start=1):
                samples, _rate, _ = read_wav(record.audio)
                enc = probe.encode(samples)
                steps = probe.greedy(enc)
                emitted = [s for s in steps if s.token != probe.blank]
                row = {
                    "id": record.id,
                    "text": probe.text([s.token for s in emitted]),
                    "logp": [float(s.m["logp"]) for s in emitted],
                    "min_margin": min((float(s.m["margin"]) for s in emitted), default=None),
                }
                sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"[{tag} probe {n}/{len(records)}] {record.id}", flush=True)

    summary["finished_utc"] = utc_now()
    (run_dir / f"{tag}.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


# ============================================================================ collect


def collect(out_root: Path, resume: Path | None) -> Path:
    from .asr_sherpa import ensure_runtime

    ensure_runtime()
    import onnxruntime
    import sherpa_onnx

    manifest = load_strict(MANIFEST)
    if resume is not None:
        run_dir = resume
    else:
        run_dir = out_root / run_id("t2c-parakeet-int8-vs-fp32")
        run_dir.mkdir(parents=True)
        run = {
            "run_id": run_dir.name,
            "task": "Phase 0 Task 2c - Parakeet INT8 vs FP32 decision gate",
            "started_utc": utc_now(),
            "git": git_state(REPO),
            "hardware": hardware(),
            "software": {
                **software(),
                "sherpa_onnx": sherpa_onnx.__version__,
                "onnxruntime": onnxruntime.__version__,
            },
            "manifest": {
                "path": str(MANIFEST.relative_to(REPO)).replace("\\", "/"),
                "sha256": manifest.sha256,
                "n": len(manifest.records),
            },
            "config": {
                "threads": NUM_THREADS,
                "provider": "cpu",
                "decoding_method": "greedy_search",
                "sequence": [f"{a}-p{p}" for a, p in SEQUENCE],
                "perturbations": list(PERTURBATIONS),
                "arms": {k: v.__dict__ for k, v in ARMS.items()},
            },
        }
        (run_dir / "run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    for precision, pass_idx in SEQUENCE:
        if (run_dir / f"{precision}-p{pass_idx}.json").exists():
            continue
        cmd = [sys.executable, "-m", "hermes_eval.t2c", "arm", str(run_dir), precision]
        cmd += [str(pass_idx)] + (["--extras"] if pass_idx == 1 else [])
        subprocess.run(cmd, check=True, cwd=REPO)
    return run_dir


# ============================================================================ analyze

SLICES: dict[str, Callable[[dict[str, Any]], bool]] = {
    "overall": lambda r: True,
    "accented_en": lambda r: r["subset"] == "accented_en",
    "general_en": lambda r: r["subset"] == "general_en",
    "russian": lambda r: r["language"] == "ru",
    "noise": lambda r: r["subset"] == "robust_noise",
    "reverb": lambda r: r["subset"] == "robust_reverb",
}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _counts(reference: str, hypothesis: str) -> Counts:
    a = align(tokenize(reference, "basic"), tokenize(hypothesis, "basic"))
    return Counts(
        errors=a.errors, ref_len=a.ref_len, sub=a.substitutions, ins=a.insertions, dele=a.deletions
    )


def _rate(cs: Sequence[Counts]) -> float:
    ref = sum(c.ref_len for c in cs)
    return round(100.0 * sum(c.errors for c in cs) / ref, 3) if ref else 0.0


def _boot(a: Sequence[Counts], b: Sequence[Counts]) -> dict[str, Any]:
    from .bootstrap import paired_bootstrap

    r = paired_bootstrap(a, b, metric="wer", resamples=RESAMPLES, seed=SEED)
    return {
        "int8": round(r.rate_a * 100, 3),
        "fp32": round(r.rate_b * 100, 3),
        "delta_fp32_minus_int8_pp": r.delta_pp,
        "ci_pp": [r.ci_low_pp, r.ci_high_pp],
        "ci_excludes_zero": r.ci_excludes_zero,
    }


def _norm(text: str) -> str:
    return " ".join(tokenize(text, "basic"))


def _word_diff(a: str, b: str) -> int:
    return align(tokenize(a, "basic"), tokenize(b, "basic")).errors


def _units(row: dict[str, Any], ref: str) -> list[ce.Unit]:
    words, scores = ce.word_scores(
        row["tokens"],
        {"logp": row["ys_log_probs"]},
        {"maxprob_min": "logp:min", "maxprob_prod": "logp:sum"},
    )
    return ce.label_units(ref, row["tokens"], words, scores).units


def _auroc(groups: Sequence[Sequence[ce.Unit]], idx: Sequence[int]) -> float | None:
    pos, neg = [], []
    for i in idx:
        for u in groups[i]:
            (pos if u.correct else neg).append(u.scores["maxprob_min"])
    return ce.auroc(pos, neg)


def _ap(groups: Sequence[Sequence[ce.Unit]], idx: Sequence[int]) -> float | None:
    units = [u for i in idx for u in groups[i]]
    return ce.average_precision(
        [u.scores["maxprob_min"] for u in units], [not u.correct for u in units]
    )


def _q(xs: list[float], q: float) -> float | None:
    xs = sorted(xs)
    return round(ce._quantile(xs, q), 4) if xs else None


def confidence_compare(ga: Sequence[Sequence[ce.Unit]], gb: Sequence[Sequence[ce.Unit]]):
    """AUROC/AP per arm and fp32-int8 deltas, both arms on the *same* utterance resamples.

    The arms' hypotheses differ, so their word units are not paired; the utterance is the
    shared unit, which is what makes the delta interval paired.
    """
    n = len(ga)
    rng = random.Random(SEED)
    full = list(range(n))
    acc: dict[str, list[float]] = {k: [] for k in ("a_au", "b_au", "d_au", "a_ap", "b_ap", "d_ap")}
    for _ in range(RESAMPLES):
        idx = [rng.randrange(n) for _ in range(n)]
        a_au, b_au, a_ap, b_ap = _auroc(ga, idx), _auroc(gb, idx), _ap(ga, idx), _ap(gb, idx)
        if None in (a_au, b_au, a_ap, b_ap):
            continue
        assert a_au is not None and b_au is not None and a_ap is not None and b_ap is not None
        acc["a_au"].append(a_au)
        acc["b_au"].append(b_au)
        acc["d_au"].append(b_au - a_au)
        acc["a_ap"].append(a_ap)
        acc["b_ap"].append(b_ap)
        acc["d_ap"].append(b_ap - a_ap)

    def pt(fn: Callable[..., float | None], g: Any) -> float | None:
        v = fn(g, full)
        return round(v, 4) if v is not None else None

    out: dict[str, Any] = {}
    for arm, g, k in (("int8", ga, "a"), ("fp32", gb, "b")):
        units = [u for grp in g for u in grp]
        probs = [math.exp(u.scores["maxprob_prod"]) for u in units]
        out[arm] = {
            "units": len(units),
            "errors": sum(not u.correct for u in units),
            "auroc": pt(_auroc, g),
            "auroc_ci": [_q(acc[f"{k}_au"], 0.025), _q(acc[f"{k}_au"], 0.975)],
            "ap": pt(_ap, g),
            "ap_ci": [_q(acc[f"{k}_ap"], 0.025), _q(acc[f"{k}_ap"], 0.975)],
            "recall_at_10": ce._r(
                ce.recall_at(
                    [u.scores["maxprob_min"] for u in units], [not u.correct for u in units], 0.1
                )
            ),
            "ece_word_prob_prod": ce._r(ce.ece(probs, [u.correct for u in units])),
        }
    a, b = out["int8"], out["fp32"]
    out["delta_auroc_fp32_minus_int8"] = (
        round(b["auroc"] - a["auroc"], 4) if None not in (a["auroc"], b["auroc"]) else None
    )
    out["delta_auroc_ci"] = [_q(acc["d_au"], 0.025), _q(acc["d_au"], 0.975)]
    out["delta_ap_fp32_minus_int8"] = (
        round(b["ap"] - a["ap"], 4) if None not in (a["ap"], b["ap"]) else None
    )
    out["delta_ap_ci"] = [_q(acc["d_ap"], 0.025), _q(acc["d_ap"], 0.975)]
    return out


def _latency(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ms = [r["decode_ms"] for r in rows]
    audio = sum(r["audio_s"] for r in rows)
    short = [r["decode_ms"] for r in rows if r["audio_s"] <= 3.0]
    return {
        "rtf_corpus": round(sum(ms) / 1000.0 / audio, 4),
        "p50_ms": percentile(ms, 0.50),
        "p95_ms": percentile(ms, 0.95),
        "max_ms": max(ms),
        "median_ms_utts_le_3s": percentile(short, 0.50),
        "n_le_3s": len(short),
        "slower_than_realtime": sum(1 for r in rows if r["decode_ms"] / 1000.0 > r["audio_s"]),
    }


T2A_PARAKEET = REPO / "eval" / "runs" / "20260927T022919Z-t2a-parakeet-tdt-v3-aff8"
FAST_REGIME = 0.5


def _regime_matched(sher: dict[tuple[str, int], list[dict[str, Any]]]) -> dict[str, Any]:
    """Latency on rows where neither arm of a pass ran in the anomalous fast regime.

    Every arm process showed contiguous stretches of rows decoding several times faster
    than the same utterance did in Task 2a (same int8 model, same sherpa decode) — a
    system-state regime, not a model property. A row is "fast" when its decode time is
    below FAST_REGIME x Task 2a's for that utterance. Only rows normal in *both* arms of a
    pass are compared, so the two arms are timed on the same content in the same regime.
    """
    t2a = {r["id"]: r["latency_ms"] for r in _jsonl(T2A_PARAKEET / "predictions.jsonl")}
    out: dict[str, Any] = {"fast_threshold_vs_t2a": FAST_REGIME}
    for (arm, p), rows in sher.items():
        out[f"fast_rows_{arm}-p{p}"] = [
            n for n, r in enumerate(rows) if r["decode_ms"] < FAST_REGIME * t2a[r["id"]]
        ]
    for p in (1, 2):
        if ("int8", p) not in sher or ("fp32", p) not in sher:
            continue
        pairs = [
            (x, y)
            for x, y in zip(sher[("int8", p)], sher[("fp32", p)], strict=True)
            if min(x["decode_ms"] / t2a[x["id"]], y["decode_ms"] / t2a[y["id"]]) >= FAST_REGIME
        ]
        ratio = sorted(y["decode_ms"] / x["decode_ms"] for x, y in pairs)
        out[f"pass{p}"] = {
            "rows": len(pairs),
            "int8": _latency([x for x, _ in pairs]),
            "fp32": _latency([y for _, y in pairs]),
            "fp32_over_int8_ratio": {
                "median": _q(ratio, 0.5),
                "p05": _q(ratio, 0.05),
                "p95": _q(ratio, 0.95),
            },
        }
    return out


def _flip_boot(a: Sequence[bool], b: Sequence[bool]) -> list[float]:
    rng = random.Random(SEED)
    n = len(a)
    ds = []
    for _ in range(RESAMPLES):
        idx = [rng.randrange(n) for _ in range(n)]
        ds.append((sum(b[i] for i in idx) - sum(a[i] for i in idx)) / n * 100)
    return [_q(ds, 0.025) or 0.0, _q(ds, 0.975) or 0.0]


def analyze(run_dir: Path) -> dict[str, Any]:
    refs: dict[str, Record] = {r.id: r for r in load_strict(MANIFEST, require_audio=False).records}
    sher = {
        (a, p): _jsonl(run_dir / f"{a}-p{p}-sherpa.jsonl")
        for a, p in SEQUENCE
        if (run_dir / f"{a}-p{p}-sherpa.jsonl").exists()
    }
    summ = {
        (a, p): json.loads((run_dir / f"{a}-p{p}.json").read_text(encoding="utf-8"))
        for a, p in SEQUENCE
        if (run_dir / f"{a}-p{p}.json").exists()
    }
    i8, f32 = sher[("int8", 1)], sher[("fp32", 1)]
    assert [r["id"] for r in i8] == [r["id"] for r in f32]
    ref_of = {r["id"]: refs[r["id"]].reference for r in i8}
    out: dict[str, Any] = {"run_id": run_dir.name, "resamples": RESAMPLES, "seed": SEED}

    # --- quality --------------------------------------------------------------------
    def slice_rows(pred: Callable[[dict[str, Any]], bool], rows: Sequence[dict[str, Any]]):
        return [r for r in rows if pred(r)]

    groups: dict[str, Callable[[dict[str, Any]], bool]] = {"overall": lambda r: True}
    for lang in sorted({r["language"] for r in i8}):
        groups[f"language={lang}"] = lambda r, lang=lang: r["language"] == lang
    for sub in sorted({r["subset"] for r in i8}):
        groups[sub] = lambda r, sub=sub: r["subset"] == sub
    quality: dict[str, Any] = {}
    for name, pred in groups.items():
        a, b = slice_rows(pred, i8), slice_rows(pred, f32)
        entry = _boot(
            [_counts(ref_of[r["id"]], r["text"]) for r in a],
            [_counts(ref_of[r["id"]], r["text"]) for r in b],
        )
        entry["n"] = len(a)
        quality[name] = entry
    out["quality_wer_pass1"] = quality
    out["empty_outputs"] = {
        f"{a}-p{p}": sum(1 for r in rows if not r["text"].strip()) for (a, p), rows in sher.items()
    }
    out["cross_precision_text_identical"] = {
        "raw": sum(x["text"] == y["text"] for x, y in zip(i8, f32, strict=True)),
        "after_basic_norm": sum(
            _norm(x["text"]) == _norm(y["text"]) for x, y in zip(i8, f32, strict=True)
        ),
        "n": len(i8),
    }
    # WER of every pass, so the repeat passes are visibly the same numbers (or not).
    out["wer_by_pass"] = {
        f"{a}-p{p}": _rate([_counts(ref_of[r["id"]], r["text"]) for r in rows])
        for (a, p), rows in sher.items()
    }

    # --- stability: repeated identical runs -------------------------------------------
    repeat: dict[str, Any] = {}
    for arm in ARMS:
        if (arm, 2) not in sher:
            continue
        p1, p2 = sher[(arm, 1)], sher[(arm, 2)]
        diffs = [
            abs(x - y)
            for r1, r2 in zip(p1, p2, strict=True)
            if r1["text"] == r2["text"]
            for x, y in zip(r1["ys_log_probs"], r2["ys_log_probs"], strict=True)
        ]
        repeat[arm] = {
            "text_identical": sum(r1["text"] == r2["text"] for r1, r2 in zip(p1, p2, strict=True)),
            "n": len(p1),
            "logp_bit_identical_utts": sum(
                r1["ys_log_probs"] == r2["ys_log_probs"] for r1, r2 in zip(p1, p2, strict=True)
            ),
            "logp_max_absdiff": max(diffs) if diffs else None,
        }
    out["stability_repeat"] = repeat

    # --- stability: sherpa vs direct ORT --------------------------------------------
    parity: dict[str, Any] = {}
    for arm in ARMS:
        path = run_dir / f"{arm}-p1-probe.jsonl"
        if not path.exists():
            continue
        probe = _jsonl(path)
        sh = sher[(arm, 1)]
        same = [(s, q) for s, q in zip(sh, probe, strict=True) if s["text"] == q["text"]]
        lp = sorted(
            abs(x - y) for s, q in same for x, y in zip(s["ys_log_probs"], q["logp"], strict=True)
        )
        boot = _boot(
            [_counts(ref_of[r["id"]], r["text"]) for r in sh],
            [_counts(ref_of[r["id"]], r["text"]) for r in probe],
        )
        parity[arm] = {
            "text_identical": len(same),
            "after_basic_norm": sum(
                _norm(s["text"]) == _norm(q["text"]) for s, q in zip(sh, probe, strict=True)
            ),
            "n": len(sh),
            "wer_sherpa": boot["int8"],
            "wer_probe": boot["fp32"],
            "delta_probe_minus_sherpa_pp": boot["delta_fp32_minus_int8_pp"],
            "delta_ci_pp": boot["ci_pp"],
            "logp_absdiff_identical_texts": {
                "n_tokens": len(lp),
                "median": _q(lp, 0.5),
                "p95": _q(lp, 0.95),
                "max": round(lp[-1], 5) if lp else None,
            },
        }
    out["stability_parity"] = parity

    # --- stability: controlled perturbations ------------------------------------------
    pert: dict[str, Any] = {}
    pr = {a: _jsonl(run_dir / f"{a}-p1-perturb.jsonl") for a in ARMS}
    for kind in PERTURBATIONS:
        entry: dict[str, Any] = {}
        flips: dict[str, list[bool]] = {}
        for arm in ARMS:
            base = sher[(arm, 1)]
            rows = pr[arm]
            changed = [b["text"] != p[kind]["text"] for b, p in zip(base, rows, strict=True)]
            changed_norm = [
                _norm(b["text"]) != _norm(p[kind]["text"]) for b, p in zip(base, rows, strict=True)
            ]
            words = [
                _word_diff(b["text"], p[kind]["text"]) for b, p in zip(base, rows, strict=True)
            ]
            flips[arm] = changed_norm
            boot = _boot(
                [_counts(ref_of[b["id"]], b["text"]) for b in base],
                [
                    _counts(ref_of[b["id"]], p[kind]["text"])
                    for b, p in zip(base, rows, strict=True)
                ],
            )
            entry[arm] = {
                "text_changed_raw": sum(changed),
                "text_changed_after_norm": sum(changed_norm),
                "words_changed_total": sum(words),
                "wer_unperturbed": boot["int8"],
                "wer_perturbed": boot["fp32"],
                "delta_pp": boot["delta_fp32_minus_int8_pp"],
                "delta_ci_pp": boot["ci_pp"],
            }
        entry["flip_rate_delta_fp32_minus_int8_pp"] = round(
            (sum(flips["fp32"]) - sum(flips["int8"])) / len(flips["int8"]) * 100, 2
        )
        entry["flip_rate_delta_ci_pp"] = _flip_boot(flips["int8"], flips["fp32"])
        pert[kind] = entry
    out["stability_perturbation"] = pert

    # --- confidence -----------------------------------------------------------------
    conf: dict[str, Any] = {}
    for name, pred in SLICES.items():
        a, b = slice_rows(pred, i8), slice_rows(pred, f32)
        conf[name] = confidence_compare(
            [_units(r, ref_of[r["id"]]) for r in a], [_units(r, ref_of[r["id"]]) for r in b]
        )
        conf[name]["utterances"] = len(a)
    out["confidence_sherpa_emitted_token"] = conf

    # --- performance ----------------------------------------------------------------
    perf: dict[str, Any] = {}
    for (arm, p), rows in sher.items():
        s = summ[(arm, p)]
        perf[f"{arm}-p{p}"] = {
            **_latency(rows),
            "load_ms": s["load_ms"],
            "warmup_ms": s["warmup_ms"],
            "working_set_before_load_mb": s["memory_before_load"]["working_set_mb"],
            "working_set_after_load_mb": s["memory_after_load"]["working_set_mb"],
            "peak_working_set_mb": s["memory_after_decode"]["peak_working_set_mb"],
            "private_after_decode_mb": s["memory_after_decode"]["private_mb"],
            "model_bytes": s["model_bytes_total"],
        }
    ratios: dict[str, Any] = {}
    for p in (1, 2):
        if ("int8", p) in sher and ("fp32", p) in sher:
            r = sorted(
                y["decode_ms"] / x["decode_ms"]
                for x, y in zip(sher[("int8", p)], sher[("fp32", p)], strict=True)
            )
            ratios[f"pass{p}"] = {"median": _q(r, 0.5), "p05": _q(r, 0.05), "p95": _q(r, 0.95)}
    perf["fp32_over_int8_latency_ratio_per_utt"] = ratios
    perf["regime_matched"] = _regime_matched(sher)
    out["performance"] = perf

    (run_dir / "analysis.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out


# ================================================================================ cli


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hermes_eval.t2c")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--resume", type=Path)
    c.add_argument("--out", type=Path, default=REPO / "eval" / "runs")
    a = sub.add_parser("arm")
    a.add_argument("run_dir", type=Path)
    a.add_argument("precision", choices=sorted(ARMS))
    a.add_argument("pass_idx", type=int)
    a.add_argument("--extras", action="store_true")
    z = sub.add_parser("analyze")
    z.add_argument("run_dir", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "collect":
        print(collect(args.out, args.resume))
    elif args.cmd == "arm":
        run_arm(args.run_dir, args.precision, args.pass_idx, args.extras)
    else:
        print(json.dumps(analyze(args.run_dir), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
