def choose_best(candidates):
    winner = max(candidates, key=lambda c: (c["raw_score"], -c["priority"]))
    return winner
