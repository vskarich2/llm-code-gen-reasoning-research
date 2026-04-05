def generate_candidates():
    # Selection: max by (raw_score, -priority)
    #   a: (91, -1) → wins (lowest priority = highest -priority)
    #   b: (91, -2)
    #   c: (80, -3)
    #
    # Normalization: score + len(payload)*4 + priority*3
    #   a: 91 + 2*4 + 1*3 = 102
    #   b: 91 + 21*4 + 2*3 = 181
    #   c: 80 + 5*4 + 3*3 = 109
    # Normalized order: b(181), c(109), a(102)
    #
    # Selected=a, top-normalized=b → BUG triggered
    return [
        {"source_id": "a", "raw_score": 91, "payload": "ax", "priority": 1},
        {"source_id": "b", "raw_score": 91, "payload": "beta-extended-payload", "priority": 2},
        {"source_id": "c", "raw_score": 80, "payload": "gamma", "priority": 3},
    ]
