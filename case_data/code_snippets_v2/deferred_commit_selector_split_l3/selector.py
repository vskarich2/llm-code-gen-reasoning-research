def choose_best(candidates):
    # Subtle tie-breaking ambiguity
    winner = max(candidates, key=lambda c: (c["raw_score"], -c["priority"]))
    return winner
