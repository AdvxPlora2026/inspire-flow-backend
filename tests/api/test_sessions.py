from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.core.security import digest_session_token
from inspire_flow_backend.data.models.auth_session import AuthSession

PASSWORD = "correct horse battery staple"


def register(client: TestClient, nickname: str = "aria") -> None:
    response = client.post(
        "/api/v1/users",
        json={
            "nickname": nickname,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 201


def login(client: TestClient, nickname: str = "aria") -> str:
    response = client.post(
        "/api/v1/sessions",
        json={
            "nickname": nickname,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 201
    return response.json()["access_token"]


def bearer(token: str, scheme: str = "Bearer") -> dict[str, str]:
    return {"Authorization": f"{scheme} {token}"}


def test_login_returns_opaque_session_and_no_store_headers(
    client: TestClient,
) -> None:
    register(client)
    before = datetime.now(UTC)

    response = client.post(
        "/api/v1/sessions",
        json={"nickname": "aria", "password": PASSWORD},
    )

    after = datetime.now(UTC)
    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) >= 43
    assert body["user"]["nickname"] == "aria"
    expires_at = datetime.fromisoformat(body["expires_at"])
    assert before + timedelta(hours=24) <= expires_at
    assert expires_at <= after + timedelta(hours=24)
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"


def test_login_failures_do_not_reveal_nickname_existence(
    client: TestClient,
) -> None:
    register(client)

    unknown = client.post(
        "/api/v1/sessions",
        json={"nickname": "missing-user", "password": "wrong"},
    )
    incorrect = client.post(
        "/api/v1/sessions",
        json={"nickname": "aria", "password": "wrong"},
    )

    expected = {
        "error": {
            "code": "invalid_credentials",
            "message": "Invalid nickname or password",
        }
    }
    assert unknown.status_code == 401
    assert incorrect.status_code == 401
    assert unknown.json() == incorrect.json() == expected


def test_persists_only_session_token_digest(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    register(client)
    access_token = login(client)

    with db_session_factory() as db:
        persisted_hashes = list(db.scalars(select(AuthSession.token_hash)))

    assert access_token not in persisted_hashes
    assert digest_session_token(access_token) in persisted_hashes


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer unknown-token"},
        {"Authorization": "Bearer"},
    ],
)
def test_rejects_invalid_session_headers(
    client: TestClient,
    headers: dict[str, str],
) -> None:
    response = client.get("/api/v1/users/me", headers=headers)

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "invalid_session",
            "message": "A valid bearer session is required",
        }
    }
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_accepts_case_insensitive_bearer_scheme(client: TestClient) -> None:
    register(client)
    access_token = login(client)

    response = client.get(
        "/api/v1/users/me",
        headers=bearer(access_token, scheme="bearer"),
    )

    assert response.status_code == 200


def test_expired_session_is_rejected_and_removed(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    register(client)
    access_token = login(client)
    token_hash = digest_session_token(access_token)
    with db_session_factory() as db:
        auth_session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
        assert auth_session is not None
        auth_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    response = client.get("/api/v1/users/me", headers=bearer(access_token))

    assert response.status_code == 401
    with db_session_factory() as db:
        assert db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash)) is None


def test_logout_revokes_only_the_current_session(client: TestClient) -> None:
    register(client)
    first_token = login(client)
    second_token = login(client)
    assert (
        client.get(
            "/api/v1/users/me",
            headers=bearer(first_token),
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/v1/users/me",
            headers=bearer(second_token),
        ).status_code
        == 200
    )

    response = client.delete(
        "/api/v1/sessions/current",
        headers=bearer(first_token),
    )

    assert response.status_code == 204
    assert response.content == b""
    assert (
        client.get(
            "/api/v1/users/me",
            headers=bearer(first_token),
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/v1/users/me",
            headers=bearer(second_token),
        ).status_code
        == 200
    )
