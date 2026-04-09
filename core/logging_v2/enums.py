"""All enums for the logging v2 system. Single source of truth.

No raw strings allowed in control flow outside this module.
Only .value is permitted at JSON serialization boundaries.
"""

from enum import Enum


class EventType(str, Enum):
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    CASE_STARTED = "case.started"
    CASE_COMPLETED = "case.completed"
    CASE_FAILED = "case.failed"
    ENGINE_GRAPH_STARTED = "engine.graph.started"
    ENGINE_GRAPH_COMPLETED = "engine.graph.completed"
    ENGINE_GRAPH_FAILED = "engine.graph.failed"
    ENGINE_NODE_STARTED = "engine.node.started"
    ENGINE_NODE_COMPLETED = "engine.node.completed"
    ENGINE_NODE_FAILED = "engine.node.failed"
    ENGINE_NODE_SKIPPED = "engine.node.skipped"
    ENGINE_MERGE_COMPLETED = "engine.merge.completed"
    CONTROLLER_ATTEMPT_STARTED = "controller.attempt.started"
    CONTROLLER_ATTEMPT_COMPLETED = "controller.attempt.completed"
    CONTROLLER_RETRY_DECIDED = "controller.retry.decided"
    CONTROLLER_CRITIQUE_GENERATED = "controller.critique.generated"
    CONTROLLER_RESULT_SELECTED = "controller.result.selected"
    LLM_CALL_STARTED = "llm.call.started"
    LLM_CALL_COMPLETED = "llm.call.completed"
    LLM_CALL_FAILED = "llm.call.failed"
    NODE_RESULT_PRODUCED = "node.result.produced"


class Emitter(str, Enum):
    ENGINE = "engine"
    CONTROLLER = "controller"
    RUNNER = "runner"
    NODE = "node"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CRASHED = "crashed"


class CallStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


class Axis(str, Enum):
    CONDITION = "condition"
    MODEL = "model"
    CASE = "case"
    TRIAL = "trial"
    PATH = "path"
    NODE = "node"
    CALL = "call"


class ArtifactGroup(str, Enum):
    CALLS = "calls"
    EXECUTION = "execution"
    DIFFS = "diffs"


class CallPhase(str, Enum):
    GENERATION = "generation"
    CLASSIFICATION = "classification"
    ORACLE = "oracle"
    CRITIQUE = "critique"


class RedisWriteMode(str, Enum):
    SYNC = "sync"
    ASYNC_BUFFERED = "async_buffered"


class RedisFailureMode(str, Enum):
    LOG_AND_CONTINUE = "log_and_continue"
    RAISE = "raise"


class ViewName(str, Enum):
    SUMMARY = "summary"
    TIMELINE = "timeline"
    FAILURES = "failures"
    LLM_CALLS = "llm_calls"
    TRIAL_TABLE = "trial_table"
    INDEX = "index"
    CASE_DETAIL = "case_detail"


class StatName(str, Enum):
    PASS_RATE = "pass_rate"
    LEG_RATE = "leg_rate"
    ATTEMPT_COUNT = "attempt_count"
    PARSE_SUCCESS_RATE = "parse_success_rate"
    MEAN_LATENCY_MS = "mean_latency_ms"
