from processor import process_batch
from reporter import build_report, verify_consistency
from metrics import reset


def ingest(records):
    reset()
    results = process_batch(records)
    report = build_report()
    consistent = verify_consistency()
    return {"results": results, "report": report, "consistent": consistent}
