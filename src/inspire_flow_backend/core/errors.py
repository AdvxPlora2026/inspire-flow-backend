from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


class ApplicationError(Exception):
    status_code = 500
    code = "application_error"
    message = "The request could not be completed"
    headers: dict[str, str] | None = None


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
        headers=exc.headers,
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
    application.add_exception_handler(ApplicationError, handle_application_error)
    application.add_exception_handler(
        RequestValidationError,
        handle_request_validation_error,
    )
    application.add_exception_handler(HTTPException, handle_http_exception)
