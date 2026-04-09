def snapshot(candidates):
    return [
        {
            'snapshot_id': i,
            'origin_ref': f"cand::{c['id']}",
            'raw_score': c['score'],
            'penalty': c['penalty']
        }
        for i, c in enumerate(candidates)
    ]
