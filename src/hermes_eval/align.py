"""Levenshtein alignment over token sequences.

The one primitive every metric here is built on. Uniform costs (sub/ins/del = 1), which
is what WER is defined as; anything else would be a different metric wearing WER's name.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class Op(StrEnum):
    EQUAL = "equal"
    SUB = "sub"
    INS = "ins"  # token in the hypothesis with no reference counterpart
    DEL = "del"  # token in the reference with no hypothesis counterpart


@dataclass(frozen=True)
class Edit:
    op: Op
    ref_index: int | None
    hyp_index: int | None


@dataclass(frozen=True)
class Alignment:
    edits: tuple[Edit, ...]
    ref_len: int
    hyp_len: int

    def count(self, op: Op) -> int:
        return sum(1 for e in self.edits if e.op is op)

    @property
    def substitutions(self) -> int:
        return self.count(Op.SUB)

    @property
    def insertions(self) -> int:
        return self.count(Op.INS)

    @property
    def deletions(self) -> int:
        return self.count(Op.DEL)

    @property
    def errors(self) -> int:
        return self.substitutions + self.insertions + self.deletions


def align(ref: Sequence[str], hyp: Sequence[str]) -> Alignment:
    """Align hypothesis tokens to reference tokens.

    Backtrace tie-breaking is fixed (diagonal, then deletion, then insertion) so that the
    alignment — and therefore every downstream per-class count — is deterministic.
    """
    n, m = len(ref), len(hyp)
    # d[i][j] = edit distance between ref[:i] and hyp[:j]
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        d[i][0] = i
    for j in range(1, m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        ref_tok = ref[i - 1]
        row, prev = d[i], d[i - 1]
        for j in range(1, m + 1):
            sub = prev[j - 1] + (0 if ref_tok == hyp[j - 1] else 1)
            dele = prev[j] + 1
            ins = row[j - 1] + 1
            row[j] = sub if sub <= dele and sub <= ins else (dele if dele <= ins else ins)

    edits: list[Edit] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            if d[i][j] == d[i - 1][j - 1] + cost:
                edits.append(Edit(Op.EQUAL if cost == 0 else Op.SUB, i - 1, j - 1))
                i, j = i - 1, j - 1
                continue
        if i > 0 and d[i][j] == d[i - 1][j] + 1:
            edits.append(Edit(Op.DEL, i - 1, None))
            i -= 1
            continue
        edits.append(Edit(Op.INS, None, j - 1))
        j -= 1
    edits.reverse()
    return Alignment(tuple(edits), n, m)


def error_counts(ref: Sequence[str], hyp: Sequence[str]) -> tuple[int, int]:
    """(edit distance, reference length) — the pair the bootstrap resamples."""
    a = align(ref, hyp)
    return a.errors, a.ref_len
