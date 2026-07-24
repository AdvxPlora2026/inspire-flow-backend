"""End-to-end real chain verification against a running server.

Drives the public HTTP API: register -> login -> create project ->
create commercial task (real Injective broadcast) -> poll proof until the
chain transaction is confirmed. Run with the server up on 127.0.0.1:8000:

    uv run uvicorn inspire_flow_backend.main:app --host 127.0.0.1 --port 8000
    uv run python scripts/verify_chain.py
"""

import time
import uuid

import httpx

BASE = "http://127.0.0.1:8000/api/v1"


def _key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=60.0)

    health = client.get("/health").json()
    print("health:", health)
    if health["services"]["injective"] != "ok":
        raise SystemExit("injective not configured; set APP_INJECTIVE_PRIVATE_KEY")

    nickname = f"chain-demo-{uuid.uuid4().hex[:8]}"
    password = "demo-password-1234567890"

    client.post("/users", json={"nickname": nickname, "password": password}).raise_for_status()
    token = client.post("/sessions", json={"nickname": nickname, "password": password}).json()[
        "access_token"
    ]
    client.headers["Authorization"] = f"Bearer {token}"
    print("logged in as:", nickname)

    project = client.post(
        "/projects",
        headers=_key(),
        json={
            "title": "链上存证 Demo 项目",
            "type": "科技",
            "audience": "关注 Web3 的创作者",
            "summary": "用于验证 Injective 商业任务链上存证。",
        },
    )
    project.raise_for_status()
    project_id = project.json()["id"]
    print("project:", project_id)

    task = client.post(
        "/commercial-tasks",
        headers=_key(),
        json={
            "project_id": project_id,
            "title": "品牌联名短视频",
            "budget": {"amount": "100", "denom": "inj"},
            "deadline": "2026-08-01T10:00:00Z",
            "splits": [
                {"party_id": "creator", "bps": 7000},
                {"party_id": "platform", "bps": 3000},
            ],
        },
    )
    task.raise_for_status()
    task_id = task.json()["id"]
    print("task:", task_id, "status:", task.json()["status"])

    # Advance the lifecycle so every action produces a chain transaction.
    client.post(
        f"/commercial-tasks/{task_id}/submissions",
        headers=_key(),
        json={
            "artifact_id": str(uuid.uuid4()),
            "artifact_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "delivery_url": "https://example.com/artifacts/final.mp4",
        },
    ).raise_for_status()
    client.post(f"/commercial-tasks/{task_id}/authorize", headers=_key()).raise_for_status()
    client.post(f"/commercial-tasks/{task_id}/settle", headers=_key()).raise_for_status()
    print("lifecycle advanced: escrow -> submission -> authorize -> settle")

    # Poll proof until all transactions leave the broadcast/prepared state.
    deadline = time.time() + 120
    while True:
        proof = client.get(f"/commercial-tasks/{task_id}/proof").json()
        txns = proof["transactions"]
        pending = [t for t in txns if t["status"] in ("prepared", "broadcast")]
        print(
            f"[{time.strftime('%H:%M:%S')}] task={proof['task']['status']} "
            f"txns={[(t['action'], t['status']) for t in txns]}"
        )
        if not pending or time.time() > deadline:
            break
        time.sleep(6)

    print("\n=== final chain transactions ===")
    for t in txns:
        print(f"- action={t['action']} status={t['status']}")
        print(f"  hash={t['transaction_hash']}")
        print(f"  explorer={t['explorer_url']}")
        if t["failure_reason"]:
            print(f"  failure_reason={t['failure_reason']} retryable={t['retryable']}")


if __name__ == "__main__":
    main()
