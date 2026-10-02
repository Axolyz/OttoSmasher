"""Shared, inference-free flatten range and target policy for preview and rendering."""
import numpy as np

VERSION = 'flatten-v3'


def regions(mode, duration, intervals, frames, preserve_boundaries=False, inner=None):
    if mode == 'all':
        return [[0, duration]]
    if mode == 'interior':
        return [list(inner)]
    if mode not in {'vowels', 'from_first_vowel'} or not intervals:
        raise ValueError('当前资产选区没有可用元音／拨音范围，请先准备匹配的 FA')
    from .vowel_bounds import bounds
    result = sorted([list(x) for x in intervals if x[1] > x[0]])
    if not result:
        raise ValueError('选区中没有元音／拨音')
    if not preserve_boundaries and frames:
        result = [bounds(a, b, frames['times'], frames['energy']) for a, b in result]
    return [[result[0][0], duration]] if mode == 'from_first_vowel' else result


def target_note(frames, intervals, target=None, strategy='region', side='left'):
    from .sample_flatten import nearest_note
    from .pitch_values import note
    if strategy not in {'region', 'boundary', 'manual'} or side not in {'left', 'right'}:
        raise ValueError('未知自动定音方式或交界参考侧')
    if strategy == 'manual' and target is None:
        raise ValueError('请填写目标音高')
    if target is not None:
        return note(target), None
    t = np.asarray(frames['times'])
    reference = None
    if strategy == 'boundary':
        a, b = (intervals[0][0], intervals[-1][1])
        reference = [a, min(b, a + .1)] if side == 'left' else [max(a, b - .1), b]
        mask = (t >= reference[0]) & (t < reference[1])
    else:
        mask = np.array([any(a <= x < b for a, b in intervals) for x in t])
    valid = mask & np.asarray(frames['voiced'], dtype=bool) & (np.asarray(frames['confidence']) >= .5)
    try:
        result = nearest_note(np.asarray(frames['f0_hz']), np.asarray(frames['confidence']), valid)
    except ValueError:
        if strategy == 'boundary':
            raise ValueError('所选交界侧 100 ms 内可靠 F0 不足；请换侧、改用段内自动或手动指定') from None
        raise
    return result, reference


def phone_ranges(db, descriptor, backend=None, material_id=None):
    from .analysis_scope import covering
    from .ui_catalog import settings
    from .rhythm_units import normalize_phone
    import json
    row = covering(db, descriptor, backend or settings(db)['phone_model_order'][0])
    if not row:
        cached = sample_measurement(db, descriptor, material_id, backend)
        if cached:
            record, start = cached
            duration = descriptor['end'] - descriptor['start']
            intervals = [[max(0,p['start']-start),min(duration,p['end']-start)]
                         for p in record['analysis']['phones']
                         if normalize_phone(p['label']) in {'a','i','u','e','o','I','U','N'}
                         and p['end']>start and p['start']<start+duration]
            if intervals:
                analysis = record['analysis']
                return intervals, bool(analysis.get('manual_timing') or analysis.get('human') or analysis.get('manual'))
        raise ValueError('当前资产选区没有覆盖全区的 FA，请先分析或使用整段／内部拉平')
    run = json.loads(row['payload'])
    measured = json.loads(row['descriptor'])
    offset = measured['start'] - descriptor['start']
    duration = descriptor['end'] - descriptor['start']
    intervals = [[max(0, p['start'] + offset), min(duration, p['end'] + offset)]
                 for p in run['phones']
                 if normalize_phone(p['label']) in {'a', 'i', 'u', 'e', 'o', 'I', 'U', 'N'}
                 and p['end'] + offset > 0 and p['start'] + offset < duration]
    if not intervals:
        raise ValueError('选区中没有元音／拨音')
    return intervals, bool(row['human'])


def sample_measurement(db, descriptor, material_id, backend=None):
    """Reuse a legacy sample projection only with proven sound and clock identity."""
    if not material_id:
        return None
    from .sample_analysis import ready
    from .asset_timeline import map_time
    try:
        record = ready(db, material_id, backend, materialize=False)
        measured = record['asset']
        if any(measured.get(k) != descriptor.get(k) for k in ('path','sha256','audio_stream')):
            return None
        if not measured['start'] <= descriptor['start'] < descriptor['end'] <= measured['end'] + 1e-8:
            return None
        offset = descriptor['start'] - measured['start']
        if any(abs(map_time(measured['root_knots'], offset+x)-y)>1e-7 for x,y in descriptor['root_knots']):
            return None
        return record, offset
    except (ValueError, KeyError):
        return None
