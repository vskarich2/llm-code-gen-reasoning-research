

from worker import process, batch_process

_shared_log = []


def with_history(func, history=_shared_log):
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        history.append({"func": func.__name__, "args_count": len(args)})
        return result

    wrapper.get_history = lambda: list(history)
    wrapper.clear_history = lambda: history.clear()
    return wrapper

@with_history
def schedule_one(task):
    return process(task)

@with_history
def schedule_batch(tasks):
    return batch_process(tasks)


def get_all_stats():
    return {
        "one_calls": len(schedule_one.get_history()),
        "batch_calls": len(schedule_batch.get_history()),
    }
