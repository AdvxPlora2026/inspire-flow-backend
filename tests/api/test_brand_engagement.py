from datetime import timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.workshop import WorkshopPublication

PASSWORD = "correct horse battery staple"


def register_and_login(client: TestClient, nickname: str) -> tuple[str, str]:
    user = client.post(
        "/api/v1/users",
        json={"nickname": nickname, "password": PASSWORD},
    ).json()
    login = client.post(
        "/api/v1/sessions",
        json={"nickname": nickname, "password": PASSWORD},
    )
    assert login.status_code == 201
    return login.json()["access_token"], user["id"]


def auth(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": f"test-{uuid4()}",
    }


def create_published_creator(
    client: TestClient,
    nickname: str,
    *,
    title: str,
    bio: str,
) -> tuple[str, str]:
    token, creator_id = register_and_login(client, nickname)
    assert (
        client.patch(
            "/api/v1/users/me/workshop",
            headers=auth(token),
            json={
                "title": title,
                "title_visibility": "workshop_public",
                "bio": bio,
                "bio_visibility": "private",
                "creator_identity": "科技创作者",
                "creator_identity_visibility": "brands_only",
                "content_focus": ["AI", "效率工具"],
                "content_focus_visibility": "brands_only",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/users/me/workshop/publish",
            headers=auth(token),
        ).status_code
        == 200
    )
    return token, creator_id


def test_discovery_does_not_match_hidden_fields(client: TestClient) -> None:
    _, creator_id = create_published_creator(
        client,
        "discovery-creator",
        title="公开的效率栏目",
        bio="绝密火星合作计划",
    )
    brand_token, _ = register_and_login(client, "discovering-brand")
    brand_id = client.post(
        "/api/v1/brands",
        headers=auth(brand_token),
        json={"name": "Discovery Org"},
    ).json()["id"]

    visible = client.get(
        f"/api/v1/brands/{brand_id}/creator-discovery",
        headers=auth(brand_token),
        params={"query": "效率", "content_focus": "AI"},
    )
    assert visible.status_code == 200
    assert [item["creator_id"] for item in visible.json()["items"]] == [creator_id]
    assert visible.json()["items"][0]["bio"] is None
    assert visible.json()["items"][0]["creator_identity"] == "科技创作者"

    hidden = client.get(
        f"/api/v1/brands/{brand_id}/creator-discovery",
        headers=auth(brand_token),
        params={"query": "火星合作"},
    )
    assert hidden.status_code == 200
    assert hidden.json()["total"] == 0


def test_follow_interest_and_creator_inbox_lifecycle(client: TestClient) -> None:
    creator_token, creator_id = create_published_creator(
        client,
        "inbox-creator",
        title="合作橱窗",
        bio="内部简介",
    )
    brand_token, _ = register_and_login(client, "inbox-brand")
    brand_id = client.post(
        "/api/v1/brands",
        headers=auth(brand_token),
        json={"name": "Inbox Org"},
    ).json()["id"]

    followed = client.put(
        f"/api/v1/brands/{brand_id}/follows/{creator_id}",
        headers=auth(brand_token),
    )
    assert followed.status_code == 200
    follow_id = followed.json()["id"]
    assert followed.json()["status"] == "active"

    inbox = client.get("/api/v1/users/me/brand-inbox", headers=auth(creator_token))
    assert inbox.status_code == 200
    follow_item = inbox.json()["items"][0]
    assert follow_item["kind"] == "follow"
    assert follow_item["is_read"] is False

    assert (
        client.patch(
            f"/api/v1/users/me/brand-inbox/{follow_item['id']}",
            headers=auth(creator_token),
            json={"is_read": True},
        ).status_code
        == 200
    )
    assert (
        client.delete(
            f"/api/v1/brands/{brand_id}/follows/{creator_id}",
            headers=auth(brand_token),
        ).status_code
        == 204
    )
    refollowed = client.put(
        f"/api/v1/brands/{brand_id}/follows/{creator_id}",
        headers=auth(brand_token),
    )
    assert refollowed.json()["id"] == follow_id
    inbox = client.get("/api/v1/users/me/brand-inbox", headers=auth(creator_token))
    assert inbox.json()["items"][0]["is_read"] is False

    interest = client.post(
        f"/api/v1/brands/{brand_id}/interests",
        headers=auth(brand_token),
        json={"creator_id": creator_id, "message": "想合作一期 AI 工具视频"},
    )
    assert interest.status_code == 201
    duplicate = client.post(
        f"/api/v1/brands/{brand_id}/interests",
        headers=auth(brand_token),
        json={"creator_id": creator_id, "message": "不同文字也返回当前待处理意向"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == interest.json()["id"]

    accepted = client.patch(
        f"/api/v1/users/me/brand-interests/{interest.json()['id']}",
        headers=auth(creator_token),
        json={"status": "accepted"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"

    authorizations = client.get(
        "/api/v1/users/me/workshop/brand-authorizations",
        headers=auth(creator_token),
    )
    assert authorizations.status_code == 200
    assert authorizations.json() == []

    marked = client.post(
        "/api/v1/users/me/brand-inbox/mark-read",
        headers=auth(creator_token),
        json={},
    )
    assert marked.status_code == 200
    assert all(item["is_read"] for item in marked.json()["items"])


def test_discovery_uses_the_requested_sort_field(
    client: TestClient,
    db_session_factory,
) -> None:
    _, first_creator_id = create_published_creator(
        client,
        "sort-first-creator",
        title="第一个橱窗",
        bio="内部简介",
    )
    _, second_creator_id = create_published_creator(
        client,
        "sort-second-creator",
        title="第二个橱窗",
        bio="内部简介",
    )
    brand_token, _ = register_and_login(client, "sorting-brand")
    brand_id = client.post(
        "/api/v1/brands",
        headers=auth(brand_token),
        json={"name": "Sorting Org"},
    ).json()["id"]

    now = utc_now()
    with db_session_factory() as db:
        first = db.scalar(
            select(WorkshopPublication).where(
                WorkshopPublication.workshop_user_id == UUID(first_creator_id)
            )
        )
        second = db.scalar(
            select(WorkshopPublication).where(
                WorkshopPublication.workshop_user_id == UUID(second_creator_id)
            )
        )
        assert first is not None
        assert second is not None
        first.published_at = now + timedelta(minutes=2)
        first.updated_at = now
        second.published_at = now
        second.updated_at = now + timedelta(minutes=2)
        db.commit()

    by_publication = client.get(
        f"/api/v1/brands/{brand_id}/creator-discovery",
        headers=auth(brand_token),
        params={"sort_by": "published_at", "sort_order": "desc"},
    )
    by_update = client.get(
        f"/api/v1/brands/{brand_id}/creator-discovery",
        headers=auth(brand_token),
        params={"sort_by": "updated_at", "sort_order": "desc"},
    )

    assert [item["creator_id"] for item in by_publication.json()["items"]] == [
        first_creator_id,
        second_creator_id,
    ]
    assert [item["creator_id"] for item in by_update.json()["items"]] == [
        second_creator_id,
        first_creator_id,
    ]
