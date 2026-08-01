from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    UserResponse,
)
from app.security.authentication import get_current_user
from app.services.auth import (
    AuthService,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
)

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)

DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_user(
    payload: RegisterRequest,
    database: DatabaseSession,
) -> User:
    try:
        return await AuthService(database).register(payload)
    except EmailAlreadyRegisteredError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from error


@router.post("/login", response_model=UserResponse)
async def login_user(
    request: Request,
    payload: LoginRequest,
    database: DatabaseSession,
) -> User:
    try:
        user = await AuthService(database).authenticate(payload)
    except InvalidCredentialsError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        ) from error

    request.session.clear()
    request.session["user_id"] = str(user.id)

    return user


@router.post("/logout", response_model=MessageResponse)
async def logout_user(request: Request) -> MessageResponse:
    request.session.clear()
    return MessageResponse(message="Logged out successfully.")


@router.get("/me", response_model=UserResponse)
async def get_authenticated_user(current_user: CurrentUser) -> User:
    return current_user
