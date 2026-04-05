def snapshot(candidates):
    # Snapshot preserves lineage, but not in the original representation.
    return [
        {
            'snapshot_id': i,
            'origin_ref': f"cand::{c['id']}",
            'raw_score': c['score'],
            'penalty': c['penalty']
        }
        for i, c in enumerate(candidates)
    ]
