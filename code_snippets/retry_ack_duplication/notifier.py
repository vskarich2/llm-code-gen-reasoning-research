_sent = []


def send_confirmation(job_id, result):
    _sent.append({"job_id": job_id, "result": result})


def get_sent():
    return list(_sent)


def clear_sent():
    _sent.clear()
