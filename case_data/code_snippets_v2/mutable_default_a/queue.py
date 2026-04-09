


def enqueue(task, queue=[]):
    queue.append(task)
    return queue


def make_task(name, priority=1):
    return {"name": name, "priority": priority}


def process(queue):
    results = []
    for task in queue:
        results.append(f"done:{task['name']}")
    return results
