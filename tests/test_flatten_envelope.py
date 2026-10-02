import numpy as np
import pytest
from ottosmasher.sample_flatten import pitch_envelope, validate_interior, nearest_note
from ottosmasher.pitch_values import midi, note
from ottosmasher.rhythm_units import normalize_phone


def test_interior_has_untouched_edges_smooth_midi_plateau():
    inner, transition = validate_interior(1, [.2, .8], [.05, .05])
    times = np.arange(1001) / 1000
    weight = pitch_envelope(times, inner, transition)
    assert np.all(weight[times < .2] == 0)
    assert np.all(weight[times >= .8] == 0)
    assert np.allclose(weight[(times >= .25) & (times <= .75)], 1)
    assert weight[225] == pytest.approx(.5)
    assert weight[201] < .002
    with pytest.raises(ValueError, match='30 ms'): validate_interior(1, [.2, .31], [.05, .05])
    with pytest.raises(ValueError): validate_interior(1, [.2, 1.1], [.05, .05])


def test_explicit_notes_and_normalized_n_are_distinct():
    assert midi('A4') == 69
    assert midi('F#5') == midi('G♭5') == 78
    assert note(69)['hz'] == 440
    assert normalize_phone('N') == 'N'
    assert normalize_phone('n') == 'n'
    with pytest.raises(ValueError): midi(float('nan'))
    with pytest.raises(ValueError): midi(True)
