from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import Profile
from app.repositories.profile import ProfileRepository
from app.schemas.profile import ProfileUpsert


class ProfileNotFoundError(Exception):
    """Raised when a user profile does not exist."""


class ProfileService:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database
        self.profiles = ProfileRepository(database)

    async def get_profile(self, user_id: UUID) -> Profile:
        profile = await self.profiles.get_by_user_id(user_id)

        if profile is None:
            raise ProfileNotFoundError

        return profile

    async def upsert_profile(
        self,
        user_id: UUID,
        payload: ProfileUpsert,
    ) -> Profile:
        values = self._profile_values(payload)
        profile = await self.profiles.get_by_user_id(user_id)

        if profile is None:
            profile = await self.profiles.create(
                user_id=user_id,
                values=values,
            )
        else:
            profile = self.profiles.update(profile, values)

        await self.database.commit()
        await self.database.refresh(profile)

        return profile

    @staticmethod
    def _profile_values(payload: ProfileUpsert) -> dict[str, object]:
        values: dict[str, object] = payload.model_dump()

        if payload.experience_level is not None:
            values["experience_level"] = payload.experience_level.value

        return values
