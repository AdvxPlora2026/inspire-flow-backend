import json

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException
from starlette.responses import Response


class ApplicationError(Exception):
    status_code = 500
    code = "application_error"
    message = "The request could not be completed"
    headers: dict[str, str] | None = None
    details: list[dict[str, object]] | None = None

    def __init__(
        self,
        *,
        message: str | None = None,
        details: list[dict[str, object]] | None = None,
    ) -> None:
        if message is not None:
            self.message = message
        self.details = details
        super().__init__(self.message)


class NicknameConflictError(ApplicationError):
    status_code = 409
    code = "nickname_conflict"
    message = "Nickname is already in use"


class InvalidCredentialsError(ApplicationError):
    status_code = 401
    code = "invalid_credentials"
    message = "Invalid nickname or password"


class InvalidSessionError(ApplicationError):
    status_code = 401
    code = "invalid_session"
    message = "A valid bearer session is required"
    headers = {"WWW-Authenticate": "Bearer"}


class IdempotencyKeyRequiredError(ApplicationError):
    status_code = 400
    code = "idempotency_key_required"
    message = "Idempotency-Key is required for authenticated write requests"


class IdempotencyKeyConflictError(ApplicationError):
    status_code = 409
    code = "idempotency_key_conflict"
    message = "Idempotency-Key was already used with a different request"


class IdempotencyRequestInProgressError(ApplicationError):
    status_code = 409
    code = "idempotency_request_in_progress"
    message = "A request with this Idempotency-Key is still in progress"


class IdempotencyOutcomeUnknownError(ApplicationError):
    status_code = 409
    code = "idempotency_outcome_unknown"
    message = "The previous request outcome is unknown; retry with a new Idempotency-Key"


class BrandNotFoundError(ApplicationError):
    status_code = 404
    code = "brand_not_found"
    message = "Brand was not found"


class BrandOwnerRequiredError(ApplicationError):
    status_code = 403
    code = "brand_owner_required"
    message = "Brand owner permission is required"


class BrandLastOwnerRequiredError(ApplicationError):
    status_code = 409
    code = "brand_last_owner_required"
    message = "A brand must keep at least one owner"


class BrandInvitationNotFoundError(ApplicationError):
    status_code = 404
    code = "brand_invitation_not_found"
    message = "Brand invitation was not found"


class BrandInvitationStateConflictError(ApplicationError):
    status_code = 409
    code = "brand_invitation_state_conflict"
    message = "Brand invitation is no longer pending"


class InvitationUserNotFoundError(ApplicationError):
    status_code = 404
    code = "invitation_user_not_found"
    message = "Invitation user was not found"


class WorkshopNotFoundError(ApplicationError):
    status_code = 404
    code = "workshop_not_found"
    message = "Workshop was not found"


class WorkshopNotPublishedError(ApplicationError):
    status_code = 404
    code = "workshop_not_published"
    message = "Workshop is not published"


class WorkshopVisibilityForbiddenError(ApplicationError):
    status_code = 403
    code = "workshop_visibility_forbidden"
    message = "Workshop field is not visible to this audience"


class WorkshopItemNotFoundError(ApplicationError):
    status_code = 404
    code = "workshop_item_not_found"
    message = "Workshop item was not found"


class InvalidWorkshopContactError(ApplicationError):
    status_code = 422
    code = "invalid_workshop_contact"
    message = "Workshop contact value is invalid"


class BrandAuthorizationNotFoundError(ApplicationError):
    status_code = 404
    code = "brand_authorization_not_found"
    message = "Brand authorization was not found"


class BrandInterestNotFoundError(ApplicationError):
    status_code = 404
    code = "brand_interest_not_found"
    message = "Brand interest was not found"


class BrandInterestStateConflictError(ApplicationError):
    status_code = 409
    code = "brand_interest_state_conflict"
    message = "Brand interest is no longer pending"


class CreatorInboxItemNotFoundError(ApplicationError):
    status_code = 404
    code = "creator_inbox_item_not_found"
    message = "Creator inbox item was not found"


class IdempotencyReplay(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        body: object,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}
        super().__init__("idempotency replay")


class ContextStorageUnavailableError(ApplicationError):
    status_code = 503
    code = "context_storage_unavailable"
    message = "Encrypted context storage is unavailable"


class MemoryNotFoundError(ApplicationError):
    status_code = 404
    code = "memory_not_found"
    message = "Memory was not found"


class CredentialMemoryForbiddenError(ApplicationError):
    status_code = 422
    code = "credential_memory_forbidden"
    message = "Credentials cannot be stored as memory"


class ConversationNotFoundError(ApplicationError):
    status_code = 404
    code = "conversation_not_found"
    message = "Conversation was not found"


class ConversationArchivedError(ApplicationError):
    status_code = 409
    code = "conversation_archived"
    message = "Conversation is archived"


class ConversationBusyError(ApplicationError):
    status_code = 409
    code = "conversation_busy"
    message = "Conversation already has an active run"


class AgentUnavailableError(ApplicationError):
    status_code = 503
    code = "agent_unavailable"
    message = "Agent model configuration is unavailable"


class AgentRunFailedError(ApplicationError):
    status_code = 502
    code = "agent_run_failed"
    message = "Agent could not complete the requested turn"


class SttUnavailableError(ApplicationError):
    status_code = 503
    code = "stt_unavailable"
    message = "Speech transcription is unavailable"


class AudioTooLargeError(ApplicationError):
    status_code = 413
    code = "audio_too_large"
    message = "Audio upload exceeds the configured size limit"


class UnsupportedAudioTypeError(ApplicationError):
    status_code = 415
    code = "unsupported_audio_type"
    message = "Audio format is not supported"


class TranscriptionNotFoundError(ApplicationError):
    status_code = 404
    code = "transcription_not_found"
    message = "Transcription job was not found"


class ProjectNotFoundError(ApplicationError):
    status_code = 404
    code = "project_not_found"
    message = "Project was not found"


class InspirationNotFoundError(ApplicationError):
    status_code = 404
    code = "inspiration_not_found"
    message = "Inspiration was not found"


class InspirationAssociationRequiredError(ApplicationError):
    status_code = 409
    code = "inspiration_association_required"
    message = "A non-inbox inspiration requires a project or source"


class OrphanedInspirationsConfirmationRequiredError(ApplicationError):
    status_code = 409
    code = "orphaned_inspirations_confirmation_required"
    message = "Deleting this resource would orphan inspirations"

    def __init__(self, details: list[dict[str, object]]) -> None:
        super().__init__(
            message=(f"Deleting this resource would orphan {len(details)} inspiration(s)"),
            details=details[:100],
        )


class CommercialTaskNotFoundError(ApplicationError):
    status_code = 404
    code = "commercial_task_not_found"
    message = "Commercial task was not found"


class SequenceConflictError(ApplicationError):
    status_code = 409
    code = "sequence_conflict"
    message = "The requested action is out of order for this commercial task"


class InjectiveUnavailableError(ApplicationError):
    status_code = 503
    code = "injective_unavailable"
    message = "Injective chain integration is not configured or unavailable"


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, object]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, object] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return JSONResponse(
        status_code=status_code,
        content={"error": body},
        headers=headers,
    )


async def handle_application_error(
    request: Request,
    exc: ApplicationError,
) -> JSONResponse:
    del request
    return error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
        headers=exc.headers,
    )


async def handle_idempotency_replay(
    request: Request,
    exc: IdempotencyReplay,
) -> JSONResponse | StreamingResponse | Response:
    if request.url.path.endswith("/messages/stream") and isinstance(exc.body, dict):
        events = exc.body.get("events")
        if isinstance(events, list):

            async def replay_events():
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    event_name = str(event.get("event", "turn.completed"))
                    data = event.get("data", {})
                    yield (
                        f"event: {event_name}\n"
                        f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"
                    )

            return StreamingResponse(
                replay_events(),
                status_code=exc.status_code,
                media_type="text/event-stream",
                headers={**exc.headers, "Idempotency-Replayed": "true"},
            )
    if exc.status_code == 204:
        return Response(
            status_code=204,
            headers={**exc.headers, "Idempotency-Replayed": "true"},
        )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.body,
        headers={**exc.headers, "Idempotency-Replayed": "true"},
    )


async def handle_request_validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    del request
    details = [
        {
            "location": list(error["loc"]),
            "message": str(error["msg"]),
            "type": str(error["type"]),
        }
        for error in exc.errors()
    ]
    return error_response(
        status_code=422,
        code="validation_error",
        message="Request validation failed",
        details=details,
    )


async def handle_http_exception(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
    del request
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return error_response(
        status_code=exc.status_code,
        code="http_error",
        message=message,
        headers=exc.headers,
    )


def register_error_handlers(application: FastAPI) -> None:
    application.add_exception_handler(IdempotencyReplay, handle_idempotency_replay)
    application.add_exception_handler(ApplicationError, handle_application_error)
    application.add_exception_handler(
        RequestValidationError,
        handle_request_validation_error,
    )
    application.add_exception_handler(HTTPException, handle_http_exception)
