"""Paired utterance-level bootstrap and the decision rule.

The rule is written down here, in code, before any experiment runs — that is the whole
point of BENCHMARKS.md section 1.2. A change is an improvement only if all of:

  1. the 95% CI on delta F-WER excludes zero in the improving direction, and
  2. the point estimate is at least `min_effect_pp` absolute (0.3 pp default), and
  3. E-WER does not regress beyond its own noise floor, and
  4. latency p95 stays inside its absolute budget — a hard SLA gate, not a statistic.

Resampling uses `random.Random`, seeded and recorded, so a run is reproducible from the
run record alone. The same seed produces the same resample indices for every metric, so
the F-WER and E-WER intervals come from the same resamples and stay comparable.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

from .metrics import Counts

DEFAULT_RESAMPLES = 2000
DEFAULT_SEED = 20260926
MIN_EFFECT_PP = 0.3


@dataclass(frozen=True)
class BootstrapResult:
    metric: str
    n: int
    rate_a: float
    rate_b: float
    delta_pp: float
    ci_low_pp: float
    ci_high_pp: float
    seed: int
    resamples: int
    confidence: float

    @property
    def ci_excludes_zero(self) -> bool:
        return self.ci_low_pp > 0.0 or self.ci_high_pp < 0.0

    def to_json(self) -> dict[str, object]:
        d = asdict(self)
        d["ci_excludes_zero"] = self.ci_excludes_zero
        return d


def _rate(counts: Sequence[Counts], indices: Sequence[int]) -> float:
    errors = 0
    ref_len = 0
    for i in indices:
        c = counts[i]
        errors += c.errors
        ref_len += c.ref_len
    return errors / ref_len if ref_len else 0.0


def _quantile(ordered: Sequence[float], q: float) -> float:
    n = len(ordered)
    if n == 0:
        return 0.0
    if n == 1:
        return ordered[0]
    pos = q * (n - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return ordered[int(pos)]
    return ordered[lo] + (pos - lo) * (ordered[hi] - ordered[lo])


def paired_bootstrap(
    baseline: Sequence[Counts],
    candidate: Sequence[Counts],
    *,
    metric: str = "fwer",
    seed: int = DEFAULT_SEED,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = 0.95,
) -> BootstrapResult:
    """Resample utterances with replacement; recompute the corpus-level delta each time.

    `baseline` and `candidate` must be per-utterance counts in the same utterance order.
    Pairing is what makes the interval tight; scoring the two systems on different
    utterance sets would make it meaningless.
    """
    import random

    if len(baseline) != len(candidate):
        raise ValueError("paired bootstrap requires the same utterances in the same order")
    if resamples < 1:
        raise ValueError("resamples must be >= 1")
    n = len(baseline)
    if n == 0:
        raise ValueError("cannot bootstrap an empty set")

    rng = random.Random(seed)
    deltas: list[float] = []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        deltas.append(_rate(candidate, idx) - _rate(baseline, idx))
    deltas.sort()

    alpha = (1.0 - confidence) / 2.0
    all_idx = list(range(n))
    rate_a = _rate(baseline, all_idx)
    rate_b = _rate(candidate, all_idx)
    return BootstrapResult(
        metric=metric,
        n=n,
        rate_a=round(rate_a, 6),
        rate_b=round(rate_b, 6),
        delta_pp=round((rate_b - rate_a) * 100, 4),
        ci_low_pp=round(_quantile(deltas, alpha) * 100, 4),
        ci_high_pp=round(_quantile(deltas, 1.0 - alpha) * 100, 4),
        seed=seed,
        resamples=resamples,
        confidence=confidence,
    )


@dataclass(frozen=True)
class Decision:
    verdict: str
    reasons: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, object]:
        return {"verdict": self.verdict, "reasons": list(self.reasons)}


VERDICTS = (
    "improvement",
    "regression",
    "noise",
    "blocked_ewer_regression",
    "blocked_latency",
)


def apply_decision_rule(
    fwer: BootstrapResult,
    *,
    ewer: BootstrapResult | None = None,
    latency_p95_ms: float | None = None,
    latency_budget_ms: float | None = None,
    min_effect_pp: float = MIN_EFFECT_PP,
) -> Decision:
    """Candidate vs baseline. Negative delta means the candidate has fewer errors."""
    reasons: list[str] = []

    if latency_budget_ms is not None and latency_p95_ms is not None:
        if latency_p95_ms > latency_budget_ms:
            reasons.append(
                f"latency p95 {latency_p95_ms:.0f} ms exceeds the {latency_budget_ms:.0f} ms "
                "budget; p95 is a hard gate, not a statistical question"
            )
            return Decision("blocked_latency", reasons)
        reasons.append(
            f"latency p95 {latency_p95_ms:.0f} ms is within the {latency_budget_ms:.0f} ms budget"
        )

    ewer_regressed = ewer is not None and ewer.ci_low_pp > 0.0
    if ewer is not None:
        reasons.append(
            f"E-WER delta {ewer.delta_pp:+.2f} pp "
            f"[{ewer.ci_low_pp:+.2f}, {ewer.ci_high_pp:+.2f}]"
            + (" — significant regression" if ewer_regressed else " — no regression")
        )

    if fwer.ci_low_pp > 0.0:
        reasons.append(f"F-WER delta {fwer.delta_pp:+.2f} pp with a CI entirely above zero: worse")
        return Decision("regression", reasons)

    if fwer.ci_high_pp >= 0.0:
        reasons.append(
            f"F-WER delta {fwer.delta_pp:+.2f} pp "
            f"[{fwer.ci_low_pp:+.2f}, {fwer.ci_high_pp:+.2f}] includes zero: noise"
        )
        return Decision("noise", reasons)

    if abs(fwer.delta_pp) < min_effect_pp:
        reasons.append(
            f"F-WER delta {fwer.delta_pp:+.2f} pp is below the {min_effect_pp} pp "
            "minimum effect size"
        )
        return Decision("noise", reasons)

    if ewer_regressed:
        reasons.append("F-WER improved but E-WER regressed: aggregate win hiding rare-word damage")
        return Decision("blocked_ewer_regression", reasons)

    reasons.append(
        f"F-WER delta {fwer.delta_pp:+.2f} pp "
        f"[{fwer.ci_low_pp:+.2f}, {fwer.ci_high_pp:+.2f}] excludes zero and clears "
        f"{min_effect_pp} pp"
    )
    return Decision("improvement", reasons)
