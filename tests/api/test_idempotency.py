from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.idempotency import IdempotencyRecord
from inspire_flow_backend.services import idempotency as idempotency_service

PASSWORD = "correct horse battery staple"


def register_and_login(client: TestClient) -> str:
    registration = client.post(
        "/api/v1/users",
        json={"nickname": "idempotency-user", "password": PASSWORD},
    )
    assert registration.status_code == 201
    login = client.post(
        "/api/v1/sessions",
        json={"nickname": "idempotency-user", "password": PASSWORD},
    )
    assert login.status_code == 201
    return login.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_authenticated_write_requires_idempotency_key(client: TestClient) -> None:
    token = register_and_login(client)

    response = client.patch(
        "/api/v1/users/me",
        headers=bearer(token),
        json={"nickname": "missing-key"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "idempotency_key_required"


def test_completed_write_replays_and_rejects_changed_payload(
    client: TestClient,
    db_session_factory,
) -> None:
    token = register_and_login(client)
    headers = {
        **bearer(token),
        "Idempotency-Key": "profile-update-0001",
    }

    first = client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"nickname": "idempotent-creator"},
    )
    replay = client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"nickname": "idempotent-creator"},
    )
    conflict = client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"nickname": "different-creator"},
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_key_conflict"

    with db_session_factory() as db:
        record = db.scalar(select(IdempotencyRecord))
        assert record is not None
        assert record.key_digest != "profile-update-0001"
        assert record.response_ciphertext is not None
        assert "idempotent-creator" not in record.response_ciphertext
        assert record.completed_at is not None
        retention = record.expires_at - record.completed_at
    assert 23 * 60 * 60 < retention.total_seconds() <= 24 * 60 * 60

    with db_session_factory() as db:
        record = db.scalar(select(IdempotencyRecord))
        assert record is not None
        record.status = "processing"
        db.commit()
    in_progress = client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"nickname": "idempotent-creator"},
    )
    assert in_progress.status_code == 409
    assert in_progress.json()["error"]["code"] == "idempotency_request_in_progress"


def test_empty_success_response_replays_without_body(client: TestClient) -> None:
    token = register_and_login(client)
    project = client.post(
        "/api/v1/projects",
        headers={
            **bearer(token),
            "Idempotency-Key": "project-create-0001",
        },
        json={
            "title": "待删除项目",
            "type": "科技",
            "audience": "创作者",
            "summary": "验证空响应重放",
        },
    ).json()
    headers = {
        **bearer(token),
        "Idempotency-Key": "project-delete-0001",
    }

    first = client.delete(
        f"/api/v1/projects/{project['id']}",
        headers=headers,
    )
    replay = client.delete(
        f"/api/v1/projects/{project['id']}",
        headers=headers,
    )

    assert first.status_code == 204
    assert first.content == b""
    assert replay.status_code == 204
    assert replay.content == b""
    assert replay.headers["Idempotency-Replayed"] == "true"


def test_expired_key_starts_a_new_operation(
    client: TestClient,
    db_session_factory,
    monkeypatch,
) -> None:
    token = register_and_login(client)
    headers = {
        **bearer(token),
        "Idempotency-Key": "profile-expiry-0001",
    }
    payload = {"nickname": "expiry-creator"}
    first = client.patch("/api/v1/users/me", headers=headers, json=payload)
    assert first.status_code == 200

    with db_session_factory() as db:
        first_record = db.scalar(select(IdempotencyRecord))
        assert first_record is not None
        first_record_id = first_record.id
        after_expiry = first_record.expires_at + timedelta(seconds=1)
    monkeypatch.setattr(idempotency_service, "utc_now", lambda: after_expiry)

    retried = client.patch("/api/v1/users/me", headers=headers, json=payload)

    assert retried.status_code == 200
    assert "Idempotency-Replayed" not in retried.headers
    with db_session_factory() as db:
        replacement = db.scalar(select(IdempotencyRecord))
        count = db.scalar(select(func.count()).select_from(IdempotencyRecord))
    assert count == 1
    assert replacement is not None
    assert replacement.id != first_record_id


def test_stale_processing_key_reports_unknown_outcome(
    client: TestClient,
    db_session_factory,
) -> None:
    token = register_and_login(client)
    headers = {
        **bearer(token),
        "Idempotency-Key": "profile-stale-0001",
    }
    payload = {"nickname": "stale-operation-creator"}
    first = client.patch("/api/v1/users/me", headers=headers, json=payload)
    assert first.status_code == 200
    with db_session_factory() as db:
        record = db.scalar(select(IdempotencyRecord))
        assert record is not None
        record.status = "processing"
        record.created_at = utc_now() - timedelta(seconds=601)
        db.commit()

    stale = client.patch("/api/v1/users/me", headers=headers, json=payload)

    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "idempotency_outcome_unknown"
    retried = client.patch(
        "/api/v1/users/me",
        headers={
            **bearer(token),
            "Idempotency-Key": "profile-stale-retry-0002",
        },
        json=payload,
    )
    assert retried.status_code == 200
    assert "Idempotency-Replayed" not in retried.headers


def test_openapi_declares_idempotency_header_on_authenticated_writes(
    client: TestClient,
) -> None:
    document = client.get("/openapi.json").json()
    missing: list[str] = []
    for path, path_item in document["paths"].items():
        for method in ("post", "put", "patch", "delete"):
            operation = path_item.get(method)
            if operation is None or not operation.get("security"):
                continue
            if path in {
                "/api/v1/sessions/current",
            }:
                continue
            header_names = {
                parameter["name"]
                for parameter in operation.get("parameters", [])
                if parameter.get("in") == "header"
            }
            if "Idempotency-Key" not in header_names:
                missing.append(f"{method.upper()} {path}")

    assert missing == []
