from uuid import uuid4

from fastapi.testclient import TestClient

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


def create_memory(client: TestClient, token: str, content: str = "偏好简洁脚本") -> dict:
    response = client.post(
        "/api/v1/users/me/memories",
        headers=bearer(token),
        json={
            "category": "workflow_preference",
            "content": content,
            "is_pinned": False,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_memory_rest_crud_and_pagination(client: TestClient) -> None:
    token = register_and_login(client)
    first = create_memory(client, token)
    create_memory(client, token, content="喜欢科技内容")

    page = client.get(
        "/api/v1/users/me/memories?limit=1&offset=0",
        headers=bearer(token),
    )
    detail = client.get(
        f"/api/v1/users/me/memories/{first['id']}",
        headers=bearer(token),
    )
    updated = client.patch(
        f"/api/v1/users/me/memories/{first['id']}",
        headers=bearer(token),
        json={"status": "inactive", "is_pinned": True},
    )
    deleted = client.delete(
        f"/api/v1/users/me/memories/{first['id']}",
        headers=bearer(token),
    )

    assert page.status_code == 200
    assert page.json()["total"] == 2
    assert page.json()["limit"] == 1
    assert len(page.json()["items"]) == 1
    assert detail.status_code == 200
    assert detail.json()["content"] == "偏好简洁脚本"
    assert updated.status_code == 200
    assert updated.json()["status"] == "inactive"
    assert updated.json()["is_pinned"] is True
    assert updated.json()["user_edited"] is True
    assert deleted.status_code == 204
    assert deleted.content == b""


def test_memory_filters_are_user_scoped(client: TestClient) -> None:
    first_token = register_and_login(client, "aria")
    second_token = register_and_login(client, "beta")
    memory = create_memory(client, first_token)

    foreign = client.get(
        f"/api/v1/users/me/memories/{memory['id']}",
        headers=bearer(second_token),
    )
    filtered = client.get(
        "/api/v1/users/me/memories?status=active&category=workflow_preference",
        headers=bearer(first_token),
    )

    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "memory_not_found"
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["items"]] == [memory["id"]]


def test_credential_memory_has_stable_safe_error(client: TestClient) -> None:
    token = register_and_login(client)
    credential = "api_key=test-secret-placeholder"

    response = client.post(
        "/api/v1/users/me/memories",
        headers=bearer(token),
        json={"category": "other", "content": credential},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "credential_memory_forbidden"
    assert credential not in response.text


def test_memory_endpoints_require_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/users/me/memories")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session"


def test_memory_query_and_body_validation_is_strict(client: TestClient) -> None:
    token = register_and_login(client)

    for query in ("limit=0", "limit=101", "offset=-1", "status=unknown"):
        response = client.get(
            f"/api/v1/users/me/memories?{query}",
            headers=bearer(token),
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    unknown_field = client.post(
        "/api/v1/users/me/memories",
        headers=bearer(token),
        json={"category": "other", "content": "safe", "unknown": "hidden-value"},
    )
    assert unknown_field.status_code == 422
    assert "hidden-value" not in unknown_field.text
