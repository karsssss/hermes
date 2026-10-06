"""Task 2b driver: collect raw confidence / N-best evidence, then score it.

    uv run --group asr python -m hermes_eval.t2b collect   # ~45 min, ORT + sherpa
    uv run python -m hermes_eval.t2b analyze <run-dir>       # stdlib only

`collect` writes `eval/runs/<id>-t2b-parakeet-confidence-<x>/` with `run.json`
(provenance, graph I/O, parity) and `raw.jsonl` (one row per utterance: everything sherpa
returned, and everything the probe recorded). It appends row by row and skips ids already
present, so an interrupted collection resumes with `--resume <run-dir>`.

`analyze` reads only those two files plus the manifest, and writes `analysis.json`.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from . import confidence_eval as ce
from .align import align
from .manifest import Record, load_strict
from .metrics import Counts
from .normalize import tokenize
from .provenance import git_state, hardware, run_id, software, utc_now

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "eval" / "datasets" / "public-proxy-v1" / "manifest.jsonl"
BEAMS = (4, 8)
STEP_FIELDS = (
    "logp",
    "margin",
    "gibbs",
    "tsallis",
    "renyi",
    "logp_blank",
    "dur_logp",
    "dur_gibbs",
)


def _round(xs: Sequence[float], nd: int = 6) -> list[float]:
    return [round(float(x), nd) for x in xs]


# ======================================================================== collect


def completed_ids(raw: Path) -> set[str]:
    """Ids already collected, after making the file safe to append to.

    A collection can be killed mid-write (it was, once, by a memory-pressure reaper). Every
    complete row ends in a newline and is flushed before the next starts, so the only
    possible damage is one unterminated trailing fragment. It is cut off here — appending
    after it would weld the next row onto garbage — and its utterance is simply redone.
    Anything else that fails to parse is real corruption and raises.
    """
    data = raw.read_bytes()
    cut = data.rfind(b"\n") + 1
    if cut < len(data):
        raw.write_bytes(data[:cut])
    ids: list[str] = [
        json.loads(line)["id"] for line in data[:cut].decode("utf-8").splitlines() if line.strip()
    ]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{raw}: duplicate ids; refusing to resume")
    return set(ids)


def record_resume(run_dir: Path, rows_present: int, git: dict[str, object]) -> None:
    """Append a resume event to run.json, so the record says the run was not one sitting."""
    path = run_dir / "run.json"
    run = json.loads(path.read_text(encoding="utf-8"))
    run.setdefault("resumes", []).append(
        {"resumed_utc": utc_now(), "rows_present": rows_present, "git": git}
    )
    path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")


def collect(out_root: Path, resume: Path | None, limit: int | None) -> Path:
    from .asr_sherpa import CANDIDATES, _combined_sha256, ensure_runtime, read_wav

    ensure_runtime()
    import kaldi_native_fbank
    import numpy as np
    import onnxruntime
    import sherpa_onnx

    from .tdt_probe import MODEL_DIR, NUM_THREADS, TdtProbe

    manifest = load_strict(MANIFEST)
    records = manifest.records[:limit] if limit else manifest.records
    models = REPO / "models"
    model_dir = models / MODEL_DIR
    cand = CANDIDATES["parakeet-tdt-v3"]

    def recognizer(method: str, paths: int) -> Any:
        return sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(model_dir / "encoder.int8.onnx"),
            decoder=str(model_dir / "decoder.int8.onnx"),
            joiner=str(model_dir / "joiner.int8.onnx"),
            tokens=str(model_dir / "tokens.txt"),
            num_threads=NUM_THREADS,
            provider="cpu",
            model_type="nemo_transducer",
            decoding_method=method,
            max_active_paths=paths,
        )

    greedy = recognizer("greedy_search", 4)
    beam4 = recognizer("modified_beam_search", 4)
    probe = TdtProbe(models)

    if resume is not None:
        run_dir = resume
        done = completed_ids(run_dir / "raw.jsonl")
        record_resume(run_dir, len(done), git_state(REPO))
    else:
        run_dir = out_root / run_id("t2b-parakeet-confidence")
        run_dir.mkdir(parents=True)
        done = set()
        run = {
            "run_id": run_dir.name,
            "task": "Phase 0 Task 2b - Parakeet confidence / N-best architecture gate",
            "started_utc": utc_now(),
            "git": git_state(REPO),
            "hardware": hardware(),
            "software": {
                **software(),
                "sherpa_onnx": sherpa_onnx.__version__,
                "onnxruntime": onnxruntime.__version__,
                "kaldi_native_fbank": getattr(kaldi_native_fbank, "__version__", "1.22.3"),
                "numpy": np.__version__,
            },
            "manifest": {
                "path": str(MANIFEST.relative_to(REPO)).replace("\\", "/"),
                "sha256": manifest.sha256,
                "n": len(records),
            },
            "model": {
                "id": cand.model_id,
                "dir": MODEL_DIR,
                "sha256": _combined_sha256([model_dir / f for f in cand.files]),
                "graph_io": probe.io,
                "vocab_size_incl_blank": probe.vocab_size,
            },
            "config": {
                "threads": NUM_THREADS,
                "provider": "cpu",
                "sherpa_arms": ["greedy_search", "modified_beam_search max_active_paths=4"],
                "probe_beams": list(BEAMS),
            },
        }
        (run_dir / "run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")

    def timed(fn: Callable[..., Any], *args: Any) -> tuple[Any, float]:
        started = time.perf_counter()
        value = fn(*args)
        return value, round((time.perf_counter() - started) * 1000.0, 1)

    def sherpa_decode(rec: Any, samples: Any, rate: int) -> Any:
        stream = rec.create_stream()
        stream.accept_waveform(rate, samples)
        rec.decode_stream(stream)
        return stream.result

    with (run_dir / "raw.jsonl").open("a", encoding="utf-8") as sink:
        for n, record in enumerate(records, start=1):
            if record.id in done:
                continue
            samples, rate, audio_s = read_wav(record.audio)
            sg, sg_ms = timed(sherpa_decode, greedy, samples, rate)
            sb, sb_ms = timed(sherpa_decode, beam4, samples, rate)
            enc, enc_ms = timed(probe.encode, samples)
            steps, greedy_ms = timed(probe.greedy, enc)
            row: dict[str, Any] = {
                "id": record.id,
                "subset": record.metadata.get("subset"),
                "language": record.metadata.get("language"),
                "audio_s": round(audio_s, 3),
                "sherpa_greedy": {
                    "text": sg.text,
                    "tokens": list(sg.tokens),
                    "ys_log_probs": [float(x) for x in sg.ys_log_probs],
                    "timestamps": _round(sg.timestamps, 3),
                    "durations": _round(sg.durations, 3),
                    "decode_ms": sg_ms,
                },
                "sherpa_beam4": {
                    "text": sb.text,
                    "ys_log_probs": [float(x) for x in sb.ys_log_probs],
                    "decode_ms": sb_ms,
                },
                "probe": {
                    "encode_ms": enc_ms,
                    "greedy_ms": greedy_ms,
                    "frames": int(enc.shape[0]),
                    "steps": {
                        "frame": [s.frame for s in steps],
                        "token": [s.token for s in steps],
                        "skip": [s.skip for s in steps],
                        # Full precision on purpose: rounding manufactures ties, and ties
                        # are exactly what a ranking metric must not be handed.
                        **{k: [float(s.m[k]) for s in steps] for k in STEP_FIELDS},
                    },
                    "alternatives": [s.alternatives for s in steps if s.token != probe.blank],
                    "greedy_text": probe.text([s.token for s in steps if s.token != probe.blank]),
                },
            }
            for k in BEAMS:
                hyps, ms = timed(probe.beam, enc, k)
                row["probe"][f"beam{k}_ms"] = ms
                row["probe"][f"beam{k}"] = [
                    {
                        "text": probe.text(h.ys),
                        "ys": h.ys,
                        "score": round(h.log_prob, 5),
                        "ys_probs": _round(h.ys_probs),
                    }
                    for h in hyps
                ]
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            sink.flush()
            print(
                f"[{n}/{len(records)}] {record.id} sherpa {sg_ms:.0f}ms "
                f"probe enc {enc_ms:.0f} greedy {greedy_ms:.0f} "
                f"greedy_eq={row['probe']['greedy_text'] == sg.text}",
                flush=True,
            )
    return run_dir


# ======================================================================== analyze

# Word-level signals. Each is "<per-token signal>:<aggregation>". The first block is
# everything sherpa's public API exposes; the rest need the joiner's full output.
SHERPA_REACHABLE = {
    "maxprob_min": "logp:min",
    "maxprob_mean": "logp:mean",
    "maxprob_prod": "logp:sum",
}
NEEDS_DISTRIBUTION = {
    "tsallis_min": "tsallis:min",
    "tsallis_mean": "tsallis:mean",
    "gibbs_min": "gibbs:min",
    "renyi_min": "renyi:min",
    "margin_min": "margin:min",
    "nonblank_min": "nonblank:min",
    "tsallis_blank_min": "tsallis_blank:min",
    "dur_gibbs_min": "dur_gibbs:min",
    "dur_maxprob_min": "dur_logp:min",
}
BASELINE = "maxprob_min"

SLICES: dict[str, Callable[[dict[str, Any]], bool]] = {
    "overall": lambda r: True,
    "accented_en": lambda r: r["subset"] == "accented_en",
    "general_en": lambda r: r["subset"] == "general_en",
    "russian": lambda r: r["subset"] in ("ru_clean", "ru_command", "ru_farfield"),
    "noise": lambda r: r["subset"] == "robust_noise",
    "reverb": lambda r: r["subset"] == "robust_reverb",
}


def _token_signals(row: dict[str, Any], blank: int) -> tuple[list[str], dict[str, list[float]]]:
    """Per-emitted-token signals from the probe's greedy steps.

    `tsallis_blank` is the blank-inclusive variant: each token also takes the minimum over
    the blank steps that follow it up to the next emission — the frames NeMo's
    `exclude_blank=False` would fold in.
    """
    steps = row["probe"]["steps"]
    emitted = [i for i, t in enumerate(steps["token"]) if t != blank]
    signals: dict[str, list[float]] = {k: [] for k in STEP_FIELDS}
    signals["nonblank"] = []
    signals["tsallis_blank"] = []
    for n, i in enumerate(emitted):
        for k in STEP_FIELDS:
            signals[k].append(steps[k][i])
        signals["nonblank"].append(1.0 - math.exp(steps["logp_blank"][i]))
        end = emitted[n + 1] if n + 1 < len(emitted) else len(steps["token"])
        signals["tsallis_blank"].append(min(steps["tsallis"][i:end]))
    return [str(t) for t in (steps["token"][i] for i in emitted)], signals


def _pieces(vocab: list[str], ids: Sequence[str]) -> list[str]:
    return [vocab[int(i)] for i in ids]


def _load_vocab() -> list[str]:
    from .tdt_probe import MODEL_DIR

    vocab: list[str] = []
    path = REPO / "models" / MODEL_DIR / "tokens.txt"
    for line in path.read_text(encoding="utf-8").splitlines():
        piece, _, _ = line.rpartition(" ")
        vocab.append(piece.replace("▁", " "))
    return vocab


def _counts(reference: str, hypothesis: str) -> Counts:
    ref, hyp = tokenize(reference, "basic"), tokenize(hypothesis, "basic")
    a = align(ref, hyp)
    return Counts(
        errors=a.errors, ref_len=a.ref_len, sub=a.substitutions, ins=a.insertions, dele=a.deletions
    )


def _wer(pairs: Sequence[tuple[str, str]]) -> float:
    c = [_counts(r, h) for r, h in pairs]
    ref_len = sum(x.ref_len for x in c)
    return round(100.0 * sum(x.errors for x in c) / ref_len, 3) if ref_len else 0.0


def analyze(run_dir: Path, resamples: int) -> dict[str, Any]:
    from .bootstrap import paired_bootstrap

    refs: dict[str, Record] = {r.id: r for r in load_strict(MANIFEST, require_audio=False).records}
    rows = [
        json.loads(line)
        for line in (run_dir / "raw.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    vocab = _load_vocab()
    blank = len(vocab) - 1
    signals = {**SHERPA_REACHABLE, **NEEDS_DISTRIBUTION}

    # --- arm 1: the probe's greedy hypothesis, every signal on the same units --------
    probe_units: dict[str, list[ce.Unit]] = {}
    probe_dels: dict[str, int] = {}
    # --- arm 2: sherpa's own hypothesis and sherpa's own ys_log_probs, untouched ------
    sherpa_units: dict[str, list[ce.Unit]] = {}
    for row in rows:
        ref = refs[row["id"]].reference
        ids, tok_sig = _token_signals(row, blank)
        pieces = _pieces(vocab, ids)
        words, scores = ce.word_scores(pieces, tok_sig, signals)
        lab = ce.label_units(ref, pieces, words, scores)
        probe_units[row["id"]] = lab.units
        probe_dels[row["id"]] = lab.deletions

        sg = row["sherpa_greedy"]
        s_words, s_scores = ce.word_scores(
            sg["tokens"], {"logp": sg["ys_log_probs"]}, {"sherpa_maxprob_min": "logp:min"}
        )
        sherpa_units[row["id"]] = ce.label_units(ref, sg["tokens"], s_words, s_scores).units

    # --- parity -----------------------------------------------------------------
    same_text = [r for r in rows if r["probe"]["greedy_text"] == r["sherpa_greedy"]["text"]]
    lp_diffs: list[float] = []
    for r in same_text:
        steps = r["probe"]["steps"]
        mine = [steps["logp"][i] for i, t in enumerate(steps["token"]) if t != blank]
        lp_diffs += [
            abs(a - b) for a, b in zip(mine, r["sherpa_greedy"]["ys_log_probs"], strict=True)
        ]
    lp_diffs.sort()
    beam_same = sum(1 for r in rows if r["probe"]["beam4"][0]["text"] == r["sherpa_beam4"]["text"])

    def pairs(text_of: Callable[[dict[str, Any]], str], subset: Sequence[dict[str, Any]]):
        return [(refs[r["id"]].reference, text_of(r)) for r in subset]

    parity = {
        "greedy_text_identical": f"{len(same_text)}/{len(rows)}",
        "beam4_best_text_identical": f"{beam_same}/{len(rows)}",
        "emitted_logp_absdiff_on_identical_texts": {
            "n_tokens": len(lp_diffs),
            "median": round(lp_diffs[len(lp_diffs) // 2], 5) if lp_diffs else None,
            "p95": round(lp_diffs[int(0.95 * (len(lp_diffs) - 1))], 5) if lp_diffs else None,
            "max": round(lp_diffs[-1], 5) if lp_diffs else None,
        },
        "wer_sherpa_greedy": _wer(pairs(lambda r: r["sherpa_greedy"]["text"], rows)),
        "wer_probe_greedy": _wer(pairs(lambda r: r["probe"]["greedy_text"], rows)),
        "wer_sherpa_beam4": _wer(pairs(lambda r: r["sherpa_beam4"]["text"], rows)),
        "wer_probe_beam4": _wer(pairs(lambda r: r["probe"]["beam4"][0]["text"], rows)),
    }

    # --- word-level confidence --------------------------------------------------
    word_level: dict[str, Any] = {}
    for slice_name, pred in SLICES.items():
        chosen = [r for r in rows if pred(r)]
        if not chosen:
            continue
        groups = [probe_units[r["id"]] for r in chosen]
        units = [u for g in groups for u in g]
        entry: dict[str, Any] = {
            "utterances": len(chosen),
            "deletions_undetectable": sum(probe_dels[r["id"]] for r in chosen),
            "signals": {},
        }
        for name in signals:
            stats: dict[str, Any] = dict(ce.summarize(units, name))
            stats["sherpa_reachable"] = name in SHERPA_REACHABLE
            stats.update(
                ce.bootstrap_auroc(
                    groups, name, None if name == BASELINE else BASELINE, resamples=resamples
                )
            )
            entry["signals"][name] = stats
        s_groups = [sherpa_units[r["id"]] for r in chosen]
        s_units = [u for g in s_groups for u in g]
        native = dict(ce.summarize(s_units, "sherpa_maxprob_min"))
        native.update(ce.bootstrap_auroc(s_groups, "sherpa_maxprob_min", resamples=resamples))
        entry["sherpa_native_maxprob_min"] = native
        # Is the emitted-token probability a probability? Word P = exp(sum log p).
        probs = [math.exp(u.scores["maxprob_prod"]) for u in units]
        entry["calibration"] = {
            "ece_word_prob_prod": ce._r(ce.ece(probs, [u.correct for u in units])),
            "mean_word_prob": ce._r(sum(probs) / len(probs)) if probs else None,
            "accuracy": ce._r(sum(u.correct for u in units) / len(units)) if units else None,
        }
        word_level[slice_name] = entry

    # --- utterance level / sequence scores ----------------------------------------
    utt: dict[str, Any] = {}
    for slice_name, pred in SLICES.items():
        chosen = [r for r in rows if pred(r)]
        if not chosen:
            continue
        wer_u = [
            _counts(refs[r["id"]].reference, r["probe"]["greedy_text"]).errors
            / max(1, len(tokenize(refs[r["id"]].reference, "basic")))
            for r in chosen
        ]
        has_err = [w > 0 for w in wer_u]
        feats: dict[str, list[float]] = {
            "sherpa_mean_token_logp": [],
            "probe_min_word_tsallis": [],
            "beam4_score_per_frame": [],
            "beam4_top1_top2_gap": [],
        }
        for r in chosen:
            lps = r["sherpa_greedy"]["ys_log_probs"]
            feats["sherpa_mean_token_logp"].append(sum(lps) / len(lps) if lps else -99.0)
            us = probe_units[r["id"]]
            feats["probe_min_word_tsallis"].append(
                min((u.scores["tsallis_min"] for u in us), default=0.0)
            )
            b = r["probe"]["beam4"]
            feats["beam4_score_per_frame"].append(b[0]["score"] / max(1, r["probe"]["frames"]))
            feats["beam4_top1_top2_gap"].append(b[0]["score"] - b[1]["score"] if len(b) > 1 else 99)
        entry = {}
        for name, xs in feats.items():
            pos = [x for x, e in zip(xs, has_err, strict=True) if not e]
            neg = [x for x, e in zip(xs, has_err, strict=True) if e]
            entry[name] = {
                "spearman_vs_utt_wer": ce.spearman(xs, [-w for w in wer_u]),
                "auroc_error_free_vs_any_error": ce._r(ce.auroc(pos, neg)),
            }
        entry["utterances"] = len(chosen)
        entry["with_any_error"] = sum(has_err)
        utt[slice_name] = entry

    # --- N-best -------------------------------------------------------------------
    nbest: dict[str, Any] = {}
    for slice_name, pred in SLICES.items():
        chosen = [r for r in rows if pred(r)]
        if not chosen:
            continue
        entry = {"utterances": len(chosen)}
        greedy_c = [_counts(refs[r["id"]].reference, r["probe"]["greedy_text"]) for r in chosen]
        entry["wer_greedy"] = _rate(greedy_c)
        for k in BEAMS:
            best_c, oracle_c, distinct, distinct_norm = [], [], [], []
            for r in chosen:
                ref = refs[r["id"]].reference
                hyps = r["probe"][f"beam{k}"]
                cs = [_counts(ref, h["text"]) for h in hyps]
                best_c.append(cs[0])
                oracle_c.append(min(cs, key=lambda c: c.errors))
                distinct.append(len({h["text"] for h in hyps}))
                distinct_norm.append(len({" ".join(tokenize(h["text"], "basic")) for h in hyps}))
            boot = paired_bootstrap(greedy_c, best_c, metric="wer", resamples=resamples)
            entry[f"beam{k}"] = {
                "wer_best": _rate(best_c),
                "wer_oracle": _rate(oracle_c),
                "delta_best_vs_greedy_pp": boot.delta_pp,
                "delta_ci_pp": [boot.ci_low_pp, boot.ci_high_pp],
                "mean_distinct_texts": round(sum(distinct) / len(distinct), 3),
                "mean_distinct_after_basic_norm": round(sum(distinct_norm) / len(distinct), 3),
                "share_with_a_lexical_alternative": round(
                    sum(1 for d in distinct_norm if d > 1) / len(distinct), 3
                ),
            }
        nbest[slice_name] = entry

    # --- cost of owning the loop, as measured in this Python probe ------------------
    def total(key: str, arm: str = "probe") -> float:
        return sum(r[arm][key] for r in rows)

    audio = sum(r["audio_s"] for r in rows)
    timing = {
        "audio_s": round(audio, 1),
        "sherpa_greedy_rtf": round(total("decode_ms", "sherpa_greedy") / 1000 / audio, 4),
        "sherpa_beam4_rtf": round(total("decode_ms", "sherpa_beam4") / 1000 / audio, 4),
        "probe_encode_rtf": round(total("encode_ms") / 1000 / audio, 4),
        "probe_greedy_loop_rtf": round(total("greedy_ms") / 1000 / audio, 4),
        **{f"probe_beam{k}_loop_rtf": round(total(f"beam{k}_ms") / 1000 / audio, 4) for k in BEAMS},
    }

    result = {
        "run_id": run_dir.name,
        "analyzed_utc": utc_now(),
        "n": len(rows),
        "bootstrap": {"resamples": resamples, "seed": ce.DEFAULT_SEED, "unit": "utterance"},
        "unit": "basic-normalized hypothesis token (the WER unit)",
        "baseline_signal": BASELINE,
        "parity": parity,
        "word_level": word_level,
        "utterance_level": utt,
        "nbest": nbest,
        "timing": timing,
    }
    (run_dir / "analysis.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def _rate(counts: Sequence[Counts]) -> float:
    ref_len = sum(c.ref_len for c in counts)
    return round(100.0 * sum(c.errors for c in counts) / ref_len, 3) if ref_len else 0.0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hermes_eval.t2b")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--out", type=Path, default=REPO / "eval" / "runs")
    c.add_argument("--resume", type=Path, default=None)
    c.add_argument("--limit", type=int, default=None)
    a = sub.add_parser("analyze")
    a.add_argument("run_dir", type=Path)
    a.add_argument("--resamples", type=int, default=ce.DEFAULT_RESAMPLES)
    args = parser.parse_args(argv)
    if args.cmd == "collect":
        print(collect(args.out, args.resume, args.limit))
    else:
        analyze(args.run_dir, args.resamples)
        print(args.run_dir / "analysis.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
