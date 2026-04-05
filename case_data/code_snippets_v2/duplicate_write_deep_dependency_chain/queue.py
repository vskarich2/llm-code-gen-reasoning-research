class Queue:
    def __init__(self):
        self.jobs = []

    def enqueue(self, request_id, payload):
        self.jobs.append((request_id, payload))

    def run(self, service):
        while self.jobs:
            request_id, payload = self.jobs.pop(0)
            service.process(request_id, payload)
