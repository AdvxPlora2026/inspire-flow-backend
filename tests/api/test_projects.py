from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.data.models.project import Project
from inspire_flow_backend.services.agent.runtime import AgentRuntime

PASSWORD = "correct horse battery staple"
PROJECT_PAYLOAD = {
    "title": "  MPS 实测  ",
    "type": " 科技数码 ",
    "audience": " Mac 用户 ",
    "summary": " 在本地运行语音识别 ",
}
NOT_FOUND = {
    "error": {
        "code": "project_not_found",
        "message": "Project was not found",
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
    return {"Authorization": f"Bearer {token}"}


def create_project(client: TestClient, token: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/projects",
        headers=authorization(token),
        json=PROJECT_PAYLOAD,
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("post", "/api/v1/projects", {"json": PROJECT_PAYLOAD}),
        ("get", "/api/v1/projects", {}),
        ("get", f"/api/v1/projects/{uuid4()}", {}),
        (
            "patch",
            f"/api/v1/projects/{uuid4()}",
            {"json": {"title": "new"}},
        ),
        ("delete", f"/api/v1/projects/{uuid4()}", {}),
    ],
)
def test_project_crud_requires_authentication(
    client: TestClient,
    method: str,
    path: str,
    kwargs: dict[str, object],
) -> None:
    response = client.request(method, path, **kwargs)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session"


def test_project_lifecycle_and_normalized_public_shape(client: TestClient) -> None:
    token = register_and_login(client, "project-owner")

    created = create_project(client, token)

    project_id = UUID(str(created["id"]))
    assert project_id.version == 4
    assert created["title"] == "MPS 实测"
    assert created["type"] == "科技数码"
    assert created["audience"] == "Mac 用户"
    assert created["summary"] == "在本地运行语音识别"
    assert created["icon_url"] is None
    assert set(created) == {
        "id",
        "user_id",
        "title",
        "type",
        "audience",
        "summary",
        "icon_url",
        "created_at",
        "updated_at",
    }

    read = client.get(
        f"/api/v1/projects/{project_id}",
        headers=authorization(token),
    )
    assert read.status_code == 200
    assert read.json() == created

    patched = client.patch(
        f"/api/v1/projects/{project_id}",
        headers=authorization(token),
        json={"title": "MPS 与 CUDA 对比", "summary": "加入性能数据"},
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "MPS 与 CUDA 对比"
    assert patched.json()["summary"] == "加入性能数据"

    deleted = client.delete(
        f"/api/v1/projects/{project_id}",
        headers=authorization(token),
    )
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert (
        client.get(
            f"/api/v1/projects/{project_id}",
            headers=authorization(token),
        ).json()
        == NOT_FOUND
    )


def test_lists_only_owned_projects_with_pagination(client: TestClient) -> None:
    owner_token = register_and_login(client, "list-owner")
    other_token = register_and_login(client, "list-other")
    first = create_project(client, owner_token)
    second_response = client.post(
        "/api/v1/projects",
        headers=authorization(owner_token),
        json={**PROJECT_PAYLOAD, "title": "第二个项目"},
    )
    assert second_response.status_code == 201
    create_project(client, other_token)

    response = client.get(
        "/api/v1/projects?limit=1&offset=0",
        headers=authorization(owner_token),
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [second_response.json()],
        "total": 2,
        "limit": 1,
        "offset": 0,
    }
    next_page = client.get(
        "/api/v1/projects?limit=1&offset=1",
        headers=authorization(owner_token),
    )
    assert next_page.json()["items"] == [first]


def test_project_icon_can_be_created_updated_and_cleared(client: TestClient) -> None:
    token = register_and_login(client, "project-icon-owner")
    response = client.post(
        "/api/v1/projects",
        headers=authorization(token),
        json={
            **PROJECT_PAYLOAD,
            "icon_url": "https://cdn.example.com/project.png",
        },
    )
    assert response.status_code == 201
    assert response.json()["icon_url"] == "https://cdn.example.com/project.png"
    project_id = response.json()["id"]

    updated = client.patch(
        f"/api/v1/projects/{project_id}",
        headers=authorization(token),
        json={"icon_url": "https://cdn.example.com/new-project.png"},
    )
    assert updated.status_code == 200
    assert updated.json()["icon_url"] == "https://cdn.example.com/new-project.png"

    cleared = client.patch(
        f"/api/v1/projects/{project_id}",
        headers=authorization(token),
        json={"icon_url": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["icon_url"] is None


def test_cross_user_and_unknown_project_share_not_found_response(
    client: TestClient,
) -> None:
    owner_token = register_and_login(client, "private-owner")
    other_token = register_and_login(client, "private-other")
    project_id = create_project(client, owner_token)["id"]
    unknown_id = uuid4()

    for target in (project_id, unknown_id):
        assert (
            client.get(
                f"/api/v1/projects/{target}",
                headers=authorization(other_token),
            ).json()
            == NOT_FOUND
        )
        assert (
            client.patch(
                f"/api/v1/projects/{target}",
                headers=authorization(other_token),
                json={"title": "越权修改"},
            ).json()
            == NOT_FOUND
        )
        assert (
            client.delete(
                f"/api/v1/projects/{target}",
                headers=authorization(other_token),
            ).json()
            == NOT_FOUND
        )


@pytest.mark.parametrize(
    ("path", "method", "kwargs"),
    [
        ("/api/v1/projects", "post", {"json": {**PROJECT_PAYLOAD, "title": " "}}),
        (
            "/api/v1/projects",
            "post",
            {"json": {**PROJECT_PAYLOAD, "unexpected": True}},
        ),
        (
            "/api/v1/projects",
            "post",
            {"json": {**PROJECT_PAYLOAD, "icon_url": "not-a-url"}},
        ),
        (f"/api/v1/projects/{uuid4()}", "patch", {"json": {}}),
        (f"/api/v1/projects/{uuid4()}", "patch", {"json": {"title": None}}),
    ],
)
def test_rejects_invalid_project_payloads(
    client: TestClient,
    path: str,
    method: str,
    kwargs: dict[str, object],
) -> None:
    token = register_and_login(client, f"invalid-{uuid4()}")

    response = client.request(
        method,
        path,
        headers=authorization(token),
        **kwargs,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_openapi_exposes_project_crud(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert set(paths["/api/v1/projects"]) >= {"get", "post"}
    assert set(paths["/api/v1/projects/{project_id}"]) >= {
        "get",
        "patch",
        "delete",
    }


def test_generates_unsaved_project_draft(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    fake_agent_runtime: AgentRuntime,
) -> None:
    token = register_and_login(client, "draft-owner")

    response = client.post(
        "/api/v1/projects/drafts",
        headers=authorization(token),
        json={"description": "  做一期本地语音识别视频  "},
    )

    assert response.status_code == 200
    assert response.json() == {
        "title": "本地语音识别实测",
        "type": "科技数码",
        "audience": "希望保护隐私的创作者",
        "summary": "对比本地部署的速度和效果",
        "icon_url": None,
    }
    generator = fake_agent_runtime.project_draft_generator
    assert generator.descriptions == ["做一期本地语音识别视频"]
    with db_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Project)) == 0


def test_project_draft_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/api/v1/projects/drafts",
        json={"description": "做一期本地语音识别视频"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session"


def test_project_draft_maps_provider_failure(
    client: TestClient,
    fake_agent_runtime: AgentRuntime,
) -> None:
    token = register_and_login(client, "draft-failure")
    fake_agent_runtime.project_draft_generator.fail_next = True

    response = client.post(
        "/api/v1/projects/drafts",
        headers=authorization(token),
        json={"description": "做一期本地语音识别视频"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "agent_run_failed"


def test_openapi_exposes_project_draft(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "post" in paths["/api/v1/projects/drafts"]
