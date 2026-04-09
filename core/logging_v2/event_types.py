"""Event type registry and payload schemas. Closed vocabulary.

Every EventType has exactly one EventTypeSpec and one payload schema.
No free-form payloads allowed.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.logging_v2.enums import Emitter, EventType


@dataclass(frozen=True)
class EventTypeSpec:
    event_type: EventType
    emitter: Emitter
    requires_case: bool
    requires_call_id: bool


EVENT_TYPE_SPECS: dict[EventType, EventTypeSpec] = {
    EventType.RUN_STARTED: EventTypeSpec(EventType.RUN_STARTED, Emitter.RUNNER, False, False),
    EventType.RUN_COMPLETED: EventTypeSpec(EventType.RUN_COMPLETED, Emitter.RUNNER, False, False),
    EventType.RUN_FAILED: EventTypeSpec(EventType.RUN_FAILED, Emitter.RUNNER, False, False),
    EventType.CASE_STARTED: EventTypeSpec(EventType.CASE_STARTED, Emitter.RUNNER, True, False),
    EventType.CASE_COMPLETED: EventTypeSpec(EventType.CASE_COMPLETED, Emitter.RUNNER, True, False),
    EventType.CASE_FAILED: EventTypeSpec(EventType.CASE_FAILED, Emitter.RUNNER, True, False),
    EventType.ENGINE_GRAPH_STARTED: EventTypeSpec(EventType.ENGINE_GRAPH_STARTED, Emitter.ENGINE, True, False),
    EventType.ENGINE_GRAPH_COMPLETED: EventTypeSpec(EventType.ENGINE_GRAPH_COMPLETED, Emitter.ENGINE, True, False),
    EventType.ENGINE_GRAPH_FAILED: EventTypeSpec(EventType.ENGINE_GRAPH_FAILED, Emitter.ENGINE, True, False),
    EventType.ENGINE_NODE_STARTED: EventTypeSpec(EventType.ENGINE_NODE_STARTED, Emitter.ENGINE, True, False),
    EventType.ENGINE_NODE_COMPLETED: EventTypeSpec(EventType.ENGINE_NODE_COMPLETED, Emitter.ENGINE, True, False),
    EventType.ENGINE_NODE_FAILED: EventTypeSpec(EventType.ENGINE_NODE_FAILED, Emitter.ENGINE, True, False),
    EventType.ENGINE_NODE_SKIPPED: EventTypeSpec(EventType.ENGINE_NODE_SKIPPED, Emitter.ENGINE, True, False),
    EventType.ENGINE_MERGE_COMPLETED: EventTypeSpec(EventType.ENGINE_MERGE_COMPLETED, Emitter.ENGINE, True, False),
    EventType.CONTROLLER_ATTEMPT_STARTED: EventTypeSpec(EventType.CONTROLLER_ATTEMPT_STARTED, Emitter.CONTROLLER, True, False),
    EventType.CONTROLLER_ATTEMPT_COMPLETED: EventTypeSpec(EventType.CONTROLLER_ATTEMPT_COMPLETED, Emitter.CONTROLLER, True, False),
    EventType.CONTROLLER_RETRY_DECIDED: EventTypeSpec(EventType.CONTROLLER_RETRY_DECIDED, Emitter.CONTROLLER, True, False),
    EventType.CONTROLLER_CRITIQUE_GENERATED: EventTypeSpec(EventType.CONTROLLER_CRITIQUE_GENERATED, Emitter.CONTROLLER, True, False),
    EventType.CONTROLLER_RESULT_SELECTED: EventTypeSpec(EventType.CONTROLLER_RESULT_SELECTED, Emitter.CONTROLLER, True, False),
    EventType.LLM_CALL_STARTED: EventTypeSpec(EventType.LLM_CALL_STARTED, Emitter.NODE, True, True),
    EventType.LLM_CALL_COMPLETED: EventTypeSpec(EventType.LLM_CALL_COMPLETED, Emitter.NODE, True, True),
    EventType.LLM_CALL_FAILED: EventTypeSpec(EventType.LLM_CALL_FAILED, Emitter.NODE, True, True),
    EventType.NODE_RESULT_PRODUCED: EventTypeSpec(EventType.NODE_RESULT_PRODUCED, Emitter.NODE, True, False),
}


PAYLOAD_SCHEMAS: dict[EventType, dict[str, type]] = {
    EventType.RUN_STARTED:                  {"experiment_name": str, "seed": int},
    EventType.RUN_COMPLETED:                {"total_cases": int, "total_pass": int},
    EventType.RUN_FAILED:                   {"error": str},
    EventType.CASE_STARTED:                 {},
    EventType.CASE_COMPLETED:               {"passed": bool, "outcome_class": str},
    EventType.CASE_FAILED:                  {"error": str},
    EventType.ENGINE_GRAPH_STARTED:         {"node_count": int},
    EventType.ENGINE_GRAPH_COMPLETED:       {"completed_nodes": int, "failed_nodes": int, "skipped_nodes": int},
    EventType.ENGINE_GRAPH_FAILED:          {"error": str},
    EventType.ENGINE_NODE_STARTED:          {},
    EventType.ENGINE_NODE_COMPLETED:        {"output_keys": list, "elapsed_ms": int},
    EventType.ENGINE_NODE_FAILED:           {"error": str, "elapsed_ms": int},
    EventType.ENGINE_NODE_SKIPPED:          {"reason": str},
    EventType.ENGINE_MERGE_COMPLETED:       {"keys_merged": int},
    EventType.CONTROLLER_ATTEMPT_STARTED:   {},
    EventType.CONTROLLER_ATTEMPT_COMPLETED: {"passed": bool},
    EventType.CONTROLLER_RETRY_DECIDED:     {"continue_retry": bool, "reason": str},
    EventType.CONTROLLER_CRITIQUE_GENERATED:{"critique_length": int, "critique_empty": bool},
    EventType.CONTROLLER_RESULT_SELECTED:   {"best_attempt_idx": int, "total_attempts": int},
    EventType.LLM_CALL_STARTED:             {"model": str},
    EventType.LLM_CALL_COMPLETED:           {"model": str, "latency_ms": int, "prompt_length": int, "response_length": int},
    EventType.LLM_CALL_FAILED:              {"model": str, "error": str},
    EventType.NODE_RESULT_PRODUCED:         {"output_keys": list},
}
