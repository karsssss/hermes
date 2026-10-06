"""Task 2b: what confidence and N-best information the Parakeet TDT ONNX export carries.

This is a **measurement instrument, not a decoder Hermes ships.** It exists to answer one
question (SYNTHESIS §5.1, D-0011's Phase 0 exit criterion): can token confidences and an
N-best list come out of the ONNX artifact *without* Hermes owning the transducer decode
loop? Answering that needs two arms:

* **sherpa arm** — what sherpa-onnx 1.13.8's public API returns (`ys_log_probs`,
  `timestamps`, `durations`, one hypothesis). Reachable without owning the loop.
* **probe arm** — the same greedy and modified-beam algorithms, ported line for line from
  sherpa-onnx v1.13.8 (`offline-transducer-greedy-search-nemo-decoder.cc`,
  `offline-transducer-modified-beam-search-nemo-decoder.cc`) onto raw ONNX Runtime
  sessions, so that what sherpa *computes and throws away* — the full per-step token
  distribution, the duration distribution, every beam hypothesis and its score — is
  recorded. The port is only trusted where it reproduces sherpa's output exactly; parity
  is checked per utterance and reported, never assumed.

Features come from kaldi-native-fbank 1.22.3 — the version sherpa 1.13.8 compiles in —
configured exactly as `OfflineRecognizerTransducerNeMoImpl::PostInit` configures it,
followed by NeMo per-feature normalization as in `math.cc:NemoNormalizePerFeature`.

Confidence measures follow NeMo's `asr_confidence_utils.py` definitions (max_prob and the
Gibbs / Tsallis / Rényi entropies, linearly normalized to [0, 1] — see `step_measures` for
why not exponentially). R8 §D names Tsallis α=1/3, exp-normalized, min-aggregated as the
best published configuration; under min aggregation the linear form ranks identically.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MODEL_DIR = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
NUM_THREADS = 4
ALPHA = 1.0 / 3.0
TOP_K_ALTERNATIVES = 5
# sherpa v1.13.8 constants, copied rather than tuned.
GREEDY_MAX_TOKENS_PER_FRAME = 5
BEAM_MAX_SYMBOLS_PER_FRAME = 10


def _np() -> Any:
    import numpy as np

    return np


# ----------------------------------------------------------------------- features


def features(samples: Any, sample_rate: int = 16000, num_bins: int = 128) -> Any:
    """Log-mel features exactly as sherpa-onnx 1.13.8 builds them for a NeMo transducer.

    FeatureExtractorConfig defaults, overridden by the NeMo PostInit: low_freq 0,
    is_librosa true, remove_dc_offset false. Window stays "povey" and preemphasis stays
    0.97 because sherpa does not forward either for this model family.
    """
    import kaldi_native_fbank as knf

    np = _np()
    opts = knf.FbankOptions()
    opts.frame_opts.dither = 0.0
    opts.frame_opts.snip_edges = False
    opts.frame_opts.samp_freq = float(sample_rate)
    opts.frame_opts.frame_shift_ms = 10.0
    opts.frame_opts.frame_length_ms = 25.0
    opts.frame_opts.remove_dc_offset = False
    opts.frame_opts.window_type = "povey"
    opts.mel_opts.num_bins = num_bins
    opts.mel_opts.low_freq = 0.0
    opts.mel_opts.high_freq = -400.0
    opts.mel_opts.is_librosa = True
    fbank = knf.OnlineFbank(opts)
    fbank.accept_waveform(float(sample_rate), np.asarray(samples, dtype=np.float32).tolist())
    fbank.input_finished()
    n = fbank.num_frames_ready
    x = np.stack([np.asarray(fbank.get_frame(i), dtype=np.float32) for i in range(n)])
    mean = x.mean(axis=0, keepdims=True)
    var = np.square(x - mean).mean(axis=0, keepdims=True)
    return ((x - mean) / (np.sqrt(var) + 1e-5)).astype(np.float32)


# --------------------------------------------------------------- confidence measures


def step_measures(token_logits: Any, duration_logits: Any) -> dict[str, Any]:
    """Every per-step quantity the full distribution makes available.

    Entropy confidences are NeMo's *linear* normalization, 1 - H/H_max: 1 for a one-hot
    distribution, 0 for a uniform one. NeMo's best published configuration uses the
    exponential form, but under min aggregation the two produce the identical ranking (both
    are monotone in H), and the exponential form is numerically useless here: over 8193
    classes Tsallis-1/3 H_max is ~609, so a *confident* step with 0.1% residual mass spread
    over the vocabulary already scores exp(-60). Stored to finite precision, that collapses
    almost every word to the same value. Mean aggregation does differ between the forms;
    it is reported as linear and labelled so.
    """
    np = _np()
    v = token_logits.shape[-1]
    z = token_logits.astype(np.float64)
    logp = z - (np.max(z) + np.log(np.sum(np.exp(z - np.max(z)))))
    p = np.exp(logp)
    order = np.argsort(-logp)
    top1, top2 = float(logp[order[0]]), float(logp[order[1]])

    h_gibbs = -float(np.sum(p * logp))
    gibbs = 1.0 - h_gibbs / math.log(v)

    sum_pa = float(np.sum(np.exp(ALPHA * logp)))
    # Tsallis: H = (1 - sum p^a) / (a - 1);  uniform max H = (1 - v^(1-a)) / (a - 1).
    h_ts = (1.0 - sum_pa) / (ALPHA - 1.0)
    h_ts_max = (1.0 - v ** (1.0 - ALPHA)) / (ALPHA - 1.0)
    tsallis = 1.0 - h_ts / h_ts_max
    # Renyi: H = log(sum p^a) / (1 - a);  uniform max H = log v.
    h_re = math.log(sum_pa) / (1.0 - ALPHA)
    renyi = 1.0 - h_re / math.log(v)

    d = duration_logits.astype(np.float64)
    dlogp = d - (np.max(d) + np.log(np.sum(np.exp(d - np.max(d)))))
    dp = np.exp(dlogp)
    nd = d.shape[-1]
    dur_gibbs = (math.exp(float(np.sum(dp * dlogp))) * nd - 1.0) / (nd - 1.0)

    return {
        "logp": top1,
        "margin": top1 - top2,
        "gibbs": gibbs,
        "tsallis": tsallis,
        "renyi": renyi,
        "logp_blank": float(logp[v - 1]),
        "dur_logp": float(np.max(dlogp)),
        "dur_gibbs": dur_gibbs,
        "_order": order[:TOP_K_ALTERNATIVES],
        "_logp": logp,
    }


# ------------------------------------------------------------------------- sessions


@dataclass
class Step:
    """One joiner evaluation on the greedy path."""

    frame: int
    token: int
    skip: int
    m: dict[str, float]
    alternatives: list[tuple[int, float]] = field(default_factory=list)


@dataclass
class BeamHyp:
    ys: list[int]
    log_prob: float
    frame_offset: int = 0
    num_symbols: int = 0
    states: tuple[Any, Any] | None = None
    ys_probs: list[float] = field(default_factory=list)
    timestamps: list[int] = field(default_factory=list)


class TdtProbe:
    def __init__(
        self,
        models_root: Path,
        *,
        num_threads: int = NUM_THREADS,
        model_dir: str = MODEL_DIR,
        files: tuple[str, str, str] = (
            "encoder.int8.onnx",
            "decoder.int8.onnx",
            "joiner.int8.onnx",
        ),
    ) -> None:
        import onnxruntime as ort

        self.dir = Path(models_root) / model_dir
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = num_threads
        opts.inter_op_num_threads = num_threads

        def session(name: str) -> Any:
            return ort.InferenceSession(
                str(self.dir / name), sess_options=opts, providers=["CPUExecutionProvider"]
            )

        self.encoder = session(files[0])
        self.decoder = session(files[1])
        self.joiner = session(files[2])
        self.vocab: list[str] = []
        for line in (self.dir / "tokens.txt").read_text(encoding="utf-8").splitlines():
            piece, _, _idx = line.rpartition(" ")
            self.vocab.append(piece.replace("▁", " "))
        self.vocab_size = len(self.vocab)  # includes <blk>, which is last
        self.blank = self.vocab_size - 1
        self.unk = self.vocab.index("<unk>")
        self._dec_in = [i.name for i in self.decoder.get_inputs()]
        self.io = {
            name: {
                "inputs": [(i.name, i.shape, i.type) for i in s.get_inputs()],
                "outputs": [(o.name, o.shape, o.type) for o in s.get_outputs()],
                "metadata": dict(s.get_modelmeta().custom_metadata_map),
            }
            for name, s in (
                ("encoder", self.encoder),
                ("decoder", self.decoder),
                ("joiner", self.joiner),
            )
        }

    # -- graph calls ------------------------------------------------------------

    def encode(self, samples: Any) -> Any:
        np = _np()
        x = features(samples)
        out, lens = self.encoder.run(
            None,
            {
                "audio_signal": x.T[None, :, :].copy(),
                "length": np.asarray([x.shape[0]], dtype=np.int64),
            },
        )
        return out[0, :, : int(lens[0])].T.copy()  # (T, 1024)

    def init_states(self) -> tuple[Any, Any]:
        np = _np()
        z = np.zeros((2, 1, 640), dtype=np.float32)
        return z, z.copy()

    def run_decoder(self, token: int, states: tuple[Any, Any]) -> tuple[Any, tuple[Any, Any]]:
        np = _np()
        out, _len, s0, s1 = self.decoder.run(
            None,
            {
                self._dec_in[0]: np.asarray([[token]], dtype=np.int32),
                self._dec_in[1]: np.asarray([1], dtype=np.int32),
                self._dec_in[2]: states[0],
                self._dec_in[3]: states[1],
            },
        )
        return out, (s0, s1)

    def run_joiner(self, enc_frame: Any, dec_out: Any) -> Any:
        (logits,) = self.joiner.run(
            None,
            {"encoder_outputs": enc_frame[None, :, None], "decoder_outputs": dec_out},
        )
        return logits.reshape(-1)

    # -- greedy (DecodeOneTDT) -----------------------------------------------------

    def greedy(self, enc: Any) -> list[Step]:
        """sherpa's DecodeOneTDT, recording every step's full distribution."""
        np = _np()
        dec_out, states = self.run_decoder(self.blank, self.init_states())
        steps: list[Step] = []
        tokens_this_frame = 0
        t = 0
        num_rows = enc.shape[0]
        while t < num_rows:
            logits = self.run_joiner(enc[t], dec_out)
            token_logits = logits[: self.vocab_size]
            duration_logits = logits[self.vocab_size :]
            y = int(np.argmax(token_logits))
            skip = int(np.argmax(duration_logits))
            m = step_measures(token_logits, duration_logits)
            step = Step(frame=t, token=y, skip=skip, m={})
            if y != self.blank:
                step.alternatives = [(int(i), round(float(m["_logp"][i]), 5)) for i in m["_order"]]
            step.m = {k: v for k, v in m.items() if not k.startswith("_")}
            steps.append(step)
            if y != self.blank:
                dec_out, states = self.run_decoder(y, states)
                tokens_this_frame += 1
            if skip > 0:
                tokens_this_frame = 0
            if tokens_this_frame >= GREEDY_MAX_TOKENS_PER_FRAME:
                tokens_this_frame = 0
                skip = 1
            if y == self.blank and skip == 0:
                tokens_this_frame = 0
                skip = 1
            t += skip
        return steps

    # -- modified beam search (OfflineTransducerModifiedBeamSearchNeMoDecoder) -----

    def beam(self, enc: Any, beam: int) -> list[BeamHyp]:
        """sherpa's TDT modified beam search, minus the line that discards all but one.

        Faithful to v1.13.8 including its simplifications: duration is the argmax (no
        duration branching), hypotheses with identical token sequences are *not* merged,
        and scores of hypotheses sitting at different frames are compared directly. The
        only change is the return value: every surviving hypothesis, best first.
        """
        np = _np()
        num_frames = enc.shape[0]
        hyps = [BeamHyp(ys=[], log_prob=0.0, states=self.init_states())]
        while True:
            min_frame = min(h.frame_offset for h in hyps)
            if min_frame >= num_frames:
                break
            candidates: list[BeamHyp] = []
            for h in hyps:
                if h.frame_offset > min_frame:
                    candidates.append(h)
                    continue
                if h.num_symbols >= BEAM_MAX_SYMBOLS_PER_FRAME:
                    candidates.append(
                        BeamHyp(
                            ys=h.ys,
                            log_prob=h.log_prob,
                            frame_offset=h.frame_offset + 1,
                            states=h.states,
                            ys_probs=h.ys_probs,
                            timestamps=h.timestamps,
                        )
                    )
                    continue
                assert h.states is not None
                last = h.ys[-1] if h.ys else self.blank
                dec_out, next_states = self.run_decoder(last, h.states)
                logits = self.run_joiner(enc[h.frame_offset], dec_out).astype(np.float32)
                tl = logits[: self.vocab_size]
                dl = logits[self.vocab_size :]
                tl = tl - (tl.max() + np.log(np.exp(tl - tl.max()).sum()))
                dl = dl - (dl.max() + np.log(np.exp(dl - dl.max()).sum()))
                skip = int(np.argmax(dl))
                dur_lp = float(dl[skip])
                top = np.argsort(-tl, kind="stable")[:beam]
                for tok in (int(i) for i in top):
                    score = float(tl[tok]) + dur_lp + h.log_prob
                    if tok in (self.blank, self.unk):  # sherpa treats <unk> as blank
                        candidates.append(
                            BeamHyp(
                                ys=h.ys,
                                log_prob=score,
                                frame_offset=h.frame_offset + max(1, skip),
                                num_symbols=0,
                                states=h.states,
                                ys_probs=h.ys_probs,
                                timestamps=h.timestamps,
                            )
                        )
                    else:
                        candidates.append(
                            BeamHyp(
                                ys=[*h.ys, tok],
                                log_prob=score,
                                frame_offset=h.frame_offset + skip,
                                num_symbols=0 if skip > 0 else h.num_symbols + 1,
                                states=next_states,
                                ys_probs=[*h.ys_probs, float(tl[tok])],
                                timestamps=[*h.timestamps, h.frame_offset],
                            )
                        )
            # std::partial_sort is not stable; ties at float32 are vanishingly rare and
            # are broken here by insertion order.
            candidates.sort(key=lambda c: -c.log_prob)
            hyps = candidates[:beam]
        hyps.sort(key=lambda c: -c.log_prob)
        return hyps

    # -- text -------------------------------------------------------------------

    def text(self, ys: list[int]) -> str:
        return "".join(self.vocab[i] for i in ys).lstrip(" ")
