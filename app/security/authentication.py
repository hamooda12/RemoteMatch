from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.repositories.user import UserRepository

DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


def authentication_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
    )


async def get_current_user(
    request: Request,
    database: DatabaseSession,
) -> User:
    session_user_id = request.session.get("user_id")

    if not isinstance(session_user_id, str):
        raise authentication_required()

    try:
        user_id = UUID(session_user_id)
    except ValueError:
        raise authentication_required() from None

    user = await UserRepository(database).get_by_id(user_id)

    if user is None:
        request.session.clear()
        raise authentication_required()

    return user
