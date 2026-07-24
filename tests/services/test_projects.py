from collections.abc import Generator
from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.core.errors import ProjectNotFoundError
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.base import Base
from inspire_flow_backend.data.database import create_database_engine
from inspire_flow_backend.data.model_registry import register_models
from inspire_flow_backend.data.models.project import Project
from inspire_flow_backend.data.models.user import User
from inspire_flow_backend.schemas.projects import (
    ProjectCreate,
    ProjectDraftRequest,
    ProjectUpdate,
)
from inspire_flow_backend.services.projects import (
    create_project,
    delete_project,
    get_project,
    list_projects,
    update_project,
)


@pytest.fixture
def db() -> Generator[Session]:
    register_models()
    engine = create_database_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def add_user(db: Session, nickname: str) -> User:
    now = utc_now()
    user = User(
        id=uuid4(),
        nickname=nickname,
        nickname_key=nickname.casefold(),
        password_hash="test-only-hash",
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    db.commit()
    return user


def project_payload(
    title: str = "MPS 实测",
    icon_url: str | None = None,
) -> ProjectCreate:
    return ProjectCreate(
        title=title,
        type="科技数码",
        audience="Mac 用户",
        summary="在本地运行语音识别",
        icon_url=icon_url,
    )


def test_project_lifecycle_and_user_isolation(db: Session) -> None:
    owner = add_user(db, "owner")
    other = add_user(db, "other")

    created = create_project(
        db,
        owner.id,
        ProjectCreate(
            title="  MPS 实测  ",
            type=" 科技数码 ",
            audience=" Mac 用户 ",
            summary=" 在本地运行语音识别 ",
        ),
    )

    assert created.title == "MPS 实测"
    assert created.type == "科技数码"
    assert created.audience == "Mac 用户"
    assert created.summary == "在本地运行语音识别"
    assert created.icon_url is None
    assert list_projects(db, owner.id, limit=20, offset=0).total == 1
    assert list_projects(db, other.id, limit=20, offset=0).total == 0
    with pytest.raises(ProjectNotFoundError):
        get_project(db, other.id, created.id)

    updated = update_project(
        db,
        owner.id,
        created.id,
        ProjectUpdate(summary=" 补充性能对比 "),
    )
    assert updated.summary == "补充性能对比"

    delete_project(db, owner.id, created.id)
    assert db.get(Project, created.id) is None
    with pytest.raises(ProjectNotFoundError):
        get_project(db, owner.id, created.id)


def test_project_list_is_newest_updated_first_and_paginated(db: Session) -> None:
    owner = add_user(db, "owner")
    first = create_project(db, owner.id, project_payload("第一期"))
    second = create_project(db, owner.id, project_payload("第二期"))

    update_project(
        db,
        owner.id,
        first.id,
        ProjectUpdate(summary="第一期已经更新"),
    )
    page = list_projects(db, owner.id, limit=1, offset=0)
    later_page = list_projects(db, owner.id, limit=1, offset=1)

    assert page.total == 2
    assert page.limit == 1
    assert page.offset == 0
    assert [project.id for project in page.items] == [first.id]
    assert [project.id for project in later_page.items] == [second.id]


def test_project_no_op_update_preserves_updated_at(db: Session) -> None:
    owner = add_user(db, "owner")
    project = create_project(db, owner.id, project_payload())
    before = project.updated_at

    result = update_project(
        db,
        owner.id,
        project.id,
        ProjectUpdate(title=" MPS 实测 "),
    )

    assert result.updated_at == before
    assert result.updated_at <= utc_now() + timedelta(seconds=1)


def test_project_icon_can_be_set_cleared_and_left_unchanged(db: Session) -> None:
    owner = add_user(db, "icon-owner")
    project = create_project(
        db,
        owner.id,
        project_payload(icon_url="https://cdn.example.com/project.png"),
    )

    assert project.icon_url == "https://cdn.example.com/project.png"
    before = project.updated_at
    unchanged = update_project(
        db,
        owner.id,
        project.id,
        ProjectUpdate(icon_url="https://cdn.example.com/project.png"),
    )
    assert unchanged.updated_at == before

    cleared = update_project(
        db,
        owner.id,
        project.id,
        ProjectUpdate(icon_url=None),
    )
    assert cleared.icon_url is None
    assert cleared.updated_at > before


@pytest.mark.parametrize(
    "payload",
    [
        {
            "title": " ",
            "type": "科技数码",
            "audience": "Mac 用户",
            "summary": "简介",
        },
        {
            "title": "标题",
            "type": "x" * 51,
            "audience": "Mac 用户",
            "summary": "简介",
        },
        {
            "title": "标题",
            "type": "科技数码",
            "audience": "x" * 501,
            "summary": "简介",
        },
        {
            "title": "标题",
            "type": "科技数码",
            "audience": "Mac 用户",
            "summary": "x" * 2001,
        },
        {
            "title": "标题",
            "type": "科技数码",
            "audience": "Mac 用户",
            "summary": "简介",
            "unknown": "forbidden",
        },
        {
            "title": 123,
            "type": "科技数码",
            "audience": "Mac 用户",
            "summary": "简介",
        },
        {
            "title": "标题",
            "type": "科技数码",
            "audience": "Mac 用户",
            "summary": "简介",
            "icon_url": "not-a-url",
        },
    ],
)
def test_project_create_rejects_invalid_fields(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ProjectCreate.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": None},
        {"type": "  "},
        {"icon_url": "not-a-url"},
        {"unknown": "forbidden"},
    ],
)
def test_project_update_rejects_empty_null_or_invalid_fields(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ProjectUpdate.model_validate(payload)


@pytest.mark.parametrize("description", ["", "   ", "x" * 4001])
def test_project_draft_request_rejects_invalid_description(description: str) -> None:
    with pytest.raises(ValidationError):
        ProjectDraftRequest(description=description)


def test_project_draft_request_normalizes_description() -> None:
    payload = ProjectDraftRequest(description="  做一期本地语音识别视频  ")

    assert payload.description == "做一期本地语音识别视频"


def test_project_bounds_apply_after_whitespace_normalization() -> None:
    payload = ProjectCreate(
        title=f"  {'x' * 120}  ",
        type=f"  {'x' * 50}  ",
        audience=f"  {'x' * 500}  ",
        summary=f"  {'x' * 2000}  ",
    )
    draft_request = ProjectDraftRequest(description=f"  {'x' * 4000}  ")
    update = ProjectUpdate(title=f"  {'x' * 120}  ")

    assert len(payload.title) == 120
    assert len(payload.type) == 50
    assert len(payload.audience) == 500
    assert len(payload.summary) == 2000
    assert len(draft_request.description) == 4000
    assert len(update.title or "") == 120
