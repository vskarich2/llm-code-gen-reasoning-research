from selector import choose_best
from snapshot_store import snapshot
from normalizer import normalize
from committer import commit


def run(candidates):
    selection = choose_best(candidates)
    snaps = snapshot(candidates)
    finalized = normalize(snaps)
    result = commit(finalized, selection)
    return selection, result
