from graph_runner.stage_spec import StageSpec
from graph_runner.executors.build_prompt import build_prompt_executor
from graph_runner.executors.generate import generate_executor
from graph_runner.executors.reconstruct import parse_executor
from graph_runner.executors.exec_eval import exec_eval_executor
from graph_runner.transitions import has_prompt, has_raw_response, can_execute

"""
This file defines a minimal, declarative execution pipeline for a graph-based runner.
It does NOT execute anything itself. Instead, it specifies a sequence of stages
(StageSpec objects) that a separate GraphRunner (or similar engine) will interpret
and execute.

At a high level, this function encodes the core dataflow of the system:

    case → build_prompt → prompt
         → generate     → raw_response
         → parse        → parsed_response
         → exec_eval    → exec_result

Each step in this pipeline is represented as a StageSpec, which describes:
    - what inputs it requires from the shared execution state
    - what outputs it will produce
    - what function (executor) performs the computation
    - under what condition (guard) it is allowed to run

--------------------------------------------------------------------------------
CORE CONCEPT: DECLARATIVE PIPELINE (NOT EXECUTION)

The return value of build_minimal_graph() is a list of StageSpec objects.
This list is a *specification* of a pipeline, not the pipeline execution itself.

A separate runtime (e.g., GraphRunner) is expected to:
    1. Maintain an ExecutionState (shared memory of artifacts)
    2. Iterate through these StageSpecs
    3. For each stage:
        - Check the guard(state)
        - If True:
            - Pull required inputs from state using input_keys
            - Call the executor
            - Write outputs back into state under output_keys

So this file is purely about "what should happen", not "how to run it".

--------------------------------------------------------------------------------
STAGE BREAKDOWN

1. build_prompt
    Input:
        - "case" (a loaded test case with code + task description)
    Output:
        - "prompt" (LLM prompt string)
    Executor:
        - build_prompt_executor
    Guard:
        - state.has("case")

    Meaning:
        If a case exists in state, construct a prompt from it.

--------------------------------------------------------------------------------

2. generate
    Input:
        - "prompt"
    Output:
        - "raw_response" (LLM output, likely unstructured text)
    Executor:
        - generate_executor
    Guard:
        - has_prompt (typically checks state.has("prompt"))

    Meaning:
        If a prompt exists, call the model to generate a response.

--------------------------------------------------------------------------------

3. parse
    Input:
        - "raw_response"
    Output:
        - "parsed_response" (structured output, e.g. JSON with code + reasoning)
    Executor:
        - parse_executor
    Guard:
        - has_raw_response

    Meaning:
        If a raw model response exists, parse it into structured form.

--------------------------------------------------------------------------------

4. exec_eval
    Input:
        - (none explicitly declared)
    Output:
        - "exec_result" (result of running tests on generated code)
    Executor:
        - exec_eval_executor
    Guard:
        - can_execute (likely checks that required artifacts exist, e.g. parsed_response + case)

    Meaning:
        If the system is in a state where execution is possible, run the generated code
        against test cases and produce an evaluation result.

NOTE:
    Although input_keys is empty here, this stage implicitly depends on prior artifacts
    (e.g., parsed_response, case). That dependency is hidden inside the guard or executor,
    which is a potential design weakness.

--------------------------------------------------------------------------------
IMPORTANT DESIGN CHARACTERISTICS

1. LINEAR PIPELINE DISGUISED AS GRAPH
    Although named "graph", this is currently just a list.
    Execution is effectively sequential, not a true DAG:
        - no branching
        - no parallelism
        - no explicit dependency graph

2. GUARD-DRIVEN CONTROL FLOW
    Execution is controlled by guard functions rather than dependency resolution.
    Each stage decides if it can run based on state inspection.

    This means:
        - correctness depends on guards being accurate
        - dependencies are not enforced structurally

3. STRING-BASED DATA CONTRACTS
    Inputs and outputs are identified by string keys:
        "prompt", "raw_response", "parsed_response", etc.

    There is no enforcement that:
        - executors actually produce declared outputs
        - required inputs exist beyond guard checks

    This introduces potential for silent mismatches.

4. SHARED MUTABLE STATE
    All stages communicate through a shared ExecutionState:
        - stages read from it (via input_keys)
        - stages write to it (via output_keys)

    This creates implicit coupling between stages:
        - naming must be consistent
        - ordering matters
        - overwrites are possible

5. SEPARATION OF CONCERNS (GOOD PART)
    The design cleanly separates:
        - specification (StageSpec)
        - execution logic (executor functions)
        - control logic (guards)

    This is the main strength of the design.

--------------------------------------------------------------------------------
MENTAL MODEL

Think of this file as defining:

    "A sequence of transformations over a shared state,
     where each transformation is conditionally executed."

Or more concretely:

    ExecutionState = memory
    StageSpec      = transformation rule
    Executor       = implementation of transformation
    Guard          = condition for applying transformation

--------------------------------------------------------------------------------
LIMITATIONS / RISKS

- Not a true dependency-driven system (guards instead of graph edges)
- No type safety or schema validation for inputs/outputs
- Hidden dependencies (especially in exec_eval)
- No versioning or history of intermediate artifacts
- Susceptible to silent failures if keys mismatch or guards are incorrect

--------------------------------------------------------------------------------
SUMMARY

build_minimal_graph() defines the canonical "single-pass" pipeline:
    prompt construction → model generation → parsing → execution evaluation

It is a declarative description of the system’s core loop, intended to be
interpreted by a runtime that manages state and executes each stage in order.

This is a solid starting abstraction, but not yet a fully robust graph execution
system. It behaves more like a guarded linear pipeline than a true DAG.
"""

def build_minimal_graph():
    return [
        StageSpec(
            name="build_prompt",
            input_keys=["case"],
            output_keys=["prompt"],
            executor=build_prompt_executor,
            guard=lambda state: state.has("case"),
        ),
        StageSpec(
            name="generate",
            input_keys=["prompt"],
            output_keys=["raw_response"],
            executor=generate_executor,
            guard=has_prompt,
        ),
        StageSpec(
            name="parse",
            input_keys=["raw_response"],
            output_keys=["parsed_response"],
            executor=parse_executor,
            guard=has_raw_response,
        ),
        StageSpec(
            name="exec_eval",
            input_keys=[],
            output_keys=["exec_result"],
            executor=exec_eval_executor,
            guard=can_execute,
        ),
    ]
