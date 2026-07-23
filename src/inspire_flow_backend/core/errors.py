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
