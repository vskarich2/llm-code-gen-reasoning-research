


def create_task(name, priority=1):
    return {"name": name, "priority": priority}


def enqueue_all(tasks, queue=None):
    if queue is None:
        queue = []
    queue.extend(tasks)
    return queue


def drain(queue):
    items = list(queue)
    queue.clear()
    return items
