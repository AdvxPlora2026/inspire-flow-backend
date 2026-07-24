from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.data.models.user_profile import UserProfile

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


def bearer(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": f"test-{uuid4()}",
    }


def test_registration_creates_one_empty_creator_profile(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    token = register_and_login(client)

    response = client.get("/api/v1/users/me/profile", headers=bearer(token))

    assert response.status_code == 200
    body = response.json()
    assert body["bio"] is None
    assert body["timezone"] is None
    assert body["preferred_language"] is None
    assert body["creator_identity"] is None
    assert body["content_focus"] == []
    assert body["collaboration_preferences"] is None
    assert datetime.fromisoformat(body["created_at"]) == datetime.fromisoformat(body["updated_at"])
    with db_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(UserProfile)) == 1


def test_updates_current_creator_profile(client: TestClient) -> None:
    token = register_and_login(client)

    response = client.patch(
        "/api/v1/users/me/profile",
        headers=bearer(token),
        json={
            "timezone": "Asia/Shanghai",
            "preferred_language": "zh-CN",
            "creator_identity": "科技区 UP 主",
            "content_focus": ["AI", "数码"],
        },
    )

    assert response.status_code == 200
    assert response.json()["timezone"] == "Asia/Shanghai"
    assert response.json()["content_focus"] == ["AI", "数码"]


def test_creator_profile_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/users/me/profile").status_code == 401
    assert client.patch("/api/v1/users/me/profile", json={"bio": "x"}).status_code == 401


def test_creator_profile_rejects_unknown_field_without_echoing_value(
    client: TestClient,
) -> None:
    token = register_and_login(client)
    secret_marker = "should-not-be-reflected"

    response = client.patch(
        "/api/v1/users/me/profile",
        headers=bearer(token),
        json={"unexpected": secret_marker},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert secret_marker not in response.text
