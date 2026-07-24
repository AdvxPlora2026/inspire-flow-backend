from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.data.models.user import User
from inspire_flow_backend.data.models.user_profile import UserProfile

PASSWORD = "correct horse battery staple"


def register_and_login(
    client: TestClient,
    nickname: str = "aria",
    avatar_url: str | None = None,
) -> tuple[dict[str, object], str]:
    payload: dict[str, object] = {
        "nickname": nickname,
        "password": PASSWORD,
    }
    if avatar_url is not None:
        payload["avatar_url"] = avatar_url
    registration = client.post("/api/v1/users", json=payload)
    assert registration.status_code == 201
    login = client.post(
        "/api/v1/sessions",
        json={"nickname": nickname, "password": PASSWORD},
    )
    assert login.status_code == 201
    return registration.json(), login.json()["access_token"]


def authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_registers_user_with_public_fields(client: TestClient) -> None:
    before = datetime.now(UTC)

    response = client.post(
        "/api/v1/users",
        json={
            "nickname": " aria ",
            "password": PASSWORD,
            "avatar_url": "https://cdn.example.com/aria.png",
        },
    )

    after = datetime.now(UTC)
    assert response.status_code == 201
    body = response.json()
    user_id = UUID(body["id"])
    assert user_id.version == 4
    assert set(body) == {
        "id",
        "nickname",
        "avatar_url",
        "created_at",
        "updated_at",
    }
    assert body["nickname"] == "aria"
    assert body["avatar_url"] == "https://cdn.example.com/aria.png"
    created_at = datetime.fromisoformat(body["created_at"])
    updated_at = datetime.fromisoformat(body["updated_at"])
    assert before <= created_at <= after
    assert updated_at == created_at
    assert created_at.utcoffset() == timedelta(0)
    assert "password" not in response.text
    assert "nickname_key" not in response.text


def test_rejects_normalized_nickname_duplicate(client: TestClient) -> None:
    first = {
        "nickname": "Ａria",
        "password": PASSWORD,
    }
    second = {
        "nickname": "aria",
        "password": "another secure passphrase value",
    }
    assert client.post("/api/v1/users", json=first).status_code == 201

    response = client.post("/api/v1/users", json=second)

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "nickname_conflict",
            "message": "Nickname is already in use",
        }
    }


@pytest.mark.parametrize(
    ("payload", "secret_value"),
    [
        (
            {"nickname": "a", "password": PASSWORD},
            None,
        ),
        (
            {"nickname": "aria", "password": "x9Q!leak"},
            "x9Q!leak",
        ),
        (
            {
                "nickname": "aria",
                "password": PASSWORD,
                "avatar_url": "not-a-url",
            },
            None,
        ),
        (
            {
                "nickname": "aria",
                "password": PASSWORD,
                "role": "admin",
            },
            None,
        ),
    ],
)
def test_rejects_invalid_registration_without_echoing_secrets(
    client: TestClient,
    payload: dict[str, object],
    secret_value: str | None,
) -> None:
    response = client.post("/api/v1/users", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    if secret_value is not None:
        assert secret_value not in response.text


def test_reads_current_public_user(client: TestClient) -> None:
    registered, access_token = register_and_login(client)

    response = client.get(
        "/api/v1/users/me",
        headers=authorization(access_token),
    )

    assert response.status_code == 200
    assert response.json() == registered
    assert "password" not in response.text
    assert "nickname_key" not in response.text


def test_changes_nickname_and_new_value_becomes_login_identifier(
    client: TestClient,
) -> None:
    registered, access_token = register_and_login(client)

    response = client.patch(
        "/api/v1/users/me",
        headers=authorization(access_token),
        json={"nickname": "Aria Renamed"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["nickname"] == "Aria Renamed"
    old_updated_at = datetime.fromisoformat(str(registered["updated_at"]))
    new_updated_at = datetime.fromisoformat(body["updated_at"])
    assert new_updated_at > old_updated_at
    assert new_updated_at.utcoffset() == timedelta(0)
    assert (
        client.post(
            "/api/v1/sessions",
            json={"nickname": "aria", "password": PASSWORD},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/sessions",
            json={"nickname": "aria renamed", "password": PASSWORD},
        ).status_code
        == 201
    )


def test_changes_avatar(client: TestClient) -> None:
    registered, access_token = register_and_login(client)

    response = client.patch(
        "/api/v1/users/me",
        headers=authorization(access_token),
        json={"avatar_url": "https://cdn.example.com/new.png"},
    )

    assert response.status_code == 200
    assert response.json()["avatar_url"] == "https://cdn.example.com/new.png"
    assert datetime.fromisoformat(response.json()["updated_at"]) > datetime.fromisoformat(
        str(registered["updated_at"])
    )


def test_clears_avatar(client: TestClient) -> None:
    _, access_token = register_and_login(
        client,
        avatar_url="https://cdn.example.com/original.png",
    )

    response = client.patch(
        "/api/v1/users/me",
        headers=authorization(access_token),
        json={"avatar_url": None},
    )

    assert response.status_code == 200
    assert response.json()["avatar_url"] is None


def test_profile_no_op_preserves_updated_at(client: TestClient) -> None:
    registered, access_token = register_and_login(client)

    response = client.patch(
        "/api/v1/users/me",
        headers=authorization(access_token),
        json={"nickname": "aria"},
    )

    assert response.status_code == 200
    assert response.json()["updated_at"] == registered["updated_at"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"nickname": None},
        {"unexpected": True},
    ],
)
def test_rejects_invalid_profile_patch(
    client: TestClient,
    payload: dict[str, object],
) -> None:
    _, access_token = register_and_login(client)

    response = client.patch(
        "/api/v1/users/me",
        headers=authorization(access_token),
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_rejects_profile_nickname_conflict(client: TestClient) -> None:
    _, access_token = register_and_login(client, "aria")
    other = client.post(
        "/api/v1/users",
        json={"nickname": "beta", "password": PASSWORD},
    )
    assert other.status_code == 201

    response = client.patch(
        "/api/v1/users/me",
        headers=authorization(access_token),
        json={"nickname": "ＢＥＴＡ"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "nickname_conflict"


def test_persists_only_argon2_password_hash(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    response = client.post(
        "/api/v1/users",
        json={"nickname": "aria", "password": PASSWORD},
    )
    assert response.status_code == 201

    with db_session_factory() as db:
        user = db.scalar(select(User).where(User.nickname == "aria"))

    assert user is not None
    assert user.password_hash != PASSWORD
    assert PASSWORD not in user.password_hash
    assert user.password_hash.startswith("$argon2")


def test_registration_persists_profile_in_same_transaction(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    response = client.post(
        "/api/v1/users",
        json={"nickname": "aria", "password": PASSWORD},
    )
    assert response.status_code == 201
    user_id = UUID(response.json()["id"])

    with db_session_factory() as db:
        profile = db.get(UserProfile, user_id)

    assert profile is not None
    assert profile.created_at == profile.updated_at
