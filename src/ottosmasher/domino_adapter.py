"""pydomino inference through Otto's shared device policy, upstream decoding unchanged."""

from .inference_runtime import onnx_session


class Aligner:
    def __init__(self, path):
        import otto_domino_decoder

        self.decode = otto_domino_decoder.decode
        self.session = onnx_session(path)

    def align(self, waveform, phonemes, min_aligned_timeframe=3):
        import numpy as np

        waveform = np.asarray(waveform, dtype=np.float32)
        transitions, blanks = self.session.run(
            ["transition_logprobs", "blank_logprobs"], {"input_waveform": waveform[None]}
        )
        return self.decode(transitions, blanks, phonemes, len(waveform), min_aligned_timeframe)

    def release(self):
        self.session = None
