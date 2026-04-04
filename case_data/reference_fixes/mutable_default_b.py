"""Worker that processes task batches."""

from queue import create_task


def process_batch(tasks, seen=None):
    """Process a batch of tasks, skipping already-seen ones.

    Invariant: each call to process_batch with a fresh batch must
    process ALL tasks in that batch, regardless of prior calls.
    """
    if seen is None:
        seen = set()
    results = []
    for task in tasks:
        task_id = task["name"]
        if task_id in seen:
            continue
        seen.add(task_id)
        results.append({"name": task["name"], "result": "processed"})
    return results


def summarize(results):
    """Summarize processing results (distractor)."""
    return f"{len(results)} tasks processed"
