"""Task queue with mutable default argument."""


def enqueue(task, queue=None):
    """Add a task to the queue and return the queue.

    Invariant: each call with a single task (no explicit queue)
    must return a list containing only that task.
    """
    if queue is None:
        queue = []
    queue.append(task)
    return queue


def make_task(name, priority=1):
    """Create a task dict."""
    return {"name": name, "priority": priority}


def process(queue):
    """Process all tasks in the queue and return results."""
    results = []
    for task in queue:
        results.append(f"done:{task['name']}")
    return results
