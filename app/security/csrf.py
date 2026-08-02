import secrets

from fastapi import HTTPException, Request, status

CSRF_SESSION_KEY = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"


def issue_csrf_token(request: Request) -> str:
    token = secrets.token_urlsafe(32)
    request.session[CSRF_SESSION_KEY] = token
    return token


def get_or_create_csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)

    if isinstance(token, str) and token:
        return token

    return issue_csrf_token(request)


async def verify_csrf_token(request: Request) -> None:
    expected_token = request.session.get(CSRF_SESSION_KEY)
    supplied_token = request.headers.get(CSRF_HEADER_NAME)

    if (
        not isinstance(expected_token, str)
        or not isinstance(supplied_token, str)
        or not secrets.compare_digest(expected_token, supplied_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing CSRF token.",
        )
