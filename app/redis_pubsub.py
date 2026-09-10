import json
import inspect
import logging
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

class BroadcastBus:
    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url
        self.subscribers: Dict[str, List[Callable]] = {}

    def subscribe(self, channel: str, callback: Callable):
        if channel not in self.subscribers:
            self.subscribers[channel] = []
        self.subscribers[channel].append(callback)

    async def publish(self, channel: str, message: dict):
        # ponytail: local in-memory fan-out; connect Redis cluster via redis.asyncio when REDIS_URL provided
        if self.redis_url:
            try:
                import redis.asyncio as aioredis
                client = aioredis.from_url(self.redis_url)
                await client.publish(channel, json.dumps(message))
                await client.aclose()
            except Exception as e:
                logger.warning("Redis publish failed, falling back to local fanout: %s", e)

        if channel in self.subscribers:
            for cb in self.subscribers[channel]:
                if inspect.iscoroutinefunction(cb):
                    await cb(message)
                else:
                    cb(message)

bus = BroadcastBus()
