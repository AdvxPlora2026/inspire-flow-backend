import asyncio
from collections.abc import Generator
from uuid import uuid4

import httpx
import pytest
from agents import ModelBehaviorError
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.core.errors import (
    AgentRunFailedError,
    BrandNotFoundError,
    ProjectNotFoundError,
)
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.base import Base
from inspire_flow_backend.data.database import create_database_engine
from inspire_flow_backend.data.model_registry import register_models
from inspire_flow_backend.data.models.brand import BrandMembership
from inspire_flow_backend.data.models.user import User
from inspire_flow_backend.schemas.advisory import (
    BrandAdvisoryContext,
    BrandAdvisoryDraft,
    BrandAdvisoryRequest,
)
from inspire_flow_backend.schemas.brands import BrandCreate
from inspire_flow_backend.schemas.projects import ProjectCreate
from inspire_flow_backend.services import advisory as advisory_service
from inspire_flow_backend.services import brands as brand_service
from inspire_flow_backend.services import projects as project_service
from inspire_flow_backend.services.agent.brand_advisor import finalize_advisory_report


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


class CapturingAdvisor:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.contexts: list[BrandAdvisoryContext] = []

    async def analyze(self, context: BrandAdvisoryContext):
        assert self.db.in_transaction() is False
        self.contexts.append(context)
        return finalize_advisory_report(
            context=context,
            draft=BrandAdvisoryDraft(
                caveats=["证据不足"],
                next_research_steps=["补充行业来源"],
            ),
            run_items=[],
            generated_at=utc_now(),
        )


class FailingAdvisor:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def analyze(self, context: BrandAdvisoryContext):
        del context
        raise self.error


def create_brand_and_project(db: Session):
    owner = add_user(db, "advisor-owner")
    member = add_user(db, "advisor-member")
    outsider = add_user(db, "advisor-outsider")
    brand = brand_service.create_brand(
        db,
        owner.id,
        BrandCreate(
            name="星河咖啡",
            description="面向年轻职场人的即饮咖啡",
            website_url="https://brand.example.com",
        ),
    )
    db.add(BrandMembership(brand_id=brand.id, user_id=member.id, role="member"))
    project = project_service.create_project(
        db,
        owner.id,
        ProjectCreate(
            title="冷萃新品内容",
            type="品牌合作",
            audience="年轻职场人",
            summary="测试不同职场场景",
        ),
    )
    db.commit()
    return owner, member, outsider, brand, project


def test_owner_and_member_can_request_read_only_advice_with_explicit_brief_precedence(
    db: Session,
) -> None:
    owner, member, _, brand, project = create_brand_and_project(db)
    advisor = CapturingAdvisor(db)
    payload = BrandAdvisoryRequest(
        project_brief="以通勤后的上午工作场景为主，覆盖项目摘要中的泛场景要求",
        project_id=project.id,
        market="中国大陆",
        focus_topics=["职场效率"],
    )

    owner_report = asyncio.run(
        advisory_service.analyze_brand_project(db, owner.id, brand.id, payload, advisor)
    )
    member_report = asyncio.run(
        advisory_service.analyze_brand_project(
            db,
            member.id,
            brand.id,
            BrandAdvisoryRequest(project_brief="成员自己的品牌项目 brief"),
            advisor,
        )
    )

    assert owner_report.brand.id == brand.id
    assert member_report.brand.id == brand.id
    first_context = advisor.contexts[0]
    assert first_context.project.brief.startswith("以通勤后的上午工作场景为主")
    assert first_context.project.linked_project is not None
    assert first_context.project.linked_project.summary == "测试不同职场场景"
    assert list(db.new) == []
    assert list(db.deleted) == []


def test_advisory_hides_inaccessible_brand_and_project(db: Session) -> None:
    owner, member, outsider, brand, project = create_brand_and_project(db)
    advisor = CapturingAdvisor(db)

    with pytest.raises(BrandNotFoundError):
        asyncio.run(
            advisory_service.analyze_brand_project(
                db,
                outsider.id,
                brand.id,
                BrandAdvisoryRequest(project_brief="brief"),
                advisor,
            )
        )
    with pytest.raises(BrandNotFoundError):
        asyncio.run(
            advisory_service.analyze_brand_project(
                db,
                owner.id,
                uuid4(),
                BrandAdvisoryRequest(project_brief="brief"),
                advisor,
            )
        )
    with pytest.raises(ProjectNotFoundError):
        asyncio.run(
            advisory_service.analyze_brand_project(
                db,
                member.id,
                brand.id,
                BrandAdvisoryRequest(project_brief="brief", project_id=project.id),
                advisor,
            )
        )


@pytest.mark.parametrize(
    "error",
    [
        ModelBehaviorError("malformed model output"),
        httpx.ConnectError("provider unavailable"),
    ],
)
def test_advisory_maps_expected_provider_failures(db: Session, error: Exception) -> None:
    owner, _, _, brand, _ = create_brand_and_project(db)

    with pytest.raises(AgentRunFailedError):
        asyncio.run(
            advisory_service.analyze_brand_project(
                db,
                owner.id,
                brand.id,
                BrandAdvisoryRequest(project_brief="brief"),
                FailingAdvisor(error),
            )
        )


def test_advisory_does_not_hide_programming_defects(db: Session) -> None:
    owner, _, _, brand, _ = create_brand_and_project(db)

    with pytest.raises(RuntimeError, match="programming defect"):
        asyncio.run(
            advisory_service.analyze_brand_project(
                db,
                owner.id,
                brand.id,
                BrandAdvisoryRequest(project_brief="brief"),
                FailingAdvisor(RuntimeError("programming defect")),
            )
        )
