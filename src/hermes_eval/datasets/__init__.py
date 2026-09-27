"""Dataset acquisition for the public proxy evaluation set.

This subpackage is **not** on the scoring path. `hermes_eval` proper stays stdlib-only so
that a published benchmark cannot blame its numbers on a third-party WER package; this
subpackage is a build-time tool that turns pinned public corpora into a manifest, and it
is allowed the `data` dependency group (numpy, soundfile) for audio decode, resampling
and augmentation. Nothing here is imported by `runner`, `metrics` or `cli`'s scoring
commands.

Why a fetcher rather than checked-in audio: EdAcc is CC BY-SA 4.0 and Golos carries a
ShareAlike-equivalent bespoke licence, so redistributing derived audio would make that
audio Adapted Material with obligations attached. Shipping a manifest plus a
deterministic fetcher keeps the repository free of third-party audio, keeps it small, and
still reproduces byte-identical inputs — every record carries the sha256 of the exact
16 kHz WAV it was scored on.
"""

from .build import BuildReport, build
from .sources import SOURCES, Source

__all__ = ["SOURCES", "BuildReport", "Source", "build"]
