"""Scoring word confidence against recognition errors (Task 2b).

Stdlib only, like the rest of the scoring path: the numbers here decide an architecture
question, so they must not depend on a third-party metrics package.

The unit is the WER unit. A hypothesis is split into ASR words (a BPE piece starting with
a space opens a word), each word gets a confidence by aggregating its tokens, and the word
is then `basic`-normalized exactly as WER normalizes — so "kube-system" becomes two scored
units sharing one confidence, and a bare "," becomes none. Each unit is labelled correct
iff the Levenshtein alignment against the `basic` reference marks it EQUAL. Substitutions
and insertions are the errors a word confidence can flag; **deletions have no hypothesis
word to carry a score, so no word-level confidence can detect them**, and they are counted
separately rather than silently dropped.

Metrics, all of which need only relative ranking — none assumes calibration:

* AUROC — P(conf of a random correct unit > conf of a random incorrect one), ties 1/2.
* AP — average precision for *error detection*, ranking by ascending confidence. Its
  chance level is the error rate, which is reported next to it.
* recall@k — share of errors caught when the lowest-confidence k% of units are flagged,
  which is the highlighting budget the UI would actually spend.

ECE is provided for signals that claim to be a probability, to test exactly that claim.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from .align import Op, align
from .normalize import tokenize

DEFAULT_RESAMPLES = 2000
DEFAULT_SEED = 20260926

AGGREGATIONS: dict[str, Callable[[Sequence[float]], float]] = {
    "min": min,
    "mean": lambda xs: sum(xs) / len(xs),
    "sum": sum,
}


def is_punctuation_piece(piece: str) -> bool:
    """A BPE piece that `basic` normalization would erase entirely."""
    return not tokenize(piece, "basic")


def group_words(pieces: Sequence[str]) -> list[list[int]]:
    """Token indices per ASR word. A piece with a leading space opens a new word."""
    words: list[list[int]] = []
    for i, piece in enumerate(pieces):
        if not words or piece.startswith(" "):
            words.append([i])
        else:
            words[-1].append(i)
    return words


@dataclass(frozen=True)
class Unit:
    """One scored WER unit: a `basic` token of the hypothesis."""

    text: str
    word: int
    correct: bool
    scores: dict[str, float]


@dataclass(frozen=True)
class Labelled:
    units: list[Unit]
    deletions: int
    ref_len: int


def word_scores(
    pieces: Sequence[str],
    token_signals: Mapping[str, Sequence[float]],
    aggregations: Mapping[str, str],
) -> tuple[list[list[int]], list[dict[str, float]]]:
    """Aggregate per-token signals to per-word scores.

    `aggregations` maps an output name to "<signal>:<agg>", e.g. {"tsallis_min":
    "tsallis:min"}. Punctuation-only pieces are excluded from the aggregate, because a
    comma's uncertainty is a formatting question that WER cannot score; a word made only
    of punctuation produces no unit downstream anyway.
    """
    words = group_words(pieces)
    out: list[dict[str, float]] = []
    for idx in words:
        lexical = [i for i in idx if not is_punctuation_piece(pieces[i])] or idx
        scores: dict[str, float] = {}
        for name, spec in aggregations.items():
            signal, _, agg = spec.partition(":")
            scores[name] = AGGREGATIONS[agg]([token_signals[signal][i] for i in lexical])
        out.append(scores)
    return words, out


def label_units(
    reference: str,
    pieces: Sequence[str],
    word_index: Sequence[list[int]],
    scores: Sequence[Mapping[str, float]],
) -> Labelled:
    """Split each ASR word into `basic` units and label each against the reference."""
    texts: list[str] = []
    owners: list[int] = []
    for w, idx in enumerate(word_index):
        for tok in tokenize("".join(pieces[i] for i in idx), "basic"):
            texts.append(tok)
            owners.append(w)
    whole = tokenize("".join(pieces), "basic")
    if texts != whole:  # pragma: no cover - guards the unit definition, not data
        raise ValueError(f"per-word normalization disagrees with whole-text: {texts} != {whole}")
    ref = tokenize(reference, "basic")
    alignment = align(ref, texts)
    correct = [False] * len(texts)
    for edit in alignment.edits:
        if edit.op is Op.EQUAL and edit.hyp_index is not None:
            correct[edit.hyp_index] = True
    units = [
        Unit(text=t, word=owners[j], correct=correct[j], scores=dict(scores[owners[j]]))
        for j, t in enumerate(texts)
    ]
    return Labelled(units=units, deletions=alignment.deletions, ref_len=len(ref))


# ------------------------------------------------------------------------ metrics


def auroc(correct: Sequence[float], incorrect: Sequence[float]) -> float | None:
    """Mann-Whitney AUROC with ties counted as 1/2. None when a class is empty."""
    n_pos, n_neg = len(correct), len(incorrect)
    if n_pos == 0 or n_neg == 0:
        return None
    pooled = sorted([(s, 1) for s in correct] + [(s, 0) for s in incorrect])
    rank_sum = 0.0
    i = 0
    while i < len(pooled):
        j = i
        while j + 1 < len(pooled) and pooled[j + 1][0] == pooled[i][0]:
            j += 1
        mid_rank = (i + j) / 2.0 + 1.0
        rank_sum += mid_rank * sum(1 for k in range(i, j + 1) if pooled[k][1] == 1)
        i = j + 1
    return (rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def _by_ascending(scores: Sequence[float], is_error: Sequence[bool]) -> list[bool]:
    # Ties are broken pessimistically (errors last), so a constant signal scores at chance
    # rather than borrowing the order the units happened to arrive in.
    order = sorted(range(len(scores)), key=lambda i: (scores[i], is_error[i]))
    return [is_error[i] for i in order]


def average_precision(scores: Sequence[float], is_error: Sequence[bool]) -> float | None:
    """AP for error detection, ranking by ascending confidence."""
    total = sum(is_error)
    if total == 0:
        return None
    hits = 0
    ap = 0.0
    for rank, err in enumerate(_by_ascending(scores, is_error), start=1):
        if err:
            hits += 1
            ap += hits / rank
    return ap / total


def recall_at(scores: Sequence[float], is_error: Sequence[bool], fraction: float) -> float | None:
    """Share of errors among the lowest-confidence `fraction` of units."""
    total = sum(is_error)
    if total == 0:
        return None
    k = max(1, round(fraction * len(scores)))
    return sum(_by_ascending(scores, is_error)[:k]) / total


def ece(probs: Sequence[float], correct: Sequence[bool], bins: int = 10) -> float | None:
    """Expected calibration error of `probs` as P(correct), equal-width bins."""
    n = len(probs)
    if n == 0:
        return None
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        members = [i for i, p in enumerate(probs) if lo <= p < hi or (b == bins - 1 and p == hi)]
        if members:
            conf = sum(probs[i] for i in members) / len(members)
            acc = sum(1 for i in members if correct[i]) / len(members)
            total += len(members) / n * abs(conf - acc)
    return total


def summarize(units: Sequence[Unit], signal: str) -> dict[str, float | int | None]:
    scores = [u.scores[signal] for u in units]
    errs = [not u.correct for u in units]
    pos = [s for s, e in zip(scores, errs, strict=True) if not e]
    neg = [s for s, e in zip(scores, errs, strict=True) if e]
    return {
        "units": len(units),
        "errors": len(neg),
        "error_rate": round(len(neg) / len(units), 4) if units else None,
        "auroc": _r(auroc(pos, neg)),
        "ap": _r(average_precision(scores, errs)),
        "recall_at_10": _r(recall_at(scores, errs, 0.10)),
        "recall_at_20": _r(recall_at(scores, errs, 0.20)),
    }


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 4)


# ---------------------------------------------------------------------- bootstrap


def _quantile(ordered: Sequence[float], q: float) -> float:
    pos = q * (len(ordered) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (pos - lo) * (ordered[hi] - ordered[lo])


def bootstrap_auroc(
    groups: Sequence[Sequence[Unit]],
    signal: str,
    baseline: str | None = None,
    *,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> dict[str, float | None]:
    """Utterance-level bootstrap CI of AUROC, and of AUROC(signal) - AUROC(baseline).

    Units inside an utterance are correlated (one bad segment makes several bad words), so
    the resampling unit is the utterance, never the word. Both signals see the same
    resamples, which is what makes the delta interval paired.
    """
    rng = random.Random(seed)
    n = len(groups)

    def stat(idx: Sequence[int], name: str) -> float | None:
        pos: list[float] = []
        neg: list[float] = []
        for i in idx:
            for u in groups[i]:
                (pos if u.correct else neg).append(u.scores[name])
        return auroc(pos, neg)

    values: list[float] = []
    deltas: list[float] = []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        a = stat(idx, signal)
        if a is None:
            continue
        values.append(a)
        if baseline is not None:
            b = stat(idx, baseline)
            if b is not None:
                deltas.append(a - b)
    values.sort()
    deltas.sort()
    out: dict[str, float | None] = {
        "auroc_ci_low": _r(_quantile(values, 0.025)) if values else None,
        "auroc_ci_high": _r(_quantile(values, 0.975)) if values else None,
    }
    if baseline is not None:
        full = list(range(n))
        a, b = stat(full, signal), stat(full, baseline)
        out["delta_vs_baseline"] = _r(a - b) if a is not None and b is not None else None
        out["delta_ci_low"] = _r(_quantile(deltas, 0.025)) if deltas else None
        out["delta_ci_high"] = _r(_quantile(deltas, 0.975)) if deltas else None
    return out


def bootstrap_ap(
    groups: Sequence[Sequence[Unit]],
    signal: str,
    *,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> dict[str, float | None]:
    """Utterance-level bootstrap CI of error-detection AP, same resampling as AUROC's."""
    rng = random.Random(seed)
    n = len(groups)
    values: list[float] = []
    for _ in range(resamples):
        units = [u for _ in range(n) for u in groups[rng.randrange(n)]]
        ap = average_precision([u.scores[signal] for u in units], [not u.correct for u in units])
        if ap is not None:
            values.append(ap)
    values.sort()
    return {
        "ap_ci_low": _r(_quantile(values, 0.025)) if values else None,
        "ap_ci_high": _r(_quantile(values, 0.975)) if values else None,
    }


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman rank correlation with average ranks for ties."""

    def ranks(v: Sequence[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2.0
            i = j + 1
        return r

    if len(xs) < 3:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return _r(cov / (vx * vy)) if vx and vy else None
