import json
from collections import Counter, defaultdict

path = "runs/wal.jsonl"

attempts = []
successes = set()
failure_types = Counter()
attempt_success = defaultdict(list)

with open(path) as f:
    for line in f:
        event = json.loads(line)

        if event["type"] == "attempt":
            attempts.append(event)

            attempt_num = event["attempt"]
            success = False

            if "evaluation" in event:
                ev = event["evaluation"]
                success = ev.get("task_correct") and not ev.get("suspicious")

            attempt_success[attempt_num].append(success)

            if "error" in event:
                err = event["error"]

                if "Scope violation" in err:
                    failure_types["scope_violation"] += 1
                elif "Diff too large" in err:
                    failure_types["diff_too_large"] += 1
                elif "Evaluator rejected" in err:
                    failure_types["evaluator_rejected"] += 1
                else:
                    failure_types["other"] += 1

        elif event["type"] == "success":
            successes.add(event["task"])

total = len(attempts)
success_rate = len(successes) / max(1, total)

print(f"Total attempts: {total}")
print(f"Success rate: {success_rate:.2%}")

print("\nFailure breakdown:")
for k, v in failure_types.items():
    print(f"{k}: {v}")

print("\nSuccess by attempt:")
for k, vals in sorted(attempt_success.items()):
    rate = sum(vals) / len(vals)
    print(f"Attempt {k}: {rate:.2%}")