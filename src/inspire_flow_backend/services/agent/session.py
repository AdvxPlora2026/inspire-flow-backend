from uuid import UUID

from agents import TResponseInputItem
from sqlalchemy.orm import Session

from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.agent_conversation import AgentConversation
from inspire_flow_backend.data.models.agent_message import AgentMessage
from inspire_flow_backend.data.repositories.conversations import get_conversation
from inspire_flow_backend.data.repositories.messages import (
    add_messages,
    delete_all_messages,
    delete_message,
    get_latest_message,
    list_messages_after,
)
from inspire_flow_backend.services.agent.session_items import (
    item_type_and_role,
    normalize_session_item,
    restore_session_item,
)


class ConversationSessionStateError(RuntimeError):
    pass


class DatabaseAgentSession:
    session_settings = None

    def __init__(
        self,
        *,
        db: Session,
        user_id: UUID,
        conversation_id: UUID,
        turn_id: UUID,
        run_id: UUID,
        cipher: ContextCipher,
    ) -> None:
        self._db = db
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.turn_id = turn_id
        self.run_id = run_id
        self._cipher = cipher
        self.session_id = str(conversation_id)

    async def get_items(
        self,
        limit: int | None = None,
    ) -> list[TResponseInputItem]:
        conversation = self._require_conversation()
        if limit is not None and limit <= 0:
            return []
        messages = list_messages_after(
            self._db,
            self.conversation_id,
            sequence=conversation.summary_through_sequence,
            limit=limit,
        )
        return [
            restore_session_item(self._cipher.decrypt_json(message.payload_ciphertext))
            for message in messages
        ]

    async def add_items(self, items: list[TResponseInputItem]) -> None:
        conversation = self._require_conversation()
        if not items:
            return

        normalized_items = [normalize_session_item(item) for item in items]
        first_sequence = conversation.next_sequence
        now = utc_now()
        messages: list[AgentMessage] = []
        for offset, item in enumerate(normalized_items):
            item_type, role = item_type_and_role(item)
            messages.append(
                AgentMessage(
                    conversation_id=self.conversation_id,
                    turn_id=self.turn_id,
                    sequence=first_sequence + offset,
                    item_type=item_type,
                    role=role,
                    payload_ciphertext=self._cipher.encrypt_json(item),
                    created_at=now,
                )
            )

        conversation.next_sequence = first_sequence + len(messages)
        conversation.updated_at = now
        add_messages(self._db, messages)
        self._db.commit()

    async def pop_item(self) -> TResponseInputItem | None:
        conversation = self._require_conversation()
        message = get_latest_message(self._db, self.conversation_id)
        if message is None:
            return None

        item = restore_session_item(self._cipher.decrypt_json(message.payload_ciphertext))
        delete_message(self._db, message)
        conversation.next_sequence = message.sequence
        if conversation.summary_through_sequence >= message.sequence:
            conversation.summary_ciphertext = None
            conversation.summary_through_sequence = 0
            conversation.summary_updated_at = None
        conversation.updated_at = utc_now()
        self._db.commit()
        return item

    async def clear_session(self) -> None:
        conversation = self._require_conversation()
        delete_all_messages(self._db, self.conversation_id)
        conversation.summary_ciphertext = None
        conversation.summary_through_sequence = 0
        conversation.summary_updated_at = None
        conversation.next_sequence = 1
        conversation.updated_at = utc_now()
        self._db.commit()

    def _require_conversation(self) -> AgentConversation:
        conversation = get_conversation(
            self._db,
            self.user_id,
            self.conversation_id,
        )
        if conversation is None or conversation.active_run_id != self.run_id:
            raise ConversationSessionStateError(
                "Conversation ownership or active run does not match"
            )
        return conversation
