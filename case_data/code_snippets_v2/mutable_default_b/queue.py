"""Task queue module."""


def create_task(name, priority=1):
    """Create a task dict."""
    return {"name": name, "priority": priority, "status": "pending"}


def enqueue(task, queue=None):
    """Add task to queue. Returns the queue."""
    if queue is None:
        queue = []
    queue.append(task)
    return queue


def dequeue(queue):
    """Remove and return the first task, or None."""
    if queue:
        return queue.pop(0)
    return None
