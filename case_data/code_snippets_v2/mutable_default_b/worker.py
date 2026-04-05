"""Worker that processes task batches."""


def process_batch(tasks, seen=set()):
    """Process a batch of tasks, skipping already-seen ones.

    Invariant: each call to process_batch with a fresh batch must
    process ALL tasks in that batch, regardless of prior calls.
    """
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
