from inspire_flow_backend.data.base import Base


def register_models() -> None:
    from inspire_flow_backend.data.models.agent_conversation import AgentConversation
    from inspire_flow_backend.data.models.agent_message import AgentMessage
    from inspire_flow_backend.data.models.auth_session import AuthSession
    from inspire_flow_backend.data.models.project import Project
    from inspire_flow_backend.data.models.transcription_job import TranscriptionJob
    from inspire_flow_backend.data.models.user import User
    from inspire_flow_backend.data.models.user_memory import UserMemory
    from inspire_flow_backend.data.models.user_profile import UserProfile

    assert {
        AgentConversation.__tablename__,
        AgentMessage.__tablename__,
        AuthSession.__tablename__,
        Project.__tablename__,
        TranscriptionJob.__tablename__,
        User.__tablename__,
        UserMemory.__tablename__,
        UserProfile.__tablename__,
    } <= set(Base.metadata.tables)
