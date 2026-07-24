from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

PASSWORD = "correct horse battery staple"
PROJECT_PAYLOAD = {
    "title": "MPS 实测",
    "type": "科技数码",
    "audience": "Mac 用户",
    "summary": "在本地运行语音识别",
}
INSPIRATION_NOT_FOUND = {
    "error": {
        "code": "inspiration_not_found",
        "message": "Inspiration was not found",
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


def create_project(client: TestClient, token: str, title: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/projects",
        headers=authorization(token),
        json={**PROJECT_PAYLOAD, "title": title},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("post", "/api/v1/inspirations", {"json": {"content": "灵感"}}),
        ("get", "/api/v1/inspirations", {}),
        ("get", f"/api/v1/inspirations/{uuid4()}", {}),
        (
            "patch",
            f"/api/v1/inspirations/{uuid4()}",
            {"json": {"title": "标题"}},
        ),
        ("delete", f"/api/v1/inspirations/{uuid4()}", {}),
        (
            "put",
            f"/api/v1/inspirations/{uuid4()}/projects/{uuid4()}",
            {},
        ),
    ],
)
def test_inspiration_routes_require_authentication(
    client: TestClient,
    method: str,
    path: str,
    kwargs: dict[str, object],
) -> None:
    response = client.request(method, path, **kwargs)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session"


def test_inspiration_rest_lifecycle_and_project_views(client: TestClient) -> None:
    token = register_and_login(client, "inspiration-owner")
    first_project = create_project(client, token, "第一期")
    second_project = create_project(client, token, "第二期")

    created_response = client.post(
        "/api/v1/inspirations",
        headers=authorization(token),
        json={
            "title": "  MPS 灵感  ",
            "content": "  对比 MPS 与 CPU  ",
            "project_ids": [first_project["id"], second_project["id"]],
        },
    )

    assert created_response.status_code == 201
    created = created_response.json()
    assert created["title"] == "MPS 灵感"
    assert created["content"] == "对比 MPS 与 CPU"
    assert created["status"] == "inbox"
    assert created["source_type"] == "manual"
    assert created["source_conversation_id"] is None
    assert created["source_message_id"] is None
    assert {project["id"] for project in created["projects"]} == {
        first_project["id"],
        second_project["id"],
    }
    assert set(created) == {
        "id",
        "user_id",
        "title",
        "content",
        "status",
        "source_type",
        "source_conversation_id",
        "source_message_id",
        "projects",
        "created_at",
        "updated_at",
    }

    patched = client.patch(
        f"/api/v1/inspirations/{created['id']}",
        headers=authorization(token),
        json={
            "status": "developing",
            "project_ids": [first_project["id"]],
        },
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "developing"
    assert [project["id"] for project in patched.json()["projects"]] == [first_project["id"]]

    linked = client.put(
        f"/api/v1/inspirations/{created['id']}/projects/{second_project['id']}",
        headers=authorization(token),
    )
    assert linked.status_code == 204
    unlinked = client.delete(
        f"/api/v1/inspirations/{created['id']}/projects/{second_project['id']}",
        headers=authorization(token),
    )
    assert unlinked.status_code == 204

    project_detail = client.get(
        f"/api/v1/projects/{first_project['id']}",
        headers=authorization(token),
    )
    assert project_detail.status_code == 200
    assert project_detail.json()["inspiration_count"] == 1
    project_inspirations = client.get(
        f"/api/v1/projects/{first_project['id']}/inspirations",
        headers=authorization(token),
    )
    assert project_inspirations.status_code == 200
    assert project_inspirations.json()["total"] == 1
    assert project_inspirations.json()["items"][0]["id"] == created["id"]

    deleted = client.delete(
        f"/api/v1/inspirations/{created['id']}",
        headers=authorization(token),
    )
    assert deleted.status_code == 204
    assert (
        client.get(
            f"/api/v1/inspirations/{created['id']}",
            headers=authorization(token),
        ).json()
        == INSPIRATION_NOT_FOUND
    )


def test_inspiration_list_filters_searches_and_paginates(client: TestClient) -> None:
    token = register_and_login(client, "inspiration-list")
    project = create_project(client, token, "系列项目")
    first = client.post(
        "/api/v1/inspirations",
        headers=authorization(token),
        json={
            "title": "本地转写",
            "content": "中文关键词",
            "source_type": "voice",
            "project_ids": [project["id"]],
        },
    ).json()
    assert (
        client.patch(
            f"/api/v1/inspirations/{first['id']}",
            headers=authorization(token),
            json={"status": "developing"},
        ).status_code
        == 200
    )
    client.post(
        "/api/v1/inspirations",
        headers=authorization(token),
        json={"content": "普通收件箱"},
    )

    response = client.get(
        "/api/v1/inspirations",
        headers=authorization(token),
        params={
            "project_id": project["id"],
            "status": "developing",
            "source_type": "voice",
            "query": "中文",
            "sort_by": "created_at",
            "sort_order": "asc",
            "limit": 1,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == first["id"]


def test_project_delete_returns_orphan_impact_then_accepts_confirmed_cascade(
    client: TestClient,
) -> None:
    token = register_and_login(client, "inspiration-cascade")
    project = create_project(client, token, "待删除项目")
    inspiration = client.post(
        "/api/v1/inspirations",
        headers=authorization(token),
        json={
            "title": "孤立候选",
            "content": "只有一个项目关联",
            "project_ids": [project["id"]],
        },
    ).json()

    blocked = client.delete(
        f"/api/v1/projects/{project['id']}",
        headers=authorization(token),
    )

    assert blocked.status_code == 409
    assert blocked.json() == {
        "error": {
            "code": "orphaned_inspirations_confirmation_required",
            "message": "Deleting this resource would orphan 1 inspiration(s)",
            "details": [
                {"id": inspiration["id"], "title": "孤立候选"},
            ],
        }
    }
    confirmed = client.delete(
        f"/api/v1/projects/{project['id']}",
        headers=authorization(token),
        params={"delete_orphan_inspirations": True},
    )
    assert confirmed.status_code == 204
    assert (
        client.get(
            f"/api/v1/inspirations/{inspiration['id']}",
            headers=authorization(token),
        ).json()
        == INSPIRATION_NOT_FOUND
    )


def test_inspiration_cross_user_resources_are_not_disclosed(
    client: TestClient,
) -> None:
    owner_token = register_and_login(client, "inspiration-private-owner")
    other_token = register_and_login(client, "inspiration-private-other")
    project = create_project(client, owner_token, "私有项目")
    inspiration = client.post(
        "/api/v1/inspirations",
        headers=authorization(owner_token),
        json={"content": "私有灵感", "project_ids": [project["id"]]},
    ).json()

    for target in (inspiration["id"], uuid4()):
        assert (
            client.get(
                f"/api/v1/inspirations/{target}",
                headers=authorization(other_token),
            ).json()
            == INSPIRATION_NOT_FOUND
        )
        assert (
            client.patch(
                f"/api/v1/inspirations/{target}",
                headers=authorization(other_token),
                json={"title": "越权"},
            ).json()
            == INSPIRATION_NOT_FOUND
        )
        assert (
            client.delete(
                f"/api/v1/inspirations/{target}",
                headers=authorization(other_token),
            ).json()
            == INSPIRATION_NOT_FOUND
        )

    foreign_link = client.post(
        "/api/v1/inspirations",
        headers=authorization(other_token),
        json={"content": "越权关联", "project_ids": [project["id"]]},
    )
    assert foreign_link.status_code == 404
    assert foreign_link.json()["error"]["code"] == "project_not_found"


@pytest.mark.parametrize(
    "payload",
    [
        {"content": " "},
        {"content": "正文", "source_type": "agent"},
        {"content": "正文", "status": "unknown"},
        {"content": "正文", "unexpected": True},
        {"content": "正文", "project_ids": [str(uuid4())] * 2},
    ],
)
def test_inspiration_create_rejects_invalid_payloads(
    client: TestClient,
    payload: dict[str, object],
) -> None:
    token = register_and_login(client, f"invalid-{str(uuid4())[:8]}")

    response = client.post(
        "/api/v1/inspirations",
        headers=authorization(token),
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_openapi_exposes_inspiration_resources(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert set(paths["/api/v1/inspirations"]) >= {"get", "post"}
    assert set(paths["/api/v1/inspirations/{inspiration_id}"]) >= {
        "get",
        "patch",
        "delete",
    }
    assert set(paths["/api/v1/inspirations/{inspiration_id}/projects/{project_id}"]) >= {
        "put",
        "delete",
    }
    assert "get" in paths["/api/v1/projects/{project_id}/inspirations"]
    project_delete = paths["/api/v1/projects/{project_id}"]["delete"]
    assert project_delete["responses"]["409"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ResourceImpactErrorResponse")
    conversation_delete = paths["/api/v1/conversations/{conversation_id}"]["delete"]
    assert conversation_delete["responses"]["409"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ResourceImpactErrorResponse")
