"""Task queue module."""


def create_task(name, priority=1):
    """Create a task dict."""
    return {"name": name, "priority": priority}


def enqueue_all(tasks, queue=None):
    """Enqueue multiple tasks. Returns the queue."""
    if queue is None:
        queue = []
    queue.extend(tasks)
    return queue


def drain(queue):
    """Remove and return all tasks from queue."""
    items = list(queue)
    queue.clear()
    return items
