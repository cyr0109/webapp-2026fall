"""Push inbox changes to connected browsers over SSE."""

import asyncio
import json
import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, time, timedelta
from threading import Event
from zoneinfo import ZoneInfo

import psycopg
from fastapi import FastAPI

from models import engine, now

TAIPEI = ZoneInfo("Asia/Taipei")
Slot = tuple[int, int]  # (group_id, member_id)
logger = logging.getLogger(__name__)


class InboxStream:
    def __init__(self) -> None:
        self.subscribers: dict[Slot, set[asyncio.Queue[None]]] = defaultdict(set)

    @staticmethod
    def wake(waiters: set[asyncio.Queue[None]]) -> None:
        for queue in waiters:
            # One pending refresh can cover any number of committed changes.
            if not queue.full():
                queue.put_nowait(None)

    def resync(self) -> None:
        for waiters in self.subscribers.values():
            self.wake(waiters)

    def notify(self, key: Slot) -> None:
        waiters = self.subscribers.get(key)
        if waiters:
            self.wake(waiters)

    def listen(self, loop: asyncio.AbstractEventLoop, stop: Event) -> None:
        # A single blocking LISTEN connection works with both Unix and Windows event loops.
        args, kwargs = engine.dialect.create_connect_args(engine.url)
        kwargs.setdefault("connect_timeout", 5)
        kwargs["autocommit"] = True
        while not stop.is_set():
            try:
                with psycopg.connect(*args, **kwargs) as connection:
                    (schema,) = connection.execute("SELECT current_schema()").fetchone()
                    connection.execute("LISTEN housemate_inbox")
                    # Resync clients in case updates were committed while LISTEN was offline.
                    loop.call_soon_threadsafe(self.resync)
                    while not stop.is_set():
                        for event in connection.notifies(timeout=1):
                            if stop.is_set():
                                return
                            try:
                                source, group_id, member_id = json.loads(event.payload)
                                if source == schema and isinstance(group_id, int) and isinstance(member_id, int):
                                    loop.call_soon_threadsafe(self.notify, (group_id, member_id))
                            except (ValueError, TypeError):
                                continue
            except psycopg.Error:
                logger.warning("Inbox listener disconnected. Reconnecting.")
                stop.wait(2)

    async def events(self, group_id: int, member_id: int):
        key = (group_id, member_id)
        queue: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
        self.subscribers[key].add(queue)
        refresh = "event: inbox\ndata: {}\n\n"
        try:
            last_date = now().astimezone(TAIPEI).date()
            yield refresh
            while True:
                local_now = now().astimezone(TAIPEI)
                if local_now.date() != last_date:
                    # A new local date can make a payment eligible for a reminder.
                    last_date = local_now.date()
                    yield refresh
                    continue
                midnight = datetime.combine(last_date + timedelta(days=1), time.min, TAIPEI)
                interval = min(20, (midnight - local_now).total_seconds())
                try:
                    await asyncio.wait_for(queue.get(), timeout=interval)
                except TimeoutError:
                    if now().astimezone(TAIPEI).date() == last_date:
                        yield ": keep-alive\n\n"
                else:
                    yield refresh
        finally:
            self.subscribers[key].remove(queue)
            if not self.subscribers[key]:
                del self.subscribers[key]


@asynccontextmanager
async def inbox_lifespan(app: FastAPI):
    app.state.inbox_stream = InboxStream()
    stop = Event()
    task = asyncio.create_task(
        asyncio.to_thread(app.state.inbox_stream.listen, asyncio.get_running_loop(), stop)
    )
    try:
        yield
    finally:
        stop.set()
        await task
