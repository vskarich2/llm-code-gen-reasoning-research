"""Worker that processes task batches."""

from queue import create_task


def process_batch(tasks, seen=set()):
    """Process a batch of tasks, skipping already-seen ones.

    Invariant: each call to process_batch with a fresh batch must
    process ALL tasks in that batch, regardless of prior calls.
    """
    # BUG: seen set persists across calls — valid tasks skipped as duplicates
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
