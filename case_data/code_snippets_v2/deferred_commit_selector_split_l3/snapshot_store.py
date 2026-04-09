def snapshot(candidates):
    snap = []
    for c in candidates:
        snap.append({
            "plan_id": f"snap::{c['source_id']}",
            "payload": c["payload"],
            "priority": c["priority"],
            "raw_score": c["raw_score"],
            "meta": {"src": c["source_id"]}
        })
    return snap
