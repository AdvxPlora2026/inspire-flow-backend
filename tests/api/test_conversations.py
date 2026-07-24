from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.agent_conversation import AgentConversation
from inspire_flow_backend.data.models.agent_message import AgentMessage
from inspire_flow_backend.services.agent.runtime import AgentRuntime

PASSWORD = "correct horse battery staple"


def register_and_login(client: TestClient, nickname: str = "aria") -> str:
    registration = client.post(
        "/api/v1/users",
        json={"nickname": nickname, "password": PASSWORD},
    )
    assert registration.status_code == 201
    login = client.post(
        "/api/v1/sessions",
        json={"nickname": nickname, "password": PASSWORD},
    )
    assert login.status_code == 201
    return login.json()["access_token"]


def login(client: TestClient, nickname: str = "aria") -> str:
    response = client.post(
        "/api/v1/sessions",
        json={"nickname": nickname, "password": PASSWORD},
    )
    assert response.status_code == 201
    return response.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_conversation(
    client: TestClient,
    token: str,
    title: str | None = None,
) -> dict[str, object]:
    payload = {} if title is None else {"title": title}
    response = client.post(
        "/api/v1/conversations",
        headers=bearer(token),
        json=payload,
    )
    assert response.status_code == 201
    return response.json()


def send_message(
    client: TestClient,
    token: str,
    conversation_id: object,
    content: str,
):
    return client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=bearer(token),
        json={"content": content},
    )


def test_conversation_resource_crud_pagination_and_openapi(client: TestClient) -> None:
    token = register_and_login(client)
    first = create_conversation(client, token, "第一个项目")
    create_conversation(client, token, "第二个项目")

    page = client.get(
        "/api/v1/conversations?limit=1&offset=0",
        headers=bearer(token),
    )
    detail = client.get(
        f"/api/v1/conversations/{first['id']}",
        headers=bearer(token),
    )
    archived = client.patch(
        f"/api/v1/conversations/{first['id']}",
        headers=bearer(token),
        json={"archived": True},
    )
    active_page = client.get("/api/v1/conversations", headers=bearer(token))
    all_page = client.get(
        "/api/v1/conversations?include_archived=true",
        headers=bearer(token),
    )
    deleted = client.delete(
        f"/api/v1/conversations/{first['id']}",
        headers=bearer(token),
    )

    assert page.status_code == 200
    assert page.json()["total"] == 2
    assert len(page.json()["items"]) == 1
    assert detail.status_code == 200
    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    assert active_page.json()["total"] == 1
    assert all_page.json()["total"] == 2
    assert deleted.status_code == 204
    assert deleted.content == b""
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/conversations/{conversation_id}/messages" in paths


def test_new_login_session_continues_existing_conversation(
    client: TestClient,
    fake_agent_runtime: AgentRuntime,
) -> None:
    first_token = register_and_login(client)
    conversation = create_conversation(client, first_token)
    first = send_message(client, first_token, conversation["id"], "第一条灵感")
    second_token = login(client)
    second = send_message(client, second_token, conversation["id"], "继续完善")

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["assistant_message"]["content"] == "已接续 2 条用户消息"
    fake_agent = fake_agent_runtime.conversation_agent
    history = fake_agent.histories[UUID(str(conversation["id"]))]
    assert "第一条灵感" in str(history)
    assert "继续完善" in str(history)


def test_two_conversations_share_memory_but_not_raw_history(
    client: TestClient,
    fake_agent_runtime: AgentRuntime,
) -> None:
    token = register_and_login(client)
    first = create_conversation(client, token)
    second = create_conversation(client, token)
    assert (
        send_message(
            client,
            token,
            first["id"],
            "我主要做科技视频",
        ).status_code
        == 201
    )

    response = send_message(client, token, second["id"], "给我一个新方向")

    assert response.status_code == 201
    fake_agent = fake_agent_runtime.conversation_agent
    second_id = UUID(str(second["id"]))
    assert "我主要做科技视频" not in str(fake_agent.histories[second_id])
    assert "用户主要制作科技视频" in str(fake_agent.model_inputs[second_id][0])


def test_foreign_conversation_and_messages_are_not_found(client: TestClient) -> None:
    owner_token = register_and_login(client, "aria")
    foreign_token = register_and_login(client, "beta")
    conversation = create_conversation(client, owner_token)

    detail = client.get(
        f"/api/v1/conversations/{conversation['id']}",
        headers=bearer(foreign_token),
    )
    messages = client.get(
        f"/api/v1/conversations/{conversation['id']}/messages",
        headers=bearer(foreign_token),
    )
    turn = send_message(
        client,
        foreign_token,
        conversation["id"],
        "越权消息",
    )

    for response in (detail, messages, turn):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "conversation_not_found"


def test_concurrent_turn_returns_conversation_busy(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    token = register_and_login(client)
    conversation = create_conversation(client, token)
    conversation_id = UUID(str(conversation["id"]))
    with db_session_factory() as db:
        persisted = db.get(AgentConversation, conversation_id)
        assert persisted is not None
        persisted.active_run_id = uuid4()
        persisted.active_run_started_at = utc_now()
        db.commit()

    response = send_message(client, token, conversation_id, "并发输入")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conversation_busy"


def test_archived_conversation_rejects_turn_until_unarchived(
    client: TestClient,
) -> None:
    token = register_and_login(client)
    conversation = create_conversation(client, token)
    path = f"/api/v1/conversations/{conversation['id']}"
    assert (
        client.patch(
            path,
            headers=bearer(token),
            json={"archived": True},
        ).status_code
        == 200
    )

    rejected = send_message(client, token, conversation["id"], "继续")
    restored = client.patch(
        path,
        headers=bearer(token),
        json={"archived": False},
    )
    accepted = send_message(client, token, conversation["id"], "重新继续")

    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "conversation_archived"
    assert restored.status_code == 200
    assert accepted.status_code == 201


def test_turn_returns_memory_updates_and_extraction_status(client: TestClient) -> None:
    token = register_and_login(client)
    conversation = create_conversation(client, token)

    response = send_message(
        client,
        token,
        conversation["id"],
        "我主要做科技视频",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["memory_extraction_status"] == "completed"
    assert body["memory_updates"][0]["content"] == "用户主要制作科技视频"
    messages = client.get(
        f"/api/v1/conversations/{conversation['id']}/messages?limit=1",
        headers=bearer(token),
    )
    assert messages.status_code == 200
    assert len(messages.json()["items"]) == 1
    assert messages.json()["next_cursor"] is not None


def test_agent_failure_uses_safe_error_and_preserves_user_message(
    client: TestClient,
    fake_agent_runtime: AgentRuntime,
    db_session_factory: sessionmaker[Session],
) -> None:
    token = register_and_login(client)
    conversation = create_conversation(client, token)
    fake_agent_runtime.conversation_agent.fail_next = True

    response = send_message(client, token, conversation["id"], "模型失败也要保留")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "agent_run_failed"
    assert "fake API model failure" not in response.text
    conversation_id = UUID(str(conversation["id"]))
    with db_session_factory() as db:
        rows = list(
            db.scalars(select(AgentMessage).where(AgentMessage.conversation_id == conversation_id))
        )
        persisted = db.get(AgentConversation, conversation_id)
    assert len(rows) == 1
    assert rows[0].role == "user"
    assert persisted is not None
    assert persisted.active_run_id is None


def test_conversation_validation_and_authentication_are_strict(
    client: TestClient,
) -> None:
    assert client.get("/api/v1/conversations").status_code == 401
    token = register_and_login(client)

    for query in ("limit=0", "limit=101", "offset=-1"):
        response = client.get(
            f"/api/v1/conversations?{query}",
            headers=bearer(token),
        )
        assert response.status_code == 422
    unknown = client.post(
        "/api/v1/conversations",
        headers=bearer(token),
        json={"unknown": "not-reflected"},
    )
    assert unknown.status_code == 422
    assert "not-reflected" not in unknown.text
