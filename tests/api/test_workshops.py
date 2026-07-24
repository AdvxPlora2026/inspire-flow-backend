from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

PASSWORD = "correct horse battery staple"


def register_and_login(client: TestClient, nickname: str) -> tuple[str, str]:
    registered = client.post(
        "/api/v1/users",
        json={"nickname": nickname, "password": PASSWORD},
    )
    assert registered.status_code == 201
    login = client.post(
        "/api/v1/sessions",
        json={"nickname": nickname, "password": PASSWORD},
    )
    assert login.status_code == 201
    return login.json()["access_token"], registered.json()["id"]


def auth(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": f"test-{uuid4()}",
    }


def create_brand_with_member(
    client: TestClient,
    owner_token: str,
    member_token: str,
    member_nickname: str,
) -> str:
    brand = client.post(
        "/api/v1/brands",
        headers=auth(owner_token),
        json={"name": "Discovery Brand"},
    ).json()
    invitation = client.post(
        f"/api/v1/brands/{brand['id']}/invitations",
        headers=auth(owner_token),
        json={"nickname": member_nickname},
    ).json()
    assert (
        client.post(
            f"/api/v1/users/me/brand-invitations/{invitation['id']}/accept",
            headers=auth(member_token),
        ).status_code
        == 200
    )
    return brand["id"]


def test_workshop_publish_and_visibility_matrix(client: TestClient) -> None:
    creator_token, creator_id = register_and_login(client, "workshop-creator")
    brand_owner_token, _ = register_and_login(client, "workshop-brand-owner")
    brand_member_token, _ = register_and_login(client, "workshop-brand-member")
    ordinary_token, _ = register_and_login(client, "ordinary-viewer")
    brand_id = create_brand_with_member(
        client,
        brand_owner_token,
        brand_member_token,
        "workshop-brand-member",
    )

    patched = client.patch(
        "/api/v1/users/me/workshop",
        headers=auth(creator_token),
        json={
            "title": "公开标题",
            "title_visibility": "workshop_public",
            "bio": "仅自己可见",
            "bio_visibility": "private",
            "creator_identity": "科技区 UP 主",
            "creator_identity_visibility": "brands_only",
            "collaboration_preferences": "接受深度测评",
            "collaboration_preferences_visibility": "authorized_brands",
        },
    )
    assert patched.status_code == 200

    owner_preview = client.get(
        "/api/v1/users/me/workshop/preview?audience=owner",
        headers=auth(creator_token),
    )
    assert owner_preview.status_code == 200
    assert owner_preview.json()["bio"] == "仅自己可见"

    published = client.post(
        "/api/v1/users/me/workshop/publish",
        headers=auth(creator_token),
    )
    assert published.status_code == 200

    public = client.get(f"/api/v1/workshops/{creator_id}")
    assert public.status_code == 200
    assert public.json()["title"] == "公开标题"
    assert public.json()["bio"] is None
    assert public.json()["creator_identity"] is None
    assert public.json()["collaboration_preferences"] is None

    invalid_session = client.get(
        f"/api/v1/workshops/{creator_id}",
        headers={"Authorization": "Bearer invalid-session"},
    )
    assert invalid_session.status_code == 401
    assert invalid_session.json()["error"]["code"] == "invalid_session"

    ordinary = client.get(
        f"/api/v1/workshops/{creator_id}",
        headers=auth(ordinary_token),
    )
    assert ordinary.status_code == 200
    assert ordinary.json()["creator_identity"] is None

    brand_view = client.get(
        f"/api/v1/workshops/{creator_id}?brand_id={brand_id}",
        headers=auth(brand_member_token),
    )
    assert brand_view.status_code == 200
    assert brand_view.json()["creator_identity"] == "科技区 UP 主"
    assert brand_view.json()["collaboration_preferences"] is None

    granted = client.put(
        f"/api/v1/users/me/workshop/brand-authorizations/{brand_id}",
        headers=auth(creator_token),
    )
    assert granted.status_code == 200

    authorized = client.get(
        f"/api/v1/workshops/{creator_id}?brand_id={brand_id}",
        headers=auth(brand_owner_token),
    )
    assert authorized.status_code == 200
    assert authorized.json()["creator_identity"] == "科技区 UP 主"
    assert authorized.json()["collaboration_preferences"] == "接受深度测评"


def test_draft_changes_do_not_change_publication_and_withdraw_hides_it(
    client: TestClient,
) -> None:
    token, creator_id = register_and_login(client, "snapshot-creator")
    assert (
        client.patch(
            "/api/v1/users/me/workshop",
            headers=auth(token),
            json={"title": "第一版", "title_visibility": "workshop_public"},
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
    assert (
        client.patch(
            "/api/v1/users/me/workshop",
            headers=auth(token),
            json={"title": "草稿第二版"},
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/workshops/{creator_id}").json()["title"] == "第一版"

    withdrawn = client.post(
        "/api/v1/users/me/workshop/withdraw",
        headers=auth(token),
    )
    assert withdrawn.status_code == 200
    hidden = client.get(f"/api/v1/workshops/{creator_id}")
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "workshop_not_published"


def test_workshop_social_contact_and_project_snapshots(
    client: TestClient,
    db_session_factory,
) -> None:
    creator_token, creator_id = register_and_login(client, "portfolio-creator")
    brand_token, _ = register_and_login(client, "portfolio-brand")
    brand_id = client.post(
        "/api/v1/brands",
        headers=auth(brand_token),
        json={"name": "Portfolio Brand"},
    ).json()["id"]

    project = client.post(
        "/api/v1/projects",
        headers=auth(creator_token),
        json={
            "title": "原项目标题",
            "type": "科技",
            "audience": "开发者",
            "summary": "项目摘要",
        },
    ).json()
    social = client.post(
        "/api/v1/users/me/workshop/social-accounts",
        headers=auth(creator_token),
        json={
            "platform": "bilibili",
            "handle": "InspireFlow",
            "profile_url": "https://space.bilibili.com/123",
            "visibility": "workshop_public",
        },
    )
    assert social.status_code == 201
    contact = client.post(
        "/api/v1/users/me/workshop/contacts",
        headers=auth(creator_token),
        json={
            "type": "email",
            "label": "商务邮箱",
            "value": "Business@Example.COM",
            "visibility": "authorized_brands",
        },
    )
    assert contact.status_code == 201
    assert contact.json()["value"] == "Business@example.com"

    invalid_contact = client.post(
        "/api/v1/users/me/workshop/contacts",
        headers=auth(creator_token),
        json={
            "type": "email",
            "value": "hidden@example.com",
            "visibility": "brands_only",
        },
    )
    assert invalid_contact.status_code == 422

    selection = client.put(
        f"/api/v1/users/me/workshop/projects/{project['id']}",
        headers=auth(creator_token),
        json={"visibility": "workshop_public", "sort_order": 1},
    )
    assert selection.status_code == 200
    assert selection.json()["title"] == "原项目标题"

    assert (
        client.post(
            "/api/v1/users/me/workshop/publish",
            headers=auth(creator_token),
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/v1/users/me/workshop/brand-authorizations/{brand_id}",
            headers=auth(creator_token),
        ).status_code
        == 200
    )

    assert (
        client.patch(
            f"/api/v1/projects/{project['id']}",
            headers=auth(creator_token),
            json={"title": "已修改的内部标题"},
        ).status_code
        == 200
    )
    public = client.get(f"/api/v1/workshops/{creator_id}").json()
    assert public["social_accounts"][0]["handle"] == "InspireFlow"
    assert public["contacts"] == []
    assert public["projects"][0]["title"] == "原项目标题"

    authorized = client.get(
        f"/api/v1/workshops/{creator_id}?brand_id={brand_id}",
        headers=auth(brand_token),
    ).json()
    assert authorized["contacts"][0]["value"] == "Business@example.com"
    assert authorized["contacts"][0]["action_uri"] == "mailto:Business@example.com"
    assert "visibility" not in authorized["contacts"][0] or (
        authorized["contacts"][0]["visibility"] is None
    )

    revoked = client.delete(
        f"/api/v1/users/me/workshop/brand-authorizations/{brand_id}",
        headers=auth(creator_token),
    )
    assert revoked.status_code == 204
    after_revocation = client.get(
        f"/api/v1/workshops/{creator_id}?brand_id={brand_id}",
        headers=auth(brand_token),
    )
    assert after_revocation.status_code == 200
    assert after_revocation.json()["contacts"] == []

    with db_session_factory() as db:
        stored = db.execute(text("SELECT value_ciphertext FROM workshop_contacts")).scalar_one()
    assert "Business@example.com" not in stored
