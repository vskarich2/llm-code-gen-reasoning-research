"""Worker module for processing tasks."""


def process(task):
    """Process a single task and return a result."""
    return {"name": task["name"], "status": "done"}


def batch_process(tasks):
    """Process a list of tasks."""
    return [process(t) for t in tasks]
