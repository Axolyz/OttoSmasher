"""HubertFA adaptation: required transcript pauses vs optional acoustic SP.

The checkpoint and upstream decoder's frame/edge scoring are retained. Only
skip eligibility is changed; decoded short SP intervals are never gap-filled.
"""

import numpy as np


def states(phones):
    labels, optional = ["SP"], [True]
    for phone in phones:
        labels.extend(["SP" if phone in {"pau", "sil", "SP", "cl"} else "ja/" + phone, "SP"])
        optional.extend([False, True])
    if len(labels) == 1:
        raise ValueError("HubertFA 需要至少一个目标音素")
    return labels, np.asarray(optional, dtype=bool)


def forward_pass(T, S, prob_log, edge_prob, curr_ph_max_prob_log, dp, ph_seq_id, optional, prob3_pad_len=2):
    """Upstream transition scores with explicit state-level skip permissions."""
    backtrack = np.full_like(dp, -1, dtype=np.int32)
    edge_log, stay_log = np.log(edge_prob + 1e-6), np.log(1 - edge_prob + 1e-6)
    skip_states = np.arange(prob3_pad_len, S)
    skipped = skip_states - prob3_pad_len + 1
    for t in range(1, T):
        previous = dp[:, t - 1]
        stay = previous + prob_log[:, t] + stay_log[t]
        advance = np.full(S, -np.inf, dtype=np.float32)
        advance[1:] = previous[:-1] + prob_log[:-1, t] + edge_log[t] + curr_ph_max_prob_log[:-1] * (T / S)
        skip = np.full(S, -np.inf, dtype=np.float32)
        candidates = (
            previous[: S - prob3_pad_len]
            + prob_log[: S - prob3_pad_len, t]
            + edge_log[t]
            + curr_ph_max_prob_log[: S - prob3_pad_len] * (T / S)
        )
        skip[skip_states] = np.where(optional[skipped], candidates, -np.inf)
        scores = np.vstack((stay, advance, skip))
        chosen = np.argmax(scores, axis=0)
        dp[:, t], backtrack[:, t] = scores[chosen, np.arange(S)], chosen
        same = chosen == 0
        np.maximum(curr_ph_max_prob_log, prob_log[:, t], out=curr_ph_max_prob_log, where=same)
        np.copyto(curr_ph_max_prob_log, prob_log[:, t], where=~same)
        curr_ph_max_prob_log[ph_seq_id == 0] = 0
    return dp, backtrack, curr_ph_max_prob_log


def align(engine, path, phones):
    import soundfile as sf
    from tools.decoder import AlignmentDecoder

    labels, optional = states(phones)
    unknown = [p for p in labels if p not in engine.vocab["vocab"]]
    if unknown:
        raise ValueError(f"Unsupported HubertFA phones: {unknown}")

    class Decoder(AlignmentDecoder):
        def forward_pass(self, T, S, prob_log, edge_prob, maximum, dp, ids, prob3_pad_len=2):
            return forward_pass(T, S, prob_log, edge_prob, maximum, dp, ids, optional, prob3_pad_len)

    decoder = Decoder(engine.vocab, engine.mel_cfg["sample_rate"], engine.mel_cfg["hop_size"])
    wave, sr = sf.read(path, dtype="float32")
    if wave.ndim != 1 or sr != engine.mel_cfg["sample_rate"]:
        raise ValueError("HubertFA 输入必须匹配模型采样率的单声道")
    output = engine.run_onnx(engine.model, {"waveform": wave[None, :]})
    words, _ = decoder.decode(
        output["ph_frame_logits"], output["ph_edge_logits"], len(wave) / sr, labels, ignore_sp=False
    )
    return [
        {"start": float(a), "end": min(float(b), len(wave) / sr), "label": p.removeprefix("ja/")}
        for p, (a, b) in zip(words.phonemes, words.intervals)
        if b > a
    ]
