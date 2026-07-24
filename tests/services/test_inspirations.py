from collections.abc import Generator
from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.base import Base
from inspire_flow_backend.data.database import create_database_engine
from inspire_flow_backend.data.model_registry import register_models
from inspire_flow_backend.data.models.agent_conversation import AgentConversation
from inspire_flow_backend.data.models.agent_message import AgentMessage
from inspire_flow_backend.data.models.project import Project
from inspire_flow_backend.data.models.user import User


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


def feature() -> SimpleNamespace:
    try:
        schemas = import_module("inspire_flow_backend.schemas.inspirations")
        services = import_module("inspire_flow_backend.services.inspirations")
        errors = import_module("inspire_flow_backend.core.errors")
    except (ImportError, AttributeError) as exc:
        pytest.fail(f"Inspiration service contract is not implemented: {exc}")
    return SimpleNamespace(schemas=schemas, services=services, errors=errors)


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


def add_project(db: Session, user: User, title: str) -> Project:
    now = utc_now()
    project = Project(
        user_id=user.id,
        title=title,
        type="知识",
        audience="创作者",
        summary=f"{title}简介",
        created_at=now,
        updated_at=now,
    )
    db.add(project)
    db.commit()
    return project


def test_inspiration_lifecycle_supports_multiple_projects_and_user_isolation(
    db: Session,
) -> None:
    modules = feature()
    owner = add_user(db, "owner")
    other = add_user(db, "other")
    first_project = add_project(db, owner, "第一期")
    second_project = add_project(db, owner, "第二期")

    created = modules.services.create_inspiration(
        db,
        owner.id,
        modules.schemas.InspirationCreate(
            title="  MPS 实测  ",
            content="  对比 MPS 和 CPU 的转写速度  ",
            project_ids=[first_project.id, second_project.id],
        ),
    )

    assert created.title == "MPS 实测"
    assert created.content == "对比 MPS 和 CPU 的转写速度"
    assert created.status == "inbox"
    assert created.source_type == "manual"
    assert {project.id for project in created.projects} == {
        first_project.id,
        second_project.id,
    }
    assert (
        modules.services.list_inspirations(
            db,
            owner.id,
            limit=20,
            offset=0,
        ).total
        == 1
    )
    assert (
        modules.services.list_inspirations(
            db,
            other.id,
            limit=20,
            offset=0,
        ).total
        == 0
    )
    with pytest.raises(modules.errors.InspirationNotFoundError):
        modules.services.get_inspiration(db, other.id, created.id)

    modules.services.delete_inspiration(db, owner.id, created.id)
    with pytest.raises(modules.errors.InspirationNotFoundError):
        modules.services.get_inspiration(db, owner.id, created.id)


def test_inspiration_project_replacement_is_atomic_and_incremental_links_are_idempotent(
    db: Session,
) -> None:
    modules = feature()
    owner = add_user(db, "owner")
    other = add_user(db, "other")
    first_project = add_project(db, owner, "第一期")
    second_project = add_project(db, owner, "第二期")
    foreign_project = add_project(db, other, "外部项目")
    created = modules.services.create_inspiration(
        db,
        owner.id,
        modules.schemas.InspirationCreate(
            content="一个待整理的灵感",
            project_ids=[first_project.id],
        ),
    )

    modules.services.add_project_link(
        db,
        owner.id,
        created.id,
        second_project.id,
    )
    modules.services.add_project_link(
        db,
        owner.id,
        created.id,
        second_project.id,
    )
    assert {project.id for project in created.projects} == {
        first_project.id,
        second_project.id,
    }

    with pytest.raises(modules.errors.ProjectNotFoundError):
        modules.services.update_inspiration(
            db,
            owner.id,
            created.id,
            modules.schemas.InspirationUpdate(project_ids=[second_project.id, foreign_project.id]),
        )
    db.refresh(created)
    assert {project.id for project in created.projects} == {
        first_project.id,
        second_project.id,
    }

    modules.services.remove_project_link(
        db,
        owner.id,
        created.id,
        first_project.id,
    )
    modules.services.remove_project_link(
        db,
        owner.id,
        created.id,
        first_project.id,
    )
    assert [project.id for project in created.projects] == [second_project.id]


def test_inspiration_list_filters_searches_sorts_and_paginates(db: Session) -> None:
    modules = feature()
    owner = add_user(db, "owner")
    project = add_project(db, owner, "MPS 系列")
    first = modules.services.create_inspiration(
        db,
        owner.id,
        modules.schemas.InspirationCreate(
            title="本地转写",
            content="测试中文关键词",
            source_type="voice",
            project_ids=[project.id],
        ),
    )
    second = modules.services.create_inspiration(
        db,
        owner.id,
        modules.schemas.InspirationCreate(
            title="拍摄清单",
            content="准备灯光和麦克风",
        ),
    )
    modules.services.update_inspiration(
        db,
        owner.id,
        first.id,
        modules.schemas.InspirationUpdate(status="developing"),
    )

    filtered = modules.services.list_inspirations(
        db,
        owner.id,
        project_id=project.id,
        status="developing",
        source_type="voice",
        query="中文",
        sort_by="created_at",
        sort_order="asc",
        limit=1,
        offset=0,
    )
    latest = modules.services.list_inspirations(
        db,
        owner.id,
        limit=1,
        offset=0,
    )
    later = modules.services.list_inspirations(
        db,
        owner.id,
        limit=1,
        offset=1,
    )

    assert filtered.total == 1
    assert [item.id for item in filtered.items] == [first.id]
    assert latest.total == 2
    assert [item.id for item in latest.items] == [first.id]
    assert [item.id for item in later.items] == [second.id]


def test_non_inbox_inspiration_requires_a_project_or_source(db: Session) -> None:
    modules = feature()
    owner = add_user(db, "owner")

    with pytest.raises(modules.errors.InspirationAssociationRequiredError):
        modules.services.create_inspiration(
            db,
            owner.id,
            modules.schemas.InspirationCreate(
                content="没有归属却标记为推进中",
                status="developing",
            ),
        )

    created = modules.services.create_inspiration(
        db,
        owner.id,
        modules.schemas.InspirationCreate(content="收件箱灵感"),
    )
    with pytest.raises(modules.errors.InspirationAssociationRequiredError):
        modules.services.update_inspiration(
            db,
            owner.id,
            created.id,
            modules.schemas.InspirationUpdate(status="converted"),
        )


def test_no_op_patch_preserves_inspiration_updated_at(db: Session) -> None:
    modules = feature()
    owner = add_user(db, "owner")
    created = modules.services.create_inspiration(
        db,
        owner.id,
        modules.schemas.InspirationCreate(
            title="灵感",
            content="正文",
        ),
    )
    before = created.updated_at

    updated = modules.services.update_inspiration(
        db,
        owner.id,
        created.id,
        modules.schemas.InspirationUpdate(
            title=" 灵感 ",
            content=" 正文 ",
            project_ids=[],
        ),
    )

    assert updated.updated_at == before


def test_project_delete_requires_confirmation_before_removing_orphaned_inspirations(
    db: Session,
) -> None:
    modules = feature()
    project_services = import_module("inspire_flow_backend.services.projects")
    owner = add_user(db, "delete-owner")
    project = add_project(db, owner, "待删除项目")
    inspiration = modules.services.create_inspiration(
        db,
        owner.id,
        modules.schemas.InspirationCreate(
            title="会变成孤立数据",
            content="只关联这一个项目",
            project_ids=[project.id],
        ),
    )

    with pytest.raises(modules.errors.OrphanedInspirationsConfirmationRequiredError) as captured:
        project_services.delete_project(db, owner.id, project.id)

    assert captured.value.details == [{"id": str(inspiration.id), "title": "会变成孤立数据"}]
    assert db.get(Project, project.id) is not None
    assert modules.services.get_inspiration(db, owner.id, inspiration.id)

    project_services.delete_project(
        db,
        owner.id,
        project.id,
        delete_orphan_inspirations=True,
    )

    assert db.get(Project, project.id) is None
    with pytest.raises(modules.errors.InspirationNotFoundError):
        modules.services.get_inspiration(db, owner.id, inspiration.id)


def test_project_delete_keeps_inspiration_with_another_project(db: Session) -> None:
    modules = feature()
    project_services = import_module("inspire_flow_backend.services.projects")
    owner = add_user(db, "delete-linked-owner")
    deleted_project = add_project(db, owner, "待删除项目")
    surviving_project = add_project(db, owner, "保留项目")
    inspiration = modules.services.create_inspiration(
        db,
        owner.id,
        modules.schemas.InspirationCreate(
            content="仍然有归属",
            project_ids=[deleted_project.id, surviving_project.id],
        ),
    )

    project_services.delete_project(db, owner.id, deleted_project.id)

    retained = modules.services.get_inspiration(db, owner.id, inspiration.id)
    assert [project.id for project in retained.projects] == [surviving_project.id]


def test_conversation_delete_requires_confirmation_for_source_only_inspiration(
    db: Session,
) -> None:
    modules = feature()
    conversation_services = import_module("inspire_flow_backend.services.conversations")
    owner = add_user(db, "conversation-delete-owner")
    now = utc_now()
    conversation = AgentConversation(
        user_id=owner.id,
        title="来源对话",
        summary_through_sequence=0,
        next_sequence=2,
        created_at=now,
        updated_at=now,
    )
    message = AgentMessage(
        conversation=conversation,
        turn_id=uuid4(),
        sequence=1,
        item_type="message",
        role="user",
        payload_ciphertext="encrypted-test-payload",
        created_at=now,
    )
    db.add_all([conversation, message])
    db.commit()
    inspiration = modules.services.create_inspiration(
        db,
        owner.id,
        modules.schemas.InspirationCreate(
            title="来自对话",
            content="只通过对话追溯",
        ),
        source_type=modules.schemas.InspirationSourceType.agent,
        source_conversation_id=conversation.id,
        source_message_id=message.id,
    )

    with pytest.raises(modules.errors.OrphanedInspirationsConfirmationRequiredError):
        conversation_services.delete_conversation(
            db,
            owner.id,
            conversation.id,
        )

    assert db.get(AgentConversation, conversation.id) is not None
    conversation_services.delete_conversation(
        db,
        owner.id,
        conversation.id,
        delete_orphan_inspirations=True,
    )

    assert db.get(AgentConversation, conversation.id) is None
    with pytest.raises(modules.errors.InspirationNotFoundError):
        modules.services.get_inspiration(db, owner.id, inspiration.id)


def test_inspiration_source_must_belong_to_the_same_user_and_conversation(
    db: Session,
) -> None:
    modules = feature()
    owner = add_user(db, "source-owner")
    other = add_user(db, "source-other")
    now = utc_now()
    foreign_conversation = AgentConversation(
        user_id=other.id,
        title="其他用户对话",
        summary_through_sequence=0,
        next_sequence=2,
        created_at=now,
        updated_at=now,
    )
    foreign_message = AgentMessage(
        conversation=foreign_conversation,
        turn_id=uuid4(),
        sequence=1,
        item_type="message",
        role="user",
        payload_ciphertext="encrypted-test-payload",
        created_at=now,
    )
    db.add_all([foreign_conversation, foreign_message])
    db.commit()

    with pytest.raises(modules.errors.ConversationNotFoundError):
        modules.services.create_inspiration(
            db,
            owner.id,
            modules.schemas.InspirationCreate(content="伪造来源"),
            source_type=modules.schemas.InspirationSourceType.agent,
            source_conversation_id=foreign_conversation.id,
            source_message_id=foreign_message.id,
        )

    assert (
        modules.services.list_inspirations(
            db,
            owner.id,
            limit=20,
            offset=0,
        ).total
        == 0
    )
