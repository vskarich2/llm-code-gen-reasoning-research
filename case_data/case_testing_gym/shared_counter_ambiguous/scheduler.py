from tracker import reset, get_count
from processor import process_batch


def run_cycle(batches):
    """Process multiple batches in sequence.

    Each cycle should accumulate counts across batches
    (reset happens only between cycles, not between batches).
    """
    # BUG: resets counter BETWEEN batches instead of only at cycle start.
    # This loses accumulated counts from previous batches within the same cycle.
    all_results = []
    for batch in batches:
        reset()  # BUG: should only reset once at start, not per batch
        results = process_batch(batch)
        all_results.extend(results)
    return all_results


def get_cycle_total():
    return get_count()
