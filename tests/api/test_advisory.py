from uuid import uuid4

from fastapi.testclient import TestClient

from inspire_flow_backend.services.agent.runtime import AgentRuntime

PASSWORD = "correct horse battery staple"


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


def auth(token: str, key: str | None = None) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": key or f"advisory-{uuid4()}",
    }


def create_brand(client: TestClient, token: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/brands",
        headers=auth(token),
        json={
            "name": "星河咖啡",
            "description": "面向年轻职场人的即饮咖啡",
            "website_url": "https://brand.example.com",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_project(client: TestClient, token: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/projects",
        headers=auth(token),
        json={
            "title": "冷萃新品内容",
            "type": "品牌合作",
            "audience": "年轻职场人",
            "summary": "测试不同职场场景",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_advisory_route_requires_authentication_and_valid_payload(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/brands/{uuid4()}/advisory-reports",
        headers={"Idempotency-Key": "advisory-no-auth"},
        json={"project_brief": "brief"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session"

    token = register_and_login(client, "advisory-validation")
    brand = create_brand(client, token)
    invalid = client.post(
        f"/api/v1/brands/{brand['id']}/advisory-reports",
        headers=auth(token),
        json={"project_brief": "brief", "lookback_days": 31},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"


def test_advisory_route_returns_typed_report_with_owned_project(
    client: TestClient,
    fake_agent_runtime: AgentRuntime,
) -> None:
    token = register_and_login(client, "advisory-owner")
    brand = create_brand(client, token)
    project = create_project(client, token)

    response = client.post(
        f"/api/v1/brands/{brand['id']}/advisory-reports",
        headers=auth(token),
        json={
            "project_brief": "  重点测试上午工作场景  ",
            "project_id": project["id"],
            "market": "中国大陆",
            "focus_topics": ["职场效率"],
        },
    )

    assert response.status_code == 200
    report = response.json()
    assert report["evidence_status"] == "insufficient"
    assert report["brand"]["id"] == brand["id"]
    assert report["project_context"]["brief"] == "重点测试上午工作场景"
    assert report["project_context"]["linked_project"]["id"] == project["id"]
    assert report["recommendations"] == []
    assert report["next_research_steps"]
    assert fake_agent_runtime.brand_advisor.contexts[-1].market == "中国大陆"


def test_advisory_route_hides_non_member_brand_and_foreign_project(
    client: TestClient,
) -> None:
    owner_token = register_and_login(client, "advisory-brand-owner")
    other_token = register_and_login(client, "advisory-other")
    brand = create_brand(client, owner_token)
    project = create_project(client, owner_token)

    hidden_brand = client.post(
        f"/api/v1/brands/{brand['id']}/advisory-reports",
        headers=auth(other_token),
        json={"project_brief": "brief"},
    )
    assert hidden_brand.status_code == 404
    assert hidden_brand.json()["error"]["code"] == "brand_not_found"

    own_brand = create_brand(client, other_token)
    hidden_project = client.post(
        f"/api/v1/brands/{own_brand['id']}/advisory-reports",
        headers=auth(other_token),
        json={"project_brief": "brief", "project_id": project["id"]},
    )
    assert hidden_project.status_code == 404
    assert hidden_project.json()["error"]["code"] == "project_not_found"


def test_advisory_route_replays_idempotent_response_without_second_model_run(
    client: TestClient,
    fake_agent_runtime: AgentRuntime,
) -> None:
    token = register_and_login(client, "advisory-replay")
    brand = create_brand(client, token)
    headers = auth(token, "advisory-replay-key-0001")
    payload = {"project_brief": "为冷萃新品分析热点"}

    first = client.post(
        f"/api/v1/brands/{brand['id']}/advisory-reports",
        headers=headers,
        json=payload,
    )
    second = client.post(
        f"/api/v1/brands/{brand['id']}/advisory-reports",
        headers=headers,
        json=payload,
    )

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert second.headers["Idempotency-Replayed"] == "true"
    assert len(fake_agent_runtime.brand_advisor.contexts) == 1


def test_advisory_route_maps_model_failure_to_502(
    client: TestClient,
    fake_agent_runtime: AgentRuntime,
) -> None:
    token = register_and_login(client, "advisory-failure")
    brand = create_brand(client, token)
    fake_agent_runtime.brand_advisor.fail_next = True

    response = client.post(
        f"/api/v1/brands/{brand['id']}/advisory-reports",
        headers=auth(token),
        json={"project_brief": "brief"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "agent_run_failed"


def test_openapi_declares_advisory_contract(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    operation = document["paths"]["/api/v1/brands/{brand_id}/advisory-reports"]["post"]

    assert operation["security"]
    assert {"200", "401", "404", "422", "502", "503"} <= set(operation["responses"])
    assert any(
        parameter["name"] == "Idempotency-Key" and parameter["in"] == "header"
        for parameter in operation["parameters"]
    )
