"""Redis streaming sink. Optional. Never blocks WAL writes."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any

from core.logging_v2.config import LoggingV2Config
from core.logging_v2.enums import RedisFailureMode, RedisWriteMode
from core.logging_v2.events import WALEvent

log = logging.getLogger("t3.redis_sink")


class RedisSink:
    """Streams WAL events to Redis. Failure never blocks WAL."""

    def __init__(self, config: LoggingV2Config) -> None:
        self.config = config
        self.buffer: list[dict] = []
        self.client: Any = None
        if config.redis_enabled:
            try:
                import redis
                self.client = redis.Redis.from_url(config.redis_url)
                self.client.ping()
            except Exception as exc:
                if config.redis_failure_mode == RedisFailureMode.RAISE:
                    raise
                log.warning("Redis connection failed: %s", exc)
                self.client = None

    def emit(self, event: WALEvent) -> None:
        if self.client is None:
            return
        record = asdict(event)
        serialized = json.dumps(record, default=str)
        if self.config.redis_write_mode == RedisWriteMode.SYNC:
            self.client.xadd(
                self.config.redis_stream_name,
                {"data": serialized},
            )
        else:
            self.buffer.append({"data": serialized})
            if len(self.buffer) >= 10:
                self.flush()

    def flush(self) -> None:
        if self.client is None or not self.buffer:
            return
        pipe = self.client.pipeline()
        for item in self.buffer:
            pipe.xadd(self.config.redis_stream_name, item)
        pipe.execute()
        self.buffer.clear()

    def close(self) -> None:
        self.flush()
        if self.client is not None:
            self.client.close()
