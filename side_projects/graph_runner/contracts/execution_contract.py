from __future__ import annotations

from typing import Any, Dict


class ExecutionContractError(Exception):
    pass


class ExecutionContract:
    REQUIRED_KEYS = ["success", "error", "tests_run", "tests_passed"]

    @classmethod
    def validate(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(data, dict):
            raise ExecutionContractError("Execution result must be a dict")

        missing = [k for k in cls.REQUIRED_KEYS if k not in data]
        if missing:
            raise ExecutionContractError(f"Missing keys: {missing}")

        if not isinstance(data["success"], bool):
            raise ExecutionContractError("success must be a bool")

        if data["error"] is not None and not isinstance(data["error"], str):
            raise ExecutionContractError("error must be a string or None")

        if not isinstance(data["tests_run"], int) or data["tests_run"] < 0:
            raise ExecutionContractError("tests_run must be a non-negative int")

        if not isinstance(data["tests_passed"], int) or data["tests_passed"] < 0:
            raise ExecutionContractError("tests_passed must be a non-negative int")

        if data["tests_passed"] > data["tests_run"]:
            raise ExecutionContractError(
                f"tests_passed ({data['tests_passed']}) must be <= tests_run ({data['tests_run']})"
            )

        return data
