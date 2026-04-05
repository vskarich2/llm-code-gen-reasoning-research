def normalize(candidates):
    normalized = []
    for c in candidates:
        score = c["raw_score"] + len(c["payload"]) * 4 + c["priority"] * 3
        normalized.append({
            "artifact_id": f"final::{c['plan_id']}",
            "payload": c["payload"].upper(),
            "normalized_score": score,
            "meta": c["meta"]
        })
    # reorder based on new scoring
    return sorted(normalized, key=lambda x: x["normalized_score"], reverse=True)
