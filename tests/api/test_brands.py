from uuid import uuid4

from fastapi.testclient import TestClient

PASSWORD = "correct horse battery staple"


def register_and_login(client: TestClient, nickname: str) -> str:
    assert (
        client.post(
            "/api/v1/users",
            json={"nickname": nickname, "password": PASSWORD},
        ).status_code
        == 201
    )
    login = client.post(
        "/api/v1/sessions",
        json={"nickname": nickname, "password": PASSWORD},
    )
    assert login.status_code == 201
    return login.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": f"test-{uuid4()}",
    }


def test_brand_owner_invites_user_who_accepts_membership(client: TestClient) -> None:
    owner_token = register_and_login(client, "brand-owner")
    member_token = register_and_login(client, "brand-member")

    created = client.post(
        "/api/v1/brands",
        headers=auth(owner_token),
        json={
            "name": "Inspire Studio",
            "description": "品牌合作团队",
            "website_url": "https://brand.example.com",
        },
    )
    assert created.status_code == 201
    brand = created.json()
    assert brand["my_role"] == "owner"

    invitation = client.post(
        f"/api/v1/brands/{brand['id']}/invitations",
        headers=auth(owner_token),
        json={"nickname": "brand-member"},
    )
    assert invitation.status_code == 201

    accepted = client.post(
        f"/api/v1/users/me/brand-invitations/{invitation.json()['id']}/accept",
        headers=auth(member_token),
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"

    brands = client.get("/api/v1/brands", headers=auth(member_token))
    assert brands.status_code == 200
    assert brands.json()["items"][0]["my_role"] == "member"

    member_forbidden = client.patch(
        f"/api/v1/brands/{brand['id']}",
        headers=auth(member_token),
        json={"description": "成员不能修改"},
    )
    assert member_forbidden.status_code == 403
    assert member_forbidden.json()["error"]["code"] == "brand_owner_required"

    owner_id = client.get("/api/v1/users/me", headers=auth(owner_token)).json()["id"]
    member_id = client.get("/api/v1/users/me", headers=auth(member_token)).json()["id"]
    promoted = client.patch(
        f"/api/v1/brands/{brand['id']}/members/{member_id}",
        headers=auth(owner_token),
        json={"role": "owner"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "owner"
    transferred = client.patch(
        f"/api/v1/brands/{brand['id']}/members/{owner_id}",
        headers=auth(member_token),
        json={"role": "member"},
    )
    assert transferred.status_code == 200
    assert transferred.json()["role"] == "member"


def test_member_cannot_invite_and_last_owner_cannot_be_removed(
    client: TestClient,
) -> None:
    owner_token = register_and_login(client, "only-owner")
    other_token = register_and_login(client, "other-user")
    brand = client.post(
        "/api/v1/brands",
        headers=auth(owner_token),
        json={"name": "Solo Brand"},
    ).json()

    forbidden = client.post(
        f"/api/v1/brands/{brand['id']}/invitations",
        headers=auth(other_token),
        json={"nickname": "only-owner"},
    )
    assert forbidden.status_code == 404
    assert forbidden.json()["error"]["code"] == "brand_not_found"

    owner_user_id = client.get(
        "/api/v1/users/me",
        headers=auth(owner_token),
    ).json()["id"]
    last_owner = client.delete(
        f"/api/v1/brands/{brand['id']}/members/{owner_user_id}",
        headers=auth(owner_token),
    )
    assert last_owner.status_code == 409
    assert last_owner.json()["error"]["code"] == "brand_last_owner_required"
