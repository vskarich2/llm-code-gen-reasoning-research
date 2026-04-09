def _format_log(collected_event):
    
    return f"[{collected_event['severity']}] {collected_event['ts']} {collected_event['source']}: {collected_event['msg']}"

def format_logs_node(collected_events):
    return {
        "collected_events": collected_events,
        "logs": [_format_log(e) for e in collected_events],
    }
