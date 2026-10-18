"""进程内 asyncio 事件流中心：SSE 进度事件订阅/发布。

单用户本地场景，无需跨进程队列；每个进行中的任务对应一个 asyncio.Queue，
subscribe(job_id) 返回该队列，SSE 端点逐条 yield。
"""

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator

Event = dict


class EventHub:
    def __init__(self) -> None:
        self._queues: defaultdict[str, list[asyncio.Queue]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def subscribe(self, key: str) -> asyncio.Queue:
        """订阅某事件流，返回回调队列。"""
        q: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._queues[key].append(q)
        return q

    async def _detach_on_closed(self, key: str, q: asyncio.Queue) -> None:
        try:
            while True:
                await q.get()
        except asyncio.CancelledError:
            async with self._lock:
                if q in self._queues.get(key, []):
                    self._queues[key].remove(q)
            raise

    async def publish(self, key: str, event: Event) -> None:
        """向某事件流广播一个事件。"""
        async with self._lock:
            queues = list(self._queues.get(key, []))
        for q in queues:
            q.put_nowait(event)

    def sse_encode(self, event: Event) -> str:
        """编码为 SSE 帧。"""
        ev_type = event.get("type", "message")
        payload = json.dumps(event.get("payload", {}), ensure_ascii=False, default=str)
        return f"event: {ev_type}\ndata: {payload}\n\n"

    async def stream(self, key: str) -> AsyncIterator[str]:
        """SSE 生成器：yield 帧，30s 无消息发 keepalive。"""
        q = await self.subscribe(key)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30)
                    yield self.sse_encode(event)
                    if event.get("type") == "done":
                        break
                except asyncio.TimeoutError:
                    yield self.sse_encode({"type": "keepalive", "payload": {}})
        finally:
            async with self._lock:
                if q in self._queues.get(key, []):
                    self._queues[key].remove(q)


# 全局单例
hub = EventHub()
