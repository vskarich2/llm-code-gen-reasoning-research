def process(task):
    return {"name": task["name"], "status": "done"}

def batch_process(tasks):

    return [process(t) for t in tasks]
