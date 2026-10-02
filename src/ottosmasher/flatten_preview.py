"""Read existing measurements for a frozen selection; never invoke a model."""
from .selection_ops import resolve
from .sample_acoustics import cached_asset
from .flatten_pitch import phone_ranges, regions, target_note
from .sample_flatten import validate_interior


def preview(db, selection, mode='all', target=None, inner=None, transition=(.05, .05), pitch_strategy='region', boundary_side='left', backend=None, material_id=None):
    selected, asset = resolve(db, selection)
    duration = selected.end - selected.start
    intervals, manual = None, False
    if mode in ('vowels', 'from_first_vowel'):
        intervals, manual = phone_ranges(db, asset, backend, material_id)
    if mode == 'interior':
        inner, transition = validate_interior(duration, inner, transition)
    frames = cached_asset(asset)['frames']
    if frames is None:
        from .flatten_pitch import sample_measurement
        cached = sample_measurement(db, asset, material_id, backend)
        if cached:
            record, offset = cached
            raw = record['frames']
            indices = [i for i,t in enumerate(raw['times']) if offset <= t < offset+duration]
            frames = {k:[v[i] for i in indices] for k,v in raw.items()}
            frames['times'] = [t-offset for t in frames['times']]
    spans = regions(mode, duration, intervals, frames, manual, inner)
    note, reference = (None, None)
    if frames or target is not None or pitch_strategy == 'manual':
        note, reference = target_note(frames, spans, target, pitch_strategy, boundary_side)
    return {'frames': frames, 'intervals': spans, 'note': note, 'reference': reference,
            'status': 'ready' if note else 'pending', 'role': asset['role']}
