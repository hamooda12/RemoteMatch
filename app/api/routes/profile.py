from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.schemas.profile import ProfileResponse, ProfileUpsert
from app.security.authentication import get_current_user
from app.services.profile import ProfileNotFoundError, ProfileService

router = APIRouter(
    prefix="/profile",
    tags=["Profile"],
)

DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("", response_model=ProfileResponse)
async def get_profile(
    current_user: CurrentUser,
    database: DatabaseSession,
) -> ProfileResponse:
    try:
        profile = await ProfileService(database).get_profile(current_user.id)
    except ProfileNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found.",
        ) from error

    return ProfileResponse.model_validate(profile)


@router.put("", response_model=ProfileResponse)
async def upsert_profile(
    payload: ProfileUpsert,
    current_user: CurrentUser,
    database: DatabaseSession,
) -> ProfileResponse:
    profile = await ProfileService(database).upsert_profile(
        current_user.id,
        payload,
    )
    return ProfileResponse.model_validate(profile)
