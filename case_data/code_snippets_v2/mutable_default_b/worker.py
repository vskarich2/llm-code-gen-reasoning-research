
def process_batch(tasks, seen=set()):
    results = []
    for task in tasks:
        task_id = task["name"]
        if task_id in seen:
            continue
        seen.add(task_id)
        results.append({"name": task["name"], "result": "processed"})
    return results

def summarize(results):
    return f"{len(results)} tasks processed"
