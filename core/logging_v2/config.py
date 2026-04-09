"""Logging V2 configuration. Frozen dataclass. Validated at startup."""

from __future__ import annotations

from dataclasses import dataclass

from core.logging_v2.enums import RedisFailureMode, RedisWriteMode


@dataclass(frozen=True)
class LoggingV2Config:
    schema_version: str = "2.0"
    wal_filename: str = "wal.jsonl"
    artifacts_dirname: str = "artifacts"
    materialized_views_dirname: str = "materialized_views"

    call_txt_separator: str = "=" * 80
    call_txt_section_names: tuple[str, str, str] = (
        "METADATA", "REQUEST", "RESPONSE",
    )

    redis_enabled: bool = False
    redis_url: str = "redis://localhost:6379/0"
    redis_stream_name: str = "t3_events"
    redis_write_mode: RedisWriteMode = RedisWriteMode.ASYNC_BUFFERED
    redis_failure_mode: RedisFailureMode = RedisFailureMode.LOG_AND_CONTINUE


def validate_config(config: LoggingV2Config) -> None:
    if config.schema_version != "2.0":
        raise ValueError(
            f"schema_version must be '2.0', got {config.schema_version!r}"
        )
    if not isinstance(config.redis_write_mode, RedisWriteMode):
        raise TypeError(
            f"redis_write_mode must be RedisWriteMode, "
            f"got {type(config.redis_write_mode)}"
        )
    if not isinstance(config.redis_failure_mode, RedisFailureMode):
        raise TypeError(
            f"redis_failure_mode must be RedisFailureMode, "
            f"got {type(config.redis_failure_mode)}"
        )
    if len(config.call_txt_section_names) != 3:
        raise ValueError(
            f"call_txt_section_names must have exactly 3 elements, "
            f"got {len(config.call_txt_section_names)}"
        )
    if not config.call_txt_separator:
        raise ValueError("call_txt_separator must be non-empty")
