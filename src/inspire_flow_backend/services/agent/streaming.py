import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from inspire_flow_backend.core.config import Settings
from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.idempotency import AgentTurnRun
from inspire_flow_backend.data.repositories.idempotency import add_agent_turn_run
from inspire_flow_backend.data.repositories.users import get_user_by_id
from inspire_flow_backend.services.agent.conversation import (
    AgentStreamEvent,
    stream_conversation_turn,
)
from inspire_flow_backend.services.agent.runtime import AgentRuntime
from inspire_flow_backend.services.idempotency import complete_idempotency_record

RuntimeFactory = Callable[[], AgentRuntime]


def encode_sse(sequence: int, event: AgentStreamEvent) -> bytes:
    data = json.dumps(
        event.data,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"id: {sequence}\nevent: {event.event}\ndata: {data}\n\n".encode()


@dataclass
class AgentStreamHandle:
    queue: asyncio.Queue[tuple[int, AgentStreamEvent]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=100)
    )
    subscribed: bool = True
    sequence: int = 0

    def publish(self, event: AgentStreamEvent) -> None:
        self.sequence += 1
        if not self.subscribed:
            return
        item = (self.sequence, event)
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            if event.event == "response.delta":
                return
            while True:
                with suppress(asyncio.QueueEmpty):
                    self.queue.get_nowait()
                    continue
                break
            self.queue.put_nowait(item)

    async def events(self) -> AsyncIterator[bytes]:
        try:
            while True:
                try:
                    sequence, event = await asyncio.wait_for(
                        self.queue.get(),
                        timeout=15,
                    )
                except TimeoutError:
                    yield b": heartbeat\n\n"
                    continue
                yield encode_sse(sequence, event)
                if event.event in {"turn.completed", "turn.failed"}:
                    return
        finally:
            self.subscribed = False


class AgentStreamManager:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def start(
        self,
        *,
        engine: Engine,
        user_id: UUID,
        conversation_id: UUID,
        content: str,
        idempotency_record_id: UUID,
        runtime_factory: RuntimeFactory,
        cipher: ContextCipher,
        settings: Settings,
    ) -> AgentStreamHandle:
        handle = AgentStreamHandle()
        task = asyncio.create_task(
            self._run(
                handle=handle,
                engine=engine,
                user_id=user_id,
                conversation_id=conversation_id,
                content=content,
                idempotency_record_id=idempotency_record_id,
                runtime_factory=runtime_factory,
                cipher=cipher,
                settings=settings,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return handle

    async def close(self) -> None:
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(
        self,
        *,
        handle: AgentStreamHandle,
        engine: Engine,
        user_id: UUID,
        conversation_id: UUID,
        content: str,
        idempotency_record_id: UUID,
        runtime_factory: RuntimeFactory,
        cipher: ContextCipher,
        settings: Settings,
    ) -> None:
        run_id = uuid4()
        turn_id = uuid4()
        db_factory = sessionmaker(bind=engine, expire_on_commit=False)
        terminal = AgentStreamEvent(
            event="turn.failed",
            data={"turn_id": str(turn_id), "error": {"code": "agent_run_failed"}},
        )
        started = AgentStreamEvent(
            event="turn.started",
            data={"turn_id": str(turn_id)},
        )
        runtime: AgentRuntime | None = None
        with db_factory() as db:
            run = AgentTurnRun(
                id=run_id,
                conversation_id=conversation_id,
                user_id=user_id,
                idempotency_record_id=idempotency_record_id,
                turn_id=turn_id,
                status="processing",
                created_at=utc_now(),
            )
            add_agent_turn_run(db, run)
            db.commit()
            try:
                user = get_user_by_id(db, user_id)
                if user is None:
                    raise RuntimeError("stream user disappeared")
                runtime = runtime_factory()
                async for event in stream_conversation_turn(
                    db,
                    user=user,
                    conversation_id=conversation_id,
                    content=content,
                    runtime=runtime,
                    cipher=cipher,
                    settings=settings,
                    run_id=run_id,
                    turn_id=turn_id,
                ):
                    if event.event == "turn.completed":
                        terminal = event
                    else:
                        handle.publish(event)
                run.status = "completed"
                run.result_ciphertext = cipher.encrypt_json(terminal.data)
                run.completed_at = utc_now()
                db.commit()
            except asyncio.CancelledError:
                db.rollback()
                run.status = "failed"
                run.error_code = "agent_stream_shutdown"
                run.completed_at = utc_now()
                db.commit()
                terminal = AgentStreamEvent(
                    event="turn.failed",
                    data={
                        "turn_id": str(turn_id),
                        "error": {"code": "agent_stream_shutdown"},
                    },
                )
            except Exception:
                db.rollback()
                run.status = "failed"
                run.error_code = "agent_run_failed"
                run.completed_at = utc_now()
                db.commit()
            finally:
                if runtime is not None:
                    await runtime.aclose()

            complete_idempotency_record(
                db,
                record_id=idempotency_record_id,
                cipher=cipher,
                status_code=200,
                body={
                    "events": [
                        {"event": started.event, "data": started.data},
                        {"event": terminal.event, "data": terminal.data},
                    ]
                },
                headers={"content-type": "text/event-stream"},
            )
        handle.publish(terminal)
