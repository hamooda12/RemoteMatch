from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import Profile


class ProfileRepository:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def get_by_user_id(self, user_id: UUID) -> Profile | None:
        return await self.database.get(Profile, user_id)

    async def create(
        self,
        *,
        user_id: UUID,
        values: dict[str, object],
    ) -> Profile:
        profile = Profile(user_id=user_id, **values)
        self.database.add(profile)
        return profile

    @staticmethod
    def update(
        profile: Profile,
        values: dict[str, object],
    ) -> Profile:
        for field_name, value in values.items():
            setattr(profile, field_name, value)

        return profile
