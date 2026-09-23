"""CTC forced Viterbi alignment with explicit blanks and repeated-token states."""

import numpy as np


def forced_ctc(logits, tokens, blank=0):
    x = np.asarray(logits, dtype=np.float64)
    if x.ndim != 2 or not tokens or not np.isfinite(x).all():
        raise ValueError("Invalid emission or empty transcript")
    x = x - np.logaddexp.reduce(x, axis=1)[:, None]
    states = np.full(2 * len(tokens) + 1, blank, dtype=int)
    states[1::2] = tokens
    count = len(states)
    prior = np.full(count, -np.inf)
    prior[0] = 0
    trace = np.zeros((len(x), count), dtype=np.int8)
    skip = np.zeros(count, dtype=bool)
    skip[2:] = (states[2:] != blank) & (states[2:] != states[:-2])
    for t, frame in enumerate(x):
        alternatives = np.stack([prior, np.r_[-np.inf, prior[:-1]], np.r_[-np.inf, -np.inf, prior[:-2]]])
        alternatives[2, ~skip] = -np.inf
        moves = alternatives.argmax(axis=0)
        prior = alternatives[moves, np.arange(count)] + frame[states]
        trace[t] = moves
    s = count - 1 if prior[-1] >= prior[-2] else count - 2
    if not np.isfinite(prior[s]):
        raise ValueError("Insufficient CTC frames for transcript/repeated phones")
    path = np.empty(len(x), dtype=int)
    for t in range(len(x) - 1, -1, -1):
        path[t] = s
        s -= int(trace[t, s])
    intervals = []
    for i in range(len(tokens)):
        frames = np.flatnonzero(path == 2 * i + 1)
        if not len(frames):
            raise ValueError("CTC path omitted a transcript token")
        intervals.append((int(frames[0]), int(frames[-1] + 1)))
    return intervals
