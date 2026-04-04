"""Scheduler with decorator that tracks call history."""

from worker import process, batch_process


def with_history(func):
    """Decorator that records call history for a function.

    Invariant: each decorated function must have its OWN
    independent history list.
    """
    history = []

    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        history.append({"func": func.__name__, "args_count": len(args)})
        return result

    wrapper.get_history = lambda: list(history)
    wrapper.clear_history = lambda: history.clear()
    return wrapper


@with_history
def schedule_one(task):
    """Schedule and process a single task."""
    return process(task)


@with_history
def schedule_batch(tasks):
    """Schedule and process a batch of tasks."""
    return batch_process(tasks)


def get_all_stats():
    """Get combined stats (distractor)."""
    return {
        "one_calls": len(schedule_one.get_history()),
        "batch_calls": len(schedule_batch.get_history()),
    }
