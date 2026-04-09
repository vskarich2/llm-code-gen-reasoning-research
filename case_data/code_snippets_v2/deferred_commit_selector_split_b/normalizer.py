def normalize(candidates):
    finalized = [
        {
            'origin_ref': c['origin_ref'],
            'final_score': c['raw_score'] - c['penalty']
        }
        for c in candidates
    ]

    return sorted(finalized, key=lambda c: -c['final_score'])
