from inspire_flow_backend.data.base import Base


def register_models() -> None:
    from inspire_flow_backend.data.models.agent_conversation import AgentConversation
    from inspire_flow_backend.data.models.agent_message import AgentMessage
    from inspire_flow_backend.data.models.auth_session import AuthSession
    from inspire_flow_backend.data.models.brand import (
        BrandFollow,
        BrandInterest,
        BrandInvitation,
        BrandMembership,
        BrandOrganization,
        CreatorInboxItem,
    )
    from inspire_flow_backend.data.models.idempotency import AgentTurnRun, IdempotencyRecord
    from inspire_flow_backend.data.models.inspiration import Inspiration
    from inspire_flow_backend.data.models.project import Project
    from inspire_flow_backend.data.models.transcription_job import TranscriptionJob
    from inspire_flow_backend.data.models.user import User
    from inspire_flow_backend.data.models.user_memory import UserMemory
    from inspire_flow_backend.data.models.user_profile import UserProfile
    from inspire_flow_backend.data.models.workshop import (
        CreatorWorkshop,
        WorkshopBrandAuthorization,
        WorkshopContact,
        WorkshopProjectSelection,
        WorkshopPublication,
        WorkshopPublicationContact,
        WorkshopPublicationProjectCard,
        WorkshopPublicationSocialAccount,
        WorkshopSocialAccount,
    )

    assert {
        AgentConversation.__tablename__,
        AgentMessage.__tablename__,
        AgentTurnRun.__tablename__,
        AuthSession.__tablename__,
        BrandFollow.__tablename__,
        BrandInterest.__tablename__,
        BrandInvitation.__tablename__,
        BrandMembership.__tablename__,
        BrandOrganization.__tablename__,
        CreatorInboxItem.__tablename__,
        CreatorWorkshop.__tablename__,
        IdempotencyRecord.__tablename__,
        Inspiration.__tablename__,
        Project.__tablename__,
        TranscriptionJob.__tablename__,
        User.__tablename__,
        UserMemory.__tablename__,
        UserProfile.__tablename__,
        WorkshopBrandAuthorization.__tablename__,
        WorkshopContact.__tablename__,
        WorkshopProjectSelection.__tablename__,
        WorkshopPublication.__tablename__,
        WorkshopPublicationContact.__tablename__,
        WorkshopPublicationProjectCard.__tablename__,
        WorkshopPublicationSocialAccount.__tablename__,
        WorkshopSocialAccount.__tablename__,
        "inspiration_projects",
    } <= set(Base.metadata.tables)
