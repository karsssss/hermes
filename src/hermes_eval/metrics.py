"""Metric definitions.

Exactly the metrics BENCHMARKS.md section 1 and 1.1 define, and nothing else.

  WER      plain word error rate, `basic` normalization. For comparability with
           published numbers. Nothing more.
  F-WER    the headline. WER on the literal text that would be injected: case- and
           punctuation-sensitive, `raw` normalization.
  casing   F-WER minus WER-computed-with-casefolding, in percentage points. The
           decomposition term that isolates how much of F-WER is casing.
  punct F1 per mark class, from a word-level alignment with trailing-mark labels.
  ITN SER  over the curated `itn_slots` of ITN-triggering utterances.
  E-WER    WER restricted to reference tokens inside entity spans. The TARQ guard:
           an aggregate win can hide rare-word damage.

Aggregate rates are corpus-level (sum of edits over sum of reference tokens), which is
the standard. Per-utterance counts are kept for every metric because pairing — and
therefore the bootstrap in bootstrap.py — is only valid at utterance granularity.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from .align import Op, align
from .manifest import Record
from .normalize import normalize, tokenize

# Scored punctuation classes. Apostrophes and hyphens are intra-word and are scored by
# F-WER itself, not here.
MARK_CLASSES = (".", ",", "?", "!", ":", ";")
_MARKS = frozenset(MARK_CLASSES)


@dataclass(frozen=True)
class Counts:
    """Edit counts against a reference length. The unit the bootstrap resamples."""

    errors: int = 0
    ref_len: int = 0
    sub: int = 0
    ins: int = 0
    dele: int = 0

    @property
    def rate(self) -> float:
        if self.ref_len == 0:
            return 0.0 if self.errors == 0 else 1.0
        return self.errors / self.ref_len

    def __add__(self, other: Counts) -> Counts:
        return Counts(
            self.errors + other.errors,
            self.ref_len + other.ref_len,
            self.sub + other.sub,
            self.ins + other.ins,
            self.dele + other.dele,
        )


@dataclass(frozen=True)
class PunctCounts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def __add__(self, other: PunctCounts) -> PunctCounts:
        return PunctCounts(self.tp + other.tp, self.fp + other.fp, self.fn + other.fn)

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass
class UtteranceScore:
    id: str
    reference: str
    hypothesis: str
    fwer: Counts
    wer: Counts
    cased: Counts
    ewer: Counts
    punctuation: dict[str, PunctCounts] = field(default_factory=dict)
    itn_slots_total: int = 0
    itn_slots_missed: int = 0
    unmatched_entities: tuple[str, ...] = ()
    latency_ms: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "reference": self.reference,
            "hypothesis": self.hypothesis,
            "fwer": round(self.fwer.rate, 6),
            "wer": round(self.wer.rate, 6),
            "ewer": round(self.ewer.rate, 6) if self.ewer.ref_len else None,
            "counts": {
                "fwer": asdict(self.fwer),
                "wer": asdict(self.wer),
                "cased": asdict(self.cased),
                "ewer": asdict(self.ewer),
            },
            "punctuation": {m: asdict(c) for m, c in sorted(self.punctuation.items())},
            "itn_slots_total": self.itn_slots_total,
            "itn_slots_missed": self.itn_slots_missed,
            "unmatched_entities": list(self.unmatched_entities),
            "latency_ms": self.latency_ms,
            "metadata": self.metadata,
        }


def counts_from(ref: Sequence[str], hyp: Sequence[str]) -> Counts:
    a = align(ref, hyp)
    return Counts(a.errors, a.ref_len, a.substitutions, a.insertions, a.deletions)


# --------------------------------------------------------------------------- entities


def entity_spans(ref_tokens: Sequence[str], entities: Iterable[str]) -> tuple[list[int], list[str]]:
    """Map each reference token to an entity id, or -1.

    Entities are matched as contiguous token subsequences under `basic` normalization.
    An entity that does not occur in its own reference is reported back rather than
    silently ignored — it means the manifest is wrong, and a wrong denominator is worse
    than a missing metric.
    """
    span_of = [-1] * len(ref_tokens)
    unmatched: list[str] = []
    for idx, entity in enumerate(entities):
        needle = tokenize(entity, "basic")
        if not needle:
            unmatched.append(entity)
            continue
        found = False
        for start in range(0, len(ref_tokens) - len(needle) + 1):
            if list(ref_tokens[start : start + len(needle)]) == needle:
                if all(span_of[i] == -1 for i in range(start, start + len(needle))):
                    for i in range(start, start + len(needle)):
                        span_of[i] = idx
                found = True
                break
        if not found:
            unmatched.append(entity)
    return span_of, unmatched


def entity_counts(
    ref_tokens: Sequence[str], hyp_tokens: Sequence[str], span_of: Sequence[int]
) -> Counts:
    """E-WER counts: substitutions and deletions of entity tokens, plus insertions
    strictly inside an entity span. Denominator is the number of entity tokens."""
    denom = sum(1 for s in span_of if s >= 0)
    if denom == 0:
        return Counts()
    a = align(ref_tokens, hyp_tokens)
    sub = dele = ins = 0
    consumed = 0  # reference tokens consumed so far
    for edit in a.edits:
        if edit.op is Op.INS:
            prev_i, next_i = consumed - 1, consumed
            if (
                0 <= prev_i < len(span_of)
                and next_i < len(span_of)
                and span_of[prev_i] >= 0
                and span_of[prev_i] == span_of[next_i]
            ):
                ins += 1
            continue
        i = edit.ref_index
        consumed += 1
        if i is None or span_of[i] < 0:
            continue
        if edit.op is Op.SUB:
            sub += 1
        elif edit.op is Op.DEL:
            dele += 1
    return Counts(sub + ins + dele, denom, sub, ins, dele)


# ------------------------------------------------------------------------ punctuation


def punctuation_sequence(text: str) -> list[tuple[str, str | None]]:
    """(word key, trailing mark) pairs. The word key is `basic`-normalized so that
    punctuation scoring is not contaminated by casing or spelling of the word itself."""
    out: list[tuple[str, str | None]] = []
    for token in tokenize(text, "raw"):
        mark: str | None = None
        core = token
        while core and core[-1] in _MARKS:
            if mark is None:
                mark = core[-1]
            core = core[:-1]
        key = "".join(tokenize(core, "basic"))
        if not key:
            if mark is not None and out:
                # A free-standing mark belongs to the preceding word.
                out[-1] = (out[-1][0], mark)
            continue
        out.append((key, mark))
    return out


def punctuation_counts(reference: str, hypothesis: str) -> dict[str, PunctCounts]:
    ref = punctuation_sequence(reference)
    hyp = punctuation_sequence(hypothesis)
    a = align([w for w, _ in ref], [w for w, _ in hyp])
    tp: dict[str, int] = {m: 0 for m in MARK_CLASSES}
    fp: dict[str, int] = {m: 0 for m in MARK_CLASSES}
    fn: dict[str, int] = {m: 0 for m in MARK_CLASSES}
    for edit in a.edits:
        r_mark = ref[edit.ref_index][1] if edit.ref_index is not None else None
        h_mark = hyp[edit.hyp_index][1] if edit.hyp_index is not None else None
        if r_mark == h_mark:
            if r_mark is not None:
                tp[r_mark] += 1
            continue
        if r_mark is not None:
            fn[r_mark] += 1
        if h_mark is not None:
            fp[h_mark] += 1
    return {m: PunctCounts(tp[m], fp[m], fn[m]) for m in MARK_CLASSES}


# ------------------------------------------------------------------------------- ITN


def _slot_present(text: str, slot: str) -> bool:
    """Exact surface-form presence, bounded so that `3` does not match inside `30`."""
    haystack = normalize(text, "raw")
    pattern = r"(?<![0-9A-Za-z_])" + re.escape(normalize(slot, "raw")) + r"(?![0-9A-Za-z_])"
    return re.search(pattern, haystack) is not None


# ---------------------------------------------------------------------------- scoring


def score_utterance(
    record: Record, hypothesis: str, latency_ms: float | None = None
) -> UtteranceScore:
    ref_raw, hyp_raw = tokenize(record.reference, "raw"), tokenize(hypothesis, "raw")
    ref_cf, hyp_cf = tokenize(record.reference, "casefold"), tokenize(hypothesis, "casefold")
    ref_basic, hyp_basic = tokenize(record.reference, "basic"), tokenize(hypothesis, "basic")

    span_of, unmatched = entity_spans(ref_basic, record.entities)
    missed = sum(1 for slot in record.itn_slots if not _slot_present(hypothesis, slot.text))

    return UtteranceScore(
        id=record.id,
        reference=record.reference,
        hypothesis=hypothesis,
        fwer=counts_from(ref_raw, hyp_raw),
        wer=counts_from(ref_basic, hyp_basic),
        cased=counts_from(ref_cf, hyp_cf),
        ewer=entity_counts(ref_basic, hyp_basic, span_of),
        punctuation=punctuation_counts(record.reference, hypothesis),
        itn_slots_total=len(record.itn_slots),
        itn_slots_missed=missed,
        unmatched_entities=tuple(unmatched),
        latency_ms=latency_ms,
        metadata=dict(record.metadata),
    )


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile. Deterministic, and it never invents a value that is not
    in the sample — which is what you want when the number is an SLA gate."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def aggregate(scores: Sequence[UtteranceScore]) -> dict[str, Any]:
    fwer = sum((s.fwer for s in scores), Counts())
    wer = sum((s.wer for s in scores), Counts())
    cased = sum((s.cased for s in scores), Counts())
    ewer = sum((s.ewer for s in scores), Counts())

    punct: dict[str, PunctCounts] = {m: PunctCounts() for m in MARK_CLASSES}
    for s in scores:
        for mark, c in s.punctuation.items():
            punct[mark] = punct[mark] + c
    micro = sum(punct.values(), PunctCounts())

    slots_total = sum(s.itn_slots_total for s in scores)
    slots_missed = sum(s.itn_slots_missed for s in scores)
    latencies = [s.latency_ms for s in scores if s.latency_ms is not None]

    return {
        "n_utterances": len(scores),
        "fwer": round(fwer.rate, 6),
        "wer": round(wer.rate, 6),
        "wer_casefold": round(cased.rate, 6),
        "casing_error_rate_pp": round((fwer.rate - cased.rate) * 100, 4),
        "ewer": round(ewer.rate, 6) if ewer.ref_len else None,
        "ewer_reference_tokens": ewer.ref_len,
        "counts": {
            "fwer": asdict(fwer),
            "wer": asdict(wer),
            "cased": asdict(cased),
            "ewer": asdict(ewer),
        },
        "punctuation_f1": {
            mark: {
                "precision": round(c.precision, 6),
                "recall": round(c.recall, 6),
                "f1": round(c.f1, 6),
                **asdict(c),
            }
            for mark, c in sorted(punct.items())
        },
        "punctuation_f1_micro": round(micro.f1, 6),
        "itn": {
            "slots_total": slots_total,
            "slots_missed": slots_missed,
            # Insertions of spurious ITN output are NOT measured in v0: detecting them
            # needs a slot detector over free text. Do not read this as zero.
            "slot_error_rate": round(slots_missed / slots_total, 6) if slots_total else None,
            "insertions_measured": False,
        },
        "latency_ms": {
            "n": len(latencies),
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
        },
        "unmatched_entities": sorted({e for s in scores for e in s.unmatched_entities}),
    }


SUBSET_AXES = ("language", "accent", "domain", "category", "speaker", "noise", "app")


def subset_metrics(scores: Sequence[UtteranceScore]) -> dict[str, dict[str, Any]]:
    """Group-by metrics over the manifest metadata axes, plus a derived code-switch axis."""
    out: dict[str, dict[str, Any]] = {}
    for axis in SUBSET_AXES:
        groups: dict[str, list[UtteranceScore]] = {}
        for s in scores:
            value = s.metadata.get(axis)
            if isinstance(value, str) and value:
                groups.setdefault(value, []).append(s)
        if groups:
            out[axis] = {key: aggregate(groups[key]) for key in sorted(groups)}

    cs: dict[str, list[UtteranceScore]] = {}
    for s in scores:
        key = "code_switched" if s.metadata.get("code_switch") else "monolingual"
        cs.setdefault(key, []).append(s)
    if len(cs) > 1:
        out["code_switch"] = {key: aggregate(cs[key]) for key in sorted(cs)}
    return out
