from writer import write_record, write_with_retry, safe_write
from store import get_seq, clear, get


def ingest_batch(records):
    clear()
    results = []
    for r in records:
        seq = write_with_retry(r["key"], r["value"])
        results.append({"key": r["key"], "seq": seq})
    return {"results": results, "final_seq": get_seq()}


def ingest_safe(records):
    clear()
    results = []
    for r in records:
        seq = safe_write(r["key"], r["value"])
        results.append({"key": r["key"], "seq": seq})
    return {"results": results, "final_seq": get_seq()}
