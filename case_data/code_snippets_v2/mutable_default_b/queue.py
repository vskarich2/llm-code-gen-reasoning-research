

def create_task(name, priority=1):
    return {"name": name, "priority": priority, "status": "pending"}


def enqueue(task, queue=None):
    if queue is None:
        queue = []
    queue.append(task)
    return queue


def dequeue(queue):
    if queue:
        return queue.pop(0)
    return None
