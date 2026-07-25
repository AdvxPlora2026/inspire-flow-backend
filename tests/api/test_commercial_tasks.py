import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from inspire_flow_backend.api.dependencies import get_injective_provider
from inspire_flow_backend.data.models.idempotency import IdempotencyRecord
from tests.api.conftest import FakeInjectiveProvider

PASSWORD = "correct horse battery staple"
PROJECT_PAYLOAD = {
    "title": "MPS 实测",
    "type": "科技数码",
    "audience": "Mac 用户",
    "summary": "在本地运行语音识别",
}
ARTIFACT_SHA256 = "a" * 64
TASK_NOT_FOUND = {
    "error": {
        "code": "commercial_task_not_found",
        "message": "Commercial task was not found",
    }
}
SEQUENCE_CONFLICT = {
    "error": {
        "code": "sequence_conflict",
        "message": "The requested action is out of order for this commercial task",
    }
}


def register_and_login(client: TestClient, nickname: str) -> str:
    assert (
        client.post(
            "/api/v1/users",
            json={"nickname": nickname, "password": PASSWORD},
        ).status_code
        == 201
    )
    response = client.post(
        "/api/v1/sessions",
        json={"nickname": nickname, "password": PASSWORD},
    )
    assert response.status_code == 201
    return response.json()["access_token"]


def authorization(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": f"test-{uuid4()}",
    }


def create_project(client: TestClient, token: str) -> str:
    response = client.post(
        "/api/v1/projects",
        headers=authorization(token),
        json=PROJECT_PAYLOAD,
    )
    assert response.status_code == 201
    return response.json()["id"]


def task_payload(project_id: str) -> dict[str, object]:
    return {
        "project_id": project_id,
        "title": "品牌合作视频",
        "budget": {"amount": "150.5", "denom": "inj"},
        "deadline": "2026-12-31T00:00:00+00:00",
        "splits": [
            {"party_id": "creator", "bps": 6000},
            {"party_id": "brand", "bps": 4000},
        ],
    }


def create_task(client: TestClient, token: str, project_id: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/commercial-tasks",
        headers=authorization(token),
        json=task_payload(project_id),
    )
    assert response.status_code == 201
    return response.json()


def submit_artifact(client: TestClient, token: str, task_id: str) -> dict[str, object]:
    response = client.post(
        f"/api/v1/commercial-tasks/{task_id}/submissions",
        headers=authorization(token),
        json={
            "artifact_id": str(uuid4()),
            "artifact_sha256": ARTIFACT_SHA256,
            "delivery_url": "https://cdn.example.com/final-cut.mp4",
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("post", "/api/v1/commercial-tasks", {"json": {}}),
        (
            "post",
            f"/api/v1/commercial-tasks/{uuid4()}/submissions",
            {"json": {}},
        ),
        ("post", f"/api/v1/commercial-tasks/{uuid4()}/authorize", {}),
        ("post", f"/api/v1/commercial-tasks/{uuid4()}/settle", {}),
        ("get", f"/api/v1/commercial-tasks/{uuid4()}/proof", {}),
    ],
)
def test_commercial_tasks_require_authentication(
    client: TestClient,
    method: str,
    path: str,
    kwargs: dict[str, object],
) -> None:
    response = client.request(method, path, **kwargs)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session"


def test_create_commercial_task_funds_escrow(
    client: TestClient,
    fake_injective_provider: FakeInjectiveProvider,
) -> None:
    token = register_and_login(client, "链上创作者")
    project_id = create_project(client, token)

    task = create_task(client, token, project_id)

    assert task["status"] == "escrow_funded"
    assert task["project_id"] == project_id
    assert task["budget"] == {"amount": "150.5", "denom": "inj"}
    assert task["splits"] == [
        {"party_id": "creator", "bps": 6000},
        {"party_id": "brand", "bps": 4000},
    ]
    assert len(fake_injective_provider.memos) == 1
    assert ARTIFACT_SHA256 not in fake_injective_provider.memos[0]
    assert "品牌合作视频" not in fake_injective_provider.memos[0]


def test_create_commercial_task_rejects_bad_splits(client: TestClient) -> None:
    token = register_and_login(client, "分账校验用户")
    project_id = create_project(client, token)
    payload = task_payload(project_id)
    payload["splits"] = [
        {"party_id": "creator", "bps": 6000},
        {"party_id": "brand", "bps": 3999},
    ]

    response = client.post(
        "/api/v1/commercial-tasks",
        headers=authorization(token),
        json=payload,
    )

    assert response.status_code == 422


def test_create_commercial_task_requires_owned_project(client: TestClient) -> None:
    token = register_and_login(client, "项目缺失用户")

    response = client.post(
        "/api/v1/commercial-tasks",
        headers=authorization(token),
        json=task_payload(str(uuid4())),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "project_not_found"


def test_commercial_task_full_lifecycle_and_proof(
    client: TestClient,
    fake_injective_provider: FakeInjectiveProvider,
) -> None:
    token = register_and_login(client, "全流程用户")
    project_id = create_project(client, token)
    task = create_task(client, token, project_id)
    task_id = task["id"]

    submission = submit_artifact(client, token, task_id)
    assert submission["artifact_sha256"] == ARTIFACT_SHA256

    authorize = client.post(
        f"/api/v1/commercial-tasks/{task_id}/authorize",
        headers=authorization(token),
    )
    assert authorize.status_code == 200
    assert authorize.json()["status"] == "authorization_activated"

    settle = client.post(
        f"/api/v1/commercial-tasks/{task_id}/settle",
        headers=authorization(token),
    )
    assert settle.status_code == 200
    assert settle.json()["status"] == "settlement_released"

    proof = client.get(
        f"/api/v1/commercial-tasks/{task_id}/proof",
        headers=authorization(token),
    )
    assert proof.status_code == 200
    body = proof.json()
    assert body["task"]["status"] == "settlement_released"
    assert [item["artifact_sha256"] for item in body["submissions"]] == [ARTIFACT_SHA256]
    actions = [item["action"] for item in body["transactions"]]
    assert actions == [
        "escrow_funded",
        "submission_recorded",
        "authorization_activated",
        "settlement_released",
    ]
    for transaction in body["transactions"]:
        assert transaction["status"] == "confirmed"
        assert transaction["network"] == "testnet"
        assert transaction["chain_id"] == "injective-888"
        assert transaction["transaction_hash"].startswith("0x")
        assert transaction["explorer_url"] == (
            "https://testnet.blockscout.injective.network/tx/" + transaction["transaction_hash"]
        )
        assert transaction["confirmed_at"] is not None
    submission_tx = body["transactions"][1]
    assert submission_tx["artifact_sha256"] == ARTIFACT_SHA256
    settlement_tx = body["transactions"][3]
    assert settlement_tx["amount"] == "150.5"
    assert settlement_tx["denom"] == "inj"


def test_authorization_and_settlement_idempotency_survive_task_deadline(
    client: TestClient,
    db_session_factory,
) -> None:
    token = register_and_login(client, "长期幂等用户")
    project_id = create_project(client, token)
    task = create_task(client, token, project_id)
    task_id = str(task["id"])
    submit_artifact(client, token, task_id)

    authorize = client.post(
        f"/api/v1/commercial-tasks/{task_id}/authorize",
        headers={
            **authorization(token),
            "Idempotency-Key": "long-authorization-0001",
        },
    )
    settle = client.post(
        f"/api/v1/commercial-tasks/{task_id}/settle",
        headers={
            **authorization(token),
            "Idempotency-Key": "long-settlement-0001",
        },
    )

    assert authorize.status_code == 200
    assert settle.status_code == 200
    minimum_expiry = task["deadline"]
    with db_session_factory() as db:
        records = list(
            db.scalars(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.route_template.in_(
                        (
                            f"/api/v1/commercial-tasks/{task_id}/authorize",
                            f"/api/v1/commercial-tasks/{task_id}/settle",
                        )
                    )
                )
            )
        )
    assert len(records) == 2
    deadline = datetime.fromisoformat(str(minimum_expiry))
    assert all(record.expires_at >= deadline + timedelta(hours=24) for record in records)


def test_concurrent_authorization_with_same_key_broadcasts_once(
    client: TestClient,
) -> None:
    class BlockingProvider(FakeInjectiveProvider):
        def __init__(self) -> None:
            super().__init__()
            self.authorization_started = Event()
            self.release_authorization = Event()
            self.authorization_broadcasts = 0

        def broadcast(self, memo: str):
            if json.loads(memo)["action"] == "authorization_activated":
                self.authorization_broadcasts += 1
                self.authorization_started.set()
                assert self.release_authorization.wait(timeout=5)
            return super().broadcast(memo)

    provider = BlockingProvider()
    client.app.dependency_overrides[get_injective_provider] = lambda: provider
    token = register_and_login(client, "并发授权用户")
    project_id = create_project(client, token)
    task = create_task(client, token, project_id)
    task_id = str(task["id"])
    submit_artifact(client, token, task_id)
    headers = {
        **authorization(token),
        "Idempotency-Key": "concurrent-authorization-0001",
    }

    with ThreadPoolExecutor(max_workers=1) as executor:
        first_future = executor.submit(
            client.post,
            f"/api/v1/commercial-tasks/{task_id}/authorize",
            headers=headers,
        )
        assert provider.authorization_started.wait(timeout=5)
        duplicate = client.post(
            f"/api/v1/commercial-tasks/{task_id}/authorize",
            headers=headers,
        )
        provider.release_authorization.set()
        first = first_future.result(timeout=5)

    replay = client.post(
        f"/api/v1/commercial-tasks/{task_id}/authorize",
        headers=headers,
    )
    assert first.status_code == 200
    assert duplicate.status_code == 409
    assert duplicate.json()["error"] == {
        "code": "idempotency_request_in_progress",
        "message": "A request with this Idempotency-Key is still in progress",
        "retryable": True,
    }
    assert replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert provider.authorization_broadcasts == 1


def test_out_of_order_actions_return_sequence_conflict(client: TestClient) -> None:
    token = register_and_login(client, "乱序用户")
    project_id = create_project(client, token)
    task = create_task(client, token, project_id)
    task_id = task["id"]

    authorize = client.post(
        f"/api/v1/commercial-tasks/{task_id}/authorize",
        headers=authorization(token),
    )
    assert authorize.status_code == 409
    assert authorize.json() == SEQUENCE_CONFLICT

    settle = client.post(
        f"/api/v1/commercial-tasks/{task_id}/settle",
        headers=authorization(token),
    )
    assert settle.status_code == 409
    assert settle.json() == SEQUENCE_CONFLICT

    proof = client.get(
        f"/api/v1/commercial-tasks/{task_id}/proof",
        headers=authorization(token),
    )
    assert proof.status_code == 200
    assert proof.json()["task"]["status"] == "escrow_funded"
    assert len(proof.json()["transactions"]) == 1


def test_commercial_tasks_are_scoped_per_user(client: TestClient) -> None:
    owner_token = register_and_login(client, "任务归属者")
    intruder_token = register_and_login(client, "越权访问者")
    project_id = create_project(client, owner_token)
    task = create_task(client, owner_token, project_id)

    response = client.get(
        f"/api/v1/commercial-tasks/{task['id']}/proof",
        headers=authorization(intruder_token),
    )

    assert response.status_code == 404
    assert response.json() == TASK_NOT_FOUND


def test_broadcast_failure_keeps_domain_write_and_retries_on_proof(
    client: TestClient,
    fake_injective_provider: FakeInjectiveProvider,
) -> None:
    token = register_and_login(client, "失败重试用户")
    project_id = create_project(client, token)
    fake_injective_provider.fail_next = True

    task = create_task(client, token, project_id)
    assert task["status"] == "escrow_funded"

    proof = client.get(
        f"/api/v1/commercial-tasks/{task['id']}/proof",
        headers=authorization(token),
    )
    assert proof.status_code == 200
    transactions = proof.json()["transactions"]
    assert len(transactions) == 1
    assert transactions[0]["status"] == "confirmed"
    assert transactions[0]["transaction_hash"] is not None


def test_broadcast_failure_is_reported_with_reason_and_retryability(
    client: TestClient,
    fake_injective_provider: FakeInjectiveProvider,
) -> None:
    token = register_and_login(client, "失败可见用户")
    project_id = create_project(client, token)
    fake_injective_provider.fail_next = True

    task = create_task(client, token, project_id)

    fake_injective_provider.fail_next = True
    proof = client.get(
        f"/api/v1/commercial-tasks/{task['id']}/proof",
        headers=authorization(token),
    )
    assert proof.status_code == 200
    transactions = proof.json()["transactions"]
    assert transactions[0]["status"] == "failed"
    assert transactions[0]["failure_reason"] == "fake broadcast failure"
    assert transactions[0]["retryable"] is True
    assert transactions[0]["transaction_hash"] is None


def test_commercial_tasks_require_injective_configuration(
    client: TestClient,
) -> None:
    token = register_and_login(client, "未配置链用户")
    project_id = create_project(client, token)
    client.app.dependency_overrides[get_injective_provider] = lambda: None

    response = client.post(
        "/api/v1/commercial-tasks",
        headers=authorization(token),
        json=task_payload(project_id),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "injective_unavailable"
