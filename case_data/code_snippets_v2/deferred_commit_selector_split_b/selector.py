def choose_best(candidates):
    winner = max(candidates, key=lambda c: c['score'])
    return {
        'selected_id': winner['id'],
        'selected_index': candidates.index(winner)
    }
