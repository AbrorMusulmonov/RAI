"""Persist the completed follow-up reading; not an automatic text classifier."""
from src.audit.final50 import AUDIT, queues, save
from src.utils.io import read_json


def persist():
    path = AUDIT / 'quality_supplemental.json'
    if path.exists():
        raise RuntimeError('Completed inspection already frozen; do not repeat it')
    q = queues()
    samples = read_json(AUDIT / 'quality_samples.json')
    entries = []
    # Indices are checked against the immutable ID anchors before serialization.
    assert q['STA-3'][8]['Candidate ID'] == 'STA3-C-9BDCE4714697'
    assert q['STA-3'][72]['Candidate ID'] == 'STA3-C-0D2822A2DF4E'
    for c in ('STA-1', 'STA-3'):
        known = {r['Candidate ID'] for rows in samples[c].values() for r in rows}
        for i, r in enumerate(q[c]):
            if r['Candidate ID'] in known:
                continue
            tag = ('L' if i < 3 else 'A') if c == 'STA-1' else 'L'
            if c == 'STA-3':
                if i in (8, 9, 15, 17, 18, 21, 23, 24, 25, 26, 27, 39): tag = 'I'
                if i in (28, 37): tag = 'W'
                if i in (6, 13, 29, 36, 59, 64): tag = 'A'
            entries.append({'category': c, 'candidate_id': r['Candidate ID'],
                'sample_tier': r['Retrieval Tier'], 'audit_rating': tag,
                'meaning': {'L': 'Likely Relevant', 'A': 'Ambiguous / potentially useful reported abuse',
                            'I': 'Likely Irrelevant', 'W': 'Wrong Category'}[tag],
                'original_example': r['Example'], 'human_review_status_unchanged': 'PENDING'})
    save('quality_supplemental.json', entries)


if __name__ == '__main__':
    persist()
