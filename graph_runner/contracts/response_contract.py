"""Strict contract for LLM response validation.

Enforces that parsed model responses contain required fields with correct types.
No silent coercion. No defaults. No fallbacks. Violations raise ResponseContractError.
"""


class ResponseContractError(Exception):
    """Raised when a model response violates the response contract."""


class ResponseContract:
    REQUIRED_KEYS = ["reasoning", "code"]

    @staticmethod
    def validate(data: object) -> dict:
        if not isinstance(data, dict):
            raise ResponseContractError("Response must be a dict")

        missing = [k for k in ResponseContract.REQUIRED_KEYS if k not in data]
        if missing:
            raise ResponseContractError(f"Missing keys: {missing}")

        if not isinstance(data["reasoning"], str):
            raise ResponseContractError("reasoning must be a string")

        if not isinstance(data["code"], str):
            raise ResponseContractError("code must be a string")

        return data
